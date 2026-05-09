from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials

import config

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
_SPREADSHEET_ID: str = config.SPREADSHEET_ID
_CREDS_DICT: dict = config.GOOGLE_CREDENTIALS_JSON
_TZ = ZoneInfo("Australia/Sydney")

_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

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


def _hours_formula(row: int) -> str:
    """Google Sheets formula: hours worked = set1 + set2 - break."""
    return (
        f'=IF(C{row}<>"",'
        f'(TIMEVALUE(D{row})-TIMEVALUE(C{row}))*24'
        f'+IF(E{row}<>"",(TIMEVALUE(F{row})-TIMEVALUE(E{row}))*24,0)'
        f'-IF(G{row}<>"",TIMEVALUE(G{row})*24,0),"")'
    )


# ---------------------------------------------------------------------------
# Sheet provisioning
# ---------------------------------------------------------------------------

def _setup_totals_row(ws: gspread.Worksheet) -> None:
    """Write =SUM(K:K) into N1 and pay formula into O1 if empty."""
    if not ws.acell("N1").value:
        ws.update_acell("N1", "=SUM(K:K)")
    if not ws.acell("O1").value:
        ws.update_acell("O1", "=N1*24*31.23")


def _provision_week(monday: date) -> bool:
    """
    Provision Mon-Fri rows + summary row for the given monday.
    Returns True if newly provisioned, False if already existed.
    """
    monday_str = monday.strftime("%Y-%m-%d")
    ws = _worksheet()

    col_a = ws.col_values(1)
    if monday_str in col_a:
        return False  # already provisioned

    _setup_totals_row(ws)
    all_rows = ws.get_all_values()
    next_row = max(2, len(all_rows) + 1)  # row 1 reserved for N1/O1 formulas

    rows_data: list[list[str]] = []
    for i, day in enumerate(_WEEKDAYS):
        d = monday + timedelta(days=i)
        row_num = next_row + i
        rows_data.append([
            d.strftime("%Y-%m-%d"),  # A: ISO date (matched by find_today_row)
            day,                      # B: day name
            "", "", "", "", "",       # C-G: filled by bot commands
            "",                       # H: unused
            "",                       # I: filled by Friday cron
            "",                       # J: payment received (/gotpaid)
            _hours_formula(row_num),  # K: auto-calculated hours
        ])

    # Summary row: blank A so find_today_row never accidentally matches it
    rows_data.append(["", "Summary", "", "", "", "", "", "", "", "", ""])

    end_row = next_row + len(rows_data) - 1
    ws.update(rows_data, f"A{next_row}:K{end_row}", raw=False)
    return True


def ensure_current_week_rows() -> None:
    """Append Mon-Fri rows + summary row for current week if absent."""
    _provision_week(_week_monday())


def provision_weeks_ahead(num_weeks: int = 2) -> None:
    """
    Provision current week and the next N weeks automatically.
    Idempotent: safe to call multiple times.
    Useful on startup to pre-create multiple weeks.
    """
    monday = _week_monday()
    for i in range(num_weeks + 1):  # +1 to include current week
        week_monday = monday + timedelta(weeks=i)
        _provision_week(week_monday)


def ensure_next_week_rows() -> None:
    """Provision next week's rows (called by Friday cron)."""
    next_monday = _week_monday() + timedelta(weeks=1)
    _provision_week(next_monday)


# ---------------------------------------------------------------------------
# Row-finding
# ---------------------------------------------------------------------------

def find_today_row() -> int:
    """Return 1-indexed sheet row for today, matched by ISO date in column A."""
    today_str = _today().strftime("%Y-%m-%d")
    col_a = _worksheet().col_values(1)
    for i in range(len(col_a) - 1, -1, -1):
        if col_a[i].strip() == today_str:
            return i + 1
    raise ValueError(f"No row for {today_str}. Is today a weekend?")


def find_previous_week_summary_row() -> int:
    """Return the 1-indexed summary row for last week (never this week's)."""
    prev_monday = _week_monday() - timedelta(days=7)
    prev_monday_str = prev_monday.strftime("%Y-%m-%d")
    ws = _worksheet()
    col_a = ws.col_values(1)

    # New-format weeks: Monday row is identified by date in col A.
    # Summary row is always created 5 rows after Monday.
    for i, val in enumerate(col_a):
        if val.strip() == prev_monday_str:
            return i + 6  # (i+1) = monday 1-indexed, +5 = summary row

    # Old-format fallback: search backwards for non-empty col I but stop
    # before current week starts so we never land on this week's summary.
    monday_str = _week_monday().strftime("%Y-%m-%d")
    current_week_start = next(
        (i for i, v in enumerate(col_a) if v.strip() == monday_str),
        len(col_a),
    )
    col_i = ws.col_values(9)
    for i in range(current_week_start - 1, -1, -1):
        if i < len(col_i) and col_i[i].strip():
            return i + 1

    raise ValueError("No completed previous week found. Make sure last week's hours were logged.")


# ---------------------------------------------------------------------------
# Weekly summary (called by Friday cron)
# ---------------------------------------------------------------------------

def calculate_and_record_week_hours() -> tuple[str, str]:
    """Sum hours for current week, write total to summary row col I. Returns (hours_str, week_label)."""
    monday = _week_monday()
    monday_str = monday.strftime("%Y-%m-%d")
    ws = _worksheet()

    col_a = ws.col_values(1)
    monday_row: int | None = None
    for i, val in enumerate(col_a):
        if val.strip() == monday_str:
            monday_row = i + 1  # 1-indexed
            break

    if monday_row is None:
        raise ValueError("No data for current week.")

    col_k = ws.col_values(11)
    total = 0.0
    for row_idx in range(monday_row - 1, min(monday_row + 4, len(col_k))):
        try:
            total += float(col_k[row_idx])
        except (ValueError, TypeError):
            pass

    # Write total to summary row col I — marks week as complete for /gotpaid
    summary_row = monday_row + 5
    ws.update_cell(summary_row, 9, round(total, 2))

    week_label = monday.strftime("%d %b %Y")
    return f"{total:.2f}", week_label


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

def read_hours_due() -> str:
    value = _worksheet().acell("N1").value
    if not value or not str(value).strip():
        raise ValueError("N1 is empty — send a /time command first to initialise the sheet.")
    return str(value).strip()


def read_payment_due() -> str:
    value = _worksheet().acell("O1").value
    if not value or not str(value).strip():
        raise ValueError("O1 is empty — send a /time command first to initialise the sheet.")
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
