-- Additive migration. Existing assignment and journal uniqueness stay unchanged.
-- Normalization follows the existing employee/object/PO matchers.
CREATE OR REPLACE FUNCTION normalize_known_value(entity_type TEXT, source_value TEXT)
RETURNS TEXT LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$
    SELECT btrim(regexp_replace(
        CASE
            WHEN entity_type IN ('object', 'subobject')
                THEN replace(replace(lower(source_value), 'ё', 'е'), '№ ', '№')
            WHEN entity_type = 'po'
                THEN replace(replace(replace(lower(source_value), 'ё', 'е'), '«', '"'), '»', '"')
            ELSE replace(lower(source_value), 'ё', 'е')
        END,
        '[[:space:]' || chr(160) || ']+', ' ', 'g'
    ));
$$;

CREATE TABLE IF NOT EXISTS construction_subobjects (
    id BIGSERIAL PRIMARY KEY,
    object_id BIGINT NOT NULL REFERENCES construction_objects(id) ON DELETE RESTRICT,
    name TEXT NOT NULL CHECK (normalize_known_value('subobject', name) <> ''),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Includes inactive entries: reactivate rather than create a second identity.
CREATE UNIQUE INDEX IF NOT EXISTS uq_construction_subobjects_object_name
    ON construction_subobjects (object_id, normalize_known_value('subobject', name));

CREATE TABLE IF NOT EXISTS value_aliases (
    id BIGSERIAL PRIMARY KEY,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('employee', 'object', 'subobject', 'po')),
    source_value TEXT NOT NULL,
    normalized_source_value TEXT GENERATED ALWAYS AS
        (normalize_known_value(entity_type, source_value)) STORED,
    target_id BIGINT NOT NULL CHECK (target_id > 0),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_value_aliases_source_nonempty CHECK (normalized_source_value <> '')
);

-- target_id is polymorphic: target existence must be checked by future services.
CREATE UNIQUE INDEX IF NOT EXISTS uq_value_aliases_type_source
    ON value_aliases (entity_type, normalized_source_value);
CREATE INDEX IF NOT EXISTS ix_value_aliases_type_target ON value_aliases (entity_type, target_id);

ALTER TABLE daily_control_results ADD COLUMN IF NOT EXISTS subobject_id BIGINT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'daily_control_results'::regclass
          AND conname = 'fk_daily_control_subobject'
    ) THEN
        ALTER TABLE daily_control_results ADD CONSTRAINT fk_daily_control_subobject
            FOREIGN KEY (subobject_id) REFERENCES construction_subobjects(id) ON DELETE RESTRICT;
    END IF;
END;
$$;

CREATE INDEX IF NOT EXISTS ix_daily_control_subobject ON daily_control_results (subobject_id);
