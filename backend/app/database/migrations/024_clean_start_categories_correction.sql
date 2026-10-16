-- Optional category: NULL means explicitly unassigned; never infer a category.
-- For the migrated clean-start rehearsal database or an explicitly approved copy.
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
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'construction_entities'
          AND column_name = 'entity_id' AND is_identity = 'YES'
    ) OR EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'construction_entities'
          AND column_name IN ('legacy_object_id', 'legacy_subobject_id', 'category_id')
    ) THEN
        RAISE EXCEPTION 'Expected clean-start model without category_id; refusing repeat or incompatible schema';
    END IF;
END
$guard$;
ALTER TABLE public.construction_entities
    ADD COLUMN category_id BIGINT REFERENCES public.object_categories(id) ON DELETE RESTRICT;
-- Append the column to preserve existing view column positions and dependencies.
CREATE OR REPLACE VIEW public.construction_entity_current AS
SELECT entity_id, name, parent_entity_id, activity_status, is_active,
       is_archived, archived_at, version, created_at, updated_at, category_id
FROM public.construction_entities;
COMMIT;
