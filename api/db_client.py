from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

import db
import config

_TZ = ZoneInfo("Australia/Sydney")
_HOURLY_RATE: float = config.HOURLY_RATE


def _today() -> date:
    return datetime.now(_TZ).date()


def _week_monday(d: date | None = None) -> date:
    if d is None:
        d = _today()
    return d - timedelta(days=d.weekday())


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
        total += _time_to_mins(end1) - _time_to_mins(start1)
    if start2 and end2:
        total += _time_to_mins(end2) - _time_to_mins(start2)
    return max(0, total - break_mins)


# ---------------------------------------------------------------------------
# Entry-point helpers (replaces row-finding logic)
# ---------------------------------------------------------------------------

async def find_today_entry() -> date:
    today = _today()
    if today.weekday() >= 5:
        raise ValueError("Today is a weekend. Commands only work Mon–Fri.")
    return today


async def find_previous_week_start() -> date:
    return _week_monday() - timedelta(days=7)


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------

async def update_time_set1(entry_date: date, start: str, end: str) -> None:
    pool = await db.get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT start2, end2, break_mins FROM work_entries WHERE entry_date = $1",
            entry_date,
        )
        start2 = row["start2"] if row else None
        end2 = row["end2"] if row else None
        break_mins = row["break_mins"] if row else 0
        worked = _calc_worked_mins(start, end, start2, end2, break_mins)

        await conn.execute(
            """
            INSERT INTO work_entries (entry_date, start1, end1, worked_mins, updated_at)
            VALUES ($1, $2, $3, $4, NOW())
            ON CONFLICT (entry_date)
            DO UPDATE SET start1 = $2, end1 = $3, worked_mins = $4, updated_at = NOW()
            """,
            entry_date, start, end, worked,
        )


async def update_time_set2(entry_date: date, start: str, end: str) -> None:
    pool = await db.get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT start1, end1, break_mins FROM work_entries WHERE entry_date = $1",
            entry_date,
        )
        start1 = row["start1"] if row else None
        end1 = row["end1"] if row else None
        break_mins = row["break_mins"] if row else 0
        worked = _calc_worked_mins(start1, end1, start, end, break_mins)

        await conn.execute(
            """
            INSERT INTO work_entries (entry_date, start2, end2, worked_mins, updated_at)
            VALUES ($1, $2, $3, $4, NOW())
            ON CONFLICT (entry_date)
            DO UPDATE SET start2 = $2, end2 = $3, worked_mins = $4, updated_at = NOW()
            """,
            entry_date, start, end, worked,
        )


async def update_break(entry_date: date, break_mins: int) -> None:
    pool = await db.get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT start1, end1, start2, end2 FROM work_entries WHERE entry_date = $1",
            entry_date,
        )
        start1 = row["start1"] if row else None
        end1 = row["end1"] if row else None
        start2 = row["start2"] if row else None
        end2 = row["end2"] if row else None
        worked = _calc_worked_mins(start1, end1, start2, end2, break_mins)

        await conn.execute(
            """
            INSERT INTO work_entries (entry_date, break_mins, worked_mins, updated_at)
            VALUES ($1, $2, $3, NOW())
            ON CONFLICT (entry_date)
            DO UPDATE SET break_mins = $2, worked_mins = $3, updated_at = NOW()
            """,
            entry_date, break_mins, worked,
        )


async def upsert_payment(week_start: date, amount: str) -> None:
    pool = await db.get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO weekly_payments (week_start, payment_received, updated_at)
            VALUES ($1, $2, NOW())
            ON CONFLICT (week_start)
            DO UPDATE SET payment_received = $2, updated_at = NOW()
            """,
            week_start, amount,
        )


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

async def _total_worked_and_paid(conn) -> tuple[int, float]:
    """Return (total_worked_mins, total_paid) across all records."""
    worked = await conn.fetchval(
        "SELECT COALESCE(SUM(worked_mins), 0) FROM work_entries"
    )
    override = await conn.fetchval(
        "SELECT COALESCE(SUM(total_mins_override), 0) FROM weekly_payments"
    )
    paid = await conn.fetchval(
        "SELECT COALESCE(SUM(payment_received), 0) FROM weekly_payments"
    )
    return int(worked) + int(override), float(paid)


async def read_hours_due() -> str:
    pool = await db.get_pool()
    async with pool.acquire() as conn:
        total_mins, total_paid = await _total_worked_and_paid(conn)
    if total_mins == 0:
        raise ValueError("No hours recorded yet.")
    hours_due = total_mins / 60 - total_paid / _HOURLY_RATE
    return f"{hours_due:.2f}"


async def read_payment_due() -> str:
    pool = await db.get_pool()
    async with pool.acquire() as conn:
        total_mins, total_paid = await _total_worked_and_paid(conn)
    if total_mins == 0:
        raise ValueError("No hours recorded yet.")
    payment_due = total_mins / 60 * _HOURLY_RATE - total_paid
    return f"{payment_due:.2f}"


# ---------------------------------------------------------------------------
# Weekly cron helper
# ---------------------------------------------------------------------------

async def calculate_week_hours() -> tuple[str, str]:
    monday = _week_monday()
    friday = monday + timedelta(days=4)
    pool = await db.get_pool()
    async with pool.acquire() as conn:
        total_mins = await conn.fetchval(
            "SELECT COALESCE(SUM(worked_mins), 0) FROM work_entries"
            " WHERE entry_date >= $1 AND entry_date <= $2",
            monday, friday,
        )
    hours = (total_mins or 0) / 60
    week_label = monday.strftime("%d %b %Y")
    return f"{hours:.2f}", week_label
