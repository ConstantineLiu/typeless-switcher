#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
[INPUT]: 依赖 crypto_utils 的 decrypt_user_data / build_security_headers / get_device_id / API_BASE;
         依赖 requests 调 Typeless API, sqlite3 读本地 typeless.db
[OUTPUT]: 命令行 verify.py <expected_email> [backup_dir]: 逐项打印检查结果, 全部通过退出 0, 否则退出 1
[POS]: typeless-reset-device 的迁移验收, 被 reset-and-migrate.sh 最后一步调用, 通过后才删除备份
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

import json
import os
import sqlite3
import sys

import requests

from crypto_utils import API_BASE, TYPELESS_DIR, build_security_headers, decrypt_user_data, get_device_id


def cloud_terms(user):
    """用新账号凭证拉全部词汇; 请求成功本身就证明服务器认这个登录。"""
    terms, offset = set(), 0
    while True:
        path = "/user/dictionary/list"
        headers = build_security_headers(path, user["user_id"], user["refresh_token"], get_device_id())
        resp = requests.get(f"{API_BASE}{path}?size=200&offset={offset}", headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "OK":
            raise RuntimeError(f"API 返回 {data.get('status')}")
        words = data["data"].get("words", [])
        terms |= {w["term"].strip() for w in words}
        offset += len(words)
        if not words or offset >= data["data"].get("total_count", 0):
            return terms


def stray_history(user_id):
    """本地历史里还挂在别的账号下的记录数。"""
    db = sqlite3.connect(os.path.join(TYPELESS_DIR, "typeless.db"))
    try:
        return sum(db.execute(f"SELECT COUNT(*) FROM {t} WHERE user_id IS NOT NULL AND user_id != ?",
                              (user_id,)).fetchone()[0] for t in ("history", "history_v2"))
    finally:
        db.close()


def backup_terms(backup_dir):
    if not backup_dir:
        return set()
    with open(os.path.join(backup_dir, "dictionary_backup.json")) as f:
        words = json.load(f).get("data", {}).get("words", [])
    return {w["term"].strip() for w in words if w.get("term", "").strip()}


def main():
    if len(sys.argv) not in (2, 3):
        raise SystemExit("用法: verify.py <expected_email> [backup_dir]")
    expected, backup_dir = sys.argv[1], (sys.argv[2] if len(sys.argv) == 3 else "")

    user = decrypt_user_data()
    try:
        terms, api_error = cloud_terms(user), None
    except Exception as e:          # network / auth failure: report it as a failed check
        terms, api_error = set(), e
    missing = backup_terms(backup_dir) - terms
    stray = stray_history(user["user_id"])

    checks = [
        ("本地已登录新账号", user.get("email") == expected and bool(user.get("refresh_token")),
         f"当前 {user.get('email')}, 期望 {expected}"),
        ("服务器接受新账号登录", api_error is None,
         f"调用失败: {api_error}" if api_error else f"云端词汇 {len(terms)} 个"),
        ("词汇已全部导入", not missing, f"缺少 {sorted(missing)}" if missing else "备份里的词都在"),
        ("历史记录全部归属新账号", stray == 0, f"{stray} 条仍属其他账号"),
    ]
    for name, ok, detail in checks:
        print(f"      [{'OK' if ok else 'FAIL'}] {name}: {detail}")
    return 0 if all(ok for _, ok, _ in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
