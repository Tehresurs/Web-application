DO $$ BEGIN
 IF current_database()<>'ai_excel_agent_test' OR current_schema()<>'test_construction_identity_stage46' THEN
  RAISE EXCEPTION '027 requires the isolated 8001 schema';
 END IF;
END $$;
CREATE TABLE IF NOT EXISTS daily_control_fact_replacements (
 id BIGSERIAL PRIMARY KEY, employee_id BIGINT NOT NULL, report_date DATE NOT NULL,
 old_source_sha256 TEXT NOT NULL, new_source_sha256 TEXT NOT NULL,
 old_facts JSONB NOT NULL, old_overrides JSONB NOT NULL, new_facts JSONB NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_fact_replacements_old_source ON daily_control_fact_replacements(old_source_sha256);
