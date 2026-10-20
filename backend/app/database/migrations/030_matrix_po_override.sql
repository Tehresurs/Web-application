-- Add PO to the existing sparse overlay mechanism; preserve source records.
ALTER TABLE production_matrix_overrides
    ADD COLUMN IF NOT EXISTS po_id BIGINT REFERENCES po_types(id) ON DELETE RESTRICT;
DO $$
DECLARE c RECORD;
BEGIN
    FOR c IN SELECT conname FROM pg_constraint
        WHERE conrelid='production_matrix_overrides'::regclass AND contype='c'
          AND pg_get_constraintdef(oid) LIKE '%field_name%'
    LOOP
        EXECUTE format('ALTER TABLE production_matrix_overrides DROP CONSTRAINT %I',c.conname);
    END LOOP;
END $$;
ALTER TABLE production_matrix_overrides
    ADD CONSTRAINT matrix_override_field_check CHECK (field_name IN ('CATEGORY','CONTROL_MODE','PO')),
    ADD CONSTRAINT matrix_override_value_check CHECK (
        (field_name='CATEGORY' AND category_id IS NOT NULL AND control_mode IS NULL AND po_id IS NULL)
        OR (field_name='CONTROL_MODE' AND control_mode IS NOT NULL AND category_id IS NULL AND po_id IS NULL)
        OR (field_name='PO' AND po_id IS NOT NULL AND category_id IS NULL AND control_mode IS NULL));
