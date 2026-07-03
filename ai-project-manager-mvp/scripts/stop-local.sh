#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="$ROOT_DIR/.runtime"
BACKEND_PID_FILE="$RUNTIME_DIR/backend.pid"
FRONTEND_PID_FILE="$RUNTIME_DIR/frontend.pid"
PORT_FILE="$RUNTIME_DIR/ports.env"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
DRY_RUN=0

usage() {
  cat <<EOF
Usage: ./scripts/stop-local.sh [--dry-run]

Stops the local backend and frontend processes started by start-local.sh.

Options:
  --dry-run   Show what would be stopped without killing processes
  -h, --help  Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      usage
      exit 1
      ;;
  esac
done

pid_is_alive() {
  local pid="${1:-}"
  [[ -n "$pid" ]] && kill -0 "$pid" >/dev/null 2>&1
}

read_pid() {
  local file="$1"
  [[ -f "$file" ]] && tr -d '[:space:]' < "$file" || true
}

stop_pid_file() {
  local name="$1"
  local file="$2"
  local pid
  pid="$(read_pid "$file")"

  if ! pid_is_alive "$pid"; then
    echo "$name is not running."
    rm -f "$file"
    return 0
  fi

  if [[ "$DRY_RUN" == "1" ]]; then
    echo "Would stop $name PID $pid."
    return 0
  fi

  echo "Stopping $name PID $pid ..."
  kill "$pid" >/dev/null 2>&1 || true

  for _ in {1..20}; do
    if ! pid_is_alive "$pid"; then
      rm -f "$file"
      echo "$name stopped."
      return 0
    fi
    sleep 0.2
  done

  echo "$name did not exit gracefully; forcing stop."
  kill -9 "$pid" >/dev/null 2>&1 || true
  rm -f "$file"
}

listener_pid() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -tiTCP:"$port" -sTCP:LISTEN -n -P 2>/dev/null | head -1 || true
  fi
}

process_cwd() {
  local pid="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -1
  fi
}

stop_port_if_project_process() {
  local name="$1"
  local port="$2"
  local pid cwd
  pid="$(listener_pid "$port")"
  if ! pid_is_alive "$pid"; then
    return 0
  fi
  cwd="$(process_cwd "$pid")"
  if [[ "$cwd" != "$ROOT_DIR"* ]]; then
    echo "$name port $port is used by PID $pid outside this project; leaving it running."
    return 0
  fi
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "Would stop $name PID $pid on port $port."
    return 0
  fi
  echo "Stopping $name PID $pid on port $port ..."
  kill "$pid" >/dev/null 2>&1 || true
  for _ in {1..20}; do
    if ! pid_is_alive "$pid"; then
      echo "$name stopped."
      return 0
    fi
    sleep 0.2
  done
  echo "$name did not exit gracefully; forcing stop."
  kill -9 "$pid" >/dev/null 2>&1 || true
}

if [[ -f "$PORT_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$PORT_FILE"
fi

stop_pid_file "Frontend" "$FRONTEND_PID_FILE"
stop_pid_file "Backend" "$BACKEND_PID_FILE"
stop_port_if_project_process "Frontend" "$FRONTEND_PORT"
stop_port_if_project_process "Backend" "$BACKEND_PORT"

if [[ "$DRY_RUN" == "0" ]]; then
  rm -f "$PORT_FILE"
fi

echo
echo "Local services are stopped."
