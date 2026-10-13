#!/usr/bin/env bash
set -euo pipefail

# Start the bot in a detached tmux session (clean restart).
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

SESSION_NAME="${SESSION_NAME:-tgseller}"

mkdir -p logs

if tmux has-session -t "${SESSION_NAME}" 2>/dev/null; then
    tmux kill-session -t "${SESSION_NAME}" 2>/dev/null || true
fi
pkill -f "uv run main.py" 2>/dev/null || true
sleep 1

tmux new-session -d -s "${SESSION_NAME}" -n bot \
    "bash -c 'uv run main.py 2>&1 | tee -a logs/bot.log'"

echo "==> Bot started in tmux session '${SESSION_NAME}' (attach: tmux attach -t ${SESSION_NAME})"
