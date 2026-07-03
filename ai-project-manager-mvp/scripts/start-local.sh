#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
HOST="${HOST:-127.0.0.1}"
RUNTIME_DIR="$ROOT_DIR/.runtime"
BACKEND_PID_FILE="$RUNTIME_DIR/backend.pid"
FRONTEND_PID_FILE="$RUNTIME_DIR/frontend.pid"
PORT_FILE="$RUNTIME_DIR/ports.env"
BACKEND_LOG="$RUNTIME_DIR/backend.log"
FRONTEND_LOG="$RUNTIME_DIR/frontend.log"

usage() {
  cat <<EOF
Usage: ./scripts/start-local.sh

Environment:
  BACKEND_PORT   Backend port, default 8000
  FRONTEND_PORT  Frontend port, default 5173
  HOST           Bind host, default 127.0.0.1

Examples:
  ./scripts/start-local.sh
  BACKEND_PORT=8001 FRONTEND_PORT=5174 ./scripts/start-local.sh

Stop:
  ./scripts/stop-local.sh
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

pid_is_alive() {
  local pid="${1:-}"
  [[ -n "$pid" ]] && kill -0 "$pid" >/dev/null 2>&1
}

read_pid() {
  local file="$1"
  [[ -f "$file" ]] && tr -d '[:space:]' < "$file" || true
}

check_existing_service() {
  local name="$1"
  local pid_file="$2"
  local pid
  pid="$(read_pid "$pid_file")"
  if pid_is_alive "$pid"; then
    echo "$name is already running with PID $pid."
    return 0
  fi
  rm -f "$pid_file"
  return 1
}

port_is_busy() {
  local port="$1"
  command -v lsof >/dev/null 2>&1 && lsof -iTCP:"$port" -sTCP:LISTEN -n -P >/dev/null 2>&1
}

check_port() {
  local port="$1"
  if port_is_busy "$port"; then
    echo "Port $port is already in use."
    echo "Run ./scripts/stop-local.sh, or choose another port with BACKEND_PORT/FRONTEND_PORT."
    exit 1
  fi
}

mkdir -p "$RUNTIME_DIR"

backend_running=0
frontend_running=0
if check_existing_service "Backend" "$BACKEND_PID_FILE"; then
  backend_running=1
fi
if check_existing_service "Frontend" "$FRONTEND_PID_FILE"; then
  frontend_running=1
fi
if [[ "$backend_running" == "1" && "$frontend_running" == "1" ]]; then
  echo
  echo "AI Project Manager MVP is already running."
  echo "Frontend: http://$HOST:$FRONTEND_PORT"
  echo "Backend:  http://$HOST:$BACKEND_PORT/health"
  exit 0
fi

if [[ "$backend_running" == "0" ]]; then
  check_port "$BACKEND_PORT"
fi
if [[ "$frontend_running" == "0" ]]; then
  check_port "$FRONTEND_PORT"
fi

if [[ ! -d "$ROOT_DIR/frontend/node_modules" ]]; then
  echo "Missing frontend/node_modules."
  echo "Install once with: cd frontend && npm install"
  exit 1
fi

if [[ -x "$ROOT_DIR/backend/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT_DIR/backend/.venv/bin/python"
else
  PYTHON_BIN="python3"
fi

if ! "$PYTHON_BIN" -c "import uvicorn" >/dev/null 2>&1; then
  echo "Backend dependencies are missing."
  echo "Install once with:"
  echo "  cd backend"
  echo "  python3 -m venv .venv"
  echo "  source .venv/bin/activate"
  echo "  pip install -r requirements.txt"
  exit 1
fi

cat > "$PORT_FILE" <<EOF
HOST=$HOST
BACKEND_PORT=$BACKEND_PORT
FRONTEND_PORT=$FRONTEND_PORT
EOF

echo "Starting backend on http://$HOST:$BACKEND_PORT ..."
cd "$ROOT_DIR/backend"
nohup "$PYTHON_BIN" -m uvicorn app.main:app --host "$HOST" --port "$BACKEND_PORT" >"$BACKEND_LOG" 2>&1 </dev/null &
BACKEND_PID="$!"
disown "$BACKEND_PID" 2>/dev/null || true
cd "$ROOT_DIR"
if [[ -z "$BACKEND_PID" ]]; then
  BACKEND_PID="$(pgrep -f "uvicorn app.main:app --host $HOST --port $BACKEND_PORT" | head -1 || true)"
fi
echo "$BACKEND_PID" > "$BACKEND_PID_FILE"

echo "Starting frontend on http://$HOST:$FRONTEND_PORT ..."
cd "$ROOT_DIR/frontend"
nohup env VITE_BACKEND_TARGET="http://$HOST:$BACKEND_PORT" npm run dev -- --port "$FRONTEND_PORT" >"$FRONTEND_LOG" 2>&1 </dev/null &
FRONTEND_PID="$!"
disown "$FRONTEND_PID" 2>/dev/null || true
cd "$ROOT_DIR"
if [[ -z "$FRONTEND_PID" ]]; then
  FRONTEND_PID="$(pgrep -f "vite.*--port $FRONTEND_PORT" | head -1 || true)"
fi
echo "$FRONTEND_PID" > "$FRONTEND_PID_FILE"

sleep 2

if ! pid_is_alive "$BACKEND_PID"; then
  echo "Backend failed to start. See: $BACKEND_LOG"
  rm -f "$BACKEND_PID_FILE"
  exit 1
fi

if ! pid_is_alive "$FRONTEND_PID"; then
  echo "Frontend failed to start. See: $FRONTEND_LOG"
  rm -f "$FRONTEND_PID_FILE"
  kill "$BACKEND_PID" >/dev/null 2>&1 || true
  exit 1
fi

echo
echo "AI Project Manager MVP is running."
echo "Frontend: http://$HOST:$FRONTEND_PORT"
echo "Backend:  http://$HOST:$BACKEND_PORT/health"
echo
echo "Logs:"
echo "  Backend:  $BACKEND_LOG"
echo "  Frontend: $FRONTEND_LOG"
echo
echo "Stop with:"
echo "  ./scripts/stop-local.sh"
