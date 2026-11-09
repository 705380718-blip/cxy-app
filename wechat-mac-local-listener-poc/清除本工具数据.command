#!/usr/bin/env bash
set -euo pipefail

data_dir="$HOME/Library/Application Support/群聊问题整理/data"
answer="$(osascript -e 'button returned of (display dialog "这会清除本工具保存的采集记录、问题、报告、规则和监听状态，不会删除微信原始聊天记录。" buttons {"取消", "清除"} default button "取消" with icon caution)')"
if [[ "$answer" != "清除" ]]; then
  exit 0
fi

if [[ -d "$data_dir" ]]; then
  find "$data_dir" -maxdepth 1 -type f \( -name 'mac-listener.db' -o -name 'mac-listener.db-wal' -o -name 'mac-listener.db-shm' \) -delete
fi
osascript -e 'display notification "本工具的本地数据已清除；微信原始记录未改动。" with title "群聊问题整理"'
