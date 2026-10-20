"""Step 38 bounded isolated load only. Never imports source connection settings."""
import os,json,time,math,threading,concurrent.futures,hashlib,hmac
from contextlib import contextmanager
from datetime import date
from pathlib import Path
import psycopg
from psycopg import sql
from scripts import dk_transaction_prototype as proto
from scripts import dk_service_prototype as old
from app.services import matrix_dk as dk
from scripts.pg_load_memory import sample as memory_sample
if os.getenv('AUTH_ISOLATED_WORKER')!='1':raise RuntimeError('Restricted harness required')
TABLES=old.TABLES

def run(cfg):
 out={'status':'running','series':[],'diagnostics':[],'errors':[],'baseline_authorized':cfg['load_baseline_authorized'],'source_sizes':cfg['source_sizes'],'limits':{'lock_timeout_ms':3000,'statement_timeout_ms':5000,'stop_total_ms':5000},'quantiles':'nearest-rank; p99 at n=100 has limited tail resolution','memory_note':'sum of RSS double-counts shared pages; private committed bytes sampled separately; 100ms sampling, not exact allocator peak'}
 destination=Path(cfg['load_output'])
 def save():destination.write_text(json.dumps(out,indent=2),encoding='utf-8')
 def connect(db,fixture=False,auto=False):
  if not db.startswith('auth_stage3_') or cfg['port']==int(cfg.get('source_port') or 5432):raise RuntimeError('Isolation guard')
  return psycopg.connect(host='127.0.0.1',port=cfg['port'],dbname=db,user=cfg['role'] if fixture else cfg['candidate_role'],password=cfg['password'] if fixture else cfg['candidate_password'],autocommit=auto,options='-c search_path='+old.SOURCE)
 def sizes(c):
  return {t:dict(zip(('rows','json_bytes'),c.execute(sql.SQL('SELECT count(*),coalesce(sum(octet_length(to_jsonb(t)::text)),0) FROM {} t').format(sql.Identifier(t))).fetchone())) for t in TABLES}
 def seed(db,scale,probe):
  target={t:int(cfg['source_sizes'][t]['rows'])*scale for t in TABLES}
  assert target['production_matrix_dk']==0 and target['employee_luvr_day_overrides']==0 and target['employee_absences']==0 and target['employee_duration_exceptions']==0,'Nonzero source needs new data design'
  with connect(db,True) as c:
   c.execute('TRUNCATE employees,positions CASCADE')
   c.execute("INSERT INTO positions(id,name,work_location,work_schedule,created_at,updated_at) SELECT n,CASE WHEN n=1 THEN %s ELSE 'Load position '||n END,'OFFICE','FIVE_TWO','2030-01-01','2030-01-01' FROM generate_series(1,%s) n",(dk.POSITION,target['positions']))
   c.execute("INSERT INTO employees(id,full_name,position_id,created_at,updated_at) SELECT n,'Load employee '||lpad(n::text,6,'0')||' A',1,'2030-01-01','2030-01-01' FROM generate_series(1,%s) n",(target['employees'],))
   c.execute("INSERT INTO employee_movements(id,employee_id,movement_type,transport_type,event_datetime,departure_station,arrival_station,created_at,updated_at) SELECT n,1+(n-1)%% %s,CASE WHEN n%%2=0 THEN 'ARRIVAL' ELSE 'DEPARTURE' END,'RAIL','1999-01-01','Load origin','Load destination','2030-01-01','2030-01-01' FROM generate_series(1,%s) n",(target['employees'],target['employee_movements']))
   c.execute("INSERT INTO rail_tickets(id,file_hash,source_filename,full_name,employee_id,status,created_at,updated_at) SELECT n,lpad(to_hex(n),64,'0'),'load.pdf','Synthetic',1+(n-1)%% %s,'PARSED','2030-01-01','2030-01-01' FROM generate_series(1,%s) n",(target['employees'],target['rail_tickets']))
   c.execute("INSERT INTO employee_sick_periods(id,employee_id,date_from,date_to,comment,created_at,updated_at) SELECT n,1+(n-1)%% %s,'1998-01-01','1998-01-02','Synthetic','2030-01-01','2030-01-01' FROM generate_series(1,%s) n",(target['employees'],target['employee_sick_periods']))
   # Approximate source JSON payload size without copying personal data.
   for table,column in [('employees','full_name'),('positions','aos_description'),('employee_movements','source_file'),('rail_tickets','source_filename'),('employee_sick_periods','comment')]:
    n,bytes_now=c.execute(sql.SQL('SELECT count(*),coalesce(sum(octet_length(to_jsonb(t)::text)),0) FROM {} t').format(sql.Identifier(table))).fetchone()
    pad=max(0,(int(cfg['source_sizes'][table]['json_bytes'])*scale-int(bytes_now))//max(1,n))
    if table=='employees':pad=min(pad,180)
    if pad:c.execute(sql.SQL("UPDATE {} SET {}=coalesce({},'')||repeat('X',%s)").format(sql.Identifier(table),sql.Identifier(column),sql.Identifier(column)),(pad,))
   if probe:
    for eid in range(1,probe+1):
     c.execute("INSERT INTO employee_luvr_day_overrides(employee_id,work_date,value,created_at,updated_at) VALUES(%s,'2030-01-15','FULL','2030-01-01','2030-01-01')",(eid,))
     c.execute("INSERT INTO production_matrix_dk(employee_id,work_date) VALUES(%s,'2030-01-15')",(eid,))
   return sizes(c)
 class Monitor:
  def __init__(self,db):self.db=db;self.stop=threading.Event();self.data={'samples':0,'rss_sum_peak_bytes':0,'private_sum_peak_bytes':0,'max_advisory_waiters':0,'errors':[]}
  def start(self):self.thread=threading.Thread(target=self.loop,daemon=True);self.thread.start();return self
  def loop(self):
   try:
    with connect(self.db,True,True) as c:
     while not self.stop.is_set():
      m=memory_sample(cfg['load_pg_pid']);python_memory=memory_sample(os.getpid());d=self.data;d['samples']+=1
      d['python_private_peak_bytes']=max(d.get('python_private_peak_bytes',0),python_memory['private_sum_bytes'])
      d['rss_sum_peak_bytes']=max(d['rss_sum_peak_bytes'],m['rss_sum_bytes']);d['private_sum_peak_bytes']=max(d['private_sum_peak_bytes'],m['private_sum_bytes'])
      waiters=c.execute("SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND NOT granted AND database=(SELECT oid FROM pg_database WHERE datname=current_database())").fetchone()[0]
      d['max_advisory_waiters']=max(d['max_advisory_waiters'],waiters)
      self.stop.wait(.1)
   except Exception as e:self.data['errors'].append(type(e).__name__)
  def finish(self):self.stop.set();self.thread.join(5);self.data['monitor_stopped']=not self.thread.is_alive();return self.data
 def dbstats(db):
  with connect(db,True,True) as c:
   c.execute('SELECT pg_stat_clear_snapshot()')
   return dict(zip(('temp_files','temp_bytes','deadlocks'),c.execute('SELECT temp_files,temp_bytes,deadlocks FROM pg_stat_database WHERE datname=current_database()').fetchone()))
 local=threading.local();original=dk.eligible
 def timed_eligible(*args,**kw):
  start=time.perf_counter()
  try:return original(*args,**kw)
  finally:
   if hasattr(local,'record'):local.record['eligible_ms']+=(time.perf_counter()-start)*1000;local.record['eligible_calls']+=1
 class Proxy:
  def __init__(self,c,record):self.c=c;self.record=record
  def __getattr__(self,name):return getattr(self.c,name)
  def execute(self,q,*args,**kw):
   start=time.perf_counter()
   try:return self.c.execute(q,*args,**kw)
   finally:
    if isinstance(q,str) and q.startswith('DELETE FROM production_matrix_dk'):self.record['apply_ms']+=(time.perf_counter()-start)*1000
    if q=='SELECT dk_service.tx_snapshot()':self.record['snapshot_ms']+=(time.perf_counter()-start)*1000
    if q=='SELECT dk_service.register_intent(%s,%s)':self.record['register_ms']+=(time.perf_counter()-start)*1000
  @contextmanager
  def cursor(self,*args,**kw):
   record=self.record
   with self.c.cursor(*args,**kw) as cur:
    class Cursor:
     def __getattr__(inner,name):return getattr(cur,name)
     def execute(inner,q,*a,**k):
      begin=time.perf_counter()
      try:return cur.execute(q,*a,**k)
      finally:
       if isinstance(q,str) and q.startswith('SELECT employee_id,work_date FROM production_matrix_dk'):record['snapshot_ms']+=(time.perf_counter()-begin)*1000
    yield Cursor()
 def percentile(values,p):return sorted(values)[max(0,math.ceil(len(values)*p)-1)]
 def summary(records):
  metrics={}
  for key in ['total_ms','lock_wait_ms','update_ms','maintenance_ms','snapshot_ms','eligible_ms','register_ms','commit_ms','apply_ms','eligible_calls']:
   vals=[r[key] for r in records if key in r]
   if vals:metrics[key]=dict(n=len(vals),p50=percentile(vals,.5),p95=percentile(vals,.95),p99=percentile(vals,.99),maximum=max(vals))
  return metrics
 def series(db,mode,scale,probe,writers,diagnostic=False):
  n=20 if diagnostic else (100 if not probe else 30)
  record={'mode':mode,'scale':scale,'dk_probe':probe,'writers':writers,'kind':'early_apply_diagnostic' if diagnostic else 'natural_commit','requested_n':n,'samples':[],'errors':[]}
  out['diagnostics' if diagnostic else 'series'].append(record);save()
  before=dbstats(db);stop=threading.Event();barrier=threading.Barrier(writers);monitor=Monitor(db).start()
  def writer(index):
   with connect(db,mode=='legacy') as c:
    c.execute("SET lock_timeout='3s'");c.execute("SET statement_timeout='5s'");c.commit()
    barrier.wait(timeout=20)
    for iteration in range(index,n,writers):
     if stop.is_set():break
     r={'eligible_ms':0.,'eligible_calls':0,'snapshot_ms':0.}
     if mode=='new':r['register_ms']=0.
     else:r['apply_ms']=0.
     local.record=r
     begin=time.perf_counter()
     try:
      mark=time.perf_counter();c.execute('SELECT pg_advisory_xact_lock(20261017,29)');r['lock_wait_ms']=(time.perf_counter()-mark)*1000
      mark=time.perf_counter();c.execute("UPDATE employees SET full_name=left(full_name,length(full_name)-1)||CASE WHEN right(full_name,1)='A' THEN 'B' ELSE 'A' END WHERE id=%s",(index+1,));r['update_ms']=(time.perf_counter()-mark)*1000
      mark=time.perf_counter()
      if mode=='legacy':dk.reconcile(Proxy(c,r))
      else:proto.register(Proxy(c,r),bytes.fromhex(cfg['dk_signing_key']))
      r['maintenance_ms']=(time.perf_counter()-mark)*1000
      if diagnostic:
       mark=time.perf_counter();c.execute('SET CONSTRAINTS ALL IMMEDIATE');r['apply_ms']=(time.perf_counter()-mark)*1000
      mark=time.perf_counter();c.commit();r['commit_ms']=(time.perf_counter()-mark)*1000;r['total_ms']=(time.perf_counter()-begin)*1000
      record['samples'].append(r)
      if r['total_ms']>5000:record['errors'].append({'type':'SeriousLatency','total_ms':r['total_ms']});stop.set()
     except Exception as e:
      c.rollback();record['errors'].append({'type':type(e).__name__,'sqlstate':getattr(e,'sqlstate',None)});stop.set();break
     finally:
      if hasattr(local,'record'):del local.record
  try:
   with concurrent.futures.ThreadPoolExecutor(max_workers=writers) as pool:
    list(pool.map(writer,range(writers)))
  except Exception as e:record['errors'].append({'type':type(e).__name__});stop.set()
  record['memory_locks']=monitor.finish();time.sleep(.2);after=dbstats(db);record['database_deltas']={k:after[k]-before[k] for k in before};record['completed_n']=len(record['samples']);record['metrics']=summary(record['samples']);save()
  if record['errors'] or after['deadlocks']>before['deadlocks']:raise RuntimeError('Load stopped at safety limit')
 def fingerprint_diagnostic(db,scale,probe):
  # Exact fixed-table hash expression used by the prototype, independently timed.
  parts=[]
  for table in TABLES:
   parts.append("encode(sha256(convert_to(coalesce((SELECT string_agg(to_jsonb(t)::text,E'\n' ORDER BY to_jsonb(t)::text COLLATE pg_catalog.\"C\") FROM "+old.SOURCE+'.'+table+" t),''),'UTF8')),'hex')")
  query="SELECT encode(sha256(convert_to("+"||'|'||".join(parts)+",'UTF8')),'hex')"
  times=[]
  with connect(db) as c:
   c.execute("SET LOCAL timezone='UTC'");c.execute("SET LOCAL datestyle='ISO,YMD'")
   for _ in range(20):
    start=time.perf_counter();c.execute(query).fetchone();times.append((time.perf_counter()-start)*1000)
  out.setdefault('fingerprint_diagnostics',[]).append({'scale':scale,'dk_probe':probe,'n':len(times),'p50_ms':percentile(times,.5),'p95_ms':percentile(times,.95),'p99_ms':percentile(times,.99),'max_ms':max(times)});save()
 dk.eligible=timed_eligible
 try:
  out['datasets']=[]
  modes=['new']+(['legacy'] if cfg['load_baseline_authorized'] else [])
  for scale in [1,3]:
   for probe in [0,30*scale]:
    for mode in modes:
     db=cfg['load_db_new'] if mode=='new' else cfg['load_db_legacy']
     actual=seed(db,scale,probe);out['datasets'].append({'mode':mode,'scale':scale,'dk_probe':probe,'actual':actual});save()
     if mode=='new':fingerprint_diagnostic(db,scale,probe)
     for writers in [1,5,10]:series(db,mode,scale,probe,writers)
     if mode=='new':series(db,mode,scale,probe,1,True)
  out['status']='completed'
 except Exception as e:out['status']='stopped';out['errors'].append({'type':type(e).__name__})
 finally:dk.eligible=original;save()
 return out
