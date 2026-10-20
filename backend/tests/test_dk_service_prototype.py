"""Isolated service proof tests; never usable against the working DB."""
import os,unittest,uuid,hashlib
from datetime import date,datetime
import psycopg
from psycopg import sql
from app.database.db import MatrixConnection
from app.services import matrix_dk as dk
from scripts import dk_service_prototype as prototype
if os.getenv('AUTH_ISOLATED_WORKER')!='1':raise RuntimeError('Restricted worker required')
class DKServiceTests(unittest.TestCase):
 config=None
 fixture_connection=None
 def connect(self,signed=False):
  cfg=self.config;key=bytes.fromhex(cfg['dk_signing_key'])
  class SignedConnection(MatrixConnection):
   def _reconcile_dk(inner):
    from psycopg.pq import TransactionStatus
    if inner.info.transaction_status!=TransactionStatus.INTRANS:return
    if inner.execute("SELECT current_setting('tehresurs.dk_calendar_dirty',true)").fetchone()[0]=='1':
     prototype.reconcile(inner,key)
     inner.execute("SELECT set_config('tehresurs.dk_calendar_dirty','0',true)")
  cls=SignedConnection if signed else psycopg.Connection
  return cls.connect(host='127.0.0.1',port=cfg['port'],dbname=cfg['databases']['stage3'],user=cfg['candidate_role'],password=cfg['candidate_password'],options='-c search_path=test_construction_identity_stage46')
 def setUp(self):
  self.key=bytes.fromhex(self.config['dk_signing_key']);self.a=date(2030,1,15);self.b=date(2030,1,16)
  with self.fixture_connection() as c:
   pid=c.execute('SELECT id FROM positions WHERE name=%s',(dk.POSITION,)).fetchone()[0]
   self.ids=[c.execute('INSERT INTO employees(full_name,position_id) VALUES(%s,%s) RETURNING id',('Prototype '+uuid.uuid4().hex,pid)).fetchone()[0] for _ in range(2)]
   c.execute('INSERT INTO luvr_months(year,month) VALUES(2030,1) ON CONFLICT DO NOTHING')
   for eid in self.ids:
    c.execute('INSERT INTO luvr_month_employees(year,month,employee_id) VALUES(2030,1,%s)',(eid,))
    for day in [self.a,self.b]:
     c.execute("INSERT INTO employee_luvr_day_overrides(employee_id,work_date,value) VALUES(%s,%s,'FULL')",(eid,day))
     c.execute('INSERT INTO production_matrix_dk(employee_id,work_date) VALUES(%s,%s)',(eid,day))
 def tearDown(self):
  with self.fixture_connection() as c:
   for table in ['rail_tickets','employee_movements','employee_absences','production_matrix_dk','employee_luvr_day_overrides','luvr_month_employees']:
    c.execute(sql.SQL('DELETE FROM {} WHERE employee_id=ANY(%s)').format(sql.Identifier(table)),(self.ids,))
   c.execute('DELETE FROM employees WHERE id=ANY(%s)',(self.ids,))
 def events(self):
  with self.fixture_connection() as c:return set(c.execute('SELECT employee_id,work_date FROM production_matrix_dk WHERE employee_id=ANY(%s)',(self.ids,)).fetchall())
 def test_employee_change(self):
  before=self.events()
  with self.connect(True) as c:c.execute("UPDATE employees SET full_name=full_name||' renamed' WHERE id=%s",(self.ids[0],))
  self.assertEqual(self.events(),before)
  with self.connect(True) as c:c.execute('UPDATE employees SET is_archived=true WHERE id=%s',(self.ids[0],))
  self.assertEqual(self.events(),{(self.ids[1],self.a),(self.ids[1],self.b)})
 def test_calendar_and_absence(self):
  with self.connect(True) as c:c.execute("UPDATE employee_luvr_day_overrides SET value='HALF' WHERE employee_id=%s AND work_date=%s",(self.ids[0],self.a))
  self.assertIn((self.ids[0],self.a),self.events())
  with self.connect(True) as c:c.execute("UPDATE employee_luvr_day_overrides SET value='TRAVEL' WHERE employee_id=%s AND work_date=%s",(self.ids[0],self.a))
  self.assertNotIn((self.ids[0],self.a),self.events());self.assertIn((self.ids[0],self.b),self.events())
  with self.connect(True) as c:c.execute("INSERT INTO employee_absences(employee_id,reason,date_from,date_to) VALUES(%s,'isolated absence',%s,%s)",(self.ids[0],self.b,self.b))
  self.assertEqual(self.events(),{(self.ids[1],self.a),(self.ids[1],self.b)})
 def test_ticket_processing(self):
  with self.connect(True) as c:c.execute("INSERT INTO rail_tickets(file_hash,source_filename,employee_id,status) VALUES(%s,'isolated.pdf',%s,'PARSED')",(hashlib.sha256(uuid.uuid4().bytes).hexdigest(),self.ids[0]))
  self.assertEqual(len(self.events()),4)
  # Confirmed state is a fixture, not a new permission to confirm tickets via API.
  with self.fixture_connection() as c:
   c.execute('DELETE FROM employee_luvr_day_overrides WHERE employee_id=%s AND work_date=%s',(self.ids[0],self.a))
   movement=c.execute("INSERT INTO employee_movements(employee_id,movement_type,transport_type,event_datetime,departure_station,arrival_station) VALUES(%s,'ARRIVAL','RAIL','2030-01-15 07:00','City',%s) RETURNING id",(self.ids[0],'\u0441\u0430\u043b\u044b\u043c')).fetchone()[0]
   ticket=c.execute("INSERT INTO rail_tickets(file_hash,source_filename,full_name,employee_id,status,movement_id,movement_type,departure_station,arrival_station,departure_datetime,arrival_datetime) VALUES(%s,'fixture.pdf','Fixture',%s,'CONFIRMED',%s,'ARRIVAL','City',%s,'2030-01-14 20:00','2030-01-15 07:00') RETURNING id",(hashlib.sha256(uuid.uuid4().bytes).hexdigest(),self.ids[0],movement,'\u0441\u0430\u043b\u044b\u043c')).fetchone()[0]
   self.assertTrue(dk.eligible(c,self.ids[0],self.a))
  with self.connect(True) as c:
   c.execute("UPDATE rail_tickets SET arrival_datetime='2030-01-15 13:00' WHERE id=%s",(ticket,))
   c.execute("UPDATE employee_movements SET event_datetime='2030-01-15 13:00' WHERE id=%s",(movement,))
  self.assertNotIn((self.ids[0],self.a),self.events());self.assertEqual(len(self.events()),3)
 def test_sql_cannot_forge_or_read_key(self):
  statements=[('DELETE FROM production_matrix_dk WHERE employee_id=%s',(self.ids[0],)),('UPDATE production_matrix_dk SET work_date=work_date WHERE false',()),('SELECT secret FROM dk_service.signing_key',()),('SELECT dk_service.context()',()),('SELECT dk_service.prune(%s,%s)',([str(self.ids[0])+':'+str(self.a)],b'x'*32)),(sql.SQL('SET ROLE {}').format(sql.Identifier(self.config['dk_owner'])),())]
  before=self.events()
  for query,args in statements:
   with self.connect() as c:
    with self.assertRaises(psycopg.errors.InsufficientPrivilege):c.execute(query,args)
  self.assertEqual(self.events(),before)
 def test_proof_bound_to_source_keys_and_transaction(self):
  with self.fixture_connection() as c:c.execute("INSERT INTO employee_absences(employee_id,reason,date_from,date_to) VALUES(%s,'isolated',%s,%s)",(self.ids[0],self.a,self.a))
  c=self.connect()
  try:
   keys,proof=prototype.prepare(c,self.key)
   c.execute('SAVEPOINT attack')
   with self.assertRaises(psycopg.errors.InsufficientPrivilege):c.execute('SELECT dk_service.prune(%s,%s)',(keys+[str(self.ids[1])+':'+str(self.a)],proof))
   c.execute('ROLLBACK TO SAVEPOINT attack')
   c.execute("UPDATE employees SET full_name=full_name||' tamper' WHERE id=%s",(self.ids[1],))
   with self.assertRaises(psycopg.errors.InsufficientPrivilege):c.execute('SELECT dk_service.prune(%s,%s)',(keys,proof))
   c.rollback()
   with self.assertRaises(psycopg.errors.InsufficientPrivilege):c.execute('SELECT dk_service.prune(%s,%s)',(keys,proof))
  finally:c.rollback();c.close()
  with self.connect() as other:
   with self.assertRaises(psycopg.errors.InsufficientPrivilege):other.execute('SELECT dk_service.prune(%s,%s)',(keys,proof))
  self.assertEqual(len(self.events()),4)
 def test_error_rolls_back_source_and_cleanup(self):
  before=self.events()
  with self.assertRaises(psycopg.errors.DivisionByZero):
   with self.connect(True) as c:
    c.execute("UPDATE employee_luvr_day_overrides SET value='TRAVEL' WHERE employee_id=%s AND work_date=%s",(self.ids[0],self.a))
    prototype.reconcile(c,self.key)
    self.assertFalse(c.execute('SELECT 1 FROM production_matrix_dk WHERE employee_id=%s AND work_date=%s',(self.ids[0],self.a)).fetchone())
    c.execute('SELECT 1/0')
  self.assertEqual(self.events(),before)
  with self.fixture_connection() as c:self.assertEqual(c.execute('SELECT value FROM employee_luvr_day_overrides WHERE employee_id=%s AND work_date=%s',(self.ids[0],self.a)).fetchone()[0],'FULL')
 def test_missing_key_fails_closed_and_rolls_back(self):
  with self.fixture_connection() as c:
   original=c.execute('SELECT full_name FROM employees WHERE id=%s',(self.ids[0],)).fetchone()[0]
   c.execute('DELETE FROM dk_service.signing_key')
  try:
   with self.assertRaises(psycopg.errors.InsufficientPrivilege):
    with self.connect(True) as c:c.execute("UPDATE employees SET full_name=full_name||' rejected' WHERE id=%s",(self.ids[0],))
   with self.fixture_connection() as c:self.assertEqual(c.execute('SELECT full_name FROM employees WHERE id=%s',(self.ids[0],)).fetchone()[0],original)
   self.assertEqual(len(self.events()),4)
  finally:
   with self.fixture_connection() as c:c.execute('INSERT INTO dk_service.signing_key VALUES(1,%s)',(self.key,))
 def test_snapshot_blocks_concurrent_calendar_writer(self):
  first=self.connect();second=self.connect();before=self.events()
  try:
   first.execute('SELECT dk_service.snapshot()')
   second.execute("SET LOCAL lock_timeout='100ms'")
   with self.assertRaises(psycopg.errors.LockNotAvailable):second.execute("UPDATE employees SET full_name=full_name||' concurrent' WHERE id=%s",(self.ids[0],))
  finally:
   second.rollback();second.close();first.rollback();first.close()
  self.assertEqual(self.events(),before)
 def test_owner_and_function_acls(self):
  with self.connect() as c:
   flags=c.execute('SELECT rolcanlogin,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=%s',(self.config['dk_owner'],)).fetchone()
   self.assertEqual(flags,(False,)*6)
   self.assertFalse(c.execute("SELECT has_table_privilege(current_user,'production_matrix_dk','DELETE')").fetchone()[0])
   self.assertFalse(c.execute("SELECT has_column_privilege(current_user,'production_matrix_dk','work_date','UPDATE')").fetchone()[0])
   entries=c.execute("SELECT p.proname,p.prosecdef,p.proconfig FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='dk_service' AND p.proname IN ('snapshot','prune')").fetchall()
   self.assertEqual(len(entries),2)
   for name,definer,settings in entries:
    self.assertTrue(definer);self.assertIn('search_path=pg_catalog, dk_service, pg_temp',settings)
   self.assertEqual(c.execute("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace CROSS JOIN LATERAL aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a WHERE n.nspname='dk_service' AND a.grantee=0 AND a.privilege_type='EXECUTE'").fetchone()[0],0)
 def test_matrix_luvr_and_vou_equal_existing_reconcile(self):
  from app.services.production_matrix import calculate_month
  from app.services.vou_data import prepare_data
  from psycopg.rows import dict_row
  def measure(c):
   matrix=calculate_month(2030,1,connection=c)
   with c.cursor(row_factory=dict_row) as cur:
    positions=cur.execute('SELECT id,name,aos_description FROM positions ORDER BY id').fetchall()
    categories=cur.execute('SELECT id,name,parent_id,sort_order FROM object_categories ORDER BY id').fetchall()
    facts=cur.execute("SELECT id,employee_id,report_date,category_id FROM daily_control_results WHERE report_date BETWEEN '2030-01-01' AND '2030-01-31'").fetchall()
   return matrix,prepare_data(matrix,positions,categories,facts)
  results=[]
  for legacy in [True,False]:
   c=self.fixture_connection() if legacy else self.connect()
   try:
    c.execute("UPDATE employee_luvr_day_overrides SET value='TRAVEL' WHERE employee_id=%s AND work_date=%s",(self.ids[0],self.a))
    if legacy:dk.reconcile(c)
    else:prototype.reconcile(c,self.key)
    results.append(measure(c))
   finally:c.rollback();c.close()
  self.assertEqual(results[0],results[1])

 def test_step35_context_changes_fail_closed(self):
  before=self.events()
  for path in ['pg_catalog', 'public,pg_catalog', 'pg_temp,pg_catalog']:
   c=self.connect()
   try:
    c.execute("SELECT set_config('search_path',%s,true)",(path,))
    with self.assertRaises(psycopg.errors.UndefinedTable):prototype.prepare(c,self.key)
   finally:c.rollback();c.close()
  self.assertEqual(self.events(),before)
 def test_step35_native_object_creation_denied(self):
  statements=['CREATE TEMP TABLE employees(id bigint)', 'CREATE TABLE public.employees(id bigint)', 'CREATE TABLE test_construction_identity_stage46.dk_shadow(id bigint)', 'CREATE SCHEMA dk_shadow']
  with self.connect() as c:
   db=c.execute('SELECT current_database()').fetchone()[0]
   self.assertFalse(c.execute("SELECT has_database_privilege(current_user,%s,'TEMP')",(db,)).fetchone()[0])
   self.assertFalse(c.execute("SELECT has_schema_privilege(current_user,'public','CREATE')").fetchone()[0])
   self.assertFalse(c.execute("SELECT has_schema_privilege(current_user,'test_construction_identity_stage46','CREATE')").fetchone()[0])
  for statement in statements:
   c=self.connect()
   try:
    with self.assertRaises(psycopg.errors.InsufficientPrivilege):c.execute(statement)
   finally:c.rollback();c.close()
  self.assertEqual(len(self.events()),4)
 def test_step35_reproduces_restore_after_prune_at_commit(self):
  # Successful test means a vulnerability was reproduced, NOT blocked.
  # Only prepare() knows the key; the SQL attacker receives its real proof.
  with self.connect(True) as c:
   c.execute("UPDATE employee_luvr_day_overrides SET value='TRAVEL' WHERE employee_id=%s AND work_date=%s",(self.ids[0],self.a))
   keys,proof=prototype.prepare(c,self.key)
   self.assertIn(str(self.ids[0])+':'+str(self.a),keys)
   c.execute('SELECT dk_service.prune(%s,%s)',(keys,proof))
   c.execute("UPDATE employee_luvr_day_overrides SET value='FULL' WHERE employee_id=%s AND work_date=%s",(self.ids[0],self.a))
   self.assertTrue(dk.eligible(c,self.ids[0],self.a))
   # SignedConnection repeats cleanup at commit: it does not restore deleted DK.
  with self.connect() as c:self.assertTrue(dk.eligible(c,self.ids[0],self.a))
  self.assertNotIn((self.ids[0],self.a),self.events())
  self.assertEqual(len(self.events()),3)
 def test_step35_reproduces_savepoint_and_repeated_source_changes(self):
  with self.connect(True) as c:
   c.execute("UPDATE employee_luvr_day_overrides SET value='TRAVEL' WHERE employee_id=%s AND work_date=%s",(self.ids[0],self.a))
   keys,proof=prototype.prepare(c,self.key)
   c.execute('SELECT dk_service.prune(%s,%s)',(keys,proof))
   c.execute('SAVEPOINT after_cleanup')
   for value in ['FULL','TRAVEL','HALF']:
    c.execute('UPDATE employee_luvr_day_overrides SET value=%s WHERE employee_id=%s AND work_date=%s',(value,self.ids[0],self.a))
   c.execute('ROLLBACK TO SAVEPOINT after_cleanup')
   c.execute("UPDATE employee_luvr_day_overrides SET value='FULL' WHERE employee_id=%s AND work_date=%s",(self.ids[0],self.a))
   c.execute('RELEASE SAVEPOINT after_cleanup')
  with self.connect() as c:self.assertTrue(dk.eligible(c,self.ids[0],self.a))
  self.assertNotIn((self.ids[0],self.a),self.events())
 def test_step35_rollback_before_cleanup_restores_dk(self):
  before=self.events()
  with self.connect(True) as c:
   c.execute('SAVEPOINT before_change')
   c.execute("UPDATE employee_luvr_day_overrides SET value='TRAVEL' WHERE employee_id=%s AND work_date=%s",(self.ids[0],self.a))
   keys,proof=prototype.prepare(c,self.key)
   c.execute('SELECT dk_service.prune(%s,%s)',(keys,proof))
   c.execute('ROLLBACK TO SAVEPOINT before_change')
   c.execute('RELEASE SAVEPOINT before_change')
  self.assertEqual(self.events(),before)
 def test_step35_restore_before_prune_rejects_proof(self):
  before=self.events();c=self.connect()
  try:
   c.execute("UPDATE employee_luvr_day_overrides SET value='TRAVEL' WHERE employee_id=%s AND work_date=%s",(self.ids[0],self.a))
   keys,proof=prototype.prepare(c,self.key)
   c.execute("UPDATE employee_luvr_day_overrides SET value='FULL' WHERE employee_id=%s AND work_date=%s",(self.ids[0],self.a))
   with self.assertRaises(psycopg.errors.InsufficientPrivilege):c.execute('SELECT dk_service.prune(%s,%s)',(keys,proof))
  finally:c.rollback();c.close()
  self.assertEqual(self.events(),before)
