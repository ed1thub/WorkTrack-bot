# Auto-Provisioning Implementation Summary

## Overview
Implemented automatic Google Sheet row provisioning to keep the calendar up-to-date without manual intervention. The system now automatically creates week rows on startup and maintains a 2-week lookahead.

## Changes Made

### 1. **api/sheets_client.py** — Multi-week provisioning
Added three new functions:

- **`_provision_week(monday: date) -> bool`** — Internal helper that provisions Mon-Fri rows + summary row for a given Monday. Returns True if newly created, False if already existed (idempotent).

- **`provision_weeks_ahead(num_weeks: int = 2) -> None`** — Provision current week and the next N weeks automatically. Safe to call multiple times (idempotent). Default provisions 3 weeks total (current + 2 ahead).

- **`ensure_next_week_rows() -> None`** — Provision next week's rows. Called by the Friday cron job to auto-create following week.

**Refactored:**
- `ensure_current_week_rows()` now delegates to `_provision_week()` for consistency

### 2. **api/index.py** — Startup provisioning
Added startup event handler:

- **`@app.on_event("startup")`** — New async function `provision_weeks_on_startup()` that runs when the FastAPI app starts. Provisions current week and next 2 weeks automatically (3 total weeks).
- Non-fatal error handling: if startup provisioning fails, commands will provision on-demand as fallback.

**Added imports:**
- `import asyncio` — for thread management
- `import sheets_client` — for provisioning functions

### 3. **api/bot_logic.py** — Cron enhancement
Updated weekly summary handler:

- **`send_weekly_summary()`** — After sending the Friday 11:30 PM summary message, now automatically calls `sheets_client.ensure_next_week_rows()` to provision the following week.

## Features Implemented

| Requirement | Implementation | Status |
|---|---|---|
| **Auto-calendar updates** | Rows provisioned on startup + after each Friday cron | ✅ Complete |
| **Weekly Friday 11:30 PM summary** | Cron endpoint + message sends total hours | ✅ Complete (enhanced) |
| **Time format support** | Already supported "1:30 PM-6:00 PM" format | ✅ Complete |
| **Auto-row provisioning** | Weeks created automatically on startup + cron | ✅ Complete |

## Data Flow

### On App Startup
```
App start
  ↓
@app.on_event("startup") triggered
  ↓
provision_weeks_ahead(2) called
  ↓
Current week + 2 future weeks provisioned
  ↓
Commands use existing rows (no more "No row for today" errors)
```

### Every Friday 11:30 PM (Vercel Cron)
```
Cron job triggers /api/cron/weekly-summary
  ↓
send_weekly_summary() executes
  ↓
- Calculate total hours for current week
- Write summary to col I
- Send Telegram message with total hours ✓
- Automatically provision next week ✓
  ↓
Sunday → new week rows ready to use
```

### On Command Execution (e.g., /time 1:30 PM-6:00 PM)
```
Telegram message received
  ↓
ensure_current_week_rows() called (existing command handler)
  ↓
If startup provisioning failed, provides fallback
  ↓
Current week guaranteed to exist
  ↓
Log time entry → success ✓
```

## Benefits

1. **Zero Manual Work** — No need to create rows or check the sheet manually
2. **Self-Healing** — Fallback provisioning ensures rows exist even if startup fails
3. **Multi-week Lookahead** — 2-3 weeks pre-created so you can enter future times if needed
4. **Idempotent** — Safe to call provisioning functions multiple times (no duplicates)
5. **Graceful Degradation** — If provisioning fails on startup, commands still work

## Testing Checklist

- [ ] Deploy to Vercel
- [ ] Monitor first app startup (check Vercel logs for "provision_weeks_on_startup")
- [ ] Test `/time 1:30 PM-6:00 PM` command → should create entry in today's row
- [ ] Verify next Friday cron runs and sends weekly summary
- [ ] Check Google Sheet for auto-created rows (current week + 2 ahead)
- [ ] Test a command next week → verify rows were pre-created

## Rollback Plan

If issues arise, revert to previous commit:
```bash
git revert HEAD
git push origin main
```

The changes are backward-compatible; existing sheets will continue to work.
