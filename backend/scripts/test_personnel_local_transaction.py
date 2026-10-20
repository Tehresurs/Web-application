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
with get_connection() as c:
 try:
  c.execute("SET LOCAL lock_timeout='3s'")
  c.execute('SELECT pg_advisory_xact_lock(20261017,29)')
  c.execute("UPDATE personnel_settings SET enabled=true,local_enabled=true,date_readers_verified=true,legacy_history_policy='LEGACY_WITH_WARNING',local_key_digest=%s WHERE id=1",(hashlib.sha256(local._sql_key.encode()).hexdigest(),))
  eid=c.execute("INSERT INTO employees(full_name,position_id,crew_id,max_shift_days,max_off_shift_days) SELECT %s,2,id,30,30 FROM crews ORDER BY id LIMIT 1 RETURNING id",('LOCAL_HR_ROLLBACK_'+uuid.uuid4().hex,)).fetchone()[0]
  c.execute("INSERT INTO employee_movements(employee_id,movement_type,transport_type,event_datetime) VALUES(%s,'ARRIVAL','SELF',%s)",(eid,str(T)+' 07:00:00'))
  @contextmanager
  def connection():yield c
  with patch.object(repo,'get_connection',connection),patch.object(local,'_enabled',True):
   p=TransferRequest(position_id=3,effective_on=T,source_position_id=2,reason='Rollback local test',request_id=uuid.uuid4(),expected_version=0)
   first=repo.execute(local._source,eid,p);assert repo.execute(local._source,eid,p)==first;result['transfer_and_replay']=True
   conflict=p.model_copy(update={'position_id':4})
   try:
    with c.transaction():repo.execute(local._source,eid,conflict)
   except ValueError:result['payload_conflict']=True
   else:raise AssertionError('Payload change accepted')
   a=ActingRequest(position_id=14,starts_on=T+timedelta(days=1),ends_on=T+timedelta(days=7),reason='Rollback local acting',request_id=uuid.uuid4(),expected_version=1)
   acting=repo.execute_acting(local._source,eid,a);assert repo.execute_acting(local._source,eid,a)==acting;result['acting_and_replay']=True
   end=ActingEndRequest(ends_on=T+timedelta(days=3),reason='Rollback return to engineering',request_id=uuid.uuid4(),expected_version=2,plan={'effective_from':str(T+timedelta(days=4)),'period_kind':'ARRIVAL','arrival_movement_ref':c.execute('SELECT id FROM employee_movements WHERE employee_id=%s',(eid,)).fetchone()[0],'assignment_state':'OBJECTS','items':[{'object_id':1}]})
   ended=repo.execute_acting(local._source,eid,end,operation='END',target=acting['root_id']);assert repo.execute_acting(local._source,eid,end,operation='END',target=acting['root_id'])==ended;result['end_plan_and_replay']=True
   history=repo.history(eid);assert history['audit'][0]['actor_login']=='Локальное приложение';assert all(x['actor_user_id'] is None and x['audit_source']=='LOCAL_APP' for x in history['acting_audit']);result['audit_without_user']=True
   assert c.execute('SELECT count(*) FROM personnel_position_requests WHERE actor_user_id IS NULL').fetchone()[0]==3
   try:
    with c.transaction():c.execute('SELECT personnel_local_admit(%s)',('invalid',))
   except Exception as ex:
    if getattr(ex,'sqlstate',None)!='42501':raise
    result['wrong_sql_capability_rejected']=True
   else:raise AssertionError('SQL capability accepted')
 finally:c.rollback()
result['all_changes_rolled_back']=True
out=Path((ROOT/'output/security/personnel_local_current.txt').read_text(encoding='utf-8'))
(out/'transaction_tests.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))
