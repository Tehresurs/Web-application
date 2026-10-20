"""Explicit backup/restore/test/apply for 8001 only. Never imported by server."""
import os,sys,json,hashlib,subprocess,uuid
from pathlib import Path
from datetime import datetime,timezone
import psycopg
from psycopg import sql
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ['APP_DB_PROFILE']='test'
from app.database.db import get_connection
DB='ai_excel_agent_test';SCHEMA='test_construction_identity_stage46'
os.environ.update(DB_NAME=DB,DB_SCHEMA=SCHEMA,APP_TEST_ALLOWED_DB_SCHEMAS=SCHEMA)
BIN=Path('C:/Program Files/PostgreSQL/18/bin')
MIG=ROOT/'app/database/migrations/032_auth_structure.sql'

def connection(database,autocommit=False):
 return psycopg.connect(host=os.getenv('DB_HOST'),port=os.getenv('DB_PORT'),user=os.getenv('DB_USER'),password=os.getenv('DB_PASSWORD'),dbname=database,autocommit=autocommit,options='-c search_path='+SCHEMA)
def fingerprint(c,names=None):
 if names is None:names=[r[0] for r in c.execute('SELECT tablename FROM pg_tables WHERE schemaname=%s ORDER BY tablename',(SCHEMA,))]
 result={}
 for name in names:
  rows=c.execute(sql.SQL("SELECT count(*),md5(coalesce(string_agg(v,E'\n' ORDER BY v),'')) FROM (SELECT row_to_json(t)::text v FROM {}.{} t) s").format(sql.Identifier(SCHEMA),sql.Identifier(name))).fetchone()
  result[name]=list(rows)
 return result
def main():
 if sys.argv[1:] not in ([],['--apply']):raise RuntimeError('Use --apply explicitly')
 with connection(DB) as c:
  c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
  assert tuple(c.execute('SELECT current_database(),current_schema()').fetchone())==(DB,SCHEMA)
  before=fingerprint(c)
  assert not any(n.startswith('auth_') for n in before),'Auth objects already exist; do not reapply'
 stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
 out=ROOT/'output'/'security' / ('auth_stage1_'+stamp);out.mkdir(parents=True,exist_ok=False)
 # Contains personnel data: restrict Windows directory to the current account.
 import getpass
 account=os.environ.get('USERDOMAIN','')+'\\'+getpass.getuser()
 subprocess.run(['icacls',str(out),'/inheritance:r','/grant:r',account+':(OI)(CI)F'],check=True,capture_output=True)
 dump=out/'schema.dump';env=os.environ.copy();env.update(PGPASSWORD=os.getenv('DB_PASSWORD',''),PGHOST=os.getenv('DB_HOST','localhost'),PGPORT=os.getenv('DB_PORT','5432'),PGUSER=os.getenv('DB_USER',''))
 def pg(tool,args):
  r=subprocess.run([str(BIN/(tool+'.exe')),*args],env=env,capture_output=True)
  if r.returncode:raise RuntimeError(tool+' failed; diagnostic suppressed to avoid secret disclosure')
 pg('pg_dump',['--dbname='+DB,'--schema='+SCHEMA,'--format=custom','--no-owner','--no-acl','--file='+str(dump)])
 restored='auth_stage1_restore_'+uuid.uuid4().hex
 report={'database':DB,'schema':SCHEMA,'backup':str(dump),'backup_sha256':hashlib.sha256(dump.read_bytes()).hexdigest(),'migration_sha256':hashlib.sha256(MIG.read_bytes()).hexdigest(),'production_before':before,'applied':False}
 created=False
 try:
  with connection(DB,True) as admin:admin.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(restored)))
  created=True
  pg('pg_restore',['--dbname='+restored,'--exit-on-error','--no-owner','--no-acl',str(dump)])
  with connection(restored) as c:
   c.execute('SET TRANSACTION READ ONLY');assert fingerprint(c)==before,'Restored data mismatch'
  report['restore_data_match']=True
  envtest=os.environ.copy();envtest.update(AUTH_TEST_DATABASE=restored,PYTHONPATH=str(ROOT))
  test=subprocess.run([sys.executable,'-B','-m','unittest','discover','-s',str(ROOT/'tests'),'-p','test_auth_structure.py','-v'],env=envtest,capture_output=True,text=True)
  (out/'tests.txt').write_text(test.stdout+test.stderr,encoding='utf-8')
  print(test.stderr)
  assert test.returncode==0,'Tests failed; migration not applied'
  report['tests_passed']=True
  if '--apply' in sys.argv:
   with connection(DB) as c:
    c.execute("SET LOCAL lock_timeout='5s'");c.execute("SET LOCAL statement_timeout='120s'")
    assert tuple(c.execute('SELECT current_database(),current_schema()').fetchone())==(DB,SCHEMA)
    # Prevent concurrent production writes during final before/after comparison.
    for name in before:c.execute(sql.SQL('LOCK TABLE {}.{} IN SHARE MODE').format(sql.Identifier(SCHEMA),sql.Identifier(name)))
    assert fingerprint(c,list(before))==before,'Production data changed during preparation; stop'
    c.execute(MIG.read_text(encoding='utf-8'))
    assert fingerprint(c,list(before))==before,'Production data changed; rollback'
    assert c.execute('SELECT count(*) FROM auth_users').fetchone()[0]==0
   report['applied']=True
  with connection(DB) as c:
   c.execute('SET TRANSACTION READ ONLY');report['production_after']=fingerprint(c,list(before));assert report['production_after']==before
  print(json.dumps({'backup':str(dump),'restore_verified':True,'tests_passed':True,'migration_applied':report['applied'],'unchanged_tables':len(before)}))
 finally:
  if created:
   with connection(DB,True) as admin:admin.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(restored)))
   report['restore_database_removed']=True
  (out/'verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
if __name__=='__main__':main()
