"""Step45: scoped capabilities, trusted auth role, bounded gate/revocation schedules."""
import os,unittest,uuid,secrets,threading,time,json,copy
from pathlib import Path
import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
from app.services.user_auth import AuthService,AuthDenied
from test_dk_service_prototype import DKServiceTests
from scripts import dk_transaction_prototype as proto
from scripts.auth_command_proof_prototype import CalendarConnection
if os.getenv('AUTH_ISOLATED_WORKER')!='1':raise RuntimeError('Owned worker only')
RECORDS=[];TOKENS=[];BUSINESS_QUERIES=0
class BusinessConnection(psycopg.Connection):
 def execute(self,q,params=None,**kw):
  global BUSINESS_QUERIES
  if params is not None and any(t in repr(params) for t in TOKENS):raise AssertionError('Original session bearer attempted in business SQL')
  BUSINESS_QUERIES+=1;return super().execute(q,params,**kw)
class AuthConnection(psycopg.Connection):
 def execute(self,q,params=None,**kw):
  if isinstance(q,str) and q.startswith("UPDATE auth_sessions SET revoked_at=now(),revoked_reason='REVOKED' WHERE user_id=%s"):
   return super().execute('SELECT auth_proof.revoke_user_sessions(%s)',params,**kw)
  return super().execute(q,params,**kw)
class ProofTests(unittest.TestCase):
 config=None;events=DKServiceTests.events
 def dbconnect(self,who='fixture',peer=False):
  z=self.config
  user,pw,cls={'fixture':(z['role'],z['password'],psycopg.Connection),'business':(z['closed_role'],z['closed_password'],BusinessConnection),'auth':(z['auth_role'],z['auth_password'],AuthConnection)}[who]
  c=cls.connect(host='127.0.0.1',port=z['port'],dbname=z['databases']['stage45_peer' if peer else 'stage45'],user=user,password=pw,connect_timeout=3,options='-c search_path=test_construction_identity_stage46 -c lock_timeout=3000 -c statement_timeout=7000')
  if who=='business' and hasattr(self,'opened'):self.opened.append(c)
  return c
 def fixture_connection(self):return self.dbconnect()
 def connect(self):return self.dbconnect('business')
 @classmethod
 def setUpClass(cls):
  class LocalAuth(AuthService):
   def connect(s):
    c=cls().dbconnect('auth');assert c.info.dbname==cls.config['databases']['stage45'];return c
  cls.service=LocalAuth();cls.pw=secrets.token_urlsafe(24);cls.encoded=cls.service.hash_password(cls.pw);assert cls.encoded.startswith('$argon2id$')
 @classmethod
 def tearDownClass(cls):
  RECORDS.append({'kind':'original_bearer_business_query_guard','queries':BUSINESS_QUERIES,'raw_bearer_transmissions':0})
  cls.service=None;cls.pw=None;cls.encoded=None;TOKENS.clear()
 def setUp(self):
  self.opened=[];self.mode='admission'
  with self.fixture_connection() as f:f.execute("SELECT auth_proof.set_policy('admission')")
  DKServiceTests.setUp(self);self.users=[];self.logins=[];self.tokens=[]
  with self.fixture_connection() as c:
   self.name=c.execute('SELECT full_name FROM employees WHERE id=%s',(self.ids[0],)).fetchone()[0]
   for eid,role in zip(self.ids,['SYSTEM_TECHNICIAN','OFFICE_MANAGER']):
    login='proof45_'+uuid.uuid4().hex;self.logins.append(login)
    uid=c.execute('INSERT INTO auth_users(login,employee_id,password_hash,is_blocked) VALUES(%s,%s,%s,false) RETURNING id',(login,eid,self.encoded)).fetchone()[0];self.users.append(uid)
    c.execute('INSERT INTO auth_user_roles SELECT %s,id FROM auth_roles WHERE code=%s',(uid,role))
  self.tokens=[self.service.login(login,self.pw,uuid.uuid4().hex) for login in self.logins];TOKENS[:]=self.tokens
 def tearDown(self):
  for c in self.opened:
   if not c.closed:c.rollback();c.close()
  log=Path(self.config['step45_log']).read_text(encoding='utf-8',errors='replace');self.assertTrue(all(v not in log for v in self.tokens+[self.pw]))
  with self.fixture_connection() as c:
   c.execute('DELETE FROM auth_security_events WHERE subject_user_id=ANY(%s) OR actor_user_id=ANY(%s)',(self.users,self.users));c.execute('DELETE FROM auth_sessions WHERE user_id=ANY(%s)',(self.users,));c.execute('DELETE FROM auth_user_roles WHERE user_id=ANY(%s)',(self.users,));c.execute('DELETE FROM auth_users WHERE id=ANY(%s)',(self.users,))
  DKServiceTests.tearDown(self);TOKENS.clear()
 def begin(self,c,op='employee.name',name=None,rid=None,mode='admission',ttl=15):
  if mode!=self.mode:
   with self.fixture_connection() as f:f.execute('SELECT auth_proof.set_policy(%s)',(mode,))
   self.mode=mode
  rid=rid or uuid.uuid4();payload={'employee_id':self.ids[0]}
  if op=='employee.name':payload['name']=self.name+' proof' if name is None else name
  ch=c.execute('SELECT auth_proof.begin_command(%s,%s,%s,%s,%s)',(op,Jsonb(payload),rid,mode,ttl)).fetchone()[0];return ch
 def issue(self,ch,who=0):
  self.service.current(self.tokens[who])
  with self.dbconnect('auth') as a:return a.execute('SELECT auth_proof.issue(%s,%s,%s)',(AuthService.digest(self.tokens[who]),Jsonb(ch['context']),bytes.fromhex(ch['mac']))).fetchone()[0]
 def write(self,c,ch,cap,name=None,rid=None,eid=None):
  return c.execute('SELECT auth_proof.employee_name(%s,%s,%s,%s,%s)',(eid or self.ids[0],ch['context']['payload']['name'] if name is None else name,rid or uuid.UUID(ch['context']['request_id']),Jsonb(cap['proof']),bytes.fromhex(cap['mac']))).fetchone()[0]
 def read(self,c,ch,cap):return c.execute('SELECT auth_proof.employee_read(%s,%s,%s,%s)',(self.ids[0],uuid.UUID(ch['context']['request_id']),Jsonb(cap['proof']),bytes.fromhex(cap['mac']))).fetchone()[0]
 def sign(self,c,ch):return proto.register(CalendarConnection(c,self.key,ch['canonical']),self.key)
 def unchanged(self,n=4):
  with self.fixture_connection() as c:self.assertEqual(c.execute('SELECT full_name FROM employees WHERE id=%s',(self.ids[0],)).fetchone()[0],self.name)
  self.assertEqual(len(self.events()),n)
 def deny(self,q,args=(),who='business',state='42501'):
  with self.dbconnect(who) as c:
   with self.assertRaises(psycopg.Error) as ctx:c.execute(q,args)
   self.assertEqual(ctx.exception.sqlstate,state)
 def wait(self,pid,key=None):
  end=time.monotonic()+2.5
  while time.monotonic()<end:
   with self.fixture_connection() as c:rows=c.execute('SELECT locktype,classid,objid,mode,granted FROM pg_locks WHERE pid=%s AND NOT granted',(pid,)).fetchall()
   if rows and (key is None or any(r[1:3]==key for r in rows)):return rows
   time.sleep(.02)
  self.fail('Bounded lock wait not observed')
 def test_01_both_roles_read_one_exact_card(self):
  for user in [0,1]:
   with self.connect() as c:
    ch=self.begin(c,'employee.read');cap=self.issue(ch,user);self.assertEqual(self.read(c,ch,cap)['full_name'],self.name)
    self.assertFalse(c.execute("SELECT EXISTS(SELECT 1 FROM pg_locks WHERE pid=pg_backend_pid() AND locktype='advisory')").fetchone()[0])
 def test_02_engineer_write_office_issue_denied(self):
  with self.connect() as c:
   ch=self.begin(c)
   with self.assertRaises(psycopg.errors.InsufficientPrivilege):self.issue(ch,1)
   cap=self.issue(ch);self.write(c,ch,cap);self.sign(c,ch)
  self.assertEqual(len(self.events()),4)
 def test_03_forged_mac_and_session_claims(self):
  with self.connect() as c:
   ch=self.begin(c);cap=self.issue(ch);c.execute('SAVEPOINT attacks')
   for mutate in ['mac','user_id','session_id','credential_version']:
    bad=copy.deepcopy(cap)
    if mutate=='mac':bad['mac']='00'*32
    else:bad['proof'][mutate]+=1
    with self.assertRaises(psycopg.errors.InsufficientPrivilege):self.write(c,ch,bad)
    c.execute('ROLLBACK TO attacks')
   c.rollback()
  self.unchanged()
 def test_04_payload_request_employee_operation_tamper(self):
  with self.connect() as c:
   ch=self.begin(c);cap=self.issue(ch);c.execute('SAVEPOINT attacks')
   for kwargs in [{'name':self.name+' other'},{'rid':uuid.uuid4()},{'eid':self.ids[1]}]:
    with self.assertRaises(psycopg.errors.InsufficientPrivilege):self.write(c,ch,cap,**kwargs)
    c.execute('ROLLBACK TO attacks')
   with self.assertRaises(psycopg.errors.InsufficientPrivilege):self.read(c,ch,cap)
   c.rollback()
  self.unchanged()
 def test_05_replay_same_transaction_consumed(self):
  with self.connect() as c:
   ch=self.begin(c);cap=self.issue(ch);self.write(c,ch,cap);c.execute('SAVEPOINT used')
   with self.assertRaises(psycopg.errors.InsufficientPrivilege):self.write(c,ch,cap)
   c.execute('ROLLBACK TO used');self.sign(c,ch)
 def test_06_other_transaction_and_pid_replay(self):
  c=self.connect();ch=self.begin(c);cap=self.issue(ch);c.rollback();c.close()
  with self.connect() as b:
   self.begin(b)
   with self.assertRaises(psycopg.errors.InsufficientPrivilege):self.write(b,ch,cap)
   b.rollback()
  self.unchanged()
 def test_07_cross_database_same_key_clone(self):
  c=self.connect();ch=self.begin(c);cap=self.issue(ch)
  try:
   with self.dbconnect('business',peer=True) as peer:
    self.begin(peer)
    with self.assertRaises(psycopg.errors.InsufficientPrivilege):self.write(peer,ch,cap)
    peer.rollback()
   with self.dbconnect('auth',peer=True) as a:
    with self.assertRaises(psycopg.errors.InsufficientPrivilege):a.execute('SELECT auth_proof.issue(%s,%s,%s)',(AuthService.digest(self.tokens[0]),Jsonb(ch['context']),bytes.fromhex(ch['mac'])))
  finally:c.rollback();c.close()
 def test_08_expired_proof_and_expired_challenge(self):
  with self.connect() as c:
   ch=self.begin(c,ttl=1);cap=self.issue(ch);time.sleep(1.1)
   with self.assertRaises(psycopg.errors.InsufficientPrivilege):self.write(c,ch,cap)
   c.rollback()
  with self.assertRaises(psycopg.errors.InsufficientPrivilege):self.issue(ch)
  self.unchanged()
 def test_09_revoked_before_consumption(self):
  with self.connect() as c:
   ch=self.begin(c);cap=self.issue(ch);self.service.revoke_all(self.users[0])
   with self.assertRaises(psycopg.errors.InsufficientPrivilege):self.write(c,ch,cap)
   c.rollback()
  self.unchanged()
 def test_10_blocked_and_credentials_invalidated(self):
  for operation in ['block_user','bump_credentials']:
   with self.connect() as c:
    ch=self.begin(c);cap=self.issue(ch)
    with self.fixture_connection() as a:a.execute('SELECT auth_proof.'+operation+'(%s)',(self.users[0],))
    with self.assertRaises(psycopg.errors.InsufficientPrivilege):self.write(c,ch,cap)
    c.rollback()
   with self.fixture_connection() as a:
    a.execute('UPDATE auth_users SET is_blocked=false WHERE id=%s',(self.users[0],));a.execute('UPDATE auth_sessions SET credential_version=(SELECT credential_version FROM auth_users WHERE id=%s) WHERE user_id=%s',(self.users[0],self.users[0]))
  self.unchanged()
 def test_11_challenge_tamper_and_closed_issuer(self):
  with self.connect() as c:
   ch=self.begin(c);bad=copy.deepcopy(ch['context']);bad['payload']['name']=self.name+' altered'
   with self.dbconnect('auth') as a:
    with self.assertRaises(psycopg.errors.InsufficientPrivilege):a.execute('SELECT auth_proof.issue(%s,%s,%s)',(AuthService.digest(self.tokens[0]),Jsonb(bad),bytes.fromhex(ch['mac'])))
   c.rollback()
  self.deny('SELECT auth_proof.issue(%s,%s,%s)',('0'*64,Jsonb(ch['context']),bytes.fromhex(ch['mac'])))
 def test_12_native_privileges_keys_and_public(self):
  for who in ['business','auth']:
   for q in ['SELECT * FROM auth_proof.key','SELECT * FROM auth_proof.state','SELECT * FROM dk_service.signing_key','SELECT auth_proof.mac(\'x\')','SELECT closed_write.employee(1,\'x\')','UPDATE employees SET full_name=full_name WHERE false','DELETE FROM production_matrix_dk WHERE false','CREATE TEMP TABLE x(id int)','CREATE TABLE public.x(id int)']:self.deny(q,who=who)
  self.deny('SELECT full_name FROM employees',who='auth')
  self.deny('UPDATE auth_sessions SET revoked_at=now() WHERE false',who='auth')
  self.deny('SELECT auth_proof.block_user(1)',who='auth')
  self.deny('SELECT auth_command.employee_read(%s,%s)',('not-a-secret',self.ids[0]))
  with self.connect() as c:
   rows=c.execute("SELECT p.oid,has_function_privilege(p.oid,'EXECUTE') FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='pg_catalog' AND p.proname LIKE 'pg_%advisory%'").fetchall();self.assertEqual(len(rows),21);self.assertTrue(all(not x[1] for x in rows))
   self.assertEqual(c.execute('SELECT count(*) FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname=current_user)').fetchone()[0],0)
  for who in ['business','auth']:
   with self.dbconnect(who) as c:
    self.assertEqual(c.execute('SELECT rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=current_user').fetchone(),(False,)*5)
  RECORDS.append({'kind':'trusted_roles','auth_login_uses_dedicated_minimal_role':True,'business_has_no_auth_issuer_or_keys':True,'auth_role_can_mint_sessions_if_compromised':True})
 def test_13_auth_proof_cannot_forge_dk_read_permit_or_hmac(self):
  with self.assertRaises(psycopg.errors.InsufficientPrivilege):
   with self.connect() as c:
    ch=self.begin(c);cap=self.issue(ch);self.write(c,ch,cap);c.execute('SELECT auth_proof.register(%s,%s)',([],bytes.fromhex(cap['mac'])))
  self.unchanged()
  with self.connect() as c:
   ch=self.begin(c);cap=self.issue(ch);self.write(c,ch,cap)
   with self.assertRaises(psycopg.errors.InsufficientPrivilege):c.execute('SELECT auth_proof.calendar_row(%s,%s)',(self.ids[0],bytes.fromhex(cap['mac'])))
   c.rollback()
  self.unchanged()
 def test_14_request_id_new_proof_idempotent_and_conflict(self):
  rid=uuid.uuid4()
  with self.connect() as c:ch=self.begin(c,rid=rid);cap=self.issue(ch);v=self.write(c,ch,cap);self.sign(c,ch)
  with self.fixture_connection() as f:stamp=f.execute('SELECT updated_at FROM employees WHERE id=%s',(self.ids[0],)).fetchone()[0]
  with self.connect() as c:
   ch=self.begin(c,rid=rid);cap=self.issue(ch);self.assertEqual(self.write(c,ch,cap),v)
  with self.fixture_connection() as f:self.assertEqual(f.execute('SELECT updated_at FROM employees WHERE id=%s',(self.ids[0],)).fetchone()[0],stamp)
  with self.assertRaises(psycopg.errors.InvalidParameterValue):
   with self.connect() as c:ch=self.begin(c,rid=rid,name=self.name+' newpayload');cap=self.issue(ch);self.write(c,ch,cap)
 def test_15_raw_commit_still_requires_dk(self):
  with self.assertRaises(psycopg.errors.InsufficientPrivilege):
   with self.connect() as c:ch=self.begin(c);cap=self.issue(ch);self.write(c,ch,cap);c.execute("SELECT set_config('tehresurs.dk_calendar_dirty','0',true)");c.execute('COMMIT')
  self.unchanged()
 def test_16_rollback_restores_nonce_consumption_branch(self):
  with self.connect() as c:
   ch=self.begin(c);cap=self.issue(ch);c.execute('SAVEPOINT branch');self.write(c,ch,cap);self.sign(c,ch);c.execute('SET CONSTRAINTS ALL IMMEDIATE');c.execute('ROLLBACK TO branch');c.execute('RELEASE branch');c.execute('SET CONSTRAINTS ALL DEFERRED');self.write(c,ch,cap);self.sign(c,ch)
  RECORDS.append({'kind':'subtransaction_replay_semantics','rollback_restores_consumption':True,'same_exact_capability_can_retry_rolled_back_branch':True,'two_committed_effects':False})
 def test_17_real_cleanup_error_rollback_then_commit(self):
  with self.fixture_connection() as f:f.execute("UPDATE employee_luvr_day_overrides SET value='TRAVEL' WHERE employee_id=%s AND work_date=%s",(self.ids[0],self.a))
  with self.assertRaises(psycopg.errors.DivisionByZero):
   with self.connect() as c:ch=self.begin(c);cap=self.issue(ch);self.write(c,ch,cap);self.sign(c,ch);c.execute('SET CONSTRAINTS ALL IMMEDIATE');c.execute('SELECT 1/0')
  self.unchanged()
  with self.connect() as c:ch=self.begin(c);cap=self.issue(ch);self.write(c,ch,cap);self.sign(c,ch)
  self.assertEqual(len(self.events()),3);self.assertNotIn((self.ids[0],self.a),self.events())
 def test_18_one_domain_sealed_and_no_read_upgrade(self):
  with self.connect() as c:
   ch=self.begin(c,'employee.read');cap=self.issue(ch,1);self.read(c,ch,cap);c.execute('SAVEPOINT read')
   with self.assertRaises(psycopg.errors.InsufficientPrivilege):self.begin(c)
   c.execute('ROLLBACK TO read');self.assertFalse(c.execute("SELECT EXISTS(SELECT 1 FROM pg_locks WHERE pid=pg_backend_pid() AND locktype='advisory')").fetchone()[0]);c.rollback()
  with self.connect() as c:
   ch=self.begin(c);cap=self.issue(ch);self.write(c,ch,cap);self.sign(c,ch);c.execute('SET CONSTRAINTS ALL IMMEDIATE');c.execute('SAVEPOINT sealed')
   with self.assertRaises(psycopg.errors.InsufficientPrivilege):self.begin(c)
   c.execute('ROLLBACK TO sealed');c.execute('SET CONSTRAINTS ALL DEFERRED')
 def test_19_admission_cutoff_immediate_revoke_commit(self):
  with self.connect() as c:
   ch=self.begin(c);cap=self.issue(ch);self.write(c,ch,cap);self.sign(c,ch);c.execute('SET CONSTRAINTS ALL IMMEDIATE');self.service.revoke_all(self.users[0])
  RECORDS.append({'kind':'admission_semantics','schedule':'IMMEDIATE -> committed revocation -> COMMIT','business_commit':True,'revocation_affects_already_admitted':False})
 def revoke_actor(self,out,ready,done):
  try:
   with self.dbconnect('auth') as a:
    out['pid']=a.info.backend_pid;ready.set();a.execute('SELECT auth_proof.revoke_user_sessions(%s)',(self.users[0],))
   out['result']='COMMIT'
  except psycopg.Error as e:out['result']=e.sqlstate
  finally:done.set()
 def test_20_serialized_immediate_revocation_waits_commit(self):
  c=self.connect();out={};ready=threading.Event();done=threading.Event();t=None
  try:
   ch=self.begin(c,mode='serialized');cap=self.issue(ch);self.write(c,ch,cap);self.sign(c,ch);c.execute('SET CONSTRAINTS ALL IMMEDIATE')
   t=threading.Thread(target=self.revoke_actor,args=(out,ready,done));t.start();self.assertTrue(ready.wait(3));wait=self.wait(out['pid'],(20261020,45));self.assertFalse(done.is_set());c.execute('SET CONSTRAINTS ALL DEFERRED');c.commit()
  finally:
   c.rollback();c.close()
   if t:t.join(10)
  self.assertFalse(t.is_alive());self.assertEqual(out['result'],'COMMIT')
  with self.assertRaises(AuthDenied):self.service.current(self.tokens[0])
  RECORDS.append({'kind':'serialized_semantics','schedule':'IMMEDIATE -> revocation waits G -> business COMMIT -> revocation COMMIT','revocation_wait':wait,'deadlock':False,'instantaneous_revocation_claim':False})
 def test_21_serialized_rollback_releases_revocation(self):
  c=self.connect();ch=self.begin(c,mode='serialized');cap=self.issue(ch);self.write(c,ch,cap);out={};ready=threading.Event();done=threading.Event();t=threading.Thread(target=self.revoke_actor,args=(out,ready,done));t.start()
  try:self.assertTrue(ready.wait(3));self.wait(out['pid'],(20261020,45));c.rollback()
  finally:c.close();t.join(10)
  self.assertFalse(t.is_alive());self.assertEqual(out['result'],'COMMIT');self.unchanged()
 def test_22_revoked_while_waiting_d_before_admission(self):
  hold=self.fixture_connection();hold.execute('SELECT pg_advisory_xact_lock(20261017,29)');out={};ready=threading.Event()
  def actor():
   try:
    with self.connect() as c:out['pid']=c.info.backend_pid;ready.set();ch=self.begin(c,mode='serialized');cap=self.issue(ch);self.write(c,ch,cap);self.sign(c,ch)
    out['result']='COMMIT'
   except AuthDenied:out['result']='AUTH_DENIED'
   except psycopg.Error as e:out['result']=e.sqlstate
  t=threading.Thread(target=actor);t.start()
  try:self.assertTrue(ready.wait(3));self.wait(out['pid'],(20261017,29));self.service.revoke_all(self.users[0])
  finally:hold.rollback();hold.close();t.join(10)
  self.assertFalse(t.is_alive());self.assertIn(out['result'],['AUTH_DENIED','42501']);self.unchanged()
  RECORDS.append({'kind':'revocation_before_admission','result':out['result'],'source_unchanged':True})
 def test_23_three_writers_bounded_not_load(self):
  a=self.connect();ch=self.begin(a,mode='serialized');cap=self.issue(ch);self.write(a,ch,cap);out=[];pids=[];ready=[threading.Event(),threading.Event()]
  def actor(i):
   try:
    with self.connect() as b:
     pids.append(b.info.backend_pid);ready[i].set();bc=self.begin(b,name=self.name+' writer '+str(i),mode='serialized');bp=self.issue(bc);self.write(b,bc,bp);self.sign(b,bc)
    out.append('COMMIT')
   except psycopg.Error as e:out.append(e.sqlstate)
   except AuthDenied:out.append('AUTH_DENIED')
  ts=[threading.Thread(target=actor,args=(i,)) for i in range(2)]
  for t in ts:t.start()
  try:
   self.assertTrue(all(e.wait(3) for e in ready));waits=[self.wait(pid,(20261017,29)) for pid in pids];self.sign(a,ch);a.commit()
  finally:
   a.rollback();a.close()
   for t in ts:t.join(10)
  self.assertFalse(any(t.is_alive() for t in ts));self.assertEqual(out,['COMMIT','COMMIT']);self.assertEqual(len(self.events()),4)
  RECORDS.append({'kind':'three_writers','commits':3,'waits':waits,'deadlock':False,'load_test':False})
 def test_24_proof_logged_scoped_bearer_consequences(self):
  with self.connect() as c:
   ch=self.begin(c);cap=self.issue(ch);c.execute('SAVEPOINT disclosure');c.execute('SET LOCAL log_parameter_max_length_on_error=-1')
   with self.assertRaises(psycopg.errors.DivisionByZero):c.execute('SELECT 1/%s,%s::jsonb,%s::bytea',(0,Jsonb(cap['proof']),bytes.fromhex(cap['mac'])))
   c.execute('ROLLBACK TO disclosure')
   log=Path(self.config['step45_log']).read_text(encoding='utf-8',errors='replace');self.assertIn(ch['context']['nonce'],log);self.assertIn(cap['mac'],log);self.assertTrue(all(v not in log for v in self.tokens+[self.pw]))
   c.execute('SAVEPOINT constrained')
   with self.assertRaises(psycopg.errors.InsufficientPrivilege):self.write(c,ch,cap,name=self.name+' attacker')
   c.execute('ROLLBACK TO constrained')
   # A disclosed, unused capability IS usable for the exact command in its original live transaction.
   self.write(c,ch,cap);self.sign(c,ch)
  with self.connect() as b:
   self.begin(b)
   with self.assertRaises(psycopg.errors.InsufficientPrivilege):self.write(b,ch,cap)
   b.rollback()
  RECORDS.append({'kind':'capability_disclosure','proof_and_mac_in_error_log':True,'raw_session_secret_in_business_sql_or_log':False,'same_live_context_exact_command_possible':True,'changed_payload_denied':True,'other_transaction_denied':True,'payload_metadata_confidentiality':False})
 def test_25_final_effective_acl_and_read_context_guard(self):
  with self.connect() as c:
   tables=c.execute("SELECT tablename FROM pg_tables WHERE schemaname='test_construction_identity_stage46'").fetchall();self.assertEqual(len(tables),41)
   for (table,) in tables:self.assertEqual(c.execute("SELECT has_table_privilege(%s,'SELECT'),has_table_privilege(%s,'INSERT'),has_any_column_privilege(%s,'UPDATE'),has_table_privilege(%s,'DELETE')",(table,)*4).fetchone(),(False,)*4)
   funcs=c.execute("SELECT n.nspname,p.proname,pg_get_function_identity_arguments(p.oid),has_function_privilege(p.oid,'EXECUTE'),p.prosecdef,p.proconfig FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname IN ('auth_proof','auth_command','closed_write','dk_service') ORDER BY n.nspname,p.proname").fetchall()
   for r in funcs:
    if r[0] in ('auth_command','closed_write','dk_service'):self.assertFalse(r[3])
  with self.dbconnect('auth') as c:
   self.assertFalse(c.execute("SELECT has_any_column_privilege('employees','UPDATE'),has_table_privilege('auth_sessions','UPDATE')").fetchone()[0])
   auth_funcs=c.execute("SELECT p.proname,has_function_privilege(p.oid,'EXECUTE') FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='auth_proof' ORDER BY p.proname").fetchall()
   self.assertEqual([r[0] for r in auth_funcs if r[1]],['issue','revoke_user_sessions'])
  RECORDS.append({'kind':'effective_acl','tables':41,'functions':funcs,'auth_runtime_allowed_functions':auth_funcs})
 def test_26_read_cannot_expand_to_maintenance(self):
  with self.connect() as c:
   ch=self.begin(c,'employee.read');cap=self.issue(ch,1);self.read(c,ch,cap)
   with self.assertRaises(psycopg.errors.InsufficientPrivilege):c.execute('SELECT auth_proof.snapshot(%s)',(bytes(32),))
   c.rollback()
 def test_27_serialized_proof_expiry_after_admission_not_abort(self):
  with self.connect() as c:
   ch=self.begin(c,mode='serialized',ttl=1);cap=self.issue(ch);self.write(c,ch,cap);time.sleep(1.1);self.sign(c,ch)
  RECORDS.append({'kind':'expiry_semantics','proof_expiry_checked_at_admission':True,'expiry_does_not_abort_already_admitted':True})

 def test_28_server_policy_cannot_be_downgraded_by_business(self):
  with self.fixture_connection() as f:f.execute("SELECT auth_proof.set_policy('serialized')")
  self.mode='serialized'
  self.deny('SELECT auth_proof.begin_command(%s,%s,%s,%s,%s)',('employee.name',Jsonb({'employee_id':self.ids[0],'name':self.name}),uuid.uuid4(),'admission',15))
  self.deny("SELECT auth_proof.set_policy('admission')")
  self.deny("SELECT auth_proof.set_policy('admission')",who='auth')
  RECORDS.append({'kind':'server_revocation_policy','business_cannot_choose_weaker_mode':True,'auth_runtime_cannot_change_server_policy':True})
 def test_29_block_and_credentials_wait_serialized_gate(self):
  for op in ['block_user','bump_credentials']:
   c=self.connect();ch=self.begin(c,mode='serialized');cap=self.issue(ch);self.write(c,ch,cap);self.sign(c,ch);out={};ready=threading.Event()
   def admin():
    try:
     with self.fixture_connection() as f:out['pid']=f.info.backend_pid;ready.set();f.execute('SELECT auth_proof.'+op+'(%s)',(self.users[0],))
     out['result']='COMMIT'
    except psycopg.Error as e:out['result']=e.sqlstate
   t=threading.Thread(target=admin);t.start()
   try:self.assertTrue(ready.wait(3));self.wait(out['pid'],(20261020,45));c.commit()
   finally:c.rollback();c.close();t.join(10)
   self.assertFalse(t.is_alive());self.assertEqual(out['result'],'COMMIT')
   with self.fixture_connection() as f:
    f.execute('UPDATE auth_users SET is_blocked=false WHERE id=%s',(self.users[0],));f.execute('UPDATE auth_sessions SET credential_version=(SELECT credential_version FROM auth_users WHERE id=%s) WHERE user_id=%s',(self.users[0],self.users[0]))
  RECORDS.append({'kind':'serialized_admin_mutations','block_and_credential_waits':2,'deadlock':False})
 def test_30_same_pid_new_transaction_replay(self):
  with self.connect() as c:
   ch=self.begin(c);cap=self.issue(ch);pid=c.info.backend_pid;c.rollback();new=self.begin(c)
   self.assertEqual(pid,c.info.backend_pid);self.assertNotEqual(ch['context']['xid'],new['context']['xid'])
   with self.assertRaises(psycopg.errors.InsufficientPrivilege):self.write(c,ch,cap)
   c.rollback()
 def test_31_same_top_transaction_new_savepoint_nonce(self):
  with self.connect() as c:
   c.execute('SELECT txid_current()');c.execute('SAVEPOINT before_context');ch=self.begin(c);cap=self.issue(ch);c.execute('ROLLBACK TO before_context');new=self.begin(c)
   self.assertEqual(ch['context']['xid'],new['context']['xid']);self.assertNotEqual(ch['context']['nonce'],new['context']['nonce'])
   with self.assertRaises(psycopg.errors.InsufficientPrivilege):self.write(c,ch,cap)
   c.rollback()
 def test_32_role_removed_before_admission(self):
  with self.connect() as c:
   ch=self.begin(c);cap=self.issue(ch)
   with self.fixture_connection() as f:f.execute('SELECT auth_proof.remove_user_roles(%s)',(self.users[0],))
   with self.assertRaises(psycopg.errors.InsufficientPrivilege):self.write(c,ch,cap)
   c.rollback()
  self.unchanged()
 def test_33_role_revocation_waits_serialized_gate(self):
  c=self.connect();ch=self.begin(c,mode='serialized');cap=self.issue(ch);self.write(c,ch,cap);self.sign(c,ch);c.execute('SET CONSTRAINTS ALL IMMEDIATE');out={};ready=threading.Event()
  def admin():
   try:
    with self.fixture_connection() as f:out['pid']=f.info.backend_pid;ready.set();f.execute('SELECT auth_proof.remove_user_roles(%s)',(self.users[0],))
    out['result']='COMMIT'
   except psycopg.Error as e:out['result']=e.sqlstate
  t=threading.Thread(target=admin);t.start()
  try:self.assertTrue(ready.wait(3));self.wait(out['pid'],(20261020,45));c.commit()
  finally:c.rollback();c.close();t.join(10)
  self.assertFalse(t.is_alive());self.assertEqual(out['result'],'COMMIT')
  with self.connect() as b:
   bc=self.begin(b,mode='serialized')
   with self.assertRaises(psycopg.errors.InsufficientPrivilege):self.issue(bc)
   b.rollback()
  RECORDS.append({'kind':'serialized_role_revocation','waited_on_gate':True,'business_committed_before_role_revocation_could_commit':True})

 def test_34_missing_authorization_key_fails_closed(self):
  z=self.config
  with BusinessConnection.connect(host='127.0.0.1',port=z['port'],dbname=z['databases']['stage45_fault'],user=z['closed_role'],password=z['closed_password'],connect_timeout=3,options='-c search_path=test_construction_identity_stage46 -c lock_timeout=3000 -c statement_timeout=7000') as f:
   with self.assertRaises(psycopg.errors.InsufficientPrivilege) as e:self.begin(f)
   self.assertIn('Authorization key unavailable',str(e.exception))
  RECORDS.append({'kind':'missing_key','challenge_generation_fails_closed':True,'fallback_or_null_mac_authorization':False})
 def test_35_expired_unauthorized_context_can_hold_gate_bounded(self):
  c=self.connect();ch=self.begin(c,mode='serialized',ttl=.1);time.sleep(.2)
  with self.dbconnect('auth') as a:
   a.execute("SET LOCAL lock_timeout='100ms'")
   with self.assertRaises(psycopg.errors.LockNotAvailable) as e:a.execute('SELECT auth_proof.revoke_user_sessions(%s)',(self.users[0],))
   self.assertEqual(e.exception.sqlstate,'55P03');a.rollback()
  c.rollback();c.close();self.service.revoke_all(self.users[0]);self.unchanged()
  RECORDS.append({'kind':'confirmed_availability_limit','unauthenticated_begin_holds_G':True,'proof_expiry_does_not_release_gate':True,'revocation_can_time_out':'55P03','release_after_rollback':True,'production_blocker':True})
 def test_36_server_canonical_name_matches_consumption(self):
  with self.connect() as c:
   ch=self.begin(c,name='  '+self.name+'   canonical  ');self.assertEqual(ch['context']['payload']['name'],self.name+' canonical');cap=self.issue(ch);self.write(c,ch,cap);self.sign(c,ch)
  with self.fixture_connection() as f:self.assertEqual(f.execute('SELECT full_name FROM employees WHERE id=%s',(self.ids[0],)).fetchone()[0],self.name+' canonical')

 def test_37_owners_public_acl_and_key_separation_catalog(self):
  cfg=self.config;owners=[cfg['auth_owner'],cfg['closed_owner'],cfg['dk_owner']]
  with self.fixture_connection() as f:
   flags=f.execute('SELECT rolname,rolcanlogin,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=ANY(%s) ORDER BY rolname',(owners,)).fetchall();self.assertEqual(len(flags),3);self.assertTrue(all(not any(r[1:]) for r in flags))
   matrix=[]
   for role in owners:
    pair=f.execute("SELECT has_table_privilege(%s,'auth_proof.key','SELECT'),has_table_privilege(%s,'dk_service.signing_key','SELECT')",(role,role)).fetchone();matrix.append([role,*pair])
    self.assertEqual(pair,(role==cfg['auth_owner'],role==cfg['dk_owner']))
   for table,owner in [('auth_proof.key',cfg['auth_owner']),('auth_proof.state',cfg['auth_owner']),('auth_proof.policy',cfg['auth_owner']),('dk_service.signing_key',cfg['dk_owner']),('dk_service.tx_state',cfg['dk_owner']),('auth_command.requests',cfg['closed_owner'])]:
    self.assertEqual(f.execute('SELECT pg_get_userbyid(c.relowner) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s AND c.relname=%s',tuple(table.split('.',1))).fetchone()[0],owner)
   public_functions=f.execute("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace CROSS JOIN LATERAL aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a WHERE n.nspname='auth_proof' AND a.grantee=0 AND a.privilege_type='EXECUTE'").fetchone()[0];self.assertEqual(public_functions,0)
   public_tables=f.execute("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace CROSS JOIN LATERAL aclexplode(coalesce(c.relacl,acldefault('r',c.relowner))) a WHERE n.nspname='auth_proof' AND c.relkind='r' AND a.grantee=0").fetchone()[0];self.assertEqual(public_tables,0)
  RECORDS.append({'kind':'owner_and_public_audit','owner_flags':flags,'cross_key_select_matrix':matrix,'public_execute_auth_proof':public_functions,'public_table_acl_entries':public_tables})
 def test_38_auth_runtime_effective_columns_sequences_and_namespaces(self):
  with self.dbconnect('auth') as a:
   self.assertEqual(a.execute("SELECT has_column_privilege('employees','id','SELECT'),has_column_privilege('employees','is_archived','SELECT'),has_column_privilege('employees','full_name','SELECT'),has_column_privilege('auth_users','password_changed_at','UPDATE'),has_column_privilege('auth_users','is_blocked','UPDATE'),has_column_privilege('auth_sessions','revoked_at','UPDATE')").fetchone(),(True,True,False,True,False,False))
   schemas=a.execute("SELECT has_schema_privilege('auth_proof','CREATE'),has_schema_privilege('test_construction_identity_stage46','CREATE'),has_schema_privilege('public','CREATE'),has_database_privilege(current_database(),'TEMP')").fetchone();self.assertEqual(schemas,(False,)*4)
   membership=a.execute('SELECT count(*) FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname=current_user)').fetchone()[0];self.assertEqual(membership,0)
   seqs=a.execute("SELECT c.relname,has_sequence_privilege(c.oid,'USAGE'),has_sequence_privilege(c.oid,'UPDATE') FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='test_construction_identity_stage46' AND c.relkind='S' ORDER BY c.relname").fetchall()
   self.assertEqual([s[0] for s in seqs if s[1]],['auth_security_events_id_seq','auth_sessions_id_seq']);self.assertFalse(any(s[2] for s in seqs))
  RECORDS.append({'kind':'auth_runtime_minimal_catalog','columns_checked':True,'schemas_create_and_temp_denied':True,'memberships':membership,'sequences':seqs})

 def test_39_read_and_write_reject_stale_snapshot_isolations(self):
  for isolation in ['REPEATABLE READ','SERIALIZABLE']:
   for op in ['employee.read','employee.name']:
    with self.connect() as c:
     c.execute('SET TRANSACTION ISOLATION LEVEL '+isolation)
     with self.assertRaises(psycopg.errors.InsufficientPrivilege) as e:self.begin(c,op)
     self.assertEqual(e.exception.sqlstate,'42501');c.rollback()
  self.unchanged()
  RECORDS.append({'kind':'isolation_boundary','read_committed_only':True,'read_and_write_stale_snapshot_modes_rejected':4})
