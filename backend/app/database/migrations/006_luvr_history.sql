-- Continuous employee history, independent of calendar months.
ALTER TABLE employees ADD COLUMN IF NOT EXISTS dismissal_date DATE;
ALTER TABLE employees ADD COLUMN IF NOT EXISTS is_archived BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE employees ADD COLUMN IF NOT EXISTS archived_at TIMESTAMP WITHOUT TIME ZONE;

CREATE TABLE IF NOT EXISTS employee_movements (
    id BIGSERIAL PRIMARY KEY,
    employee_id BIGINT NOT NULL REFERENCES employees(id) ON DELETE RESTRICT,
    movement_type TEXT NOT NULL CHECK (movement_type IN ('ARRIVAL','DEPARTURE')),
    transport_type TEXT NOT NULL CHECK (transport_type IN ('RAIL','SELF')),
    event_datetime TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    departure_station TEXT,
    arrival_station TEXT,
    source_file TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_movement_self_source CHECK (transport_type <> 'SELF' OR source_file IS NULL)
);
CREATE INDEX IF NOT EXISTS ix_employee_movements_time ON employee_movements(employee_id,event_datetime,id);

CREATE TABLE IF NOT EXISTS employee_sick_periods (
    id BIGSERIAL PRIMARY KEY,
    employee_id BIGINT NOT NULL REFERENCES employees(id) ON DELETE RESTRICT,
    date_from DATE NOT NULL,
    date_to DATE,
    comment TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_sick_period_dates CHECK (date_to IS NULL OR date_to >= date_from)
);
CREATE INDEX IF NOT EXISTS ix_employee_sick_dates ON employee_sick_periods(employee_id,date_from);

CREATE TABLE IF NOT EXISTS employee_duration_exceptions (
    id BIGSERIAL PRIMARY KEY,
    employee_id BIGINT NOT NULL REFERENCES employees(id) ON DELETE RESTRICT,
    exception_type TEXT NOT NULL CHECK (exception_type IN ('SHIFT','OFF_SHIFT')),
    date_from DATE NOT NULL,
    date_to DATE NOT NULL,
    comment TEXT NOT NULL CHECK (comment ~ '[^[:space:]]'),
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_duration_exception_dates CHECK (date_to >= date_from)
);
CREATE INDEX IF NOT EXISTS ix_employee_exception_dates ON employee_duration_exceptions(employee_id,date_from);

CREATE TABLE IF NOT EXISTS employee_luvr_day_overrides (
    id BIGSERIAL PRIMARY KEY,
    employee_id BIGINT NOT NULL REFERENCES employees(id) ON DELETE RESTRICT,
    work_date DATE NOT NULL,
    value TEXT NOT NULL CHECK (value IN ('FULL','HALF','TRAVEL','OFF_SHIFT','DOWNTIME','DISMISSED','EMPTY')),
    comment TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_employee_luvr_day UNIQUE (employee_id,work_date)
);
