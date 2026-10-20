"""Step 44: real Argon2 sessions, native SQL ACL, bounded revocation races."""
import os,unittest,uuid,secrets,threading,time,hashlib,json
from pathlib import Path
import psycopg
from psycopg import sql
from app.services.user_auth import AuthService
from test_dk_service_prototype import DKServiceTests
from scripts import dk_transaction_prototype as proto
from scripts.auth_closed_command_prototype import EligibleConnection
if os.getenv('AUTH_ISOLATED_WORKER')!='1':raise RuntimeError('Own worker required')
RECORDS=[]
class CommandTests(unittest.TestCase):
 config=None
 events=DKServiceTests.events
 def fixture_connection(self):
  z=self.config
  return psycopg.connect(host='127.0.0.1',port=z['port'],dbname=z['databases']['stage44'],user=z['role'],password=z['password'],options='-c search_path=test_construction_identity_stage46 -c lock_timeout=3000 -c statement_timeout=7000',connect_timeout=3)
 def connect(self):
  z=self.config
  return psycopg.connect(host='127.0.0.1',port=z['port'],dbname=z['databases']['stage44'],user=z['closed_role'],password=z['closed_password'],options='-c search_path=test_construction_identity_stage46 -c lock_timeout=3000 -c statement_timeout=7000',connect_timeout=3)
 @classmethod
 def setUpClass(cls):
  class LocalService(AuthService):
   def connect(inner):
    c=cls().fixture_connection()
    assert c.info.dbname==cls.config['databases']['stage44'];return c
  cls.service=LocalService()
  cls.pw=secrets.token_urlsafe(24);cls.encoded=cls.service.hash_password(cls.pw)
  assert cls.encoded.startswith('$argon2id$')
 @classmethod
 def tearDownClass(cls):cls.pw=None;cls.encoded=None;cls.service=None
 def setUp(self):
  DKServiceTests.setUp(self);self.users=[];self.logins=[];self.tokens=[]
  with self.fixture_connection() as c:
   self.name=c.execute('SELECT full_name FROM employees WHERE id=%s',(self.ids[0],)).fetchone()[0]
   for eid,role in zip(self.ids,['SYSTEM_TECHNICIAN','OFFICE_MANAGER']):
    login='s44_'+uuid.uuid4().hex;self.logins.append(login)
    u=c.execute('INSERT INTO auth_users(login,employee_id,password_hash,is_blocked) VALUES(%s,%s,%s,false) RETURNING id',(login,eid,self.encoded)).fetchone()[0];self.users.append(u)
    c.execute('INSERT INTO auth_user_roles SELECT %s,id FROM auth_roles WHERE code=%s',(u,role))
  for login in self.logins:self.tokens.append(self.service.login(login,self.pw,uuid.uuid4().hex))
 def tearDown(self):
  with self.fixture_connection() as c:
   c.execute('DELETE FROM auth_security_events WHERE subject_user_id=ANY(%s) OR actor_user_id=ANY(%s)',(self.users,self.users))
   c.execute('DELETE FROM auth_sessions WHERE user_id=ANY(%s)',(self.users,));c.execute('DELETE FROM auth_user_roles WHERE user_id=ANY(%s)',(self.users,));c.execute('DELETE FROM auth_users WHERE id=ANY(%s)',(self.users,))
  DKServiceTests.tearDown(self)
  log=Path(self.config['step44_log']).read_text(encoding='utf-8',errors='replace')
  self.assertTrue(all(s not in log for s in self.tokens+[self.pw]))
 def write(self,c,token=None,name=None,rid=None):
  return c.execute('SELECT auth_command.employee_name(%s,%s,%s,%s)',(self.tokens[0] if token is None else token,self.ids[0],self.name+' changed' if name is None else name,rid or uuid.uuid4())).fetchone()[0]
 def sign(self,c):return proto.register(EligibleConnection(c,self.tokens[0]),self.key)
 def read(self,c,token):return c.execute('SELECT auth_command.employee_read(%s,%s)',(token,self.ids[0])).fetchone()[0]
 def deny(self,q,args=(),state='42501'):
  with self.connect() as c:
   with self.assertRaises(psycopg.Error) as ctx:c.execute(q,args)
   self.assertEqual(ctx.exception.sqlstate,state)
 def unchanged(self):
  with self.fixture_connection() as c:self.assertEqual(c.execute('SELECT full_name FROM employees WHERE id=%s',(self.ids[0],)).fetchone()[0],self.name)
  self.assertEqual(len(self.events()),4)
 def test_01_real_engineer_session_write_and_commit(self):
  with self.connect() as c:self.write(c);self.sign(c)
  with self.fixture_connection() as c:self.assertEqual(c.execute('SELECT full_name FROM employees WHERE id=%s',(self.ids[0],)).fetchone()[0],self.name+' changed')
  self.assertEqual(len(self.events()),4)
 def test_02_both_roles_read_without_table_write(self):
  for token in self.tokens:
   with self.connect() as c:
    self.assertEqual(self.read(c,token)['full_name'],self.name)
    self.assertFalse(c.execute("SELECT has_table_privilege('employees','UPDATE')").fetchone()[0])
    self.assertFalse(c.execute("SELECT EXISTS(SELECT 1 FROM pg_locks WHERE pid=pg_backend_pid() AND locktype='advisory')").fetchone()[0])
 def test_03_manager_cannot_write(self):
  self.deny('SELECT auth_command.employee_name(%s,%s,%s,%s)',(self.tokens[1],self.ids[0],self.name,uuid.uuid4()));self.unchanged()
 def test_04_missing_forged_and_digest_bearer(self):
  for tok in [None,'',secrets.token_urlsafe(32),AuthService.digest(self.tokens[0])]:
   self.deny('SELECT auth_command.employee_read(%s,%s)',(tok,self.ids[0]))
 def test_05_foreign_bearer_and_identity_spoof(self):
  # A manager bearer cannot gain engineer rights through client claims.
  with self.connect() as c:
   c.execute("SELECT set_config('app.role','SYSTEM_TECHNICIAN',true),set_config('app.user_id',%s,true)",(str(self.users[0]),))
   with self.assertRaises(psycopg.errors.InsufficientPrivilege):self.write(c,self.tokens[1])
  # Conversely, a stolen VALID engineer secret IS a bearer: no second identity exists at SQL socket.
  with self.connect() as c:self.write(c,self.tokens[0]);self.sign(c)
  RECORDS.append({'kind':'bearer_boundary','manager_claim_spoof_denied':True,'possessor_of_engineer_bearer_can_act_as_engineer':True})
 def mutate_auth(self,query):
  with self.fixture_connection() as c:c.execute(query,(self.users[0],))
 def test_06_expired(self):
  self.mutate_auth("UPDATE auth_sessions SET created_at=now()-interval '2 days',last_seen_at=now()-interval '2 days',expires_at=now()-interval '1 day' WHERE user_id=%s")
  self.deny('SELECT auth_command.employee_read(%s,%s)',(self.tokens[0],self.ids[0]))
 def test_07_revoked(self):
  self.service.revoke_all(self.users[0]);self.deny('SELECT auth_command.employee_read(%s,%s)',(self.tokens[0],self.ids[0]))
 def test_08_blocked(self):
  self.mutate_auth('UPDATE auth_users SET is_blocked=true WHERE id=%s');self.deny('SELECT auth_command.employee_read(%s,%s)',(self.tokens[0],self.ids[0]))
 def test_09_archived_dismissed_or_unlinked(self):
  for col,value in [('is_archived',True),('dismissal_date','2000-01-01')]:
   with self.fixture_connection() as c:c.execute(sql.SQL('UPDATE employees SET {}=%s WHERE id=%s').format(sql.Identifier(col)),(value,self.ids[0]))
   self.deny('SELECT auth_command.employee_read(%s,%s)',(self.tokens[0],self.ids[0]))
   with self.fixture_connection() as c:c.execute(sql.SQL('UPDATE employees SET {}=%s WHERE id=%s').format(sql.Identifier(col)),(False if col=='is_archived' else None,self.ids[0]))
  self.mutate_auth('UPDATE auth_users SET employee_id=NULL WHERE id=%s');self.deny('SELECT auth_command.employee_read(%s,%s)',(self.tokens[0],self.ids[0]))
 def test_10_credential_version(self):
  self.mutate_auth('UPDATE auth_users SET credential_version=credential_version+1 WHERE id=%s');self.deny('SELECT auth_command.employee_read(%s,%s)',(self.tokens[0],self.ids[0]))
 def test_11_role_permission_and_operation_spoof(self):
  self.deny('SELECT auth_command.identify(%s,%s)',(self.tokens[1],'employee.name'))
  self.deny('SELECT auth_command.employee_read(%s,%s,%s)',(self.tokens[1],self.ids[0],self.users[0]),'42883')
  self.deny('SELECT auth_command.employee_name(%s,%s,%s,%s,%s)',(self.tokens[1],self.ids[0],self.name,uuid.uuid4(),'SYSTEM_TECHNICIAN'),'42883')
  self.mutate_auth('DELETE FROM auth_user_roles WHERE user_id=%s');self.deny('SELECT auth_command.employee_read(%s,%s)',(self.tokens[0],self.ids[0]))
 def test_12_native_dml_raw_reads_private_calls(self):
  for table in ['employees','production_matrix_dk','auth_users','auth_sessions','auth_security_events']:
   self.deny(sql.SQL('SELECT * FROM {}').format(sql.Identifier(table)))
   for verb in ['UPDATE '+table+' SET '+({'employees':'full_name=full_name','production_matrix_dk':'employee_id=employee_id','auth_users':'login=login','auth_sessions':'token_hash=token_hash','auth_security_events':'event_type=event_type'}[table])+' WHERE false','DELETE FROM '+table+' WHERE false','INSERT INTO '+table+' DEFAULT VALUES']:self.deny(verb)
  for query in ['SELECT closed_write.employee(1,\'x\')','SELECT closed_write.enter()','SELECT auth_command.finish()','SELECT * FROM auth_command.pending','SELECT * FROM auth_command.requests','SELECT * FROM dk_service.signing_key','SELECT dk_service.finish()','CREATE TEMP TABLE x(id int)','CREATE TABLE public.x(id int)']:self.deny(query)
 def test_13_all_advisory_rowlocks_and_memberships(self):
  with self.connect() as c:
   rows=c.execute("SELECT p.proname,pg_get_function_identity_arguments(p.oid),has_function_privilege(p.oid,'EXECUTE') FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='pg_catalog' AND p.proname LIKE 'pg_%advisory%'").fetchall()
   self.assertEqual(len(rows),21);self.assertTrue(all(not r[2] for r in rows))
   self.assertEqual(c.execute('SELECT count(*) FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname=current_user)').fetchone()[0],0)
   flags=c.execute('SELECT rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=current_user').fetchone();self.assertEqual(flags,(False,)*5)
   self.assertFalse(c.execute("SELECT has_database_privilege(current_database(),'TEMP'),has_schema_privilege('public','CREATE')").fetchone()[0])
  for name,args,ok in rows:
   vals=[] if not args else [42] if args=='bigint' else [42,43]
   self.deny(sql.SQL('SELECT pg_catalog.{}('+','.join(['%s']*len(vals))+')').format(sql.Identifier(name)),vals)
  for clause in ['FOR UPDATE','FOR SHARE','FOR KEY SHARE','FOR NO KEY UPDATE']:self.deny('SELECT * FROM employees '+clause)
  self.deny('LOCK TABLE employees IN ACCESS EXCLUSIVE MODE')
  self.deny(sql.SQL('SET ROLE {}').format(sql.Identifier(self.config['closed_owner'])))
 def test_14_request_id_replay_and_changed_payload(self):
  rid=uuid.uuid4()
  with self.connect() as c:v=self.write(c,rid=rid);self.sign(c)
  with self.fixture_connection() as c:stamp=c.execute('SELECT updated_at FROM employees WHERE id=%s',(self.ids[0],)).fetchone()[0]
  with self.connect() as c:self.assertEqual(self.write(c,rid=rid),v) # no new source DML, no new DK obligation
  with self.fixture_connection() as c:self.assertEqual(c.execute('SELECT updated_at FROM employees WHERE id=%s',(self.ids[0],)).fetchone()[0],stamp)
  self.deny('SELECT auth_command.employee_name(%s,%s,%s,%s)',(self.tokens[0],self.ids[0],self.name+' other',rid),'22023')
 def test_15_raw_commit_without_dk_intent(self):
  with self.assertRaises(psycopg.errors.InsufficientPrivilege):
   with self.connect() as c:self.write(c);c.execute("SELECT set_config('tehresurs.dk_calendar_dirty','0',true)");c.execute('COMMIT')
  self.unchanged()
 def test_16_stale_hmac_and_forgery(self):
  with self.assertRaises(psycopg.errors.InsufficientPrivilege):
   with self.connect() as c:self.write(c);self.sign(c);self.write(c,name=self.name+' stale')
  with self.assertRaises(psycopg.errors.InsufficientPrivilege):
   with self.connect() as c:self.write(c);c.execute('SELECT auth_command.register(%s,%s,%s)',(self.tokens[0],[],bytes(32)))
  self.unchanged()
 def test_17_savepoints_release_sealed_guc(self):
  with self.connect() as c:
   c.execute('SAVEPOINT before');self.write(c);self.sign(c);c.execute('SET CONSTRAINTS ALL IMMEDIATE');c.execute('ROLLBACK TO before');c.execute('RELEASE before');c.execute('SET CONSTRAINTS ALL DEFERRED')
   self.write(c);self.sign(c);c.execute('SET CONSTRAINTS ALL IMMEDIATE');c.execute('SAVEPOINT sealed');c.execute("SELECT set_config('dk_service.sealed','false',true)")
   with self.assertRaises(psycopg.errors.InsufficientPrivilege):self.write(c,name=self.name+' late')
   c.execute('ROLLBACK TO sealed');c.execute('SET CONSTRAINTS ALL DEFERRED');c.execute('RELEASE sealed')
  self.assertEqual(len(self.events()),4)
 def test_18_field_validation_and_errors_atomic(self):
  for value in ['', '   ',None]:
   self.deny('SELECT auth_command.employee_name(%s,%s,%s,%s)',(self.tokens[0],self.ids[0],value,uuid.uuid4()),'22023')
  with self.fixture_connection() as c:other=c.execute('SELECT full_name FROM employees WHERE id=%s',(self.ids[1],)).fetchone()[0]
  self.deny('SELECT auth_command.employee_name(%s,%s,%s,%s)',(self.tokens[0],self.ids[0],other,uuid.uuid4()),'23505')
  with self.assertRaises(psycopg.errors.DivisionByZero):
   with self.connect() as c:self.write(c);self.sign(c);c.execute('SET CONSTRAINTS ALL IMMEDIATE');c.execute('SELECT 1/0')
  self.unchanged()
 def wait_blocked(self,pid):
  deadline=time.monotonic()+2.5
  while time.monotonic()<deadline:
   with self.fixture_connection() as c:row=c.execute('SELECT locktype,mode FROM pg_locks WHERE pid=%s AND NOT granted',(pid,)).fetchone()
   if row:return row
   time.sleep(.02)
  self.fail('Bounded wait not observed')
 def test_19_revoke_while_waiting_and_activity_parameters(self):
  hold=self.fixture_connection();hold.execute('SELECT pg_advisory_xact_lock(20261017,29)')
  out={};ready=threading.Event()
  def actor():
   try:
    with self.connect() as c:
     out['pid']=c.info.backend_pid;ready.set();self.write(c);self.sign(c)
    out['result']='COMMIT'
   except psycopg.Error as e:out['result']=e.sqlstate
  t=threading.Thread(target=actor);t.start()
  try:
   self.assertTrue(ready.wait(3));wait=self.wait_blocked(out['pid'])
   with self.connect() as c:
    query=c.execute('SELECT query FROM pg_stat_activity WHERE pid=%s',(out['pid'],)).fetchone()[0]
    self.assertNotIn(self.tokens[0],query);self.assertIn('$1',query)
   self.service.revoke_all(self.users[0])
  finally:
   hold.rollback();hold.close();t.join(10)
   if t.is_alive():raise AssertionError('Actor did not finish')
  self.assertEqual(out['result'],'42501');self.unchanged()
  RECORDS.append({'kind':'revoke_before_admission','wait':wait,'sqlstate':out['result'],'activity_contains_bind_secret':False,'partial_changes':False})
 def test_20_revoke_during_transaction_commit_check(self):
  c=self.connect()
  try:
   self.write(c);self.sign(c);self.service.revoke_all(self.users[0])
   with self.assertRaises(psycopg.errors.InsufficientPrivilege):c.commit()
   c.rollback()
  finally:c.close()
  self.unchanged();RECORDS.append({'kind':'revoke_after_write_before_deferred_check','commit':'42501','rollback_all':True})
 def test_21_permission_revoked_after_signing(self):
  c=self.connect()
  try:
   self.write(c);self.sign(c);self.mutate_auth('DELETE FROM auth_user_roles WHERE user_id=%s')
   with self.assertRaises(psycopg.errors.InsufficientPrivilege):c.execute('COMMIT')
   c.rollback()
  finally:c.close()
  self.unchanged()
 def test_22_early_constraint_auth_cutoff_is_not_commit(self):
  with self.connect() as c:
   self.write(c);self.sign(c);c.execute('SET CONSTRAINTS ALL IMMEDIATE');self.service.revoke_all(self.users[0]);c.execute('SET CONSTRAINTS ALL DEFERRED')
  # Reproduced limitation: all deferred checks already executed. SEALED still prevents new writes.
  with self.fixture_connection() as c:self.assertEqual(c.execute('SELECT full_name FROM employees WHERE id=%s',(self.ids[0],)).fetchone()[0],self.name+' changed')
  RECORDS.append({'kind':'revocation_cutoff_limit','revoke_after_early_checks_commit_succeeds':True,'instant_commit_revocation_guarantee':False,'blocker_for_stronger_semantics':True})
 def test_23_simultaneous_commands_no_auth_business_cycle(self):
  c=self.connect();self.write(c);out={};ready=threading.Event()
  def actor():
   try:
    with self.connect() as b:out['pid']=b.info.backend_pid;ready.set();self.write(b,name=self.name+' second');self.sign(b)
    out['result']='COMMIT'
   except psycopg.Error as e:out['result']=e.sqlstate
  t=threading.Thread(target=actor);t.start()
  try:
   self.assertTrue(ready.wait(3));self.wait_blocked(out['pid'])
   with self.fixture_connection() as f:
    rows=f.execute("SELECT classid,objid,granted FROM pg_locks WHERE pid=%s AND locktype='advisory' ORDER BY classid,objid",(out['pid'],)).fetchall()
    self.assertEqual(rows,[(20261017,29,False)])
   self.sign(c);c.commit()
  finally:c.rollback();c.close();t.join(10)
  self.assertFalse(t.is_alive());self.assertEqual(out['result'],'COMMIT');self.assertEqual(len(self.events()),4)
  RECORDS.append({'kind':'two_authorized_writers','commits':2,'deadlock':False,'waiting_lock_order':rows})
 def test_24_parameters_logs_settings_and_function_acl(self):
  with self.connect() as c:
   settings={k:c.execute('SHOW '+k).fetchone()[0] for k in ['log_statement','log_min_duration_statement','log_parameter_max_length_on_error']}
   settings.update(self.config['step44_settings']);self.assertEqual(settings['log_statement'],'none');self.assertEqual(settings['log_min_duration_statement'],'-1');self.assertEqual(settings['log_parameter_max_length_on_error'],'0')
   self.assertFalse(c.execute("SELECT pg_has_role(current_user,'pg_read_all_stats','MEMBER') OR pg_has_role(current_user,'pg_read_server_files','MEMBER')").fetchone()[0])
   # Runtime can observe only parameterized statement text, never persisted bearer/digest.
   self.assertFalse(c.execute("SELECT EXISTS(SELECT 1 FROM information_schema.role_column_grants WHERE grantee=current_user AND privilege_type IN ('INSERT','UPDATE','DELETE'))").fetchone()[0])
  self.deny("SET log_statement='all'")
  self.deny('SELECT pg_read_file(\'postgresql.conf\')')
  self.deny('SELECT * FROM auth_command.requests')
  RECORDS.append({'kind':'secret_transport','protocol':'bound extended-query parameters; loopback owned PG','activity_checked':True,'postgres_log_scanned_each_test':True,'settings':settings,'external_monitors_or_privileged_memory_proven_safe':False})
 def test_25_read_in_readonly_transaction(self):
  with self.connect() as c:
   c.execute('SET TRANSACTION READ ONLY');self.assertEqual(self.read(c,self.tokens[1])['id'],self.ids[0])
 def test_26_isolation_role_and_search_path(self):
  with self.connect() as c:
   c.execute("SET LOCAL search_path=pg_temp,public,pg_catalog");self.write(c);self.sign(c)
  with self.assertRaises(psycopg.errors.InsufficientPrivilege):
   with self.connect() as c:c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ');self.write(c)

 def test_27_public_canary_proves_user_settable_error_bind_logging(self):
  marker='PUBLIC_NOT_A_SESSION_SECRET_'+uuid.uuid4().hex
  with self.connect() as c:
   self.assertEqual(c.execute("SELECT context FROM pg_settings WHERE name='log_parameter_max_length_on_error'").fetchone()[0],'user')
   c.execute('SET LOCAL log_parameter_max_length_on_error=-1')
   with self.assertRaises(psycopg.errors.DivisionByZero):c.execute('SELECT 1/%s,%s::text',(0,marker))
   c.rollback()
  deadline=time.monotonic()+1
  while time.monotonic()<deadline:
   log=Path(self.config['step44_log']).read_text(encoding='utf-8',errors='replace')
   if marker in log:break
   time.sleep(.02)
  self.assertIn(marker,log)
  self.assertTrue(all(secret not in log for secret in self.tokens+[self.pw]))
  RECORDS.append({'kind':'confirmed_diagnostic_channel_blocker','user_can_enable_error_bind_logging':True,'public_nonsecret_bind_canary_in_postgres_log':True,'actual_session_secrets_used_in_probe':False,'parameterization_alone_proves_confidentiality':False})
 def test_28_effective_acl_snapshot(self):
  with self.connect() as c:
   tables=c.execute("SELECT tablename FROM pg_tables WHERE schemaname='test_construction_identity_stage46' ORDER BY tablename").fetchall();self.assertEqual(len(tables),41)
   for (table,) in tables:
    privileges=c.execute("SELECT has_table_privilege(%s,'SELECT'),has_table_privilege(%s,'INSERT'),has_any_column_privilege(%s,'UPDATE'),has_table_privilege(%s,'DELETE'),has_table_privilege(%s,'TRUNCATE')",(table,)*5).fetchone()
    self.assertEqual(privileges,(False,)*5)
   seqs=c.execute("SELECT c.oid,has_sequence_privilege(c.oid,'USAGE'),has_sequence_privilege(c.oid,'UPDATE') FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='test_construction_identity_stage46' AND c.relkind='S'").fetchall()
   self.assertTrue(all(not r[1] and not r[2] for r in seqs))
   funcs=c.execute("SELECT n.nspname,p.proname,pg_get_function_identity_arguments(p.oid),p.prosecdef,has_function_privilege(p.oid,'EXECUTE'),p.proconfig FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname IN ('closed_write','dk_service','auth_command','test_construction_identity_stage46') ORDER BY n.nspname,p.proname,p.oid").fetchall()
   self.assertFalse(any(r[4] for r in funcs if r[0] in ('closed_write','dk_service')))
   public_auth=[r[1] for r in funcs if r[0]=='auth_command' and r[4]]
   self.assertEqual(sorted(public_auth),['absence','calendar_row','employee_name','employee_read','register','snapshot'])
  RECORDS.append({'kind':'effective_acl','business_tables':41,'all_direct_select_insert_update_delete_truncate_denied':True,'sequences':len(seqs),'no_usage_or_update_on_sequences':True,'functions':funcs,'runtime':self.config['closed_role']})
