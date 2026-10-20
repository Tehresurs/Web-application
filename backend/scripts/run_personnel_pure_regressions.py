"""Autonomous regression suite. No database driver may connect."""
import sys,unittest,io,json,os
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')];os.environ.pop('DAILY_CONTROL_TEST_DB',None)
import psycopg
psycopg.connect=lambda *a,**k:(_ for _ in ()).throw(RuntimeError('No DB allowed in pure regression'))
from app.database.db import MatrixConnection
MatrixConnection.connect=staticmethod(psycopg.connect)
names=['test_personnel_positions','test_personnel_movements','test_deployment','test_deployment_analysis','test_luvr_calendar','test_luvr_month','test_luvr_day_totals','test_production_matrix','test_vou_data','test_luvr_export_table','test_luvr_export_footer','test_luvr_export_layout']
def cases(suite):
 for x in suite:
  if isinstance(x,unittest.TestSuite):yield from cases(x)
  elif not getattr(type(x),'__unittest_skip__',False) and not getattr(getattr(type(x),x._testMethodName),'__unittest_skip__',False):yield x
suite=unittest.TestSuite(cases(unittest.defaultTestLoader.loadTestsFromNames(names)));stream=io.StringIO();r=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
d=Path((ROOT/'output/security/personnel_movements_current.txt').read_text().strip());stem='pure_regressions_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ');(d/(stem+'.txt')).write_text(stream.getvalue(),encoding='utf-8');result=dict(success=r.wasSuccessful(),tests=r.testsRun,failures=len(r.failures),errors=len(r.errors),skipped=len(r.skipped),database_connection_barrier=True);(d/(stem+'.json')).write_text(json.dumps(result),encoding='utf-8');print(result)
if not r.wasSuccessful():print(stream.getvalue()[-6000:])
raise SystemExit(0 if r.wasSuccessful() else 1)
