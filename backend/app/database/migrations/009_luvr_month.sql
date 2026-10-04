-- A header preserves the distinction between an empty and an unformed month.
CREATE TABLE IF NOT EXISTS luvr_months (
    year INTEGER NOT NULL CHECK (year BETWEEN 1 AND 9999),
    month INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (year, month)
);
CREATE TABLE IF NOT EXISTS luvr_month_employees (
    id BIGSERIAL PRIMARY KEY,
    year INTEGER NOT NULL,
    month INTEGER NOT NULL,
    employee_id BIGINT NOT NULL REFERENCES employees(id) ON DELETE RESTRICT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (year, month) REFERENCES luvr_months(year, month) ON DELETE RESTRICT,
    UNIQUE (year, month, employee_id)
);
CREATE INDEX IF NOT EXISTS ix_luvr_month_employees_employee ON luvr_month_employees(employee_id);
