# WorkTrack Bot

A personal Telegram bot that tracks work hours and payments in a private Google Sheet. Built with FastAPI, deployed serverlessly on Vercel.

## Features

- Logs shift times, breaks, and payments via Telegram commands
- Stores all data in a private Google Sheet you own
- Weekly summary cron job every Friday night
- Single-user design — only your chat ID can trigger any action

## Commands

| Command | Format | Description |
|---------|--------|-------------|
| `/time` | `H:MM AM-H:MM PM` | Log today's shift (set 1) |
| `/timeupdateset1` | `H:MM AM-H:MM PM` | Same as `/time` |
| `/timeupdateset2` | `H:MM AM-H:MM PM` | Log a second shift on the same day |
| `/break` | `HH:MM` | Log unpaid break duration |
| `/gotpaid` | `<amount>` | Record last week's payment (e.g. `500` or `$500.00`) |
| `/hoursdue` | — | Show total hours worked across all weeks |
| `/paymentdue` | — | Show total payment owed across all weeks |
| `/help` | — | List all commands |

## Architecture

```
Telegram
  └─▶ POST /api/webhook
        ├─ Verify X-Telegram-Bot-Api-Secret-Token   (api/security.py)
        ├─ Reject non-admin chat IDs                (api/index.py)
        ├─ Parse and validate command               (api/bot_logic.py)
        └─ Write to Google Sheet                    (api/sheets_client.py)

Vercel Cron (Friday 11:30 PM AEST)
  └─▶ GET /api/cron/weekly-summary
        └─ Send weekly hours summary via Telegram
```

| Module | Role |
|--------|------|
| `api/index.py` | FastAPI entry point, route definitions |
| `api/config.py` | Env var validation — raises `RuntimeError` at startup if any are missing |
| `api/security.py` | Constant-time webhook token verification (`hmac.compare_digest`) |
| `api/bot_logic.py` | Regex input validation, command dispatch, Telegram reply sender |
| `api/sheets_client.py` | gspread wrapper for reading and writing the Google Sheet |

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
| `GOOGLE_CREDENTIALS_JSON` | Service account JSON as a single-line string |
| `SPREADSHEET_ID` | Google Sheet document ID from its URL |

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
- No database — all data lives in your own Google Sheet
- Secrets validated at startup; app refuses to start with missing config

## License

MIT
