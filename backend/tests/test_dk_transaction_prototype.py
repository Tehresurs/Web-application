"""Step 37: native SQL adversarial tests on a separate isolated clone."""
import os,unittest
import psycopg
from psycopg import sql
from test_dk_service_prototype import DKServiceTests
from scripts import dk_transaction_prototype as proto
from scripts import dk_service_prototype as legacy
from app.services import matrix_dk as dk
if os.getenv('AUTH_ISOLATED_WORKER')!='1':raise RuntimeError('Restricted worker only')
class TransactionDKTests(unittest.TestCase):
 config=None
 fixture_connection=None
 setUp=DKServiceTests.setUp
 tearDown=DKServiceTests.tearDown
 events=DKServiceTests.events
 def connect(self,signed=False):
  cfg=self.config;key=bytes.fromhex(cfg['dk_signing_key'])
  from app.database.db import MatrixConnection
  class SignedIntentConnection(MatrixConnection):
   def _reconcile_dk(inner):
    from psycopg.pq import TransactionStatus
    if inner.info.transaction_status==TransactionStatus.INTRANS and inner.execute("SELECT current_setting('tehresurs.dk_calendar_dirty',true)").fetchone()[0]=='1':
     proto.register(inner,key)
     inner.execute("SELECT set_config('tehresurs.dk_calendar_dirty','0',true)")
  connector=SignedIntentConnection.connect if signed else psycopg.connect
  return connector(host='127.0.0.1',port=cfg['port'],dbname=cfg['databases']['stage37'],user=cfg['candidate_role'],password=cfg['candidate_password'],options='-c search_path=test_construction_identity_stage46')
 def change(self,c,value):
  c.execute('UPDATE employee_luvr_day_overrides SET value=%s WHERE employee_id=%s AND work_date=%s',(value,self.ids[0],self.a))
 def apply(self,c):c.execute('SET CONSTRAINTS ALL IMMEDIATE')
 def test_intent_is_not_deletion_and_commit_applies(self):
  with self.connect() as c:
   self.change(c,'TRAVEL');proto.register(c,self.key)
   self.assertTrue(c.execute('SELECT 1 FROM production_matrix_dk WHERE employee_id=%s AND work_date=%s',(self.ids[0],self.a)).fetchone())
  self.assertNotIn((self.ids[0],self.a),self.events());self.assertEqual(len(self.events()),3)
 def test_raw_commit_without_intent_rejected_despite_dirty_guc(self):
  before=self.events();c=self.connect()
  try:
   self.change(c,'TRAVEL');c.execute("SELECT set_config('tehresurs.dk_calendar_dirty','0',true)")
   with self.assertRaises(psycopg.errors.InsufficientPrivilege):c.execute('COMMIT')
  finally:c.rollback();c.close()
  self.assertEqual(self.events(),before)
  with self.connect() as c:self.assertTrue(dk.eligible(c,self.ids[0],self.a))
 def test_restore_invalidates_intent_before_commit(self):
  before=self.events();c=self.connect()
  try:
   self.change(c,'TRAVEL');proto.register(c,self.key);self.change(c,'FULL')
   with self.assertRaises(psycopg.errors.InsufficientPrivilege):c.commit()
  finally:c.rollback();c.close()
  self.assertEqual(self.events(),before)
 def test_attack_after_early_cleanup_blocked_and_rolled_back(self):
  before=self.events()
  with self.assertRaises(psycopg.errors.InsufficientPrivilege):
   with self.connect() as c:
    self.change(c,'TRAVEL');proto.register(c,self.key);self.apply(c)
    self.change(c,'FULL')
  self.assertEqual(self.events(),before)
 def test_savepoint_after_cleanup_cannot_unseal(self):
  c=self.connect()
  try:
   self.change(c,'TRAVEL');proto.register(c,self.key);self.apply(c)
   c.execute('SAVEPOINT after_cleanup')
   for value in ['FULL','HALF','TRAVEL']:
    with self.assertRaises(psycopg.errors.InsufficientPrivilege):self.change(c,value)
    c.execute('ROLLBACK TO SAVEPOINT after_cleanup')
   c.execute('SET CONSTRAINTS ALL DEFERRED')
   with self.assertRaises(psycopg.errors.InsufficientPrivilege):self.change(c,'FULL')
  finally:c.rollback();c.close()
  self.assertEqual(len(self.events()),4)
 def test_savepoint_before_cleanup_restores_state_and_marks(self):
  before=self.events()
  with self.connect() as c:
   c.execute('SAVEPOINT before_cleanup');self.change(c,'TRAVEL');proto.register(c,self.key);self.apply(c)
   c.execute('ROLLBACK TO SAVEPOINT before_cleanup');c.execute('RELEASE SAVEPOINT before_cleanup')
   self.change(c,'HALF');proto.register(c,self.key)
  self.assertEqual(self.events(),before)
 def test_nested_transactions_only_outer_commit_deletes(self):
  c=self.connect()
  try:
   with c.transaction():
    with c.transaction():self.change(c,'TRAVEL');proto.register(c,self.key)
    self.assertTrue(c.execute('SELECT 1 FROM production_matrix_dk WHERE employee_id=%s AND work_date=%s',(self.ids[0],self.a)).fetchone())
    self.change(c,'FULL');self.change(c,'HALF');proto.register(c,self.key)
  finally:c.close()
  self.assertEqual(len(self.events()),4)
 def test_immediate_without_intent_fails_closed(self):
  before=self.events()
  with self.assertRaises(psycopg.errors.InsufficientPrivilege):
   with self.connect() as c:self.change(c,'TRAVEL');self.apply(c)
  self.assertEqual(self.events(),before)
 def test_closed_internals_legacy_prune_and_public(self):
  statements=['DELETE FROM production_matrix_dk','UPDATE production_matrix_dk SET work_date=work_date','UPDATE dk_service.tx_state SET sealed=false','DELETE FROM dk_service.tx_state','SELECT * FROM dk_service.tx_state','SELECT dk_service.tx_context()','SELECT dk_service.finish()',"SELECT dk_service.prune(ARRAY[]::text[],decode(repeat('00',32),'hex'))",'ALTER TABLE employees DISABLE TRIGGER ALL','CREATE TEMP TABLE employees(id bigint)']
  for query in statements:
   c=self.connect()
   try:
    with self.assertRaises(psycopg.errors.InsufficientPrivilege):c.execute(query)
   finally:c.rollback();c.close()
  with self.connect() as c:
   self.assertEqual(c.execute("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace CROSS JOIN LATERAL aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a WHERE n.nspname='dk_service' AND a.grantee=0 AND a.privilege_type='EXECUTE'").fetchone()[0],0)
 def test_search_path_cannot_spoof_signer_and_forgery_denied(self):
  before=self.events()
  with self.connect() as c:
   c.execute('SET LOCAL search_path=pg_temp,public,pg_catalog')
   proto.register(c,self.key)
  self.assertEqual(self.events(),before)
  c=self.connect()
  try:
   self.change(c,'TRAVEL')
   with self.assertRaises(psycopg.errors.InsufficientPrivilege):c.execute('SELECT dk_service.register_intent(%s,%s)',([str(self.ids[1])+':'+str(self.a)],b'x'*32))
  finally:c.rollback();c.close()
 def test_concurrent_candidate_writer_blocks_before_mutation(self):
  a=self.connect();b=self.connect();before=self.events()
  try:
   self.change(a,'TRAVEL');proto.register(a,self.key)
   b.execute("SET LOCAL lock_timeout='100ms'")
   with self.assertRaises(psycopg.errors.LockNotAvailable):
    b.execute('UPDATE employees SET full_name=full_name WHERE id=%s',(self.ids[1],))
  finally:b.rollback();b.close();a.rollback();a.close()
  self.assertEqual(self.events(),before)
 def test_error_after_apply_rolls_back_sources_and_seal(self):
  before=self.events()
  with self.assertRaises(psycopg.errors.DivisionByZero):
   with self.connect() as c:
    self.change(c,'TRAVEL');proto.register(c,self.key);self.apply(c);c.execute('SELECT 1/0')
  with self.connect() as c:self.change(c,'HALF');proto.register(c,self.key)
  self.assertEqual(self.events(),before)
 def test_final_results_equal_legacy_matrix_luvr_vou(self):
  from app.services.production_matrix import calculate_month
  from app.services.vou_data import prepare_data
  from psycopg.rows import dict_row
  def measure(c):
   events=c.execute('SELECT employee_id,work_date FROM production_matrix_dk ORDER BY employee_id,work_date').fetchall()
   matrix=calculate_month(2030,1,connection=c)
   with c.cursor(row_factory=dict_row) as cur:
    positions=cur.execute('SELECT id,name,aos_description FROM positions ORDER BY id').fetchall()
    categories=cur.execute('SELECT id,name,parent_id,sort_order FROM object_categories ORDER BY id').fetchall()
    facts=cur.execute("SELECT id,employee_id,report_date,category_id FROM daily_control_results WHERE report_date BETWEEN '2030-01-01' AND '2030-01-31'").fetchall()
   return events,matrix,prepare_data(matrix,positions,categories,facts)
  results=[]
  for old in [True,False]:
   c=self.fixture_connection() if old else self.connect()
   try:
    self.change(c,'TRAVEL')
    if old:dk.reconcile(c)
    else:proto.register(c,self.key);self.apply(c)
    results.append(measure(c))
   finally:c.rollback();c.close()
  self.assertEqual(results[0],results[1])

 def test_early_apply_then_commit_succeeds_once(self):
  with self.connect() as c:
   self.change(c,'TRAVEL');proto.register(c,self.key);self.apply(c)
   c.execute('SET CONSTRAINTS ALL DEFERRED')
  self.assertEqual(len(self.events()),3)
 def test_old_receipt_rejected_after_savepoint_rollback_and_new_revision(self):
  before=self.events();c=self.connect()
  try:
   c.execute('SAVEPOINT old_branch');self.change(c,'TRAVEL');keys,proof=proto.prepare(c,self.key)
   c.execute('ROLLBACK TO SAVEPOINT old_branch');self.change(c,'TRAVEL')
   with self.assertRaises(psycopg.errors.InsufficientPrivilege):c.execute('SELECT dk_service.register_intent(%s,%s)',(keys,proof))
  finally:c.rollback();c.close()
  self.assertEqual(self.events(),before)
 def test_sealed_survives_client_guc_and_named_constraints(self):
  before=self.events();c=self.connect()
  try:
   self.change(c,'TRAVEL');proto.register(c,self.key)
   c.execute('SET CONSTRAINTS dk_service.dk_finish IMMEDIATE')
   c.execute("SELECT set_config('tehresurs.dk_calendar_dirty','0',true)")
   c.execute("SELECT set_config('dk_service.sealed','false',true)")
   c.execute('SET CONSTRAINTS dk_service.dk_finish DEFERRED')
   with self.assertRaises(psycopg.errors.InsufficientPrivilege):self.change(c,'FULL')
  finally:c.rollback();c.close()
  self.assertEqual(self.events(),before)

 # Same canonical employee/ticket/absence scenarios as step 33, now with intent-only MatrixConnection.
 test_employee_update_and_archive=DKServiceTests.test_employee_change
 test_ticket_processing_with_intent_connection=DKServiceTests.test_ticket_processing
 test_calendar_half_travel_absence_with_intent_connection=DKServiceTests.test_calendar_and_absence
 def test_nested_matrix_connection_registers_without_early_delete(self):
  with self.connect(True) as c:
   with c.transaction():
    with c.transaction():self.change(c,'TRAVEL')
    self.assertTrue(c.execute('SELECT 1 FROM production_matrix_dk WHERE employee_id=%s AND work_date=%s',(self.ids[0],self.a)).fetchone())
    self.change(c,'FULL')
  self.assertEqual(len(self.events()),4)
