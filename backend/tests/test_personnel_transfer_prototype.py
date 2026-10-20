"""Opt-in synthetic PostgreSQL temporal model; no application connection factory."""
import unittest,uuid,threading,time,json
import psycopg
CONNECT=None;REPORT=None
def configure(connect,report):
 global CONNECT,REPORT
 CONNECT,REPORT=connect,report

class PersonnelTests(unittest.TestCase):
 def setUp(self):
  if CONNECT is None:self.skipTest("Own isolated runner required")
  with CONNECT() as c:
   c.execute('TRUNCATE hr.requests,hr.events');c.execute('UPDATE hr.head SET version=0')
  self.before=self.base()
 def base(self):
  with CONNECT() as c:return c.execute('SELECT jsonb_agg(to_jsonb(e) ORDER BY id) FROM hr.employees e').fetchone()[0]
 def call(self,c,pid=2,day='2030-01-15',expected=0,rid=None,eid=1,note=None):
  return c.execute('select hr.transfer(%s,%s,%s,%s,%s,%s)',(eid,pid,day,note,rid or uuid.uuid4(),expected)).fetchone()[0]
 def resolve(self,day,eid=1):
  with CONNECT('personnel_office') as c:return c.execute('select hr.resolve(%s,%s)',(eid,day)).fetchone()[0]
 def history(self):
  with CONNECT('personnel_office') as c:return c.execute('select hr.history(1)').fetchone()[0]
 def error(self,code,fn,user='personnel_tech'):
  c=CONNECT(user)
  try:
   with self.assertRaises(psycopg.Error) as caught:fn(c)
   self.assertEqual(caught.exception.sqlstate,code)
   c.rollback()
  finally:c.close()
 def tearDown(self):self.assertEqual(self.base(),self.before,'Unrelated employee and fixture facts must stay unchanged')
 def test_01_unknown_initial_date(self):
  self.assertEqual(self.resolve('2029-12-31')['status'],'UNKNOWN_HISTORY')
  row=self.resolve('2030-01-01');self.assertTrue(row['start_unknown']);self.assertEqual(row['position_id'],1)
 def test_02_future_and_boundary(self):
  with CONNECT('personnel_tech') as c:self.call(c,day='2030-02-01')
  self.assertEqual(self.resolve('2030-01-31')['position_id'],1)
  self.assertEqual(self.resolve('2030-02-01')['position_id'],2)
 def test_03_retroactive_within_known_window(self):
  with CONNECT('personnel_tech') as c:self.call(c,day='2030-01-10')
  self.assertEqual(self.resolve('2030-01-09')['position_id'],1)
  self.assertEqual(self.resolve('2030-01-10')['position_id'],2)
 def test_04_before_baseline_rejected(self):
  for day in ('2029-12-31','2030-01-01',None):self.error('22023',lambda c:self.call(c,day=day))
 def test_05_idempotency_same_payload(self):
  rid=uuid.uuid4()
  with CONNECT('personnel_tech') as c:a=self.call(c,rid=rid)
  with CONNECT('personnel_tech') as c:b=self.call(c,rid=rid)
  self.assertEqual(a,b);self.assertEqual(len(self.history()['audit']),1)
 def test_06_reused_request_payload_rejected(self):
  rid=uuid.uuid4()
  with CONNECT('personnel_tech') as c:self.call(c,rid=rid)
  self.error('22023',lambda c:self.call(c,rid=rid,pid=3))
 def test_07_one_effective_date(self):
  with CONNECT('personnel_tech') as c:self.call(c)
  self.error('23505',lambda c:self.call(c,pid=3,expected=1))
 def test_08_stale_revision(self):
  with CONNECT('personnel_tech') as c:self.call(c)
  self.error('40001',lambda c:self.call(c,pid=3,day='2030-02-01'))
 def test_09_office_cannot_transfer(self):self.error('42501',lambda c:self.call(c),user='personnel_office')
 def test_10_no_direct_mutation_or_locks(self):
  for user in ('personnel_tech','personnel_office'):
   for statement in ("UPDATE hr.employees SET position_id=2 WHERE id=1","INSERT INTO hr.events VALUES(1,1,gen_random_uuid(),'TRANSFER',2,'2030-01-15',NULL,session_user,now())","DELETE FROM hr.events","SELECT * FROM hr.employees FOR SHARE","SELECT pg_advisory_xact_lock(20261013,24)","SELECT hr.command(1,2,'2030-01-15',NULL,gen_random_uuid(),0,'TRANSFER',NULL)","SET ROLE personnel_owner","CREATE TEMP TABLE forbidden(id int)"):
    with self.subTest(user=user,sql=statement):self.error('42501',lambda c:c.execute(statement),user)
 def test_11_inactive_and_missing_positions(self):
  for pid in (4,999):self.error('23514',lambda c:self.call(c,pid=pid))
 def test_12_correction_preserves_journal(self):
  with CONNECT('personnel_tech') as c:r=self.call(c)
  with CONNECT('personnel_review') as c:c.execute("select hr.review(1,3,'2030-01-20','Исправлена дата и должность',%s,1,'CORRECT',%s)",(uuid.uuid4(),r['root']))
  h=self.history();self.assertEqual(len(h['audit']),2);self.assertEqual(h['audit'][0]['kind'],'TRANSFER')
  self.assertEqual(self.resolve('2030-01-15')['position_id'],1);self.assertEqual(self.resolve('2030-01-20')['position_id'],3)
 def test_13_cancel_append_only(self):
  with CONNECT('personnel_tech') as c:r=self.call(c)
  with CONNECT('personnel_review') as c:c.execute("select hr.review(1,NULL,NULL,'Ошибка основания',%s,1,'CANCEL',%s)",(uuid.uuid4(),r['root']))
  self.assertEqual(len(self.history()['audit']),2);self.assertEqual(self.resolve('2030-02-01')['position_id'],1)
 def test_14_no_new_correction_permission(self):
  for user in ('personnel_tech','personnel_office'):
   self.error('42501',lambda c:c.execute("select hr.review(1,2,'2030-01-15','Основание',%s,0,'CORRECT',%s)",(uuid.uuid4(),uuid.uuid4())),user)
 def test_15_rollback(self):
  c=CONNECT('personnel_tech')
  try:
   self.call(c)
   with self.assertRaises(psycopg.errors.DivisionByZero):c.execute('select 1/0')
   c.rollback()
  finally:c.close()
  self.assertEqual(self.history()['version'],0);self.assertEqual(self.resolve('2030-02-01')['position_id'],1)
 def test_16_savepoint_and_retry(self):
  with CONNECT('personnel_tech') as c:
   c.execute('savepoint draft');rid=uuid.uuid4();a=self.call(c,rid=rid);c.execute('rollback to draft');b=self.call(c,rid=rid);c.execute('release draft')
  self.assertEqual(a,b);self.assertEqual(len(self.history()['audit']),1)
 def test_17_multiple_plans_nonoverlap(self):
  with CONNECT('personnel_tech') as c:self.call(c,pid=3,day='2030-03-01');self.call(c,pid=2,day='2030-02-01',expected=1)
  periods=self.history()['periods'];self.assertEqual(len(periods),3)
  for a,b in zip(periods,periods[1:]):self.assertEqual(a['known_to'],b['known_from'])
  self.assertEqual(self.resolve('2030-02-28')['position_id'],2);self.assertEqual(self.resolve('2030-03-01')['position_id'],3)
 def test_18_no_position_baseline(self):
  self.assertEqual(self.resolve('2030-01-01',3)['status'],'UNKNOWN_POSITION')
  with CONNECT('personnel_tech') as c:self.call(c,eid=3)
  self.assertEqual(self.resolve('2030-01-15',3)['position_id'],2)
 def test_19_closed_search_path(self):
  with CONNECT('personnel_tech') as c:c.execute('set search_path=pg_temp,public');self.call(c)
  self.assertEqual(self.resolve('2030-01-15')['position_id'],2)
 def test_20_read_only_history(self):
  with CONNECT('personnel_office') as c:
   c.execute('set transaction read only');self.assertEqual(c.execute('select hr.history(1)').fetchone()[0]['version'],0)
 def test_21_concurrent_stale_writer(self):
  a=CONNECT('personnel_tech');a_pid=a.info.backend_pid;self.call(a)
  finished=threading.Event();result={}
  def b_run():
   c=CONNECT('personnel_tech');result['pid']=c.info.backend_pid
   try:self.call(c,pid=3,day='2030-02-01');c.commit();result['outcome']='COMMIT'
   except psycopg.Error as e:result['sqlstate']=e.sqlstate;c.rollback();result['outcome']='ROLLBACK'
   finally:c.close();finished.set()
  t=threading.Thread(target=b_run,daemon=True);t.start();waits=[]
  try:
   until=time.monotonic()+1.5
   with CONNECT() as obs:
    while time.monotonic()<until:
     if result.get('pid'):
      waits=obs.execute("select classid::bigint,objid::bigint,granted from pg_locks where pid=%s and locktype='advisory'",(result['pid'],)).fetchall()
      if any(not r[2] for r in waits):break
     time.sleep(.02)
   self.assertIn((20261017,29,False),waits);self.assertFalse(any(r[2] for r in waits));a.commit()
  finally:
   a.rollback();a.close();t.join(7)
  self.assertTrue(finished.is_set());self.assertEqual(result.get('sqlstate'),'40001')
  REPORT.setdefault('concurrency',[]).append({'name':'same_employee_stale','a_pid':a_pid,'b':result,'observed_locks':waits,'a_outcome':'COMMIT'})
 def test_22_concurrent_independent_employees(self):
  a=CONNECT('personnel_tech');self.call(a);out={};ready=threading.Event()
  def run_b():
   with CONNECT('personnel_tech') as b:
    ready.set()
    try:out['result']=self.call(b,eid=2);out['outcome']='COMMIT'
    except psycopg.Error as e:out['sqlstate']=e.sqlstate;raise
  t=threading.Thread(target=run_b,daemon=True);t.start()
  try:self.assertTrue(ready.wait(2));time.sleep(.1);a.commit()
  finally:a.rollback();a.close();t.join(7)
  self.assertFalse(t.is_alive());self.assertEqual(out.get('outcome'),'COMMIT')
  REPORT.setdefault('concurrency',[]).append({'name':'independent_employees','a':'COMMIT','b':out})
 def test_23_same_position_rejected(self):self.error('22023',lambda c:self.call(c,pid=1))
 def test_24_invalid_review_target(self):
  self.error('22023',lambda c:c.execute("select hr.review(1,NULL,NULL,'Причина',%s,0,'CANCEL',%s)",(uuid.uuid4(),uuid.uuid4())),'personnel_review')
 def test_25_period_month_split_not_duplicate_people(self):
  with CONNECT('personnel_tech') as c:self.call(c)
  positions=[self.resolve('2030-01-'+str(day).zfill(2))['position_id'] for day in range(1,32)]
  self.assertEqual(positions.count(1),14);self.assertEqual(positions.count(2),17);self.assertEqual(len(positions),31)

 def test_26_correct_to_occupied_date_rejected(self):
  with CONNECT('personnel_tech') as c:
   a=self.call(c);self.call(c,pid=3,day='2030-03-01',expected=1)
  self.error('23505',lambda c:c.execute("select hr.review(1,3,'2030-03-01','Проверка конфликта',%s,2,'CORRECT',%s)",(uuid.uuid4(),a['root'])),'personnel_review')
  self.assertEqual(len(self.history()['audit']),2)
 def test_27_cancel_middle_keeps_later_transfer(self):
  with CONNECT('personnel_tech') as c:
   a=self.call(c);self.call(c,pid=3,day='2030-03-01',expected=1)
  with CONNECT('personnel_review') as c:c.execute("select hr.review(1,NULL,NULL,'Отмена ошибочного перевода',%s,2,'CANCEL',%s)",(uuid.uuid4(),a['root']))
  self.assertEqual(self.resolve('2030-02-01')['position_id'],1);self.assertEqual(self.resolve('2030-03-01')['position_id'],3)
  self.assertEqual(len(self.history()['audit']),3)
 def test_28_lock_timeout_no_partial_history(self):
  a=CONNECT('personnel_tech');self.call(a)
  b=CONNECT('personnel_tech')
  try:
   b.execute("set lock_timeout='100ms'")
   with self.assertRaises(psycopg.errors.LockNotAvailable) as caught:self.call(b,eid=2)
   self.assertEqual(caught.exception.sqlstate,'55P03');b.rollback();a.rollback()
  finally:b.close();a.close()
  self.assertEqual(self.history()['version'],0)
 def test_29_dictionary_versioning_remaining_blocker(self):
  old=self.resolve('2030-01-10')['name']
  try:
   with CONNECT() as c:c.execute("update hr.positions set name='Изменённое название' where id=1")
   self.assertNotEqual(old,self.resolve('2030-01-10')['name'])
   REPORT['dictionary_versioning_blocker_reproduced']=True
  finally:
   with CONNECT() as c:c.execute('update hr.positions set name=%s where id=1',(old,))
 def test_30_cancelled_root_not_reactivated_silently(self):
  with CONNECT('personnel_tech') as c:a=self.call(c)
  with CONNECT('personnel_review') as c:c.execute("select hr.review(1,NULL,NULL,'Отмена',%s,1,'CANCEL',%s)",(uuid.uuid4(),a['root']))
  self.error('22023',lambda c:c.execute("select hr.review(1,3,'2030-02-01','Нельзя скрыто восстановить',%s,2,'CORRECT',%s)",(uuid.uuid4(),a['root'])),'personnel_review')
 def test_31_review_reason_required(self):
  with CONNECT('personnel_tech') as c:a=self.call(c)
  self.error('22023',lambda c:c.execute("select hr.review(1,NULL,NULL,' ',%s,1,'CANCEL',%s)",(uuid.uuid4(),a['root'])),'personnel_review')
 def test_32_employee_not_found(self):self.error('P0002',lambda c:self.call(c,eid=999))
