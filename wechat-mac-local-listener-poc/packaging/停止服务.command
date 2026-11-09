#!/usr/bin/env bash
set -euo pipefail

bundle_dir="$(cd "$(dirname "$0")" && pwd)"
stopper="$bundle_dir/程序文件/stop-server.sh"

/usr/bin/xattr -dr com.apple.quarantine "$bundle_dir/程序文件" 2>/dev/null || true

if [[ ! -x "$stopper" ]]; then
  echo "[错误] 软件包不完整，请保留“程序文件”与本命令在同一文件夹。"
  read -r -p "按回车键关闭..." _
  exit 1
fi

"$stopper"
echo ""
read -r -p "按回车键关闭本窗口..." _
