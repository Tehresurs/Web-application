ALTER TABLE construction_objects
 ADD COLUMN IF NOT EXISTS is_archived BOOLEAN NOT NULL DEFAULT false,
 ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ,
 ADD COLUMN IF NOT EXISTS activity_status TEXT NOT NULL DEFAULT 'ACTIVE';
ALTER TABLE construction_subobjects
 ADD COLUMN IF NOT EXISTS is_archived BOOLEAN NOT NULL DEFAULT false,
 ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ,
 ADD COLUMN IF NOT EXISTS activity_status TEXT NOT NULL DEFAULT 'ACTIVE';
DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='construction_objects'::regclass AND conname='object_activity_status_check') THEN
  ALTER TABLE construction_objects ADD CONSTRAINT object_activity_status_check CHECK(activity_status IN ('ACTIVE','SUSPENDED','COMPLETED'));
 END IF;
 IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='construction_subobjects'::regclass AND conname='subobject_activity_status_check') THEN
  ALTER TABLE construction_subobjects ADD CONSTRAINT subobject_activity_status_check CHECK(activity_status IN ('ACTIVE','SUSPENDED','COMPLETED'));
 END IF;
END $$;
