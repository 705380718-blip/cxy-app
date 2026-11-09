#!/usr/bin/env bash
set -euo pipefail
if [[ $# -ne 0 ]]; then
  echo '[错误] 此入口不接受参数。端口、数据库请通过 WML_* 环境变量或配置文件设置。' >&2
  exit 2
fi
project_dir="$(cd "$(dirname "$0")" && pwd)"
cd "$project_dir"
default_env="$project_dir/.env.delivery.example"
if [[ -f "$project_dir/.env.delivery-live" ]]; then
  default_env="$project_dir/.env.delivery-live"
fi
export WML_ENV_FILE="${WML_ENV_FILE:-$default_env}"
python_bin="${WML_PYTHON:-$project_dir/.venv/bin/python}"
if [[ ! -x "$python_bin" ]]; then
  echo '[错误] 缺少 Python 环境，请先安装 requirements.txt 中的依赖。' >&2
  exit 1
fi
trap 'echo "[错误] 启动失败，退出码 $?. 请检查配置与端口占用。" >&2' ERR
"$python_bin" - <<'PY'
import socket
from app.config import Settings
settings=Settings.from_env()
if settings.port in {5173,8000}:
    raise SystemExit('[错误] 5173/8000 是其他项目保留端口')
family = socket.AF_INET6 if settings.host == '::1' else socket.AF_INET
with socket.socket(family) as probe:
    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        probe.bind((settings.host,settings.port))
    except OSError:
        raise SystemExit('[错误] 指定端口已占用，请选择独立端口；不会停止其他进程')
print(f'[启动] 交付小助手开发版 http://{settings.host}:{settings.port}/')
print('[启动] 独立开发数据库；按 Ctrl+C 停止服务')
PY
"$python_bin" run.py
