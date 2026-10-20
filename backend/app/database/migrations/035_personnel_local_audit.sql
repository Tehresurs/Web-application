-- 035: explicit local HR audit, no users/sessions/roles. Existing user commands remain.
ALTER TABLE personnel_settings ADD COLUMN local_enabled boolean NOT NULL DEFAULT false;
ALTER TABLE personnel_settings ADD COLUMN local_key_digest text;
ALTER TABLE personnel_position_events ALTER COLUMN actor_user_id DROP NOT NULL;
ALTER TABLE personnel_position_events ADD COLUMN audit_source text NOT NULL DEFAULT 'USER';
ALTER TABLE personnel_position_events ADD CONSTRAINT personnel_position_events_audit_source_check CHECK ((audit_source='USER' AND actor_user_id IS NOT NULL) OR (audit_source='LOCAL_APP' AND actor_user_id IS NULL));
ALTER TABLE personnel_acting_events ALTER COLUMN actor_user_id DROP NOT NULL;
ALTER TABLE personnel_acting_events ADD COLUMN audit_source text NOT NULL DEFAULT 'USER';
ALTER TABLE personnel_acting_events ADD CONSTRAINT personnel_acting_events_audit_source_check CHECK ((audit_source='USER' AND actor_user_id IS NOT NULL) OR (audit_source='LOCAL_APP' AND actor_user_id IS NULL));
ALTER TABLE personnel_position_requests DROP CONSTRAINT personnel_position_requests_pkey;
ALTER TABLE personnel_position_requests ALTER COLUMN actor_user_id DROP NOT NULL;
ALTER TABLE personnel_position_requests ADD COLUMN audit_source text NOT NULL DEFAULT 'USER';
ALTER TABLE personnel_position_requests ADD CONSTRAINT personnel_position_requests_audit_source_check CHECK ((audit_source='USER' AND actor_user_id IS NOT NULL) OR (audit_source='LOCAL_APP' AND actor_user_id IS NULL));
CREATE UNIQUE INDEX personnel_request_source_unique ON personnel_position_requests(audit_source,actor_user_id,request_id) NULLS NOT DISTINCT;
CREATE FUNCTION personnel_local_admit(secret text) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,__SCHEMA__,pg_temp AS $$
DECLARE cfg personnel_settings%ROWTYPE;
BEGIN
 SELECT * INTO cfg FROM personnel_settings WHERE id=1;
 IF secret IS NULL OR length(secret)<40 OR NOT cfg.local_enabled OR cfg.local_key_digest IS NULL OR encode(sha256(convert_to(secret,'UTF8')),'hex')<>cfg.local_key_digest THEN RAISE EXCEPTION 'Local HR capability rejected' USING ERRCODE='42501';END IF;
 IF current_setting('transaction_read_only')='on' THEN RAISE EXCEPTION 'Read only' USING ERRCODE='25006';END IF;
 IF NOT cfg.enabled OR NOT cfg.date_readers_verified OR cfg.legacy_history_policy='UNRESOLVED' THEN RAISE EXCEPTION 'Local HR not ready' USING ERRCODE='55000';END IF;
 -- Local legacy mode cannot bypass an installed signed DK protocol.
 IF to_regclass('dk_service.tx_state') IS NOT NULL THEN RAISE EXCEPTION 'Signed DK requires separate integration' USING ERRCODE='55000';END IF;
END;$$;
REVOKE ALL ON FUNCTION personnel_local_admit(text) FROM PUBLIC;
CREATE FUNCTION personnel_local_position_command(local_secret text,eid bigint,pid bigint,on_day date,note text,rid uuid,expected integer,operation text,target uuid,source_pid bigint DEFAULT NULL) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,__SCHEMA__,pg_temp AS $$
 DECLARE actor bigint:=NULL;cfg personnel_settings%ROWTYPE;u auth_users%ROWTYPE;emp employees%ROWTYPE;previous personnel_position_current_orders%ROWTYPE;old_request personnel_position_requests%ROWTYPE;
 v integer;baseline date;payload jsonb;result jsonb;root uuid;prior_position jsonb;new_definition jsonb;creator boolean;allowed boolean;source_explicit boolean:=false;source_day date;next_order personnel_position_current_orders%ROWTYPE;
 BEGIN
 PERFORM personnel_local_admit(local_secret);
 SELECT * INTO cfg FROM personnel_settings WHERE id=1;
 IF rid IS NULL OR expected IS NULL OR expected<0 OR eid IS NULL OR operation IS NULL OR operation NOT IN ('TRANSFER','CORRECT','CANCEL') OR length(note)>2000 THEN RAISE EXCEPTION 'Некорректная кадровая команда' USING ERRCODE='22023';END IF;
 IF (operation='TRANSFER' AND target IS NOT NULL) OR (operation<>'TRANSFER' AND (target IS NULL OR nullif(btrim(note),'') IS NULL)) THEN RAISE EXCEPTION 'Укажите исправляемую запись и основание' USING ERRCODE='22023';END IF;
 IF operation='CANCEL' AND (pid IS NOT NULL OR on_day IS NOT NULL) THEN RAISE EXCEPTION 'Отмена не задаёт новую должность или дату' USING ERRCODE='22023';END IF;
 payload:=jsonb_build_object('employee_id',eid,'position_id',pid,'effective_on',on_day,'reason',nullif(btrim(note),''),'operation',operation,'target',target,'source_position_id',source_pid);
 PERFORM pg_advisory_xact_lock(20261017,29);PERFORM pg_advisory_xact_lock(20261007,1601);PERFORM pg_advisory_xact_lock(20261013,24);
 PERFORM personnel_local_admit(local_secret);
 SELECT * INTO old_request FROM personnel_position_requests WHERE audit_source='LOCAL_APP' AND actor_user_id IS NULL AND request_id=rid;
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
 INSERT INTO personnel_position_events(employee_id,version,root_id,kind,position_id,effective_on,reason,actor_user_id,audit_source,source_position_id,source_on,source_explicit,retained_report_requirement,retained_calendar_configuration) VALUES(eid,v+1,root,operation,pid,on_day,nullif(btrim(note),''),actor,'LOCAL_APP',(prior_position->>'position_id')::bigint,source_day,source_explicit,CASE WHEN pid=16 AND coalesce((prior_position->'definition'->>'requires_daily_report')::boolean,false) THEN true ELSE NULL END,(prior_position->'definition') - ARRAY['name','action_description','specialty','report_description','aos_description','requires_daily_report','planned_count','equipment_description']);
 UPDATE personnel_position_state SET version=v+1 WHERE employee_id=eid;
 result:=jsonb_build_object('employee_id',eid,'root_id',root,'version',v+1,'operation',operation);
 INSERT INTO personnel_position_requests(actor_user_id,audit_source,request_id,payload,result) VALUES(actor,'LOCAL_APP',rid,payload,result);
 RETURN result;
 END;$$;

REVOKE ALL ON FUNCTION personnel_local_position_command(text,bigint,bigint,date,text,uuid,integer,text,uuid,bigint) FROM PUBLIC;
CREATE FUNCTION personnel_local_acting_command(local_secret text,eid bigint,pid bigint,starts date,ends date,note text,rid uuid,expected integer,operation text,target uuid,plan_id bigint,plan_payload jsonb) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,__SCHEMA__,pg_temp AS $$
 DECLARE actor bigint:=NULL;cfg personnel_settings%ROWTYPE;u auth_users%ROWTYPE;e employees%ROWTYPE;old personnel_acting_current%ROWTYPE;
 req personnel_position_requests%ROWTYPE;v integer;payload jsonb;result jsonb;root uuid;creator boolean;main jsonb;v_definition jsonb;start_day date;end_day date;
 BEGIN
 IF operation IS NULL OR operation NOT IN ('ASSIGN','CHANGE_END','END','CANCEL') OR rid IS NULL OR expected IS NULL OR expected<0 OR length(note)>2000 THEN RAISE EXCEPTION 'Некорректная кадровая команда' USING ERRCODE='22023';END IF;
 -- Global business order, before any row lock or nested assignment writer.
 PERFORM pg_advisory_xact_lock(20261017,29);PERFORM pg_advisory_xact_lock(20261007,1601);PERFORM pg_advisory_xact_lock(20261013,24);
 PERFORM personnel_local_admit(local_secret);
 SELECT * INTO cfg FROM personnel_settings WHERE id=1;
 payload:=jsonb_build_object('employee_id',eid,'position_id',pid,'starts_on',starts,'ends_on',ends,'reason',nullif(btrim(note),''),'operation',operation,'target',target,'plan',plan_payload);
 SELECT * INTO req FROM personnel_position_requests WHERE audit_source='LOCAL_APP' AND actor_user_id IS NULL AND request_id=rid;
 IF FOUND THEN IF req.payload<>payload THEN RAISE EXCEPTION 'request_id уже использован с другими данными' USING ERRCODE='22023';END IF;RETURN req.result;END IF;
 SELECT version INTO v FROM personnel_position_state WHERE employee_id=eid FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Сотрудник не найден' USING ERRCODE='P0002';END IF;
 IF v<>expected THEN RAISE EXCEPTION 'История уже изменена. Обновите карточку' USING ERRCODE='40001';END IF;
 SELECT * INTO e FROM employees WHERE id=eid;
 IF e.is_archived THEN RAISE EXCEPTION 'Сотрудник находится в архиве' USING ERRCODE='23514';END IF;
 IF operation='ASSIGN' THEN
 IF target IS NOT NULL OR pid IS NULL OR starts IS NULL OR ends IS NULL OR plan_id IS NOT NULL OR plan_payload IS NOT NULL THEN RAISE EXCEPTION 'Укажите должность и период И.О.' USING ERRCODE='22023';END IF;
 start_day:=starts;end_day:=ends;root:=rid;
 ELSE
 IF target IS NULL OR pid IS NOT NULL OR starts IS NOT NULL OR nullif(btrim(note),'') IS NULL THEN RAISE EXCEPTION 'Укажите назначение и основание изменения' USING ERRCODE='22023';END IF;
 SELECT * INTO old FROM personnel_acting_current WHERE employee_id=eid AND root_id=target;
 IF NOT FOUND THEN RAISE EXCEPTION 'Действующее назначение И.О. не найдено' USING ERRCODE='22023';END IF;
 IF old.kind='END' THEN RAISE EXCEPTION 'И.О. уже завершено с планом; исправление связанных планов требует отдельной проверки' USING ERRCODE='23514';END IF;
 start_day:=old.starts_on;end_day:=CASE WHEN operation='CANCEL' THEN old.ends_on ELSE ends END;pid:=old.position_id;root:=target;
 IF operation='CANCEL' AND ends IS NOT NULL THEN RAISE EXCEPTION 'Отмена не меняет дату окончания' USING ERRCODE='22023';END IF;
 END IF;
 IF start_day IS NULL OR end_day IS NULL OR NOT isfinite(start_day) OR NOT isfinite(end_day) OR end_day<start_day THEN RAISE EXCEPTION 'Некорректный период И.О.' USING ERRCODE='22023';END IF;
 IF e.dismissal_date IS NOT NULL AND end_day>=e.dismissal_date THEN RAISE EXCEPTION 'Назначение затрагивает увольнение' USING ERRCODE='23514';END IF;
 IF operation<>'CANCEL' AND EXISTS(SELECT 1 FROM personnel_acting_current a WHERE a.employee_id=eid AND a.root_id<>root AND a.starts_on<=end_day AND start_day<=a.ends_on) THEN RAISE EXCEPTION 'Периоды И.О. пересекаются' USING ERRCODE='23514';END IF;
 -- Conservative refusal: never reinterpret stored factual reports in an affected interval.
 IF EXISTS(SELECT 1 FROM daily_control_results f WHERE f.employee_id=eid AND f.report_date BETWEEN least(start_day,coalesce(old.starts_on,start_day)) AND greatest(end_day,coalesce(old.ends_on,end_day))) THEN RAISE EXCEPTION 'Период содержит фактическую отчётность: требуется отдельная проверка исправления' USING ERRCODE='23514';END IF;
 main:=personnel_position_at(eid,start_day);
 SELECT d.definition INTO v_definition FROM personnel_position_definitions d WHERE position_id=pid AND known_from<=start_day ORDER BY known_from DESC,id DESC LIMIT 1;
 IF v_definition IS NULL OR main->>'status'<>'KNOWN' OR main->>'definition_status'<>'KNOWN' THEN RAISE EXCEPTION 'Должность или её параметры на дату неизвестны' USING ERRCODE='23514';END IF;
 IF operation='ASSIGN' AND (main->>'position_id')::bigint=pid THEN RAISE EXCEPTION 'И.О. не заменяет назначение на собственную должность' USING ERRCODE='22023';END IF;
 IF v_definition->>'work_schedule' IS DISTINCT FROM main->'definition'->>'work_schedule' OR v_definition->>'work_location' IS DISTINCT FROM main->'definition'->>'work_location' THEN RAISE EXCEPTION 'И.О. не изменяет график или место работы' USING ERRCODE='23514';END IF;
 IF operation='END' THEN
 IF ends>old.ends_on THEN RAISE EXCEPTION 'Завершение не продлевает И.О.; используйте исправление даты' USING ERRCODE='22023';END IF;
 main:=personnel_position_at(eid,end_day+1);
 IF main->>'definition_status'<>'KNOWN' OR coalesce((main->'definition'->>'requires_daily_report')::boolean,false)=false THEN RAISE EXCEPTION 'На дату возвращения не установлена инженерная отчётность' USING ERRCODE='23514';END IF;
 IF NOT EXISTS(SELECT 1 FROM production_assignment_changes c WHERE c.id=plan_id AND c.employee_id=eid AND c.effective_from=end_day+1 AND c.assignment_state='OBJECTS' AND c.source_kind='MANUAL') OR NOT EXISTS(SELECT 1 FROM production_assignment_items WHERE change_id=plan_id) THEN RAISE EXCEPTION 'Необходимо подтверждённое плановое закрепление с даты возвращения' USING ERRCODE='23514';END IF;
 ELSIF plan_id IS NOT NULL OR plan_payload IS NOT NULL THEN RAISE EXCEPTION 'План допустим только при завершении И.О.' USING ERRCODE='22023';END IF;
 INSERT INTO personnel_acting_events(employee_id,version,root_id,kind,position_id,starts_on,ends_on,reason,actor_user_id,audit_source,plan_change_id) VALUES(eid,v+1,root,operation,pid,start_day,end_day,nullif(btrim(note),''),actor,'LOCAL_APP',plan_id);
 UPDATE personnel_position_state SET version=v+1 WHERE employee_id=eid;
 result:=jsonb_build_object('employee_id',eid,'root_id',root,'version',v+1,'operation',operation,'plan_change_id',plan_id);
 INSERT INTO personnel_position_requests(actor_user_id,audit_source,request_id,payload,result) VALUES(actor,'LOCAL_APP',rid,payload,result);
 RETURN result;
 END;$$;

REVOKE ALL ON FUNCTION personnel_local_acting_command(text,bigint,bigint,date,date,text,uuid,integer,text,uuid,bigint,jsonb) FROM PUBLIC;
