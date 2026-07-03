#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_URL="${FRONTEND_URL:-http://127.0.0.1:5173}"
SESSION="${PLAYWRIGHT_SESSION:-ai-pm-smoke}"
PWCLI="${PWCLI:-$HOME/.codex/skills/playwright/scripts/playwright_cli.sh}"
SMOKE_SCRIPT="$ROOT_DIR/output/playwright/today-core-flow.js"

if [ ! -x "$PWCLI" ]; then
  echo "Playwright CLI wrapper not found: $PWCLI"
  exit 1
fi

if [ ! -f "$SMOKE_SCRIPT" ]; then
  echo "Smoke script not found: $SMOKE_SCRIPT"
  exit 1
fi

mkdir -p "$ROOT_DIR/output/playwright"

echo "Opening $FRONTEND_URL in Playwright session: $SESSION"
"$PWCLI" --session "$SESSION" open "$FRONTEND_URL"

echo "Running core MVP smoke flow..."
SMOKE_OUTPUT="$(
  cd "$ROOT_DIR"
  "$PWCLI" --session "$SESSION" run-code --filename "$SMOKE_SCRIPT" 2>&1
)"
printf '%s\n' "$SMOKE_OUTPUT"

if grep -q "### Error" <<<"$SMOKE_OUTPUT"; then
  echo "Smoke flow failed."
  exit 1
fi

if grep -q '"ok":false' <<<"$SMOKE_OUTPUT"; then
  echo "Smoke flow completed with failed checks."
  exit 1
fi

echo
echo "Smoke flow finished. To clean generated DB records afterward, run:"
echo "  python3 scripts/reset-demo-data.py --smoke-only --yes --keep-files"
