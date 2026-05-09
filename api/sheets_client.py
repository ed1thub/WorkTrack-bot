from datetime import datetime, date, timedelta
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


def _today() -> date:
    return datetime.now(_TZ).date()


def _week_monday(d: date | None = None) -> date:
    if d is None:
        d = _today()
    return d - timedelta(days=d.weekday())


def _week_range_str(monday: date) -> str:
    """Col A display value: 'DD/MM - DD/MM' (Mon to Sun)."""
    sunday = monday + timedelta(days=6)
    return f"{monday.strftime('%d/%m')} - {sunday.strftime('%d/%m')}"


# ---------------------------------------------------------------------------
# Row-finding
# ---------------------------------------------------------------------------

def find_today_row() -> int:
    """Return 1-indexed row for today, matched by week range in col A + weekday offset."""
    today = _today()
    if today.weekday() >= 5:
        raise ValueError("Today is a weekend. Commands only work Mon–Fri.")
    monday = _week_monday(today)
    week_range = _week_range_str(monday)
    col_a = _worksheet().col_values(1)
    for i, val in enumerate(col_a):
        if val.strip() == week_range:
            return i + 1 + today.weekday()  # Monday row + weekday offset
    raise ValueError(
        f"No row found for this week ({week_range}). "
        "Add this week's rows to the sheet first."
    )


def find_previous_week_summary_row() -> int:
    """Return 1-indexed summary row for last week."""
    prev_monday = _week_monday() - timedelta(days=7)
    prev_monday_str = prev_monday.strftime("%Y-%m-%d")
    prev_range = _week_range_str(prev_monday)
    ws = _worksheet()
    col_a = ws.col_values(1)

    # Bot-provisioned weeks have "S:YYYY-MM-DD" marker in col A.
    for i, val in enumerate(col_a):
        if val.strip() == f"S:{prev_monday_str}":
            return i + 1

    # Manually created weeks: week range in col A on Monday row; summary is Mon+5.
    for i, val in enumerate(col_a):
        if val.strip() == prev_range:
            return i + 6  # Monday row (i+1) + 5 weekday rows = summary

    raise ValueError(
        f"No data found for week of {prev_monday.strftime('%d %b %Y')}. "
        "Add last week's rows to the sheet first."
    )


# ---------------------------------------------------------------------------
# Weekly summary (called by Friday cron)
# ---------------------------------------------------------------------------

def calculate_and_record_week_hours() -> tuple[str, str]:
    """Sum worked hours (col H) for current week. Returns (hours_str, week_label)."""
    monday = _week_monday()
    week_range = _week_range_str(monday)
    ws = _worksheet()

    col_a = ws.col_values(1)
    monday_row: int | None = None
    for i, val in enumerate(col_a):
        if val.strip() == week_range:
            monday_row = i + 1
            break

    if monday_row is None:
        raise ValueError("No rows found for current week in the sheet.")

    col_h = ws.col_values(8)
    total = 0.0
    for row_idx in range(monday_row - 1, min(monday_row + 4, len(col_h))):
        try:
            total += float(col_h[row_idx])
        except (ValueError, TypeError):
            pass

    week_label = monday.strftime("%d %b %Y")
    return f"{total:.2f}", week_label


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

def read_hours_due() -> str:
    value = _worksheet().acell("N1").value
    if not value or not str(value).strip():
        raise ValueError("N1 is empty — no hours recorded yet.")
    return str(value).strip()


def read_payment_due() -> str:
    value = _worksheet().acell("O1").value
    if not value or not str(value).strip():
        raise ValueError("O1 is empty — no hours recorded yet.")
    return str(value).strip().replace("$", "").replace(",", "")


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
