#!/usr/bin/env python3
"""
One-time migration script: Google Sheets → Neon PostgreSQL.

Run from repo root:
    python scripts/migrate_from_sheets.py

Requires .env with both Google Sheets vars (for reading) and DATABASE_URL (for writing).
Reads the full sheet, reconstructs all week blocks, inserts work_entries and weekly_payments.
Safe to re-run — uses INSERT ... ON CONFLICT DO UPDATE.
"""

import asyncio
import json
import os
import re
import ssl
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "api"))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

import asyncpg
import gspread
from google.oauth2.service_account import Credentials

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "").strip() or os.getenv("GOOGLE_SHEET_ID", "").strip()
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON", "").strip()
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
HOURLY_RATE = float(os.getenv("HOURLY_RATE", "31.23"))

if not SPREADSHEET_ID:
    sys.exit("ERROR: SPREADSHEET_ID (or GOOGLE_SHEET_ID) not set in .env")
if not GOOGLE_CREDENTIALS_JSON:
    sys.exit("ERROR: GOOGLE_CREDENTIALS_JSON not set in .env")
if not DATABASE_URL:
    sys.exit("ERROR: DATABASE_URL not set in .env")

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

_SUMMARY_RE = re.compile(r"^S:(\d{4}-\d{2}-\d{2})$")
_WEEK_RANGE_RE = re.compile(r"^(\d{2})/(\d{2})\s*-\s*\d{2}/\d{2}$")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _time_to_mins(t: str) -> int:
    dt = datetime.strptime(t.strip(), "%I:%M %p")
    return dt.hour * 60 + dt.minute


def _calc_worked_mins(
    start1: str | None,
    end1: str | None,
    start2: str | None,
    end2: str | None,
    break_mins: int,
) -> int:
    total = 0
    if start1 and end1:
        try:
            total += _time_to_mins(end1) - _time_to_mins(start1)
        except ValueError:
            pass
    if start2 and end2:
        try:
            total += _time_to_mins(end2) - _time_to_mins(start2)
        except ValueError:
            pass
    return max(0, total - break_mins)


def _parse_break(break_str: str) -> int:
    try:
        h, m = break_str.strip().split(":")
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return 0


def _cell(row: list[str], col: int) -> str | None:
    if col >= len(row):
        return None
    val = row[col].strip()
    return val if val else None


# ---------------------------------------------------------------------------
# Sheet reading
# ---------------------------------------------------------------------------

def read_sheet_rows() -> list[list[str]]:
    print("Connecting to Google Sheets...")
    creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    gc = gspread.authorize(creds)
    ws = gc.open_by_key(SPREADSHEET_ID).sheet1
    rows = ws.get_all_values()
    print(f"  Read {len(rows)} rows from sheet.")
    return rows


# ---------------------------------------------------------------------------
# Week block parsing
# ---------------------------------------------------------------------------

def parse_work_entries_and_payments(
    rows: list[list[str]],
) -> tuple[list[dict], list[dict]]:
    """
    Returns (work_entries, weekly_payments).

    Sheet structure (data rows, skipping header row 0):
      For each week: 5 day rows (Mon–Fri) + 1 summary row = 6 rows total.
      Bot-provisioned: summary row col A = "S:YYYY-MM-DD"
      Manual weeks: Monday row col A = "DD/MM - DD/MM", no S: marker on summary row
    """
    data = rows[1:]  # skip header

    work_entries: list[dict] = []
    payments: list[dict] = []
    processed_summary_indices: set[int] = set()

    # Pass 1: bot-provisioned weeks via S: marker
    for i, row in enumerate(data):
        col_a = row[0].strip() if row else ""
        m = _SUMMARY_RE.match(col_a)
        if not m:
            continue

        monday_date = date.fromisoformat(m.group(1))
        processed_summary_indices.add(i)

        for weekday in range(5):
            day_idx = i - 5 + weekday
            if day_idx < 0:
                continue
            day_row = data[day_idx]
            entry_date = monday_date + timedelta(days=weekday)

            start1 = _cell(day_row, 2)
            end1   = _cell(day_row, 3)
            start2 = _cell(day_row, 4)
            end2   = _cell(day_row, 5)
            brk    = _cell(day_row, 6)

            if not any([start1, end1, start2, end2, brk]):
                continue

            break_mins = _parse_break(brk) if brk else 0
            worked_mins = _calc_worked_mins(start1, end1, start2, end2, break_mins)

            work_entries.append({
                "entry_date": entry_date,
                "start1": start1, "end1": end1,
                "start2": start2, "end2": end2,
                "break_mins": break_mins, "worked_mins": worked_mins,
            })

        payment_str = _cell(row, 9)
        if payment_str:
            try:
                amount = float(payment_str.replace("$", "").replace(",", ""))
                payments.append({"week_start": monday_date, "payment_received": amount})
            except ValueError:
                print(f"  WARN: could not parse payment '{payment_str}' for week {monday_date}")

    # Pass 2: manual weeks (DD/MM - DD/MM in col A, no S: on summary row)
    known_mondays = sorted(
        {e["entry_date"] - timedelta(days=e["entry_date"].weekday()) for e in work_entries}
    )
    last_known_date = known_mondays[0] if known_mondays else date.today()

    for i, row in enumerate(data):
        col_a = row[0].strip() if row else ""
        m = _WEEK_RANGE_RE.match(col_a)
        if not m:
            continue

        summary_idx = i + 5
        if summary_idx in processed_summary_indices:
            continue

        day_num, month = int(m.group(1)), int(m.group(2))
        monday_date = None
        for year_offset in [0, 1, -1]:
            candidate_year = last_known_date.year + year_offset
            try:
                candidate = date(candidate_year, month, day_num)
                if candidate.weekday() != 0:
                    continue
                if abs((candidate - last_known_date).days) <= 730:
                    monday_date = candidate
                    break
            except ValueError:
                continue

        if monday_date is None:
            print(f"  WARN: could not infer year for manual week '{col_a}' at data row {i+2}. Skipping.")
            continue

        last_known_date = monday_date
        processed_summary_indices.add(summary_idx)

        for weekday in range(5):
            day_idx = i + weekday
            if day_idx >= len(data):
                continue
            day_row = data[day_idx]
            entry_date = monday_date + timedelta(days=weekday)

            start1 = _cell(day_row, 2)
            end1   = _cell(day_row, 3)
            start2 = _cell(day_row, 4)
            end2   = _cell(day_row, 5)
            brk    = _cell(day_row, 6)

            if not any([start1, end1, start2, end2, brk]):
                continue

            break_mins = _parse_break(brk) if brk else 0
            worked_mins = _calc_worked_mins(start1, end1, start2, end2, break_mins)

            work_entries.append({
                "entry_date": entry_date,
                "start1": start1, "end1": end1,
                "start2": start2, "end2": end2,
                "break_mins": break_mins, "worked_mins": worked_mins,
            })

        if summary_idx < len(data):
            summary_row = data[summary_idx]
            payment_str = _cell(summary_row, 9)
            if payment_str:
                try:
                    amount = float(payment_str.replace("$", "").replace(",", ""))
                    payments.append({"week_start": monday_date, "payment_received": amount})
                except ValueError:
                    print(f"  WARN: could not parse payment '{payment_str}' for week {monday_date}")

    # Deduplicate by date (last write wins)
    work_entries = list({e["entry_date"]: e for e in work_entries}.values())
    payments = list({p["week_start"]: p for p in payments}.values())

    return work_entries, payments


# ---------------------------------------------------------------------------
# Database insertion
# ---------------------------------------------------------------------------

async def insert_into_db(work_entries: list[dict], payments: list[dict]) -> None:
    print("\nConnecting to database...")

    url = DATABASE_URL
    kwargs: dict = {}
    if "sslmode=require" in url or "neon.tech" in url:
        kwargs["ssl"] = ssl.create_default_context()
        url = url.split("?")[0]

    pool = await asyncpg.create_pool(url, min_size=1, max_size=3, **kwargs)

    async with pool.acquire() as conn:
        schema = (ROOT / "api" / "schema.sql").read_text()
        await conn.execute(schema)
        print("  Tables ready.")

        inserted_entries = 0
        skipped_entries = 0
        for e in sorted(work_entries, key=lambda x: x["entry_date"]):
            try:
                await conn.execute(
                    """
                    INSERT INTO work_entries
                        (entry_date, start1, end1, start2, end2, break_mins, worked_mins)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    ON CONFLICT (entry_date) DO UPDATE SET
                        start1 = EXCLUDED.start1, end1 = EXCLUDED.end1,
                        start2 = EXCLUDED.start2, end2 = EXCLUDED.end2,
                        break_mins = EXCLUDED.break_mins,
                        worked_mins = EXCLUDED.worked_mins,
                        updated_at = NOW()
                    """,
                    e["entry_date"], e["start1"], e["end1"],
                    e["start2"], e["end2"], e["break_mins"], e["worked_mins"],
                )
                inserted_entries += 1
            except Exception as exc:
                print(f"  ERROR inserting {e['entry_date']}: {exc}")
                skipped_entries += 1

        inserted_payments = 0
        skipped_payments = 0
        for p in sorted(payments, key=lambda x: x["week_start"]):
            try:
                await conn.execute(
                    """
                    INSERT INTO weekly_payments (week_start, payment_received)
                    VALUES ($1, $2)
                    ON CONFLICT (week_start) DO UPDATE SET
                        payment_received = EXCLUDED.payment_received, updated_at = NOW()
                    """,
                    p["week_start"], p["payment_received"],
                )
                inserted_payments += 1
            except Exception as exc:
                print(f"  ERROR inserting payment {p['week_start']}: {exc}")
                skipped_payments += 1

    await pool.close()

    print("\n--- Migration complete ---")
    print(f"  Work entries : {inserted_entries} inserted, {skipped_entries} errors")
    print(f"  Payments     : {inserted_payments} inserted, {skipped_payments} errors")
    total_hours = sum(e["worked_mins"] for e in work_entries) / 60
    print(f"  Total hours  : {total_hours:.2f} hrs")
    print(f"  Implied pay  : ${total_hours * HOURLY_RATE:.2f}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main() -> None:
    rows = read_sheet_rows()
    work_entries, payments = parse_work_entries_and_payments(rows)

    print(f"\nParsed from sheet:")
    print(f"  Work entries : {len(work_entries)}")
    print(f"  Payments     : {len(payments)}")

    if not work_entries and not payments:
        print("Nothing to migrate. Check that the sheet has data.")
        return

    if work_entries:
        sorted_entries = sorted(work_entries, key=lambda x: x["entry_date"])
        print(f"  Date range   : {sorted_entries[0]['entry_date']} → {sorted_entries[-1]['entry_date']}")

    confirm = input("\nProceed with database insertion? [y/N] ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        return

    await insert_into_db(work_entries, payments)


if __name__ == "__main__":
    asyncio.run(main())
