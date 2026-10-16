ALTER TABLE positions
    ADD COLUMN IF NOT EXISTS report_description TEXT,
    ADD COLUMN IF NOT EXISTS aos_description TEXT;
