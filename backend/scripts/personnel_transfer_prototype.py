"""Synthetic temporal personnel model ONLY; never a working-schema migration.
No DK/eligible implementation: production integration requires a new signed context.
"""
import os,sys,json,uuid,secrets,socket,subprocess,hashlib,unittest,threading,time
from pathlib import Path
from datetime import datetime,timezone
import psycopg
from psycopg import sql
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from auth_cluster_cleanup import cleanup
DDL=r"""
CREATE SCHEMA hr;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON SCHEMA hr FROM PUBLIC;
CREATE TABLE hr.positions(id bigint PRIMARY KEY,name text NOT NULL,active boolean NOT NULL,report_description text,aos_description text);
CREATE TABLE hr.employees(id bigint PRIMARY KEY,full_name text,position_id bigint REFERENCES hr.positions,crew_id bigint,other_data jsonb NOT NULL);
CREATE TABLE hr.baseline(employee_id bigint PRIMARY KEY REFERENCES hr.employees,observed_on date NOT NULL,position_id bigint REFERENCES hr.positions,start_unknown boolean NOT NULL CHECK(start_unknown));
CREATE TABLE hr.head(employee_id bigint PRIMARY KEY REFERENCES hr.employees,version integer NOT NULL DEFAULT 0);
CREATE TABLE hr.events(employee_id bigint NOT NULL REFERENCES hr.employees,version integer NOT NULL,root uuid NOT NULL,kind text NOT NULL CHECK(kind IN ('TRANSFER','CORRECT','CANCEL')),position_id bigint REFERENCES hr.positions,effective_on date,reason text,actor name NOT NULL,recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),PRIMARY KEY(employee_id,version));
CREATE TABLE hr.requests(actor name NOT NULL,request_id uuid NOT NULL,payload jsonb NOT NULL,result jsonb NOT NULL,PRIMARY KEY(actor,request_id));
CREATE VIEW hr.current_orders AS SELECT * FROM (SELECT DISTINCT ON(employee_id,root) * FROM hr.events ORDER BY employee_id,root,version DESC) s WHERE kind<>'CANCEL';
CREATE VIEW hr.periods AS SELECT employee_id,position_id,known_from,lead(known_from) OVER(PARTITION BY employee_id ORDER BY known_from) known_to,start_unknown,root FROM
 (SELECT employee_id,position_id,observed_on known_from,true start_unknown,NULL::uuid root FROM hr.baseline
 UNION ALL SELECT employee_id,position_id,effective_on,false,root FROM hr.current_orders) s;
CREATE FUNCTION hr.resolve(eid bigint,day date) RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,hr,pg_temp AS $$
 SELECT coalesce((SELECT jsonb_build_object('status',CASE WHEN p.position_id IS NULL THEN 'UNKNOWN_POSITION' ELSE 'KNOWN' END,'position_id',p.position_id,'name',d.name,'known_from',p.known_from,'known_to',p.known_to,'start_unknown',p.start_unknown) FROM hr.periods p LEFT JOIN hr.positions d ON d.id=p.position_id WHERE p.employee_id=eid AND p.known_from<=day AND (p.known_to IS NULL OR day<p.known_to)),jsonb_build_object('status','UNKNOWN_HISTORY','position_id',NULL));$$;
CREATE FUNCTION hr.history(eid bigint) RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,hr,pg_temp AS $$
 SELECT jsonb_build_object('version',(SELECT version FROM hr.head WHERE employee_id=eid),'periods',coalesce((SELECT jsonb_agg(to_jsonb(p) ORDER BY known_from) FROM hr.periods p WHERE employee_id=eid),'[]'::jsonb),'audit',coalesce((SELECT jsonb_agg(to_jsonb(e) ORDER BY version) FROM hr.events e WHERE employee_id=eid),'[]'::jsonb));$$;
CREATE FUNCTION hr.command(eid bigint,pid bigint,on_day date,note text,rid uuid,expected integer,operation text,target uuid) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,hr,pg_temp AS $$
DECLARE v integer; old hr.current_orders%ROWTYPE; response jsonb; canonical jsonb; prior hr.requests%ROWTYPE; anchor date; root_id uuid; old_position bigint;
BEGIN
 IF session_user NOT IN ('personnel_tech','personnel_review') OR (operation<>'TRANSFER' AND session_user<>'personnel_review') THEN RAISE EXCEPTION 'Not permitted' USING ERRCODE='42501';END IF;
 IF operation NOT IN ('TRANSFER','CORRECT','CANCEL') OR operation IS NULL OR rid IS NULL OR eid IS NULL OR expected IS NULL THEN RAISE EXCEPTION 'Invalid command' USING ERRCODE='22023';END IF;
 IF operation='TRANSFER' AND target IS NOT NULL THEN RAISE EXCEPTION 'No correction target on transfer' USING ERRCODE='22023';END IF;
 IF operation<>'TRANSFER' AND (target IS NULL OR nullif(btrim(note),'') IS NULL) THEN RAISE EXCEPTION 'Review reason and target required' USING ERRCODE='22023';END IF;
 IF operation='CANCEL' AND (pid IS NOT NULL OR on_day IS NOT NULL) THEN RAISE EXCEPTION 'Cancel has no replacement' USING ERRCODE='22023';END IF;
 canonical:=jsonb_build_object('employee',eid,'position',pid,'date',on_day,'reason',nullif(btrim(note),''),'operation',operation,'target',target);
 PERFORM pg_advisory_xact_lock(20261017,29);PERFORM pg_advisory_xact_lock(20261007,1601);PERFORM pg_advisory_xact_lock(20261013,24);
 SELECT * INTO prior FROM hr.requests WHERE actor=session_user AND request_id=rid;
 IF FOUND THEN IF prior.payload<>canonical THEN RAISE EXCEPTION 'Request payload conflict' USING ERRCODE='22023';END IF;RETURN prior.result;END IF;
 SELECT version INTO v FROM hr.head WHERE employee_id=eid FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Employee missing' USING ERRCODE='P0002';END IF;
 IF v<>expected THEN RAISE EXCEPTION 'Stale timeline version' USING ERRCODE='40001';END IF;
 SELECT observed_on INTO anchor FROM hr.baseline WHERE employee_id=eid;
 IF operation<>'TRANSFER' THEN SELECT * INTO old FROM hr.current_orders WHERE employee_id=eid AND root=target;
 IF NOT FOUND THEN RAISE EXCEPTION 'No active transfer to review' USING ERRCODE='22023';END IF;END IF;
 IF operation<>'CANCEL' THEN
  IF on_day IS NULL OR on_day<=anchor OR NOT isfinite(on_day) OR pid IS NULL THEN RAISE EXCEPTION 'Date requires known baseline; no invented history' USING ERRCODE='22023';END IF;
  IF NOT EXISTS(SELECT 1 FROM hr.positions WHERE id=pid AND active) THEN RAISE EXCEPTION 'Position unavailable' USING ERRCODE='23514';END IF;
  IF EXISTS(SELECT 1 FROM hr.current_orders WHERE employee_id=eid AND effective_on=on_day AND (target IS NULL OR root<>target)) THEN RAISE EXCEPTION 'Date occupied' USING ERRCODE='23505';END IF;
  SELECT position_id INTO old_position FROM hr.periods WHERE employee_id=eid AND known_from<on_day AND (known_to IS NULL OR known_to>=on_day) ORDER BY known_from DESC LIMIT 1;
  IF operation='TRANSFER' AND old_position IS NOT DISTINCT FROM pid THEN RAISE EXCEPTION 'Same position' USING ERRCODE='22023';END IF;
 END IF;
 root_id:=CASE WHEN operation='TRANSFER' THEN rid ELSE target END;
 INSERT INTO hr.events VALUES(eid,v+1,root_id,operation,pid,on_day,nullif(btrim(note),''),session_user,clock_timestamp());
 UPDATE hr.head SET version=v+1 WHERE employee_id=eid;
 response:=jsonb_build_object('employee_id',eid,'root',root_id,'version',v+1,'operation',operation);
 INSERT INTO hr.requests VALUES(session_user,rid,canonical,response);RETURN response;
END;$$;
CREATE FUNCTION hr.transfer(eid bigint,pid bigint,on_day date,note text,rid uuid,expected integer) RETURNS jsonb LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,hr,pg_temp AS $$SELECT hr.command(eid,pid,on_day,note,rid,expected,'TRANSFER',NULL)$$;
CREATE FUNCTION hr.review(eid bigint,pid bigint,on_day date,note text,rid uuid,expected integer,operation text,target uuid) RETURNS jsonb LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,hr,pg_temp AS $$SELECT hr.command(eid,pid,on_day,note,rid,expected,operation,target)$$;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA hr FROM PUBLIC;
INSERT INTO hr.positions VALUES(1,'Инженер ПИЛ',true,'Описание отчёта','Описание АОС'),(2,'Ведущий инженер',true,'Работы ведущего','Ведущий инженер АОС'),(3,'Руководитель СК',true,'Руководитель','Руководитель АОС'),(4,'Закрытая должность',false,NULL,NULL);
INSERT INTO hr.employees VALUES(1,'Тестовый сотрудник',1,7,'{"assignments":[101],"category":2,"movements":[201],"tickets":[301],"facts":[401],"rotation":30,"luvr":["2030-01-01"],"dk":["2030-01-02"]}'),(2,'Второй сотрудник',1,8,'{}'),(3,'Без должности',NULL,NULL,'{}');
INSERT INTO hr.baseline SELECT id,'2030-01-01',position_id,true FROM hr.employees;
INSERT INTO hr.head SELECT id,0 FROM hr.employees;
"""

def run():
 base=ROOT/'output/security/personnel_isolated';base.mkdir(exist_ok=True)
 run=base/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex);run.mkdir()
 cluster=run/'cluster';pw=run/'pw.tmp';admin='personnel_admin_'+uuid.uuid4().hex;password=secrets.token_urlsafe(32)
 users={n:secrets.token_urlsafe(32) for n in ('personnel_tech','personnel_office','personnel_review')}
 bin=Path('C:/Program Files/PostgreSQL/18/bin');flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
 with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
 started=False;report={'success':False,'synthetic_model_only':True,'production_algorithms_tested':False,'port':port,'cleanup_errors':[]}
 def tool(name,args):
  with (run/'tools.log').open('ab') as f:
   r=subprocess.run([str(bin/(name+'.exe')),*args],stdout=f,stderr=subprocess.STDOUT,timeout=60,creationflags=flags)
  if r.returncode:raise RuntimeError(name+' failed')
 def connect(user=admin,auto=False):return psycopg.connect(host='127.0.0.1',port=port,dbname='postgres',user=user,password=password if user==admin else users[user],autocommit=auto,connect_timeout=3,options='-c lock_timeout=2000 -c statement_timeout=5000')
 try:
  pw.write_text(password);tool('initdb',['-D',str(cluster),'--username='+admin,'--pwfile='+str(pw),'--auth-host=scram-sha-256','--auth-local=scram-sha-256','--encoding=UTF8','--locale=C']);pw.unlink()
  tool('pg_ctl',['-D',str(cluster),'-l',str(run/'postgres.log'),'-o',f'-h 127.0.0.1 -p {port}','-w','start']);started=True
  with connect(auto=True) as c:
   assert Path(c.execute('show data_directory').fetchone()[0]).resolve()==cluster.resolve()
   c.execute('CREATE ROLE personnel_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS')
   for user,secret in users.items():c.execute(sql.SQL('CREATE ROLE {} LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}').format(sql.Identifier(user),sql.Literal(secret)))
   c.execute('REVOKE CONNECT,TEMPORARY ON DATABASE postgres FROM PUBLIC');c.execute('GRANT CONNECT ON DATABASE postgres TO personnel_tech,personnel_office,personnel_review')
   c.execute(DDL)
   for sig, in c.execute("SELECT oid::regprocedure::text FROM pg_proc WHERE pronamespace='pg_catalog'::regnamespace AND proname LIKE '%advisory%'").fetchall():c.execute(sql.SQL('REVOKE EXECUTE ON FUNCTION '+sig+' FROM PUBLIC'))
   c.execute('GRANT EXECUTE ON FUNCTION pg_advisory_xact_lock(integer,integer) TO personnel_owner')
   c.execute('GRANT USAGE ON SCHEMA hr TO personnel_owner,personnel_tech,personnel_office,personnel_review')
   c.execute('GRANT SELECT ON ALL TABLES IN SCHEMA hr TO personnel_owner')
   c.execute('GRANT INSERT ON hr.events,hr.requests TO personnel_owner');c.execute('GRANT UPDATE(version) ON hr.head TO personnel_owner')
   for sig, in c.execute("select p.oid::regprocedure::text from pg_proc p where pronamespace='hr'::regnamespace").fetchall():c.execute(sql.SQL('ALTER FUNCTION '+sig+' OWNER TO personnel_owner'))
   c.execute('GRANT EXECUTE ON FUNCTION hr.resolve(bigint,date),hr.history(bigint) TO personnel_tech,personnel_office,personnel_review')
   c.execute('GRANT EXECUTE ON FUNCTION hr.transfer(bigint,bigint,date,text,uuid,integer) TO personnel_tech')
   c.execute('GRANT EXECUTE ON FUNCTION hr.review(bigint,bigint,date,text,uuid,integer,text,uuid) TO personnel_review')
  import test_personnel_transfer_prototype as tests
  tests.configure(connect,report)
  suite=unittest.defaultTestLoader.loadTestsFromModule(tests)
  with (run/'tests.txt').open('w',encoding='utf-8') as stream:result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
  report.update(tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped),success=result.wasSuccessful() and not result.skipped)
  with connect() as c:
   report['effective_acl']=c.execute("select r.rolname,has_table_privilege(r.oid,'hr.employees','UPDATE'),has_table_privilege(r.oid,'hr.events','INSERT'),has_function_privilege(r.oid,'hr.command(bigint,bigint,date,text,uuid,integer,text,uuid)','EXECUTE') from pg_roles r where rolname in ('personnel_tech','personnel_office','personnel_review','personnel_owner') order by 1").fetchall()
 except Exception as e:report['failure']=type(e).__name__+': '+str(e);raise
 finally:
  def stopped():return not (cluster/'postmaster.pid').exists()
  def stop():tool('pg_ctl',['-D',str(cluster),'-m','fast','-w','stop'])
  status=cleanup(cluster,run,base,stop,stopped);report['cluster_removed']=status['removed']
  if status['error']:report['cleanup_errors'].append(status['error'])
  if pw.exists():pw.unlink()
  (run/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
  print(json.dumps({'report':str(run/'report.json'),'success':report['success'],'cluster_removed':status['removed']}))
 return report['success']
if __name__=='__main__':sys.path.insert(0,str(ROOT/'tests'));raise SystemExit(0 if run() else 1)
