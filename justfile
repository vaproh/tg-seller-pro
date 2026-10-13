# TG Seller Bot — justfile

# List available commands
default:
    @just --list

# Run the bot
run:
    uv run main.py

# Deploy: pull latest, sync deps, restart bot in tmux
deploy:
    ./deploy.sh

# Auto-deploy: poll GitHub every 60s and redeploy on new pushes
watch:
    ./deploy.sh --watch

# Restart the bot without pulling
restart:
    ./scripts/stop_bot.sh
    ./scripts/start_bot.sh

# Stop the bot
stop:
    ./scripts/stop_bot.sh

# Show git revision, bot and service status
status:
    ./deploy.sh --status

# Install the systemd watcher so auto-deploy survives reboots
install-service:
    ./deploy.sh --install-service

# Run tests
test:
    uv run pytest tests/ -v

# Install/update dependencies
install:
    uv sync

# Add a dependency
add *ARGS:
    uv add {{ ARGS }}

# Remove a dependency
remove *ARGS:
    uv remove {{ ARGS }}

# Format code
fmt:
    uv run python -m black . 2>/dev/null || true
    uv run python -m ruff format . 2>/dev/null || true

# Lint code
lint:
    uv run python -m ruff check . 2>/dev/null || true

# Clean build artifacts, caches, and temp files
clean:
    rm -rf .venv/
    rm -rf __pycache__/ **/__pycache__/
    rm -rf *.pyc **/*.pyc
    rm -rf .pytest_cache/ **/.pytest_cache/
    rm -rf dist/ build/ *.egg-info/
    rm -rf .mypy_cache/
    rm -rf data/*.db-wal data/*.db-shm
    rm -rf logs/*.log
    echo "✨ Cleaned"

# Deep clean (remove everything including DB and env)
clean-all: clean
    rm -rf data/
    rm -rf logs/
    rm -f .env
    echo "🧹 Deep cleaned"

# Format + lint + test (full check)
check: fmt lint test

# Backup database
backup:
    cp data/reddit_seller.db data/reddit_seller.db.bak 2>/dev/null && echo "📦 Backup created" || echo "⚠️ No database found"
