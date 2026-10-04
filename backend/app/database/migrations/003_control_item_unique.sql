-- Execute in one transaction. Never drop the old protection before validation.
LOCK TABLE daily_control_results IN ACCESS EXCLUSIVE MODE;
DO $$
BEGIN
    IF current_setting('server_version_num')::integer < 150000 THEN
        RAISE EXCEPTION 'Migration 003 requires PostgreSQL 15 or newer';
    END IF;
    IF EXISTS (
        SELECT 1 FROM daily_control_results
        GROUP BY report_date, employee_id, object_id, subobject_id, po_id, category_id
        HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION 'Duplicate control facts: migration cancelled without changing data';
    END IF;
    IF EXISTS (
        SELECT 1 FROM daily_control_results r
        LEFT JOIN construction_subobjects s ON s.id = r.subobject_id
        WHERE r.subobject_id IS NOT NULL AND (s.id IS NULL OR s.object_id <> r.object_id)
    ) THEN
        RAISE EXCEPTION 'Invalid object/subobject pair: migration cancelled';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint c JOIN pg_index i ON i.indexrelid = c.conindid
        WHERE c.conrelid = 'daily_control_results'::regclass
          AND c.conname = 'uq_daily_control_fact' AND i.indnullsnotdistinct
          AND pg_get_constraintdef(c.oid) =
              'UNIQUE NULLS NOT DISTINCT (report_date, employee_id, object_id, subobject_id, po_id, category_id)'
    ) THEN
        CREATE UNIQUE INDEX uq_daily_control_fact_stage6
            ON daily_control_results
            (report_date, employee_id, object_id, subobject_id, po_id, category_id)
            NULLS NOT DISTINCT;
        ALTER TABLE daily_control_results DROP CONSTRAINT uq_daily_control_fact;
        ALTER TABLE daily_control_results ADD CONSTRAINT uq_daily_control_fact
            UNIQUE USING INDEX uq_daily_control_fact_stage6;
    END IF;
END;
$$;
