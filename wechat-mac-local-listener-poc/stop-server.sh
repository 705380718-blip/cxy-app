#!/usr/bin/env bash
set -euo pipefail

app_support_dir="$HOME/Library/Application Support/群聊问题整理"
pid_file="$app_support_dir/service.pid"

if [[ ! -f "$pid_file" ]]; then
  echo "群聊问题整理服务当前没有运行。"
  exit 0
fi

server_pid="$(tr -cd '0-9' <"$pid_file")"
if [[ -n "$server_pid" ]] && kill -0 "$server_pid" 2>/dev/null; then
  kill "$server_pid"
  for _ in {1..20}; do
    kill -0 "$server_pid" 2>/dev/null || break
    sleep 0.1
  done
fi
rm -f "$pid_file"
echo "群聊问题整理服务已停止。"
