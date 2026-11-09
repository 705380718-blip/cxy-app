#!/usr/bin/env bash
set -euo pipefail

bundle_dir="$(cd "$(dirname "$0")" && pwd)"
helper="$bundle_dir/程序文件/清除本工具数据.command"

/usr/bin/xattr -dr com.apple.quarantine "$bundle_dir/程序文件" 2>/dev/null || true

if [[ ! -x "$helper" ]]; then
  echo "[错误] 软件包不完整，请保留“程序文件”与本命令在同一文件夹。"
  read -r -p "按回车键关闭..." _
  exit 1
fi

exec "$helper"
