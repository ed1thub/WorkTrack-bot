# WorkTrack Bot

WorkTrack Bot is a serverless FastAPI backend for Telegram that receives a signed webhook, verifies the sender, and writes work-tracking data into a private Google Sheet.

## What it does

- Accepts Telegram webhook updates on `/api/webhook`
- Verifies the `X-Telegram-Bot-Api-Secret-Token` header
- Ignores any chat that is not the configured admin chat ID
- Supports time, break, payment, hours due, and payment due commands
- Exposes a simple health check at `/api/health`

## Environment

Create a local `.env` from the example file:

```bash
cp .env.example .env
```

Required variables:

- `TELEGRAM_BOT_TOKEN` - Telegram bot token from BotFather
- `TELEGRAM_SECRET_TOKEN` - Random webhook secret used by Telegram
- `ADMIN_CHAT_ID` - Your personal Telegram chat ID
- `GOOGLE_CREDENTIALS_JSON` - Service account JSON, stored as a single-line JSON string
- `SPREADSHEET_ID` or `GOOGLE_SHEET_ID` - Google Sheet key

## Local development

Install dependencies with:

```bash
pip install -r requirements.txt
```

Run the app with your preferred ASGI server. For example:

```bash
uvicorn api.index:app --reload
```

## Deployment notes

- Vercel uses `api/index.py` as the serverless entry point
- The repo intentionally ignores `.env`, `.vercel/`, and local Claude settings
- The webhook only accepts the configured Telegram secret token and admin chat ID

## Security posture

The application keeps secret handling centralized in `api/config.py`, validates webhook requests before command processing, and rejects malformed command input before writing to Google Sheets.