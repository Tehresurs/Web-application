"""Backup/restore verification and actual application tests in an owned PostgreSQL.
The source connection is used only for a READ ONLY snapshot and pg_dump.
No working migration, server start/restart or account creation.
"""
import os,sys,json,uuid,secrets,socket,subprocess,hashlib,getpass
from pathlib import Path
from datetime import datetime,timezone
import psycopg
from psycopg import sql
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from run_auth_isolated import snap,SOURCE,SOURCE_DB,SCHEMA,BIN,NO_WINDOW
from auth_cluster_cleanup import cleanup

def full_snapshot(connection):
 connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
 connection.execute("SET LOCAL timezone='UTC'");connection.execute("SET LOCAL datestyle='ISO,YMD'")
 tables=connection.execute("SELECT schemaname,tablename FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema') ORDER BY schemaname,tablename").fetchall()
 result={}
 for schema,name in tables:
  result[schema+'.'+name]=list(connection.execute(sql.SQL("SELECT count(*),md5(coalesce(string_agg(v,E'\\n' ORDER BY v COLLATE \"C\"),'')) FROM (SELECT row_to_json(t)::text v FROM {}.{} t) q").format(sql.Identifier(schema),sql.Identifier(name))).fetchone())
 return result

def main(*,backup_only=False):
 base=ROOT/'output/security/personnel_integration';base.mkdir(exist_ok=True)
 run=base/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex);run.mkdir()
 account=os.environ.get('USERDOMAIN','')+'\\'+getpass.getuser()
 subprocess.run(['icacls',str(run),'/inheritance:r','/grant:r',account+':(OI)(CI)F'],capture_output=True,check=True,creationflags=NO_WINDOW)
 cluster=run/'cluster';pwfile=run/'admin-password.tmp';admin='personnel_fixture_'+uuid.uuid4().hex;password=secrets.token_urlsafe(40)
 db='personnel_restore_'+uuid.uuid4().hex;dump=run/'before_personnel.dump'
 report={'success':False,'source_database':SOURCE_DB,'restored_database':db,'cleanup_errors':[]}
 with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
 if port==int(SOURCE.get('port') or 5432):raise RuntimeError('Source port collision')
 started=False
 def tool(name,args,secret=None):
  env=dict(os.environ)
  if secret:env['PGPASSWORD']=secret
  with (run/'tools.log').open('ab') as output:
   r=subprocess.run([str(BIN/(name+'.exe')),*args],stdout=output,stderr=subprocess.STDOUT,env=env,creationflags=NO_WINDOW,timeout=90)
  if r.returncode:raise RuntimeError(name+' failed; sensitive details suppressed')
 def local(database='postgres',auto=False):return psycopg.connect(host='127.0.0.1',port=port,user=admin,password=password,dbname=database,autocommit=auto,connect_timeout=3,options='-c search_path='+SCHEMA+',public -c timezone=UTC -c datestyle=ISO,YMD -c lock_timeout=3000 -c statement_timeout=10000')
 try:
  report['before']=snap();assert len(report['before'])==41
  with psycopg.connect(**SOURCE,dbname=SOURCE_DB) as source:
   source.execute('SET TRANSACTION READ ONLY')
   locale=source.execute('select datcollate,datctype from pg_database where datname=current_database()').fetchone()
   report['source_locale']=list(locale)
  # pg_dump opens a consistent read-only transaction. Password never enters argv.
  dump_args=['--format=custom','--file='+str(dump),'--host='+str(SOURCE['host']),'--port='+str(SOURCE.get('port') or 5432),'--username='+str(SOURCE['user']),'--dbname='+SOURCE_DB]
  report['backup_scope']='full_database' if backup_only else 'target_schema'
  if backup_only:
   with psycopg.connect(**SOURCE,dbname=SOURCE_DB) as source:report['full_before']=full_snapshot(source)
  else:dump_args.append('--schema='+SCHEMA)
  tool('pg_dump',dump_args,SOURCE['password'])
  report['backup_path']=str(dump);report['backup_sha256']=hashlib.sha256(dump.read_bytes()).hexdigest()
  pwfile.write_text(password);tool('initdb',['-D',str(cluster),'--username='+admin,'--pwfile='+str(pwfile),'--auth-host=scram-sha-256','--auth-local=scram-sha-256','--encoding=UTF8','--locale=C']);pwfile.unlink()
  tool('pg_ctl',['-D',str(cluster),'-l',str(run/'postgres.log'),'-o',f'-h 127.0.0.1 -p {port}','-w','start']);started=True
  with local(auto=True) as c:
   assert Path(c.execute('show data_directory').fetchone()[0]).resolve()==cluster.resolve()
   c.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0 ENCODING {} LC_COLLATE {} LC_CTYPE {}').format(sql.Identifier(db),sql.Literal('UTF8'),sql.Literal(locale[0]),sql.Literal(locale[1])))
  with local(db) as c:c.execute('CREATE EXTENSION IF NOT EXISTS pgcrypto')
  tool('pg_restore',['--exit-on-error','--no-owner','--no-acl','--host=127.0.0.1','--port='+str(port),'--username='+admin,'--dbname='+db,str(dump)],password)
  restored={}
  with local(db) as c:
   c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
   for name in report['before']:
    restored[name]=list(c.execute(sql.SQL("SELECT count(*),md5(coalesce(string_agg(v,E'\n' ORDER BY v COLLATE \"C\"),'')) FROM (SELECT row_to_json(t)::text v FROM {}.{} t) q").format(sql.Identifier(SCHEMA),sql.Identifier(name))).fetchone())
  report['restored_fingerprints']=restored
  report['restore_differences']={name:{'source':report['before'][name],'restored':value} for name,value in restored.items() if value!=report['before'][name]}
  assert restored==report['before'],'Restore fingerprint mismatch: '+','.join(report['restore_differences'])
  if backup_only:
   with local(db) as c:report['full_restored']=full_snapshot(c)
   assert report['full_restored']==report['full_before'],'Full database restore fingerprint mismatch'
   report['full_restoration_verified']=True
  report['restoration_verified']=True;report['restored_fingerprints']=restored
  manifest=run/'backup_verification.json';manifest.write_text(json.dumps({k:report[k] for k in ('source_database','restored_database','backup_path','backup_sha256','restoration_verified')},indent=2),encoding='utf-8')
  report['mode']='backup_restore_only' if backup_only else 'integration'
  if backup_only:
   report['success']=True
  else:
   env={k:v for k,v in os.environ.items() if not k.startswith(('DB_','PG')) and k not in ('APP_DB_PROFILE','DATABASE_URL')}
   env['PYTHONDONTWRITEBYTECODE']='1';env['PYTHONIOENCODING']='utf-8'
   report['worker_source_credentials_removed']=all(k not in env for k in ('DB_HOST','DB_PORT','DB_USER','DB_PASSWORD','PGPASSWORD','DATABASE_URL'))
   config={'port':port,'user':admin,'password':password,'dbname':db,'schema':SCHEMA,'run':str(run),'manifest':str(manifest)}
   process=subprocess.run([sys.executable,'-B',str(ROOT/'scripts/personnel_integration_worker.py')],input=json.dumps(config),capture_output=True,text=True,encoding='utf-8',env=env,creationflags=NO_WINDOW,timeout=180)
   (run/'worker.stderr.log').write_text(process.stderr.replace(password,'[redacted]'),encoding='utf-8')
   worker=json.loads(process.stdout);report['worker']=worker;report['success']=worker['success'] and process.returncode==0
   (run/'tests.txt').write_text(worker['test_log'],encoding='utf-8')
 except Exception as error:
  report['failure']=type(error).__name__+': '+str(error)
 finally:
  def stopped():return not (cluster/'postmaster.pid').exists()
  def stop():tool('pg_ctl',['-D',str(cluster),'-m','fast','-w','stop'])
  status=cleanup(cluster,run,base,stop,stopped);report['cluster_removed']=status['removed']
  if status['error']:report['cleanup_errors'].append(status['error'])
  if pwfile.exists():pwfile.unlink()
  if backup_only and 'full_before' in report:
   with psycopg.connect(**SOURCE,dbname=SOURCE_DB) as source:report['full_after']=full_snapshot(source)
   report['full_source_unchanged']=report['full_before']==report['full_after']
  report['after']=snap();report['source_unchanged']=report.get('before')==report['after']
  (run/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
  print(json.dumps({'report':str(run/'report.json'),'success':report['success'],'source_unchanged':report['source_unchanged'],'cluster_removed':report['cluster_removed']}))
 return report['success'] and report['source_unchanged'] and report['cluster_removed'] and report.get('full_source_unchanged',True)
if __name__=='__main__':
 import argparse
 parser=argparse.ArgumentParser();parser.add_argument('--backup-only',action='store_true');args=parser.parse_args()
 raise SystemExit(0 if main(backup_only=args.backup_only) else 1)
