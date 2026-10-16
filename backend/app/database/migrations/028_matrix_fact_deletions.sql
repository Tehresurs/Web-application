DO $$ BEGIN
 IF current_database()<>'ai_excel_agent_test' OR current_schema()<>'test_construction_identity_stage46' THEN
  RAISE EXCEPTION '028 requires the isolated 8001 schema';
 END IF;
END $$;
CREATE TABLE IF NOT EXISTS daily_control_fact_deletions (
 id BIGSERIAL PRIMARY KEY, fact_id BIGINT NOT NULL, employee_id BIGINT NOT NULL,
 report_date DATE NOT NULL, fact JSONB NOT NULL, overrides JSONB NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
