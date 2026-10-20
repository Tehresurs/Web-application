"""Protected read-only entrance to 8001. This never starts Cloudflare Tunnel."""
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent
if ROOT!=Path('C:/Projects/excel-ai-agent-8001'):
    raise RuntimeError('This launcher is restricted to project 8001')
BACKEND=ROOT/'backend'
os.chdir(BACKEND)
sys.path.insert(0,str(BACKEND))
os.environ['APP_DB_PROFILE']='test'
from dotenv import load_dotenv
load_dotenv(BACKEND/'.env.demo')
from app.main import app as original_app
os.environ.update(DB_NAME='ai_excel_agent_test',DB_SCHEMA='test_construction_identity_stage46',
                  APP_TEST_ALLOWED_DB_SCHEMAS='test_construction_identity_stage46')
from app.access_context import read_only_request
from app.database.db import get_connection
token=read_only_request.set(True)
try:
    with get_connection() as connection:
        assert connection.execute("SHOW transaction_read_only").fetchone()[0]=='on'
finally:read_only_request.reset(token)
from app.demo_access import DemoAccess
users=BACKEND/'private/demo_users.json'
if not users.is_file():raise RuntimeError('Create a READ_ONLY demo user first: backend/scripts/demo_user.py')
hosts={'localhost','127.0.0.1'}
public_host=os.getenv('DEMO_PUBLIC_HOST','').strip().lower()
if public_host:
    import re
    if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?',public_host):raise RuntimeError('Invalid DEMO_PUBLIC_HOST')
    hosts.add(public_host)
app=DemoAccess(original_app,users,hosts)
if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=18001,proxy_headers=False,access_log=False)
