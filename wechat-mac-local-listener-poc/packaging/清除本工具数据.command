#!/usr/bin/env bash
set -euo pipefail

bundle_dir="$(cd "$(dirname "$0")" && pwd)"
helper="$bundle_dir/群聊问题整理.app/Contents/Resources/群聊问题整理/清除本工具数据.command"

if [[ ! -x "$helper" ]]; then
  osascript -e 'display alert "软件包不完整" message "请保留应用与辅助命令在同一文件夹内。" as critical'
  exit 1
fi

exec "$helper"
