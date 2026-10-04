ALTER TABLE rail_tickets ADD COLUMN IF NOT EXISTS source_page INTEGER;
ALTER TABLE rail_tickets ADD COLUMN IF NOT EXISTS source_sha256 CHAR(64);
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='rail_tickets'::regclass AND conname='ck_rail_source_page') THEN
        ALTER TABLE rail_tickets ADD CONSTRAINT ck_rail_source_page CHECK(source_page > 0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='rail_tickets'::regclass AND conname='ck_rail_source_hash') THEN
        ALTER TABLE rail_tickets ADD CONSTRAINT ck_rail_source_hash CHECK(source_sha256 ~ '^[0-9a-f]{64}$');
    END IF;
END;
$$;
