from datetime import datetime
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials

import config

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
_SPREADSHEET_ID: str = config.SPREADSHEET_ID
_CREDS_DICT: dict = config.GOOGLE_CREDENTIALS_JSON
_TZ = ZoneInfo("Australia/Sydney")

# Lazily initialised; reused across warm Vercel invocations.
_ws: gspread.Worksheet | None = None


def _worksheet() -> gspread.Worksheet:
    global _ws
    if _ws is None:
        creds = Credentials.from_service_account_info(_CREDS_DICT, scopes=_SCOPES)
        gc = gspread.authorize(creds)
        _ws = gc.open_by_key(_SPREADSHEET_ID).sheet1
    return _ws


# ---------------------------------------------------------------------------
# Row-finding algorithms
# ---------------------------------------------------------------------------

def find_today_row() -> int:
    """Return the 1-indexed sheet row whose column B matches today's day name."""
    today = datetime.now(_TZ).strftime("%A")
    col_b = _worksheet().col_values(2)
    for i in range(len(col_b) - 1, -1, -1):
        if col_b[i].strip() == today:
            return i + 1
    raise ValueError(f"No row found for {today} — is the sheet up to date?")


def find_previous_week_summary_row() -> int:
    """Return the 1-indexed row of the most recent completed week (non-empty col I)."""
    col_i = _worksheet().col_values(9)
    for i in range(len(col_i) - 1, -1, -1):
        if col_i[i].strip():
            return i + 1
    raise ValueError("No completed weekly summary row found in column I.")


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

def read_hours_due() -> str:
    """Return the grand total hours due from cell N1 (=SUM(K:K) formula)."""
    value = _worksheet().acell("N1").value
    if not value or not value.strip():
        raise ValueError("Cell N1 is empty — ensure the =SUM(K:K) formula is in place.")
    return value.strip()


def read_payment_due() -> str:
    """Return the total payment due from cell O1 (=N1*24*31.23 formula)."""
    value = _worksheet().acell("O1").value
    if not value or not value.strip():
        raise ValueError("Cell O1 is empty — ensure the =N1*24*31.23 formula is in place.")
    return value.strip().replace("$", "").replace(",", "")


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------

def write_time_set1(row: int, start: str, end: str) -> None:
    _worksheet().batch_update([
        {"range": f"C{row}", "values": [[start]]},
        {"range": f"D{row}", "values": [[end]]},
    ])


def write_time_set2(row: int, start: str, end: str) -> None:
    _worksheet().batch_update([
        {"range": f"E{row}", "values": [[start]]},
        {"range": f"F{row}", "values": [[end]]},
    ])


def write_break(row: int, duration: str) -> None:
    _worksheet().update_cell(row, 7, duration)


def write_got_paid(row: int, amount: str) -> None:
    _worksheet().update_cell(row, 10, amount)
