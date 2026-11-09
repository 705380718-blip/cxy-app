#!/bin/bash
set -euo pipefail
if [[ $# -ne 0 ]]; then echo '请双击此入口，不接受命令参数。' >&2; exit 2; fi
trap 'echo "打开失败，请查看 manual.html 中的故障排查。"; read -r -p "按回车关闭…" _' ERR
package_dir="$(cd "$(dirname "$0")" && pwd)"
if [[ "$(/usr/bin/uname -m)" != 'arm64' ]]; then
  echo '此包需要 Apple Silicon Mac。Intel Mac 或 Rosetta 终端请勿使用。'; exit 1
fi
export PYTHONHOME="$package_dir/python"
export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
unset PYTHONPATH
exec "$package_dir/python/bin/python3.11" "$package_dir/tools/recipient.py"
