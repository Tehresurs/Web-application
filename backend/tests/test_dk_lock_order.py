"""Step 40: bounded, trigger-backed lock schedules; isolated worker only."""
import os,json,time,threading,uuid,unittest
import psycopg
from test_dk_service_prototype import DKServiceTests
from app.services import matrix_dk
from scripts import dk_transaction_prototype as proto
if os.getenv('AUTH_ISOLATED_WORKER')!='1':raise RuntimeError('Isolated worker only')
RECORDS=[]
class LockOrderTests(unittest.TestCase):
 config=None
 setUp=DKServiceTests.setUp
 tearDown=DKServiceTests.tearDown
 events=DKServiceTests.events
 def open(self,mode,fixture=False):
  cfg=self.config;candidate=mode=='new' and not fixture
  return psycopg.connect(host='127.0.0.1',port=cfg['port'],dbname=cfg['databases']['stage37' if mode=='new' else 'stage3'],user=cfg['candidate_role'] if candidate else cfg['role'],password=cfg['candidate_password'] if candidate else cfg['password'],options='-c search_path=test_construction_identity_stage46 -c lock_timeout=4000 -c statement_timeout=8000',connect_timeout=3)
 def trial(self,mode,kind,repeat):
  self.fixture_connection=lambda:self.open(mode,True)
  self._fixture_setup()
  record={'mode':mode,'scenario':kind,'repeat':repeat,'events':[],'locks':[],'outcomes':{}}
  gate=threading.Event();ready=threading.Event();started=threading.Event();connections={};mutex=threading.Lock();origin=time.monotonic()
  def log(actor,event):
   with mutex:record['events'].append({'actor':actor,'event':event,'ms':round((time.monotonic()-origin)*1000,3)})
  with self.open(mode,True) as c:
   ticket=c.execute("INSERT INTO rail_tickets(file_hash,source_filename,employee_id,status) VALUES(%s,'step40.pdf',%s,'PARSED') RETURNING id",(uuid.uuid4().hex+uuid.uuid4().hex,self.ids[0])).fetchone()[0]
   crew=c.execute("SELECT crew_id FROM employees WHERE id=%s",(self.ids[0],)).fetchone()[0]
   object_id=c.execute('SELECT id FROM construction_objects ORDER BY id LIMIT 1').fetchone()[0]
   name=c.execute('SELECT full_name FROM employees WHERE id=%s',(self.ids[0],)).fetchone()[0]
  before=self.events()
  def actor(label):
   c=self.open(mode);connections[label]=c
   try:
    record[label+'_pid']=c.info.backend_pid
    if label=='holder':
     if kind=='ticket_identity':
      c.execute('SELECT pg_advisory_xact_lock(20261007,1601)');c.execute('SELECT pg_advisory_xact_lock(20261013,24)');c.execute('SELECT id FROM rail_tickets WHERE id=%s FOR UPDATE',(ticket,));log(label,'identity24 and other ticket row held')
     else:
      c.execute('SELECT id FROM employees WHERE id=%s FOR '+('UPDATE' if kind=='crew_update' else 'SHARE'),(self.ids[0],));log(label,'employee row held')
     ready.set()
     if not gate.wait(5):raise RuntimeError('Synchronization deadline')
     if kind=='ticket_identity':c.execute('UPDATE rail_tickets SET object_id=%s WHERE id=%s',(object_id,ticket))
     elif kind=='crew_update':c.execute('UPDATE employees SET crew_id=crew_id WHERE id=%s',(self.ids[0],))
     elif kind=='share_cycle':c.execute("INSERT INTO employee_movements(employee_id,movement_type,transport_type,event_datetime) VALUES(%s,'ARRIVAL','RAIL','2030-01-15 07:00')",(self.ids[0],))
     log(label,'post-gate SQL completed')
    else:
     if not ready.wait(5):raise RuntimeError('Holder deadline')
     started.set();log(label,'source DML started')
     if kind=='ticket_identity':c.execute("INSERT INTO rail_tickets(file_hash,source_filename,employee_id,status) VALUES(%s,'step40-new.pdf',%s,'PARSED')",(uuid.uuid4().hex+uuid.uuid4().hex,self.ids[0]))
     else:c.execute("UPDATE employees SET full_name=full_name||' step40' WHERE id=%s",(self.ids[0],))
     log(label,'source DML completed')
    if mode=='new':
     if c.execute("SELECT current_setting('tehresurs.dk_calendar_dirty',true)").fetchone()[0]=='1':proto.register(c,self.key)
    elif c.execute("SELECT current_setting('tehresurs.dk_calendar_dirty',true)").fetchone()[0]=='1':matrix_dk.reconcile(c)
    c.commit();record['outcomes'][label]={'result':'COMMIT','sqlstate':None};log(label,'COMMIT')
   except Exception as e:
    c.rollback();record['outcomes'][label]={'result':'ROLLBACK','sqlstate':getattr(e,'sqlstate',None),'error':type(e).__name__};log(label,'ROLLBACK')
   finally:c.close()
  threads=[threading.Thread(target=actor,args=(label,),daemon=True) for label in ['holder','writer']]
  try:
   for t in threads:t.start()
   self.assertTrue(started.wait(5))
   with self.open(mode,True) as observer:
    observer.autocommit=True
    record['deadlock_timeout']=observer.execute('SHOW deadlock_timeout').fetchone()[0]
    deadline=time.monotonic()+2.5
    while time.monotonic()<deadline:
     pids=[record.get('holder_pid',0),record.get('writer_pid',0)]
     rows=observer.execute("SELECT pid,locktype,mode,granted,classid::bigint,objid::bigint,transactionid::text FROM pg_locks WHERE pid=ANY(%s) AND (locktype IN ('advisory','transactionid','tuple')) ORDER BY pid,locktype,granted",(pids,)).fetchall()
     waits=[r for r in rows if r[0]==record.get('writer_pid') and not r[3]]
     if waits:
      record['locks']=[list(r) for r in rows];log('observer','writer waiting; release holder');break
     time.sleep(.02)
    self.assertTrue(record['locks'],'Expected controlled wait not observed')
   gate.set()
   for t in threads:t.join(11)
   self.assertFalse(any(t.is_alive() for t in threads),'Bounded actors did not finish')
   states=[v['sqlstate'] for v in record['outcomes'].values()]
   record['deadlock']='40P01' in states
   if kind=='share_wait':self.assertEqual(states,[None,None])
   else:self.assertEqual(sorted(str(v) for v in states),['40P01','None'])
   self.assertEqual(self.events(),before)
   with self.open(mode,True) as c:
    actual=c.execute('SELECT full_name,crew_id FROM employees WHERE id=%s',(self.ids[0],)).fetchone()
    self.assertEqual(actual[0],name+(' step40' if record['outcomes']['writer']['result']=='COMMIT' and kind!='ticket_identity' else ''))
    self.assertEqual(actual[1],crew)
    ticket_object=c.execute('SELECT object_id FROM rail_tickets WHERE id=%s',(ticket,)).fetchone()[0]
    self.assertEqual(ticket_object,object_id if kind=='ticket_identity' and record['outcomes']['holder']['result']=='COMMIT' else None)
    inserted=c.execute("SELECT count(*) FROM rail_tickets WHERE employee_id=%s AND source_filename='step40-new.pdf'",(self.ids[0],)).fetchone()[0]
    self.assertEqual(inserted,int(kind=='ticket_identity' and record['outcomes']['writer']['result']=='COMMIT'))
    movements=c.execute('SELECT count(*) FROM employee_movements WHERE employee_id=%s',(self.ids[0],)).fetchone()[0]
    self.assertEqual(movements,int(kind=='share_cycle' and record['outcomes']['holder']['result']=='COMMIT'))
    record['verified_counts']={'new_tickets':inserted,'movements':movements,'dk':len(before)}
    for eid,day in before:self.assertTrue(matrix_dk.eligible(c,eid,day))
   record['data_and_dk_verified']=True
  finally:
   gate.set()
   for c in list(connections.values()):
    if not c.closed:
     try:c.cancel()
     except Exception:pass
   for t in threads:
    if t.is_alive():t.join(9)
   RECORDS.append(record)
   self._fixture_cleanup()
 def scenarios(self,kind):
  for mode in ['legacy','new']:
   for repeat in range(2):
    with self.subTest(mode=mode,kind=kind,repeat=repeat):self.trial(mode,kind,repeat)
 def test_ticket_identity(self):self.scenarios('ticket_identity')
 def test_crew_update(self):self.scenarios('crew_update')
 def test_share_cycle(self):self.scenarios('share_cycle')
 def test_share_wait(self):self.scenarios('share_wait')
 # Fixtures are per trial, not per outer unittest method.
 def run(self,result=None):
  setup=self.setUp;cleanup=self.tearDown
  self.setUp=lambda:None;self.tearDown=lambda:None
  self._fixture_setup=setup;self._fixture_cleanup=cleanup
  return super().run(result)
