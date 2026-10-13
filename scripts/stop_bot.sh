#!/usr/bin/env bash
set -euo pipefail

SESSION_NAME="${SESSION_NAME:-tgseller}"

if tmux has-session -t "${SESSION_NAME}" 2>/dev/null; then
    tmux kill-session -t "${SESSION_NAME}" 2>/dev/null || true
fi
pkill -f "uv run main.py" 2>/dev/null || true
echo "==> Bot stopped."
