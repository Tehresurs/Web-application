DO $$ BEGIN
 IF current_database()<>'ai_excel_agent_test' OR current_schema()<>'test_construction_identity_stage46' THEN
  RAISE EXCEPTION '029 requires the isolated 8001 schema';
 END IF;
END $$;
CREATE TABLE IF NOT EXISTS production_matrix_dk (
 employee_id BIGINT NOT NULL REFERENCES employees(id) ON DELETE RESTRICT,
 work_date DATE NOT NULL,
 PRIMARY KEY(employee_id,work_date)
);
-- Mark calendar-source transactions for application reconciliation before COMMIT.
-- No source record is changed by these triggers.
CREATE OR REPLACE FUNCTION mark_matrix_dk_calendar_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 PERFORM pg_advisory_xact_lock(20261017,29);
 PERFORM set_config('tehresurs.dk_calendar_dirty','1',true);
 RETURN NULL;
END $$;
DO $$ DECLARE tab TEXT; BEGIN
 FOREACH tab IN ARRAY ARRAY['employees','positions','employee_movements','rail_tickets',
    'employee_sick_periods','employee_luvr_day_overrides','employee_duration_exceptions','employee_absences'] LOOP
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgrelid=to_regclass(tab) AND tgname='matrix_dk_calendar_change') THEN
   EXECUTE format('CREATE TRIGGER matrix_dk_calendar_change BEFORE INSERT OR UPDATE OR DELETE ON %I FOR EACH STATEMENT EXECUTE FUNCTION mark_matrix_dk_calendar_change()',tab);
  END IF;
 END LOOP;
END $$;
