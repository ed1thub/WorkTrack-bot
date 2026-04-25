import asyncio
import os
import re

import httpx
from dotenv import load_dotenv

import sheets_client

load_dotenv()

_WHATSAPP_TOKEN: str = os.environ["WHATSAPP_TOKEN"]
_PHONE_ID: str = os.environ["WHATSAPP_PHONE_ID"]

_GRAPH_URL = f"https://graph.facebook.com/v17.0/{_PHONE_ID}/messages"

# Regex patterns — validated once at import time.
_TIME_RANGE_RE = re.compile(
    r"^(\d{1,2}):([0-5]\d)(AM|PM)-(\d{1,2}):([0-5]\d)(AM|PM)$",
    re.IGNORECASE,
)
_BREAK_RE = re.compile(r"^(\d{2}):(\d{2})$")
_AMOUNT_RE = re.compile(r"^\d+\.\d{2}$")


# ---------------------------------------------------------------------------
# WhatsApp reply sender
# ---------------------------------------------------------------------------

async def _reply(to: str, body: str) -> None:
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body},
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(
            _GRAPH_URL,
            headers={"Authorization": f"Bearer {_WHATSAPP_TOKEN}"},
            json=payload,
        )
        r.raise_for_status()


# ---------------------------------------------------------------------------
# Hours parsing — column K may be decimal ("12.5") or HH:MM ("12:30").
# ---------------------------------------------------------------------------

def _parse_hours(value: str) -> float:
    value = value.strip().replace(",", "")
    if ":" in value:
        h, m = value.split(":", 1)
        return int(h) + int(m) / 60
    return float(value)


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

async def _cmd_time(sender: str, arg: str, *, set2: bool = False) -> None:
    m = _TIME_RANGE_RE.match(arg.strip())
    if not m:
        await _reply(sender, "Invalid format. Example: /time 1:30PM-8:00PM")
        return

    start_hour = int(m.group(1))
    end_hour = int(m.group(4))
    if not (1 <= start_hour <= 12 and 1 <= end_hour <= 12):
        await _reply(sender, "Invalid time. Hours must be between 1 and 12.")
        return

    start = f"{start_hour}:{m.group(2)}{m.group(3).upper()}"
    end = f"{end_hour}:{m.group(5)}{m.group(6).upper()}"
    row = await asyncio.to_thread(sheets_client.find_today_row)
    if set2:
        await asyncio.to_thread(sheets_client.write_time_set2, row, start, end)
        await _reply(sender, f"Set 2 logged: {start} - {end}")
    else:
        await asyncio.to_thread(sheets_client.write_time_set1, row, start, end)
        await _reply(sender, f"Time logged: {start} - {end}")


async def _cmd_break(sender: str, arg: str) -> None:
    arg = arg.strip()
    m = _BREAK_RE.match(arg)
    if not m:
        await _reply(sender, "Invalid format. Use HH:MM — e.g. /break 00:30")
        return
    if int(m.group(2)) > 59:
        await _reply(sender, "Invalid break duration. Minutes must be between 00 and 59.")
        return
    row = await asyncio.to_thread(sheets_client.find_today_row)
    await asyncio.to_thread(sheets_client.write_break, row, arg)
    await _reply(sender, f"Break logged: {arg}")


async def _cmd_got_paid(sender: str, arg: str) -> None:
    arg = arg.strip()
    if not _AMOUNT_RE.match(arg):
        await _reply(sender, "Invalid format. Example: /gotpaid 475.00")
        return
    row = await asyncio.to_thread(sheets_client.find_previous_week_summary_row)
    await asyncio.to_thread(sheets_client.write_got_paid, row, arg)
    await _reply(sender, f"Payment recorded: ${arg}")


async def _cmd_hours_due(sender: str) -> None:
    hours = await asyncio.to_thread(sheets_client.read_hours_due)
    await _reply(sender, f"Hours due: {hours}")


async def _cmd_payment_due(sender: str) -> None:
    hours_str = await asyncio.to_thread(sheets_client.read_hours_due)
    rate = await asyncio.to_thread(sheets_client.read_rate_value)
    total = _parse_hours(hours_str) * rate
    await _reply(sender, f"Payment due: ${total:.2f}  ({hours_str} hrs @ ${rate:.2f}/hr)")


# ---------------------------------------------------------------------------
# Command dispatch table
# ---------------------------------------------------------------------------

_COMMANDS = {
    "/time":            lambda s, a: _cmd_time(s, a),
    "/timeupdateset1":  lambda s, a: _cmd_time(s, a),
    "/timeupdateset2":  lambda s, a: _cmd_time(s, a, set2=True),
    "/break":           _cmd_break,
    "/gotpaid":         _cmd_got_paid,
    "/hoursdue":        lambda s, _: _cmd_hours_due(s),
    "/paymentdue":      lambda s, _: _cmd_payment_due(s),
}


async def handle(sender: str, text: str) -> None:
    """Entry point called by the webhook handler for every verified admin message."""
    text = text.strip()
    if not text.startswith("/"):
        return

    parts = text.split(None, 1)
    command = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    handler = _COMMANDS.get(command)
    if handler is None:
        return

    try:
        await handler(sender, arg)
    except ValueError as e:
        await _reply(sender, str(e))
    except Exception:
        await _reply(sender, "Something went wrong. Please try again.")
