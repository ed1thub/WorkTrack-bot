import asyncio
import json
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

import config


class SheetsSyncError(RuntimeError):
    """Raised when a log was saved locally but could not be mirrored to Sheets."""


_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]


async def sync_work_entry(entry: Mapping[str, Any]) -> None:
    await asyncio.to_thread(_sync_work_entry_sync, entry)


async def sync_payment(week_start: date, amount: str) -> None:
    await asyncio.to_thread(_sync_payment_sync, week_start, amount)


def _worksheet():
    if not config.SPREADSHEET_ID or not config.GOOGLE_CREDENTIALS_JSON:
        raise SheetsSyncError("Google Sheets is not configured.")

    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError as exc:
        raise SheetsSyncError("Google Sheets dependencies are not installed.") from exc

    try:
        creds_dict = json.loads(config.GOOGLE_CREDENTIALS_JSON)
        creds = Credentials.from_service_account_info(creds_dict, scopes=_SCOPES)
        client = gspread.authorize(creds)
        return client.open_by_key(config.SPREADSHEET_ID).sheet1
    except Exception as exc:
        raise SheetsSyncError("Could not connect to Google Sheets.") from exc


def _sync_work_entry_sync(entry: Mapping[str, Any]) -> None:
    entry_date = entry["entry_date"]
    if not isinstance(entry_date, date):
        raise SheetsSyncError("Work entry date is invalid.")

    ws = _worksheet()
    row_number = _find_or_create_day_row(ws, entry_date)
    values = [
        entry.get("start1") or "",
        entry.get("end1") or "",
        entry.get("start2") or "",
        entry.get("end2") or "",
        _format_break(entry.get("break_mins") or 0),
    ]

    try:
        ws.update(
            values=[values],
            range_name=f"C{row_number}:G{row_number}",
            value_input_option="USER_ENTERED",
        )
    except Exception as exc:
        raise SheetsSyncError("Could not update the work entry in Google Sheets.") from exc


def _sync_payment_sync(week_start: date, amount: str) -> None:
    ws = _worksheet()
    _, summary_row = _find_or_create_week_block(ws, week_start)
    try:
        ws.update(
            values=[[_format_payment(amount)]],
            range_name=f"J{summary_row}",
            value_input_option="USER_ENTERED",
        )
    except Exception as exc:
        raise SheetsSyncError("Could not update the payment in Google Sheets.") from exc


def _find_or_create_day_row(ws, entry_date: date) -> int:
    if entry_date.weekday() >= 5:
        raise SheetsSyncError("Google Sheets sync only supports Monday-Friday workdays.")

    monday = _week_monday(entry_date)
    start_row, _ = _find_or_create_week_block(ws, monday)
    return start_row + entry_date.weekday()


def _find_or_create_week_block(ws, monday: date) -> tuple[int, int]:
    rows = ws.get_all_values()
    marker = f"S:{monday.isoformat()}"

    for index, row in enumerate(rows, start=1):
        first_cell = row[0].strip() if row else ""
        if first_cell == marker:
            summary_row = index
            start_row = summary_row - 5
            if start_row < 1:
                raise SheetsSyncError("Google Sheets week block is malformed.")
            return start_row, summary_row

    manual_block = _find_manual_week_block(rows, monday)
    if manual_block is not None:
        return manual_block

    start_row = len(rows) + 1
    summary_row = start_row + 5
    try:
        ws.append_rows(_new_week_block(monday), value_input_option="USER_ENTERED")
    except Exception as exc:
        raise SheetsSyncError("Could not create the week block in Google Sheets.") from exc
    return start_row, summary_row


def _new_week_block(monday: date) -> list[list[str]]:
    friday = monday + timedelta(days=4)
    week_label = f"{monday:%d/%m} - {friday:%d/%m}"

    rows = []
    for index, day_name in enumerate(_WEEKDAYS):
        rows.append([week_label if index == 0 else "", day_name, "", "", "", "", "", "", "", ""])

    rows.append([f"S:{monday.isoformat()}", "Total", "", "", "", "", "", "", "", ""])
    return rows


def _find_manual_week_block(rows: list[list[str]], monday: date) -> tuple[int, int] | None:
    labels = _manual_week_labels(monday)
    match = None
    for index, row in enumerate(rows, start=1):
        first_cell = row[0].strip() if row else ""
        if first_cell in labels:
            summary_row = index + 5
            if summary_row > len(rows):
                raise SheetsSyncError("Google Sheets week block is missing its summary row.")
            match = (index, summary_row)
    return match


def _manual_week_labels(monday: date) -> set[str]:
    friday = monday + timedelta(days=4)
    return {
        f"{monday:%d/%m} - {friday:%d/%m}",
        f"{monday.day}/{monday.month} - {friday.day}/{friday.month}",
    }


def _week_monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _format_break(break_mins: int) -> str:
    if break_mins <= 0:
        return ""
    hours, minutes = divmod(break_mins, 60)
    return f"{hours:02d}:{minutes:02d}"


def _format_payment(amount: str) -> str:
    try:
        return f"${Decimal(amount):.2f}"
    except (InvalidOperation, ValueError):
        return amount
