# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run locally
uvicorn api.index:app --reload

# Run a single test
pytest tests/test_bot_logic.py::test_name -v

# Run all tests with coverage
pytest --cov=api --cov-report=term-missing
```

## Architecture

Serverless FastAPI app deployed on Vercel. All routes funnel through `api/index.py` (Vercel entry point via `vercel.json`).

**Request flow:**
```
Telegram → POST /api/webhook
  → _require_valid_token (FastAPI dependency) — hmac.compare_digest on X-Telegram-Bot-Api-Secret-Token
  → admin chat ID gate — silently drops anything not matching ADMIN_CHAT_ID
  → bot_logic.handle() — parses command, dispatches to handler
  → sheets_client — locates row, writes via gspread
  → _reply() — sends response via httpx
```

**Module responsibilities:**

| File | Role |
|------|------|
| `api/config.py` | Validates all env vars at import time; raises `RuntimeError` on missing/invalid values |
| `api/security.py` | Constant-time token comparison (`hmac.compare_digest`) |
| `api/bot_logic.py` | Regex validation per command, `_COMMANDS` dispatch table, Telegram reply sender |
| `api/sheets_client.py` | gspread wrapper; lazy singleton `_ws` reused across warm Vercel invocations |

## Sheet Layout

Fixed column layout assumed in `sheet1`. Timezone hardcoded to `Australia/Sydney`.

| Column | Content |
|--------|---------|
| B | Day name ("Monday" etc.) — used by `find_today_row()` |
| C, D | Set 1 start/end times |
| E, F | Set 2 start/end times |
| G | Break duration (HH:MM) |
| I | Weekly summary — non-empty = completed week (used by `find_previous_week_summary_row()`) |
| J | Payment received |
| N1 | Formula `=SUM(K:K)` — hours due |
| O1 | Formula `=N1*24*31.23` — payment due |

## Supported Commands

| Command | Arg format |
|---------|-----------|
| `/time`, `/timeupdateset1` | `H:MMAM/PM-H:MMAM/PM` → writes cols C/D |
| `/timeupdateset2` | same format → writes cols E/F |
| `/break` | `HH:MM` → writes col G |
| `/gotpaid` | amount (strips `$` and `,`) → writes col J on previous week row |
| `/hoursdue`, `/paymentdue` | no arg — reads N1/O1 |

## Environment Variables

`config.py` fails at startup if any are missing:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_SECRET_TOKEN` — must match what was sent to Telegram's `setWebhook`
- `ADMIN_CHAT_ID` — integer; all other chats silently ignored
- `GOOGLE_CREDENTIALS_JSON` — service account JSON as single-line string
- `SPREADSHEET_ID` or `GOOGLE_SHEET_ID` — Google Sheet document ID

## Key Constraints

- gspread is synchronous — all `sheets_client` calls wrapped in `asyncio.to_thread` in `bot_logic.py`
- FastAPI app disables `/docs` and `/redoc` (`docs_url=None, redoc_url=None`)
- No database; no persistent storage — all state in Google Sheet

## Automated Deployment

Every push to the main branch automatically deploys to Vercel.

### Setup (One-time)

1. **Link Vercel to repository:**
   ```bash
   vercel link
   ```

2. **Create GitHub Actions workflow:**
   Create `.github/workflows/deploy.yml`:
   ```yaml
   name: Deploy to Vercel

   on:
     push:
       branches:
         - main

   jobs:
     deploy:
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v3
         - uses: vercel/action@v5
           with:
             vercel-token: ${{ secrets.VERCEL_TOKEN }}
             vercel-org-id: ${{ secrets.VERCEL_ORG_ID }}
             vercel-project-id: ${{ secrets.VERCEL_PROJECT_ID }}
   ```

3. **Add secrets to GitHub:**
   - Go to repo Settings → Secrets → New repository secret
   - Add: `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID`
   - Get values from [Vercel dashboard](https://vercel.com/account/tokens)

### Workflow

```bash
# Make changes and commit
git add .
git commit -m "feat: update command logic"

# Push to main
git push origin main
# GitHub Actions automatically runs → Vercel deploys → Live in ~30 seconds
```

### Testing Before Push (Optional)

Use a pre-commit hook to run tests locally:
```bash
# Create .git/hooks/pre-commit
#!/bin/bash
pytest --cov=api --cov-report=term-missing
# Make it executable: chmod +x .git/hooks/pre-commit
```
