CREATE TABLE IF NOT EXISTS work_entries (
    id          SERIAL PRIMARY KEY,
    entry_date  DATE NOT NULL UNIQUE,
    start1      VARCHAR(20),
    end1        VARCHAR(20),
    start2      VARCHAR(20),
    end2        VARCHAR(20),
    break_mins  INTEGER NOT NULL DEFAULT 0,
    worked_mins INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS weekly_payments (
    id               SERIAL PRIMARY KEY,
    week_start       DATE NOT NULL UNIQUE,
    payment_received NUMERIC(10,2),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
