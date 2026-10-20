"""Own temporary PostgreSQL cluster; NEVER changes roles/grants on source cluster."""
import os,sys,json,uuid,secrets,socket,subprocess,hashlib,shutil,getpass
from pathlib import Path
from datetime import datetime,timezone
import psycopg
from psycopg import sql
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ['APP_DB_PROFILE']='test'
from app.database.db import get_connection
SOURCE_DB='ai_excel_agent_test';SCHEMA='test_construction_identity_stage46'
os.environ.update(DB_NAME=SOURCE_DB,DB_SCHEMA=SCHEMA)
SOURCE={k:os.getenv('DB_'+k.upper()) for k in ['host','port','user','password']}
BIN=Path('C:/Program Files/PostgreSQL/18/bin')
BASE=ROOT/'output/security/auth_isolated'
NO_WINDOW=getattr(subprocess,'CREATE_NO_WINDOW',0)

def snap():
 with psycopg.connect(**SOURCE,dbname=SOURCE_DB,options='-c search_path='+SCHEMA+' -c timezone=UTC -c datestyle=ISO,YMD') as c:
  c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
  assert tuple(c.execute('SELECT current_database(),current_schema()').fetchone())==(SOURCE_DB,SCHEMA)
  names=[r[0] for r in c.execute('SELECT tablename FROM pg_tables WHERE schemaname=%s ORDER BY tablename',(SCHEMA,))]
  values={}
  for name in names:
   values[name]=list(c.execute(sql.SQL("SELECT count(*),md5(coalesce(string_agg(v,E'\n' ORDER BY v COLLATE \"C\"),'')) FROM (SELECT row_to_json(t)::text v FROM {}.{} t) q").format(sql.Identifier(SCHEMA),sql.Identifier(name))).fetchone())
  return values

def main():
 run_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex
 run=BASE/run_id;run.mkdir(parents=True,exist_ok=False)
 account=os.environ.get('USERDOMAIN','')+'\\'+getpass.getuser()
 subprocess.run(['icacls',str(run),'/inheritance:r','/grant:r',account+':(OI)(CI)F'],check=True,capture_output=True,creationflags=NO_WINDOW)
 report={'run_id':run_id,'source':SOURCE_DB+'/'+SCHEMA,'success':False,'open_finding':'construction_objects discrepancy cause remains unknown','cluster_started':False,'cluster_removed':False}
 cluster=run/'cluster';pwfile=run/'admin-password.tmp';admin='iso_admin_'+uuid.uuid4().hex;adminpw=secrets.token_urlsafe(40);role='iso_test_'+uuid.uuid4().hex;password=secrets.token_urlsafe(40)
 started=False;before=None;failure=None
 with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
 # Never use source-cluster port, even if OS selection changes.
 if port==int(SOURCE.get('port') or 5432):raise RuntimeError('Port collision')
 def tool(name,args,env=None):
  with (run/'tools.log').open('ab') as output:
   r=subprocess.run([str(BIN/(name+'.exe')),*args],stdout=output,stderr=subprocess.STDOUT,env=env,creationflags=NO_WINDOW,timeout=90)
  if r.returncode:raise RuntimeError(name+' failed (sensitive diagnostics suppressed)')
  return r
 def local(db='postgres',auto=False):
  return psycopg.connect(host='127.0.0.1',port=port,user=admin,password=adminpw,dbname=db,autocommit=auto,connect_timeout=5,options='-c search_path='+SCHEMA)
 try:
  before=snap();report['before']=before
  load_enabled=os.getenv('AUTH_STEP38_LOAD')=='1'
  source_sizes={}
  if load_enabled:
   from dk_service_prototype import TABLES as load_tables
   with psycopg.connect(**SOURCE,dbname=SOURCE_DB,options='-c search_path='+SCHEMA) as size_conn:
    size_conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
    assert size_conn.execute('SELECT current_database(),current_schema()').fetchone()==(SOURCE_DB,SCHEMA)
    for name in load_tables:
     row=size_conn.execute(sql.SQL('SELECT count(*),coalesce(sum(octet_length(to_jsonb(t)::text)),0),pg_total_relation_size(%s::regclass) FROM {}.{} t').format(sql.Identifier(SCHEMA),sql.Identifier(name)),(SCHEMA+'.'+name,)).fetchone()
     source_sizes[name]=dict(zip(('rows','json_bytes','relation_bytes'),map(int,row)))
   report['source_sizes']=source_sizes

  (run/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
  with psycopg.connect(**SOURCE,dbname=SOURCE_DB) as c:
   c.execute('SET TRANSACTION READ ONLY');assert not c.execute('SELECT 1 FROM pg_roles WHERE rolname=%s',(role,)).fetchone()
  pwfile.write_text(adminpw,encoding='utf-8')
  tool('initdb',['-D',str(cluster),'--username='+admin,'--pwfile='+str(pwfile),'--auth-host=scram-sha-256','--auth-local=scram-sha-256','--encoding=UTF8','--locale=C'])
  pwfile.unlink()
  tool('pg_ctl',['-D',str(cluster),'-l',str(run/'postgres.log'),'-o','-h 127.0.0.1 -p '+str(port),'-w','start'])
  started=True;report['cluster_started']=True
  with local(auto=True) as c:
   assert c.execute("SELECT current_setting('data_directory')").fetchone()[0].replace('\\','/').lower()==str(cluster).replace('\\','/').lower()
   c.execute(sql.SQL('CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}').format(sql.Identifier(role),sql.Literal(password)))
  databases={'stage1':'auth_stage1_restore_'+uuid.uuid4().hex,'stage2':'auth_stage2_'+uuid.uuid4().hex,'stage3':'auth_stage3_'+uuid.uuid4().hex}
  report.update(temporary_role=role,temporary_databases=databases,port=port)
  backup=ROOT/'output/security/auth_stage1_20261018T132747Z/schema.dump'
  meta=json.loads(backup.with_name('verification.json').read_text())
  assert hashlib.sha256(backup.read_bytes()).hexdigest()==meta['backup_sha256'],'Backup digest mismatch'
  envlocal={'SYSTEMROOT':os.environ.get('SYSTEMROOT','C:/Windows'),'PATH':os.environ.get('PATH',''),'TEMP':os.environ.get('TEMP',''),'PGPASSWORD':adminpw}
  for stage,db in databases.items():
   with local(auto=True) as c:c.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(db)))
   if stage!='stage2':
    tool('pg_restore',['--exit-on-error','--no-owner','--no-acl','--host=127.0.0.1','--port='+str(port),'--username='+admin,'--dbname='+db,str(backup)],envlocal)
   with local(db) as c:
    if stage!='stage2':
     for table,expected in meta['production_before'].items():
      count=c.execute(sql.SQL('SELECT count(*) FROM {}.{}').format(sql.Identifier(SCHEMA),sql.Identifier(table))).fetchone()[0]
      if count!=expected[0]:raise RuntimeError('Restored table count mismatch')
    if stage=='stage2':
     c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(SCHEMA)));c.execute('CREATE TABLE employees(id bigint PRIMARY KEY,is_archived boolean NOT NULL DEFAULT false)')
    if stage!='stage1':
     migration=(ROOT/'app/database/migrations/032_auth_structure.sql').read_text().replace("current_database() <> 'ai_excel_agent_test'","current_database() <> '"+db+"'")
     c.execute(migration)
    c.execute(sql.SQL('GRANT USAGE ON SCHEMA {} TO {}').format(sql.Identifier(SCHEMA),sql.Identifier(role)))
    if stage=='stage1':c.execute(sql.SQL('GRANT CREATE ON SCHEMA {} TO {}').format(sql.Identifier(SCHEMA),sql.Identifier(role)))
    c.execute(sql.SQL('GRANT SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES ON ALL TABLES IN SCHEMA {} TO {}').format(sql.Identifier(SCHEMA),sql.Identifier(role)))
    c.execute(sql.SQL('GRANT USAGE,SELECT,UPDATE ON ALL SEQUENCES IN SCHEMA {} TO {}').format(sql.Identifier(SCHEMA),sql.Identifier(role)))
  # Step 32: a second, narrower runtime candidate only in the owned cluster.
  candidate='iso_test_app_'+uuid.uuid4().hex;candidatepw=secrets.token_urlsafe(32)
  grants=json.loads((ROOT/'scripts/app_role_grants.json').read_text())
  with local(auto=True) as c:
   c.execute(sql.SQL('CREATE ROLE {} LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}').format(sql.Identifier(candidate),sql.Literal(candidatepw)))
   c.execute('CREATE DATABASE ai_excel_agent TEMPLATE template0')
   for name in [*databases.values(),'ai_excel_agent','postgres','template1']:
    c.execute(sql.SQL('REVOKE CONNECT,TEMPORARY ON DATABASE {} FROM PUBLIC').format(sql.Identifier(name)))
   for name in databases.values():c.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(sql.Identifier(name),sql.Identifier(role)))
   c.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(sql.Identifier(databases['stage3']),sql.Identifier(candidate)))
  with local(databases['stage3']) as c:
   c.execute('REVOKE ALL ON SCHEMA public FROM PUBLIC')
   c.execute(sql.SQL('REVOKE ALL ON ALL FUNCTIONS IN SCHEMA {} FROM PUBLIC').format(sql.Identifier(SCHEMA)))
   c.execute(sql.SQL('GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA {} TO {}').format(sql.Identifier(SCHEMA),sql.Identifier(role)))
   c.execute(sql.SQL('GRANT USAGE ON SCHEMA {} TO {}').format(sql.Identifier(SCHEMA),sql.Identifier(candidate)))
   for table in grants['select']:
    c.execute(sql.SQL('GRANT SELECT ON {}.{} TO {}').format(sql.Identifier(SCHEMA),sql.Identifier(table),sql.Identifier(candidate)))
   for table,rights in grants['write'].items():
    c.execute(sql.SQL('GRANT '+','.join(rights)+' ON {}.{} TO {}').format(sql.Identifier(SCHEMA),sql.Identifier(table),sql.Identifier(candidate)))
    if 'INSERT' in rights:
     sequences=c.execute("SELECT s.relname FROM pg_class s JOIN pg_depend d ON d.objid=s.oid JOIN pg_class t ON t.oid=d.refobjid JOIN pg_namespace n ON n.oid=t.relnamespace WHERE s.relkind='S' AND d.deptype='a' AND n.nspname=%s AND t.relname=%s",(SCHEMA,table)).fetchall()
     for sequence, in sequences:c.execute(sql.SQL('GRANT USAGE ON SEQUENCE {}.{} TO {}').format(sql.Identifier(SCHEMA),sql.Identifier(sequence),sql.Identifier(candidate)))
   for table,columns in grants.get('column_update',{}).items():
    c.execute(sql.SQL('GRANT UPDATE('+','.join(columns)+') ON {}.{} TO {}').format(sql.Identifier(SCHEMA),sql.Identifier(table),sql.Identifier(candidate)))
   for signature in grants['functions']:
    c.execute(sql.SQL('GRANT EXECUTE ON FUNCTION {}.'+signature+' TO {}').format(sql.Identifier(SCHEMA),sql.Identifier(candidate)))
  from dk_service_prototype import install as install_dk_prototype
  dk_owner='iso_dk_owner_'+uuid.uuid4().hex;dk_key=secrets.token_bytes(32)
  with local(databases['stage3']) as c:install_dk_prototype(c,dk_owner,candidate,dk_key)
  with local(databases['stage3']) as c:
   c.execute(sql.SQL('GRANT USAGE ON SCHEMA dk_service TO {}').format(sql.Identifier(role)))
   c.execute(sql.SQL('GRANT INSERT,DELETE ON dk_service.signing_key TO {}').format(sql.Identifier(role)))
  # Step 37 has a separate clone so old vulnerability controls remain executable.
  tx_db='auth_stage3_tx_'+uuid.uuid4().hex
  with local(auto=True) as c:
   c.execute(sql.SQL('CREATE DATABASE {} TEMPLATE {}').format(sql.Identifier(tx_db),sql.Identifier(databases['stage3'])))
   c.execute(sql.SQL('REVOKE CONNECT,TEMPORARY ON DATABASE {} FROM PUBLIC').format(sql.Identifier(tx_db)))
   c.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {},{}').format(sql.Identifier(tx_db),sql.Identifier(role),sql.Identifier(candidate)))
  from scripts.dk_transaction_prototype import install as install_transaction_prototype
  with local(tx_db) as c:install_transaction_prototype(c,dk_owner,candidate)
  databases['stage37']=tx_db
  closed_config={}
  if os.getenv('AUTH_STEP42_CLOSED')=='1':
   closed_db='auth_stage3_tx_closed_'+uuid.uuid4().hex
   with local(auto=True) as c:
    c.execute(sql.SQL('CREATE DATABASE {} TEMPLATE {}').format(sql.Identifier(closed_db),sql.Identifier(tx_db)))
    c.execute(sql.SQL('REVOKE CONNECT ON DATABASE {} FROM {}').format(sql.Identifier(closed_db),sql.Identifier(candidate)))
   from scripts.dk_closed_write_prototype import install as install_closed
   closed_role='iso_closed_'+uuid.uuid4().hex;closed_password=secrets.token_urlsafe(32);closed_owner='iso_write_owner_'+uuid.uuid4().hex
   with local(closed_db) as c:report['closed_install']=install_closed(c,closed_role,closed_password,closed_owner,dk_owner,role)
   databases['stage42']=closed_db
   closed_config=dict(step42_closed=True,closed_role=closed_role,closed_password=closed_password,closed_owner=closed_owner)
  if os.getenv('AUTH_STEP44_COMMANDS')=='1':
   if not closed_config:raise RuntimeError('Step 44 requires isolated closed clone')
   auth_db='auth_stage3_tx_closed_auth_'+uuid.uuid4().hex
   with local(auto=True) as c:
    c.execute(sql.SQL('CREATE DATABASE {} TEMPLATE {}').format(sql.Identifier(auth_db),sql.Identifier(databases['stage42'])))
    c.execute(sql.SQL('REVOKE CONNECT,TEMPORARY ON DATABASE {} FROM PUBLIC').format(sql.Identifier(auth_db)))
    c.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {},{}').format(sql.Identifier(auth_db),sql.Identifier(role),sql.Identifier(closed_role)))
   from scripts.auth_closed_command_prototype import install as install_auth_commands
   with local(auth_db) as c:report['auth_command_install']=install_auth_commands(c,closed_role,closed_owner,dk_owner,role)
   databases['stage44']=auth_db
   closed_config.update(step44_commands=True,step44_log=str(run/'postgres.log'),step44_settings=report['auth_command_install']['diagnostic_settings'])
  if os.getenv('AUTH_STEP45_PROOF')=='1':
   if not closed_config.get('step44_commands'):raise RuntimeError('Step 45 requires isolated stage44 clone')
   proof_db='auth_stage3_tx_closed_auth_proof_'+uuid.uuid4().hex
   with local(auto=True) as c:
    c.execute(sql.SQL('CREATE DATABASE {} TEMPLATE {}').format(sql.Identifier(proof_db),sql.Identifier(databases['stage44'])))
    c.execute(sql.SQL('REVOKE CONNECT,TEMPORARY ON DATABASE {} FROM PUBLIC').format(sql.Identifier(proof_db)))
    c.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {},{}').format(sql.Identifier(proof_db),sql.Identifier(role),sql.Identifier(closed_role)))
   auth_role='iso_auth_runtime_'+uuid.uuid4().hex;auth_password=secrets.token_urlsafe(32);auth_owner='iso_auth_owner_'+uuid.uuid4().hex
   auth_key=secrets.token_bytes(32);assert auth_key!=dk_key
   from scripts.auth_command_proof_prototype import install as install_proof
   with local(proof_db) as c:report['proof_install']=install_proof(c,closed_role,closed_owner,dk_owner,role,auth_role,auth_password,auth_owner,auth_key)
   databases['stage45']=proof_db
   peer_db='auth_stage3_tx_closed_auth_proof_peer_'+uuid.uuid4().hex
   with local(auto=True) as c:
    c.execute(sql.SQL('CREATE DATABASE {} TEMPLATE {}').format(sql.Identifier(peer_db),sql.Identifier(proof_db)))
    c.execute(sql.SQL('REVOKE CONNECT,TEMPORARY ON DATABASE {} FROM PUBLIC').format(sql.Identifier(peer_db)))
    c.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {},{},{}').format(sql.Identifier(peer_db),sql.Identifier(role),sql.Identifier(closed_role),sql.Identifier(auth_role)))
   databases['stage45_peer']=peer_db
   fault_db='auth_stage3_tx_closed_auth_proof_fault_'+uuid.uuid4().hex
   with local(auto=True) as c:
    c.execute(sql.SQL('CREATE DATABASE {} TEMPLATE {}').format(sql.Identifier(fault_db),sql.Identifier(proof_db)))
    c.execute(sql.SQL('REVOKE CONNECT,TEMPORARY ON DATABASE {} FROM PUBLIC').format(sql.Identifier(fault_db)))
    c.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {},{}').format(sql.Identifier(fault_db),sql.Identifier(closed_role),sql.Identifier(auth_role)))
   with local(fault_db) as c:c.execute('DELETE FROM auth_proof.key')
   databases['stage45_fault']=fault_db

   closed_config.update(step45_proof=True,step45_focused=os.getenv('AUTH_STEP45_FOCUSED') in ('1','owners'),step45_owner_audit=os.getenv('AUTH_STEP45_FOCUSED')=='owners',auth_role=auth_role,auth_password=auth_password,auth_owner=auth_owner,step45_log=str(run/'postgres.log'))
  report['dk_service_owner']=dk_owner
  report['candidate_role']=candidate
  # Decoy production-name database in isolated cluster, with NO schema/table grants.
  with local(auto=True) as c:c.execute('CREATE DATABASE ai_excel_agent_test TEMPLATE template0');c.execute('REVOKE CONNECT,TEMPORARY ON DATABASE ai_excel_agent_test FROM PUBLIC');c.execute(sql.SQL('GRANT CONNECT ON DATABASE ai_excel_agent_test TO {}').format(sql.Identifier(role)))
  with local(SOURCE_DB) as c:
   c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(SCHEMA)))
   c.execute('CREATE TABLE construction_objects(id bigint PRIMARY KEY)');c.execute('INSERT INTO construction_objects VALUES (1)')
  load_databases={}
  if load_enabled:
   for name,template in [('new',databases['stage37']),('legacy',databases['stage3'])]:
    load_db='auth_stage3_'+('tx_load_' if name=='new' else 'load_')+uuid.uuid4().hex
    with local(auto=True) as c:
     c.execute(sql.SQL('CREATE DATABASE {} TEMPLATE {}').format(sql.Identifier(load_db),sql.Identifier(template)))
     c.execute(sql.SQL('REVOKE CONNECT,TEMPORARY ON DATABASE {} FROM PUBLIC').format(sql.Identifier(load_db)))
     c.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {},{}').format(sql.Identifier(load_db),sql.Identifier(role),sql.Identifier(candidate)))
    load_databases[name]=load_db
   report['load_databases']=load_databases
  worker_env={k:os.environ[k] for k in ['SYSTEMROOT','PATH','TEMP','TMP','WINDIR'] if k in os.environ}
  worker_env.update(AUTH_ISOLATED_WORKER='1',PYTHONDONTWRITEBYTECODE='1',PYTHONIOENCODING='utf-8')
  config=dict(step40_locks=os.getenv('AUTH_STEP40_LOCKS')=='1',dk_owner=dk_owner,dk_signing_key=dk_key.hex(),candidate_role=candidate,candidate_password=candidatepw,port=port,role=role,password=password,databases=databases,source_host=SOURCE['host'],source_port=SOURCE['port'])
  config.update(closed_config)
  if load_enabled:
   config.update(load_enabled=True,source_sizes=source_sizes,load_db_new=load_databases['new'],load_db_legacy=load_databases['legacy'],load_pg_pid=int((cluster/'postmaster.pid').read_text().splitlines()[0]),load_baseline_authorized=os.getenv('AUTH_STEP38_BASELINE_FIXTURE_ALLOWED')=='1',load_output=str(run/'load.json'))
  result=subprocess.run([sys.executable,'-B',str(ROOT/'scripts/auth_test_worker.py')],input=json.dumps(config),text=True,encoding='utf-8',capture_output=True,env=worker_env,creationflags=NO_WINDOW,timeout=600 if load_enabled or closed_config else 240)
  (run/'worker.stderr.log').write_text(result.stderr.replace(password,'<redacted>').replace(adminpw,'<redacted>').replace(candidatepw,'<redacted>').replace(dk_key.hex(),'<redacted>').replace(closed_config.get('closed_password','UNUSED_CLOSED_SECRET'),'<redacted>').replace(closed_config.get('auth_password','UNUSED_AUTH_SECRET'),'<redacted>'),encoding='utf-8')
  try:result_json=json.loads(result.stdout)
  except ValueError:raise RuntimeError('Worker failed before diagnostic result (details suppressed)') from None
  (run/'tests.txt').write_text(result_json.pop('test_log'),encoding='utf-8');report['worker']=result_json
  assert result.returncode==0 and result_json['success'],'Restricted integration tests failed'
  with local(SOURCE_DB) as c:assert c.execute('SELECT id FROM construction_objects').fetchall()==[(1,)]
  report['decoy_integrity']=True
  report['success']=True
 except BaseException as e:
  failure=e;report['error_type']=type(e).__name__;report['error']='Isolated run failed; inspect restricted diagnostics'
 finally:
  cleanup_errors=[]
  from auth_cluster_cleanup import cleanup
  def stopped():
   if not cluster.exists():return True
   status=subprocess.run([str(BIN/'pg_ctl.exe'),'-D',str(cluster),'status'],capture_output=True,creationflags=NO_WINDOW,timeout=10)
   return status.returncode==3
  try:
   result_cleanup=cleanup(cluster,run,BASE,lambda:tool('pg_ctl',['-D',str(cluster),'-m','fast','-w','stop']),stopped)
   report['cleanup']=result_cleanup;report['cluster_removed']=result_cleanup['removed'];report['cluster_stopped']=stopped()
   if result_cleanup['error']:cleanup_errors.append(result_cleanup['error'])
  except BaseException as e:cleanup_errors.append('cleanup:'+type(e).__name__)
  try:
   if pwfile.exists():pwfile.unlink()
  except BaseException as e:cleanup_errors.append('password-file:'+type(e).__name__)
  report['cleanup_errors']=cleanup_errors
  if before is not None:
   try:
    after=snap();report['after']=after;report['source_unchanged']=before==after
   except BaseException as e:
    report['source_unchanged']=False;cleanup_errors.append('verification:'+type(e).__name__)
  report['success']=report['success'] and not cleanup_errors and report.get('source_unchanged',False)
  (run/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
  print(json.dumps({'report':str(run/'report.json'),'success':report['success'],'source_unchanged':report.get('source_unchanged'),'cleanup_errors':cleanup_errors}))
 if not report['success']:raise SystemExit(1)
if __name__=='__main__':main()
