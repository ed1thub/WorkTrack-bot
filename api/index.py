import hmac
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

sys.path.insert(0, str(Path(__file__).parent))

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse

import config
import bot_logic
import db
import security

_ADMIN_CHAT_ID: int = config.ADMIN_CHAT_ID


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    await db.init_db()
    yield
    await db.close_pool()


app = FastAPI(docs_url=None, redoc_url=None, lifespan=lifespan)


# ---------------------------------------------------------------------------
# Dependency: secret token guard
# ---------------------------------------------------------------------------

async def _require_valid_token(request: Request) -> None:
    header = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if not security.verify_token(header):
        raise HTTPException(status_code=401, detail="Unauthorized")


# ---------------------------------------------------------------------------
# Payload extraction helper
# ---------------------------------------------------------------------------

def _extract_message(payload: dict) -> tuple[int, str] | None:
    """Return (chat_id, text) or None for non-text / unsupported update types."""
    try:
        msg = payload["message"]
        text = msg.get("text")
        if not text:
            return None
        return msg["chat"]["id"], text
    except (KeyError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/api/webhook", status_code=200)
async def receive_webhook(
    request: Request,
    _: None = Depends(_require_valid_token),
) -> dict:
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    message = _extract_message(payload)
    if message is None:
        return {"status": "ignored"}

    chat_id, text = message
    if chat_id != _ADMIN_CHAT_ID:
        return {"status": "ignored"}

    await bot_logic.handle(chat_id, text)
    return {"status": "ok"}


@app.get("/api/cron/weekly-summary", status_code=200)
async def weekly_summary_cron(request: Request) -> dict:
    """Called by Vercel cron every Friday at 11:30 PM AEST (13:30 UTC)."""
    if config.CRON_SECRET:
        auth = request.headers.get("Authorization", "")
        expected = f"Bearer {config.CRON_SECRET}"
        if not hmac.compare_digest(auth, expected):
            raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        await bot_logic.send_weekly_summary()
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}

    return {"status": "ok"}


@app.get("/privacy")
async def privacy_policy() -> HTMLResponse:
    html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Privacy Policy – WorkTrack Bot</title>
  <style>
    body { font-family: sans-serif; max-width: 680px; margin: 60px auto; padding: 0 24px; color: #222; line-height: 1.7; }
    h1 { font-size: 1.6rem; margin-bottom: 4px; }
    h2 { font-size: 1.1rem; margin-top: 2rem; }
    p, li { font-size: 0.97rem; }
    a { color: #0070f3; }
    footer { margin-top: 3rem; font-size: 0.85rem; color: #888; }
  </style>
</head>
<body>
  <h1>Privacy Policy</h1>
  <p><strong>WorkTrack Bot</strong> &mdash; Last updated: May 2026</p>

  <h2>What this app does</h2>
  <p>WorkTrack Bot is a personal productivity tool that receives Telegram messages from a single authorised user and records work-hour data (shift times, breaks, and payments) to a private PostgreSQL database and, when enabled, a private Google Sheet.</p>

  <h2>Data collected</h2>
  <ul>
    <li><strong>Telegram messages</strong> &mdash; only slash-command messages from the authorised chat ID are processed. All other messages are discarded immediately without storage.</li>
    <li><strong>Work-hour data</strong> &mdash; shift start/end times, break durations, and payment amounts are stored in a private database and optionally mirrored to a Google Sheet controlled by the owner.</li>
  </ul>

  <h2>Data sharing</h2>
  <p>No data is sold, shared, or disclosed to any third party. The only external services used are:</p>
  <ul>
    <li><strong>Telegram Bot API</strong> &mdash; to receive and send messages.</li>
    <li><strong>Neon (PostgreSQL)</strong> &mdash; to persist work-hour records in a private database.</li>
    <li><strong>Google Sheets</strong> &mdash; to mirror work-hour records into a private spreadsheet when sheet sync is configured.</li>
  </ul>

  <h2>Data retention</h2>
  <p>Data is stored in a private PostgreSQL database and optionally mirrored to a private Google Sheet controlled by the owner. Message content is processed in memory and not logged beyond the storage writes triggered by commands.</p>

  <h2>Security</h2>
  <p>All incoming webhook requests are verified using the X-Telegram-Bot-Api-Secret-Token header. Only messages from the registered authorised chat ID are acted upon. The database connection uses TLS encryption.</p>

  <h2>Contact</h2>
  <p>For any questions about this policy, contact: <a href="mailto:www.siamhasan189@gmail.com">www.siamhasan189@gmail.com</a></p>

  <footer>&copy; 2026 WorkTrack Bot. All rights reserved.</footer>
</body>
</html>"""
    return HTMLResponse(content=html)
