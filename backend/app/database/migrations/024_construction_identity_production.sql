-- Production-only counterpart to 024_construction_identity.sql.
-- Apply only through migrate_construction_identity_production.py in one transaction.
-- Existing object/subobject and consumer rows are not rewritten.
DO $$
DECLARE
    required_table TEXT;
    required_column TEXT;
BEGIN
    IF current_database() <> 'ai_excel_agent' OR current_schema() <> 'public' THEN
        RAISE EXCEPTION 'Production 024 is restricted to ai_excel_agent.public';
    END IF;

    FOREACH required_table IN ARRAY ARRAY[
        'employees', 'construction_objects', 'construction_subobjects', 'employee_assignments',
        'rail_tickets', 'production_assignment_items', 'daily_control_results'
    ] LOOP
        IF to_regclass(format('%I.%I', current_schema(), required_table)) IS NULL THEN
            RAISE EXCEPTION 'Required production table is missing: %', required_table;
        END IF;
    END LOOP;

    IF to_regclass('construction_entities') IS NOT NULL
       OR to_regclass('construction_entity_hierarchy') IS NOT NULL
       OR to_regclass('construction_entity_current') IS NOT NULL THEN
        RAISE EXCEPTION 'Construction identity objects already exist; refusing partial or repeated production migration';
    END IF;

    FOREACH required_column IN ARRAY ARRAY[
        'employee_assignments.entity_id',
        'rail_tickets.entity_id',
        'production_assignment_items.entity_id',
        'daily_control_results.entity_id',
        'construction_subobjects.initial_parent_entity_id'
    ] LOOP
        IF EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = split_part(required_column, '.', 1)
              AND column_name = split_part(required_column, '.', 2)
        ) THEN
            RAISE EXCEPTION 'Identity column already exists: %', required_column;
        END IF;
    END LOOP;

    IF to_regprocedure('normalize_known_value(text,text)') IS NULL THEN
        RAISE EXCEPTION 'Required normalize_known_value(text,text) function is missing';
    END IF;

    IF EXISTS (
        SELECT 1 FROM construction_subobjects s
        LEFT JOIN construction_objects o ON o.id = s.object_id
        WHERE o.id IS NULL
    ) THEN
        RAISE EXCEPTION 'Orphan construction_subobjects rows exist';
    END IF;

    IF EXISTS (
        SELECT 1 FROM employee_assignments a
        LEFT JOIN employees e ON e.id = a.employee_id
        LEFT JOIN construction_objects o ON o.id = a.object_id
        WHERE e.id IS NULL OR o.id IS NULL
    ) THEN
        RAISE EXCEPTION 'Invalid employee_assignments references exist';
    END IF;

    IF EXISTS (
        SELECT 1 FROM daily_control_results f
        LEFT JOIN employees e ON e.id = f.employee_id
        LEFT JOIN construction_objects o ON o.id = f.object_id
        LEFT JOIN construction_subobjects s ON s.id = f.subobject_id
        WHERE e.id IS NULL OR (f.object_id IS NOT NULL AND o.id IS NULL)
           OR (f.subobject_id IS NOT NULL AND s.id IS NULL)
    ) THEN
        RAISE EXCEPTION 'Invalid daily_control_results references exist';
    END IF;

    IF EXISTS (
        SELECT 1 FROM production_assignment_items i
        LEFT JOIN construction_objects o ON o.id = i.object_id
        LEFT JOIN construction_subobjects s ON s.id = i.subobject_id
        WHERE (i.object_id IS NOT NULL AND o.id IS NULL)
           OR (i.subobject_id IS NOT NULL AND s.id IS NULL)
    ) THEN
        RAISE EXCEPTION 'Invalid production_assignment_items references exist';
    END IF;

    IF EXISTS (
        SELECT 1 FROM rail_tickets t
        LEFT JOIN construction_objects o ON o.id = t.object_id
        WHERE t.object_id IS NOT NULL AND o.id IS NULL
    ) THEN
        RAISE EXCEPTION 'Invalid rail_tickets object references exist';
    END IF;

    IF EXISTS (
        SELECT 1 FROM (
            SELECT normalize_known_value('object', name) AS normalized_name
            FROM construction_objects
            GROUP BY 1 HAVING count(*) > 1
        ) duplicates
    ) OR EXISTS (
        SELECT 1 FROM (
            SELECT object_id, normalize_known_value('object', name) AS normalized_name
            FROM construction_subobjects
            GROUP BY 1, 2 HAVING count(*) > 1
        ) duplicates
    ) THEN
        RAISE EXCEPTION 'Normalized duplicate object or sibling-subobject names exist';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM daily_control_results
        GROUP BY report_date, employee_id, object_id, subobject_id, po_id, subcontractor_id, category_id
        HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION 'Duplicate daily-control identity keys prevent the replacement unique constraint';
    END IF;
END
$$;

CREATE TABLE construction_entities (
    id BIGSERIAL PRIMARY KEY,
    legacy_object_id BIGINT UNIQUE REFERENCES construction_objects(id) ON DELETE RESTRICT,
    legacy_subobject_id BIGINT UNIQUE REFERENCES construction_subobjects(id) ON DELETE RESTRICT,
    CHECK (num_nonnulls(legacy_object_id, legacy_subobject_id) = 1)
);

CREATE TABLE construction_entity_hierarchy (
    entity_id BIGINT PRIMARY KEY REFERENCES construction_entities(id) ON DELETE RESTRICT,
    parent_entity_id BIGINT REFERENCES construction_entities(id) ON DELETE RESTRICT,
    version BIGINT NOT NULL DEFAULT 1 CHECK (version > 0),
    CHECK (parent_entity_id IS DISTINCT FROM entity_id)
);

ALTER TABLE construction_subobjects
    ADD COLUMN initial_parent_entity_id BIGINT REFERENCES construction_entities(id) ON DELETE RESTRICT;
ALTER TABLE construction_subobjects ALTER COLUMN object_id DROP NOT NULL;
CREATE INDEX construction_hierarchy_parent ON construction_entity_hierarchy(parent_entity_id);

-- Each source table has its own legacy ID namespace. Surrogate entity IDs are
-- generated independently, so equal object/subobject IDs cannot collide.
INSERT INTO construction_entities (legacy_object_id)
    SELECT id FROM construction_objects ORDER BY id;
INSERT INTO construction_entities (legacy_subobject_id)
    SELECT id FROM construction_subobjects ORDER BY id;
INSERT INTO construction_entity_hierarchy (entity_id, parent_entity_id)
    SELECT e.id, p.id
    FROM construction_entities e
    LEFT JOIN construction_subobjects s ON s.id = e.legacy_subobject_id
    LEFT JOIN construction_entities p ON p.legacy_object_id = s.object_id
    ORDER BY e.id;

CREATE VIEW construction_entity_current AS
    SELECT e.id AS entity_id, e.legacy_object_id, e.legacy_subobject_id,
           COALESCE(o.name, s.name) AS name, h.parent_entity_id, h.version,
           COALESCE(o.is_archived, s.is_archived) AS is_archived,
           COALESCE(o.archived_at, s.archived_at) AS archived_at,
           COALESCE(o.activity_status, s.activity_status) AS activity_status,
           COALESCE(s.is_active, true) AS is_active
    FROM construction_entities e
    JOIN construction_entity_hierarchy h ON h.entity_id = e.id
    LEFT JOIN construction_objects o ON o.id = e.legacy_object_id
    LEFT JOIN construction_subobjects s ON s.id = e.legacy_subobject_id;

CREATE OR REPLACE FUNCTION guard_construction_hierarchy() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(20261013, 24);
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Construction identity cannot be deleted' USING ERRCODE = '23514';
    END IF;
    IF NEW.parent_entity_id IS NOT NULL THEN
        IF NOT EXISTS (
            SELECT 1 FROM construction_entity_hierarchy
            WHERE entity_id = NEW.parent_entity_id AND parent_entity_id IS NULL
        ) OR EXISTS (
            SELECT 1 FROM construction_entity_hierarchy WHERE parent_entity_id = NEW.entity_id
        ) THEN
            RAISE EXCEPTION 'Only two hierarchy levels are allowed' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER construction_hierarchy_guard
    BEFORE INSERT OR UPDATE OR DELETE ON construction_entity_hierarchy
    FOR EACH ROW EXECUTE FUNCTION guard_construction_hierarchy();

ALTER TABLE employee_assignments
    ADD COLUMN entity_id BIGINT REFERENCES construction_entities(id) ON DELETE RESTRICT;
ALTER TABLE rail_tickets
    ADD COLUMN entity_id BIGINT REFERENCES construction_entities(id) ON DELETE RESTRICT;
ALTER TABLE production_assignment_items
    ADD COLUMN entity_id BIGINT REFERENCES construction_entities(id) ON DELETE RESTRICT;
ALTER TABLE daily_control_results
    ADD COLUMN entity_id BIGINT REFERENCES construction_entities(id) ON DELETE RESTRICT;

CREATE OR REPLACE FUNCTION construction_reference(e BIGINT, o BIGINT, s BIGINT DEFAULT NULL)
RETURNS BIGINT LANGUAGE sql STABLE AS $$
    SELECT COALESCE(e, (
        SELECT id FROM construction_entities
        WHERE CASE WHEN s IS NOT NULL THEN legacy_subobject_id = s ELSE legacy_object_id = o END
    ))
$$;

CREATE OR REPLACE FUNCTION lock_construction_structure() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(20261013, 24);
    RETURN NULL;
END
$$;

CREATE TRIGGER identity_structure_lock
    BEFORE INSERT OR UPDATE ON construction_objects
    FOR EACH STATEMENT EXECUTE FUNCTION lock_construction_structure();
CREATE TRIGGER identity_structure_lock
    BEFORE INSERT OR UPDATE ON construction_subobjects
    FOR EACH STATEMENT EXECUTE FUNCTION lock_construction_structure();

CREATE OR REPLACE FUNCTION register_construction_identity() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    eid BIGINT;
    parent BIGINT;
BEGIN
    IF TG_TABLE_NAME = 'construction_objects' THEN
        INSERT INTO construction_entities (legacy_object_id) VALUES (NEW.id) RETURNING id INTO eid;
    ELSE
        SELECT entity_id INTO parent
        FROM construction_entity_current
        WHERE ((NEW.initial_parent_entity_id IS NOT NULL AND entity_id = NEW.initial_parent_entity_id)
            OR (NEW.initial_parent_entity_id IS NULL AND legacy_object_id = NEW.object_id))
          AND parent_entity_id IS NULL AND NOT is_archived;
        IF NEW.initial_parent_entity_id IS NOT NULL AND NEW.object_id IS NOT NULL
           AND NEW.object_id IS DISTINCT FROM (
               SELECT legacy_object_id FROM construction_entities WHERE id = parent
           ) THEN
            RAISE EXCEPTION 'Inconsistent parent identity' USING ERRCODE = '23514';
        END IF;
        IF parent IS NULL THEN
            RAISE EXCEPTION 'Select a standalone non-archived parent' USING ERRCODE = '23514';
        END IF;
        INSERT INTO construction_entities (legacy_subobject_id) VALUES (NEW.id) RETURNING id INTO eid;
    END IF;

    IF EXISTS (
        SELECT 1 FROM construction_entity_current c
        WHERE c.parent_entity_id IS NOT DISTINCT FROM parent
          AND normalize_known_value('object', c.name) = normalize_known_value('object', NEW.name)
    ) THEN
        RAISE EXCEPTION 'Duplicate name in current hierarchy' USING ERRCODE = '23505';
    END IF;
    INSERT INTO construction_entity_hierarchy (entity_id, parent_entity_id) VALUES (eid, parent);
    RETURN NEW;
END
$$;

ALTER TABLE daily_control_results ALTER COLUMN object_id DROP NOT NULL;

CREATE OR REPLACE FUNCTION validate_fact_identity() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    eid BIGINT;
    source construction_entities%ROWTYPE;
BEGIN
    PERFORM pg_advisory_xact_lock(20261013, 24);
    eid = construction_reference(NEW.entity_id, NEW.object_id, NEW.subobject_id);
    SELECT * INTO source FROM construction_entities WHERE id = eid;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Fact requires a valid entity' USING ERRCODE = '23503';
    END IF;
    IF NEW.subobject_id IS NOT NULL AND source.legacy_subobject_id IS DISTINCT FROM NEW.subobject_id THEN
        RAISE EXCEPTION 'Inconsistent fact subobject' USING ERRCODE = '23514';
    END IF;
    IF NEW.object_id IS NOT NULL AND NEW.object_id IS DISTINCT FROM COALESCE(
        source.legacy_object_id,
        (SELECT object_id FROM construction_subobjects WHERE id = source.legacy_subobject_id)
    ) THEN
        RAISE EXCEPTION 'Inconsistent fact object' USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        SELECT 1 FROM daily_control_results r
        WHERE r.id IS DISTINCT FROM NEW.id
          AND r.report_date = NEW.report_date AND r.employee_id = NEW.employee_id
          AND construction_reference(r.entity_id, r.object_id, r.subobject_id) = eid
          AND r.po_id IS NOT DISTINCT FROM NEW.po_id
          AND r.category_id IS NOT DISTINCT FROM NEW.category_id
          AND r.subcontractor_id IS NOT DISTINCT FROM NEW.subcontractor_id
    ) THEN
        RAISE EXCEPTION 'Duplicate fact identity' USING ERRCODE = '23505';
    END IF;
    IF TG_OP = 'INSERT' THEN NEW.entity_id = eid; END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER fact_identity_guard
    BEFORE INSERT OR UPDATE ON daily_control_results
    FOR EACH ROW EXECUTE FUNCTION validate_fact_identity();

ALTER TABLE daily_control_results DROP CONSTRAINT uq_daily_control_fact;
ALTER TABLE daily_control_results ADD CONSTRAINT uq_daily_control_fact
    UNIQUE NULLS NOT DISTINCT
    (report_date, employee_id, object_id, subobject_id, entity_id, po_id, subcontractor_id, category_id);

CREATE TRIGGER register_identity
    AFTER INSERT ON construction_objects
    FOR EACH ROW EXECUTE FUNCTION register_construction_identity();
CREATE TRIGGER register_identity
    AFTER INSERT ON construction_subobjects
    FOR EACH ROW EXECUTE FUNCTION register_construction_identity();

CREATE OR REPLACE FUNCTION validate_construction_reference() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    eid BIGINT;
    sid BIGINT;
    source construction_entities%ROWTYPE;
    current_item construction_entity_current%ROWTYPE;
    changed BOOLEAN;
BEGIN
    PERFORM pg_advisory_xact_lock(20261013, 24);
    sid = (to_jsonb(NEW)->>'subobject_id')::BIGINT;
    eid = construction_reference(NEW.entity_id, NEW.object_id, sid);
    IF eid IS NULL THEN
        IF TG_TABLE_NAME = 'rail_tickets' AND NEW.object_id IS NULL AND NEW.entity_id IS NULL THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION 'Construction reference required' USING ERRCODE = '23514';
    END IF;
    SELECT * INTO source FROM construction_entities WHERE id = eid;
    IF NOT FOUND THEN RAISE EXCEPTION 'Unknown entity' USING ERRCODE = '23503'; END IF;
    IF sid IS NOT NULL AND source.legacy_subobject_id IS DISTINCT FROM sid THEN
        RAISE EXCEPTION 'Inconsistent subobject identity' USING ERRCODE = '23514';
    END IF;
    IF NEW.object_id IS NOT NULL AND NEW.object_id IS DISTINCT FROM COALESCE(
        source.legacy_object_id,
        (SELECT object_id FROM construction_subobjects WHERE id = source.legacy_subobject_id)
    ) THEN
        RAISE EXCEPTION 'Inconsistent object identity' USING ERRCODE = '23514';
    END IF;

    changed = TG_OP = 'INSERT';
    IF TG_OP = 'UPDATE' THEN
        changed = eid IS DISTINCT FROM construction_reference(
            OLD.entity_id, OLD.object_id, (to_jsonb(OLD)->>'subobject_id')::BIGINT
        );
    END IF;
    SELECT * INTO current_item FROM construction_entity_current WHERE entity_id = eid;
    IF changed AND (current_item.is_archived OR NOT current_item.is_active OR EXISTS (
        SELECT 1 FROM construction_entity_current
        WHERE entity_id = current_item.parent_entity_id AND is_archived
    )) THEN
        RAISE EXCEPTION 'Archived or inactive entity cannot receive new assignments' USING ERRCODE = '23514';
    END IF;

    IF TG_TABLE_NAME = 'employee_assignments' THEN
        IF EXISTS (
            SELECT 1 FROM employee_assignments a
            WHERE a.id IS DISTINCT FROM NEW.id
              AND a.employee_id = NEW.employee_id
              AND a.po_id IS NOT DISTINCT FROM NEW.po_id
              AND a.category_id IS NOT DISTINCT FROM NEW.category_id
              AND construction_reference(a.entity_id, a.object_id) = eid
        ) THEN
            RAISE EXCEPTION 'Duplicate assignment identity' USING ERRCODE = '23505';
        END IF;
    ELSIF TG_TABLE_NAME = 'production_assignment_items' THEN
        IF TG_OP = 'UPDATE' AND NEW.change_id <> OLD.change_id THEN
            RAISE EXCEPTION 'Cannot move assignment item' USING ERRCODE = '23514';
        END IF;
        IF EXISTS (
            SELECT 1 FROM production_assignment_items a
            WHERE a.id IS DISTINCT FROM NEW.id AND a.change_id = NEW.change_id
              AND a.po_id IS NOT DISTINCT FROM NEW.po_id
              AND a.subcontractor_id IS NOT DISTINCT FROM NEW.subcontractor_id
              AND construction_reference(a.entity_id, a.object_id, a.subobject_id) = eid
        ) THEN
            RAISE EXCEPTION 'Duplicate production identity' USING ERRCODE = '23505';
        END IF;
    END IF;

    IF TG_OP = 'INSERT' THEN NEW.entity_id = eid; END IF;
    RETURN NEW;
END
$$;

DROP TRIGGER production_item_parent ON production_assignment_items;
CREATE TRIGGER identity_reference_guard
    BEFORE INSERT OR UPDATE ON employee_assignments
    FOR EACH ROW EXECUTE FUNCTION validate_construction_reference();
CREATE TRIGGER identity_reference_guard
    BEFORE INSERT OR UPDATE ON production_assignment_items
    FOR EACH ROW EXECUTE FUNCTION validate_construction_reference();
CREATE TRIGGER identity_reference_guard
    BEFORE INSERT OR UPDATE ON rail_tickets
    FOR EACH ROW EXECUTE FUNCTION validate_construction_reference();

DO $$
DECLARE
    constraint_name TEXT;
BEGIN
    FOR constraint_name IN
        SELECT conname FROM pg_constraint
        WHERE conrelid = 'production_assignment_items'::regclass AND contype = 'u'
          AND (
              SELECT array_agg(a.attname::TEXT ORDER BY k.ordinality)
              FROM unnest(conkey) WITH ORDINALITY k(attnum, ordinality)
              JOIN pg_attribute a ON a.attrelid = conrelid AND a.attnum = k.attnum
          ) = ARRAY['change_id', 'object_id', 'subobject_id', 'po_id', 'subcontractor_id']
    LOOP
        EXECUTE format('ALTER TABLE production_assignment_items DROP CONSTRAINT %I', constraint_name);
    END LOOP;
END
$$;

DO $$
DECLARE
    objects_count BIGINT;
    subobjects_count BIGINT;
BEGIN
    SELECT count(*) INTO objects_count FROM construction_objects;
    SELECT count(*) INTO subobjects_count FROM construction_subobjects;

    IF (SELECT count(*) FROM construction_entities) <> objects_count + subobjects_count
       OR (SELECT count(*) FROM construction_entity_hierarchy) <> objects_count + subobjects_count THEN
        RAISE EXCEPTION 'Entity/hierarchy counts do not match source catalog: objects %, subobjects %',
            objects_count, subobjects_count;
    END IF;

    IF EXISTS (
        SELECT 1 FROM construction_objects o
        LEFT JOIN construction_entities e ON e.legacy_object_id = o.id
        LEFT JOIN construction_entity_hierarchy h ON h.entity_id = e.id
        WHERE e.id IS NULL OR h.entity_id IS NULL OR h.parent_entity_id IS NOT NULL
    ) OR EXISTS (
        SELECT 1 FROM construction_subobjects s
        LEFT JOIN construction_entities e ON e.legacy_subobject_id = s.id
        LEFT JOIN construction_entities p ON p.legacy_object_id = s.object_id
        LEFT JOIN construction_entity_hierarchy h ON h.entity_id = e.id
        WHERE e.id IS NULL OR p.id IS NULL OR h.entity_id IS NULL OR h.parent_entity_id IS DISTINCT FROM p.id
    ) THEN
        RAISE EXCEPTION 'Entity hierarchy does not preserve source IDs and parent links';
    END IF;

    IF (SELECT count(*) FROM construction_entity_current) <> objects_count + subobjects_count THEN
        RAISE EXCEPTION 'Current entity view does not contain every source row';
    END IF;
END
$$;
