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


def _week_range_str(monday: date) -> str:
    """Display string for col A: 'DD/MM - DD/MM' (Mon to Sun)."""
    sunday = monday + timedelta(days=6)
    return f"{monday.strftime('%d/%m')} - {sunday.strftime('%d/%m')}"


def _hours_formula(row: int) -> str:
    """Col H: daily worked hours = set1 + set2 - break."""
    return (
        f'=IF(C{row}<>"",'
        f'(TIMEVALUE(D{row})-TIMEVALUE(C{row}))*24'
        f'+IF(E{row}<>"",(TIMEVALUE(F{row})-TIMEVALUE(E{row}))*24,0)'
        f'-IF(G{row}<>"",TIMEVALUE(G{row})*24,0),"")'
    )


def _weekly_total_formula(first_row: int, last_row: int) -> str:
    """Col I (summary row): sum of daily worked hours for the week."""
    return f'=IFERROR(SUM(H{first_row}:H{last_row}),"")'


def _hours_due_formula(summary_row: int) -> str:
    """Col K (summary row): discrepancy = got_paid / rate - weekly_total."""
    return f'=IF(J{summary_row}<>"",J{summary_row}/31.23-I{summary_row},"")'


# ---------------------------------------------------------------------------
# Sheet provisioning
# ---------------------------------------------------------------------------

def _setup_sheet_headers(ws: gspread.Worksheet) -> None:
    if ws.acell("B1").value:
        return
    ws.update(
        [["Date", "Day", "Start 1", "End 1", "Start 2", "End 2", "Break",
          "Worked Hours", "Weekly Total", "Got Paid", "Hours Due"]],
        "A1:K1",
        raw=True,
    )


def _setup_totals_row(ws: gspread.Worksheet) -> None:
    if not ws.acell("N1").value:
        ws.update_acell("N1", "=SUM(H:H)")
    if not ws.acell("O1").value:
        ws.update_acell("O1", "=N1*31.23")


def _provision_week(monday: date) -> bool:
    """
    Provision Mon-Fri rows + summary row for the given monday.
    Returns True if newly provisioned, False if already existed.
    """
    week_range = _week_range_str(monday)
    ws = _worksheet()

    col_a = ws.col_values(1)
    if week_range in col_a:
        return False  # already provisioned

    _setup_sheet_headers(ws)
    _setup_totals_row(ws)
    all_rows = ws.get_all_values()
    next_row = max(2, len(all_rows) + 1)

    rows_data: list[list[str]] = []
    for i, day in enumerate(_WEEKDAYS):
        row_num = next_row + i
        rows_data.append([
            week_range if i == 0 else "",  # A: week range on Monday only
            day,                            # B: day name
            "", "", "", "", "",             # C-G: filled by bot commands
            _hours_formula(row_num),        # H: worked hours (auto-calculated)
            "",                             # I: weekly total (summary row only)
            "",                             # J: got paid (summary row only)
            "",                             # K: hours due (summary row only)
        ])

    summary_row_num = next_row + 5
    week_end = monday + timedelta(days=4)
    week_label = f"Week of {monday.strftime('%d %b')}–{week_end.strftime('%d %b %Y')}"
    rows_data.append([
        f"S:{monday.strftime('%Y-%m-%d')}",              # A: marker for find_previous_week_summary_row
        week_label,                                       # B: human-readable label
        "", "", "", "", "",                               # C-G
        "",                                               # H
        _weekly_total_formula(next_row, next_row + 4),   # I: sum of Mon-Fri worked hours
        "",                                               # J: got paid
        _hours_due_formula(summary_row_num),              # K: discrepancy
    ])

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
    """
    monday = _week_monday()
    for i in range(num_weeks + 1):
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
    """Return 1-indexed sheet row for today, derived from week range in col A + weekday offset."""
    today = _today()
    if today.weekday() >= 5:
        raise ValueError("Today is a weekend. Commands are only available Mon–Fri.")
    monday = _week_monday(today)
    week_range = _week_range_str(monday)
    col_a = _worksheet().col_values(1)
    for i, val in enumerate(col_a):
        if val.strip() == week_range:
            return i + 1 + today.weekday()  # Monday row + weekday offset
    raise ValueError(f"No row found for {week_range}. Sheet may not be provisioned yet.")


def _provision_summary_row_only(ws: gspread.Worksheet, monday: date) -> int:
    """Append a payment-summary row for a manually-entered week. Returns 1-indexed row."""
    all_rows = ws.get_all_values()
    next_row = max(2, len(all_rows) + 1)
    week_end = monday + timedelta(days=4)
    week_label = f"Week of {monday.strftime('%d %b')}–{week_end.strftime('%d %b %Y')}"
    ws.update(
        [[f"S:{monday.strftime('%Y-%m-%d')}", week_label, "", "", "", "", "", "", "", "", ""]],
        f"A{next_row}:K{next_row}",
        raw=False,
    )
    return next_row


def find_previous_week_summary_row() -> int:
    """Return the 1-indexed summary row for last week (never this week's)."""
    prev_monday = _week_monday() - timedelta(days=7)
    prev_monday_str = prev_monday.strftime("%Y-%m-%d")
    ws = _worksheet()
    col_a = ws.col_values(1)

    # Primary: "S:YYYY-MM-DD" marker — unambiguous, used by all bot-provisioned weeks.
    marker = f"S:{prev_monday_str}"
    for i, val in enumerate(col_a):
        if val.strip() == marker:
            return i + 1

    # Secondary: week range string in col A (new layout, no S: marker).
    prev_range = _week_range_str(prev_monday)
    for i, val in enumerate(col_a):
        if val.strip() == prev_range:
            return i + 6  # Monday row (i+1) + 5 weekday rows = summary

    # Tertiary: old ISO date format — Monday date in col A, summary is Mon+5 rows.
    for i, val in enumerate(col_a):
        if val.strip() == prev_monday_str:
            return i + 6

    # Legacy: blank-A summary rows from old sheets with non-empty col I marker.
    current_monday_str = _week_monday().strftime("%Y-%m-%d")
    current_week_range = _week_range_str(_week_monday())
    current_week_start = next(
        (i for i, val in enumerate(col_a)
         if val.strip() in (current_week_range, current_monday_str)),
        len(col_a),
    )
    col_b = ws.col_values(2)
    col_i = ws.col_values(9)
    legacy_idx = current_week_start - 1
    if (
        legacy_idx >= 0
        and legacy_idx < len(col_b)
        and legacy_idx < len(col_i)
        and col_b[legacy_idx].strip() == "Summary"
        and col_i[legacy_idx].strip()
    ):
        return legacy_idx + 1

    # Nothing found: week was manually entered without bot format.
    # Append a summary-only row so the payment has somewhere to land.
    return _provision_summary_row_only(ws, prev_monday)


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
        raise ValueError("No data for current week.")

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
