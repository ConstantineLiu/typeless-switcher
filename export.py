#!/usr/bin/env python3
"""
Export all Typeless data from the current account.

Usage:
    uv run python3 export.py [--output DIR]

Exports:
    - Dictionary words (cloud API)
    - Local database (typeless.db)
    - Recordings (.ogg files)
    - App settings (app-settings.json, app-storage.json, app-onboarding.json)
"""

import argparse
import json
import os
import shutil
import sqlite3
import sys
import time

import requests

from crypto_utils import (
    API_BASE,
    TYPELESS_DIR,
    build_security_headers,
    decrypt_user_data,
    get_device_id,
)


def get_proxy():
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    return {"https": proxy} if proxy else None


def export_dictionary(backup_dir):
    """Fetch all dictionary words from API and save to JSON."""
    user = decrypt_user_data()
    token = user["refresh_token"]
    user_id = user["user_id"]
    device_id = get_device_id()
    proxy = get_proxy()

    print(f"[dict] Account:  {user['email']}")
    print(f"[dict] User ID:  {user_id}")

    all_words = []
    offset = 0
    page_size = 200

    while True:
        headers = build_security_headers("/user/dictionary/list", user_id, token, device_id)
        resp = requests.get(
            f"{API_BASE}/user/dictionary/list?size={page_size}&offset={offset}",
            headers=headers,
            proxies=proxy,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("status") != "OK":
            print(f"[dict] Error: {data}", file=sys.stderr)
            sys.exit(1)

        words = data["data"].get("words", [])
        total = data["data"].get("total_count", 0)
        all_words.extend(words)
        print(f"[dict]   Fetched {len(all_words)}/{total} words...")

        if len(all_words) >= total or len(words) == 0:
            break
        offset += page_size

    manual = [w for w in all_words if not w.get("auto")]
    auto = [w for w in all_words if w.get("auto")]

    result = {
        "status": "OK",
        "data": {"words": all_words, "total_count": len(all_words)},
        "backup_email": user["email"],
        "backup_user_id": user_id,
        "backup_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "stats": {"total": len(all_words), "manual": len(manual), "auto": len(auto)},
    }

    path = os.path.join(backup_dir, "dictionary_backup.json")
    with open(path, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"[dict] Saved {len(all_words)} words → {path}")
    return user_id


def export_local(backup_dir):
    """Backup local files: database, recordings, settings."""
    db_path = os.path.join(TYPELESS_DIR, "typeless.db")
    recordings_dir = os.path.join(TYPELESS_DIR, "Recordings")

    # 1. Database
    if os.path.isfile(db_path):
        dst = os.path.join(backup_dir, "typeless.db")
        shutil.copy2(db_path, dst)
        print(f"[db]   Copied typeless.db")

        # Show summary for all history tables
        conn = sqlite3.connect(db_path)
        old_user_id = None
        cur = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name IN ('history', 'history_v2')"
        )
        tables = [row[0] for row in cur.fetchall()]
        for table in tables:
            cur = conn.execute(f"SELECT COUNT(*) FROM {table}")
            count = cur.fetchone()[0]
            print(f"[db]   {table}: {count} records")
            if old_user_id is None:
                cur = conn.execute(
                    f"SELECT DISTINCT user_id FROM {table} LIMIT 1"
                )
                row = cur.fetchone()
                old_user_id = row[0] if row else None
        conn.close()

        print(f"[db]   user_id: {old_user_id}")
    else:
        print("[db]   typeless.db not found, skipping")
        old_user_id = None

    # 2. Recordings
    if os.path.isdir(recordings_dir):
        ogg_count = len([f for f in os.listdir(recordings_dir) if f.endswith(".ogg")])
        if ogg_count > 0:
            dst = os.path.join(backup_dir, "Recordings")
            if os.path.exists(dst):
                shutil.rmtree(dst)
            shutil.copytree(recordings_dir, dst)
            print(f"[rec]   Copied {ogg_count} .ogg files")
    else:
        print("[rec]   Recordings/ not found, skipping")

    # 3. Settings files
    for name in ["app-settings.json", "app-storage.json", "app-onboarding.json"]:
        src = os.path.join(TYPELESS_DIR, name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(backup_dir, name))
            print(f"[cfg]   Copied {name}")
        else:
            print(f"[cfg]   {name} not found, skipping")

    return old_user_id


def main():
    parser = argparse.ArgumentParser(description="Export all Typeless data")
    parser.add_argument("--output", "-o", help="Output directory (default: ./backup_<timestamp>)")
    args = parser.parse_args()

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    backup_dir = args.output or os.path.join(os.getcwd(), f"backup_{timestamp}")
    os.makedirs(backup_dir, exist_ok=True)

    print(f"Exporting to {backup_dir}/")
    print()

    # Export dictionary
    user_id = export_dictionary(backup_dir)
    print()

    # Export local data
    old_user_id = export_local(backup_dir)
    print()

    # Write metadata
    meta = {
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "user_id": old_user_id or user_id,
        "backup_dir": backup_dir,
    }
    with open(os.path.join(backup_dir, "export_meta.json"), "w") as f:
        json.dump(meta, f, indent=2)

    print(f"Done! All data exported to {backup_dir}/")
    print()
    print("Next steps:")
    print("  1. bash reset-device-macos.sh")
    print("  2. Login to NEW account in Typeless")
    print(f"  3. uv run python3 import.py {backup_dir}")


if __name__ == "__main__":
    main()
