#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
[INPUT]: 依赖 playwright 的 sync_api (驱动本机 Google Chrome, 每次全新临时配置, 等同无痕);
         依赖 gmail_code 的 get_password / watch_codes / setup_hint
[OUTPUT]: next_alias(email, used) 按固定顺序算下一个未用过的 Gmail 点号别名 (从 3 个点起), used_emails() 读备份里的历史邮箱;
          命令行 web_login.py <email>: 网页邮箱登录 → 自动填 Gmail 验证码 → 把 typeless:// 回调交给 app
[POS]: typeless-reset-device 的登录自动化, 被 reset-and-migrate.sh 第 4 步调用
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md

原理:
    app 的 "Sign in with email" 按钮只是用浏览器打开 LOGIN_URL。网页验证通过后执行
    window.location.href = "typeless://auth/...?<登录结果>", macOS 把它交给 app 完成登录。
    这里用 CDP 的 Page.frameRequestedNavigation 截下这个链接, 再用 `open` 交给 app。
    浏览器是全新临时配置, 没有旧账号 Cookie, 所以不用先退出网页版。
"""

import json
import subprocess
import sys
from itertools import combinations
from pathlib import Path

from playwright.sync_api import sync_playwright

from gmail_code import get_password, setup_hint, watch_codes

LOGIN_URL = "https://www.typeless.com/login/email?registration_origin=desktop_app"
CODE_TIMEOUT_SEC = 300      # 等验证码邮件
HANDOFF_TIMEOUT_MS = 60_000  # 填完码后等 typeless:// 跳转
DEBUG_SHOT = Path(__file__).with_name("web_login_debug.png")


# ---------------------------------------------------------------- 别名 --
# Gmail ignores dots in the local part, so every set of "gaps" (1..n-1) that
# holds a dot is a distinct Typeless account landing in the same inbox.
# All sets live in one fixed order: MIN_DOTS dots first (l.i.u.yuan...), then
# more dots, then fewer as a last resort. Next alias = next unused set after
# the current one, so the order itself never repeats and backups guard the rest.
MIN_DOTS = 3


def dot_gaps(local):
    """'l.i.uyuan' → (1, 2): 每个点前面有几个字符。"""
    gaps, seen = [], 0
    for ch in local:
        if ch == ".":
            gaps.append(seen)
        else:
            seen += 1
    return tuple(gaps)


def alias_order(n):
    """长度 n 的名字所有加点方案, 从 MIN_DOTS 个点开始, 字典序。"""
    k0 = min(MIN_DOTS, n - 1)
    for k in [*range(k0, n), *range(1, k0)]:
        yield from combinations(range(1, n), k)


def used_emails():
    """历次备份记录的账号邮箱。"""
    here = Path(__file__).parent
    return {json.loads(p.read_text())["backup_email"]
            for p in here.glob("backup_*/dictionary_backup.json")}


def next_alias(email, used=()):
    local, domain = email.split("@")
    plain = local.replace(".", "")
    order = list(alias_order(len(plain)))
    cur = dot_gaps(local)
    start = order.index(cur) + 1 if len(cur) >= min(MIN_DOTS, len(plain) - 1) else 0
    taken = {dot_gaps(u.split("@")[0]) for u in used
             if u.split("@")[0].replace(".", "") == plain} | {cur}
    for gaps in order[start:] + order[:start]:
        if gaps not in taken:
            dotted = "".join(("." if i in gaps else "") + c for i, c in enumerate(plain))
            return f"{dotted}@{domain}"
    raise SystemExit(f"错误: {plain}@{domain} 的 {len(order)} 个点号别名都用过了")


# ---------------------------------------------------------------- 登录 --
def login(page, email, pw):
    handoff = []
    cdp = page.context.new_cdp_session(page)
    cdp.send("Page.enable")
    cdp.on("Page.frameRequestedNavigation",
           lambda e: e["url"].startswith("typeless://") and handoff.append(e["url"]))

    page.goto(LOGIN_URL)
    page.fill('input[name="email"]', email)
    codes = watch_codes(pw, days=1, timeout_sec=CODE_TIMEOUT_SEC)  # 先取基线再发信
    page.get_by_role("button", name="Continue with email").click()
    print(f"      已提交 {email}, 等 Gmail 验证码...")

    code, _ = next(codes, (None, None))
    codes.close()
    if not code:
        raise SystemExit(f"错误: {CODE_TIMEOUT_SEC}s 内没收到验证码")
    print(f"      收到验证码 {code}, 填入网页")

    page.locator('input:visible:not([name="email"])').first.click()
    page.keyboard.type(code)
    page.keyboard.press("Enter")

    for _ in range(HANDOFF_TIMEOUT_MS // 500):
        if handoff:
            return handoff[0]
        page.wait_for_timeout(500)
    raise SystemExit(f"错误: 填码后 {HANDOFF_TIMEOUT_MS // 1000}s 没等到 typeless:// 跳转")


def main():
    if len(sys.argv) != 2:
        raise SystemExit("用法: web_login.py <email>")
    pw = get_password()
    if not pw:
        setup_hint()
        return 2

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=False)
        page = browser.new_page()
        try:
            url = login(page, sys.argv[1], pw)
        except BaseException:
            page.screenshot(path=str(DEBUG_SHOT))
            print(f"      出错时的页面截图: {DEBUG_SHOT}", file=sys.stderr)
            raise
        finally:
            browser.close()

    print(f"      截到回调 {url.split('?')[0]}, 交给 Typeless")
    subprocess.run(["open", url], check=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
