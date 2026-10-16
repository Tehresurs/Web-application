-- Destructive clean-start cleanup. Never run without an explicit approval gate.
-- Run only in one transaction. This file intentionally leaves lookup, personnel,
-- LUVR, movement, settings, and unlinked-ticket data untouched.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '5min';

DO $authorization$
DECLARE
    approved_database TEXT;
BEGIN
    approved_database := current_setting('app.stage4129_rehearsal_database', TRUE);
    IF current_setting('app.allow_test_catalog_cleanup', TRUE) IS DISTINCT FROM 'yes' THEN
        RAISE EXCEPTION 'Cleanup requires app.allow_test_catalog_cleanup=yes';
    END IF;
    IF current_database() NOT IN (
           'ai_excel_agent_stage41210_20261014_1634',
           'ai_excel_agent_stage4151_20261019_988ebc2b',
           'ai_excel_agent_stage4151_20261019_86bf41ed'
       )
       OR approved_database IS DISTINCT FROM current_database() THEN
        RAISE EXCEPTION 'Cleanup refused for database %', current_database();
    END IF;
    IF current_schema() <> 'public' THEN
        RAISE EXCEPTION 'Cleanup is restricted to the public schema';
    END IF;
END
$authorization$;

LOCK TABLE
    public.construction_objects,
    public.construction_subobjects,
    public.value_aliases,
    public.employee_assignments,
    public.daily_control_results,
    public.production_assignment_items,
    public.production_assignment_changes,
    public.production_matrix_overrides,
    public.rail_tickets
IN ACCESS EXCLUSIVE MODE;

DO $cleanup$
DECLARE
    approved_database TEXT;
    table_name TEXT;
    row_count BIGINT;
    deleted_count BIGINT;
    preserved_before JSONB := '{}'::JSONB;
    preserved_after JSONB := '{}'::JSONB;
    retained_aliases_before JSONB;
    retained_aliases_after JSONB;
    retained_tickets_before JSONB;
    retained_tickets_after JSONB;
BEGIN
    approved_database := current_setting('app.stage4129_rehearsal_database', TRUE);
    IF current_setting('app.allow_test_catalog_cleanup', TRUE) IS DISTINCT FROM 'yes' THEN
        RAISE EXCEPTION 'Cleanup requires app.allow_test_catalog_cleanup=yes';
    END IF;
    IF current_database() NOT IN (
           'ai_excel_agent_stage41210_20261014_1634',
           'ai_excel_agent_stage4151_20261019_988ebc2b',
           'ai_excel_agent_stage4151_20261019_86bf41ed'
       )
       OR approved_database IS DISTINCT FROM current_database() THEN
        RAISE EXCEPTION 'Cleanup refused for database %', current_database();
    END IF;
    IF current_schema() <> 'public' THEN
        RAISE EXCEPTION 'Cleanup is restricted to the public schema';
    END IF;

    IF to_regclass('public.construction_entities') IS NOT NULL
       OR to_regclass('public.construction_entity_hierarchy') IS NOT NULL
       OR to_regclass('public.construction_entity_current') IS NOT NULL THEN
        RAISE EXCEPTION 'Identity migration objects exist; clean-start cleanup must run before migration';
    END IF;

    IF (SELECT count(*) FROM public.construction_objects) <> 143
       OR (SELECT count(*) FROM public.construction_subobjects) <> 10
       OR (SELECT count(*) FROM public.employee_assignments) <> 249
       OR (SELECT count(*) FROM public.daily_control_results) <> 420
       OR (SELECT count(*) FROM public.production_assignment_items) <> 3
       OR (SELECT count(*) FROM public.production_assignment_changes) <> 3
       OR (SELECT count(*) FROM public.rail_tickets) <> 125
       OR (SELECT count(*) FROM public.production_matrix_overrides) <> 248
       OR (SELECT count(*) FROM public.value_aliases
           WHERE entity_type IN ('object', 'subobject')) <> 85 THEN
        RAISE EXCEPTION 'Source counts differ from the approved backup baseline; no rows were removed';
    END IF;

    IF (SELECT count(*) FROM public.rail_tickets WHERE object_id IS NOT NULL) <> 3
       OR (SELECT count(*) FROM public.daily_control_results WHERE subobject_id IS NOT NULL) <> 1
       OR (SELECT count(*) FROM public.production_assignment_items WHERE subobject_id IS NOT NULL) <> 0 THEN
        RAISE EXCEPTION 'Linked-ticket or subobject counts differ from the approved backup baseline';
    END IF;

    -- Reject newly added foreign-key dependencies rather than silently modifying
    -- an unreviewed table. Known dependency edges are removed below in order.
    IF EXISTS (
        SELECT 1
        FROM pg_constraint c
        JOIN pg_class parent ON parent.oid = c.confrelid
        JOIN pg_namespace n ON n.oid = parent.relnamespace
        JOIN pg_class child ON child.oid = c.conrelid
        WHERE c.contype = 'f'
          AND n.nspname = 'public'
          AND (
              (parent.relname = 'construction_objects'
                  AND child.relname NOT IN (
                      'construction_subobjects', 'employee_assignments',
                      'daily_control_results', 'production_assignment_items', 'rail_tickets'
                  ))
              OR (parent.relname = 'construction_subobjects'
                  AND child.relname NOT IN ('daily_control_results', 'production_assignment_items'))
              OR (parent.relname = 'daily_control_results'
                  AND child.relname <> 'production_matrix_overrides')
              OR (parent.relname = 'production_assignment_items'
                  AND child.relname <> 'production_matrix_overrides')
              OR (parent.relname = 'production_assignment_changes'
                  AND child.relname <> 'production_assignment_items')
              OR (parent.relname = 'rail_tickets'
                  AND child.relname <> 'production_assignment_changes')
          )
    ) THEN
        RAISE EXCEPTION 'Unexpected foreign-key dependency found; cleanup refused';
    END IF;

    FOR table_name IN
        SELECT t.table_name
        FROM information_schema.tables t
        WHERE t.table_schema = 'public'
          AND t.table_type = 'BASE TABLE'
          AND t.table_name NOT IN (
              'construction_objects', 'construction_subobjects', 'value_aliases',
              'employee_assignments', 'daily_control_results',
              'production_assignment_items', 'production_assignment_changes',
              'production_matrix_overrides', 'rail_tickets'
          )
    LOOP
        EXECUTE format('SELECT count(*) FROM public.%I', table_name) INTO row_count;
        preserved_before := preserved_before || jsonb_build_object(table_name, row_count);
    END LOOP;

    SELECT COALESCE(jsonb_agg(to_jsonb(a) ORDER BY a.id), '[]'::JSONB)
    INTO retained_aliases_before
    FROM public.value_aliases AS a
    WHERE a.entity_type NOT IN ('object', 'subobject');

    SELECT COALESCE(jsonb_agg(to_jsonb(t) ORDER BY t.id), '[]'::JSONB)
    INTO retained_tickets_before
    FROM public.rail_tickets AS t
    WHERE t.object_id IS NULL;

    DELETE FROM public.value_aliases
    WHERE entity_type IN ('object', 'subobject');
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    IF deleted_count <> 85 THEN
        RAISE EXCEPTION 'Expected to delete 85 construction aliases, deleted %', deleted_count;
    END IF;

    DELETE FROM public.production_matrix_overrides
    WHERE fact_id IN (SELECT id FROM public.daily_control_results)
       OR assignment_item_id IN (SELECT id FROM public.production_assignment_items);
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    IF deleted_count <> 248 THEN
        RAISE EXCEPTION 'Expected to delete 248 linked matrix overrides, deleted %', deleted_count;
    END IF;

    DELETE FROM public.employee_assignments;
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    IF deleted_count <> 249 THEN
        RAISE EXCEPTION 'Expected to delete 249 assignments, deleted %', deleted_count;
    END IF;

    DELETE FROM public.daily_control_results;
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    IF deleted_count <> 420 THEN
        RAISE EXCEPTION 'Expected to delete 420 daily facts, deleted %', deleted_count;
    END IF;

    DELETE FROM public.production_assignment_items;
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    IF deleted_count <> 3 THEN
        RAISE EXCEPTION 'Expected to delete 3 production items, deleted %', deleted_count;
    END IF;

    DELETE FROM public.production_assignment_changes;
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    IF deleted_count <> 3 THEN
        RAISE EXCEPTION 'Expected to delete 3 production changes, deleted %', deleted_count;
    END IF;

    DELETE FROM public.rail_tickets WHERE object_id IS NOT NULL;
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    IF deleted_count <> 3 THEN
        RAISE EXCEPTION 'Expected to delete 3 linked tickets, deleted %', deleted_count;
    END IF;

    DELETE FROM public.construction_subobjects;
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    IF deleted_count <> 10 THEN
        RAISE EXCEPTION 'Expected to delete 10 subobjects, deleted %', deleted_count;
    END IF;

    DELETE FROM public.construction_objects;
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    IF deleted_count <> 143 THEN
        RAISE EXCEPTION 'Expected to delete 143 objects, deleted %', deleted_count;
    END IF;

    IF (SELECT count(*) FROM public.rail_tickets) <> 122
       OR EXISTS (SELECT 1 FROM public.rail_tickets WHERE object_id IS NOT NULL)
       OR EXISTS (SELECT 1 FROM public.production_matrix_overrides)
       OR EXISTS (SELECT 1 FROM public.employee_assignments)
       OR EXISTS (SELECT 1 FROM public.daily_control_results)
       OR EXISTS (SELECT 1 FROM public.production_assignment_items)
       OR EXISTS (SELECT 1 FROM public.production_assignment_changes)
       OR EXISTS (SELECT 1 FROM public.construction_subobjects)
       OR EXISTS (SELECT 1 FROM public.construction_objects)
       OR EXISTS (SELECT 1 FROM public.value_aliases
                  WHERE entity_type IN ('object', 'subobject')) THEN
        RAISE EXCEPTION 'Post-cleanup invariant failed';
    END IF;

    FOR table_name IN
        SELECT t.table_name
        FROM information_schema.tables t
        WHERE t.table_schema = 'public'
          AND t.table_type = 'BASE TABLE'
          AND t.table_name NOT IN (
              'construction_objects', 'construction_subobjects', 'value_aliases',
              'employee_assignments', 'daily_control_results',
              'production_assignment_items', 'production_assignment_changes',
              'production_matrix_overrides', 'rail_tickets'
          )
    LOOP
        EXECUTE format('SELECT count(*) FROM public.%I', table_name) INTO row_count;
        preserved_after := preserved_after || jsonb_build_object(table_name, row_count);
    END LOOP;
    IF preserved_after IS DISTINCT FROM preserved_before THEN
        RAISE EXCEPTION 'A retained table row count changed: before %, after %',
            preserved_before, preserved_after;
    END IF;

    SELECT COALESCE(jsonb_agg(to_jsonb(a) ORDER BY a.id), '[]'::JSONB)
    INTO retained_aliases_after
    FROM public.value_aliases AS a
    WHERE a.entity_type NOT IN ('object', 'subobject');
    IF retained_aliases_after IS DISTINCT FROM retained_aliases_before THEN
        RAISE EXCEPTION 'A non-construction alias changed during cleanup';
    END IF;

    SELECT COALESCE(jsonb_agg(to_jsonb(t) ORDER BY t.id), '[]'::JSONB)
    INTO retained_tickets_after
    FROM public.rail_tickets AS t
    WHERE t.object_id IS NULL;
    IF retained_tickets_after IS DISTINCT FROM retained_tickets_before THEN
        RAISE EXCEPTION 'An unlinked ticket changed during cleanup';
    END IF;
END
$cleanup$;

COMMIT;
