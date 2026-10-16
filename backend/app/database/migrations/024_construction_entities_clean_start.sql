-- Alternative to 024_construction_identity_production.sql.
-- Use only after cleanup_legacy_construction_test_data.sql succeeds.
-- This migration does not copy, synthesize, or require legacy IDs.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '5min';
SELECT pg_advisory_xact_lock(20261014, 25);

DO $preflight$
DECLARE
    approved_database TEXT;
BEGIN
    approved_database := current_setting('app.stage4129_rehearsal_database', TRUE);
    IF current_setting('app.allow_clean_start_migration', TRUE) IS DISTINCT FROM 'yes' THEN
        RAISE EXCEPTION 'Migration requires app.allow_clean_start_migration=yes';
    END IF;
    IF (current_database() NOT IN (
            'ai_excel_agent_stage41210_20261014_1634',
            'ai_excel_agent_stage4151_20261019_988ebc2b',
            'ai_excel_agent_stage4151_20261019_86bf41ed'
        )
        AND current_database() !~ '^ai_excel_agent_test_categories_[a-f0-9]{12}$')
       OR approved_database IS DISTINCT FROM current_database() THEN
        RAISE EXCEPTION 'Clean-start migration refused for database %', current_database();
    END IF;
    IF current_schema() <> 'public' THEN
        RAISE EXCEPTION 'Clean-start migration is restricted to the public schema';
    END IF;
    IF to_regclass('public.construction_entities') IS NOT NULL
       OR to_regclass('public.construction_entity_current') IS NOT NULL
       OR to_regclass('public.construction_entity_hierarchy') IS NOT NULL
       OR to_regclass('public.construction_entity_aliases') IS NOT NULL THEN
        RAISE EXCEPTION 'An identity model already exists; refusing repeat or partial migration';
    END IF;
    IF (SELECT count(*) FROM public.construction_objects) <> 0
       OR (SELECT count(*) FROM public.construction_subobjects) <> 0
       OR (SELECT count(*) FROM public.employee_assignments) <> 0
       OR (SELECT count(*) FROM public.daily_control_results) <> 0
       OR (SELECT count(*) FROM public.production_assignment_items) <> 0
       OR EXISTS (SELECT 1 FROM public.rail_tickets WHERE object_id IS NOT NULL) THEN
        RAISE EXCEPTION 'Legacy catalog or consumer references remain; run the approved cleanup first';
    END IF;
    IF to_regprocedure('public.normalize_known_value(text,text)') IS NULL THEN
        RAISE EXCEPTION 'Required normalize_known_value(text,text) function is missing';
    END IF;
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name IN (
              'employee_assignments', 'daily_control_results',
              'production_assignment_items', 'rail_tickets'
          )
          AND column_name = 'entity_id'
    ) THEN
        RAISE EXCEPTION 'A consumer entity_id column already exists; refusing partial migration';
    END IF;
END
$preflight$;

CREATE TABLE public.construction_entities (
    entity_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL CHECK (normalize_known_value('object', name) <> ''),
    category_id BIGINT REFERENCES public.object_categories(id) ON DELETE RESTRICT,
    parent_entity_id BIGINT REFERENCES public.construction_entities(entity_id) ON DELETE RESTRICT,
    activity_status TEXT NOT NULL DEFAULT 'ACTIVE'
        CHECK (activity_status IN ('ACTIVE', 'SUSPENDED', 'COMPLETED')),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    is_archived BOOLEAN NOT NULL DEFAULT FALSE,
    archived_at TIMESTAMPTZ,
    version BIGINT NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (parent_entity_id IS DISTINCT FROM entity_id),
    CHECK (
        (is_archived AND archived_at IS NOT NULL)
        OR (NOT is_archived AND archived_at IS NULL)
    )
);

CREATE TABLE public.construction_entity_aliases (
    alias_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    entity_id BIGINT NOT NULL
        REFERENCES public.construction_entities(entity_id) ON DELETE RESTRICT,
    source_value TEXT NOT NULL CHECK (btrim(source_value) <> ''),
    normalized_source_value TEXT GENERATED ALWAYS AS
        (public.normalize_known_value('object', source_value)) STORED,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (normalized_source_value <> '')
);

CREATE UNIQUE INDEX construction_entity_aliases_source_uq
    ON public.construction_entity_aliases(normalized_source_value);
CREATE INDEX construction_entity_aliases_entity_idx
    ON public.construction_entity_aliases(entity_id);

CREATE INDEX construction_entities_parent_idx
    ON public.construction_entities(parent_entity_id);
CREATE UNIQUE INDEX construction_entities_sibling_name_uq
    ON public.construction_entities(
        parent_entity_id,
        public.normalize_known_value('object', name)
    ) NULLS NOT DISTINCT;

CREATE FUNCTION public.guard_clean_construction_entity() RETURNS trigger
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

CREATE TRIGGER clean_construction_entity_guard
    BEFORE INSERT OR UPDATE OR DELETE ON public.construction_entities
    FOR EACH ROW EXECUTE FUNCTION public.guard_clean_construction_entity();

CREATE VIEW public.construction_entity_current AS
SELECT entity_id, name, parent_entity_id, activity_status, is_active,
       is_archived, archived_at, version, created_at, updated_at, category_id
FROM public.construction_entities;

CREATE FUNCTION public.validate_clean_entity_reference() RETURNS trigger
LANGUAGE plpgsql AS $reference$
DECLARE
    changed BOOLEAN;
    target public.construction_entities%ROWTYPE;
    parent public.construction_entities%ROWTYPE;
BEGIN
    PERFORM pg_advisory_xact_lock(20261014, 25);

    IF NEW.entity_id IS NULL THEN
        IF TG_TABLE_NAME = 'rail_tickets' AND NEW.object_id IS NULL THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION 'A construction entity is required'
            USING ERRCODE = '23514';
    END IF;

    SELECT * INTO target
    FROM public.construction_entities
    WHERE entity_id = NEW.entity_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Unknown construction entity %', NEW.entity_id
            USING ERRCODE = '23503';
    END IF;

    IF TG_OP = 'INSERT' THEN
        changed := TRUE;
    ELSE
        changed := NEW.entity_id IS DISTINCT FROM OLD.entity_id;
    END IF;
    IF changed THEN
        IF target.is_archived OR NOT target.is_active THEN
            RAISE EXCEPTION 'Archived or inactive entity cannot receive a new reference'
                USING ERRCODE = '23514';
        END IF;
        IF target.parent_entity_id IS NOT NULL THEN
            SELECT * INTO parent
            FROM public.construction_entities
            WHERE entity_id = target.parent_entity_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Parent construction entity % does not exist', target.parent_entity_id
                    USING ERRCODE = '23503';
            END IF;
            IF parent.is_archived OR NOT parent.is_active THEN
                RAISE EXCEPTION 'Entity under an archived or inactive parent cannot receive a new reference'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
    END IF;
    RETURN NEW;
END
$reference$;

ALTER TABLE public.employee_assignments
    ADD COLUMN entity_id BIGINT REFERENCES public.construction_entities(entity_id) ON DELETE RESTRICT;
ALTER TABLE public.employee_assignments ALTER COLUMN object_id DROP NOT NULL;
ALTER TABLE public.employee_assignments ALTER COLUMN entity_id SET NOT NULL;
ALTER TABLE public.employee_assignments
    ADD CONSTRAINT employee_assignments_entity_only CHECK (object_id IS NULL);
ALTER TABLE public.employee_assignments DROP CONSTRAINT uq_employee_assignment;
ALTER TABLE public.employee_assignments
    ADD CONSTRAINT uq_employee_assignment_entity
    UNIQUE (employee_id, entity_id, po_id, category_id);

ALTER TABLE public.daily_control_results
    ADD COLUMN entity_id BIGINT REFERENCES public.construction_entities(entity_id) ON DELETE RESTRICT;
ALTER TABLE public.daily_control_results ALTER COLUMN object_id DROP NOT NULL;
ALTER TABLE public.daily_control_results ALTER COLUMN entity_id SET NOT NULL;
ALTER TABLE public.daily_control_results
    ADD CONSTRAINT daily_control_results_entity_only
    CHECK (object_id IS NULL AND subobject_id IS NULL);
ALTER TABLE public.daily_control_results DROP CONSTRAINT uq_daily_control_fact;
ALTER TABLE public.daily_control_results
    ADD CONSTRAINT uq_daily_control_fact_entity
    UNIQUE NULLS NOT DISTINCT
    (report_date, employee_id, entity_id, po_id, subcontractor_id, category_id);

ALTER TABLE public.production_assignment_items
    ADD COLUMN entity_id BIGINT REFERENCES public.construction_entities(entity_id) ON DELETE RESTRICT;
ALTER TABLE public.production_assignment_items ALTER COLUMN object_id DROP NOT NULL;
ALTER TABLE public.production_assignment_items ALTER COLUMN entity_id SET NOT NULL;
ALTER TABLE public.production_assignment_items
    ADD CONSTRAINT production_assignment_items_entity_only
    CHECK (object_id IS NULL AND subobject_id IS NULL);
ALTER TABLE public.production_assignment_items
    DROP CONSTRAINT production_assignment_items_change_id_object_id_subobject_i_key;
ALTER TABLE public.production_assignment_items
    ADD CONSTRAINT production_assignment_items_change_entity_uq
    UNIQUE NULLS NOT DISTINCT (change_id, entity_id, po_id, subcontractor_id);

ALTER TABLE public.rail_tickets
    ADD COLUMN entity_id BIGINT REFERENCES public.construction_entities(entity_id) ON DELETE RESTRICT;
ALTER TABLE public.rail_tickets
    ADD CONSTRAINT rail_tickets_entity_only CHECK (object_id IS NULL);

DROP TRIGGER IF EXISTS production_item_parent ON public.production_assignment_items;
CREATE TRIGGER clean_entity_reference_guard
    BEFORE INSERT OR UPDATE ON public.employee_assignments
    FOR EACH ROW EXECUTE FUNCTION public.validate_clean_entity_reference();
CREATE TRIGGER clean_entity_reference_guard
    BEFORE INSERT OR UPDATE ON public.daily_control_results
    FOR EACH ROW EXECUTE FUNCTION public.validate_clean_entity_reference();
CREATE TRIGGER clean_entity_reference_guard
    BEFORE INSERT OR UPDATE ON public.production_assignment_items
    FOR EACH ROW EXECUTE FUNCTION public.validate_clean_entity_reference();
CREATE TRIGGER clean_entity_reference_guard
    BEFORE INSERT OR UPDATE ON public.rail_tickets
    FOR EACH ROW EXECUTE FUNCTION public.validate_clean_entity_reference();

COMMIT;
