-- Explicit extension of 033. No startup DDL; never apply to the working DB without approval.
CREATE TABLE personnel_acting_events (
 employee_id bigint NOT NULL REFERENCES employees(id) ON DELETE RESTRICT,
 version integer NOT NULL CHECK(version>0), root_id uuid NOT NULL,
 kind text NOT NULL CHECK(kind IN ('ASSIGN','CHANGE_END','END','CANCEL')),
 position_id bigint NOT NULL REFERENCES positions(id) ON DELETE RESTRICT,
 starts_on date NOT NULL, ends_on date NOT NULL,
 reason text CHECK(length(reason)<=2000), actor_user_id bigint NOT NULL REFERENCES auth_users(id) ON DELETE RESTRICT,
 plan_change_id bigint REFERENCES production_assignment_changes(id) ON DELETE RESTRICT,
 recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(employee_id,version), CHECK(isfinite(starts_on) AND isfinite(ends_on) AND starts_on<=ends_on),
 CHECK(kind='ASSIGN' OR nullif(btrim(reason),'') IS NOT NULL), CHECK(kind<>'END' OR plan_change_id IS NOT NULL)
);
CREATE VIEW personnel_acting_current AS
 SELECT * FROM (SELECT DISTINCT ON(employee_id,root_id) * FROM personnel_acting_events ORDER BY employee_id,root_id,version DESC) t WHERE kind<>'CANCEL';
CREATE FUNCTION personnel_acting_at(eid bigint,day date) RETURNS jsonb
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,__SCHEMA__,pg_temp AS $$
 SELECT (SELECT to_jsonb(a)||jsonb_build_object('definition',d.definition) FROM personnel_acting_current a LEFT JOIN LATERAL
 (SELECT definition FROM personnel_position_definitions WHERE position_id=a.position_id AND known_from<=day ORDER BY known_from DESC,id DESC LIMIT 1) d ON true
 WHERE a.employee_id=eid AND day BETWEEN a.starts_on AND a.ends_on);$$;
CREATE FUNCTION personnel_acting_command(actor bigint,sid bigint,eid bigint,pid bigint,starts date,ends date,note text,rid uuid,expected integer,operation text,target uuid,plan_id bigint,plan_payload jsonb) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,__SCHEMA__,pg_temp AS $$
 DECLARE cfg personnel_settings%ROWTYPE;u auth_users%ROWTYPE;e employees%ROWTYPE;old personnel_acting_current%ROWTYPE;
 req personnel_position_requests%ROWTYPE;v integer;payload jsonb;result jsonb;root uuid;creator boolean;main jsonb;v_definition jsonb;start_day date;end_day date;
 BEGIN
 IF operation IS NULL OR operation NOT IN ('ASSIGN','CHANGE_END','END','CANCEL') OR rid IS NULL OR expected IS NULL OR expected<0 OR length(note)>2000 THEN RAISE EXCEPTION 'Некорректная кадровая команда' USING ERRCODE='22023';END IF;
 -- Global business order, before any row lock or nested assignment writer.
 PERFORM pg_advisory_xact_lock(20261017,29);PERFORM pg_advisory_xact_lock(20261007,1601);PERFORM pg_advisory_xact_lock(20261013,24);
 SELECT * INTO cfg FROM personnel_settings WHERE id=1;
 SELECT * INTO u FROM auth_users WHERE id=actor AND NOT is_blocked;
 creator:=coalesce(cfg.creator_user_id=actor,false);
 IF u.id IS NULL OR NOT EXISTS(SELECT 1 FROM auth_sessions s WHERE s.id=sid AND s.user_id=actor AND s.revoked_at IS NULL AND s.expires_at>clock_timestamp() AND s.credential_version=u.credential_version)
 OR NOT (creator OR EXISTS(SELECT 1 FROM auth_user_roles ur JOIN auth_roles r ON r.id=ur.role_id JOIN auth_role_permissions rp ON rp.role_id=r.id JOIN auth_permissions p ON p.id=rp.permission_id WHERE ur.user_id=actor AND r.code='SYSTEM_TECHNICIAN' AND p.code='data.update'))
 OR (operation IN ('CANCEL','CHANGE_END') AND NOT creator) THEN RAISE EXCEPTION 'Кадровая операция недоступна' USING ERRCODE='42501';END IF;
 IF NOT cfg.enabled OR NOT cfg.dk_context_verified OR NOT cfg.date_readers_verified OR cfg.legacy_history_policy='UNRESOLVED' THEN RAISE EXCEPTION 'Кадровая запись не включена: контекст ДК и читатели не проверены' USING ERRCODE='55000';END IF;
 payload:=jsonb_build_object('employee_id',eid,'position_id',pid,'starts_on',starts,'ends_on',ends,'reason',nullif(btrim(note),''),'operation',operation,'target',target,'plan',plan_payload);
 SELECT * INTO req FROM personnel_position_requests WHERE actor_user_id=actor AND request_id=rid;
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
 INSERT INTO personnel_acting_events(employee_id,version,root_id,kind,position_id,starts_on,ends_on,reason,actor_user_id,plan_change_id) VALUES(eid,v+1,root,operation,pid,start_day,end_day,nullif(btrim(note),''),actor,plan_id);
 UPDATE personnel_position_state SET version=v+1 WHERE employee_id=eid;
 result:=jsonb_build_object('employee_id',eid,'root_id',root,'version',v+1,'operation',operation,'plan_change_id',plan_id);
 INSERT INTO personnel_position_requests(actor_user_id,request_id,payload,result) VALUES(actor,rid,payload,result);
 RETURN result;
 END;$$;
REVOKE ALL ON personnel_acting_events,personnel_acting_current FROM PUBLIC;
REVOKE ALL ON FUNCTION personnel_acting_at(bigint,date),personnel_acting_command(bigint,bigint,bigint,bigint,date,date,text,uuid,integer,text,uuid,bigint,jsonb) FROM PUBLIC;
