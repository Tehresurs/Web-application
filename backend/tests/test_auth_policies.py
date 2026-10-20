import os
if os.environ.get('AUTH_ISOLATED_WORKER') != '1':
    raise RuntimeError('Use backend/scripts/run_auth_isolated.py; legacy DB fixtures are disabled')
import asyncio,json,os,sys,unittest,subprocess,uuid
from pathlib import Path
from unittest.mock import patch
import psycopg
from psycopg import sql
from app.auth_policies import policies,routes,identity
from app.auth_protected import create_protected_app
from app.services.user_auth import AuthService
from app.access_context import read_only_request
from app.api import user_auth as api
from app.main import app
from starlette.responses import Response

DB='auth_stage3_'+uuid.uuid4().hex
SCHEMA='test_construction_identity_stage46'
ROOT=Path(__file__).resolve().parents[1]
def conn(name=DB,auto=False):
 raise RuntimeError("Worker must supply restricted connection factory")
 c=psycopg.connect(host=os.getenv('DB_HOST'),port=os.getenv('DB_PORT'),user=os.getenv('DB_USER'),password=os.getenv('DB_PASSWORD'),dbname=name,autocommit=auto,options='-c search_path='+SCHEMA)
 if read_only_request.get():c.read_only=True
 return c
class TestService(AuthService):
 def connect(self):
  c=conn();assert c.info.dbname==DB and DB.startswith('auth_stage3_');return c

async def http(protected,path,method='GET',token=None,csrf=None,data=None,raw=None,content_type='application/json'):
 from urllib.parse import urlsplit
 u=urlsplit(path);headers=[(b'host',b'127.0.0.1'),(b'origin',b'http://127.0.0.1'),(b'content-type',content_type.encode()),(b'x-role',b'SYSTEM_TECHNICIAN'),(b'x-employee-id',b'999')]
 if token:headers.append((b'cookie',('tehresurs_session='+token).encode()))
 if csrf:headers.append((b'x-csrf-token',csrf.encode()))
 body=raw if raw is not None else json.dumps(data).encode() if data is not None else b'';messages=[]
 async def receive():return {'type':'http.request','body':body,'more_body':False}
 async def send(m):messages.append(m)
 await protected({'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','scheme':'http','method':method,'path':u.path,'raw_path':u.path.encode(),'query_string':u.query.encode(),'headers':headers,'client':('127.0.0.1',1234),'server':('127.0.0.1',80)},receive,send)
 start=next(m for m in messages if m['type']=='http.response.start')
 return start['status'],dict(start['headers']),b''.join(m.get('body',b'') for m in messages if m['type']=='http.response.body')

class PolicyTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
     raise RuntimeError("Legacy fixture disabled; restricted worker supplies lifecycle")
 @classmethod
 def tearDownClass(cls):
     raise RuntimeError("Legacy fixture disabled; restricted worker supplies lifecycle")
 def request(self,path,method='GET',role='manager',data=None,csrf=True):
  token=self.tokens.get(role)
  return asyncio.run(http(self.protected,path,method,token,self.s.csrf(token) if token and csrf else None,data))
 def test_driver_barrier_blocks_production_for_both_connection_paths(self):
  with self.assertRaises(RuntimeError):psycopg.connect(dbname='ai_excel_agent_test')
  from app.database.db import MatrixConnection
  with self.assertRaises(RuntimeError):MatrixConnection.connect(dbname='ai_excel_agent_test')
  with self.assertRaises(RuntimeError):psycopg.connect('dbname=ai_excel_agent_test')
 def test_registry_complete_and_handler_bound(self):
  registered={(m,r.path,identity(r)) for r in routes(app) for m in (getattr(r,'methods',None) or ['MOUNT'])}
  self.assertEqual(registered,{(p['method'],p['path'],p['handler']) for p in policies()})
 def test_anonymous_all_registered_routes(self):
  for p in policies():
   if p['permission']=='PUBLIC':continue
   path=self.example(p['path']);method='GET' if p['method']=='MOUNT' else p['method']
   with self.subTest(method=method,path=path):self.assertEqual(self.request(path,method,role='anonymous')[0],401)
 @staticmethod
 def example(path):
  import re
  return re.sub(r'\{[^}]+\}','1',path)
 def test_manager_all_writes_denied_and_engineer_all_explicit_denials(self):
  for p in policies():
   if p['permission']=='DENY':roles=['manager','engineer']
   elif p['permission'] in ('data.create','data.update'):roles=['manager']
   else:continue
   for role in roles:
    with self.subTest(role=role,path=p['path'],method=p['method']):self.assertEqual(self.request(self.example(p['path']),p['method'],role=role,data={'role':'SYSTEM_TECHNICIAN','employee_id':999})[0],403)
 def test_actual_create_edit_csrf_and_delete_denial(self):
  payload={'name':'Isolated stage3 object '+uuid.uuid4().hex}
  self.assertEqual(self.request('/api/objects','POST',role='engineer',data=payload,csrf=False)[0],403)
  status,_,body=self.request('/api/objects','POST',role='engineer',data=payload)
  self.assertEqual(status,200,body)
  d=json.loads(body);oid=d.get('object',d).get('id') or d.get('id')
  if oid is None:
   with conn() as c:oid=c.execute('SELECT id FROM construction_objects WHERE name=%s',(payload['name'],)).fetchone()[0]
  self.assertEqual(self.request('/api/objects/'+str(oid),'PATCH',role='engineer',data={'name':payload['name']+' edited'})[0],200)
  self.assertEqual(self.request('/api/objects/'+str(oid),'DELETE',role='engineer')[0],403)
 def test_new_routes_denied_and_context_reset(self):
  async def future():return Response('must not run')
  app.add_api_route('/api/unreviewed-stage3',future,methods=['GET','POST'])
  try:
   self.assertEqual(self.request('/api/unreviewed-stage3')[0],403)
   self.assertEqual(self.request('/api/unreviewed-stage3','POST',role='engineer')[0],403)
   self.assertFalse(read_only_request.get())
  finally:app.router.routes.pop()
 def test_view_sections_exports_unchanged(self):
  from tempfile import TemporaryDirectory
  from app.api import vou_archive as va
  from app.services.vou_archive import VouArchive
  folder=TemporaryDirectory(dir=ROOT/'output/security');self.addCleanup(folder.cleanup)
  archive_patch=patch.object(va,'archive',VouArchive(Path(folder.name)/'archive',Path(folder.name)))
  archive_patch.start();self.addCleanup(archive_patch.stop)
  from auth_stage1 import fingerprint
  with conn() as c:before=fingerprint(c)
  for role in ['manager','engineer']:
   for path in ['/','/api/employees','/api/objects','/api/positions','/api/rail-tickets','/api/production-matrix?year=2026&month=10','/api/luvr/month?year=2026&month=10','/api/deployment/report?date=2026-10-18','/api/deployment/analysis?date=2026-10-18','/api/vou/settings','/api/vou/reports']:
    with self.subTest(role=role,path=path):
     status,_,body=self.request(path,role=role);self.assertEqual(status,200,body[:250])
   for path in ['/api/deployment/report/export?date=2026-10-18','/api/luvr/month/export?year=2026&month=10']:
    with self.subTest(role=role,path=path):
     status,_,body=self.request(path,role=role);self.assertEqual(status,200,body[:250]);self.assertTrue(body.startswith(b'PK'))
   status,_,body=self.request('/api/luvr/month/export','POST',role=role,data={'year':2026,'month':10,'employee_ids':[]})
   self.assertEqual(status,400) # Empty explicit selection: business validation, not role denial.
   self.assertEqual(self.request('/api/luvr/month/export','POST',role=role,data={'year':2026,'month':10,'employee_ids':[]},csrf=False)[0],403)
   status,_,body=self.request('/api/vou/reports',role=role);items=json.loads(body)['items']
   if items:
    rid=items[0]['id']
    status,_,body=self.request('/api/vou/reports/'+rid+'/file',role=role);self.assertEqual(status,200);self.assertTrue(body.startswith(b'PK'))
  with conn() as c:self.assertEqual(fingerprint(c),before)
 def candidate_connection(self,autocommit=False,database=None):
  cfg=CANDIDATE_CONFIG
  from app.database.db import MatrixConnection
  c=MatrixConnection.connect(host='127.0.0.1',port=cfg['port'],dbname=database or DB,user=cfg['candidate_role'],password=cfg['candidate_password'],autocommit=autocommit,options='-c search_path='+SCHEMA)
  if read_only_request.get():c.read_only=True
  return c
 def test_step32_native_minimal_privileges(self):
  cfg=CANDIDATE_CONFIG
  with self.candidate_connection() as c:
   self.assertEqual(c.execute('SELECT rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=current_user').fetchone(),(False,)*5)
   self.assertFalse(c.execute("SELECT has_schema_privilege(current_user,'public','USAGE')").fetchone()[0])
   self.assertFalse(c.execute("SELECT has_database_privilege(current_user,current_database(),'TEMP')").fetchone()[0])
   self.assertEqual(c.execute('SELECT count(*) FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname=current_user)').fetchone()[0],0)
   for statement in ['CREATE TABLE forbidden_table(id int)','CREATE TEMP TABLE forbidden_temp(id int)','ALTER TABLE employees ADD COLUMN forbidden int','DROP TABLE employees','TRUNCATE employees','DELETE FROM employees WHERE false','UPDATE auth_users SET is_blocked=true WHERE false','INSERT INTO auth_roles(code,description) VALUES (\'FORBIDDEN\',\'test\')','UPDATE luvr_settings SET agreed_name=agreed_name WHERE false',"SELECT setval('auth_sessions_id_seq',999)"]:
    c.execute('SAVEPOINT blocked')
    with self.subTest(sql=statement.split()[0]):
     with self.assertRaises(psycopg.errors.InsufficientPrivilege):c.execute(statement)
    c.execute('ROLLBACK TO SAVEPOINT blocked')
  with self.candidate_connection(autocommit=True) as c:
   with self.assertRaises(psycopg.errors.InsufficientPrivilege):c.execute('CREATE DATABASE forbidden_database')
   with self.assertRaises(psycopg.errors.InsufficientPrivilege):c.execute('CREATE ROLE forbidden_role')
  for foreign in ['ai_excel_agent','ai_excel_agent_test','postgres',cfg['databases']['stage2']]:
   with self.subTest(database=foreign):
    with self.assertRaises(psycopg.Error) as error:self.candidate_connection(database=foreign)
    raw=getattr(error.exception,'pgconn',None)
    messages=(raw.error_message.decode('utf-8',errors='replace') if raw else '').lower()
    self.assertTrue(error.exception.sqlstate=='42501' or 'permission denied for database' in messages)
    with self.candidate_connection() as c:self.assertFalse(c.execute('SELECT has_database_privilege(current_user,%s,\'CONNECT\')',(foreign,)).fetchone()[0])
 def test_step32_runtime_role_and_dk_conflict(self):
  from app.services.user_auth import AuthService
  from app.auth_ui import create_auth_ui
  owner=self
  class CandidateService(AuthService):
   def connect(self):return owner.candidate_connection()
  service=CandidateService()
  token=service.login('engineer','Only isolated stage3 password!','candidate-role')
  self.assertIn('SYSTEM_TECHNICIAN',service.current(token)['roles'])
  ui=create_auth_ui(app,service)
  patches=[]
  try:
   for name,module in list(sys.modules.items()):
    if name.startswith('app.') and hasattr(module,'get_connection'):
     p=patch.object(module,'get_connection',side_effect=lambda:self.candidate_connection());p.start();patches.append(p)
   p=patch.object(api,'service',return_value=service);p.start();patches.append(p)
   for path in ['/api/employees','/api/objects','/api/rail-tickets','/api/production-matrix?year=2026&month=10','/api/luvr/month?year=2026&month=10','/api/deployment/report/export?date=2026-10-18']:
    self.assertEqual(asyncio.run(http(ui,path,token=token))[0],200,path)
   status,_,body=asyncio.run(http(ui,'/api/objects','POST',token,service.csrf(token),{'name':'Candidate role object '+uuid.uuid4().hex}))
   self.assertEqual(status,200,body[:250])
   status,_,body=asyncio.run(http(ui,'/api/luvr/month/form','POST',token,service.csrf(token),{'year':2027,'month':3}))
   self.assertEqual(status,200,body[:250])
   with self.candidate_connection() as c:
    self.assertGreater(c.execute("SELECT count(*) FROM auth_security_events WHERE event_type='LOGIN_SUCCESS'").fetchone()[0],0)
    # Derived DK cleanup performs DELETE even if no rows match: intentionally NOT granted.
    with self.assertRaises(psycopg.errors.InsufficientPrivilege):c.execute('DELETE FROM production_matrix_dk WHERE false')
   with conn() as setup:
    employee_id,old_name=setup.execute('SELECT id,full_name FROM employees ORDER BY id LIMIT 1').fetchone()
   source_change=self.candidate_connection()
   try:
    source_change.execute('UPDATE employees SET full_name=%s WHERE id=%s',(old_name+' ISOLATED CANDIDATE',employee_id))
    with self.assertRaises(psycopg.errors.InsufficientPrivilege):source_change.commit()
   finally:source_change.close()
   with conn() as verify:self.assertEqual(verify.execute('SELECT full_name FROM employees WHERE id=%s',(employee_id,)).fetchone()[0],old_name)
   from app.services.matrix_dk import reconcile
   with self.candidate_connection() as c:
    with self.assertRaises(psycopg.errors.InsufficientPrivilege):reconcile(c)
   service.logout(token)
   from app.services.user_auth import AuthDenied
   with self.assertRaises(AuthDenied):service.current(token)
  finally:
   for p in reversed(patches):p.stop()
 def test_step32_candidate_vou_archive(self):
  from app.services.user_auth import AuthService
  from app.auth_ui import create_auth_ui
  owner=self
  class CandidateService(AuthService):
   def connect(self):return owner.candidate_connection()
  service=CandidateService();previous=self.protected
  patches=[]
  try:
   self.protected=create_auth_ui(app,service)
   for name,module in list(sys.modules.items()):
    if name.startswith('app.') and hasattr(module,'get_connection'):
     p=patch.object(module,'get_connection',side_effect=lambda:self.candidate_connection());p.start();patches.append(p)
   p=patch.object(api,'service',return_value=service);p.start();patches.append(p)
   self.test_step28_vou_archive_route_isolated_files_and_db()
  finally:
   self.protected=previous
   for p in reversed(patches):p.stop()
 def test_step32_candidate_protected_launcher(self):
  old=dict(os.environ)
  try:
   os.environ.update(DB_USER=CANDIDATE_CONFIG['candidate_role'],DB_PASSWORD=CANDIDATE_CONFIG['candidate_password'])
   self.test_step31_real_bat_chain_and_duplicate()
  finally:
   os.environ.clear();os.environ.update(old)
 def test_step31_forbidden_launch_modes(self):
  env=dict(os.environ);env.pop('AUTH_ISOLATED_WORKER',None)
  for arguments in [['--start','--port','8000'],['--check','--port','8002'],['--start','--isolated-test','--port','8001'],['--check','--isolated-test','--port','49999']]:
   result=subprocess.run([sys.executable,'-B',str(ROOT.parent/'run_8001_authenticated.py'),*arguments],env=env,capture_output=True,timeout=10)
   self.assertNotEqual(result.returncode,0)
 def test_step31_real_bat_chain_and_duplicate(self):
  import socket,time,urllib.request,urllib.error
  with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
  self.assertNotIn(port,(8000,8001))
  project=ROOT.parent
  state=ROOT/'output/launcher_8001'/('authenticated-'+str(port)+'.json')
  env=dict(os.environ,DB_NAME=DB,DB_SCHEMA=SCHEMA,AUTH_ISOLATED_WORKER='1')
  command=['cmd.exe','/d','/c',str(project/'start_tehresurs_8001.bat'),'-Authenticated','-IsolatedTest','-TestPort',str(port),'-NoBrowser']
  log=ROOT/'output/security'/('auth_step31_bat_'+uuid.uuid4().hex+'.log')
  try:
   with log.open('w',encoding='utf-8') as output:first=subprocess.run(command,cwd=project,env=env,stdout=output,stderr=subprocess.STDOUT,timeout=65,stdin=subprocess.DEVNULL)
   self.assertEqual(first.returncode,0,log.read_text(encoding='utf-8',errors='replace'))
   info=json.loads(state.read_text());self.assertEqual(info['database'],DB);self.assertTrue(info['protected'])
   before=info['pid']
   with log.open('w',encoding='utf-8') as output:second=subprocess.run(command,cwd=project,env=env,stdout=output,stderr=subprocess.STDOUT,timeout=30,stdin=subprocess.DEVNULL)
   second_output=log.read_text(encoding='utf-8',errors='replace')
   self.assertEqual(second.returncode,0,second_output)
   self.assertEqual(json.loads(state.read_text())['pid'],before)
   self.assertIn('already running',second_output)
   opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
   self.assertIn(b'authLoginForm',opener.open('http://127.0.0.1:'+str(port)+'/login').read())
   for path in ['/api/auth/me','/api/employees','/api/vou/reports/unknown/file','/api/deployment/report/export','/static/js/processing.js','/api/unknown-route']:
    with self.subTest(path=path):
     with self.assertRaises(urllib.error.HTTPError) as error:opener.open('http://127.0.0.1:'+str(port)+path)
     self.assertEqual(error.exception.code,401)
  finally:
   # Graceful shutdown exists only in the restricted test mode, never production.
   if state.exists():
    info=json.loads(state.read_text());self.assertEqual(info['mode'],'isolated');self.assertEqual(info['port'],port)
    import ctypes
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD];kernel.WaitForSingleObject.restype=wintypes.DWORD
    kernel.CloseHandle.argtypes=[wintypes.HANDLE];kernel.CloseHandle.restype=wintypes.BOOL
    handle=kernel.OpenProcess(0x100000,False,info['pid'])
    self.assertTrue(handle,'Cannot verify isolated process exit')
    try:
     state.with_suffix('.stop').write_text('stop isolated test',encoding='utf-8')
     for _ in range(300):
      if not state.exists():break
      time.sleep(.1)
     self.assertFalse(state.exists(),'Test launcher failed to remove manifest')
     self.assertEqual(kernel.WaitForSingleObject(handle,10000),0,'Test launcher process did not exit')
    finally:kernel.CloseHandle(handle)
 def test_step30_bootstrap_and_protected_downloads(self):
  from app.auth_ui import create_auth_ui
  from scripts.provision_auth_account import password_hash,create_account
  from argon2 import PasswordHasher
  encoded=password_hash('Isolated initial password 2026!','Isolated initial password 2026!')
  self.assertTrue(PasswordHasher().verify(encoded,'Isolated initial password 2026!'))
  with self.assertRaises(ValueError):password_hash('short','short')
  with self.assertRaises(ValueError):password_hash('Isolated initial password 2026!','mismatch')
  c=conn()
  try:
   eid=c.execute('SELECT id FROM employees WHERE NOT is_archived ORDER BY id LIMIT 1').fetchone()[0]
   with self.assertRaises(ValueError):create_account(c,'new-login',eid,'SYSTEM_TECHNICIAN',encoded)
   uid=create_account(c,'bootstrap-test',eid,'SYSTEM_TECHNICIAN',encoded,expected=(DB,SCHEMA))
   self.assertEqual(c.execute('SELECT employee_id,is_blocked FROM auth_users WHERE id=%s',(uid,)).fetchone(),(eid,False))
   self.assertEqual(c.execute('SELECT count(*) FROM auth_security_events WHERE subject_user_id=%s',(uid,)).fetchone()[0],2)
   other=c.execute('SELECT id FROM employees WHERE NOT is_archived AND id<>%s ORDER BY id LIMIT 1',(eid,)).fetchone()[0]
   manager=create_account(c,'bootstrap-manager',other,'OFFICE_MANAGER',encoded,expected=(DB,SCHEMA))
   perms=c.execute('SELECT p.code FROM auth_permissions p JOIN auth_role_permissions rp ON rp.permission_id=p.id JOIN auth_user_roles ur ON ur.role_id=rp.role_id WHERE ur.user_id=%s ORDER BY p.code',(manager,)).fetchall()
   self.assertEqual(perms,[('data.read',),('excel.export',)])
   c.execute('SAVEPOINT duplicate_account')
   with self.assertRaises(psycopg.errors.UniqueViolation):create_account(c,'bootstrap-test',other,'OFFICE_MANAGER',encoded,expected=(DB,SCHEMA))
   c.execute('ROLLBACK TO SAVEPOINT duplicate_account')
   with self.assertRaises(ValueError):create_account(c,'other-login',eid,'ADMIN',encoded,expected=(DB,SCHEMA))
  finally:c.rollback();c.close()
  ui=create_auth_ui(app,self.s)
  for path in ['/static/js/processing.js','/static/../templates/processing.html','/api/vou/reports','/api/vou/reports/unknown/file','/api/deployment/report/export','/docs','/api/unknown-new-route']:
   with self.subTest(path=path):self.assertEqual(asyncio.run(http(ui,path))[0],401)
  for role in ['engineer','manager']:
   self.assertEqual(asyncio.run(http(ui,'/static/js/processing.js',token=self.tokens[role]))[0],200)
   self.assertEqual(asyncio.run(http(ui,'/static/../templates/processing.html',token=self.tokens[role]))[0],404)
 def test_step29_session_expiry_and_public_asset_allowlist(self):
  from app.auth_ui import create_auth_ui
  import hashlib
  ui=create_auth_ui(app,self.s)
  self.assertEqual(asyncio.run(http(ui,'/'))[0],303)
  for path in ['/login','/auth-ui.js','/auth-ui.css']:
   status,headers,body=asyncio.run(http(ui,path))
   self.assertEqual(status,200);self.assertEqual(headers[b'cache-control'],b'no-store')
  self.assertEqual(asyncio.run(http(ui,'/static/js/processing.js'))[0],401)
  self.assertEqual(asyncio.run(http(ui,'/auth-ui.js','POST'))[0],401)
  token=self.s.login('engineer','Only isolated stage3 password!','ui-expiry')
  with conn() as c:
   c.execute("UPDATE auth_sessions SET created_at=now()-interval '2 hours',last_seen_at=now()-interval '2 hours',expires_at=now()-interval '1 hour' WHERE token_hash=%s",(hashlib.sha256(token.encode()).hexdigest(),))
  self.assertEqual(asyncio.run(http(ui,'/',token=token))[0],303)
  self.assertEqual(asyncio.run(http(ui,'/api/auth/me',token=token))[0],401)
  self.assertEqual(asyncio.run(http(ui,'/api/employees',token=token))[0],401)
 def test_step29_browser_sessions_and_ui(self):
  import socket,threading,subprocess,time,shutil
  from tempfile import TemporaryDirectory
  from app.auth_ui import create_auth_ui
  import uvicorn
  browser=Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
  self.assertTrue(browser.is_file(),'Headless browser is required')
  with socket.socket() as sock:
   sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
  with socket.socket() as sock:
   sock.bind(('127.0.0.1',0));debug=sock.getsockname()[1]
  server=uvicorn.Server(uvicorn.Config(create_auth_ui(app,self.s),host='127.0.0.1',port=port,lifespan='off',access_log=False,log_level='critical'))
  thread=threading.Thread(target=server.run,daemon=True);thread.start()
  process=None
  try:
   for _ in range(100):
    if server.started:break
    time.sleep(.05)
   self.assertTrue(server.started)
   with TemporaryDirectory(dir=ROOT/'output/security') as folder:
    process=subprocess.Popen([str(browser),'--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--remote-debugging-address=127.0.0.1','--remote-debugging-port='+str(debug),'--user-data-dir='+folder,'about:blank'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    result=subprocess.run(['node',str(ROOT/'tests/browser/auth_ui.cjs')],input=json.dumps({'base':'http://127.0.0.1:'+str(port),'debug':debug,'password':'Only isolated stage3 password!'}),text=True,capture_output=True,timeout=65)
    if process.poll() is None:process.terminate()
    process.wait(timeout=10)
    self.assertEqual(result.returncode,0,result.stdout+result.stderr)
  finally:
   if process is not None:
    # Close only the browser instance created with our temporary profile.
    if process.poll() is None:process.terminate()
    process.wait(timeout=10)
   server.should_exit=True;thread.join(timeout=10)
   self.assertFalse(thread.is_alive())
 def test_step28_allowed_workflows_require_csrf_and_manager_denied(self):
  for policy in policies():
   if policy.get('allowed_roles'):
    path=self.example(policy['path'])
    with self.subTest(path=path):
     self.assertEqual(self.request(path,policy['method'],role='manager',data={})[0],403)
     self.assertEqual(self.request(path,policy['method'],role='engineer',data={},csrf=False)[0],403)
 def test_step28_replacement_and_approval_branches_blocked(self):
  for path in ['/api/daily-control-results','/api/daily-control-results/check']:
   for extra in [{'replace_fact_id':1},{'confirm_replacement':True},{'replacement_token':'token'},{'replace_source_sha256':'a'*64}]:
    self.assertEqual(self.request(path,'POST',role='engineer',data={'path':'does-not-exist.docx',**extra})[0],403)
  for extra in [{'field':'general_contractor'},{'as_rule':True}]:
   self.assertEqual(self.request('/api/daily-control-results/review-options','POST',role='engineer',data={'path':'x.docx',**extra})[0],403)
  for path in ['/api/daily-control-results','/api/daily-control-results/check','/api/daily-control-results/review-options']:
   self.assertEqual(self.request(path,'POST',role='engineer',data={'path':'does-not-exist.docx'})[0],400)
 def test_step28_luvr_form_and_single_member_real_db(self):
  from auth_stage1 import fingerprint
  with conn() as c:
   before=fingerprint(c)
   c.execute("UPDATE luvr_settings SET agreed_name='ISOLATED TEST SIGNER' WHERE id=1")
   employee=c.execute('SELECT id FROM employees ORDER BY id LIMIT 1').fetchone()[0]
  try:
   status,_,body=self.request('/api/luvr/month/form','POST',role='engineer',data={'year':2027,'month':2})
   self.assertEqual(status,200,body)
   self.assertEqual(self.request('/api/luvr/month/employees','POST',role='engineer',data={'year':2027,'month':2,'employee_id':employee})[0],200)
   with conn() as c:
    after=fingerprint(c)
    self.assertTrue(c.execute('SELECT 1 FROM luvr_months WHERE year=2027 AND month=2').fetchone())
   self.assertTrue(all(before[k]==after[k] for k in before if k not in ('luvr_months','luvr_month_employees','luvr_settings')))
  finally:
   with conn() as c:
    c.execute('DELETE FROM luvr_month_employees WHERE year=2027 AND month=2');c.execute('DELETE FROM luvr_months WHERE year=2027 AND month=2')
 def test_step28_upload_single_files_and_reject_bulk(self):
  from tempfile import TemporaryDirectory
  from app.api import rail_tickets as rail
  from app.services import matrix_report_service as mr
  from datetime import date
  from auth_stage1 import fingerprint
  def multipart(field,filenames):
   boundary='step28boundary'
   parts=[]
   for name in filenames:
    parts.append(('--'+boundary+'\r\nContent-Disposition: form-data; name="'+field+'"; filename="'+name+'"\r\nContent-Type: application/octet-stream\r\n\r\nfixture-bytes-'+name+'\r\n').encode())
   return b''.join(parts)+('--'+boundary+'--\r\n').encode(),'multipart/form-data; boundary='+boundary
  def upload(path,field,names,role='engineer'):
   raw,kind=multipart(field,names);token=self.tokens[role]
   return asyncio.run(http(self.protected,path,'POST',token,self.s.csrf(token),raw=raw,content_type=kind))
  with patch.object(rail,'process_document',return_value=[]) as process:
   self.assertEqual(upload('/api/rail-tickets/upload','files',['one.pdf'])[0],200)
   self.assertEqual(process.call_count,1)
   self.assertEqual(upload('/api/rail-tickets/upload','files',['one.pdf','two.pdf'])[0],403)
   self.assertEqual(upload('/api/rail-tickets/upload','files',['one.pdf'],role='manager')[0],403)
   self.assertEqual(process.call_count,1)
  with conn() as c:before=fingerprint(c);emp=c.execute('SELECT id FROM employees ORDER BY id LIMIT 1').fetchone()[0]
  with TemporaryDirectory(dir=ROOT/'output/security') as folder:
   isolated_module=str(Path(folder)/'backend/app/services/matrix_report_service.py')
   with patch.object(mr,'__file__',isolated_module),patch.object(mr,'read_document',return_value={}),patch.object(mr,'prepare_report',return_value={'employee_id':emp,'report_date':date(2026,10,1)}),patch.object(mr.report_review,'options',return_value={'fields':{}}):
    status,_,body=upload('/api/daily-control-results/upload-file','file',['one.docx'])
    self.assertEqual(status,200,body)
    target=Path(json.loads(body)['report']['source_path'])
    self.assertTrue(target.is_relative_to(Path(folder)));self.assertTrue(target.is_file())
    self.assertEqual(upload('/api/daily-control-results/upload-file','file',['one.docx'],role='manager')[0],403)
  with conn() as c:self.assertEqual(fingerprint(c),before)
 def test_step28_user_management_is_not_authorized(self):
  for role in ['manager','engineer']:
   for path in ['/api/users','/api/users/1','/api/auth/users','/api/auth/roles']:
    self.assertEqual(self.request(path,'POST',role=role,data={})[0],403)
 def test_step28_vou_archive_route_isolated_files_and_db(self):
  from tempfile import TemporaryDirectory
  from zipfile import ZipFile
  from app.api import vou_archive as va
  from app.services import vou_report as vr
  from app.services.vou_archive import VouArchive
  from auth_stage1 import fingerprint
  settings=dict(contract_number='ISOLATED',contract_date='2026-01-01',contract_revision='TEST',customer_signer_name='TEST CUSTOMER',contractor_signer_name='TEST CONTRACTOR')
  data=dict(year=2026,month=10,total_cents=100,sections=[{'total_cents':100}],warnings=[])
  with TemporaryDirectory(dir=ROOT/'output/security') as folder:
   output=Path(folder);archive=VouArchive(output/'archive',output);source=output/'test.xlsm'
   with ZipFile(source,'w') as z:z.writestr('xl/workbook.xml','<workbook/>');z.writestr('xl/vbaProject.bin',b'isolated fixture')
   checks=dict(excel_reopened=True,preservation_accepted=True,data_totals_match=True)
   with conn() as c:before=fingerprint(c)
   with patch.object(vr.vou_settings,'get_settings',return_value=settings),patch.object(vr.vou_data,'prepare_month',return_value=(data,{})),patch.object(vr,'render',return_value=(source,output/'test.pdf',checks)),patch.object(vr,'VouArchive',return_value=archive),patch.object(va,'archive',archive):
    status,_,body=self.request('/api/vou/reports','POST',role='engineer',data={'year':2026,'month':10})
    self.assertEqual(status,200,body);first=json.loads(body)['item']['id']
    status,_,body=self.request('/api/vou/reports','POST',role='engineer',data={'year':2026,'month':10});self.assertEqual(status,200,body);second=json.loads(body)['item']['id']
    self.assertNotEqual(first,second)
    self.assertTrue((output/'archive'/first/'report.xlsm').exists());self.assertTrue((output/'archive'/first/'snapshot.json').exists())
    self.assertEqual(self.request('/api/vou/reports','POST',role='manager',data={'year':2026,'month':10})[0],403)
    self.assertEqual(self.request('/api/vou/reports/'+first+'/file',role='manager')[0],200)
   with conn() as c:self.assertEqual(fingerprint(c),before)
 def test_capabilities_do_not_expose_leader(self):
  for role in ['manager','engineer']:
   status,_,body=self.request('/api/production-matrix/capabilities',role=role)
   self.assertEqual(status,200);self.assertNotIn(b'LEADER',body);self.assertFalse(json.loads(body)['item']['can_manage_dk'])

if __name__=='__main__':unittest.main()
