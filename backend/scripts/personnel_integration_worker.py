"""Restricted-to-own-cluster application integration worker (stdin credentials)."""
import os,sys,json,io,unittest,uuid,threading,time,asyncio
from pathlib import Path
from datetime import date,timedelta
from unittest.mock import patch
import psycopg
from psycopg import sql
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
config=json.load(sys.stdin)
assert config['dbname'].startswith('personnel_restore_') and config['schema']=='test_construction_identity_stage46'
import dotenv;dotenv.load_dotenv=lambda *a,**k:False
assert all(k not in os.environ for k in ('DB_HOST','DB_PORT','DB_USER','DB_PASSWORD','PGPASSWORD','DATABASE_URL')),'Source credentials inherited'
os.environ.update(APP_DB_PROFILE='test',DB_HOST='127.0.0.1',DB_PORT=str(config['port']),DB_USER=config['user'],DB_PASSWORD=config['password'],DB_NAME=config['dbname'],DB_SCHEMA=config['schema'])
from app.database import db

def connect():
 from app.access_context import read_only_request
 c=db.MatrixConnection.connect(host='127.0.0.1',port=config['port'],user=config['user'],password=config['password'],dbname=config['dbname'],connect_timeout=3,options='-c search_path='+config['schema']+',public -c lock_timeout=3000 -c statement_timeout=8000')
 if c.execute('select current_database(),current_schema()').fetchone()!=(config['dbname'],config['schema']):c.close();raise RuntimeError('Wrong isolated connection')
 c.rollback()
 if read_only_request.get():c.read_only=True
 return c

saved_psycopg_connect=psycopg.connect
saved_matrix_connect=db.MatrixConnection.connect
def checked_driver(original,*args,**kwargs):
 if args or kwargs.get('host')!='127.0.0.1' or int(kwargs.get('port',0))!=config['port'] or kwargs.get('dbname')!=config['dbname'] or kwargs.get('user')!=config['user']:
  raise RuntimeError('Worker connections restricted to exact owned PostgreSQL endpoint')
 return original(**kwargs)
psycopg.connect=lambda *a,**kw:checked_driver(saved_psycopg_connect,*a,**kw)
db.MatrixConnection.connect=staticmethod(lambda *a,**kw:checked_driver(saved_matrix_connect,*a,**kw))
db.get_connection=connect
from app.database.migrate_personnel_transfers import apply_migration
with connect() as c:apply_migration(c,config['manifest'],expected_database=config['dbname'])
from app.database.migrate_personnel_transfers import apply_movements_migration
with connect() as c:apply_movements_migration(c,config['manifest'],expected_database=config['dbname'])
# Test the pre-activation rollback only in this exact owned restore, then reinstall.
with connect() as c:
 names=[r[0] for r in c.execute("SELECT tablename FROM pg_tables WHERE schemaname=current_schema() AND tablename NOT LIKE 'personnel_%' ORDER BY tablename").fetchall()]
 assert len(names)==41
 def fingerprints():
  return {name:c.execute(sql.SQL("SELECT count(*),md5(coalesce(string_agg(v,E'\\n' ORDER BY v COLLATE \"C\"),'')) FROM (SELECT row_to_json(t)::text v FROM {} t) q").format(sql.Identifier(name))).fetchone() for name in names}
 before_rollback=fingerprints()
 rollback_sql=(ROOT/'docs/sql/rollback_personnel_movements_pre_activation.sql').read_text(encoding='utf-8-sig').replace('__SCHEMA__',sql.Identifier(config['schema']).as_string(c))
 c.execute(rollback_sql)
 assert c.execute("SELECT to_regclass('personnel_settings')").fetchone()[0] is None
 assert fingerprints()==before_rollback
 apply_migration(c,config['manifest'],expected_database=config['dbname']);apply_movements_migration(c,config['manifest'],expected_database=config['dbname'])
rollback_verified=True
from app.main import app
from app.api import user_auth
from app.repositories import personnel_transfers as repo
from app.services.user_auth import AuthService
from app.services.luvr_duration import local_today
class TestAuth(AuthService):
 def connect(self):return connect()
auth=TestAuth();user_auth.service=lambda:auth
TODAY=local_today();BASE=TODAY-timedelta(days=40)
async def http(application,path,method='GET',token=None,csrf=None,data=None):
 from urllib.parse import urlsplit
 u=urlsplit(path);headers=[(b'host',b'127.0.0.1'),(b'origin',b'http://127.0.0.1'),(b'content-type',b'application/json')]
 if token:headers.append((b'cookie',('tehresurs_session='+token).encode()))
 if csrf:headers.append((b'x-csrf-token',csrf.encode()))
 body=json.dumps(data).encode() if data is not None else b'';messages=[]
 async def receive():return {'type':'http.request','body':body,'more_body':False}
 async def send(message):messages.append(message)
 await application({'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','scheme':'http','method':method,'path':u.path,'raw_path':u.path.encode(),'query_string':u.query.encode(),'headers':headers,'client':('127.0.0.1',1234),'server':('127.0.0.1',80)},receive,send)
 start=next(m for m in messages if m['type']=='http.response.start')
 return start['status'],dict(start['headers']),b''.join(m.get('body',b'') for m in messages if m['type']=='http.response.body')
# http() works with app.main too: authorization is also checked inside the new handlers.
def request(path,method='GET',token=None,payload=None,csrf=True):
 return asyncio.run(http(app,path,method,token,auth.csrf(token) if token and csrf else None,payload))

class TransferApplicationTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.password='Only isolated transfer test '+uuid.uuid4().hex
  encoded=auth.hash_password(cls.password)
  with connect() as c:
   cls.positions=[]
   for name,place,schedule in [('A','OBJECT','SHIFT'),('B','OBJECT','SHIFT'),('C','OBJECT','SHIFT'),('Office','OFFICE','FIVE_TWO')]:
    cls.positions.append(c.execute('INSERT INTO positions(name,work_location,work_schedule,requires_daily_report) VALUES(%s,%s,%s,true) RETURNING id',('Transfer test '+name+' '+uuid.uuid4().hex,place,schedule)).fetchone()[0])
   cls.positions.append(c.execute('SELECT id FROM positions WHERE id=14 AND requires_daily_report=false').fetchone()[0])
   cls.crew=c.execute('INSERT INTO crews(name) VALUES(%s) RETURNING id',('Transfer crew '+uuid.uuid4().hex,)).fetchone()[0]
   cls.employee=c.execute('INSERT INTO employees(full_name,position_id,crew_id,max_shift_days,max_off_shift_days) VALUES(%s,%s,%s,30,30) RETURNING id',('Transfer employee '+uuid.uuid4().hex,cls.positions[0],cls.crew)).fetchone()[0]
   c.execute("INSERT INTO employee_movements(employee_id,movement_type,transport_type,event_datetime) VALUES(%s,'ARRIVAL','SELF',%s)",(cls.employee,str(BASE+timedelta(days=1))+' 07:00:00'))
   c.execute("INSERT INTO rail_tickets(file_hash,source_filename,employee_id,status) VALUES(%s,'personnel_fixture.pdf',%s,'PARSED')",(uuid.uuid4().hex+uuid.uuid4().hex,cls.employee))
   c.execute("INSERT INTO daily_control_results(report_date,employee_id,object_id,subobject_id,entity_id,po_id,category_id,subcontractor_id,source_file,source_sha256) SELECT %s,%s,object_id,subobject_id,entity_id,po_id,category_id,subcontractor_id,'personnel_fixture.docx',%s FROM daily_control_results LIMIT 1",(TODAY,cls.employee,uuid.uuid4().hex+uuid.uuid4().hex))
   c.execute('INSERT INTO employee_assignments(id,employee_id,object_id,po_id,category_id,entity_id) SELECT (SELECT coalesce(max(id),0)+1 FROM employee_assignments),%s,object_id,po_id,category_id,entity_id FROM employee_assignments LIMIT 1',(cls.employee,))
   c.execute('UPDATE personnel_position_baselines SET known_on=%s WHERE employee_id=%s',(BASE,cls.employee))
   c.execute('UPDATE personnel_position_definitions SET known_from=%s WHERE position_id=ANY(%s)',(BASE,cls.positions))
   cls.users={}
   for login,role in [('transfer_tech','SYSTEM_TECHNICIAN'),('transfer_office','OFFICE_MANAGER'),('transfer_creator','SYSTEM_TECHNICIAN')]:
    uid=c.execute('INSERT INTO auth_users(login,password_hash,is_blocked) VALUES(%s,%s,false) RETURNING id',(login,encoded)).fetchone()[0]
    c.execute('INSERT INTO auth_user_roles SELECT %s,id FROM auth_roles WHERE code=%s',(uid,role));cls.users[login]=uid
  cls.tokens={name:auth.login(name,cls.password,'127.0.0.1') for name in cls.users}
  cls.sessions={name:auth.current(token)['session_id'] for name,token in cls.tokens.items()}
  cls.base=f'/api/employees/{cls.employee}/position-transfers'
 def setUp(self):
  with connect() as c:
   c.execute('DELETE FROM personnel_acting_events');c.execute('DELETE FROM production_assignment_items WHERE change_id IN (SELECT id FROM production_assignment_changes WHERE employee_id=%s)',(TransferApplicationTests.employee,));c.execute('DELETE FROM production_assignment_changes WHERE employee_id=%s',(TransferApplicationTests.employee,));c.execute('DELETE FROM personnel_position_requests');c.execute('DELETE FROM personnel_position_events');c.execute('UPDATE personnel_position_state SET version=0')
   # Business-core fixture only: not evidence of a real DK/reader integration.
   c.execute("UPDATE personnel_settings SET enabled=true,dk_context_verified=true,date_readers_verified=true,legacy_history_policy='LEGACY_WITH_WARNING',creator_user_id=NULL WHERE id=1")
   self.before=c.execute('select to_jsonb(e) from employees e where id=%s',(self.employee,)).fetchone()[0]
   self.related_before={table:c.execute(sql.SQL("select coalesce(jsonb_agg(to_jsonb(t) order by id),'[]'::jsonb) from {} t where employee_id=%s").format(sql.Identifier(table)),(self.employee,)).fetchone()[0] for table in ('employee_movements','rail_tickets','daily_control_results','employee_assignments')}
 def tearDown(self):
  with connect() as c:
   self.assertEqual(c.execute('select to_jsonb(e) from employees e where id=%s',(self.employee,)).fetchone()[0],self.before)
   for table,values in self.related_before.items():
    actual=c.execute(sql.SQL("select coalesce(jsonb_agg(to_jsonb(t) order by id),'[]'::jsonb) from {} t where employee_id=%s").format(sql.Identifier(table)),(self.employee,)).fetchone()[0]
    self.assertEqual(actual,values,table)
    self.assertTrue(values,'Expected non-empty related fixture '+table)
 def payload(self,pid=None,day=None,version=0,rid=None):
  return dict(position_id=pid or self.positions[1],effective_on=str(day or TODAY),reason='Integration fixture',request_id=str(rid or uuid.uuid4()),expected_version=version)
 def post(self,payload,role='transfer_tech',csrf=True):
  code,_,raw=request(self.base,'POST',self.tokens.get(role),payload,csrf);return code,json.loads(raw)
 def hist(self):return request(self.base,token=self.tokens['transfer_office'])
 def resolve(self,day):
  with connect() as c:return c.execute('select personnel_position_at(%s,%s)',(self.employee,day)).fetchone()[0]
 def test_01_schema_and_unknown_baseline(self):
  self.assertEqual(self.resolve(BASE-timedelta(days=1))['status'],'UNKNOWN_HISTORY')
  self.assertTrue(self.resolve(BASE)['effective_start_unknown'])
 def test_02_actual_http_transfer_and_periods(self):
  code,body=self.post(self.payload());self.assertEqual(code,200,body)
  self.assertEqual(self.resolve(TODAY)['position_id'],self.positions[1]);self.assertEqual(self.resolve(TODAY-timedelta(days=1))['position_id'],self.positions[0])
  code,_,raw=self.hist();self.assertEqual(code,200);self.assertEqual(len(json.loads(raw)['item']['periods']),2)
 def test_03_future(self):
  day=TODAY+timedelta(days=10);self.assertEqual(self.post(self.payload(day=day))[0],200)
  self.assertEqual(self.resolve(TODAY)['position_id'],self.positions[0]);self.assertEqual(self.resolve(day)['position_id'],self.positions[1])
 def test_04_multiple_and_repeat(self):
  payload=self.payload();a=self.post(payload);b=self.post(payload);self.assertEqual(a,b)
  self.assertEqual(self.post(self.payload(pid=self.positions[2],day=TODAY+timedelta(days=5),version=1))[0],200)
  with connect() as c:self.assertEqual(c.execute('select count(*) from personnel_position_events where employee_id=%s',(self.employee,)).fetchone()[0],2)
 def test_05_payload_conflict(self):
  payload=self.payload();self.assertEqual(self.post(payload)[0],200);payload['position_id']=self.positions[2];self.assertEqual(self.post(payload)[0],409)
 def test_06_stale_and_date_collision(self):
  self.assertEqual(self.post(self.payload())[0],200)
  self.assertEqual(self.post(self.payload(pid=self.positions[2]))[0],409)
  self.assertEqual(self.post(self.payload(pid=self.positions[2],version=1))[0],409)
 def test_07_office_no_write(self):self.assertEqual(self.post(self.payload(),role='transfer_office')[0],403)
 def test_08_session_and_csrf(self):
  self.assertEqual(self.post(self.payload(),role='anonymous')[0],403)
  self.assertEqual(self.post(self.payload(),csrf=False)[0],403)
  self.assertEqual(request(self.base)[0],401)
 def test_09_no_new_correction_permissions(self):
  root=uuid.uuid4();payload=self.payload();payload['reason']='Review attempt'
  for user in self.tokens:
   self.assertEqual(request(self.base+'/'+str(root)+'/corrections','POST',self.tokens[user],payload)[0],403)
 def test_10_transfer_does_not_adopt_directory_rotation(self):
  code,body=self.post(self.payload(pid=self.positions[3]));self.assertEqual(code,200,body)
  self.assertEqual(self.resolve(TODAY)['definition']['work_schedule'],'SHIFT');self.assertEqual(self.resolve(TODAY)['definition']['work_location'],'OBJECT')
 def test_11_unknown_date_and_same_position(self):
  self.assertEqual(self.post(self.payload(day=BASE-timedelta(days=1)))[0],409)
  self.assertEqual(self.post(self.payload(pid=self.positions[0]))[0],409)
 def test_12_atomic_rollback(self):
  c=connect()
  try:
   c.execute('select personnel_transfer(%s,%s,%s,%s,%s,%s,%s,%s)',(self.users['transfer_tech'],self.sessions['transfer_tech'],self.employee,self.positions[1],TODAY,None,uuid.uuid4(),0))
   with self.assertRaises(psycopg.errors.DivisionByZero):c.execute('select 1/0')
   c.rollback()
  finally:c.close()
  self.assertEqual(self.resolve(TODAY)['position_id'],self.positions[0])
 def test_13_direct_patch_blocked(self):
  c=connect()
  try:
   with self.assertRaises(psycopg.errors.CheckViolation):c.execute('update employees set position_id=%s where id=%s',(self.positions[1],self.employee))
   c.rollback()
  finally:c.close()
 def test_14_definition_versions(self):
  old=self.resolve(TODAY-timedelta(days=1))['definition']['name']
  with connect() as c:c.execute('update positions set name=%s where id=%s',('Renamed '+uuid.uuid4().hex,self.positions[0]))
  self.assertEqual(self.resolve(TODAY-timedelta(days=1))['definition']['name'],old)
  self.assertNotEqual(self.resolve(TODAY)['definition']['name'],old)
 def test_15_readonly_history(self):
  from app.access_context import read_only_request
  context=read_only_request.set(True)
  try:self.assertTrue(repo.history(self.employee)['installed'])
  finally:read_only_request.reset(context)
 def test_16_default_gates_are_fail_closed(self):
  with connect() as c:c.execute('update personnel_settings set dk_context_verified=false')
  self.assertEqual(self.post(self.payload())[0],409)
  self.assertFalse(repo.capabilities(auth.current(self.tokens['transfer_tech']))['can_transfer'])
 def test_17_savepoint(self):
  with connect() as c:
   c.execute('savepoint transfer_try');rid=uuid.uuid4();args=(self.users['transfer_tech'],self.sessions['transfer_tech'],self.employee,self.positions[1],TODAY,None,rid,0)
   c.execute('select personnel_transfer(%s,%s,%s,%s,%s,%s,%s,%s)',args);c.execute('rollback to transfer_try');c.execute('select personnel_transfer(%s,%s,%s,%s,%s,%s,%s,%s)',args);c.execute('release transfer_try')
  self.assertEqual(self.resolve(TODAY)['position_id'],self.positions[1])
 def test_18_concurrent_version_conflict(self):
  a=connect();a.execute('select personnel_transfer(%s,%s,%s,%s,%s,%s,%s,%s)',(self.users['transfer_tech'],self.sessions['transfer_tech'],self.employee,self.positions[1],TODAY,None,uuid.uuid4(),0))
  done=threading.Event();out={}
  def writer():
   c=connect();out['pid']=c.info.backend_pid
   try:c.execute('select personnel_transfer(%s,%s,%s,%s,%s,%s,%s,%s)',(self.users['transfer_tech'],self.sessions['transfer_tech'],self.employee,self.positions[2],TODAY+timedelta(days=5),None,uuid.uuid4(),0));c.commit();out['outcome']='COMMIT'
   except psycopg.Error as e:out['sqlstate']=e.sqlstate;c.rollback();out['outcome']='ROLLBACK'
   finally:c.close();done.set()
  t=threading.Thread(target=writer,daemon=True);t.start();locks=[]
  try:
   until=time.monotonic()+2
   with connect() as obs:
    while time.monotonic()<until:
     if out.get('pid'):
      locks=obs.execute("select classid::bigint,objid::bigint,granted from pg_locks where pid=%s and locktype='advisory'",(out['pid'],)).fetchall()
      if any(not x[2] for x in locks):break
     time.sleep(.02)
   self.assertIn((20261017,29,False),locks);self.assertFalse(any(x[2] for x in locks));a.commit()
  finally:a.rollback();a.close();t.join(10)
  self.assertTrue(done.is_set());self.assertEqual(out.get('sqlstate'),'40001')
 def test_19_policies_match_handlers(self):
  from app.auth_policies import policies,routes,identity
  registered={(m,r.path,identity(r)) for r in routes(app) for m in (getattr(r,'methods',None) or ['MOUNT'])}
  self.assertEqual(registered,{(p['method'],p['path'],p['handler']) for p in policies()})
 def test_20_existing_calendar_numeric_invariance_same_graph(self):
  from app.repositories.luvr_calendar import get_calendar_inputs
  from app.services.luvr_calendar import calculate_employee_month
  before=calculate_employee_month(get_calendar_inputs(self.employee),TODAY.year,TODAY.month)
  self.assertEqual(self.post(self.payload())[0],200)
  after=calculate_employee_month(get_calendar_inputs(self.employee),TODAY.year,TODAY.month)
  self.assertEqual(before,after)

 def test_21_session_revoked_before_http(self):
  token=auth.login('transfer_tech',self.password,'temporary-test')
  auth.logout(token)
  code,_,_=request(self.base,'POST',token,self.payload(),auth.csrf(token));self.assertEqual(code,403)
 def test_22_missing_session_cannot_call_sql(self):
  c=connect()
  try:
   with self.assertRaises(psycopg.errors.InsufficientPrivilege):c.execute('select personnel_transfer(%s,%s,%s,%s,%s,%s,%s,%s)',(self.users['transfer_tech'],0,self.employee,self.positions[1],TODAY,None,uuid.uuid4(),0))
   c.rollback()
  finally:c.close()
 def test_23_payload_fields_are_whitelisted(self):
  payload=self.payload();payload['crew_id']=999;self.assertEqual(self.post(payload)[0],422)
 def test_24_public_has_no_command_execute(self):
  with connect() as c:
   rows=c.execute("select proname,coalesce((select bool_or(x.grantee=0 and x.privilege_type='EXECUTE') from aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) x),false) from pg_proc p where pronamespace=current_schema()::regnamespace and proname in ('personnel_position_command','personnel_transfer','personnel_review_transfer')").fetchall()
  self.assertEqual(len(rows),3);self.assertTrue(all(not public for name,public in rows))

 def test_25_current_list_uses_dated_position(self):
  self.assertEqual(self.post(self.payload())[0],200)
  from app.repositories.employees import get_employees
  current=next(e for e in get_employees() if e['id']==self.employee)
  self.assertEqual(current['position_id'],self.positions[1]);self.assertTrue(current['personnel_history_installed'])
 def test_26_ordinary_patch_preserves_legacy_observation(self):
  self.assertEqual(self.post(self.payload())[0],200)
  original=self.before
  try:
   payload={'full_name':original['full_name'],'position_id':self.positions[1],'phone':original['phone'],'crew_id':original['crew_id']}
   code,_,raw=request('/api/employees/'+str(self.employee),'PATCH',self.tokens['transfer_tech'],payload);self.assertEqual(code,200,raw)
   with connect() as c:self.assertEqual(c.execute('select position_id from employees where id=%s',(self.employee,)).fetchone()[0],self.positions[0])
  finally:
   with connect() as c:c.execute('update employees set updated_at=%s where id=%s',(original['updated_at'],self.employee))

 def test_27_transfer_on_observation_date_keeps_original_observation(self):
  try:
   with connect() as c:c.execute('update personnel_position_baselines set known_on=%s where employee_id=%s',(TODAY,self.employee))
   payload=self.payload();payload['source_position_id']=self.positions[0]
   self.assertEqual(self.post(payload)[0],200)
   data=repo.history(self.employee)
   self.assertEqual(data['baseline']['position_id'],self.positions[0]);self.assertTrue(data['baseline']['effective_start_unknown']);self.assertIsNotNone(data['baseline']['definition'])
   self.assertEqual(len(data['periods']),2);self.assertEqual(data['current']['position_id'],self.positions[1])
  finally:
   with connect() as c:c.execute('update personnel_position_baselines set known_on=%s where employee_id=%s',(BASE,self.employee))
 def test_28_original_observation_definition_not_overwritten(self):
  original=repo.history(self.employee)['baseline']['definition']
  with connect() as c:c.execute('update positions set name=%s where id=%s',('Further rename '+uuid.uuid4().hex,self.positions[0]))
  self.assertEqual(repo.history(self.employee)['baseline']['definition'],original)

 def test_29_explicit_creator_correction_and_cancel(self):
  code,first=self.post(self.payload());self.assertEqual(code,200,first)
  with connect() as c:c.execute('update personnel_settings set creator_user_id=%s where id=1',(self.users['transfer_creator'],))
  payload=self.payload(pid=self.positions[2],day=TODAY+timedelta(days=2),version=1);payload['reason']='Correct erroneous personnel transfer'
  root=first['item']['root_id']
  code,_,raw=request(self.base+'/'+root+'/corrections','POST',self.tokens['transfer_creator'],payload);self.assertEqual(code,200,raw)
  self.assertEqual(self.resolve(TODAY)['position_id'],self.positions[0]);self.assertEqual(self.resolve(TODAY+timedelta(days=2))['position_id'],self.positions[2])
  cancel={'position_id':None,'effective_on':None,'reason':'Cancelled with audit retained','request_id':str(uuid.uuid4()),'expected_version':2}
  code,_,raw=request(self.base+'/'+root+'/cancellations','POST',self.tokens['transfer_creator'],cancel);self.assertEqual(code,200,raw)
  history=repo.history(self.employee);self.assertEqual([e['kind'] for e in history['audit']],['TRANSFER','CORRECT','CANCEL'])
  self.assertEqual(history['current']['position_id'],self.positions[0])
 def test_30_creator_does_not_elevate_the_whole_role(self):
  with connect() as c:c.execute('update personnel_settings set creator_user_id=%s where id=1',(self.users['transfer_creator'],))
  self.assertTrue(repo.capabilities(auth.current(self.tokens['transfer_creator']))['can_review'])
  self.assertFalse(repo.capabilities(auth.current(self.tokens['transfer_tech']))['can_review'])
  self.assertFalse(repo.capabilities(auth.current(self.tokens['transfer_office']))['can_review'])
 def test_31_creator_can_transfer(self):
  with connect() as c:c.execute('update personnel_settings set creator_user_id=%s where id=1',(self.users['transfer_creator'],))
  self.assertEqual(self.post(self.payload(),role='transfer_creator')[0],200)

 def acting_payload(self,version=0):
  return dict(position_id=self.positions[4],starts_on=str(TODAY+timedelta(days=1)),ends_on=str(TODAY+timedelta(days=7)),reason='Isolated acting test',request_id=str(uuid.uuid4()),expected_version=version)
 def acting_post(self,payload,path='/acting',role='transfer_tech'):
  status,_,raw=request(self.base+path,'POST',self.tokens[role],payload);return status,json.loads(raw)
 def acting_at(self,day):
  with connect() as c:return c.execute('SELECT personnel_acting_at(%s,%s)',(self.employee,day)).fetchone()[0]
 def end_payload(self,version=1):
  with connect() as c:
   from app.repositories.construction_identity import catalog
   candidates=catalog(c,archive='active');self.assertTrue(candidates)
   entity=candidates[0]['entity_id']
   movement=c.execute("SELECT id FROM employee_movements WHERE employee_id=%s AND movement_type='ARRIVAL' ORDER BY event_datetime DESC LIMIT 1",(self.employee,)).fetchone()[0]
  return dict(ends_on=str(TODAY+timedelta(days=3)),reason='Return to engineering',request_id=str(uuid.uuid4()),expected_version=version,plan=dict(effective_from=str(TODAY+timedelta(days=4)),period_kind='ARRIVAL',arrival_movement_ref=movement,period_start=None,period_end=None,source_kind='MANUAL',source_ticket_id=None,assignment_state='OBJECTS',items=[dict(entity_id=entity)]))
 def test_32_acting_dates_and_main_position_unchanged(self):
  code,body=self.acting_post(self.acting_payload());self.assertEqual(code,200,body)
  self.assertIsNone(self.acting_at(TODAY));self.assertIsNotNone(self.acting_at(TODAY+timedelta(days=1)));self.assertIsNotNone(self.acting_at(TODAY+timedelta(days=7)));self.assertIsNone(self.acting_at(TODAY+timedelta(days=8)))
  self.assertEqual(self.resolve(TODAY+timedelta(days=2))['position_id'],self.positions[0]);self.assertEqual(len(repo.history(self.employee)['acting_audit']),1)
 def test_33_acting_replay_and_changed_payload(self):
  payload=self.acting_payload();a=self.acting_post(payload);self.assertEqual(a[0],200,a);self.assertEqual(self.acting_post(payload),a)
  payload['ends_on']=str(TODAY+timedelta(days=9));self.assertEqual(self.acting_post(payload)[0],409)
 def test_34_overlap_and_stale_history(self):
  self.assertEqual(self.acting_post(self.acting_payload())[0],200)
  self.assertEqual(self.acting_post(self.acting_payload())[0],409)
  self.assertEqual(self.acting_post(self.acting_payload(version=1))[0],409)
 def test_35_office_and_review_permissions(self):
  self.assertEqual(self.acting_post(self.acting_payload(),role='transfer_office')[0],403)
  code,body=self.acting_post(self.acting_payload());self.assertEqual(code,200,body)
  change=dict(ends_on=str(TODAY+timedelta(days=8)),reason='Correction',request_id=str(uuid.uuid4()),expected_version=1)
  self.assertEqual(self.acting_post(change,'/acting/'+body['item']['root_id']+'/end-date')[0],403)
 def test_36_end_with_existing_plan_writer_is_atomic_and_idempotent(self):
  code,first=self.acting_post(self.acting_payload());self.assertEqual(code,200,first)
  payload=self.end_payload();path='/acting/'+first['item']['root_id']+'/end';code,body=self.acting_post(payload,path);self.assertEqual(code,200,body)
  self.assertEqual(self.acting_post(payload,path),(code,body));self.assertIsNone(self.acting_at(TODAY+timedelta(days=4)))
  with connect() as c:
   self.assertEqual(c.execute('SELECT count(*) FROM production_assignment_changes WHERE employee_id=%s',(self.employee,)).fetchone()[0],1)
   self.assertEqual(c.execute('SELECT kind,plan_change_id FROM personnel_acting_events WHERE employee_id=%s ORDER BY version DESC LIMIT 1',(self.employee,)).fetchone(),('END',body['item']['plan_change_id']))
 def test_37_stale_end_rolls_back_new_plan(self):
  code,first=self.acting_post(self.acting_payload());self.assertEqual(code,200,first)
  payload=self.end_payload(version=0);self.assertEqual(self.acting_post(payload,'/acting/'+first['item']['root_id']+'/end')[0],409)
  with connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM production_assignment_changes WHERE employee_id=%s',(self.employee,)).fetchone()[0],0)
  self.assertIsNotNone(self.acting_at(TODAY+timedelta(days=7)))
 def test_38_invalid_object_leaves_acting_unchanged(self):
  code,first=self.acting_post(self.acting_payload());self.assertEqual(code,200,first)
  payload=self.end_payload();payload['plan']['items']=[dict(entity_id=999999999)]
  self.assertIn(self.acting_post(payload,'/acting/'+first['item']['root_id']+'/end')[0],(404,409))
  self.assertIsNotNone(self.acting_at(TODAY+timedelta(days=7)))
 def test_39_creator_revises_without_erasing_audit(self):
  code,first=self.acting_post(self.acting_payload());self.assertEqual(code,200,first)
  with connect() as c:c.execute('UPDATE personnel_settings SET creator_user_id=%s',(self.users['transfer_creator'],))
  base='/acting/'+first['item']['root_id'];payload=dict(ends_on=str(TODAY+timedelta(days=10)),reason='Correct end with audit',request_id=str(uuid.uuid4()),expected_version=1)
  code,body=self.acting_post(payload,base+'/end-date',role='transfer_creator');self.assertEqual(code,200,body)
  payload=dict(reason='Cancel erroneous appointment',request_id=str(uuid.uuid4()),expected_version=2)
  code,body=self.acting_post(payload,base+'/cancel',role='transfer_creator');self.assertEqual(code,200,body)
  self.assertIsNone(self.acting_at(TODAY+timedelta(days=3)));self.assertEqual([a['kind'] for a in repo.history(self.employee)['acting_audit']],['ASSIGN','CHANGE_END','CANCEL'])
 def test_40_existing_facts_prevent_historical_reinterpretation(self):
  payload=self.acting_payload();payload['starts_on']=str(TODAY)
  self.assertEqual(self.acting_post(payload)[0],409)
 def test_41_actual_context_luvr_and_matrix(self):
  code,body=self.acting_post(self.acting_payload());self.assertEqual(code,200,body)
  from app.repositories.luvr_calendar import get_calendar_inputs
  from app.services.luvr_calendar import calculate_employee_month
  from app.services.personnel_positions import split_luvr_rows,dated_personnel
  from app.services.luvr_month import calendar_totals,calendar_day_totals
  inputs=get_calendar_inputs(self.employee);original=calculate_employee_month(inputs,TODAY.year,TODAY.month)
  rows=split_luvr_rows(original,inputs)
  self.assertEqual(sum(calendar_totals(r['days'])['work_days_total'] for r in rows),calendar_totals(original['days'])['work_days_total'])
  self.assertEqual(calendar_day_totals(rows,TODAY.year,TODAY.month),calendar_day_totals([original],TODAY.year,TODAY.month))
  target=TODAY+timedelta(days=2);dated=dated_personnel(inputs,target)
  self.assertFalse(dated['engineering_report_required']);self.assertTrue(dated['display_position_name'].startswith('И.О. '))
  # Actual matrix accepts the same calendar/context with its original assignment projector.
  from app.repositories.production_assignments import _inputs
  from app.services.production_matrix import employee_matrix
  with connect() as c:production=_inputs(c,self.employee)
  data={**inputs,'position_id':self.positions[0],'requires_daily_report':True,'production':production,'matrix_overrides':[]}
  matrix=employee_matrix(data,{table:{} for table in ('construction_objects','construction_subobjects','po_types','object_categories')},TODAY.year,TODAY.month)
  cells=[r['cells'].get(str(target)) for r in matrix['rows'] if str(target) in r['cells']]
  self.assertTrue(cells);self.assertTrue(all(not c['report_required'] for c in cells));self.assertTrue(all(c['position_name'].startswith('И.О. ') for c in cells))
 def test_42_planning_context_uses_real_arrival(self):
  code,_,raw=request(self.base+'/planning-context?on_day='+str(TODAY+timedelta(days=4)),token=self.tokens['transfer_office']);self.assertEqual(code,200,raw)
  self.assertTrue(json.loads(raw)['item']['periods'])
 def test_43_movement_and_transfer_share_global_version(self):
  self.assertEqual(self.acting_post(self.acting_payload())[0],200)
  self.assertEqual(self.post(self.payload())[0],409)
  self.assertEqual(self.post(self.payload(version=1))[0],200)

 def test_44_backdate_uses_previous_day_not_today(self):
  self.assertEqual(self.post(self.payload(day=TODAY-timedelta(days=10)))[0],200)
  self.assertEqual(self.post(self.payload(pid=self.positions[2],day=TODAY-timedelta(days=5),version=1))[0],200)
  with connect() as c:
   row=c.execute('SELECT source_position_id,source_on FROM personnel_position_events WHERE employee_id=%s AND version=2',(self.employee,)).fetchone()
  self.assertEqual(row,(self.positions[1],TODAY-timedelta(days=6)))
 def test_45_unknown_predecessor_requires_explicit_catalog_choice(self):
  day=BASE-timedelta(days=5);payload=self.payload(day=day)
  self.assertEqual(self.post(payload)[0],409)
  payload['source_position_id']=self.positions[0]
  code,body=self.post(payload);self.assertEqual(code,200,body)
  self.assertEqual(self.resolve(day-timedelta(days=1))['position_id'],self.positions[0]);self.assertEqual(self.resolve(day)['position_id'],self.positions[1]);self.assertEqual(self.resolve(TODAY)['position_id'],self.positions[1])
  self.assertEqual(self.resolve(day-timedelta(days=2))['status'],'UNKNOWN_HISTORY')
 def test_46_conflicting_following_transfer_is_not_rewritten(self):
  self.assertEqual(self.post(self.payload(pid=self.positions[2],day=TODAY+timedelta(days=10)))[0],200)
  self.assertEqual(self.post(self.payload(day=TODAY+timedelta(days=3),version=1))[0],409)
  self.assertEqual(self.resolve(TODAY+timedelta(days=10))['position_id'],self.positions[2])

 def test_47_ta_transfer_retains_engineering_obligation_without_dictionary_change(self):
  with connect() as c:
   before=c.execute('SELECT requires_daily_report FROM positions WHERE id=16').fetchone()[0]
   c.execute('UPDATE personnel_position_definitions SET known_from=%s WHERE position_id=16',(BASE,))
  code,body=self.post(self.payload(pid=16));self.assertEqual(code,200,body)
  self.assertTrue(self.resolve(TODAY)['definition']['requires_daily_report'])
  with connect() as c:self.assertEqual(c.execute('SELECT requires_daily_report FROM positions WHERE id=16').fetchone()[0],before)
 def test_48_luvr_export_keeps_both_display_rows(self):
  from app.services.luvr_export_table import ordered_employees
  data={'formed':True,'employees':[{'employee_id':1,'row_key':'employee:1','full_name':'Engineer','specialty':'X'},{'employee_id':1,'row_key':'acting:a','full_name':'Engineer','specialty':'X'}]}
  rows=ordered_employees(data,[1,1],['acting:a','employee:1']);self.assertEqual([r['row_key'] for r in rows],['acting:a','employee:1'])
  with self.assertRaises(ValueError):ordered_employees(data,[1])

 def test_49_cancel_cannot_break_later_transfer_source(self):
  code,first=self.post(self.payload());self.assertEqual(code,200,first)
  self.assertEqual(self.post(self.payload(pid=self.positions[2],day=TODAY+timedelta(days=5),version=1))[0],200)
  with connect() as c:c.execute('UPDATE personnel_settings SET creator_user_id=%s',(self.users['transfer_creator'],))
  data={'reason':'Invalidating predecessor must refuse','request_id':str(uuid.uuid4()),'expected_version':2}
  code,_,raw=request(self.base+'/'+first['item']['root_id']+'/cancellations','POST',self.tokens['transfer_creator'],data);self.assertEqual(code,409,raw)
  self.assertEqual(self.resolve(TODAY+timedelta(days=5))['position_id'],self.positions[2]);self.assertEqual(len(repo.history(self.employee)['audit']),2)
 def test_50_return_plan_date_and_empty_objects_are_rejected(self):
  code,first=self.acting_post(self.acting_payload());self.assertEqual(code,200,first)
  data=self.end_payload();data['plan']['effective_from']=str(TODAY+timedelta(days=5))
  self.assertEqual(self.acting_post(data,'/acting/'+first['item']['root_id']+'/end')[0],409)
  data=self.end_payload();data['plan']['items']=[]
  self.assertEqual(self.acting_post(data,'/acting/'+first['item']['root_id']+'/end')[0],422)
  self.assertIsNotNone(self.acting_at(TODAY+timedelta(days=7)))

 def test_51_rollback_refuses_to_erase_recorded_operations(self):
  self.assertEqual(self.post(self.payload())[0],200)
  c=connect()
  try:
   with self.assertRaises(psycopg.errors.RaiseException):c.execute(rollback_sql)
   c.rollback()
  finally:c.close()
  self.assertEqual(len(repo.history(self.employee)['audit']),1)

 def test_52_real_month_readers_deployment_and_vou_projection(self):
  code,body=self.acting_post(self.acting_payload());self.assertEqual(code,200,body)
  from app.repositories.luvr_month import form_month
  form_month(TODAY.year,TODAY.month)
  with connect() as c:c.execute('INSERT INTO luvr_month_employees(year,month,employee_id) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING',(TODAY.year,TODAY.month,self.employee))
  code,_,raw=request(f'/api/luvr/month?year={TODAY.year}&month={TODAY.month}',token=self.tokens['transfer_office']);self.assertEqual(code,200,raw[:200])
  monthly=json.loads(raw)['item'];lanes=[r for r in monthly['employees'] if r['employee_id']==self.employee]
  self.assertEqual(len(lanes),2);self.assertTrue(all(r['row_key'] for r in lanes))
  code,_,raw=request(f'/api/production-matrix?year={TODAY.year}&month={TODAY.month}&employee_id={self.employee}',token=self.tokens['transfer_office']);self.assertEqual(code,200,raw[:200])
  matrix=json.loads(raw)['item'];target=TODAY+timedelta(days=2)
  from app.services.deployment import build_report
  deployed=build_report(target,matrix,{})
  self.assertEqual(deployed['totals']['specialists'],1);self.assertTrue(all(r['position_name'].startswith('И.О.') for r in deployed['rows']))
  # VOU consumes ready matrix shares, never recomputes them. Inspect the acting date only;
  # unrelated synthetic engineer IDs deliberately have no approved VOU mapping.
  from copy import deepcopy
  ready=deepcopy(matrix)
  for employee in ready['employees']:
   for row in employee['rows']:row['cells']={d:cell for d,cell in row['cells'].items() if d==str(target)}
  from app.services.vou_data import prepare_data
  from psycopg.rows import dict_row
  with connect() as c,c.cursor(row_factory=dict_row) as cur:
   cur.execute('SELECT id,name,aos_description FROM positions');positions=cur.fetchall()
   cur.execute('SELECT id,position_id,definition FROM personnel_position_definitions');versions=cur.fetchall()
   for position in positions:position['_definitions']={v['id']:v['definition'] for v in versions if v['position_id']==position['id']}
   cur.execute('SELECT id,name,parent_id,sort_order FROM object_categories');categories=cur.fetchall()
  vou=prepare_data(ready,positions,categories,[])
  expected=sum(cell['share_cents'] for e in ready['employees'] for r in e['rows'] for cell in r['cells'].values())
  self.assertEqual(vou['total_cents'],expected);self.assertGreater(expected,0)
  self.assertNotIn('aos_description',raw.decode());self.assertNotIn('report_description',raw.decode())
 def test_53_multi_object_return_uses_existing_items(self):
  code,first=self.acting_post(self.acting_payload());self.assertEqual(code,200,first)
  payload=self.end_payload()
  with connect() as c:
   from app.repositories.construction_identity import catalog
   choices=catalog(c,archive='active');self.assertGreaterEqual(len(choices),2)
  payload['plan']['items']=[{'entity_id':row['entity_id']} for row in choices[:2]]
  code,body=self.acting_post(payload,'/acting/'+first['item']['root_id']+'/end');self.assertEqual(code,200,body)
  with connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM production_assignment_items WHERE change_id=%s',(body['item']['plan_change_id'],)).fetchone()[0],2)
 def test_54_concurrent_acting_commands_wait_on_d(self):
  c=connect();result={};thread=None
  try:
   payload=self.acting_payload()
   c.execute('SELECT personnel_acting_command(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',(self.users['transfer_tech'],self.sessions['transfer_tech'],self.employee,self.positions[4],payload['starts_on'],payload['ends_on'],payload['reason'],uuid.uuid4(),0,'ASSIGN',None,None,None))
   thread=threading.Thread(target=lambda:result.update(response=self.acting_post(self.acting_payload())),daemon=True);thread.start()
   until=time.monotonic()+2;waiter=None
   while time.monotonic()<until:
    with connect() as observer:
     waiter=observer.execute("SELECT pid FROM pg_locks WHERE locktype='advisory' AND classid=20261017 AND objid=29 AND NOT granted").fetchone()
     if waiter:
      held=observer.execute("SELECT classid::bigint,objid::bigint FROM pg_locks WHERE pid=%s AND locktype='advisory' AND granted",(waiter[0],)).fetchall()
      self.assertNotIn((20261007,1601),held);self.assertNotIn((20261013,24),held);break
    time.sleep(.025)
   self.assertIsNotNone(waiter);c.commit();thread.join(5);self.assertFalse(thread.is_alive());self.assertEqual(result['response'][0],409)
  finally:
   c.rollback();c.close()
   if thread:thread.join(5)

 def test_55_fact_received_after_acting_is_preserved_without_report_obligation(self):
  code,body=self.acting_post(self.acting_payload());self.assertEqual(code,200,body)
  target=TODAY+timedelta(days=2);fid=None
  try:
   with connect() as c:
    fid=c.execute("INSERT INTO daily_control_results(report_date,employee_id,object_id,subobject_id,entity_id,po_id,category_id,subcontractor_id,source_file,source_sha256) SELECT %s,employee_id,object_id,subobject_id,entity_id,po_id,category_id,subcontractor_id,'isolated_optional_acting_report.docx',%s FROM daily_control_results WHERE employee_id=%s LIMIT 1 RETURNING id",(target,uuid.uuid4().hex+uuid.uuid4().hex,self.employee)).fetchone()[0]
    from app.repositories.luvr_calendar import CALENDAR_SELECT,decode_calendar_inputs
    from app.repositories.personnel_transfers import attach_context
    from app.repositories.production_assignments import _inputs
    from psycopg.rows import dict_row
    with c.cursor(row_factory=dict_row) as cur:cur.execute(CALENDAR_SELECT+' WHERE e.id=%s',(self.employee,));employee=decode_calendar_inputs(cur.fetchone())
    attach_context(c,[employee]);employee.update(position_id=self.positions[0],requires_daily_report=True,production=_inputs(c,self.employee),matrix_overrides=[])
   from app.services.production_matrix import employee_matrix
   matrix=employee_matrix(employee,{table:{} for table in ('construction_objects','construction_subobjects','po_types','object_categories')},TODAY.year,TODAY.month)
   cells=[r['cells'][str(target)] for r in matrix['rows'] if str(target) in r['cells']]
   facts=[cell for cell in cells if cell.get('source_fact_id')==fid];self.assertEqual(len(facts),1);self.assertFalse(facts[0]['report_required']);self.assertTrue(facts[0]['report_received']);self.assertNotIn('FACT_OUTSIDE_KNOWN_PERIOD',facts[0]['warnings'])
  finally:
   if fid:
    with connect() as c:c.execute('DELETE FROM daily_control_results WHERE id=%s',(fid,))

stream=io.StringIO();result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(TransferApplicationTests))
browser={'success':False,'not_run':True}
if result.wasSuccessful() and not result.skipped:
 import socket,subprocess,shutil
 import uvicorn
 from app.auth_ui import create_auth_ui
 with connect() as c:
  c.execute('DELETE FROM personnel_acting_events');c.execute('DELETE FROM production_assignment_items WHERE change_id IN (SELECT id FROM production_assignment_changes WHERE employee_id=%s)',(TransferApplicationTests.employee,));c.execute('DELETE FROM production_assignment_changes WHERE employee_id=%s',(TransferApplicationTests.employee,));c.execute('DELETE FROM personnel_position_requests');c.execute('DELETE FROM personnel_position_events');c.execute('UPDATE personnel_position_state SET version=0')
  c.execute("UPDATE personnel_settings SET enabled=true,dk_context_verified=true,date_readers_verified=true,legacy_history_policy='LEGACY_WITH_WARNING',creator_user_id=NULL")
  position_name=c.execute('select name from positions where id=%s',(TransferApplicationTests.positions[1],)).fetchone()[0]
  c.execute('update personnel_settings set creator_user_id=%s',(TransferApplicationTests.users['transfer_creator'],))
 with socket.socket() as sock:sock.bind(('127.0.0.1',0));webport=sock.getsockname()[1]
 with socket.socket() as sock:sock.bind(('127.0.0.1',0));debugport=sock.getsockname()[1]
 assert webport not in (8000,8001) and debugport not in (8000,8001)
 server=uvicorn.Server(uvicorn.Config(create_auth_ui(app,auth),host='127.0.0.1',port=webport,log_level='error',access_log=False))
 thread=threading.Thread(target=server.run,daemon=True);thread.start();chrome=None;profile=Path(config['run'])/'browser-profile'
 try:
  until=time.monotonic()+6
  while not server.started and time.monotonic()<until:time.sleep(.05)
  if not server.started:raise RuntimeError('Own application server did not start')
  chrome=subprocess.Popen(['C:/Program Files/Google/Chrome/Application/chrome.exe','--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--disable-background-networking','--remote-debugging-port='+str(debugport),'--user-data-dir='+str(profile),'about:blank'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
  time.sleep(1)
  browser_config={'debug_port':debugport,'url':'http://127.0.0.1:'+str(webport),'password':TransferApplicationTests.password,'employee':TransferApplicationTests.employee,'position':TransferApplicationTests.positions[1],'position_name':position_name,'correction_position':TransferApplicationTests.positions[2],'original_position':TransferApplicationTests.positions[0],'today':str(TODAY),'acting_position':TransferApplicationTests.positions[4],'acting_start':str(TODAY+timedelta(days=1)),'acting_end':str(TODAY+timedelta(days=7)),'acting_early_end':str(TODAY+timedelta(days=3)),'run':config['run']}
  response=subprocess.run(['node',str(ROOT/'tests/browser/personnel_transfers.cjs')],input=json.dumps(browser_config),capture_output=True,text=True,encoding='utf-8',timeout=75)
  if response.returncode:browser={'success':False,'error':response.stderr.replace(TransferApplicationTests.password,'[redacted]')}
  else:browser=json.loads((Path(config['run'])/'browser.json').read_text(encoding='utf-8'))
 except Exception as error:browser={'success':False,'error':type(error).__name__+': '+str(error)}
 finally:
  server.should_exit=True;thread.join(8)
  if chrome:
   try:chrome.wait(timeout=4)
   except subprocess.TimeoutExpired:chrome.terminate();chrome.wait(timeout=4)
  if profile.resolve().parent!=Path(config['run']).resolve():raise RuntimeError('Invalid own profile directory')
  if profile.exists():shutil.rmtree(profile)
  browser['own_server_stopped']=not thread.is_alive()
success=result.wasSuccessful() and not result.skipped and browser['success']
print(json.dumps({'success':success,'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),'test_log':stream.getvalue(),'browser':browser,'scope':'real app routes/repository/migration; synthetic business fixture enables acceptance flags only for core tests','source_credentials_absent_on_entry':True,'driver_endpoint_barrier':True,'pre_activation_rollback_verified':rollback_verified,'not_verified':['Creator identity missing','dated report readers','new signed DK context','production deployment']},ensure_ascii=False))
raise SystemExit(0 if success else 1)
