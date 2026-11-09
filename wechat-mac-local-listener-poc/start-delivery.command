#!/usr/bin/env bash
set -euo pipefail
if [[ $# -ne 0 ]]; then echo '[错误] 此入口不接受参数。' >&2; exit 2; fi
cd "$(dirname "$0")"
exec bash ./start-delivery.sh
