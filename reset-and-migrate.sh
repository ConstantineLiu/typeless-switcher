#!/usr/bin/env bash
#
# 一键迁移：导出当前账号数据 → 重置设备码(=本地退出) → 网页自动登录下一个别名 → 导入并迁移
#
# 用法: bash reset-and-migrate.sh [you@gmail.com]
#   登录着旧账号时: 完整迁移, 邮箱可省略 (从当前账号推出)。
#   没登录任何账号时: 首次登录, 跳过导出/导入, 直接登录一个新别名。
#   邮箱取值顺序: 参数 > GMAIL_USER 环境变量 > 当前账号 > 终端提问 (非交互环境直接报错)。
#
# 说明: 新账号邮箱 = 按固定顺序取下一个没用过的 Gmail 点号别名 (见 web_login.py next_alias),
#       脚本开一个全新配置的 Chrome 走网页邮箱登录, 自动从 Gmail 取码填入,
#       再把 typeless:// 回调交给 app。全程无需手动操作。
#       删除操作全部走 trash(进废纸篓, 可恢复)。
#
set -euo pipefail
cd "$(dirname "$0")"

TS="$HOME/Library/Application Support/Typeless"
NOW="$HOME/Library/Application Support/now.typeless.desktop"

# ---------------------------------------------------------------------------
# Preflight: everything that can fail without side effects fails here
# ---------------------------------------------------------------------------
GMAIL_USER="${1:-${GMAIL_USER:-}}"      # arg > env > current account > prompt
if [ -f "$TS/user-data.json" ]; then
  LOGGED_IN=1
  OLD_EMAIL=$(uv run python3 -c "from crypto_utils import decrypt_user_data; print(decrypt_user_data()['email'])")
  GMAIL_USER="${GMAIL_USER:-$OLD_EMAIL}"
else
  LOGGED_IN=0
  echo "Typeless 当前没有登录账号: 首次登录模式, 跳过导出/导入, 直接登录一个新别名"
  if [ -z "$GMAIL_USER" ]; then
    [ -t 0 ] || { echo "错误: 首次登录需要 Gmail 地址, 用法: bash reset-and-migrate.sh you@gmail.com" >&2; exit 1; }
    read -r -p "你的 Gmail 地址 (如 you@gmail.com): " GMAIL_USER
  fi
fi
GMAIL_LOCAL=${GMAIL_USER%@*}
export GMAIL_USER="${GMAIL_LOCAL//./}@${GMAIL_USER#*@}"   # the inbox itself has no dots
OLD_EMAIL="${OLD_EMAIL:-$GMAIL_USER}"
security find-generic-password -s "typeless-reset-gmail" -a "$GMAIL_USER" > /dev/null 2>&1 || {
  echo "错误: Keychain 里没有 $GMAIL_USER 的 Gmail 应用专用密码, 配置方法见 README" >&2
  exit 1
}

BACKUP=""
if [ "$LOGGED_IN" = 1 ]; then
  echo "[1/6] 导出当前账号数据..."
  uv run python3 export.py
  BACKUP=$(ls -dt backup_*/ | head -1)
  echo "      备份目录: $BACKUP"
else
  echo "[1/6] 没有登录账号, 跳过导出"
fi

echo "[2/6] 退出 Typeless..."
osascript -e 'quit app "Typeless"' 2>/dev/null || true
for _ in $(seq 1 10); do
  pgrep -f "Typeless.app" > /dev/null 2>&1 || break
  sleep 0.5
done

echo "[3/6] 重置设备码 (trash 方式, 可从废纸篓恢复)..."
[ -f "$NOW/device.cache" ] && trash "$NOW/device.cache" || true
security delete-generic-password \
  -s "now.typeless.desktop.deviceIdentifier" \
  -a "now.typeless.desktop.security.auth_key" > /dev/null 2>&1 || true
for f in user-data.json Cookies Cookies-journal; do
  [ -f "$TS/$f" ] && trash "$TS/$f" || true
done
[ -d "$TS/Local Storage" ] && trash "$TS/Local Storage" || true
if [ -f "$TS/app-storage.json" ]; then
  node -e "
    const fs = require('fs');
    try {
      const data = JSON.parse(fs.readFileSync('$TS/app-storage.json', 'utf8'));
      delete data.userData;
      delete data.quotaUsage;
      fs.writeFileSync('$TS/app-storage.json', JSON.stringify(data, null, '\t'));
    } catch (_) {}
  " || true
fi

NEW_EMAIL=$(uv run python3 -c "from web_login import next_alias, used_emails; print(next_alias('$OLD_EMAIL', used_emails()))")
echo "[4/6] 网页登录新账号 $NEW_EMAIL (旧: $OLD_EMAIL)..."
open /Applications/Typeless.app
uv run python3 web_login.py "$NEW_EMAIL"

uv run python3 - <<'PYEOF'
import os, time
from crypto_utils import decrypt_user_data

path = os.path.expanduser("~/Library/Application Support/Typeless/user-data.json")
while True:
    if os.path.isfile(path):
        try:
            user = decrypt_user_data()
            if user.get("refresh_token"):
                print(f"      已检测到新登录: {user['email']}")
                time.sleep(2)   # 等应用把登录态写稳
                break
        except Exception:
            pass
    time.sleep(2)
PYEOF

echo "[5/6] 导入词汇 + 迁移历史记录..."
NEW_UID=$(uv run python3 -c "from crypto_utils import decrypt_user_data; print(decrypt_user_data()['user_id'])")
if [ -n "$BACKUP" ]; then
  # 防呆: 新账号和备份是同一账号时中止
  OLD_UID=$(uv run python3 -c "import json; print(json.load(open('$BACKUP/dictionary_backup.json'))['backup_user_id'])")
  if [ "$NEW_UID" = "$OLD_UID" ]; then
    echo "错误: 当前登录的还是备份时的旧账号, 未导入。请登录新账号后重跑:"
    echo "  uv run python3 import.py $BACKUP"
    exit 1
  fi
  uv run python3 import.py "$BACKUP"
fi

# import.py 只迁移 export_meta 里记录的一个旧 user_id,
# 这里把 history / history_v2 中所有其他 user_id 一并归到新账号
sqlite3 "$TS/typeless.db" "
  UPDATE history    SET user_id = '$NEW_UID' WHERE user_id IS NOT NULL AND user_id != '$NEW_UID';
  UPDATE history_v2 SET user_id = '$NEW_UID' WHERE user_id IS NOT NULL AND user_id != '$NEW_UID';
"

echo "[6/6] 重启 Typeless..."
open /Applications/Typeless.app

echo ""
echo "完成! 当前账号 $NEW_EMAIL, 本地全部历史记录已归属新账号${BACKUP:+, 词汇已导入, 备份在 $BACKUP}"
