#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG_DIR="$REPO_ROOT/pipeline/logs"
LOG_FILE="$LOG_DIR/if_baseline.log"
PID_FILE="$LOG_DIR/if_baseline.pid"
SCRIPT="$REPO_ROOT/pipeline/scripts/collect_if_baseline.py"
DURATION_S="${IF_BASELINE_DURATION_S:-3600}"

mkdir -p "$LOG_DIR"

if [[ -f "$PID_FILE" ]]; then
  OLD_PID="$(cat "$PID_FILE" || true)"
  if [[ -n "${OLD_PID:-}" ]] && ps -p "$OLD_PID" >/dev/null 2>&1; then
    echo "IF baseline collection already running with PID $OLD_PID"
    exit 1
  fi
fi

echo "Starting clean IF baseline collection for ${DURATION_S}s"
echo "Log file: $LOG_FILE"

nohup python3 -u "$SCRIPT" --duration-seconds "$DURATION_S" >"$LOG_FILE" 2>&1 &
PID=$!
echo "$PID" >"$PID_FILE"

sleep 2
if ! ps -p "$PID" >/dev/null 2>&1; then
  echo "Baseline collector exited immediately. Check $LOG_FILE"
  exit 1
fi

echo "Started PID $PID"
echo "Monitor with: tail -f $LOG_FILE"
