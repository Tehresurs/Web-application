"""Step 45. Owned isolated PG only; separate authorization key and transactional capability."""
import hashlib,hmac,json
from psycopg import sql
from scripts.dk_service_prototype import SOURCE
from app.repositories.luvr_calendar import CALENDAR_SELECT
GATE=(20261020,45)

def install(c,caller,write_owner,dk_owner,fixture,auth_role,auth_password,auth_owner,auth_key):
 if not c.info.dbname.startswith('auth_stage3_tx_closed_auth_proof_') or len(auth_key)!=32:raise RuntimeError('Own proof clone required')
 for role,login in [(auth_role,True),(auth_owner,False)]:
  c.execute(sql.SQL('CREATE ROLE {} '+('LOGIN' if login else 'NOLOGIN')+' NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS').format(sql.Identifier(role)))
 c.execute(sql.SQL('ALTER ROLE {} PASSWORD {}').format(sql.Identifier(auth_role),sql.Literal(auth_password)))
 c.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(sql.Identifier(c.info.dbname),sql.Identifier(auth_role)))
 for role in [auth_role,auth_owner]:c.execute(sql.SQL('GRANT USAGE ON SCHEMA {} TO {}').format(sql.Identifier(SOURCE),sql.Identifier(role)))
 for table in ['auth_users','auth_sessions','auth_roles','auth_permissions','auth_user_roles','auth_role_permissions']:
  c.execute(sql.SQL('GRANT SELECT ON {}.{} TO {},{}').format(sql.Identifier(SOURCE),sql.Identifier(table),sql.Identifier(auth_role),sql.Identifier(auth_owner)))
 c.execute(sql.SQL('GRANT SELECT(id,is_archived) ON {}.employees TO {}').format(sql.Identifier(SOURCE),sql.Identifier(auth_role)))
 c.execute(sql.SQL('GRANT UPDATE(password_changed_at) ON {}.auth_users TO {}').format(sql.Identifier(SOURCE),sql.Identifier(auth_role)))
 for t in ['auth_sessions','auth_security_events']:
  cols={'auth_sessions':'user_id,token_hash,credential_version,expires_at','auth_security_events':'subject_user_id,event_type,outcome,details'}[t]
  c.execute(sql.SQL('GRANT INSERT('+cols+') ON {}.'+t+' TO {}').format(sql.Identifier(SOURCE),sql.Identifier(auth_role)))
  seq=c.execute("SELECT pg_get_serial_sequence(%s,'id')",(SOURCE+'.'+t,)).fetchone()[0]
  c.execute(sql.SQL('GRANT USAGE ON SEQUENCE '+seq+' TO {}').format(sql.Identifier(auth_role)))
 c.execute(sql.SQL('GRANT SELECT(id) ON {}.auth_security_events TO {}').format(sql.Identifier(SOURCE),sql.Identifier(auth_role)))
 # Login rate limit reads its own event store; the trusted auth role is an authority, not a business candidate.
 c.execute(sql.SQL('GRANT SELECT(event_type,occurred_at,details) ON {}.auth_security_events TO {}').format(sql.Identifier(SOURCE),sql.Identifier(auth_role)))
 c.execute(sql.SQL('GRANT UPDATE(revoked_at,revoked_reason) ON {}.auth_sessions TO {}').format(sql.Identifier(SOURCE),sql.Identifier(auth_owner)))
 c.execute(sql.SQL('GRANT DELETE ON {}.auth_user_roles TO {}').format(sql.Identifier(SOURCE),sql.Identifier(auth_owner)))
 c.execute(sql.SQL('GRANT UPDATE(is_blocked,credential_version) ON {}.auth_users TO {}').format(sql.Identifier(SOURCE),sql.Identifier(auth_owner)))
 c.execute(sql.SQL('GRANT EXECUTE ON FUNCTION pg_catalog.pg_advisory_xact_lock(bigint) TO {}').format(sql.Identifier(auth_role)))
 c.execute(sql.SQL('GRANT EXECUTE ON FUNCTION pg_catalog.pg_advisory_xact_lock(integer,integer) TO {}').format(sql.Identifier(auth_owner)))
 c.execute(sql.SQL('CREATE SCHEMA auth_proof AUTHORIZATION {}').format(sql.Identifier(auth_owner)))
 c.execute('REVOKE ALL ON SCHEMA auth_proof FROM PUBLIC')
 for role in [caller,write_owner,auth_role,fixture]:c.execute(sql.SQL('GRANT USAGE ON SCHEMA auth_proof TO {}').format(sql.Identifier(role)))
 c.execute('CREATE TABLE auth_proof.key(id integer PRIMARY KEY CHECK(id=1),secret bytea NOT NULL CHECK(octet_length(secret)=32))')
 c.execute('CREATE TABLE auth_proof.state(xid bigint PRIMARY KEY,ctx jsonb NOT NULL,used boolean NOT NULL DEFAULT false,sid bigint,uid bigint)')
 c.execute("CREATE TABLE auth_proof.policy(id integer PRIMARY KEY CHECK(id=1),mode text NOT NULL CHECK(mode IN ('admission','serialized')))")
 c.execute("INSERT INTO auth_proof.policy VALUES(1,'admission')")
 for t in ['key','state','policy']:c.execute(sql.SQL('ALTER TABLE auth_proof.'+t+' OWNER TO {}').format(sql.Identifier(auth_owner)))
 c.execute('INSERT INTO auth_proof.key VALUES(1,%s)',(auth_key,))
 for role in [auth_owner]:
  c.execute(sql.SQL('GRANT USAGE ON SCHEMA dk_service,auth_command,closed_write TO {}').format(sql.Identifier(role)))
  c.execute(sql.SQL('GRANT EXECUTE ON FUNCTION dk_service.hmac(bytea,bytea,text),auth_command.check_session(bigint,bigint,text),closed_write.enter() TO {}').format(sql.Identifier(role)))
 c.execute(sql.SQL('REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA auth_command FROM {}').format(sql.Identifier(caller)))
 # The old deferred auth interface is retained only as a separate stage44 control, never used here.
 funcs={
 'mac(message text)':('bytea',"DECLARE k bytea;BEGIN SELECT secret INTO k FROM auth_proof.key WHERE id=1;IF message IS NULL OR k IS NULL OR octet_length(k)<>32 THEN RAISE EXCEPTION 'Authorization key unavailable' USING ERRCODE='42501';END IF;RETURN dk_service.hmac(convert_to(message,'UTF8'),k,'sha256');END"),
 'verify_mac(message text,p bytea)':('void',"DECLARE e bytea;diff integer:=0;i integer;BEGIN IF p IS NULL OR octet_length(p)<>32 THEN RAISE EXCEPTION 'Proof denied' USING ERRCODE='42501';END IF;e:=auth_proof.mac(message);IF e IS NULL OR octet_length(e)<>32 THEN RAISE EXCEPTION 'Authorization key unavailable' USING ERRCODE='42501';END IF;FOR i IN 0..31 LOOP diff:=diff | (get_byte(e,i)#get_byte(p,i));END LOOP;IF diff<>0 THEN RAISE EXCEPTION 'Proof denied' USING ERRCODE='42501';END IF;END"),
 'begin_command(op text,payload jsonb,rid uuid,mode text,ttl double precision)':('jsonb',r"""DECLARE v jsonb;d text;BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN RAISE EXCEPTION 'Unsupported proof isolation' USING ERRCODE='42501';END IF;
 IF EXISTS(SELECT 1 FROM auth_proof.state WHERE xid=txid_current()) THEN RAISE EXCEPTION 'One command domain per transaction' USING ERRCODE='42501';END IF;
 IF op IS NULL OR mode IS NULL OR op NOT IN ('employee.read','employee.name') OR mode NOT IN ('admission','serialized') OR rid IS NULL OR ttl IS NULL OR ttl<0.1 OR ttl>15 OR payload IS NULL OR jsonb_typeof(payload)<>'object' THEN RAISE EXCEPTION 'Invalid context' USING ERRCODE='22023';END IF;
 IF (SELECT count(*) FROM jsonb_object_keys(payload))<>(CASE WHEN op='employee.read' THEN 1 ELSE 2 END) OR NOT payload ? 'employee_id' OR (op='employee.name' AND NOT payload ? 'name') OR (payload->>'employee_id')::bigint<=0 THEN RAISE EXCEPTION 'Invalid payload' USING ERRCODE='22023';END IF;
 IF op='employee.name' THEN
 payload:=jsonb_build_object('employee_id',(payload->>'employee_id')::bigint,'name',btrim(regexp_replace(payload->>'name','\s+',' ','g')));
 IF payload->>'name' IS NULL OR payload->>'name'='' THEN RAISE EXCEPTION 'Invalid name' USING ERRCODE='22023';END IF;
 ELSE payload:=jsonb_build_object('employee_id',(payload->>'employee_id')::bigint);END IF;
 IF mode IS DISTINCT FROM (SELECT cfg.mode FROM auth_proof.policy AS cfg WHERE cfg.id=1) THEN RAISE EXCEPTION 'Server mode policy denied' USING ERRCODE='42501';END IF;
 IF op='employee.name' THEN PERFORM closed_write.enter();END IF;
 IF mode='serialized' THEN PERFORM pg_advisory_xact_lock(20261020,45);END IF;
 d:=current_database();
 v:=jsonb_build_object('v',1,'purpose','one-sql-command','db',d,'dbid',(SELECT oid::bigint FROM pg_database WHERE datname=d),'pid',pg_backend_pid(),'xid',txid_current(),'nonce',gen_random_uuid(),'op',op,'payload',payload,'request_id',rid,'mode',mode,'issued_ms',(extract(epoch FROM clock_timestamp())*1000)::bigint,'expires_ms',((extract(epoch FROM clock_timestamp())+ttl)*1000)::bigint);
 INSERT INTO auth_proof.state(xid,ctx) VALUES(txid_current(),v);
 RETURN jsonb_build_object('context',v,'canonical',v::text,'mac',encode(auth_proof.mac('challenge45|'||v::text),'hex'));
 END"""),
 'issue(digest text,challenge jsonb,p bytea)':('jsonb',r"""DECLARE a jsonb;s bigint;u bigint;cv integer;BEGIN
 PERFORM auth_proof.verify_mac('challenge45|'||challenge::text,p);
 IF challenge->>'db'<>current_database() OR (challenge->>'dbid')::bigint<>(SELECT oid FROM pg_database WHERE datname=current_database()) OR (challenge->>'expires_ms')::bigint<=(extract(epoch FROM clock_timestamp())*1000)::bigint OR (challenge->>'expires_ms')::bigint-(challenge->>'issued_ms')::bigint>15100 OR challenge->>'mode' IS DISTINCT FROM (SELECT cfg.mode FROM auth_proof.policy AS cfg WHERE cfg.id=1) THEN RAISE EXCEPTION 'Challenge expired or wrong database' USING ERRCODE='42501';END IF;
 SELECT id,user_id,credential_version INTO s,u,cv FROM test_construction_identity_stage46.auth_sessions WHERE token_hash=digest;
 PERFORM auth_command.check_session(s,u,challenge->>'op');
 a:=jsonb_build_object('context',challenge,'session_id',s,'user_id',u,'credential_version',cv);
 RETURN jsonb_build_object('proof',a,'mac',encode(auth_proof.mac('capability45|'||a::text),'hex'));
 END"""),
 'consume(a jsonb,p bytea,op text,payload jsonb,rid uuid)':('bigint[]',r"""DECLARE st auth_proof.state%ROWTYPE;s bigint;u bigint;cv integer;BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN RAISE EXCEPTION 'Unsupported proof isolation' USING ERRCODE='42501';END IF;
 SELECT * INTO st FROM auth_proof.state WHERE xid=txid_current();
 IF NOT FOUND OR st.used OR a IS NULL OR a->'context' IS DISTINCT FROM st.ctx OR st.ctx->>'db'<>current_database() OR (st.ctx->>'pid')::integer<>pg_backend_pid() OR (st.ctx->>'xid')::bigint<>txid_current() OR st.ctx->>'op' IS DISTINCT FROM op OR st.ctx->'payload' IS DISTINCT FROM payload OR st.ctx->>'request_id' IS DISTINCT FROM rid::text OR (st.ctx->>'expires_ms')::bigint<=(extract(epoch FROM clock_timestamp())*1000)::bigint OR st.ctx->>'mode' IS DISTINCT FROM (SELECT cfg.mode FROM auth_proof.policy AS cfg WHERE cfg.id=1) THEN RAISE EXCEPTION 'Wrong or consumed context' USING ERRCODE='42501';END IF;
 PERFORM auth_proof.verify_mac('capability45|'||a::text,p);
 s:=(a->>'session_id')::bigint;u:=(a->>'user_id')::bigint;
 SELECT credential_version INTO cv FROM test_construction_identity_stage46.auth_sessions WHERE id=s;
 IF cv IS DISTINCT FROM (a->>'credential_version')::integer THEN RAISE EXCEPTION 'Credential version denied' USING ERRCODE='42501';END IF;
 PERFORM auth_command.check_session(s,u,op);
 UPDATE auth_proof.state SET used=true,sid=s,uid=u WHERE xid=txid_current();RETURN ARRAY[s,u];END"""),
 'admitted_context()':('text',"DECLARE v text;BEGIN SELECT ctx::text INTO v FROM auth_proof.state WHERE xid=txid_current() AND used AND ctx->>'op'='employee.name';IF v IS NULL THEN RAISE EXCEPTION 'Not admitted' USING ERRCODE='42501';END IF;RETURN v;END"),
 'set_policy(mode text)':('void',"BEGIN IF mode IS NULL OR mode NOT IN ('admission','serialized') THEN RAISE EXCEPTION 'Invalid policy' USING ERRCODE='22023';END IF;PERFORM pg_advisory_xact_lock(20261020,45);UPDATE auth_proof.policy SET mode=set_policy.mode WHERE id=1;END"),
 'remove_user_roles(uid bigint)':('void',"BEGIN PERFORM pg_advisory_xact_lock(20261020,45);DELETE FROM test_construction_identity_stage46.auth_user_roles WHERE user_id=uid;END"),
 'revoke_user_sessions(uid bigint)':('void',"BEGIN PERFORM pg_advisory_xact_lock(20261020,45);UPDATE test_construction_identity_stage46.auth_sessions SET revoked_at=clock_timestamp(),revoked_reason='REVOKED' WHERE user_id=uid AND revoked_at IS NULL;END"),
 'block_user(uid bigint)':('void',"BEGIN PERFORM pg_advisory_xact_lock(20261020,45);UPDATE test_construction_identity_stage46.auth_users SET is_blocked=true WHERE id=uid;END"),
 'bump_credentials(uid bigint)':('void',"BEGIN PERFORM pg_advisory_xact_lock(20261020,45);UPDATE test_construction_identity_stage46.auth_users SET credential_version=credential_version+1 WHERE id=uid;END")}
 types={'mac':'text','verify_mac':'text,bytea','begin_command':'text,jsonb,uuid,text,double precision','issue':'text,jsonb,bytea','consume':'jsonb,bytea,text,jsonb,uuid','admitted_context':'','revoke_user_sessions':'bigint','block_user':'bigint','bump_credentials':'bigint','set_policy':'text','remove_user_roles':'bigint'}
 for sig,(ret,body) in funcs.items():
  name=sig.split('(')[0];c.execute('CREATE FUNCTION auth_proof.'+sig+' RETURNS '+ret+' LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,auth_proof,test_construction_identity_stage46,pg_temp AS $$ '+body+' $$')
  c.execute(sql.SQL('ALTER FUNCTION auth_proof.'+name+'('+types[name]+') OWNER TO {}').format(sql.Identifier(auth_owner)))
 c.execute('REVOKE ALL ON ALL FUNCTIONS IN SCHEMA auth_proof FROM PUBLIC')
 for name,role in [('begin_command',caller),('issue',auth_role),('consume',write_owner),('admitted_context',write_owner),('revoke_user_sessions',auth_role),('block_user',fixture),('bump_credentials',fixture),('set_policy',fixture),('remove_user_roles',fixture)]:
  c.execute(sql.SQL('GRANT EXECUTE ON FUNCTION auth_proof.'+name+'('+types[name]+') TO {}').format(sql.Identifier(role)))
 # A separate, purpose-bound DK read MAC avoids expanding a leaked auth capability into arbitrary calendar reads.
 c.execute("""CREATE FUNCTION dk_service.check45_read(message text,p bytea) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,dk_service,pg_temp AS $$ DECLARE e bytea;i integer;diff integer:=0;BEGIN IF p IS NULL OR octet_length(p)<>32 THEN RAISE EXCEPTION 'Read permit denied' USING ERRCODE='42501';END IF;SELECT dk_service.hmac(convert_to(message,'UTF8'),secret,'sha256') INTO e FROM dk_service.signing_key WHERE id=1;IF e IS NULL THEN RAISE EXCEPTION 'Read key unavailable' USING ERRCODE='42501';END IF;FOR i IN 0..31 LOOP diff:=diff|(get_byte(e,i)#get_byte(p,i));END LOOP;IF diff<>0 THEN RAISE EXCEPTION 'Read permit denied' USING ERRCODE='42501';END IF;END $$""")
 c.execute(sql.SQL('ALTER FUNCTION dk_service.check45_read(text,bytea) OWNER TO {}').format(sql.Identifier(dk_owner)))
 c.execute('REVOKE ALL ON FUNCTION dk_service.check45_read(text,bytea) FROM PUBLIC')
 c.execute(sql.SQL('GRANT EXECUTE ON FUNCTION dk_service.check45_read(text,bytea) TO {}').format(sql.Identifier(write_owner)))
 business={
 'employee_read(eid bigint,rid uuid,a jsonb,p bytea)':('jsonb',"DECLARE ids bigint[];v jsonb;BEGIN ids:=auth_proof.consume(a,p,'employee.read',jsonb_build_object('employee_id',eid),rid);SELECT jsonb_build_object('id',id,'full_name',full_name,'position_id',position_id,'phone',phone) INTO v FROM test_construction_identity_stage46.employees WHERE id=eid;IF v IS NULL THEN RAISE EXCEPTION 'Employee missing' USING ERRCODE='P0002';END IF;RETURN v;END"),
 'employee_name(eid bigint,new_name text,rid uuid,a jsonb,p bytea)':('jsonb',r"""DECLARE ids bigint[];clean text;h text;old auth_command.requests%ROWTYPE;v jsonb;BEGIN
 clean:=btrim(regexp_replace(new_name,'\s+',' ','g'));
 ids:=auth_proof.consume(a,p,'employee.name',jsonb_build_object('employee_id',eid,'name',clean),rid);
 IF clean IS NULL OR clean='' THEN RAISE EXCEPTION 'Invalid name' USING ERRCODE='22023';END IF;
 h:=encode(sha256(convert_to(jsonb_build_array(eid,clean)::text,'UTF8')),'hex');
 SELECT * INTO old FROM auth_command.requests WHERE uid=ids[2] AND auth_command.requests.rid=employee_name.rid;
 IF FOUND THEN IF old.op<>'employee.name' OR old.payload<>h THEN RAISE EXCEPTION 'Request conflict' USING ERRCODE='22023';END IF;RETURN old.result;END IF;
 PERFORM id FROM test_construction_identity_stage46.employees WHERE id=eid FOR UPDATE;IF NOT FOUND THEN RAISE EXCEPTION 'Employee missing' USING ERRCODE='P0002';END IF;
 IF EXISTS(SELECT 1 FROM test_construction_identity_stage46.employees WHERE lower(btrim(full_name))=lower(btrim(clean)) AND id<>eid) THEN RAISE EXCEPTION 'Duplicate employee' USING ERRCODE='23505';END IF;
 UPDATE test_construction_identity_stage46.employees SET full_name=clean,updated_at=now() WHERE id=eid;
 v:=jsonb_build_object('employee_id',eid,'request_id',rid);INSERT INTO auth_command.requests VALUES(ids[2],rid,'employee.name',h,v);RETURN v;END"""),
 'snapshot(permit bytea)':('jsonb',"DECLARE ctx text;BEGIN ctx:=auth_proof.admitted_context();PERFORM dk_service.check45_read('read45|'||ctx||'|snapshot|0|',permit);RETURN dk_service.tx_snapshot();END"),
 'calendar_row(eid bigint,permit bytea)':('jsonb',"DECLARE ctx text;v jsonb;BEGIN ctx:=auth_proof.admitted_context();PERFORM dk_service.check45_read('read45|'||ctx||'|row|'||eid::text||'|',permit);SELECT to_jsonb(q) INTO v FROM ("+CALENDAR_SELECT+" WHERE e.id=eid) q;RETURN v;END"),
 'absence(eid bigint,day date,permit bytea)':('boolean',"DECLARE ctx text;BEGIN ctx:=auth_proof.admitted_context();PERFORM dk_service.check45_read('read45|'||ctx||'|absence|'||eid::text||'|'||day::text,permit);RETURN EXISTS(SELECT 1 FROM test_construction_identity_stage46.employee_absences WHERE employee_id=eid AND date_from<=day AND (date_to IS NULL OR date_to>=day));END"),
 'register(keys text[],p bytea)':('void',"BEGIN PERFORM auth_proof.admitted_context();PERFORM dk_service.register_intent(keys,p);END")}
 bt={'employee_read':'bigint,uuid,jsonb,bytea','employee_name':'bigint,text,uuid,jsonb,bytea','snapshot':'bytea','calendar_row':'bigint,bytea','absence':'bigint,date,bytea','register':'text[],bytea'}
 for sig,(ret,body) in business.items():
  name=sig.split('(')[0];c.execute('CREATE FUNCTION auth_proof.'+sig+' RETURNS '+ret+' LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,auth_proof,test_construction_identity_stage46,pg_temp AS $$ '+body+' $$')
  c.execute(sql.SQL('ALTER FUNCTION auth_proof.'+name+'('+bt[name]+') OWNER TO {}').format(sql.Identifier(write_owner)))
  c.execute('REVOKE ALL ON FUNCTION auth_proof.'+name+'('+bt[name]+') FROM PUBLIC')
  c.execute(sql.SQL('GRANT EXECUTE ON FUNCTION auth_proof.'+name+'('+bt[name]+') TO {}').format(sql.Identifier(caller)))
 return {'auth_runtime':auth_role,'auth_owner':auth_owner,'auth_key_independent':True,'modes':['admission','serialized'],'gate':GATE,'auth_row_lock_added':False,'max_proof_ttl_seconds':15}

class CalendarConnection:
 def __init__(self,c,key,canonical):self.c=c;self.key=key;self.canonical=canonical
 def __getattr__(self,n):return getattr(self.c,n)
 def permit(self,kind,eid=0,day=''):return hmac.new(self.key,('read45|'+self.canonical+'|'+kind+'|'+str(eid)+'|'+str(day)).encode(),hashlib.sha256).digest()
 def execute(self,q,args=None):
  if q=='SELECT dk_service.tx_snapshot()':return self.c.execute('SELECT auth_proof.snapshot(%s)',(self.permit('snapshot'),))
  if q=='SELECT dk_service.register_intent(%s,%s)':return self.c.execute('SELECT auth_proof.register(%s,%s)',args)
  return self.c.execute(q,args)
 def cursor(self,**kw):return CalendarCursor(self)
class CalendarCursor:
 def __init__(self,a):self.a=a;self.row=None
 def __enter__(self):return self
 def __exit__(self,*a):return False
 def execute(self,q,args):
  a=self.a
  if q==CALENDAR_SELECT+' WHERE e.id=%s':
   self.row=a.c.execute('SELECT auth_proof.calendar_row(%s,%s)',(args[0],a.permit('row',args[0]))).fetchone()[0]
   if self.row and self.row.get('dismissal_date'):
    from datetime import date
    self.row['dismissal_date']=date.fromisoformat(self.row['dismissal_date'])
  elif ' '.join(q.split())=='SELECT 1 FROM employee_absences WHERE employee_id=%s AND date_from<=%s AND (date_to IS NULL OR date_to>=%s) LIMIT 1':
   if args[1]!=args[2]:raise RuntimeError('Unknown canonical query')
   v=a.c.execute('SELECT auth_proof.absence(%s,%s,%s)',(args[0],args[1],a.permit('absence',args[0],args[1]))).fetchone()[0];self.row={'?column?':1} if v else None
  else:raise RuntimeError('Unknown canonical query')
 def fetchone(self):return self.row
