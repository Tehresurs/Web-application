"""Step 44. Installer and read adapter for owned temporary clone only."""
from psycopg import sql
from scripts.dk_service_prototype import SOURCE
from app.repositories.luvr_calendar import CALENDAR_SELECT

def install(c,caller,owner,dk_owner,fixture):
 if not c.info.dbname.startswith('auth_stage3_tx_closed_auth_'):raise RuntimeError('Own auth clone required')
 c.execute(sql.SQL('REVOKE SELECT ON ALL TABLES IN SCHEMA {} FROM {}').format(sql.Identifier(SOURCE),sql.Identifier(caller)))
 c.execute(sql.SQL('REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA closed_write FROM {}').format(sql.Identifier(caller)))
 c.execute(sql.SQL('GRANT EXECUTE ON FUNCTION closed_write.enter() TO {}').format(sql.Identifier(owner)))
 c.execute(sql.SQL('GRANT EXECUTE ON FUNCTION pg_catalog.pg_advisory_xact_lock(bigint) TO {}').format(sql.Identifier(fixture)))
 c.execute(sql.SQL('CREATE SCHEMA auth_command AUTHORIZATION {}').format(sql.Identifier(owner)))
 c.execute('REVOKE ALL ON SCHEMA auth_command FROM PUBLIC')
 c.execute(sql.SQL('GRANT USAGE ON SCHEMA auth_command TO {}').format(sql.Identifier(caller)))
 for t in ['auth_users','auth_sessions','auth_roles','auth_permissions','auth_user_roles','auth_role_permissions']:
  c.execute(sql.SQL('GRANT SELECT ON {}.{} TO {}').format(sql.Identifier(SOURCE),sql.Identifier(t),sql.Identifier(owner)))
 for t in ['positions','employee_movements','employee_sick_periods','employee_duration_exceptions','employee_luvr_day_overrides','employee_absences']:
  c.execute(sql.SQL('GRANT SELECT ON {}.{} TO {}').format(sql.Identifier(SOURCE),sql.Identifier(t),sql.Identifier(owner)))
 c.execute('CREATE TABLE auth_command.pending(xid bigint NOT NULL,sid bigint NOT NULL,uid bigint NOT NULL,op text NOT NULL,PRIMARY KEY(xid,sid,op))')
 c.execute('CREATE TABLE auth_command.requests(uid bigint NOT NULL,rid uuid NOT NULL,op text NOT NULL,payload text NOT NULL,result jsonb NOT NULL,PRIMARY KEY(uid,rid))')
 for t in ['pending','requests']:c.execute(sql.SQL('ALTER TABLE auth_command.'+t+' OWNER TO {}').format(sql.Identifier(owner)))
 functions={
 'check_session(sid bigint,uid bigint,op text)':('void',r"""BEGIN
 IF op NOT IN ('employee.read','employee.name') OR NOT EXISTS(
 SELECT 1 FROM test_construction_identity_stage46.auth_sessions s
 JOIN test_construction_identity_stage46.auth_users u ON u.id=s.user_id
 JOIN test_construction_identity_stage46.employees e ON e.id=u.employee_id
 JOIN test_construction_identity_stage46.auth_user_roles ur ON ur.user_id=u.id
 JOIN test_construction_identity_stage46.auth_roles r ON r.id=ur.role_id
 JOIN test_construction_identity_stage46.auth_role_permissions rp ON rp.role_id=r.id
 JOIN test_construction_identity_stage46.auth_permissions p ON p.id=rp.permission_id
 WHERE s.id=sid AND u.id=uid AND s.revoked_at IS NULL AND s.expires_at>clock_timestamp()
 AND s.credential_version=u.credential_version AND NOT u.is_blocked AND NOT e.is_archived
 AND (e.dismissal_date IS NULL OR e.dismissal_date>=current_date)
 AND ((op='employee.read' AND r.code IN ('SYSTEM_TECHNICIAN','OFFICE_MANAGER') AND p.code='data.read')
 OR (op='employee.name' AND r.code='SYSTEM_TECHNICIAN' AND p.code='data.update')))
 THEN RAISE EXCEPTION 'Command authorization denied' USING ERRCODE='42501'; END IF;
 END"""),
 'identify(secret text,op text)':('bigint[]',r"""DECLARE s bigint;u bigint; BEGIN
 IF secret IS NULL OR length(secret)<>43 THEN RAISE EXCEPTION 'Session denied' USING ERRCODE='42501'; END IF;
 SELECT id,user_id INTO s,u FROM test_construction_identity_stage46.auth_sessions WHERE token_hash=encode(sha256(convert_to(secret,'UTF8')),'hex');
 PERFORM auth_command.check_session(s,u,op);RETURN ARRAY[s,u];END"""),
 'employee_read(secret text,eid bigint)':('jsonb',r"""DECLARE a bigint[];v jsonb;BEGIN
 a:=auth_command.identify(secret,'employee.read');
 SELECT jsonb_build_object('id',id,'full_name',full_name,'position_id',position_id,'phone',phone) INTO v FROM test_construction_identity_stage46.employees WHERE id=eid;
 IF v IS NULL THEN RAISE EXCEPTION 'Employee missing' USING ERRCODE='P0002'; END IF;RETURN v;END"""),
 'employee_name(secret text,eid bigint,new_name text,rid uuid)':('jsonb',r"""DECLARE a bigint[];clean text;h text;old auth_command.requests%ROWTYPE;v jsonb;BEGIN
 PERFORM closed_write.enter();
 a:=auth_command.identify(secret,'employee.name');
 clean:=btrim(regexp_replace(new_name,'\s+',' ','g'));
 IF clean IS NULL OR clean='' OR rid IS NULL THEN RAISE EXCEPTION 'Invalid name/request' USING ERRCODE='22023';END IF;
 h:=encode(sha256(convert_to(jsonb_build_array(eid,clean)::text,'UTF8')),'hex');
 SELECT * INTO old FROM auth_command.requests WHERE uid=a[2] AND auth_command.requests.rid=employee_name.rid;
 IF FOUND THEN
 IF old.op<>'employee.name' OR old.payload<>h THEN RAISE EXCEPTION 'Request conflict' USING ERRCODE='22023';END IF;v:=old.result;
 ELSE
 PERFORM id FROM test_construction_identity_stage46.employees WHERE id=eid FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Employee missing' USING ERRCODE='P0002';END IF;
 IF EXISTS(SELECT 1 FROM test_construction_identity_stage46.employees WHERE lower(btrim(full_name))=lower(btrim(clean)) AND id<>eid)
 THEN RAISE EXCEPTION 'Duplicate employee' USING ERRCODE='23505';END IF;
 UPDATE test_construction_identity_stage46.employees SET full_name=clean,updated_at=now() WHERE id=eid;
 v:=jsonb_build_object('employee_id',eid,'request_id',rid);
 INSERT INTO auth_command.requests VALUES(a[2],rid,'employee.name',h,v);
 END IF;
 INSERT INTO auth_command.pending VALUES(txid_current(),a[1],a[2],'employee.name') ON CONFLICT DO NOTHING;
 RETURN v;END"""),
 'finish()':('trigger',r"""BEGIN PERFORM auth_command.check_session(NEW.sid,NEW.uid,NEW.op);RETURN NULL;END"""),
 'calendar_row(secret text,eid bigint)':('jsonb',"DECLARE a bigint[];v jsonb;BEGIN a:=auth_command.identify(secret,'employee.name'); SELECT to_jsonb(q) INTO v FROM ("+CALENDAR_SELECT+" WHERE e.id=eid) q;RETURN v;END"),
 'absence(secret text,eid bigint,day date)':('boolean',"BEGIN PERFORM auth_command.identify(secret,'employee.name');RETURN EXISTS(SELECT 1 FROM test_construction_identity_stage46.employee_absences WHERE employee_id=eid AND date_from<=day AND (date_to IS NULL OR date_to>=day));END")}
 for sig,(returns,body) in functions.items():
  c.execute('CREATE FUNCTION auth_command.'+sig+' RETURNS '+returns+' LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,auth_command,test_construction_identity_stage46,pg_temp AS $$ '+body+' $$')
  name=sig.split('(')[0];args={'check_session':'bigint,bigint,text','identify':'text,text','employee_read':'text,bigint','employee_name':'text,bigint,text,uuid','finish':'','calendar_row':'text,bigint','absence':'text,bigint,date'}[name]
  c.execute(sql.SQL('ALTER FUNCTION auth_command.'+name+'('+args+') OWNER TO {}').format(sql.Identifier(owner)))
 c.execute('REVOKE ALL ON ALL FUNCTIONS IN SCHEMA auth_command FROM PUBLIC')
 for sig in ['employee_read(text,bigint)','employee_name(text,bigint,text,uuid)','calendar_row(text,bigint)','absence(text,bigint,date)']:
  c.execute(sql.SQL('GRANT EXECUTE ON FUNCTION auth_command.'+sig+' TO {}').format(sql.Identifier(caller)))
 c.execute(sql.SQL('GRANT USAGE ON SCHEMA dk_service TO {}').format(sql.Identifier(owner)))
 for sig in ['tx_snapshot()','register_intent(text[],bytea)']:
  c.execute(sql.SQL('REVOKE EXECUTE ON FUNCTION dk_service.'+sig+' FROM {}').format(sql.Identifier(caller)))
  c.execute(sql.SQL('GRANT EXECUTE ON FUNCTION dk_service.'+sig+' TO {}').format(sql.Identifier(owner)))
 for name,args,returns,body,sig in [
 ('snapshot','secret text','jsonb',"PERFORM closed_write.enter();PERFORM auth_command.identify(secret,'employee.name');RETURN dk_service.tx_snapshot();",'text'),
 ('register','secret text,keys text[],proof bytea','void',"PERFORM closed_write.enter();PERFORM auth_command.identify(secret,'employee.name');PERFORM dk_service.register_intent(keys,proof);",'text,text[],bytea')]:
  c.execute('CREATE FUNCTION auth_command.'+name+'('+args+') RETURNS '+returns+' LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,auth_command,test_construction_identity_stage46,pg_temp AS $$ BEGIN '+body+' END $$')
  c.execute(sql.SQL('ALTER FUNCTION auth_command.'+name+'('+sig+') OWNER TO {}').format(sql.Identifier(owner)))
  c.execute('REVOKE ALL ON FUNCTION auth_command.'+name+'('+sig+') FROM PUBLIC')
  c.execute(sql.SQL('GRANT EXECUTE ON FUNCTION auth_command.'+name+'('+sig+') TO {}').format(sql.Identifier(caller)))
 c.execute('CREATE CONSTRAINT TRIGGER auth_finish AFTER INSERT ON auth_command.pending DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION auth_command.finish()')
 return {'diagnostic_settings':{k:c.execute('SHOW '+k).fetchone()[0] for k in ['shared_preload_libraries','session_preload_libraries','log_parameter_max_length']},'commands':['employee_read','employee_name'],'calendar_read_adapters':2,'auth_row_locks':False,'raw_business_select':False,'final_auth_is_deferrable':True}

class EligibleConnection:
 """Only translates the two exact canonical read queries; never evaluates SQL supplied by a user."""
 def __init__(self,c,token):self.c=c;self.token=token
 def __getattr__(self,k):return getattr(self.c,k)
 def cursor(self,**kw):return EligibleCursor(self.c,self.token)
 def execute(self,q,args=None):
  if q=='SELECT dk_service.tx_snapshot()':return self.c.execute('SELECT auth_command.snapshot(%s)',(self.token,))
  if q=='SELECT dk_service.register_intent(%s,%s)':return self.c.execute('SELECT auth_command.register(%s,%s,%s)',(self.token,*args))
  return self.c.execute(q,args)
class EligibleCursor:
 def __init__(self,c,token):self.c=c;self.token=token;self.row=None
 def __enter__(self):return self
 def __exit__(self,*a):return False
 def execute(self,q,args):
  if q==CALENDAR_SELECT+' WHERE e.id=%s':
   self.row=self.c.execute('SELECT auth_command.calendar_row(%s,%s)',(self.token,args[0])).fetchone()[0]
   if self.row and self.row.get('dismissal_date'):
    from datetime import date
    self.row['dismissal_date']=date.fromisoformat(self.row['dismissal_date'])
  elif ' '.join(q.split())=='SELECT 1 FROM employee_absences WHERE employee_id=%s AND date_from<=%s AND (date_to IS NULL OR date_to>=%s) LIMIT 1':
   if args[1]!=args[2]:raise RuntimeError('Unexpected canonical query')
   v=self.c.execute('SELECT auth_command.absence(%s,%s,%s)',(self.token,args[0],args[1])).fetchone()[0];self.row={'?column?':1} if v else None
  else:raise RuntimeError('Unrecognized canonical query')
 def fetchone(self):return self.row
