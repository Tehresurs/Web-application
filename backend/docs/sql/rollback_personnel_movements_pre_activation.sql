-- PRE-ACTIVATION rollback only. Never run on the working DB without approval.
-- Caller must verify database/schema and hold a verified backup.
SET LOCAL lock_timeout='3s';
SELECT pg_advisory_xact_lock(20261017,29);
SELECT pg_advisory_xact_lock(20261007,1601);
SELECT pg_advisory_xact_lock(20261013,24);
DO $$BEGIN
 IF EXISTS(SELECT 1 FROM __SCHEMA__.personnel_settings WHERE enabled)
 OR EXISTS(SELECT 1 FROM __SCHEMA__.personnel_position_events)
 OR EXISTS(SELECT 1 FROM __SCHEMA__.personnel_acting_events)
 OR EXISTS(SELECT 1 FROM __SCHEMA__.personnel_position_requests)
 THEN RAISE EXCEPTION 'Rollback refused: personnel operations must remain preserved';END IF;
END$$;
DROP TRIGGER personnel_capture_position_definition ON __SCHEMA__.positions;
DROP TRIGGER personnel_new_employee ON __SCHEMA__.employees;
DROP TRIGGER personnel_guard_direct_position ON __SCHEMA__.employees;
DROP FUNCTION __SCHEMA__.personnel_transfer(bigint,bigint,bigint,bigint,date,text,uuid,integer);
DROP FUNCTION __SCHEMA__.personnel_transfer_with_source(bigint,bigint,bigint,bigint,date,text,uuid,integer,bigint);
DROP FUNCTION __SCHEMA__.personnel_review_transfer(bigint,bigint,bigint,bigint,date,text,uuid,integer,text,uuid);
DROP FUNCTION __SCHEMA__.personnel_position_command(bigint,bigint,bigint,bigint,date,text,uuid,integer,text,uuid,bigint);
DROP FUNCTION __SCHEMA__.personnel_acting_command(bigint,bigint,bigint,bigint,date,date,text,uuid,integer,text,uuid,bigint,jsonb);
DROP FUNCTION __SCHEMA__.personnel_acting_at(bigint,date);
DROP FUNCTION __SCHEMA__.personnel_position_at(bigint,date);
DROP FUNCTION __SCHEMA__.personnel_capture_position_definition();
DROP FUNCTION __SCHEMA__.personnel_new_employee();
DROP FUNCTION __SCHEMA__.personnel_guard_direct_position();
DROP VIEW __SCHEMA__.personnel_acting_current;
DROP VIEW __SCHEMA__.personnel_position_periods;
DROP VIEW __SCHEMA__.personnel_position_current_orders;
DROP TABLE __SCHEMA__.personnel_acting_events;
DROP TABLE __SCHEMA__.personnel_position_requests;
DROP TABLE __SCHEMA__.personnel_position_events;
DROP TABLE __SCHEMA__.personnel_position_state;
DROP TABLE __SCHEMA__.personnel_position_baselines;
DROP TABLE __SCHEMA__.personnel_position_definitions;
DROP TABLE __SCHEMA__.personnel_settings;
