#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "$0")" && pwd)"
cd "$project_dir"

app_support_dir="$HOME/Library/Application Support/群聊问题整理"
runtime_env="$app_support_dir/config/runtime.env"
log_file="$app_support_dir/logs/app.log"
mkdir -p "$app_support_dir/config" "$app_support_dir/data" "$app_support_dir/logs"

if curl -fsS "http://127.0.0.1:8791/api/health" >/dev/null 2>&1; then
  open "http://127.0.0.1:8791/"
  exit 0
fi

if [[ -x runtime/bin/python3 ]]; then
  python_bin="$project_dir/runtime/bin/python3"
  export PYTHONHOME="$project_dir/runtime"
elif [[ -x .venv/bin/python ]]; then
  python_bin="$project_dir/.venv/bin/python"
else
  if ! command -v python3 >/dev/null 2>&1; then
    osascript -e 'display alert "缺少 Python 3" message "请先安装 Python 3.11 或更高版本，再重新打开本软件。" as critical'
    exit 1
  fi
  python3 -m venv .venv
  if [[ -d wheelhouse ]] && compgen -G "wheelhouse/*.whl" >/dev/null; then
    .venv/bin/python -m pip install --no-index --find-links wheelhouse -r requirements-runtime.txt
  else
    .venv/bin/python -m pip install --upgrade pip
    .venv/bin/python -m pip install -r requirements-runtime.txt
  fi
  python_bin="$project_dir/.venv/bin/python"
fi

if [[ ! -f "$runtime_env" ]]; then
  cp .env.example "$runtime_env"
fi

export WML_ENV_FILE="$runtime_env"
export WML_PYTHON="$python_bin"

"$python_bin" run.py >>"$log_file" 2>&1 &
server_pid=$!
trap 'kill "$server_pid" 2>/dev/null || true' EXIT INT TERM

for _ in {1..60}; do
  if curl -fsS "http://127.0.0.1:8791/api/health" >/dev/null 2>&1; then
    open "http://127.0.0.1:8791/"
    wait "$server_pid"
    exit $?
  fi
  sleep 0.25
done

osascript -e 'display alert "启动失败" message "本地服务未能启动，请查看使用手册中的故障排查。" as critical'
exit 1
