ALTER TABLE rail_tickets
    ADD COLUMN IF NOT EXISTS object_id BIGINT REFERENCES construction_objects(id) ON DELETE SET NULL;

ALTER TABLE rail_tickets DROP CONSTRAINT IF EXISTS rail_tickets_status_check;
ALTER TABLE rail_tickets ADD CONSTRAINT rail_tickets_status_check
    CHECK (status IN ('PARSED','PARSE_ERROR','REJECTED','CONFIRMED','ANNULLED'));
