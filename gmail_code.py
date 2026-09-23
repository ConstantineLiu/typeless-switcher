#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
[INPUT]: 系统 python3 标准库 (imaplib/email/re/subprocess); Keychain 里的 Gmail 应用专用密码
[OUTPUT]: 从 Gmail 收件箱提取 Typeless 登录验证码, 复制到剪贴板并弹通知; watch_codes 生成器供 web_login.py 复用
[POS]: typeless-reset-device 的取码模块, 被 web_login.py 导入, 也可单独运行
[PROTOCOL]: 变更时更新此头部

Typeless Gmail 验证码取码器

实测邮件样本 (2026-09-17):
    From: Typeless Team <no-reply@typeless.com>
    Subject: Your Typeless verification code
    结构: multipart/alternative (text/plain + text/html)
    正文: "Your secret verification code: 493159"  ← 6 位数字

原理:
    Typeless 登录/注册时向邮箱发验证码邮件。Gmail 忽略地址中的点,
    所以 you / y.ou / y.o.u@gmail.com ... 全部落到
    同一个收件箱, 本工具只需监听这一个盒子。

健壮性:
    - 连接/命令均带 30s 超时 (IMAP4_SSL timeout)
    - 连接失败指数退避重试 (2s → 4s → 8s, 共 3 次)
    - watch 轮询断线自动重连 (1s 起, 翻倍, 上限 60s; 连续 6 次失败放弃)
    - 单封邮件解析失败不影响其他邮件
    - watch 有总超时兜底 (默认 900s), 防止挂在后台不退出

凭据:
    Gmail 应用专用密码存在 macOS Keychain 里(不落明文文件):
        security add-generic-password \\
          -s "typeless-reset-gmail" \\
          -a "you@gmail.com" \\
          -w "<16位应用密码>"

用法:
    python3 gmail_code.py                  # 取最近 1 天内最新验证码
    python3 gmail_code.py --days 7        # 放宽到 7 天
    python3 gmail_code.py --watch         # 持续监听新验证码(集成在 reset-and-migrate.sh)
    python3 gmail_code.py --watch --timeout 1800
    必须设置环境变量 GMAIL_USER=you@gmail.com (reset-and-migrate.sh 会自动从当前账号推出)
"""

import argparse
import email
import email.policy
import imaplib
import os
import re
import subprocess
import sys
import time
from datetime import date, timedelta

GMAIL_USER = os.environ.get("GMAIL_USER", "")
KEYCHAIN_SERVICE = "typeless-reset-gmail"
IMAP_HOST = "imap.gmail.com"

POLL_SEC = 5            # watch 轮询间隔
CONN_TIMEOUT_SEC = 30   # 单次 IMAP 连接/命令超时
CONNECT_ATTEMPTS = 3    # 首次连接重试次数
CONNECT_BACKOFF_SEC = 2 # 首次连接退避起步值
RECONNECT_BACKOFF_SEC = 1  # watch 断线重连退避起步值
RECONNECT_BACKOFF_MAX = 60
MAX_CONSEC_FAILURES = 6 # watch 连续失败到此次数后放弃
DEFAULT_DAYS = 1        # 默认只看最近 1 天, 避免捞到过期旧码
DEFAULT_WATCH_TIMEOUT = 900


# ---------------------------------------------------------------- 凭据 --
def get_password():
    """从 Keychain 读取应用专用密码, 读不到返回 None。"""
    if not GMAIL_USER:
        raise SystemExit("[gmail-code] 请设置环境变量 GMAIL_USER=you@gmail.com")
    r = subprocess.run(
        ["security", "find-generic-password",
         "-s", KEYCHAIN_SERVICE, "-a", GMAIL_USER, "-w"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return None
    pw = r.stdout.strip()
    return pw or None


def setup_hint():
    print("未找到 Gmail 应用专用密码, 一次性配置步骤:", file=sys.stderr)
    print(f"  1. 确认 {GMAIL_USER} 已开启两步验证 (myaccount.google.com/security)", file=sys.stderr)
    print("  2. 访问 myaccount.google.com/apppasswords 创建应用密码(16位)", file=sys.stderr)
    print("  3. 存入 Keychain:", file=sys.stderr)
    print(f'     security add-generic-password -s "{KEYCHAIN_SERVICE}" '
          f'-a "{GMAIL_USER}" -w "<16位应用密码>"', file=sys.stderr)


# ---------------------------------------------------------------- IMAP --
def connect_once(pw):
    m = imaplib.IMAP4_SSL(IMAP_HOST, 993, timeout=CONN_TIMEOUT_SEC)
    m.login(GMAIL_USER, pw)
    m.select("INBOX")
    return m


def connect(pw, attempts=CONNECT_ATTEMPTS):
    """带指数退避的连接: 2s → 4s → 8s, 全部失败才抛最后一场。"""
    delay = CONNECT_BACKOFF_SEC
    for i in range(attempts):
        try:
            return connect_once(pw)
        except Exception as e:
            if i == attempts - 1:
                raise
            print(f"[gmail-code] 连接失败({e}), {delay}s 后重试 "
                  f"({i + 1}/{attempts})...", file=sys.stderr)
            time.sleep(delay)
            delay = min(delay * 2, 30)


def search_criteria(days):
    since = (date.today() - timedelta(days=days)).strftime("%d-%b-%Y")
    return f'(FROM "typeless" SINCE {since})'


def uid_list(mail, days):
    typ, data = mail.uid("search", None, search_criteria(days))
    if typ != "OK":
        return []
    return data[0].split()


def body_text(msg):
    """取邮件正文: 优先 text/plain, 只有 html 时去标签。解析异常返回空串。"""
    plain, html = [], []
    try:
        if msg.is_multipart():
            for part in msg.walk():
                ct = part.get_content_type()
                if ct == "text/plain":
                    plain.append(part.get_content())
                elif ct == "text/html":
                    html.append(part.get_content())
        else:
            content = msg.get_content()
            (plain if msg.get_content_type() == "text/plain" else html).append(content)
    except Exception:
        pass
    for text in plain:
        if isinstance(text, str) and text.strip():
            return text
    for text in html:
        if isinstance(text, str) and text.strip():
            return re.sub(r"<[^>]+>", " ", text)
    return ""


def extract_code(text):
    """从正文提取验证码: 优先 'code/验证码 ... 数字', 否则取独立 6 位数。"""
    m = re.search(r"(?:code|验证码|passcode)[^0-9\n]{0,40}(\d{4,8})", text, re.I)
    if m:
        return m.group(1)
    codes = re.findall(r"(?<!\d)\d{6}(?!\d)", text)
    return codes[0] if codes else None


def fetch_uid(mail, uid):
    """取单封邮件, 任何异常返回 None, 不拖垮整个循环。"""
    try:
        typ, data = mail.uid("fetch", uid, "(RFC822)")
        if typ != "OK" or not data or not data[0]:
            return None
        return email.message_from_bytes(data[0][1], policy=email.policy.default)
    except Exception:
        return None


# ---------------------------------------------------------------- 输出 --
def deliver(code, subject=""):
    print(code)
    subprocess.run(["pbcopy"], input=code.encode(), check=False)
    subprocess.run(
        ["osascript", "-e",
         f'display notification "验证码 {code} 已复制到剪贴板" '
         f'with title "Typeless 验证码" sound name "Glass"'],
        capture_output=True,
    )
    print(f"[gmail-code] {subject or 'Typeless'} → {code} (已复制)", file=sys.stderr)


# ---------------------------------------------------------------- 模式 --
def run_once(pw, days):
    mail = connect(pw)
    uids = uid_list(mail, days)
    if not uids:
        print(f"[gmail-code] 最近 {days} 天没有 Typeless 邮件", file=sys.stderr)
        mail.logout()
        return 1
    msg = fetch_uid(mail, uids[-1])
    mail.logout()
    if not msg:
        print("[gmail-code] 邮件拉取失败", file=sys.stderr)
        return 1
    code = extract_code(body_text(msg))
    if code:
        deliver(code, str(msg.get("Subject", "")))
        return 0
    print("[gmail-code] 最新邮件里没解析出验证码", file=sys.stderr)
    return 1


class WatchError(RuntimeError):
    """watch 连续轮询失败, 放弃。"""


def watch_codes(pw, days, timeout_sec):
    """立刻连接并记下已有 UID, 返回一个生成器, 逐个产出之后新到的 (code, subject)。

    基线在调用时就取, 而不是第一次迭代时, 这样调用方先 watch 再触发发信不会漏码。
    超时后生成器正常结束; 连续失败抛 WatchError。
    """
    mail = connect(pw)
    baseline = set(uid_list(mail, days))   # 启动时已有的 UID 不再通知
    print(f"[gmail-code] 开始监听 {GMAIL_USER} 的 Typeless 验证码 "
          f"(每 {POLL_SEC}s 轮询, 最长 {int(timeout_sec)}s)", file=sys.stderr)

    def gen(mail):
        started = time.monotonic()
        failures = 0
        backoff = RECONNECT_BACKOFF_SEC
        try:
            while time.monotonic() - started <= timeout_sec:
                time.sleep(POLL_SEC)
                try:
                    mail.noop()
                    uids = uid_list(mail, days)
                    failures, backoff = 0, RECONNECT_BACKOFF_SEC
                except Exception as e:
                    failures += 1
                    if failures >= MAX_CONSEC_FAILURES:
                        raise WatchError(f"连续 {failures} 次轮询失败({e}), 放弃")
                    print(f"[gmail-code] 轮询失败({e}), {backoff}s 后重连 "
                          f"({failures}/{MAX_CONSEC_FAILURES})...", file=sys.stderr)
                    time.sleep(backoff)
                    backoff = min(backoff * 2, RECONNECT_BACKOFF_MAX)
                    mail = connect(pw)
                    continue

                for uid in uids:
                    if uid in baseline:
                        continue
                    baseline.add(uid)
                    msg = fetch_uid(mail, uid)
                    code = msg and extract_code(body_text(msg))
                    if code:
                        yield code, str(msg.get("Subject", ""))
            print("[gmail-code] 监听超时", file=sys.stderr)
        finally:
            try:
                mail.logout()
            except Exception:
                pass

    return gen(mail)


def run_watch(pw, days, timeout_sec):
    try:
        for code, subject in watch_codes(pw, days, timeout_sec):
            deliver(code, subject)
    except WatchError as e:
        print(f"[gmail-code] {e}", file=sys.stderr)
        return 4
    except KeyboardInterrupt:
        pass
    return 0


def main():
    ap = argparse.ArgumentParser(description="从 Gmail 取 Typeless 验证码")
    ap.add_argument("--watch", action="store_true", help="持续监听新邮件")
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS,
                    help=f"回看天数, 默认 {DEFAULT_DAYS}")
    ap.add_argument("--timeout", type=int, default=DEFAULT_WATCH_TIMEOUT,
                    help=f"watch 模式总超时秒数, 默认 {DEFAULT_WATCH_TIMEOUT}")
    args = ap.parse_args()

    pw = get_password()
    if not pw:
        setup_hint()
        return 2
    try:
        return run_watch(pw, args.days, args.timeout) if args.watch \
            else run_once(pw, args.days)
    except imaplib.IMAP4.error as e:
        print(f"[gmail-code] IMAP 登录/操作失败: {e}", file=sys.stderr)
        print("[gmail-code] 请检查应用专用密码是否正确", file=sys.stderr)
        return 3
    except OSError as e:
        print(f"[gmail-code] 网络错误(重试后仍失败): {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
