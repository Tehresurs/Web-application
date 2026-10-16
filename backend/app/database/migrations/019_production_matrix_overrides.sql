CREATE TABLE IF NOT EXISTS production_matrix_overrides (
    id BIGSERIAL PRIMARY KEY,
    employee_id BIGINT NOT NULL REFERENCES employees(id) ON DELETE RESTRICT,
    effective_from DATE NOT NULL,
    scope TEXT NOT NULL CHECK (scope IN ('FACT','PLAN')),
    field_name TEXT NOT NULL CHECK (field_name IN ('CATEGORY','CONTROL_MODE')),
    category_id BIGINT REFERENCES object_categories(id) ON DELETE RESTRICT,
    control_mode TEXT CHECK (control_mode IN ('INSPECTION','OPERATIONAL')),
    fact_id BIGINT REFERENCES daily_control_results(id) ON DELETE RESTRICT,
    assignment_item_id BIGINT REFERENCES production_assignment_items(id) ON DELETE SET NULL,
    -- Retain provenance if stage 3A corrects/replaces the source item.
    assignment_item_ref BIGINT CHECK (assignment_item_ref > 0),
    period_key TEXT NOT NULL CHECK (btrim(period_key)<>''),
    basis_revision TEXT NOT NULL CHECK (btrim(basis_revision)<>''),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version>0),
    is_deleted BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK ((field_name='CATEGORY' AND category_id IS NOT NULL AND control_mode IS NULL)
        OR (field_name='CONTROL_MODE' AND control_mode IS NOT NULL AND category_id IS NULL)),
    CHECK ((fact_id IS NOT NULL AND assignment_item_ref IS NULL AND assignment_item_id IS NULL)
        OR (fact_id IS NULL AND assignment_item_ref IS NOT NULL)),
    CHECK (assignment_item_id IS NULL OR assignment_item_id=assignment_item_ref),
    CHECK (scope<>'FACT' OR fact_id IS NOT NULL),
    UNIQUE NULLS NOT DISTINCT
        (employee_id,period_key,basis_revision,scope,fact_id,assignment_item_ref,field_name,effective_from)
);
CREATE INDEX IF NOT EXISTS ix_matrix_overrides_employee_date
    ON production_matrix_overrides(employee_id,effective_from);
CREATE INDEX IF NOT EXISTS ix_matrix_overrides_item ON production_matrix_overrides(assignment_item_id);
CREATE INDEX IF NOT EXISTS ix_matrix_overrides_fact ON production_matrix_overrides(fact_id);
