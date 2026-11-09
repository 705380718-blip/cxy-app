#!/usr/bin/env bash
set -euo pipefail
if [[ $# -ne 0 ]]; then
  echo '[错误] 此入口不接受参数；请使用 WML_* 环境变量配置。' >&2
  exit 2
fi
trap 'echo "[错误] 启动失败，退出码 $?。请检查 Python 3.11、依赖和端口。" >&2' ERR
project_dir="$(cd "$(dirname "$0")" && pwd)"
cd "$project_dir"
export WML_ENV_FILE="${WML_ENV_FILE:-$project_dir/delivery-local.env}"
bootstrap_python="${WML_PYTHON:-python3.11}"
if [[ ! -x "$project_dir/.venv/bin/python" ]]; then
  "$bootstrap_python" -c 'import sys; assert sys.version_info[:2]==(3,11), "离线包需要 Python 3.11"'
  "$bootstrap_python" -m venv "$project_dir/.venv"
fi
python_bin="$project_dir/.venv/bin/python"
"$python_bin" - <<'PY'
import socket
from app.config import Settings
s=Settings.from_env()
if s.host not in ('127.0.0.1','localhost') or s.port in (5173,8000) or not 1024<=s.port<=65535:
    raise SystemExit('[错误] 仅支持本机独立端口；5173/8000 为其他项目保留')
with socket.socket() as probe:
    probe.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
    try:probe.bind((s.host,s.port))
    except OSError:raise SystemExit('[错误] 端口已占用；请选择独立端口，不会停止其他进程')
print(f'[启动] http://{s.host}:{s.port}/ · 按 Ctrl+C 停止')
PY
if [[ -d "$project_dir/wheelhouse" ]]; then
  "$python_bin" -m pip install --disable-pip-version-check --no-index --find-links "$project_dir/wheelhouse" -r requirements-lock.txt
else
  "$python_bin" -m pip install --disable-pip-version-check -r requirements-lock.txt
fi
exec "$python_bin" run.py
