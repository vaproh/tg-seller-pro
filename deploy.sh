#!/usr/bin/env bash
set -euo pipefail

# TG Seller Bot deploy script.
#   ./deploy.sh                  pull latest, sync deps, restart the bot in tmux
#   ./deploy.sh --watch          poll GitHub and auto-redeploy on new commits (keeps bot alive)
#   ./deploy.sh --stop           stop the bot
#   ./deploy.sh --status         show git revision, tmux state, service state
#   ./deploy.sh --install-service  install+enable the systemd watcher (auto-start on boot)
#
# Env overrides: BRANCH (main), SESSION_NAME (tgseller), INTERVAL (60), REMOTE (origin)

export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${ROOT_DIR}"

BRANCH="${BRANCH:-main}"
REMOTE="${REMOTE:-origin}"
SESSION_NAME="${SESSION_NAME:-tgseller}"
INTERVAL="${INTERVAL:-60}"
SERVICE_NAME="tg-seller-autodeploy.service"

mkdir -p logs
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a logs/deploy.log; }

start_bot() { "${ROOT_DIR}/scripts/start_bot.sh"; }
stop_bot()  { "${ROOT_DIR}/scripts/stop_bot.sh"; }

# Returns 0 if this checkout was updated to the newest commit on ${REMOTE}/${BRANCH}.
pull_latest() {
    if ! git fetch "${REMOTE}" "${BRANCH}" --quiet; then
        log "git fetch failed — skipping"
        return 1
    fi
    local local_rev remote_rev
    local_rev="$(git rev-parse HEAD)"
    remote_rev="$(git rev-parse "${REMOTE}/${BRANCH}")"
    [ "${local_rev}" = "${remote_rev}" ] && return 1

    git checkout "${BRANCH}" --quiet 2>/dev/null || true
    stop_bot
    if ! git pull --ff-only "${REMOTE}" "${BRANCH}"; then
        log "git pull failed (local changes?) — restarting on current checkout"
        start_bot
        return 1
    fi
    if ! uv sync; then
        log "uv sync failed — restarting on current checkout"
        start_bot
        return 1
    fi
    return 0
}

deploy() {
    if pull_latest; then
        log "Updated to $(git rev-parse --short HEAD) — restarting bot"
    else
        log "Already up to date ($(git rev-parse --short HEAD)) — restarting bot"
    fi
    start_bot
}

watch() {
    log "Auto-deploy watching ${REMOTE}/${BRANCH} every ${INTERVAL}s (Ctrl-C to stop)"
    while true; do
        if ! tmux has-session -t "${SESSION_NAME}" 2>/dev/null; then
            log "Bot not running — starting it"
            start_bot
        fi
        if pull_latest; then
            log "New commit $(git rev-parse --short HEAD) — redeployed"
            start_bot
        fi
        sleep "${INTERVAL}"
    done
}

status() {
    echo "Revision : $(git rev-parse --short HEAD) ($(git rev-parse --abbrev-ref HEAD))"
    echo "Remote   : ${REMOTE}/${BRANCH} = $(git rev-parse --short "${REMOTE}/${BRANCH}" 2>/dev/null || echo unknown)"
    if tmux has-session -t "${SESSION_NAME}" 2>/dev/null; then
        echo "Bot      : RUNNING (attach: tmux attach -t ${SESSION_NAME})"
    else
        echo "Bot      : STOPPED"
    fi
    local svc_state
    svc_state="$(systemctl is-active "${SERVICE_NAME}" 2>/dev/null || true)"
    echo "Service  : ${svc_state:-unknown}"
}

install_service() {
    local service_file="/etc/systemd/system/${SERVICE_NAME}"

    # Run as the user who owns the repo (has uv + the GitHub SSH key), not root.
    local run_user run_group run_home
    if [ -n "${SUDO_USER:-}" ] && [ "${SUDO_USER}" != "root" ]; then
        run_user="${SUDO_USER}"
    else
        run_user="$(stat -c '%U' "${ROOT_DIR}")"
    fi
    run_group="$(id -gn "${run_user}" 2>/dev/null || echo "${run_user}")"
    run_home="$(getent passwd "${run_user}" | cut -d: -f6)"
    [ -n "${run_home}" ] || run_home="${HOME}"

    local unit
    unit=$(cat <<EOF
[Unit]
Description=TG Seller auto-deploy watcher
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${run_user}
Group=${run_group}
Environment=HOME=${run_home}
WorkingDirectory=${ROOT_DIR}
ExecStart=/bin/bash ${ROOT_DIR}/deploy.sh --watch
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
)

    if [ "${EUID}" -eq 0 ]; then
        printf '%s\n' "${unit}" > "${service_file}"
        systemctl daemon-reload
        systemctl enable --now "${SERVICE_NAME}"
        # let git trust the repo even if it is owned by a different user
        runuser -u "${run_user}" -- git config --global --add safe.directory "${ROOT_DIR}" 2>/dev/null || true
        log "Service '${SERVICE_NAME}' installed and started as ${run_user}."
    elif command -v sudo &>/dev/null && sudo -n true 2>/dev/null; then
        printf '%s\n' "${unit}" | sudo tee "${service_file}" >/dev/null
        sudo systemctl daemon-reload
        sudo systemctl enable --now "${SERVICE_NAME}"
        sudo -u "${run_user}" git config --global --add safe.directory "${ROOT_DIR}" 2>/dev/null || true
        log "Service '${SERVICE_NAME}' installed and started as ${run_user}."
    else
        echo "Need root to install the systemd service. Run:"
        echo "  sudo ./deploy.sh --install-service"
        exit 1
    fi
}

case "${1:-}" in
    --watch)           watch ;;
    --stop)            stop_bot ;;
    --status)          status ;;
    --install-service) install_service ;;
    --help|-h)
        sed -n '3,10p' "$0"
        ;;
    "")                deploy ;;
    *)                 echo "Unknown option: $1 (try --help)"; exit 1 ;;
esac
