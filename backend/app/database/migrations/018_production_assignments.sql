-- Dated assignment changes only. Existing operational tables are not modified.
CREATE TABLE IF NOT EXISTS production_assignment_changes (
    id BIGSERIAL PRIMARY KEY,
    employee_id BIGINT NOT NULL REFERENCES employees(id) ON DELETE RESTRICT,
    effective_from DATE NOT NULL,
    period_kind TEXT NOT NULL CHECK (period_kind IN ('ARRIVAL','EXPLICIT')),
    arrival_movement_ref BIGINT CHECK (arrival_movement_ref > 0),
    arrival_ticket_id BIGINT REFERENCES rail_tickets(id) ON DELETE RESTRICT,
    period_start DATE NOT NULL,
    period_end DATE,
    period_revision TEXT NOT NULL,
    source_kind TEXT NOT NULL CHECK (source_kind IN ('MANUAL','TICKET')),
    source_ticket_id BIGINT REFERENCES rail_tickets(id) ON DELETE RESTRICT,
    source_revision TEXT,
    assignment_state TEXT NOT NULL CHECK (assignment_state IN ('OBJECTS','NO_OBJECT')),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    correction_history JSONB NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(correction_history)='array'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (effective_from >= period_start),
    CHECK (period_end IS NULL OR (period_end >= period_start AND effective_from <= period_end)),
    CHECK ((period_kind='ARRIVAL' AND arrival_movement_ref IS NOT NULL)
        OR (period_kind='EXPLICIT' AND arrival_movement_ref IS NULL AND arrival_ticket_id IS NULL AND period_end IS NOT NULL)),
    CHECK ((source_kind='MANUAL' AND source_ticket_id IS NULL AND source_revision IS NULL)
        OR (source_kind='TICKET' AND source_ticket_id IS NOT NULL AND source_revision IS NOT NULL AND period_kind='ARRIVAL' AND assignment_state='OBJECTS')),
    UNIQUE NULLS NOT DISTINCT (employee_id,period_kind,arrival_movement_ref,period_start,effective_from)
);
CREATE INDEX IF NOT EXISTS ix_production_changes_employee_date
    ON production_assignment_changes(employee_id,effective_from);
CREATE INDEX IF NOT EXISTS ix_production_changes_source_ticket
    ON production_assignment_changes(source_ticket_id);

CREATE TABLE IF NOT EXISTS production_assignment_items (
    id BIGSERIAL PRIMARY KEY,
    change_id BIGINT NOT NULL REFERENCES production_assignment_changes(id) ON DELETE RESTRICT,
    object_id BIGINT NOT NULL REFERENCES construction_objects(id) ON DELETE RESTRICT,
    subobject_id BIGINT REFERENCES construction_subobjects(id) ON DELETE RESTRICT,
    po_id BIGINT REFERENCES po_types(id) ON DELETE RESTRICT,
    subcontractor_id BIGINT REFERENCES po_types(id) ON DELETE RESTRICT,
    initial_category_id BIGINT REFERENCES object_categories(id) ON DELETE RESTRICT,
    initial_control_mode TEXT CHECK (initial_control_mode IN ('INSPECTION','OPERATIONAL')),
    -- Provenance, not a live dependency: existing assignments may be removed.
    source_assignment_id BIGINT CHECK (source_assignment_id > 0),
    UNIQUE NULLS NOT DISTINCT (change_id,object_id,subobject_id,po_id,subcontractor_id)
);

CREATE OR REPLACE FUNCTION validate_production_assignment_item() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP='UPDATE' AND NEW.change_id<>OLD.change_id THEN
        RAISE EXCEPTION 'Assignment item cannot move to another change' USING ERRCODE='23514';
    END IF;
    IF NEW.subobject_id IS NOT NULL THEN
        PERFORM 1 FROM construction_subobjects
            WHERE id=NEW.subobject_id AND object_id=NEW.object_id AND is_active FOR SHARE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Subobject does not belong to object or is inactive' USING ERRCODE='23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS production_item_parent ON production_assignment_items;
CREATE TRIGGER production_item_parent BEFORE INSERT OR UPDATE ON production_assignment_items
    FOR EACH ROW EXECUTE FUNCTION validate_production_assignment_item();

CREATE OR REPLACE FUNCTION validate_production_assignment_shape() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE target_id BIGINT; state TEXT; item_count BIGINT;
BEGIN
    IF TG_TABLE_NAME='production_assignment_changes' THEN target_id=NEW.id;
    ELSIF TG_OP='DELETE' THEN target_id=OLD.change_id;
    ELSE target_id=NEW.change_id; END IF;
    SELECT assignment_state INTO state FROM production_assignment_changes WHERE id=target_id;
    IF NOT FOUND THEN RETURN NULL; END IF;
    SELECT count(*) INTO item_count FROM production_assignment_items WHERE change_id=target_id;
    IF (state='OBJECTS' AND item_count=0) OR (state='NO_OBJECT' AND item_count<>0) THEN
        RAISE EXCEPTION 'Assignment state and items disagree' USING ERRCODE='23514';
    END IF;
    RETURN NULL;
END;
$$;
DROP TRIGGER IF EXISTS production_change_shape ON production_assignment_changes;
CREATE CONSTRAINT TRIGGER production_change_shape AFTER INSERT OR UPDATE ON production_assignment_changes
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION validate_production_assignment_shape();
DROP TRIGGER IF EXISTS production_items_shape ON production_assignment_items;
CREATE CONSTRAINT TRIGGER production_items_shape AFTER INSERT OR UPDATE OR DELETE ON production_assignment_items
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION validate_production_assignment_shape();
