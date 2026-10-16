ALTER TABLE positions
    ADD COLUMN IF NOT EXISTS requires_daily_report BOOLEAN NOT NULL DEFAULT false;
