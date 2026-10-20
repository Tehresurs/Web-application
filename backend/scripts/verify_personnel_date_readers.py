"""Rollback-only validation in existing DB; synthetic employee, no account/session."""
import sys,os,json,hashlib,uuid
from pathlib import Path
from datetime import timedelta
from unittest.mock import patch
from contextlib import contextmanager
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
os.environ['APP_DB_PROFILE']='test'
from app.database.db import get_connection
os.environ.update(DB_NAME='ai_excel_agent_test',DB_SCHEMA='test_construction_identity_stage46',APP_TEST_ALLOWED_DB_SCHEMAS='test_construction_identity_stage46')
from app.repositories import personnel_transfers as repo
from app.api.personnel_transfers import TransferRequest,ActingRequest,ActingEndRequest
from app.services import personnel_local as local
from app.services.luvr_duration import local_today
T=local_today();result={}
from app.repositories.luvr_calendar import CALENDAR_SELECT,decode_calendar_inputs
from app.services.luvr_calendar import calculate_employee_month
from app.services.personnel_positions import split_luvr_rows,dated_personnel
from app.services.luvr_month import calendar_totals,calendar_day_totals
from app.services.production_matrix import calculate_month
from app.services.deployment import build_report
from app.services.vou_data import prepare_data,VouDataError
from psycopg.rows import dict_row
from copy import deepcopy
with get_connection() as c:
 try:
  c.execute("SET LOCAL lock_timeout='3s'")
  c.execute('SELECT pg_advisory_xact_lock(20261017,29)')
  c.execute("UPDATE personnel_settings SET enabled=true,local_enabled=true,date_readers_verified=true,legacy_history_policy='LEGACY_WITH_WARNING',local_key_digest=%s WHERE id=1",(hashlib.sha256(local._sql_key.encode()).hexdigest(),))
  eid=c.execute("INSERT INTO employees(full_name,position_id,crew_id,max_shift_days,max_off_shift_days) SELECT %s,2,id,30,30 FROM crews ORDER BY id LIMIT 1 RETURNING id",('LOCAL_HR_ROLLBACK_'+uuid.uuid4().hex,)).fetchone()[0]
  c.execute("INSERT INTO employee_movements(employee_id,movement_type,transport_type,event_datetime) VALUES(%s,'ARRIVAL','SELF',%s)",(eid,str(T-timedelta(days=8))+' 07:00:00'))
  from app.repositories.production_assignments import save
  arrival=c.execute('SELECT id FROM employee_movements WHERE employee_id=%s',(eid,)).fetchone()[0]
  save(eid,{'effective_from':str(T-timedelta(days=8)),'period_kind':'ARRIVAL','arrival_movement_ref':arrival,'source_kind':'MANUAL','assignment_state':'OBJECTS','items':[{'object_id':1,'initial_category_id':1}]},connection=c)
  @contextmanager
  def connection():yield c
  with patch.object(repo,'get_connection',connection),patch.object(local,'_enabled',True):
   p=TransferRequest(position_id=3,effective_on=T-timedelta(days=5),source_position_id=2,reason='Rollback local test',request_id=uuid.uuid4(),expected_version=0)
   first=repo.execute(local._source,eid,p);assert repo.execute(local._source,eid,p)==first;result['transfer_and_replay']=True
   conflict=p.model_copy(update={'position_id':4})
   try:
    with c.transaction():repo.execute(local._source,eid,conflict)
   except ValueError:result['payload_conflict']=True
   else:raise AssertionError('Payload change accepted')
   second=TransferRequest(position_id=4,effective_on=T,reason='Dated second transfer',request_id=uuid.uuid4(),expected_version=1)
   repo.execute(local._source,eid,second)
   assert c.execute('SELECT source_position_id,source_on FROM personnel_position_events WHERE employee_id=%s AND version=2',(eid,)).fetchone()==(3,T-timedelta(days=1))
   result['backdated_predecessor']=True
   a=ActingRequest(position_id=14,starts_on=T+timedelta(days=1),ends_on=T+timedelta(days=7),reason='Rollback local acting',request_id=uuid.uuid4(),expected_version=2)
   acting=repo.execute_acting(local._source,eid,a);assert repo.execute_acting(local._source,eid,a)==acting;result['acting_and_replay']=True
   end=ActingEndRequest(ends_on=T+timedelta(days=3),reason='Rollback return to engineering',request_id=uuid.uuid4(),expected_version=3,plan={'effective_from':str(T+timedelta(days=4)),'period_kind':'ARRIVAL','arrival_movement_ref':c.execute('SELECT id FROM employee_movements WHERE employee_id=%s',(eid,)).fetchone()[0],'assignment_state':'OBJECTS','items':[{'object_id':1,'initial_category_id':1}]})
   ended=repo.execute_acting(local._source,eid,end,operation='END',target=acting['root_id']);assert repo.execute_acting(local._source,eid,end,operation='END',target=acting['root_id'])==ended;result['end_plan_and_replay']=True
   history=repo.history(eid);assert history['audit'][0]['actor_login']=='Локальное приложение';assert all(x['actor_user_id'] is None and x['audit_source']=='LOCAL_APP' for x in history['acting_audit']);result['audit_without_user']=True
   c.execute('INSERT INTO luvr_months(year,month,approver_position_snapshot,approver_name_snapshot,document_title_snapshot,developer_position_snapshot,developer_name_snapshot,agreed_position_snapshot,agreed_name_snapshot,legend_snapshot) SELECT %s,%s,approver_position,approver_name,document_title,developer_position,developer_name,agreed_position,agreed_name,legend FROM luvr_settings WHERE id=1 ON CONFLICT DO NOTHING',(T.year,T.month))
   c.execute('INSERT INTO luvr_month_employees(year,month,employee_id) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING',(T.year,T.month,eid))
   def matrix():return calculate_month(T.year,T.month,eid,connection=c)
   with c.cursor(row_factory=dict_row) as cur:
    cur.execute(CALENDAR_SELECT+' WHERE e.id=%s',(eid,));inputs=decode_calendar_inputs(cur.fetchone())
   repo.attach_context(c,[inputs])
   calendar=calculate_employee_month(inputs,T.year,T.month);lanes=split_luvr_rows(calendar,inputs)
   assert len(lanes)==2
   assert sum(calendar_totals(x['days'])['work_days_total'] for x in lanes)==calendar_totals(calendar['days'])['work_days_total']
   assert calendar_day_totals(lanes,T.year,T.month)==calendar_day_totals([calendar],T.year,T.month)
   result['luvr_no_double_days']=True
   dates=[T-timedelta(days=5),T,T+timedelta(days=2),T+timedelta(days=4)]
   expected=[3,4,14,4]
   ready=matrix()
   for day,pid in zip(dates,expected):
    dated=dated_personnel(inputs,day)
    assert dated['position_id']==(4 if pid==14 else pid)
    assert bool(dated['engineering_report_required'])==(pid!=14)
    report=build_report(day,ready,{})
    assert report['totals']['specialists']==1,(str(day),report['totals'])
    expected_name=c.execute('SELECT name FROM positions WHERE id=%s',(pid,)).fetchone()[0]
    assert all(row['position_name']==row['sources'][0]['position_name'] and all(cell['position_id']==pid for cell in row['sources']) for row in report['rows']),(str(day),report['rows'])
    cells=[r['cells'][str(day)] for e in ready['employees'] for r in e['rows'] if str(day) in r['cells']]
    assert cells and all(cell['position_id']==pid for cell in cells)
    assert all(bool(cell['report_required'])==(pid!=14) for cell in cells)
   result['matrix_and_deployment_dates']=True
   with c.cursor(row_factory=dict_row) as cur:
    cur.execute('SELECT id,name,aos_description FROM positions');positions=cur.fetchall()
    cur.execute('SELECT id,position_id,definition FROM personnel_position_definitions');definitions=cur.fetchall()
    for position in positions:position['_definitions']={v['id']:v['definition'] for v in definitions if v['position_id']==position['id']}
    cur.execute('SELECT id,name,parent_id,sort_order FROM object_categories');categories=cur.fetchall()
   vou_checks=[]
   for day in dates:
    daily=deepcopy(ready)
    for employee in daily['employees']:
     for row in employee['rows']:row['cells']={d:cell for d,cell in row['cells'].items() if d==str(day)}
    try:
     vou=prepare_data(daily,positions,categories,[])
     cents=sum(cell['share_cents'] for e in daily['employees'] for r in e['rows'] for cell in r['cells'].values())
     assert vou['total_cents']==cents,(str(day),vou['total_cents'],cents,vou['warnings'])
     vou_checks.append({'date':str(day),'result':'EXACT_MATRIX_SUM','cents':cents})
    except VouDataError as ex:
     assert ex.code=='POSITION_ORDER_NOT_AGREED',ex
     assert ex.details['position_id']==14,ex
     vou_checks.append({'date':str(day),'result':ex.code,'position_id':14})
   result['vou_dates']=vou_checks
   # A factual result arriving after assignment must remain immutable and visible.
   fact_day=T+timedelta(days=2)
   fid=c.execute("INSERT INTO daily_control_results(report_date,employee_id,object_id,subobject_id,entity_id,po_id,category_id,subcontractor_id,source_file,source_sha256) SELECT %s,%s,object_id,subobject_id,entity_id,po_id,category_id,subcontractor_id,'LOCAL_HR_DATED_CHECK.docx',%s FROM daily_control_results LIMIT 1 RETURNING id",(fact_day,eid,uuid.uuid4().hex+uuid.uuid4().hex)).fetchone()[0]
   frozen=c.execute('SELECT to_jsonb(f) FROM daily_control_results f WHERE id=%s',(fid,)).fetchone()[0]
   factual=matrix();facts=[cell for e in factual['employees'] for r in e['rows'] for cell in r['cells'].values() if cell.get('source_fact_id')==fid]
   assert len(facts)==1 and facts[0]['report_received'] and not facts[0]['report_required']
   try:
    with c.transaction():
     change=ActingRequest(position_id=14,starts_on=fact_day,ends_on=fact_day,reason='Conflict check',request_id=uuid.uuid4(),expected_version=4)
     repo.execute_acting(local._source,eid,change)
   except ValueError:pass
   else:raise AssertionError('Conflicting historical acting accepted')
   assert c.execute('SELECT to_jsonb(f) FROM daily_control_results f WHERE id=%s',(fid,)).fetchone()[0]==frozen
   result['confirmed_fact_preserved']=True
   assert c.execute("SELECT count(*) FROM personnel_position_requests WHERE actor_user_id IS NULL AND payload->>'employee_id'=%s",(str(eid),)).fetchone()[0]==4
   try:
    with c.transaction():c.execute('SELECT personnel_local_admit(%s)',('invalid',))
   except Exception as ex:
    if getattr(ex,'sqlstate',None)!='42501':raise
    result['wrong_sql_capability_rejected']=True
   else:raise AssertionError('SQL capability accepted')
 finally:c.rollback()
result['all_changes_rolled_back']=True
out=Path((ROOT/'output/security/personnel_local_current.txt').read_text(encoding='utf-8'))
(out/'dated_integration_checks.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))
