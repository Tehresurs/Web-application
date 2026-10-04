-- Additive LU VR stage 1. Existing records remain unknown (NULL), never inferred.
ALTER TABLE positions ADD COLUMN IF NOT EXISTS specialty TEXT;
ALTER TABLE positions ADD COLUMN IF NOT EXISTS work_location TEXT;
ALTER TABLE positions ADD COLUMN IF NOT EXISTS work_schedule TEXT;
ALTER TABLE employees ADD COLUMN IF NOT EXISTS nrs_number TEXT;
ALTER TABLE employees ADD COLUMN IF NOT EXISTS max_shift_days INTEGER;
ALTER TABLE employees ADD COLUMN IF NOT EXISTS max_off_shift_days INTEGER;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='positions'::regclass AND conname='ck_positions_work_location') THEN
        ALTER TABLE positions ADD CONSTRAINT ck_positions_work_location CHECK(work_location IN ('OBJECT','OFFICE'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='positions'::regclass AND conname='ck_positions_work_schedule') THEN
        ALTER TABLE positions ADD CONSTRAINT ck_positions_work_schedule CHECK(work_schedule IN ('SHIFT','FIVE_TWO'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='positions'::regclass AND conname='ck_positions_object_shift') THEN
        ALTER TABLE positions ADD CONSTRAINT ck_positions_object_shift
            CHECK(work_location IS DISTINCT FROM 'OBJECT' OR work_schedule IS NOT DISTINCT FROM 'SHIFT');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='employees'::regclass AND conname='ck_employees_max_shift_days') THEN
        ALTER TABLE employees ADD CONSTRAINT ck_employees_max_shift_days CHECK(max_shift_days > 0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='employees'::regclass AND conname='ck_employees_max_off_shift_days') THEN
        ALTER TABLE employees ADD CONSTRAINT ck_employees_max_off_shift_days CHECK(max_off_shift_days > 0);
    END IF;
END;
$$;
