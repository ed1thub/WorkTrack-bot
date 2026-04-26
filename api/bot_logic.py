import asyncio
import re
from decimal import Decimal, InvalidOperation

import httpx

import config
import sheets_client

_TOKEN: str = config.TELEGRAM_BOT_TOKEN
_TELEGRAM_API = f"https://api.telegram.org/bot{_TOKEN}"

_TIME_RANGE_RE = re.compile(
    r"^(\d{1,2}):([0-5]\d)(AM|PM)-(\d{1,2}):([0-5]\d)(AM|PM)$",
    re.IGNORECASE,
)
_BREAK_RE = re.compile(r"^(\d{2}):(\d{2})$")
_AMOUNT_RE = re.compile(r"^\d+(?:\.\d{1,2})?$")


# ---------------------------------------------------------------------------
# Telegram reply sender
# ---------------------------------------------------------------------------

async def _reply(chat_id: int, text: str) -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(
            f"{_TELEGRAM_API}/sendMessage",
            json={"chat_id": chat_id, "text": text},
        )
        r.raise_for_status()


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

async def _cmd_time(chat_id: int, arg: str, *, set2: bool = False) -> None:
    m = _TIME_RANGE_RE.match(arg.strip())
    if not m:
        await _reply(chat_id, "Invalid format. Example: /time 1:30PM-8:00PM")
        return

    start_hour = int(m.group(1))
    end_hour = int(m.group(4))
    if not (1 <= start_hour <= 12 and 1 <= end_hour <= 12):
        await _reply(chat_id, "Invalid time. Hours must be between 1 and 12.")
        return

    start = f"{start_hour}:{m.group(2)}{m.group(3).upper()}"
    end = f"{end_hour}:{m.group(5)}{m.group(6).upper()}"
    row = await asyncio.to_thread(sheets_client.find_today_row)
    if set2:
        await asyncio.to_thread(sheets_client.write_time_set2, row, start, end)
        await _reply(chat_id, f"Set 2 logged: {start} - {end}")
    else:
        await asyncio.to_thread(sheets_client.write_time_set1, row, start, end)
        await _reply(chat_id, f"Time logged: {start} - {end}")


async def _cmd_break(chat_id: int, arg: str) -> None:
    arg = arg.strip()
    m = _BREAK_RE.match(arg)
    if not m:
        await _reply(chat_id, "Invalid format. Use HH:MM — e.g. /break 00:30")
        return
    if int(m.group(2)) > 59:
        await _reply(chat_id, "Invalid break duration. Minutes must be between 00 and 59.")
        return
    if int(m.group(1)) > 23:
        await _reply(chat_id, "Invalid break duration. Hours must be between 00 and 23.")
        return
    row = await asyncio.to_thread(sheets_client.find_today_row)
    await asyncio.to_thread(sheets_client.write_break, row, arg)
    await _reply(chat_id, f"Break logged: {arg}")


async def _cmd_got_paid(chat_id: int, arg: str) -> None:
    raw_amount = arg.strip()
    clean_amount = raw_amount.replace("$", "").replace(",", "")
    if not _AMOUNT_RE.fullmatch(clean_amount):
        await _reply(chat_id, "Error: Could not read the amount. Please check your formatting.")
        return
    try:
        formatted = f"{Decimal(clean_amount):.2f}"
    except InvalidOperation:
        await _reply(chat_id, "Error: Could not read the amount. Please check your formatting.")
        return
    row = await asyncio.to_thread(sheets_client.find_previous_week_summary_row)
    await asyncio.to_thread(sheets_client.write_got_paid, row, formatted)
    await _reply(chat_id, f"Payment recorded: ${formatted}")


async def _cmd_hours_due(chat_id: int) -> None:
    hours = await asyncio.to_thread(sheets_client.read_hours_due)
    await _reply(chat_id, f"Hours due: {hours}")


async def _cmd_payment_due(chat_id: int) -> None:
    total = await asyncio.to_thread(sheets_client.read_payment_due)
    await _reply(chat_id, f"Payment due: ${total}")


# ---------------------------------------------------------------------------
# Command dispatch table
# ---------------------------------------------------------------------------

_COMMANDS = {
    "/time":           lambda c, a: _cmd_time(c, a),
    "/timeupdateset1": lambda c, a: _cmd_time(c, a),
    "/timeupdateset2": lambda c, a: _cmd_time(c, a, set2=True),
    "/break":          _cmd_break,
    "/gotpaid":        _cmd_got_paid,
    "/hoursdue":       lambda c, _: _cmd_hours_due(c),
    "/paymentdue":     lambda c, _: _cmd_payment_due(c),
}


async def handle(chat_id: int, text: str) -> None:
    """Entry point called by the webhook handler for every verified admin message."""
    text = text.strip()
    if not text.startswith("/"):
        return

    # Telegram appends bot username in group chats: /cmd@BotName arg → /cmd
    parts = text.split(None, 1)
    command = parts[0].split("@")[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    handler = _COMMANDS.get(command)
    if handler is None:
        return

    try:
        await handler(chat_id, arg)
    except ValueError as e:
        await _reply(chat_id, str(e))
    except Exception:
        await _reply(chat_id, "Something went wrong. Please try again.")
