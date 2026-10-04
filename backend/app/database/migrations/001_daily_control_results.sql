-- Run explicitly after the existing directories and employee_assignments exist.
CREATE TABLE IF NOT EXISTS daily_control_results (
    id BIGSERIAL PRIMARY KEY,
    report_date DATE NOT NULL,
    employee_id BIGINT NOT NULL REFERENCES employees(id) ON DELETE RESTRICT,
    object_id BIGINT NOT NULL REFERENCES construction_objects(id) ON DELETE RESTRICT,
    po_id BIGINT NOT NULL REFERENCES po_types(id) ON DELETE RESTRICT,
    category_id BIGINT NOT NULL REFERENCES object_categories(id) ON DELETE RESTRICT,
    source_file TEXT NOT NULL CHECK (btrim(source_file) <> ''),
    source_sha256 CHAR(64) NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_daily_control_fact UNIQUE
        (report_date, employee_id, object_id, po_id, category_id)
);

CREATE INDEX IF NOT EXISTS ix_daily_control_date ON daily_control_results(report_date);
CREATE INDEX IF NOT EXISTS ix_daily_control_employee_date
    ON daily_control_results(employee_id, report_date);
CREATE INDEX IF NOT EXISTS ix_daily_control_object_date
    ON daily_control_results(object_id, report_date);
CREATE INDEX IF NOT EXISTS ix_daily_control_source ON daily_control_results(source_sha256);
