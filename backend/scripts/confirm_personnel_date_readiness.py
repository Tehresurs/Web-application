"""Explicit confirmation from fresh dated integration evidence, never a bare flag setter."""
import sys,os,json,hashlib,subprocess
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
os.environ['APP_DB_PROFILE']='test'
from app.database.db import get_connection
os.environ.update(DB_NAME='ai_excel_agent_test',DB_SCHEMA='test_construction_identity_stage46',APP_TEST_ALLOWED_DB_SCHEMAS='test_construction_identity_stage46')
from apply_personnel_033_034_approved import snapshot

def hashes():
 paths=[*list((ROOT/'app/services').glob('*.py')),*list((ROOT/'app/repositories').glob('*.py')),ROOT/'scripts/verify_personnel_date_readers.py',ROOT/'app/database/migrations/035_personnel_local_audit.sql']
 return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}

def working():
 with get_connection() as c:
  c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
  return snapshot(c)

def main():
 import argparse
 p=argparse.ArgumentParser();p.add_argument('--activate',action='store_true');args=p.parse_args()
 out=Path((ROOT/'output/security/personnel_local_current.txt').read_text(encoding='utf-8'))
 report={'activated':False,'date':datetime.now(timezone.utc).isoformat()}
 before=working();code=hashes();report['before']=before;report['code_sha256']=code
 try:
  with (out/'dated_readiness_test.log').open('w',encoding='utf-8') as log:
   subprocess.run([sys.executable,'-B',str(ROOT/'scripts/verify_personnel_date_readers.py')],stdout=log,stderr=log,check=True,timeout=45)
  proof=json.loads((out/'dated_integration_checks.json').read_text(encoding='utf-8'))
  for key in ('transfer_and_replay','payload_conflict','backdated_predecessor','acting_and_replay','end_plan_and_replay','audit_without_user','luvr_no_double_days','matrix_and_deployment_dates','confirmed_fact_preserved','wrong_sql_capability_rejected','all_changes_rolled_back'):
   if proof.get(key) is not True:raise RuntimeError('Required dated check failed: '+key)
  if len(proof.get('vou_dates',[]))!=4 or any(x['result']!='EXACT_MATRIX_SUM' or x['cents']<=0 for x in proof['vou_dates']):raise RuntimeError('VOU dated checks incomplete')
  if hashes()!=code:raise RuntimeError('Reader code changed during verification')
  if working()!=before:raise RuntimeError('Source rows changed during rollback-only verification')
  report['dated_evidence']=proof;report['all_source_rows_unchanged']=True
  if args.activate:
   with get_connection() as c:
    c.execute("SET LOCAL lock_timeout='3s'")
    c.execute('SELECT pg_advisory_xact_lock(20261017,29)')
    if c.execute('SELECT current_database(),current_schema()').fetchone()!=('ai_excel_agent_test','test_construction_identity_stage46'):raise RuntimeError('Wrong target')
    if c.execute("SELECT to_regclass('dk_service.tx_state')").fetchone()[0] is not None:raise RuntimeError('Signed protocol needs separate integration')
    if c.execute("SELECT NOT local_enabled AND NOT enabled FROM personnel_settings WHERE id=1").fetchone()!=(True,):raise RuntimeError('Unexpected activation state')
    if hashes()!=code:raise RuntimeError('Verified code changed')
    c.execute("UPDATE personnel_settings SET date_readers_verified=true,enabled=true,local_enabled=true,legacy_history_policy='LEGACY_WITH_WARNING' WHERE id=1")
   report['activated']=True
 finally:
  (out/'dated_readiness_confirmation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'activated':report['activated'],'source_unchanged':report['all_source_rows_unchanged'],'report':str(out/'dated_readiness_confirmation.json')}))

if __name__=='__main__':main()
