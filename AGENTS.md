# AGENTS.md — tg-seller-pro

## What this is
Telegram bot for selling Reddit accounts. python-telegram-bot v21+, SQLite (`data/reddit_accounts.db`), APScheduler. Full domain docs in `bot.md` — read it before changing flows.

## Commands
- `just run` / `uv run main.py` — polling bot
- `just test` / `uv run pytest tests/ -v` — tests (note: `tests/test_database.py` has a pre-existing collection error, unrelated `update_account_optional_fields` import)
- `uv run python -m py_compile <file>` — syntax check

## Conventions
- `uv` for env/deps. States via `core/state.py` (5-min TTL). Copyable values use `core/format.py:code()`.
- Roles in `core/permissions.py`: admin (`ADMIN_USER_ID`) + sellers (`/addseller`). Sellers own their sales; admin bypasses.
- Sell flow ends in `handlers/callbacks/sell.py:sellconfirm` — single receipt edit + trailing `/pay` hint message, bulk receipts + status edit + trailing `/pay A, B, ...` hint. Notification failures must fall back to visible chat messages, never silent `pass` with only a log.
- `tg-payment-pro` (sibling repo) shares this DB file and auto-marks sales `paid` via webhooks. Don't break `sale_code` uniqueness or `sales`/`accounts` status transitions (`available`/`pending_payment`/`sold`, `pending`/`paid`).
- Never commit `.env`, `data/`, `logs/`, `.venv/`.
