# WorkTrack Bot

A personal Telegram bot that tracks work hours and payments in a private PostgreSQL database. Built with FastAPI, deployed serverlessly on Vercel.

## Features

- Logs shift times, breaks, and payments via Telegram commands
- Stores all data in a private Neon PostgreSQL database
- Mirrors log changes into a Google Sheets timesheet template
- Calculates unpaid hours and outstanding payment balance
- Weekly summary cron job every Friday night
- Single-user design — only your chat ID can trigger any action

## Commands

| Command | Format | Description |
|---------|--------|-------------|
| `/time1` | `H:MM AM-H:MM PM` | Log today's shift (set 1) |
| `/time2` | `H:MM AM-H:MM PM` | Log a second shift on the same day |
| `/break` | `HH:MM` | Log unpaid break duration |
| `/gotpaid` | `<amount>` | Record last week's payment (e.g. `500` or `$500.00`) |
| `/total` | — | Show total hours worked in the current week so far |
| `/hoursdue` | — | Show hours still owed to you (worked − paid-for) |
| `/paymentdue` | — | Show money still owed to you |
| `/help` | — | List all commands |

## Architecture

```
Telegram
  └─▶ POST /api/webhook
        ├─ Verify X-Telegram-Bot-Api-Secret-Token   (api/security.py)
        ├─ Reject non-admin chat IDs                (api/index.py)
        ├─ Parse and validate command               (api/bot_logic.py)
        ├─ Read/write Neon PostgreSQL               (api/db_client.py)
        └─ Mirror log changes to Google Sheets      (api/sheets_client.py)

Vercel Cron (Friday 11:30 PM AEST)
  └─▶ GET /api/cron/weekly-summary
        └─ Send weekly hours summary via Telegram
```

| Module | Role |
|--------|------|
| `api/index.py` | FastAPI entry point, DB lifespan, route definitions |
| `api/config.py` | Env var validation — raises `RuntimeError` at startup if any are missing |
| `api/security.py` | Constant-time webhook token verification (`hmac.compare_digest`) |
| `api/bot_logic.py` | Regex input validation, command dispatch, Telegram reply sender |
| `api/db.py` | asyncpg connection pool — `init_db()` on startup, `close_pool()` on shutdown |
| `api/db_client.py` | PostgreSQL read/write helpers, hours calculation |
| `api/sheets_client.py` | Optional Google Sheets sync for work logs and payments |
| `api/schema.sql` | Table definitions for `work_entries` and `weekly_payments` |

## Setup

### 1. Clone and install

```bash
git clone https://github.com/ed1thub/WorkTrack-bot.git
cd WorkTrack-bot
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Fill in `.env`:

| Variable | Description |
|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Token from [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_SECRET_TOKEN` | Random string — must match what you pass to Telegram's `setWebhook` |
| `ADMIN_CHAT_ID` | Your personal Telegram chat ID (use [@userinfobot](https://t.me/userinfobot)) |
| `DATABASE_URL` | Neon (or any PostgreSQL) connection string |
| `HOURLY_RATE` | Hourly pay rate (default: `31.23`) |
| `SPREADSHEET_ID` | Optional Google Sheet ID for log syncing |
| `GOOGLE_CREDENTIALS_JSON` | Optional service account JSON for Google Sheets API access |

When Google Sheets sync is enabled, share the spreadsheet with the service account email from `GOOGLE_CREDENTIALS_JSON`.

### 3. Register the webhook

```bash
curl "https://api.telegram.org/bot<TOKEN>/setWebhook" \
  -d "url=https://your-deployment.vercel.app/api/webhook" \
  -d "secret_token=<TELEGRAM_SECRET_TOKEN>"
```

### 4. Run locally

```bash
uvicorn api.index:app --reload
```

## Deployment

Push to `main` — Vercel deploys automatically via its native GitHub integration.

Add the same environment variables to your Vercel project dashboard before deploying.

## Security

- Webhook requests verified with `hmac.compare_digest` before any processing
- Only the configured `ADMIN_CHAT_ID` can trigger any command — all other messages silently dropped
- All data stored in a private, TLS-encrypted PostgreSQL database
- Secrets validated at startup; app refuses to start with missing config

## License

MIT
