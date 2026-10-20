"""Restricted subprocess. Receives ONLY isolated test credentials on stdin."""
import os,sys,json,unittest,io
from pathlib import Path
from unittest.mock import patch
import psycopg
from psycopg import sql
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests'),str(ROOT/'output/auth_stage2_dependencies')]
config=json.load(sys.stdin)
os.environ.update(APP_DB_PROFILE='test',DB_HOST='127.0.0.1',DB_PORT=str(config['port']),DB_USER=config['role'],DB_PASSWORD=config['password'],DB_SCHEMA='test_construction_identity_stage46')
# Do not allow project dotenv files to replace the restricted credentials.
import dotenv
dotenv.load_dotenv=lambda *a,**kw:False
SCHEMA='test_construction_identity_stage46'
def connection(db,auto=False):
 c=psycopg.connect(host='127.0.0.1',port=config['port'],user=config['role'],password=config['password'],dbname=db,autocommit=auto,options='-c search_path='+SCHEMA)
 from app.access_context import read_only_request
 if read_only_request.get():c.read_only=True
 return c

def role_proofs():
 out={}
 saved=psycopg.connect
 # Real PostgreSQL authentication rejection, not a Python guard or a network timeout.
 source=dict(host=config['source_host'],port=config['source_port'],dbname='ai_excel_agent_test',user=config['role'],password=config['password'],connect_timeout=3)
 for mode in ('direct','saved_alias','bad_environment'):
  old={k:os.environ.get(k) for k in ('DB_HOST','DB_PORT','DB_NAME','DB_USER','DB_PASSWORD')}
  try:
   params=dict(source)
   if mode=='bad_environment':
    os.environ.update(DB_HOST=str(source['host']),DB_PORT=str(source['port']),DB_NAME=source['dbname'],DB_USER=config['role'],DB_PASSWORD=config['password'])
    params=dict(host=os.environ['DB_HOST'],port=os.environ['DB_PORT'],dbname=os.environ['DB_NAME'],user=os.environ['DB_USER'],password=os.environ['DB_PASSWORD'],connect_timeout=3)
   connector=psycopg.connect if mode=='direct' else saved
   try:
    with connector(**params) as c:raise AssertionError('Isolated role unexpectedly connected to source')
   except psycopg.OperationalError as error:
    pg=getattr(error,'pgconn',None)
    raw=pg.error_message if pg is not None else b''
    messages=[raw.decode(encoding,errors='replace').casefold() for encoding in ('utf-8','cp1251')]
    russian='\u043f\u043e\u0434\u043b\u0438\u043d\u043d\u043e\u0441\u0442'
    auth_message=any('password authentication failed' in msg or russian in msg for msg in messages)
    if error.sqlstate not in ('28P01','28000') and not auth_message:raise
    out['source_'+mode+'_rejected']=True;out['source_'+mode+'_sqlstate']=error.sqlstate
    out['source_'+mode+'_server_auth_message']=auth_message
  finally:
   for key,value in old.items():
    if value is None:os.environ.pop(key,None)
    else:os.environ[key]=value
 out['source_connection_rejected']=all(out['source_'+mode+'_rejected'] for mode in ('direct','saved_alias','bad_environment'))
 db=config['databases']['stage3']
 with connection(db) as c:
  flags=c.execute('SELECT rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=current_user').fetchone()
  assert flags==(False,False,False,False,False);out['minimal_role_flags']=True
 # Local decoy has the exact production DB/schema/table name but no grants.
 for kind in ['direct','saved_alias','bad_environment']:
  if kind=='bad_environment':os.environ['DB_NAME']='ai_excel_agent_test'
  try:
   with saved(host='127.0.0.1',port=config['port'],dbname=os.environ['DB_NAME'] if kind=='bad_environment' else 'ai_excel_agent_test',user=config['role'],password=config['password']) as c:
    c.execute('UPDATE test_construction_identity_stage46.construction_objects SET id=id')
  except psycopg.errors.InsufficientPrivilege:out[kind+'_sql_denied']=True
  else:raise AssertionError('Decoy write allowed')
 # The same DB-level denial survives without connection monkey-patches.
 return out

if config.get('step45_focused'):
 import test_auth_command_proofs as focused_proofs
 focused_proofs.ProofTests.config=config
 focused_stream=io.StringIO()
 focused_suite=unittest.defaultTestLoader.loadTestsFromTestCase(focused_proofs.ProofTests)
 if config.get('step45_owner_audit'):
  focused_suite=unittest.TestSuite(focused_proofs.ProofTests(n) for n in unittest.defaultTestLoader.getTestCaseNames(focused_proofs.ProofTests) if n.startswith(('test_37_','test_38_')))
 focused=unittest.TextTestRunner(stream=focused_stream,verbosity=2).run(focused_suite)
 print(json.dumps({'success':focused.wasSuccessful(),'proofs':{},'test_log':focused_stream.getvalue(),'test_counts':[focused.testsRun],'proof_records':focused_proofs.RECORDS,'focused_only':True}))
 raise SystemExit(not focused.wasSuccessful())

stream=io.StringIO();summary=[];counts=[]
# Separate real BAT preflight BEFORE the general suites; no account setup needed.
import test_auth_policies as preflight_module
preflight_module.DB=config['databases']['stage3'];preflight_module.CANDIDATE_CONFIG=config
class LaunchPreflight(unittest.TestCase):
 test_launcher_shutdown=preflight_module.PolicyTests.test_step31_real_bat_chain_and_duplicate
preflight=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(LaunchPreflight))
summary.append(preflight.wasSuccessful());counts.append(preflight.testsRun)
if not preflight.wasSuccessful():
 print(json.dumps({'success':False,'proofs':{},'test_log':stream.getvalue(),'test_counts':counts}))
 raise SystemExit(1)
proofs=role_proofs()

import test_auth_structure as structure
os.environ['AUTH_TEST_DATABASE']=config['databases']['stage1']
structure.connect=lambda:connection(config['databases']['stage1'])
r=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(structure.AuthStructureTests));summary.append(r.wasSuccessful());counts.append(r.testsRun)

import test_user_auth as stage2
stage2.DB=config['databases']['stage2'];stage2.connect=connection
@classmethod
def stage2_setup(cls):
 cls.s=stage2.IsolatedService();cls.password='Isolated test password 2026!';cls.hash=cls.s.hash_password(cls.password)
stage2.UserAuthTests.setUpClass=stage2_setup
stage2.UserAuthTests.tearDownClass=classmethod(lambda cls:None)
r=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(stage2.UserAuthTests));summary.append(r.wasSuccessful());counts.append(r.testsRun)

import test_auth_policies as stage3
stage3.CANDIDATE_CONFIG=config;stage3.DB=config['databases']['stage3'];stage3.conn=lambda name=stage3.DB,auto=False:connection(name,auto)
@classmethod
def stage3_setup(cls):
 cls.s=stage3.TestService();pw='Only isolated stage3 password!';encoded=cls.s.hash_password(pw)
 with connection(stage3.DB) as c:
  for login,role in [('engineer','SYSTEM_TECHNICIAN'),('manager','OFFICE_MANAGER')]:
   uid=c.execute('INSERT INTO auth_users(login,password_hash,is_blocked) VALUES (%s,%s,false) RETURNING id',(login,encoded)).fetchone()[0]
   c.execute('INSERT INTO auth_user_roles SELECT %s,id FROM auth_roles WHERE code=%s',(uid,role))
 cls.tokens={name:cls.s.login(name,pw,name) for name in ['engineer','manager']}
 cls.patches=[]
 for name,module in list(sys.modules.items()):
  if name.startswith('app.') and hasattr(module,'get_connection'):
   p=patch.object(module,'get_connection',side_effect=lambda:connection(stage3.DB));p.start();cls.patches.append(p)
 from app.services import vou_settings
 def guard(c):assert tuple(c.execute('SELECT current_database(),current_schema()').fetchone())==(stage3.DB,SCHEMA)
 p=patch.object(vou_settings,'assert_target',side_effect=guard);p.start();cls.patches.append(p)
 cls.sp=patch.object(stage3.api,'service',return_value=cls.s);cls.sp.start()
 cls.protected=stage3.create_protected_app(stage3.app,cls.s)
@classmethod
def stage3_cleanup(cls):
 cls.sp.stop()
 for p in reversed(cls.patches):p.stop()
stage3.PolicyTests.setUpClass=stage3_setup;stage3.PolicyTests.tearDownClass=stage3_cleanup
# Replace the old Python-barrier-specific check by the actual PostgreSQL proof.
def sql_barrier(self):self.assertTrue(proofs['source_connection_rejected']);self.assertTrue(proofs['saved_alias_sql_denied'])
stage3.PolicyTests.test_driver_barrier_blocks_production_for_both_connection_paths=sql_barrier
r=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(stage3.PolicyTests));summary.append(r.wasSuccessful());counts.append(r.testsRun)
load_summary=None
if config.get('load_enabled'):
 from scripts.dk_load_benchmark import run as run_load
 load_result=run_load(config)
 load_summary={'status':load_result['status'],'series':len(load_result['series']),'errors':load_result['errors'],'baseline_authorized':load_result['baseline_authorized']}
 summary.append(load_result['status']=='completed')
import test_dk_service_prototype as dk_prototype_tests
dk_prototype_tests.DKServiceTests.config=config
dk_prototype_tests.DKServiceTests.fixture_connection=staticmethod(lambda:connection(stage3.DB))
r=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(dk_prototype_tests.DKServiceTests));summary.append(r.wasSuccessful());counts.append(r.testsRun)
import test_dk_transaction_prototype as tx_tests
tx_tests.TransactionDKTests.config=config
tx_tests.TransactionDKTests.fixture_connection=staticmethod(lambda:connection(config['databases']['stage37']))
r=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(tx_tests.TransactionDKTests));summary.append(r.wasSuccessful());counts.append(r.testsRun)
lock_records=None
if config.get('step40_locks'):
 import test_dk_lock_order as lock_tests
 lock_tests.LockOrderTests.config=config
 r=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(lock_tests.LockOrderTests));summary.append(r.wasSuccessful());counts.append(r.testsRun)
 lock_records=lock_tests.RECORDS
closed_records=None
if config.get('step42_closed'):
 import test_dk_closed_write as closed_tests
 closed_tests.ClosedWriteTests.config=config
 r=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(closed_tests.ClosedWriteTests));summary.append(r.wasSuccessful());counts.append(r.testsRun)
 closed_records=closed_tests.RECORDS
command_records=None
if config.get('step44_commands'):
 import test_auth_closed_commands as command_tests
 command_tests.CommandTests.config=config
 r=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(command_tests.CommandTests));summary.append(r.wasSuccessful());counts.append(r.testsRun)
 command_records=command_tests.RECORDS
proof_records=None
if config.get('step45_proof'):
 import test_auth_command_proofs as proof_tests
 proof_tests.ProofTests.config=config
 r=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(proof_tests.ProofTests));summary.append(r.wasSuccessful());counts.append(r.testsRun)
 proof_records=proof_tests.RECORDS
print(json.dumps({'success':all(summary),'proofs':proofs,'test_log':stream.getvalue(),'test_counts':counts,'load_summary':load_summary,'lock_records':lock_records,'closed_records':closed_records,'command_records':command_records,'proof_records':proof_records}))
raise SystemExit(not all(summary))
