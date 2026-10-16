-- Presentation absences do not participate in LUVR calculations.
CREATE TABLE IF NOT EXISTS employee_absences (
    id BIGSERIAL PRIMARY KEY,
    employee_id BIGINT NOT NULL REFERENCES employees(id) ON DELETE RESTRICT,
    reason TEXT NOT NULL CHECK (reason ~ '[^[:space:]]'),
    date_from DATE NOT NULL,
    date_to DATE NOT NULL,
    comment TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_employee_absence_dates CHECK(date_to >= date_from)
);
CREATE INDEX IF NOT EXISTS ix_employee_absences_dates ON employee_absences(employee_id,date_from,date_to);
-- Existing illness stays in its original table and retains its calculation semantics.
CREATE TABLE IF NOT EXISTS employee_sick_absence_labels (
    sick_period_id BIGINT PRIMARY KEY REFERENCES employee_sick_periods(id) ON DELETE CASCADE,
    reason TEXT NOT NULL CHECK (reason ~ '[^[:space:]]')
);
