"""Probe the real launcher without starting its HTTP server; DB reads only."""
import os,sys,runpy,json,hashlib,importlib,importlib.metadata
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];BACKEND=ROOT/'backend'
EXPECTED=ROOT/'backend.venv/Scripts/python.exe';LAUNCHER=Path('C:/Projects/run_report_review_8001.py')
if Path(sys.executable).resolve()!=EXPECTED.resolve():raise RuntimeError('Use the independent 8001 interpreter')
if any(str(p).replace('\\','/').lower().startswith('c:/projects/excel-ai-agent/') for p in sys.path):raise RuntimeError('Old project in sys.path')
sys.path.insert(0,str(BACKEND))
modules=['fastapi','uvicorn','jinja2','docx','psycopg','dotenv','pypdf','multipart','openpyxl','argon2','lxml']
for name in modules:importlib.import_module(name)
import uvicorn
from app.access_context import read_only_request
captured={}
def intercept(app,**kwargs):
 if kwargs.get('host')!='127.0.0.1' or kwargs.get('port')!=8001:raise RuntimeError('Unexpected bind')
 captured['bind']=kwargs;captured['app']=app
ctx=read_only_request.set(True)
try:
 with patch.object(uvicorn,'run',side_effect=intercept):runpy.run_path(str(LAUNCHER),run_name='__main__')
 from app.database.db import get_connection
 with get_connection() as c:
  actual=c.execute('SELECT current_database(),current_schema()').fetchone()
  readonly=c.execute('SHOW transaction_read_only').fetchone()[0]
  if tuple(actual)!=('ai_excel_agent_test','test_construction_identity_stage46') or readonly!='on':raise RuntimeError('Invalid target/read-only probe')
finally:read_only_request.reset(ctx)
if 'app' not in captured:raise RuntimeError('Launcher did not reach uvicorn')
from app.services.user_auth import AuthService
s=AuthService();value='Temporary in-memory Argon2 probe';encoded=s.hash_password(value);assert s.hasher.verify(encoded,value)
from app.services.vou_excel_com import MASTER,EXPECTED_MASTER_SHA256
assert MASTER.is_file() and hashlib.sha256(MASTER.read_bytes()).hexdigest()==EXPECTED_MASTER_SHA256
versions={d.metadata['Name']:d.version for d in importlib.metadata.distributions()}
print(json.dumps({'python':sys.executable,'prefix':sys.prefix,'base_prefix':sys.base_prefix,'modules_imported':modules,'packages':versions,'database':actual[0],'schema':actual[1],'probe_transaction_read_only':readonly,'bind':captured['bind'],'launcher_sha256':hashlib.sha256(LAUNCHER.read_bytes()).hexdigest(),'argon2':True,'template_sha256_ok':True,'old_project_in_sys_path':False,'server_started':False},indent=2))
