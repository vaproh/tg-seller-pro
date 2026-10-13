# 🤖 TG Seller Bot

A Telegram bot for managing and selling Reddit accounts. Built with python-telegram-bot v21+, SQLite, and APScheduler.

## ✨ Features

- 📦 **Account Management** — Add single, bulk, or CSV import
- 💰 **Selling** — Sell individually or in bulk with receipt generation
- 💳 **Payment Tracking** — Pending/paid status with 4-hour reminders
- 📊 **Inventory** — Real-time stock overview by category and status
- 🔎 **Search** — Multi-filter search by username, category, status
- 📈 **Reports** — Daily, weekly, and custom period revenue reports with charts
- 👥 **Multi-seller** — Admin + seller roles with permission controls
- ⏰ **Scheduled Reports** — Auto daily/weekly reports + pending payment alerts
- 📋 **Activity Logs** — Track all command usage across sellers
- 💸 **Dues Management** — Track and manage seller dues
- 🔄 **Bulk Operations** — Transfer sales, bulk delete, bulk sell

## 🚀 Quick Start

```bash
git clone https://github.com/Vaproh/tg-seller-pro.git
cd tg-seller-pro
./install.sh
```

Then edit `.env` with your `BOT_TOKEN` and `ADMIN_USER_ID`.

```bash
uv run main.py
```

## 🚀 Deployment (VPS)

The bot runs inside a detached tmux session named `tgseller`.

```bash
./deploy.sh                 # pull latest, sync deps, restart the bot
./deploy.sh --watch         # poll GitHub every 60s; pull + restart on new pushes
./deploy.sh --status        # git revision, bot state, watcher service state
./deploy.sh --stop          # stop the bot
```

For unattended auto-deploy that survives reboots, install the systemd watcher:

```bash
sudo ./deploy.sh --install-service
```

Logs: `logs/deploy.log` (watcher) and `logs/bot.log` (bot output).

Env overrides: `BRANCH` (default `main`), `INTERVAL` (default `60`), `SESSION_NAME` (default `tgseller`).

## 📝 Commands

### 📦 Account Management
| Command | Description |
|---------|-------------|
| `/add` | Add single account (step-by-step wizard) |
| `/bulkadd` | Bulk import (user:pass format) |
| `/extractcsv` | Import from CSV file |
| `/delete` | Delete account (by ID or filter) |
| `/bulkdelete` | Bulk delete by IDs or category |
| `/getid <id>` | View account details |

### 🔍 Browsing
| Command | Description |
|---------|-------------|
| `/list` | Browse accounts with filters |
| `/search` | Search with multi-filters |
| `/inventory` | Stock overview |
| `/preview` | Show accounts to buyer |

### 💰 Selling
| Command | Description |
|---------|-------------|
| `/sell` | Sell one or more accounts |
| `/sample` | Generate account previews for buyers |
| `/sales` | View all sales |
| `/sale <id>` | View sale detail |
| `/markpaid` | Mark pending sale as paid |
| `/voidsale` | Cancel a sale (admin) |
| `/editsale` | Edit sale details |

### 🔴 Status Management
| Command | Description |
|---------|-------------|
| `/marksold <id,id,...>` | Mark account(s) as sold |
| `/markunsold <id,id,...>` | Mark account(s) as available |
| `/markpendingpayment <id,id,...>` | Mark as pending payment |

### 📂 Categories
| Command | Description |
|---------|-------------|
| `/categories` | List all categories |
| `/addcategory <name>` | Create category |
| `/deletecategory <name>` | Delete category |

### 👥 Team
| Command | Description |
|---------|-------------|
| `/addseller <id> <name>` | Register seller (admin) |
| `/removeseller <id>` | Remove seller (admin) |
| `/listsellers` | List all sellers |
| `/transfersales` | Transfer sales between sellers (admin) |

### 💸 Dues
| Command | Description |
|---------|-------------|
| `/dues` | View dues balance |
| `/duesadd` | Add due amount |
| `/duesremove` | Remove due amount |

### 🛠️ Admin
| Command | Description |
|---------|-------------|
| `/export` | Download CSV |
| `/backup` | Download database |
| `/report` | Revenue reports |
| `/stats` | Revenue stats with charts |
| `/logs` | View command activity |
| `/help` | Help with inline topic browser |

## 📊 Account Statuses

| Status | Meaning |
|--------|---------|
| 🟢 `available` | Ready to sell |
| 🔴 `sold` | Already sold |
| 🟡 `pending_payment` | Sold, waiting for payment |

## ⚙️ Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `BOT_TOKEN` | ✅ | — | Telegram bot token |
| `ADMIN_USER_ID` | ✅ | — | Admin Telegram ID |
| `DAILY_REPORT_HOUR` | ❌ | `9` | Hour for daily report |
| `WEEKLY_REPORT_DAY` | ❌ | `monday` | Day for weekly report |
| `TIMEZONE` | ❌ | `Asia/Kolkata` | Timezone |

## 🧪 Testing

```bash
uv run pytest tests/ -v
```

## 📁 Project Structure

```
├── main.py                 # 🚀 Entry point
├── config.py               # ⚙️ Environment config
├── install.sh              # 📥 Install script
├── deploy.sh               # 🚀 Deploy / auto-deploy watcher
├── scripts/                # 🔁 start_bot.sh / stop_bot.sh
├── pyproject.toml          # 📦 Dependencies (uv)
├── justfile                # 🔧 Task runner
├── .env.example            # 📝 Env template
├── bot.md                  # 📖 Full documentation
├── database/               # 💾 SQLite database layer
│   ├── connection.py       #    DB connection + migrations
│   ├── categories.py       #    Category CRUD
│   ├── accounts.py         #    Account CRUD + search
│   ├── sales.py            #    Sale CRUD + revenue
│   ├── sellers.py          #    Seller CRUD
│   ├── dues.py             #    Dues tracking
│   ├── logs.py             #    Command activity logs
│   └── sessions.py         #    Legacy retrieval sessions
├── handlers/               # 🤖 Telegram command handlers
│   ├── callbacks/          #    Button handlers
│   ├── messages.py         #    Free-text input
│   ├── sell.py             #    Sell flow
│   ├── accounts.py         #    Add/delete/list
│   ├── logs.py             #    Activity logs
│   ├── dues.py             #    Dues management
│   └── ...
├── core/                   # 🔧 Shared utilities
│   ├── filters.py          #    Filter system
│   ├── format.py           #    Text formatting
│   ├── keyboards.py        #    Inline keyboards
│   ├── permissions.py      #    Role checks
│   ├── state.py            #    State manager
│   └── help_content.py     #    Help text
├── utils/                  # 🛠️ Utilities
│   ├── scheduler.py        #    APScheduler jobs
│   ├── notifications.py    #    Admin notifications
│   ├── csv_utils.py        #    CSV import/export
│   └── parsers.py          #    Input parsers
└── tests/                  # 🧪 pytest test suite
    ├── conftest.py         #    Test fixtures
    └── test_*.py           #    Test modules
```

## 📄 License

Private use only.
