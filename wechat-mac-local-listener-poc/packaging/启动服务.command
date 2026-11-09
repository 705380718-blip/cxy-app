#!/usr/bin/env bash
set -euo pipefail

bundle_dir="$(cd "$(dirname "$0")" && pwd)"
launcher="$bundle_dir/程序文件/start-server.sh"

# 用户主动双击本命令后，仅移除本软件包内置运行时的下载隔离标记；
# 不修改系统全局 Gatekeeper 或其他应用的安全设置。
/usr/bin/xattr -dr com.apple.quarantine "$bundle_dir/程序文件" 2>/dev/null || true

if [[ ! -x "$launcher" ]]; then
  echo "[错误] 软件包不完整，请保留“程序文件”与本命令在同一文件夹。"
  read -r -p "按回车键关闭..." _
  exit 1
fi

"$launcher"
echo ""
read -r -p "按回车键关闭本窗口..." _
