-- Apply only to the isolated 8001 instance.
DO $$ BEGIN
 IF current_database()<>'ai_excel_agent_test' OR current_schema()<>'test_construction_identity_stage46' THEN
  RAISE EXCEPTION '026 requires the isolated 8001 schema';
 END IF;
END $$;
ALTER TABLE po_types ADD COLUMN IF NOT EXISTS default_category_id BIGINT
 REFERENCES object_categories(id) ON DELETE SET NULL;
