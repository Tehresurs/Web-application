-- Rehearsal-only correction; preserves data and can be applied repeatedly.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '1min';
SELECT pg_advisory_xact_lock(20261014, 25);
DO $guard$
BEGIN
    IF current_setting('app.allow_clean_start_migration', TRUE) IS DISTINCT FROM 'yes'
       OR current_setting('app.stage4129_rehearsal_database', TRUE) IS DISTINCT FROM current_database()
       OR (current_database() <> 'ai_excel_agent_stage41210_20261014_1634'
           AND current_database() !~ '^ai_excel_agent_test_categories_[a-f0-9]{12}$')
       OR current_schema() <> 'public' THEN
        RAISE EXCEPTION 'Clean-start category correction refused for this database/schema';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='construction_entities' AND column_name='category_id') OR to_regprocedure('public.guard_clean_construction_entity()') IS NULL THEN
        RAISE EXCEPTION 'Expected corrected clean-start schema';
    END IF;
END
$guard$;
CREATE OR REPLACE FUNCTION public.guard_clean_construction_entity() RETURNS trigger
LANGUAGE plpgsql AS $guard$
DECLARE
    parent_parent_id BIGINT;
    parent_archived BOOLEAN;
    parent_active BOOLEAN;
BEGIN
    PERFORM pg_advisory_xact_lock(20261014, 25);
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Construction entities are archived, not physically deleted'
            USING ERRCODE = '23514';
    END IF;

    IF TG_OP = 'UPDATE' THEN
        NEW.version := OLD.version + 1;
        NEW.updated_at := clock_timestamp();
    END IF;

    IF NEW.parent_entity_id IS NOT NULL THEN
        SELECT parent_entity_id, is_archived, is_active
        INTO parent_parent_id, parent_archived, parent_active
        FROM public.construction_entities
        WHERE entity_id = NEW.parent_entity_id
        FOR KEY SHARE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Parent entity does not exist' USING ERRCODE = '23503';
        END IF;
        IF parent_parent_id IS NOT NULL THEN
            RAISE EXCEPTION 'Construction hierarchy is limited to two levels'
                USING ERRCODE = '23514';
        END IF;
        IF (TG_OP = 'INSERT' OR NEW.parent_entity_id IS DISTINCT FROM OLD.parent_entity_id)
           AND (parent_archived OR NOT parent_active) THEN
            RAISE EXCEPTION 'A new child requires an active, non-archived parent'
                USING ERRCODE = '23514';
        END IF;
        IF TG_OP = 'UPDATE' AND EXISTS (
            SELECT 1
            FROM public.construction_entities
            WHERE parent_entity_id = NEW.entity_id
        ) THEN
            RAISE EXCEPTION 'An entity with children cannot become a child'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END
$guard$;

COMMIT;
