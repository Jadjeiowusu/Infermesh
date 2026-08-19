#!/usr/bin/env bash
# Stops the vLLM server started by launch_vllm_local.sh.

set -euo pipefail

LOG_DIR="${LOG_DIR:-./logs}"
PID_FILE="$LOG_DIR/vllm.pid"

if [[ ! -f "$PID_FILE" ]]; then
    echo "No PID file at $PID_FILE — is vLLM running? (check: ps aux | grep vllm)"
    exit 1
fi

PID=$(cat "$PID_FILE")
if kill -0 "$PID" 2>/dev/null; then
    kill "$PID"
    echo "Sent SIGTERM to PID $PID"
else
    echo "PID $PID from $PID_FILE is not running (already stopped?)"
fi
rm -f "$PID_FILE"
