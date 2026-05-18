import asyncio
import os
import sys
import unittest
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_SECRET_TOKEN", "test-secret")
os.environ.setdefault("ADMIN_CHAT_ID", "123")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/db")

import bot_logic
import db_client
import sheets_client


class FakeWorksheet:
    def __init__(self, rows):
        self.rows = rows
        self.updates = []

    def get_all_values(self):
        return self.rows

    def append_rows(self, rows, value_input_option=None):
        self.rows.extend(rows)

    def update(self, values, range_name=None, value_input_option=None):
        self.updates.append((range_name, values, value_input_option))


class BotLogicTests(unittest.IsolatedAsyncioTestCase):
    def test_command_routes_are_renamed(self):
        self.assertIn("/time1", bot_logic._COMMANDS)
        self.assertIn("/time2", bot_logic._COMMANDS)
        self.assertIn("/total", bot_logic._COMMANDS)
        self.assertNotIn("/time", bot_logic._COMMANDS)
        self.assertNotIn("/timeupdateset1", bot_logic._COMMANDS)
        self.assertNotIn("/timeupdateset2", bot_logic._COMMANDS)

    def test_full_date_format_uses_ordinal_suffix(self):
        self.assertEqual(
            bot_logic._format_full_date(date(2026, 5, 18)),
            "Monday, 18th May, 2026",
        )
        self.assertEqual(
            bot_logic._format_full_date(date(2026, 6, 1)),
            "Monday, 1st June, 2026",
        )

    async def test_total_command_replies_with_current_week_total(self):
        replies = []
        original_total = bot_logic.db_client.read_current_week_total
        original_reply = bot_logic._reply

        async def fake_total():
            return "23.50"

        async def fake_reply(chat_id, text):
            replies.append((chat_id, text))

        bot_logic.db_client.read_current_week_total = fake_total
        bot_logic._reply = fake_reply
        try:
            await bot_logic.handle(123, "/total")
        finally:
            bot_logic.db_client.read_current_week_total = original_total
            bot_logic._reply = original_reply

        self.assertEqual(replies, [(123, "Total worked this week: 23.50 hrs")])

    async def test_time_reply_includes_full_date_and_sheet_warning(self):
        replies = []
        updates = []
        original_today = bot_logic.db_client.find_today_entry
        original_update = bot_logic.db_client.update_time_set1
        original_read = bot_logic.db_client.read_work_entry
        original_sync = bot_logic.sheets_client.sync_work_entry
        original_reply = bot_logic._reply

        async def fake_today():
            return date(2026, 5, 18)

        async def fake_update(entry_date, start, end):
            updates.append((entry_date, start, end))

        async def fake_read(entry_date):
            return {
                "entry_date": entry_date,
                "start1": "1:30 PM",
                "end1": "6:30 PM",
                "start2": None,
                "end2": None,
                "break_mins": 0,
                "worked_mins": 300,
            }

        async def fake_sync(entry):
            raise sheets_client.SheetsSyncError("boom")

        async def fake_reply(chat_id, text):
            replies.append((chat_id, text))

        bot_logic.db_client.find_today_entry = fake_today
        bot_logic.db_client.update_time_set1 = fake_update
        bot_logic.db_client.read_work_entry = fake_read
        bot_logic.sheets_client.sync_work_entry = fake_sync
        bot_logic._reply = fake_reply
        try:
            await bot_logic.handle(123, "/time1 1:30 PM-6:30 PM")
        finally:
            bot_logic.db_client.find_today_entry = original_today
            bot_logic.db_client.update_time_set1 = original_update
            bot_logic.db_client.read_work_entry = original_read
            bot_logic.sheets_client.sync_work_entry = original_sync
            bot_logic._reply = original_reply

        self.assertEqual(updates, [(date(2026, 5, 18), "1:30 PM", "6:30 PM")])
        self.assertEqual(
            replies,
            [
                (
                    123,
                    "Time logged: 1:30 PM-6:30 PM for Monday, 18th May, 2026"
                    "\nGoogle Sheets sync failed. Your database log was saved.",
                )
            ],
        )

    async def test_old_time_command_is_ignored(self):
        replies = []
        original_reply = bot_logic._reply

        async def fake_reply(chat_id, text):
            replies.append((chat_id, text))

        bot_logic._reply = fake_reply
        try:
            await bot_logic.handle(123, "/time 1:30 PM-6:30 PM")
            await asyncio.sleep(0)
        finally:
            bot_logic._reply = original_reply

        self.assertEqual(replies, [])


class DbClientTests(unittest.TestCase):
    def test_worked_minutes_include_two_shifts_minus_break(self):
        self.assertEqual(
            db_client._calc_worked_mins(
                "1:30 PM",
                "6:30 PM",
                "7:00 PM",
                "8:00 PM",
                30,
            ),
            330,
        )

    def test_week_monday_uses_current_week_start(self):
        self.assertEqual(
            db_client._week_monday(date(2026, 5, 21)),
            date(2026, 5, 18),
        )

    def test_worked_minutes_do_not_go_negative(self):
        self.assertEqual(
            db_client._calc_worked_mins(None, None, None, None, 30),
            0,
        )


class SheetsClientTests(unittest.TestCase):
    def test_sync_work_entry_updates_template_input_columns(self):
        rows = [
            ["Header"],
            ["18/05 - 22/05", "Monday"],
            ["", "Tuesday"],
            ["", "Wednesday"],
            ["", "Thursday"],
            ["", "Friday"],
            ["", "Total"],
        ]
        ws = FakeWorksheet(rows)
        original_worksheet = sheets_client._worksheet
        sheets_client._worksheet = lambda: ws
        try:
            sheets_client._sync_work_entry_sync(
                {
                    "entry_date": date(2026, 5, 19),
                    "start1": "1:30 PM",
                    "end1": "6:30 PM",
                    "start2": "7:00 PM",
                    "end2": "8:00 PM",
                    "break_mins": 30,
                }
            )
        finally:
            sheets_client._worksheet = original_worksheet

        self.assertEqual(
            ws.updates,
            [("C3:G3", [["1:30 PM", "6:30 PM", "7:00 PM", "8:00 PM", "00:30"]], "USER_ENTERED")],
        )

    def test_sync_payment_updates_summary_payment_column(self):
        rows = [
            ["Header"],
            ["18/05 - 22/05", "Monday"],
            ["", "Tuesday"],
            ["", "Wednesday"],
            ["", "Thursday"],
            ["", "Friday"],
            ["", "Total"],
        ]
        ws = FakeWorksheet(rows)
        original_worksheet = sheets_client._worksheet
        sheets_client._worksheet = lambda: ws
        try:
            sheets_client._sync_payment_sync(date(2026, 5, 18), "500.00")
        finally:
            sheets_client._worksheet = original_worksheet

        self.assertEqual(ws.updates, [("J7", [["$500.00"]], "USER_ENTERED")])

    def test_existing_week_marker_finds_correct_day_row(self):
        rows = [
            ["Header"],
            ["18/05 - 22/05", "Monday"],
            ["", "Tuesday"],
            ["", "Wednesday"],
            ["", "Thursday"],
            ["", "Friday"],
            ["S:2026-05-18", "Total"],
        ]
        ws = FakeWorksheet(rows)

        row_number = sheets_client._find_or_create_day_row(ws, date(2026, 5, 20))

        self.assertEqual(row_number, 4)
        self.assertEqual(len(ws.rows), 7)

    def test_missing_week_appends_template_block(self):
        ws = FakeWorksheet([["Header"]])

        row_number = sheets_client._find_or_create_day_row(ws, date(2026, 5, 18))

        self.assertEqual(row_number, 2)
        self.assertEqual(len(ws.rows), 7)
        self.assertEqual(ws.rows[-1][0], "S:2026-05-18")

    def test_manual_week_block_is_reused_without_marker(self):
        rows = [
            ["Header"],
            ["18/05 - 22/05", "Monday"],
            ["", "Tuesday"],
            ["", "Wednesday"],
            ["", "Thursday"],
            ["", "Friday"],
            ["", "Total"],
        ]
        ws = FakeWorksheet(rows)

        row_number = sheets_client._find_or_create_day_row(ws, date(2026, 5, 21))

        self.assertEqual(row_number, 5)
        self.assertEqual(len(ws.rows), 7)

    def test_manual_week_block_accepts_non_padded_dates(self):
        rows = [
            ["Header"],
            ["1/6 - 5/6", "Monday"],
            ["", "Tuesday"],
            ["", "Wednesday"],
            ["", "Thursday"],
            ["", "Friday"],
            ["", "Total"],
        ]
        ws = FakeWorksheet(rows)

        row_number = sheets_client._find_or_create_day_row(ws, date(2026, 6, 3))

        self.assertEqual(row_number, 4)
        self.assertEqual(len(ws.rows), 7)

    def test_duplicate_manual_week_labels_use_latest_block(self):
        rows = [
            ["Header"],
            ["18/05 - 22/05", "Monday"],
            ["", "Tuesday"],
            ["", "Wednesday"],
            ["", "Thursday"],
            ["", "Friday"],
            ["", "Total"],
            ["18/05 - 22/05", "Monday"],
            ["", "Tuesday"],
            ["", "Wednesday"],
            ["", "Thursday"],
            ["", "Friday"],
            ["", "Total"],
        ]
        ws = FakeWorksheet(rows)

        row_number = sheets_client._find_or_create_day_row(ws, date(2026, 5, 19))

        self.assertEqual(row_number, 9)
        self.assertEqual(len(ws.rows), 13)


if __name__ == "__main__":
    unittest.main()
