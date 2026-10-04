CREATE TABLE IF NOT EXISTS rail_tickets (
    id BIGSERIAL PRIMARY KEY,
    file_hash CHAR(64) NOT NULL UNIQUE CHECK (file_hash ~ '^[0-9a-f]{64}$'),
    source_filename TEXT NOT NULL CHECK (btrim(source_filename) <> ''),
    full_name TEXT,
    departure_station TEXT,
    departure_datetime TIMESTAMP WITHOUT TIME ZONE,
    arrival_station TEXT,
    arrival_datetime TIMESTAMP WITHOUT TIME ZONE,
    parse_errors JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(parse_errors)='array'),
    status TEXT NOT NULL CHECK (status IN ('PARSED','PARSE_ERROR','REJECTED','CONFIRMED')),
    employee_id BIGINT REFERENCES employees(id) ON DELETE RESTRICT,
    movement_type TEXT CHECK (movement_type IN ('ARRIVAL','DEPARTURE')),
    movement_id BIGINT UNIQUE REFERENCES employee_movements(id) ON DELETE RESTRICT,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_rail_ticket_confirmed CHECK (
        (status='CONFIRMED' AND movement_id IS NOT NULL AND employee_id IS NOT NULL
         AND movement_type IS NOT NULL AND full_name IS NOT NULL
         AND departure_station IS NOT NULL AND departure_datetime IS NOT NULL
         AND arrival_station IS NOT NULL AND arrival_datetime IS NOT NULL)
        OR (status<>'CONFIRMED' AND movement_id IS NULL)
    )
);
CREATE INDEX IF NOT EXISTS ix_rail_tickets_employee ON rail_tickets(employee_id);
