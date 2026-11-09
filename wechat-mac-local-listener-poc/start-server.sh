#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "$0")" && pwd)"
app_support_dir="$HOME/Library/Application Support/群聊问题整理"
runtime_env="$app_support_dir/config/runtime.env"
log_file="$app_support_dir/logs/app.log"
pid_file="$app_support_dir/service.pid"
url="http://127.0.0.1:8791/"

mkdir -p "$app_support_dir/config" "$app_support_dir/data" "$app_support_dir/logs"
cd "$project_dir"

if curl -fsS "${url}api/health" >/dev/null 2>&1; then
  echo "群聊问题整理服务已经在运行。"
  echo "浏览器访问：$url"
  exit 0
fi

if [[ ! -x runtime/bin/python3 ]]; then
  echo "[错误] 软件包不完整：缺少内置运行环境。"
  exit 1
fi

python_bin="$project_dir/runtime/bin/python3"
export PYTHONHOME="$project_dir/runtime"
export WML_PYTHON="$python_bin"

if [[ ! -f "$runtime_env" ]]; then
  cp .env.example "$runtime_env"
fi
export WML_ENV_FILE="$runtime_env"

nohup "$python_bin" run.py >>"$log_file" 2>&1 </dev/null &
server_pid=$!
echo "$server_pid" >"$pid_file"

for _ in {1..60}; do
  if curl -fsS "${url}api/health" >/dev/null 2>&1; then
    echo ""
    echo "群聊问题整理服务已启动。"
    echo "请在浏览器输入：$url"
    echo "本窗口现在可以关闭；需要退出服务时双击“停止服务.command”。"
    exit 0
  fi
  if ! kill -0 "$server_pid" 2>/dev/null; then
    break
  fi
  sleep 0.25
done

echo "[错误] 服务启动失败。日志末尾如下："
tail -40 "$log_file" 2>/dev/null || true
rm -f "$pid_file"
exit 1
