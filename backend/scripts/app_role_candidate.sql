-- PREPARATION ONLY. Not a migration; never applied to the working cluster.
-- Replace :"app_role" only via a trusted identifier parameter, not string interpolation.
-- Preconditions: exact target, reviewed PUBLIC database/schema/function ACL, independent backup.
-- No password is embedded. Provision LOGIN/SCRAM interactively using separately approved tooling.
BEGIN;
DO $$ BEGIN
 IF current_database()<>'ai_excel_agent_test' OR to_regnamespace('test_construction_identity_stage46') IS NULL THEN RAISE EXCEPTION 'Wrong target'; END IF;
 IF EXISTS(SELECT 1 FROM pg_database d CROSS JOIN LATERAL aclexplode(coalesce(d.datacl,acldefault('d',d.datdba))) a WHERE a.grantee=0 AND a.privilege_type='CONNECT' AND d.datallowconn AND d.datname<>'ai_excel_agent_test') THEN RAISE EXCEPTION 'Unresolved PUBLIC CONNECT on foreign databases; no role created'; END IF;
END $$;
CREATE ROLE :"app_role" NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT;
GRANT CONNECT ON DATABASE ai_excel_agent_test TO :"app_role";
GRANT USAGE ON SCHEMA test_construction_identity_stage46 TO :"app_role";
GRANT SELECT ON test_construction_identity_stage46.auth_permissions TO :"app_role";
GRANT SELECT ON test_construction_identity_stage46.auth_role_permissions TO :"app_role";
GRANT SELECT ON test_construction_identity_stage46.auth_roles TO :"app_role";
GRANT SELECT ON test_construction_identity_stage46.auth_security_events TO :"app_role";
GRANT SELECT ON test_construction_identity_stage46.auth_sessions TO :"app_role";
GRANT SELECT ON test_construction_identity_stage46.auth_user_roles TO :"app_role";
GRANT SELECT ON test_construction_identity_stage46.auth_users TO :"app_role";
GRANT SELECT ON test_construction_identity_stage46.construction_entities TO :"app_role";
GRANT SELECT ON test_construction_identity_stage46.construction_entity_hierarchy TO :"app_role";
GRANT SELECT ON test_construction_identity_stage46.construction_objects TO :"app_role";
GRANT SELECT ON test_construction_identity_stage46.construction_subobjects TO :"app_role";
GRANT SELECT ON test_construction_identity_stage46.crews TO :"app_role";
GRANT SELECT ON test_construction_identity_stage46.daily_control_fact_deletions TO :"app_role";
GRANT SELECT ON test_construction_identity_stage46.daily_control_fact_replacements TO :"app_role";
GRANT SELECT ON test_construction_identity_stage46.daily_control_results TO :"app_role";
GRANT SELECT ON test_construction_identity_stage46.employee_absences TO :"app_role";
GRANT SELECT ON test_construction_identity_stage46.employee_assignments TO :"app_role";
GRANT SELECT ON test_construction_identity_stage46.employee_duration_exceptions TO :"app_role";
GRANT SELECT ON test_construction_identity_stage46.employee_luvr_day_overrides TO :"app_role";
GRANT SELECT ON test_construction_identity_stage46.employee_movements TO :"app_role";
GRANT SELECT ON test_construction_identity_stage46.employee_sick_absence_labels TO :"app_role";
GRANT SELECT ON test_construction_identity_stage46.employee_sick_periods TO :"app_role";
GRANT SELECT ON test_construction_identity_stage46.employees TO :"app_role";
GRANT SELECT ON test_construction_identity_stage46.luvr_month_employees TO :"app_role";
GRANT SELECT ON test_construction_identity_stage46.luvr_months TO :"app_role";
GRANT SELECT ON test_construction_identity_stage46.luvr_settings TO :"app_role";
GRANT SELECT ON test_construction_identity_stage46.object_categories TO :"app_role";
GRANT SELECT ON test_construction_identity_stage46.object_po TO :"app_role";
GRANT SELECT ON test_construction_identity_stage46.po_types TO :"app_role";
GRANT SELECT ON test_construction_identity_stage46.positions TO :"app_role";
GRANT SELECT ON test_construction_identity_stage46.production_assignment_changes TO :"app_role";
GRANT SELECT ON test_construction_identity_stage46.production_assignment_items TO :"app_role";
GRANT SELECT ON test_construction_identity_stage46.production_control_mode_positions TO :"app_role";
GRANT SELECT ON test_construction_identity_stage46.production_matrix_dk TO :"app_role";
GRANT SELECT ON test_construction_identity_stage46.production_matrix_overrides TO :"app_role";
GRANT SELECT ON test_construction_identity_stage46.rail_tickets TO :"app_role";
GRANT SELECT ON test_construction_identity_stage46.report_absence_approvals TO :"app_role";
GRANT SELECT ON test_construction_identity_stage46.report_absence_rules TO :"app_role";
GRANT SELECT ON test_construction_identity_stage46.report_review_events TO :"app_role";
GRANT SELECT ON test_construction_identity_stage46.value_aliases TO :"app_role";
GRANT SELECT ON test_construction_identity_stage46.vou_settings TO :"app_role";
GRANT SELECT ON test_construction_identity_stage46.construction_entity_current TO :"app_role";
GRANT INSERT,UPDATE ON test_construction_identity_stage46.construction_objects TO :"app_role";
GRANT INSERT,UPDATE ON test_construction_identity_stage46.construction_subobjects TO :"app_role";
GRANT INSERT,UPDATE ON test_construction_identity_stage46.crews TO :"app_role";
GRANT INSERT,UPDATE ON test_construction_identity_stage46.employees TO :"app_role";
GRANT INSERT,UPDATE ON test_construction_identity_stage46.positions TO :"app_role";
GRANT INSERT,UPDATE ON test_construction_identity_stage46.object_categories TO :"app_role";
GRANT INSERT,UPDATE ON test_construction_identity_stage46.po_types TO :"app_role";
GRANT INSERT,UPDATE ON test_construction_identity_stage46.employee_assignments TO :"app_role";
GRANT INSERT,UPDATE ON test_construction_identity_stage46.employee_movements TO :"app_role";
GRANT INSERT,UPDATE ON test_construction_identity_stage46.employee_sick_periods TO :"app_role";
GRANT INSERT,UPDATE ON test_construction_identity_stage46.employee_sick_absence_labels TO :"app_role";
GRANT INSERT,UPDATE ON test_construction_identity_stage46.employee_duration_exceptions TO :"app_role";
GRANT INSERT,UPDATE ON test_construction_identity_stage46.employee_luvr_day_overrides TO :"app_role";
GRANT INSERT,UPDATE ON test_construction_identity_stage46.employee_absences TO :"app_role";
GRANT INSERT,UPDATE ON test_construction_identity_stage46.production_assignment_items TO :"app_role";
GRANT INSERT,UPDATE ON test_construction_identity_stage46.production_matrix_overrides TO :"app_role";
GRANT INSERT,UPDATE ON test_construction_identity_stage46.rail_tickets TO :"app_role";
GRANT INSERT,UPDATE ON test_construction_identity_stage46.value_aliases TO :"app_role";
GRANT INSERT ON test_construction_identity_stage46.construction_entities TO :"app_role";
GRANT INSERT ON test_construction_identity_stage46.construction_entity_hierarchy TO :"app_role";
GRANT INSERT ON test_construction_identity_stage46.daily_control_results TO :"app_role";
GRANT INSERT ON test_construction_identity_stage46.production_assignment_changes TO :"app_role";
GRANT INSERT ON test_construction_identity_stage46.report_review_events TO :"app_role";
GRANT INSERT ON test_construction_identity_stage46.luvr_months TO :"app_role";
GRANT INSERT ON test_construction_identity_stage46.luvr_month_employees TO :"app_role";
GRANT INSERT,UPDATE ON test_construction_identity_stage46.auth_sessions TO :"app_role";
GRANT INSERT ON test_construction_identity_stage46.auth_security_events TO :"app_role";
GRANT EXECUTE ON FUNCTION test_construction_identity_stage46.normalize_known_value(text,text) TO :"app_role";
GRANT EXECUTE ON FUNCTION test_construction_identity_stage46.construction_reference(bigint,bigint,bigint) TO :"app_role";
-- Grant USAGE only on sequences owned by the above INSERT tables, after catalog verification.
-- Do NOT GRANT ALL, DELETE, TRUNCATE, sequence UPDATE, schema CREATE or default blanket privileges.
-- REVOKE FROM this role cannot negate CONNECT/TEMP/EXECUTE inherited from PUBLIC.
-- Never run this template unchanged: PUBLIC restrictions require a separately approved plan.

-- SELECT FOR UPDATE in login requires UPDATE privilege on at least one column.
GRANT UPDATE(password_changed_at) ON test_construction_identity_stage46.auth_users TO :"app_role";
GRANT USAGE ON SEQUENCE test_construction_identity_stage46.construction_entities_id_seq TO :"app_role";
GRANT USAGE ON SEQUENCE test_construction_identity_stage46.construction_objects_id_seq TO :"app_role";
GRANT USAGE ON SEQUENCE test_construction_identity_stage46.construction_subobjects_id_seq TO :"app_role";
GRANT USAGE ON SEQUENCE test_construction_identity_stage46.crews_id_seq TO :"app_role";
GRANT USAGE ON SEQUENCE test_construction_identity_stage46.daily_control_results_id_seq TO :"app_role";
GRANT USAGE ON SEQUENCE test_construction_identity_stage46.employee_absences_id_seq TO :"app_role";
GRANT USAGE ON SEQUENCE test_construction_identity_stage46.employee_duration_exceptions_id_seq TO :"app_role";
GRANT USAGE ON SEQUENCE test_construction_identity_stage46.employee_luvr_day_overrides_id_seq TO :"app_role";
GRANT USAGE ON SEQUENCE test_construction_identity_stage46.employee_movements_id_seq TO :"app_role";
GRANT USAGE ON SEQUENCE test_construction_identity_stage46.employee_sick_periods_id_seq TO :"app_role";
GRANT USAGE ON SEQUENCE test_construction_identity_stage46.employees_id_seq TO :"app_role";
GRANT USAGE ON SEQUENCE test_construction_identity_stage46.luvr_month_employees_id_seq TO :"app_role";
GRANT USAGE ON SEQUENCE test_construction_identity_stage46.object_categories_id_seq TO :"app_role";
GRANT USAGE ON SEQUENCE test_construction_identity_stage46.po_types_id_seq TO :"app_role";
GRANT USAGE ON SEQUENCE test_construction_identity_stage46.positions_id_seq TO :"app_role";
GRANT USAGE ON SEQUENCE test_construction_identity_stage46.production_assignment_changes_id_seq TO :"app_role";
GRANT USAGE ON SEQUENCE test_construction_identity_stage46.production_assignment_items_id_seq TO :"app_role";
GRANT USAGE ON SEQUENCE test_construction_identity_stage46.production_matrix_overrides_id_seq TO :"app_role";
GRANT USAGE ON SEQUENCE test_construction_identity_stage46.rail_tickets_id_seq TO :"app_role";
GRANT USAGE ON SEQUENCE test_construction_identity_stage46.report_review_events_id_seq TO :"app_role";
GRANT USAGE ON SEQUENCE test_construction_identity_stage46.value_aliases_id_seq TO :"app_role";
COMMIT;
