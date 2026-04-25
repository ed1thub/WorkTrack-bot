import json
import os
import sys
from pathlib import Path

# Ensure sibling modules (security, sheets_client, bot_logic) are importable
# both on Vercel and when running locally with `uvicorn api.index:app`.
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

# Load env before importing sibling modules that read os.environ at import time.
load_dotenv()

import bot_logic
import security

_VERIFY_TOKEN: str = os.environ["VERIFY_TOKEN"]


def _normalize_phone(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())


# WhatsApp payloads can vary in formatting; compare normalized digit-only values.
_ADMIN_PHONE: str = _normalize_phone(os.environ["ADMIN_PHONE_NUMBER"])

app = FastAPI(docs_url=None, redoc_url=None)


# ---------------------------------------------------------------------------
# Dependency: HMAC-SHA256 signature guard
# ---------------------------------------------------------------------------

async def _require_valid_signature(request: Request) -> bytes:
    raw_body = await request.body()
    sig_header = request.headers.get("X-Hub-Signature-256")
    if not security.verify_signature(raw_body, sig_header):
        raise HTTPException(status_code=403, detail="Forbidden")
    return raw_body


# ---------------------------------------------------------------------------
# Payload extraction helper
# ---------------------------------------------------------------------------

def _extract_text_message(payload: dict) -> tuple[str, str] | None:
    """Return (sender_phone, message_text) or None for non-text / status events."""
    try:
        value = payload["entry"][0]["changes"][0]["value"]
        messages = value.get("messages")
        if not messages:
            return None
        msg = messages[0]
        if msg.get("type") != "text":
            return None
        return msg["from"], msg["text"]["body"]
    except (KeyError, IndexError):
        return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/api/webhook")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
) -> PlainTextResponse:
    if hub_mode == "subscribe" and hub_verify_token == _VERIFY_TOKEN:
        return PlainTextResponse(content=hub_challenge)
    raise HTTPException(status_code=403, detail="Forbidden")


@app.post("/api/webhook", status_code=200)
async def receive_webhook(
    raw_body: bytes = Depends(_require_valid_signature),
) -> dict:
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid payload")

    message = _extract_text_message(payload)
    if message is None:
        # Status updates (delivered / read) and non-text events: acknowledge
        # silently. Meta retries indefinitely on any non-200 response.
        return {"status": "ignored"}

    sender, text = message
    if _normalize_phone(sender) != _ADMIN_PHONE:
        return {"status": "ignored"}

    await bot_logic.handle(sender, text)
    return {"status": "ok"}
