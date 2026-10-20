"""Step 42: own isolated closed-write role, bounded concurrency and native ACL."""
import os,unittest,uuid,time,threading
import psycopg
from psycopg import sql
from test_dk_service_prototype import DKServiceTests
from scripts import dk_transaction_prototype as proto
from app.services import matrix_dk as dk
if os.getenv('AUTH_ISOLATED_WORKER')!='1':raise RuntimeError('Restricted worker only')
RECORDS=[]
class ClosedWriteTests(unittest.TestCase):
 config=None
 events=DKServiceTests.events
 def fixture_connection(self):
  cfg=self.config
  return psycopg.connect(host='127.0.0.1',port=cfg['port'],dbname=cfg['databases']['stage42'],user=cfg['role'],password=cfg['password'],options='-c search_path=test_construction_identity_stage46',connect_timeout=3)
 def connect(self):
  cfg=self.config
  return psycopg.connect(host='127.0.0.1',port=cfg['port'],dbname=cfg['databases']['stage42'],user=cfg['closed_role'],password=cfg['closed_password'],options='-c search_path=test_construction_identity_stage46 -c lock_timeout=4000 -c statement_timeout=8000',connect_timeout=3)
 def setUp(self):
  DKServiceTests.setUp(self)
  with self.fixture_connection() as c:
   self.name=c.execute('SELECT full_name FROM employees WHERE id=%s',(self.ids[0],)).fetchone()[0]
   row=c.execute('SELECT id FROM crews ORDER BY id LIMIT 1').fetchone();self.created_crew=not bool(row)
   self.crew=row[0] if row else c.execute('INSERT INTO crews(name) VALUES(%s) RETURNING id',('Closed '+uuid.uuid4().hex,)).fetchone()[0]
   self.object=c.execute('SELECT id FROM construction_objects WHERE NOT is_archived ORDER BY id LIMIT 1').fetchone()[0]
   self.ticket=c.execute("INSERT INTO rail_tickets(file_hash,source_filename,employee_id,status) VALUES(%s,'closed-fixture.pdf',%s,'PARSED') RETURNING id",(self.digest(),self.ids[0])).fetchone()[0]
 def tearDown(self):
  DKServiceTests.tearDown(self)
  if self.created_crew:
   with self.fixture_connection() as c:c.execute('DELETE FROM crews WHERE id=%s',(self.crew,))
 def digest(self):return uuid.uuid4().hex+uuid.uuid4().hex
 def employee(self,c,name=None):c.execute('SELECT closed_write.employee(%s,%s)',(self.ids[0],name or self.name+' changed'))
 def deny(self,query,args=()):
  with self.connect() as c:
   with self.assertRaises(psycopg.errors.InsufficientPrivilege) as ctx:c.execute(query,args)
   self.assertEqual(ctx.exception.sqlstate,'42501')
 def test_four_closed_operations(self):
  digest=self.digest();before=self.events()
  with self.connect() as c:
   self.employee(c);c.execute('SELECT closed_write.crew(%s,%s)',(self.ids[0],self.crew));c.execute('SELECT closed_write.ticket(%s,%s)',(digest,self.ids[0]));c.execute('SELECT closed_write.ticket_object(%s,%s)',(self.ticket,self.object));proto.register(c,self.key)
  with self.fixture_connection() as c:
   self.assertEqual(c.execute('SELECT full_name,crew_id FROM employees WHERE id=%s',(self.ids[0],)).fetchone(),(self.name+' changed',self.crew))
   self.assertEqual(c.execute('SELECT object_id FROM rail_tickets WHERE id=%s',(self.ticket,)).fetchone()[0],self.object)
   self.assertEqual(c.execute('SELECT count(*) FROM rail_tickets WHERE file_hash=%s',(digest,)).fetchone()[0],1)
  self.assertEqual(self.events(),before)
 def test_native_dml_row_and_table_locks_denied(self):
  prelock_states=[]
  for table in ['employees','crews','rail_tickets','employee_movements','production_matrix_dk','positions','employee_luvr_day_overrides','employee_absences','employee_duration_exceptions','employee_sick_periods','construction_objects','construction_subobjects','construction_entities','construction_entity_hierarchy','construction_entity_current']:
   for clause in ['FOR UPDATE','FOR SHARE','FOR KEY SHARE','FOR NO KEY UPDATE']:
    if table=='construction_entity_current':
     with self.connect() as c:
      with self.assertRaises((psycopg.errors.InsufficientPrivilege,psycopg.errors.FeatureNotSupported)) as ctx:c.execute(sql.SQL('SELECT * FROM {} LIMIT 1 '+clause).format(sql.Identifier(table)))
      prelock_states.append(ctx.exception.sqlstate)
    else:self.deny(sql.SQL('SELECT * FROM {} LIMIT 1 '+clause).format(sql.Identifier(table)))
   self.deny(sql.SQL('LOCK TABLE {} IN ACCESS EXCLUSIVE MODE').format(sql.Identifier(table)))
  for query in ['UPDATE employees SET full_name=full_name WHERE false','UPDATE employees SET crew_id=NULL WHERE false','DELETE FROM employees WHERE false','INSERT INTO rail_tickets(file_hash,source_filename,status) VALUES(repeat(\'a\',64),\'x\',\'PARSED\')','UPDATE production_matrix_dk SET work_date=work_date WHERE false','DELETE FROM production_matrix_dk WHERE false','UPDATE employee_movements SET event_datetime=event_datetime WHERE false']:
   self.deny(query)
  RECORDS.append({'kind':'relation_prelocks','relations':15,'locking_selects':60,'strong_table_locks':15,'base_denied_sqlstate':'42501','view_sqlstates':prelock_states})
 def test_all_advisory_overloads_denied(self):
  with self.connect() as c:rows=c.execute("SELECT p.oid,p.proname,pg_get_function_identity_arguments(p.oid),has_function_privilege(p.oid,'EXECUTE') FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='pg_catalog' AND p.proname LIKE 'pg_%advisory%' ORDER BY p.proname,p.oid").fetchall()
  with self.fixture_connection() as c:
   owner_allowed=c.execute("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='pg_catalog' AND p.proname LIKE 'pg_%%advisory%%' AND has_function_privilege(%s,p.oid,'EXECUTE')",(self.config['closed_owner'],)).fetchone()[0]
   self.assertEqual(owner_allowed,1)
  for oid,name,args,allowed in rows:
   self.assertFalse(allowed,(name,args))
   values=[] if not args else [202610170029] if args=='bigint' else [20261017,29]
   self.deny(sql.SQL('SELECT pg_catalog.{}('+','.join(['%s']*len(values))+')').format(sql.Identifier(name)),values)
  RECORDS.append({'kind':'advisory_acl','overloads':len(rows),'all_execute_denied':True})
 def test_private_functions_key_state_and_role_denied(self):
  for query,args in [('SELECT closed_write.enter()',()),('SELECT dk_service.finish()',()),('SELECT dk_service.context()',()),('SELECT dk_service.snapshot()',()),('SELECT dk_service.prune(%s,%s)',([],b'x'*32)),('SELECT * FROM dk_service.tx_state',()),('UPDATE dk_service.tx_state SET sealed=false',()),('SELECT * FROM dk_service.signing_key',()),('CREATE TEMP TABLE employees(id bigint)',()),('CREATE TABLE public.step42_bypass(id bigint)',()),('ALTER TABLE employees DISABLE TRIGGER ALL',()),(sql.SQL('SET ROLE {}').format(sql.Identifier(self.config['closed_owner'])),())]:self.deny(query,args)
 def test_raw_commit_missing_intent_and_dirty_guc(self):
  with self.assertRaises(psycopg.errors.InsufficientPrivilege):
   with self.connect() as c:self.employee(c);c.execute("SELECT set_config('tehresurs.dk_calendar_dirty','0',true)");c.execute('COMMIT')
  with self.fixture_connection() as c:self.assertEqual(c.execute('SELECT full_name FROM employees WHERE id=%s',(self.ids[0],)).fetchone()[0],self.name)
 def test_savepoint_rollback_release_and_repeated_writes(self):
  before=self.events()
  with self.connect() as c:
   c.execute('SAVEPOINT before_entry');self.employee(c);proto.register(c,self.key);c.execute('SET CONSTRAINTS ALL IMMEDIATE');c.execute('ROLLBACK TO before_entry');c.execute('RELEASE before_entry');c.execute('SET CONSTRAINTS ALL DEFERRED')
   self.employee(c,self.name+' final');self.employee(c,self.name+' final again');proto.register(c,self.key)
  self.assertEqual(self.events(),before)
  with self.fixture_connection() as c:self.assertEqual(c.execute('SELECT full_name FROM employees WHERE id=%s',(self.ids[0],)).fetchone()[0],self.name+' final again')
 def test_sealed_early_apply_cannot_write_or_unseal(self):
  before=self.events()
  with self.connect() as c:
   self.employee(c);proto.register(c,self.key);c.execute('SET CONSTRAINTS ALL IMMEDIATE');c.execute('SAVEPOINT sealed')
   for op,args in [('employee',(self.ids[0],self.name)),('crew',(self.ids[0],None)),('ticket',(self.digest(),self.ids[0])),('ticket_object',(self.ticket,None))]:
    with self.assertRaises(psycopg.errors.InsufficientPrivilege):c.execute('SELECT closed_write.'+op+'(%s,%s)',args)
    c.execute('ROLLBACK TO sealed');c.execute('SET CONSTRAINTS ALL DEFERRED')
   c.execute('RELEASE sealed')
  self.assertEqual(self.events(),before)
 def test_stale_intent_forgery_and_search_path(self):
  before=self.events()
  with self.assertRaises(psycopg.errors.InsufficientPrivilege):
   with self.connect() as c:self.employee(c);proto.register(c,self.key);self.employee(c,self.name);c.commit()
  with self.assertRaises(psycopg.errors.InsufficientPrivilege):
   with self.connect() as c:self.employee(c);c.execute('SELECT dk_service.register_intent(%s,%s)',([],b'x'*32))
  with self.connect() as c:
   c.execute('SET LOCAL search_path=pg_temp,public,pg_catalog');self.employee(c);proto.register(c,self.key)
  self.assertEqual(self.events(),before)
 def test_error_rolls_back_all_operations(self):
  before=self.events()
  with self.assertRaises(psycopg.errors.CheckViolation):
   with self.connect() as c:self.employee(c);c.execute('SELECT closed_write.crew(%s,%s)',(self.ids[0],self.crew));c.execute('SELECT closed_write.ticket(%s,%s)',('invalid',self.ids[0]))
  with self.fixture_connection() as c:self.assertEqual(c.execute('SELECT full_name,crew_id FROM employees WHERE id=%s',(self.ids[0],)).fetchone(),(self.name,None))
  self.assertEqual(self.events(),before)
 def test_immediate_without_intent_fails_closed(self):
  with self.assertRaises(psycopg.errors.InsufficientPrivilege):
   with self.connect() as c:self.employee(c);c.execute('SET CONSTRAINTS ALL IMMEDIATE')
 def test_subquery_and_cte_cannot_prelock(self):
  self.deny('SELECT closed_write.employee((SELECT id FROM employees WHERE id=%s FOR UPDATE),%s)',(self.ids[0],self.name))
  self.deny('WITH locked AS MATERIALIZED (SELECT id FROM employees WHERE id=%s FOR SHARE) SELECT closed_write.employee(id,%s) FROM locked',(self.ids[0],self.name))
  self.deny('WITH changed AS (UPDATE employees SET full_name=full_name WHERE id=%s RETURNING id) SELECT closed_write.crew(id,NULL) FROM changed',(self.ids[0],))
 def test_owner_flags_and_closed_acl(self):
  with self.fixture_connection() as c:
   self.assertEqual(c.execute('SELECT rolcanlogin,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=%s',(self.config['closed_owner'],)).fetchone(),(False,False,False,False,False,False))
   self.assertEqual(c.execute('SELECT count(*) FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname=%s)',(self.config['closed_role'],)).fetchone()[0],0)
  with self.connect() as c:
   for table in ['employees','rail_tickets','production_matrix_dk']:
    self.assertFalse(c.execute("SELECT has_table_privilege(%s,'UPDATE') OR has_table_privilege(%s,'DELETE') OR has_any_column_privilege(%s,'UPDATE')",(table,table,table)).fetchone()[0])
   self.assertEqual(c.execute("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace CROSS JOIN LATERAL aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a WHERE n.nspname IN ('closed_write','dk_service') AND a.grantee=0 AND a.privilege_type='EXECUTE'").fetchone()[0],0)
 def pair(self,kind,repeat):
  a=self.connect();b=self.connect();gate=threading.Event();record={'kind':kind,'repeat':repeat,'events':[],'outcomes':{},'locks':[]};start=time.monotonic()
  def log(who,event):record['events'].append({'actor':who,'event':event,'ms':round((time.monotonic()-start)*1000,3)})
  def operation(c,which):
   if which=='employee':self.employee(c,self.name+' '+str(repeat))
   elif which=='crew':c.execute('SELECT closed_write.crew(%s,%s)',(self.ids[0],self.crew))
   elif which=='upload':c.execute('SELECT closed_write.ticket(%s,%s)',(self.digest(),self.ids[0]))
   else:c.execute('SELECT closed_write.ticket_object(%s,%s)',(self.ticket,self.object))
  first,second={'ticket_identity':('object','upload'),'crew_update':('crew','employee'),'share_cycle':('employee','crew')}[kind]
  def writer():
   try:
    log('B','call started');operation(b,second);log('B','call completed');proto.register(b,self.key);b.commit();record['outcomes']['B']='COMMIT'
   except Exception as e:b.rollback();record['outcomes']['B']=getattr(e,'sqlstate',None) or type(e).__name__
   finally:b.close();gate.set()
  try:
   operation(a,first);log('A','closed call returned; transaction held');record['A_pid']=a.info.backend_pid;record['B_pid']=b.info.backend_pid
   t=threading.Thread(target=writer,daemon=True);t.start()
   with self.fixture_connection() as obs:
    obs.autocommit=True;deadline=time.monotonic()+2.5
    while time.monotonic()<deadline:
     rows=obs.execute("SELECT pid,locktype,mode,granted,classid::bigint,objid::bigint FROM pg_locks WHERE pid=ANY(%s) AND locktype IN ('advisory','transactionid','tuple') ORDER BY pid,locktype,granted",([a.info.backend_pid,b.info.backend_pid],)).fetchall()
     if any(row[0]==b.info.backend_pid and not row[3] for row in rows):record['locks']=[list(row) for row in rows];break
     time.sleep(.02)
    self.assertTrue(record['locks'])
    self.assertTrue(any(row[0]==b.info.backend_pid and row[1]=='advisory' and not row[3] and row[4:]==(20261017,29) for row in rows))
    self.assertFalse(any(row[0]==b.info.backend_pid and row[1]=='advisory' and row[3] for row in rows))
   proto.register(a,self.key);a.commit();record['outcomes']['A']='COMMIT';log('A','COMMIT');self.assertTrue(gate.wait(10));t.join(1);self.assertFalse(t.is_alive());self.assertEqual(record['outcomes'],{'A':'COMMIT','B':'COMMIT'})
   self.assertEqual(len(self.events()),4)
   with self.fixture_connection() as check:
    actual=check.execute('SELECT full_name,crew_id FROM employees WHERE id=%s',(self.ids[0],)).fetchone()
    if kind in ('crew_update','share_cycle'):self.assertEqual(actual,(self.name+' '+str(repeat),self.crew))
    if kind=='ticket_identity':
     self.assertEqual(check.execute('SELECT object_id FROM rail_tickets WHERE id=%s',(self.ticket,)).fetchone()[0],self.object)
     self.assertEqual(check.execute("SELECT count(*) FROM rail_tickets WHERE employee_id=%s AND source_filename='closed-isolated.pdf'",(self.ids[0],)).fetchone()[0],repeat+1)
   record['source_effects_verified']=True
   with self.connect() as c:
    for eid,day in self.events():self.assertTrue(dk.eligible(c,eid,day))
   record['dk_verified']=True
  finally:
   if not a.closed:a.rollback();a.close()
   if not b.closed:
    b.cancel();gate.wait(9)
   RECORDS.append(record)
 def test_concurrent_ticket_identity(self):
  for n in range(2):self.pair('ticket_identity',n)
 def test_concurrent_crew_update(self):
  for n in range(2):self.pair('crew_update',n)
 def test_concurrent_share_then_write(self):
  for n in range(2):self.pair('share_cycle',n)

 def test_actual_cleanup_and_rollback_after_apply(self):
  with self.fixture_connection() as c:c.execute("UPDATE employee_luvr_day_overrides SET value='TRAVEL' WHERE employee_id=%s AND work_date=%s",(self.ids[0],self.a))
  before=self.events()
  with self.assertRaises(psycopg.errors.DivisionByZero):
   with self.connect() as c:
    self.employee(c);keys=proto.register(c,self.key);self.assertEqual(keys,[str(self.ids[0])+':'+str(self.a)]);c.execute('SET CONSTRAINTS ALL IMMEDIATE')
    self.assertFalse(c.execute('SELECT 1 FROM production_matrix_dk WHERE employee_id=%s AND work_date=%s',(self.ids[0],self.a)).fetchone());c.execute('SELECT 1/0')
  self.assertEqual(self.events(),before)
  with self.fixture_connection() as c:self.assertEqual(c.execute('SELECT full_name FROM employees WHERE id=%s',(self.ids[0],)).fetchone()[0],self.name)
  with self.connect() as c:self.employee(c);proto.register(c,self.key)
  self.assertEqual(self.events(),before-{(self.ids[0],self.a)})
 def test_lock_stages_before_source_rows(self):
  for held,expected in [((20261007,1601),[(20261017,29)]),((20261013,24),[(20261017,29),(20261007,1601)])]:
   blocker=self.fixture_connection();worker=self.connect();finished=threading.Event();outcome=[]
   def run():
    try:self.employee(worker);proto.register(worker,self.key);worker.commit();outcome.append('COMMIT')
    except Exception as e:worker.rollback();outcome.append(getattr(e,'sqlstate',None) or type(e).__name__)
    finally:worker.close();finished.set()
   try:
    blocker.execute('SELECT pg_advisory_xact_lock(%s,%s)',held);pid=worker.info.backend_pid;t=threading.Thread(target=run,daemon=True);t.start()
    with self.fixture_connection() as obs:
     obs.autocommit=True;deadline=time.monotonic()+2.5;rows=[]
     while time.monotonic()<deadline:
      rows=obs.execute("SELECT classid::bigint,objid::bigint,granted FROM pg_locks WHERE pid=%s AND locktype='advisory' ORDER BY classid,objid",(pid,)).fetchall()
      if any(tuple(x[:2])==held and not x[2] for x in rows):break
      time.sleep(.02)
     self.assertEqual(sorted(tuple(x[:2]) for x in rows if x[2]),sorted(expected));self.assertTrue(any(tuple(x[:2])==held and not x[2] for x in rows))
     RECORDS.append({'kind':'entry_lock_stage','blocked_on':list(held),'locks':[list(x) for x in rows]})
    blocker.rollback();self.assertTrue(finished.wait(10));t.join(1);self.assertEqual(outcome,['COMMIT'])
   finally:
    blocker.rollback();blocker.close()
    if not worker.closed:worker.cancel();finished.wait(9)
 def test_invalid_reference_rolls_back_prior_write(self):
  with self.assertRaises(psycopg.errors.CheckViolation) as ctx:
   with self.connect() as c:self.employee(c);c.execute('SELECT closed_write.ticket_object(%s,%s)',(self.ticket,9223372036854775806))
  self.assertEqual(ctx.exception.sqlstate,'23514')
  with self.fixture_connection() as c:
   self.assertEqual(c.execute('SELECT full_name FROM employees WHERE id=%s',(self.ids[0],)).fetchone()[0],self.name)
   self.assertIsNone(c.execute('SELECT object_id FROM rail_tickets WHERE id=%s',(self.ticket,)).fetchone()[0])
 def test_no_column_grants_or_sibling_service_access(self):
  with self.connect() as c:
   for (table,) in c.execute("SELECT tablename FROM pg_tables WHERE schemaname='test_construction_identity_stage46'").fetchall():
    self.assertFalse(c.execute("SELECT has_table_privilege(%s,'UPDATE') OR has_table_privilege(%s,'INSERT') OR has_table_privilege(%s,'DELETE') OR has_any_column_privilege(%s,'UPDATE')",(table,table,table,table)).fetchone()[0],table)
   self.assertEqual(c.execute("SELECT count(*) FROM pg_roles WHERE rolname=current_user AND (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls)").fetchone()[0],0)
  self.deny('SELECT * FROM auth_users')
  self.deny("SET LOCAL session_replication_role='replica'")

 def test_lock_timeout_has_no_partial_changes(self):
  a=self.connect();b=self.connect();before=self.events()
  try:
   self.employee(a)
   b.execute("SET LOCAL lock_timeout='100ms'")
   with self.assertRaises(psycopg.errors.LockNotAvailable) as ctx:b.execute('SELECT closed_write.crew(%s,%s)',(self.ids[0],self.crew))
   self.assertEqual(ctx.exception.sqlstate,'55P03');b.rollback();a.rollback()
  finally:a.close();b.close()
  with self.fixture_connection() as c:self.assertEqual(c.execute('SELECT full_name,crew_id FROM employees WHERE id=%s',(self.ids[0],)).fetchone(),(self.name,None))
  self.assertEqual(self.events(),before)
  RECORDS.append({'kind':'bounded_busy_refusal','sqlstate':'55P03','both_rolled_back':True,'source_and_dk_unchanged':True})
