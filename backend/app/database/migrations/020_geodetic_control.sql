CREATE TABLE IF NOT EXISTS production_control_mode_positions (
    position_id BIGINT PRIMARY KEY REFERENCES positions(id) ON DELETE RESTRICT,
    control_mode TEXT NOT NULL CHECK (control_mode='GEODETIC')
);
-- One-time binding by the exact approved directory entry; runtime uses its ID.
DO $$
BEGIN
    IF (SELECT count(*) FROM positions WHERE name='Инженер СК (Геодезические работы)')>1 THEN
        RAISE EXCEPTION 'Ambiguous geodetic position';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM production_control_mode_positions) THEN
        INSERT INTO production_control_mode_positions(position_id,control_mode)
        SELECT id,'GEODETIC' FROM positions WHERE name='Инженер СК (Геодезические работы)';
    END IF;
END $$;
ALTER TABLE production_assignment_items DROP CONSTRAINT IF EXISTS production_assignment_items_initial_control_mode_check;
ALTER TABLE production_assignment_items ADD CONSTRAINT production_assignment_items_initial_control_mode_check
    CHECK (initial_control_mode IN ('INSPECTION','OPERATIONAL','GEODETIC'));
ALTER TABLE production_matrix_overrides DROP CONSTRAINT IF EXISTS production_matrix_overrides_control_mode_check;
ALTER TABLE production_matrix_overrides ADD CONSTRAINT production_matrix_overrides_control_mode_check
    CHECK (control_mode IN ('INSPECTION','OPERATIONAL','GEODETIC'));
