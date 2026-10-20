-- Personnel transfers: additive migration. Apply only via the checked installer.
-- No accounts, roles, password resets or direct DK privileges are created.
CREATE TABLE personnel_settings (
 id integer PRIMARY KEY CHECK(id=1), enabled boolean NOT NULL DEFAULT false,
 legacy_history_policy text NOT NULL DEFAULT 'UNRESOLVED' CHECK(legacy_history_policy IN ('UNRESOLVED','LEGACY_WITH_WARNING','REQUIRE_HISTORY')),
 creator_user_id bigint REFERENCES auth_users(id) ON DELETE RESTRICT, dk_context_verified boolean NOT NULL DEFAULT false, date_readers_verified boolean NOT NULL DEFAULT false,
 installed_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
INSERT INTO personnel_settings(id) VALUES(1);
CREATE TABLE personnel_position_definitions (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 position_id bigint NOT NULL REFERENCES positions(id) ON DELETE RESTRICT,
 known_from date NOT NULL, recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 definition jsonb NOT NULL CHECK(jsonb_typeof(definition)='object'), start_unknown boolean NOT NULL DEFAULT true
);
CREATE INDEX personnel_position_definitions_lookup ON personnel_position_definitions(position_id,known_from,id);
CREATE TABLE personnel_position_baselines (
 employee_id bigint PRIMARY KEY REFERENCES employees(id) ON DELETE RESTRICT,
 position_id bigint REFERENCES positions(id) ON DELETE RESTRICT,
 known_on date NOT NULL, observed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 effective_start_unknown boolean NOT NULL DEFAULT true CHECK(effective_start_unknown)
);
CREATE TABLE personnel_position_state (
 employee_id bigint PRIMARY KEY REFERENCES employees(id) ON DELETE RESTRICT,
 version integer NOT NULL DEFAULT 0 CHECK(version>=0)
);
CREATE TABLE personnel_position_events (
 employee_id bigint NOT NULL REFERENCES employees(id) ON DELETE RESTRICT,
 version integer NOT NULL CHECK(version>0),root_id uuid NOT NULL,
 kind text NOT NULL CHECK(kind IN ('TRANSFER','CORRECT','CANCEL')),
 position_id bigint REFERENCES positions(id) ON DELETE RESTRICT,effective_on date,
 reason text CHECK(length(reason)<=2000),actor_user_id bigint NOT NULL REFERENCES auth_users(id) ON DELETE RESTRICT,
 recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),source_position_id bigint REFERENCES positions(id) ON DELETE RESTRICT,source_on date,source_explicit boolean NOT NULL DEFAULT false,retained_report_requirement boolean CHECK(retained_report_requirement IS NULL OR retained_report_requirement),retained_calendar_configuration jsonb,PRIMARY KEY(employee_id,version),
 CHECK((kind='CANCEL' AND position_id IS NULL AND effective_on IS NULL) OR (kind<>'CANCEL' AND position_id IS NOT NULL AND effective_on IS NOT NULL)),
 CHECK(kind='TRANSFER' OR nullif(btrim(reason),'') IS NOT NULL)
);
CREATE TABLE personnel_position_requests (
 actor_user_id bigint NOT NULL REFERENCES auth_users(id) ON DELETE RESTRICT,request_id uuid NOT NULL,
 payload jsonb NOT NULL,result jsonb NOT NULL,created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(actor_user_id,request_id)
);
INSERT INTO personnel_position_definitions(position_id,known_from,definition)
 SELECT id,(clock_timestamp() AT TIME ZONE 'Asia/Yekaterinburg')::date,
 jsonb_build_object('name',name,'action_description',action_description,'specialty',specialty,'work_location',work_location,'work_schedule',work_schedule,'report_description',report_description,'aos_description',aos_description,'requires_daily_report',requires_daily_report,'planned_count',planned_count,'equipment_description',equipment_description) FROM positions;
INSERT INTO personnel_position_baselines(employee_id,position_id,known_on)
 SELECT id,position_id,(clock_timestamp() AT TIME ZONE 'Asia/Yekaterinburg')::date FROM employees;
INSERT INTO personnel_position_state(employee_id) SELECT id FROM employees;
CREATE VIEW personnel_position_current_orders AS
 SELECT * FROM (SELECT DISTINCT ON(employee_id,root_id) * FROM personnel_position_events ORDER BY employee_id,root_id,version DESC) r WHERE kind<>'CANCEL';
CREATE VIEW personnel_position_periods AS
 SELECT employee_id,position_id,known_from,lead(known_from) OVER(PARTITION BY employee_id ORDER BY known_from) known_to,effective_start_unknown,root_id,retained_report_requirement,retained_calendar_configuration
 FROM (SELECT employee_id,position_id,known_on known_from,true effective_start_unknown,NULL::uuid root_id,NULL::boolean retained_report_requirement,NULL::jsonb retained_calendar_configuration FROM personnel_position_baselines b WHERE NOT EXISTS(SELECT 1 FROM personnel_position_current_orders o WHERE o.employee_id=b.employee_id AND o.effective_on<=b.known_on)
 UNION ALL SELECT employee_id,position_id,effective_on,false,root_id,retained_report_requirement,retained_calendar_configuration FROM personnel_position_current_orders
 UNION ALL SELECT employee_id,source_position_id,source_on,false,root_id,NULL::boolean,NULL::jsonb FROM personnel_position_current_orders o WHERE source_explicit AND NOT EXISTS(SELECT 1 FROM personnel_position_current_orders x WHERE x.employee_id=o.employee_id AND x.effective_on=o.source_on)) r;

CREATE FUNCTION personnel_position_at(eid bigint,day date) RETURNS jsonb
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,__SCHEMA__,pg_temp AS $$
 SELECT coalesce((SELECT jsonb_build_object('status',CASE WHEN p.position_id IS NULL THEN 'UNKNOWN_POSITION' ELSE 'KNOWN' END,
 'position_id',p.position_id,'known_from',p.known_from,'known_to',p.known_to,'effective_start_unknown',p.effective_start_unknown,
 'definition_version_id',v.id,'definition',CASE WHEN p.retained_report_requirement THEN v.definition||jsonb_build_object('requires_daily_report',true)||coalesce(p.retained_calendar_configuration,'{}'::jsonb) ELSE v.definition||coalesce(p.retained_calendar_configuration,'{}'::jsonb) END,'definition_status',CASE WHEN v.id IS NULL THEN 'UNKNOWN_HISTORY' WHEN v.known_from>day THEN 'LEGACY_UNVERIFIED' ELSE 'KNOWN' END)
 FROM personnel_position_periods p LEFT JOIN LATERAL
 (SELECT d.id,d.definition,d.known_from FROM personnel_position_definitions d WHERE d.position_id=p.position_id AND (d.known_from<=day OR EXISTS(SELECT 1 FROM personnel_settings WHERE id=1 AND legacy_history_policy='LEGACY_WITH_WARNING')) ORDER BY (d.known_from<=day) DESC,CASE WHEN d.known_from<=day THEN d.known_from END DESC,d.known_from,d.id DESC LIMIT 1) v ON true
 WHERE p.employee_id=eid AND p.known_from<=day AND (p.known_to IS NULL OR day<p.known_to)),jsonb_build_object('status','UNKNOWN_HISTORY','position_id',NULL,'definition_status','UNKNOWN_HISTORY'));
 $$;
CREATE FUNCTION personnel_capture_position_definition() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,__SCHEMA__,pg_temp AS $$
 DECLARE value jsonb;prev jsonb;
 BEGIN
 value:=jsonb_build_object('name',NEW.name,'action_description',NEW.action_description,'specialty',NEW.specialty,'work_location',NEW.work_location,'work_schedule',NEW.work_schedule,'report_description',NEW.report_description,'aos_description',NEW.aos_description,'requires_daily_report',NEW.requires_daily_report,'planned_count',NEW.planned_count,'equipment_description',NEW.equipment_description);
 SELECT definition INTO prev FROM personnel_position_definitions WHERE position_id=NEW.id ORDER BY known_from DESC,id DESC LIMIT 1;
 IF prev IS DISTINCT FROM value THEN
 INSERT INTO personnel_position_definitions(position_id,known_from,definition,start_unknown) VALUES(NEW.id,(clock_timestamp() AT TIME ZONE 'Asia/Yekaterinburg')::date,value,false);
 END IF;RETURN NEW;
 END;$$;
CREATE TRIGGER personnel_capture_position_definition AFTER INSERT OR UPDATE ON positions FOR EACH ROW EXECUTE FUNCTION personnel_capture_position_definition();
CREATE FUNCTION personnel_new_employee() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,__SCHEMA__,pg_temp AS $$
 BEGIN
 INSERT INTO personnel_position_baselines(employee_id,position_id,known_on) VALUES(NEW.id,NEW.position_id,(clock_timestamp() AT TIME ZONE 'Asia/Yekaterinburg')::date);
 INSERT INTO personnel_position_state(employee_id) VALUES(NEW.id);RETURN NEW;
 END;$$;
CREATE TRIGGER personnel_new_employee AFTER INSERT ON employees FOR EACH ROW EXECUTE FUNCTION personnel_new_employee();
CREATE FUNCTION personnel_guard_direct_position() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,__SCHEMA__,pg_temp AS $$
 BEGIN
 IF NEW.position_id IS DISTINCT FROM OLD.position_id THEN RAISE EXCEPTION 'Оформите перевод отдельной кадровой операцией' USING ERRCODE='23514';END IF;
 RETURN NEW;END;$$;
CREATE TRIGGER personnel_guard_direct_position BEFORE UPDATE OF position_id ON employees FOR EACH ROW EXECUTE FUNCTION personnel_guard_direct_position();

CREATE FUNCTION personnel_position_command(actor bigint,sid bigint,eid bigint,pid bigint,on_day date,note text,rid uuid,expected integer,operation text,target uuid,source_pid bigint DEFAULT NULL) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,__SCHEMA__,pg_temp AS $$
 DECLARE cfg personnel_settings%ROWTYPE;u auth_users%ROWTYPE;emp employees%ROWTYPE;previous personnel_position_current_orders%ROWTYPE;old_request personnel_position_requests%ROWTYPE;
 v integer;baseline date;payload jsonb;result jsonb;root uuid;prior_position jsonb;new_definition jsonb;creator boolean;allowed boolean;source_explicit boolean:=false;source_day date;next_order personnel_position_current_orders%ROWTYPE;
 BEGIN
 SELECT * INTO cfg FROM personnel_settings WHERE id=1;
 SELECT * INTO u FROM auth_users WHERE id=actor AND NOT is_blocked;
 creator:=coalesce(cfg.creator_user_id=actor,false);
 allowed:=u.id IS NOT NULL AND EXISTS(SELECT 1 FROM auth_sessions s WHERE s.id=sid AND s.user_id=actor AND s.revoked_at IS NULL AND s.expires_at>clock_timestamp() AND s.credential_version=u.credential_version) AND (creator OR EXISTS(SELECT 1 FROM auth_user_roles ur JOIN auth_roles r ON r.id=ur.role_id JOIN auth_role_permissions rp ON rp.role_id=r.id JOIN auth_permissions p ON p.id=rp.permission_id WHERE ur.user_id=actor AND r.code='SYSTEM_TECHNICIAN' AND p.code='data.update'));
 IF NOT allowed OR (operation<>'TRANSFER' AND NOT creator) THEN RAISE EXCEPTION 'Операция недоступна для учётной записи' USING ERRCODE='42501';END IF;
 IF NOT cfg.enabled OR NOT cfg.dk_context_verified OR NOT cfg.date_readers_verified OR cfg.legacy_history_policy='UNRESOLVED' THEN RAISE EXCEPTION 'Кадровая запись не включена: требуется проверенный контекст ДК и настройка истории' USING ERRCODE='55000';END IF;
 IF rid IS NULL OR expected IS NULL OR expected<0 OR eid IS NULL OR operation IS NULL OR operation NOT IN ('TRANSFER','CORRECT','CANCEL') OR length(note)>2000 THEN RAISE EXCEPTION 'Некорректная кадровая команда' USING ERRCODE='22023';END IF;
 IF (operation='TRANSFER' AND target IS NOT NULL) OR (operation<>'TRANSFER' AND (target IS NULL OR nullif(btrim(note),'') IS NULL)) THEN RAISE EXCEPTION 'Укажите исправляемую запись и основание' USING ERRCODE='22023';END IF;
 IF operation='CANCEL' AND (pid IS NOT NULL OR on_day IS NOT NULL) THEN RAISE EXCEPTION 'Отмена не задаёт новую должность или дату' USING ERRCODE='22023';END IF;
 payload:=jsonb_build_object('employee_id',eid,'position_id',pid,'effective_on',on_day,'reason',nullif(btrim(note),''),'operation',operation,'target',target,'source_position_id',source_pid);
 PERFORM pg_advisory_xact_lock(20261017,29);PERFORM pg_advisory_xact_lock(20261007,1601);PERFORM pg_advisory_xact_lock(20261013,24);
 IF NOT EXISTS(SELECT 1 FROM auth_users x JOIN auth_sessions s ON s.user_id=x.id WHERE x.id=actor AND NOT x.is_blocked AND x.credential_version=u.credential_version AND s.id=sid AND s.revoked_at IS NULL AND s.expires_at>clock_timestamp() AND s.credential_version=x.credential_version) OR NOT (EXISTS(SELECT 1 FROM personnel_settings WHERE id=1 AND creator_user_id=actor) OR (operation='TRANSFER' AND EXISTS(SELECT 1 FROM auth_user_roles ur JOIN auth_roles r ON r.id=ur.role_id JOIN auth_role_permissions rp ON rp.role_id=r.id JOIN auth_permissions p ON p.id=rp.permission_id WHERE ur.user_id=actor AND r.code='SYSTEM_TECHNICIAN' AND p.code='data.update'))) THEN RAISE EXCEPTION 'Полномочия изменены' USING ERRCODE='42501';END IF;
 SELECT * INTO old_request FROM personnel_position_requests WHERE actor_user_id=actor AND request_id=rid;
 IF FOUND THEN IF old_request.payload<>payload THEN RAISE EXCEPTION 'request_id уже использован с другими данными' USING ERRCODE='22023';END IF;RETURN old_request.result;END IF;
 SELECT version INTO v FROM personnel_position_state WHERE employee_id=eid FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Сотрудник не найден' USING ERRCODE='P0002';END IF;
 IF v<>expected THEN RAISE EXCEPTION 'История уже изменена. Обновите карточку' USING ERRCODE='40001';END IF;
 SELECT * INTO emp FROM employees WHERE id=eid;
 IF emp.is_archived THEN RAISE EXCEPTION 'Сотрудник находится в архиве' USING ERRCODE='23514';END IF;
 SELECT known_on INTO baseline FROM personnel_position_baselines WHERE employee_id=eid;
 IF operation<>'TRANSFER' THEN
 SELECT * INTO previous FROM personnel_position_current_orders WHERE employee_id=eid AND root_id=target;
 IF NOT FOUND THEN RAISE EXCEPTION 'Действующая запись перевода не найдена' USING ERRCODE='22023';END IF;
 SELECT * INTO next_order FROM personnel_position_current_orders WHERE employee_id=eid AND root_id<>target AND effective_on>previous.effective_on ORDER BY effective_on LIMIT 1;
 IF FOUND AND ((operation='CANCEL' OR on_day>=next_order.effective_on) AND next_order.source_position_id IS DISTINCT FROM previous.source_position_id) THEN RAISE EXCEPTION 'Исправление нарушает исходную должность последующего перевода' USING ERRCODE='23514';END IF;
 END IF;
 IF operation<>'CANCEL' THEN
 IF on_day IS NULL OR NOT isfinite(on_day) OR pid IS NULL THEN RAISE EXCEPTION 'Укажите допустимую дату и должность; исходная история неизвестна' USING ERRCODE='22023';END IF;
 IF emp.dismissal_date IS NOT NULL AND on_day>=emp.dismissal_date THEN RAISE EXCEPTION 'Дата перевода не может быть на дату увольнения или позже' USING ERRCODE='23514';END IF;
 IF EXISTS(SELECT 1 FROM personnel_position_current_orders WHERE employee_id=eid AND effective_on=on_day AND (target IS NULL OR root_id<>target)) THEN RAISE EXCEPTION 'На выбранную дату уже есть перевод' USING ERRCODE='23505';END IF;
 SELECT definition INTO new_definition FROM personnel_position_definitions WHERE position_id=pid AND (known_from<=on_day OR cfg.legacy_history_policy='LEGACY_WITH_WARNING') ORDER BY (known_from<=on_day) DESC,CASE WHEN known_from<=on_day THEN known_from END DESC,known_from,id DESC LIMIT 1;
 IF NOT FOUND THEN RAISE EXCEPTION 'Должность или её параметры на выбранную дату неизвестны' USING ERRCODE='23514';END IF;
 source_day:=on_day-1;
 prior_position:=personnel_position_at(eid,source_day);
 -- Observation date is a cutover, never an invented first appointment date.
 IF prior_position->>'status'='UNKNOWN_HISTORY' THEN
 IF source_pid IS NULL OR NOT EXISTS(SELECT 1 FROM positions WHERE id=source_pid) THEN RAISE EXCEPTION 'Должность накануне перевода неизвестна: выберите её из справочника' USING ERRCODE='22023';END IF;
 SELECT jsonb_build_object('position_id',source_pid,'definition',definition) INTO prior_position FROM personnel_position_definitions WHERE position_id=source_pid ORDER BY known_from,id LIMIT 1;
 source_explicit:=true;
 ELSIF source_pid IS NOT NULL AND source_pid IS DISTINCT FROM (prior_position->>'position_id')::bigint THEN RAISE EXCEPTION 'Исходная должность противоречит кадровой истории накануне перевода' USING ERRCODE='23514';END IF;
 SELECT * INTO next_order FROM personnel_position_current_orders WHERE employee_id=eid AND effective_on>on_day AND (target IS NULL OR root_id<>target) ORDER BY effective_on LIMIT 1;
 IF FOUND AND next_order.source_position_id IS NOT NULL AND next_order.source_position_id<>pid THEN RAISE EXCEPTION 'Последующий перевод ожидает другую исходную должность. Проверьте последовательность истории' USING ERRCODE='23514';END IF;
 IF prior_position->'definition'->>'work_schedule' IS NULL OR prior_position->'definition'->>'work_location' IS NULL THEN RAISE EXCEPTION 'Исходный график неизвестен: требуется проверка кадровой истории' USING ERRCODE='23514';END IF;
 IF operation='TRANSFER' AND (prior_position->>'position_id')::bigint=pid THEN RAISE EXCEPTION 'На выбранную дату уже действует эта должность' USING ERRCODE='22023';END IF;
 END IF;
 root:=CASE WHEN operation='TRANSFER' THEN rid ELSE target END;
 INSERT INTO personnel_position_events(employee_id,version,root_id,kind,position_id,effective_on,reason,actor_user_id,source_position_id,source_on,source_explicit,retained_report_requirement,retained_calendar_configuration) VALUES(eid,v+1,root,operation,pid,on_day,nullif(btrim(note),''),actor,(prior_position->>'position_id')::bigint,source_day,source_explicit,CASE WHEN pid=16 AND coalesce((prior_position->'definition'->>'requires_daily_report')::boolean,false) THEN true ELSE NULL END,(prior_position->'definition') - ARRAY['name','action_description','specialty','report_description','aos_description','requires_daily_report','planned_count','equipment_description']);
 UPDATE personnel_position_state SET version=v+1 WHERE employee_id=eid;
 result:=jsonb_build_object('employee_id',eid,'root_id',root,'version',v+1,'operation',operation);
 INSERT INTO personnel_position_requests(actor_user_id,request_id,payload,result) VALUES(actor,rid,payload,result);
 RETURN result;
 END;$$;
CREATE FUNCTION personnel_transfer(actor bigint,sid bigint,eid bigint,pid bigint,on_day date,note text,rid uuid,expected integer) RETURNS jsonb
 LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,__SCHEMA__,pg_temp AS $$SELECT personnel_position_command(actor,sid,eid,pid,on_day,note,rid,expected,'TRANSFER',NULL)$$;
CREATE FUNCTION personnel_review_transfer(actor bigint,sid bigint,eid bigint,pid bigint,on_day date,note text,rid uuid,expected integer,operation text,target uuid) RETURNS jsonb
 LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,__SCHEMA__,pg_temp AS $$SELECT personnel_position_command(actor,sid,eid,pid,on_day,note,rid,expected,operation,target)$$;
REVOKE ALL ON personnel_settings,personnel_position_definitions,personnel_position_baselines,personnel_position_state,personnel_position_events,personnel_position_requests,personnel_position_current_orders,personnel_position_periods FROM PUBLIC;
REVOKE ALL ON FUNCTION personnel_position_command(bigint,bigint,bigint,bigint,date,text,uuid,integer,text,uuid,bigint),personnel_transfer(bigint,bigint,bigint,bigint,date,text,uuid,integer),personnel_review_transfer(bigint,bigint,bigint,bigint,date,text,uuid,integer,text,uuid),personnel_position_at(bigint,date),personnel_capture_position_definition(),personnel_new_employee(),personnel_guard_direct_position() FROM PUBLIC;

REVOKE ALL ON SEQUENCE personnel_position_definitions_id_seq FROM PUBLIC;

CREATE FUNCTION personnel_transfer_with_source(actor bigint,sid bigint,eid bigint,pid bigint,on_day date,note text,rid uuid,expected integer,source_pid bigint) RETURNS jsonb
 LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,__SCHEMA__,pg_temp AS $$SELECT personnel_position_command(actor,sid,eid,pid,on_day,note,rid,expected,'TRANSFER',NULL,source_pid)$$;
REVOKE ALL ON FUNCTION personnel_transfer_with_source(bigint,bigint,bigint,bigint,date,text,uuid,integer,bigint) FROM PUBLIC;
