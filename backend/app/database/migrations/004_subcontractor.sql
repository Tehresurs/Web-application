-- Run in one transaction after migrations 001-003. No historic rows are rewritten.
LOCK TABLE daily_control_results IN ACCESS EXCLUSIVE MODE;
ALTER TABLE daily_control_results ADD COLUMN IF NOT EXISTS subcontractor_id BIGINT;
DO $$
BEGIN
    IF current_setting('server_version_num')::integer < 150000 THEN
        RAISE EXCEPTION 'Migration 004 requires PostgreSQL 15 or newer';
    END IF;
    IF EXISTS (
        SELECT 1 FROM daily_control_results
        GROUP BY report_date, employee_id, object_id, subobject_id, po_id, subcontractor_id, category_id
        HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION 'Duplicate control facts: migration cancelled without changing data';
    END IF;
    IF EXISTS (
        SELECT 1 FROM daily_control_results r LEFT JOIN po_types p ON p.id = r.subcontractor_id
        WHERE r.subcontractor_id IS NOT NULL AND p.id IS NULL
    ) THEN
        RAISE EXCEPTION 'Invalid subcontractor: migration cancelled';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'daily_control_results'::regclass
                   AND conname = 'fk_daily_control_subcontractor') THEN
        ALTER TABLE daily_control_results ADD CONSTRAINT fk_daily_control_subcontractor
            FOREIGN KEY (subcontractor_id) REFERENCES po_types(id) ON DELETE RESTRICT;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint c JOIN pg_index i ON i.indexrelid = c.conindid
        WHERE c.conrelid = 'daily_control_results'::regclass AND c.conname = 'uq_daily_control_fact'
          AND i.indnullsnotdistinct AND pg_get_constraintdef(c.oid) =
          'UNIQUE NULLS NOT DISTINCT (report_date, employee_id, object_id, subobject_id, po_id, subcontractor_id, category_id)'
    ) THEN
        CREATE UNIQUE INDEX uq_daily_control_fact_subcontractor ON daily_control_results
            (report_date, employee_id, object_id, subobject_id, po_id, subcontractor_id, category_id)
            NULLS NOT DISTINCT;
        ALTER TABLE daily_control_results DROP CONSTRAINT uq_daily_control_fact;
        ALTER TABLE daily_control_results ADD CONSTRAINT uq_daily_control_fact
            UNIQUE USING INDEX uq_daily_control_fact_subcontractor;
    END IF;
END;
$$;
CREATE INDEX IF NOT EXISTS ix_daily_control_subcontractor ON daily_control_results(subcontractor_id);

-- Existing types keep precisely the same normalization; only the new role is added.
CREATE OR REPLACE FUNCTION normalize_known_value(entity_type TEXT, source_value TEXT)
RETURNS TEXT LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$
    SELECT btrim(regexp_replace(
        CASE
            WHEN entity_type IN ('object', 'subobject')
                THEN replace(replace(lower(source_value), 'ё', 'е'), '№ ', '№')
            WHEN entity_type IN ('po', 'subcontractor')
                THEN replace(replace(replace(lower(source_value), 'ё', 'е'), '«', '"'), '»', '"')
            ELSE replace(lower(source_value), 'ё', 'е')
        END,
        '[[:space:]' || chr(160) || ']+', ' ', 'g'
    ));
$$;
ALTER TABLE value_aliases DROP CONSTRAINT value_aliases_entity_type_check;
ALTER TABLE value_aliases ADD CONSTRAINT value_aliases_entity_type_check
    CHECK (entity_type IN ('employee', 'object', 'subobject', 'po', 'subcontractor'));
