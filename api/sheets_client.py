import json
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

load_dotenv()

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
_SPREADSHEET_ID: str = os.environ.get("SPREADSHEET_ID") or os.environ.get("GOOGLE_SHEET_ID") or ""
_CREDS_DICT: dict = json.loads(os.environ["GOOGLE_CREDENTIALS_JSON"])
_TZ = ZoneInfo("Australia/Sydney")

# Lazily initialised; reused across warm Vercel invocations.
_ws: gspread.Worksheet | None = None


def _worksheet() -> gspread.Worksheet:
    global _ws
    if _ws is None:
        if not _SPREADSHEET_ID:
            raise ValueError("Missing SPREADSHEET_ID (or GOOGLE_SHEET_ID) environment variable.")
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
    """Return the bottom-most non-empty value from column K (Hours Due)."""
    col_k = _worksheet().col_values(11)
    for i in range(len(col_k) - 1, -1, -1):
        if col_k[i].strip():
            return col_k[i].strip()
    raise ValueError("No value found in column K (Hours Due).")


def read_rate_value() -> float:
    """Return the hourly rate from the bottom-most non-empty cell in column M."""
    col_m = _worksheet().col_values(13)
    for i in range(len(col_m) - 1, -1, -1):
        if col_m[i].strip():
            cleaned = re.sub(r"[^0-9.\-]", "", col_m[i].strip())
            if cleaned:
                return float(cleaned)
    raise ValueError("No rate value found in column M.")


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
