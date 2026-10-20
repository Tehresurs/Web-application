"""Explicit loopback-only HR launch. No global authorization changes."""
import os,sys
from pathlib import Path
backend=Path(__file__).resolve().parent/'backend'
os.chdir(backend);sys.path.insert(0,str(backend))
os.environ['APP_DB_PROFILE']='test'
from app.main import app
os.environ.update(DB_NAME='ai_excel_agent_test',DB_SCHEMA='test_construction_identity_stage46',APP_TEST_ALLOWED_DB_SCHEMAS='test_construction_identity_stage46',PERSONNEL_LOCAL_8001='1')
from app.services.personnel_local import activate
activate()
import uvicorn
uvicorn.run(app,host='127.0.0.1',port=8001,proxy_headers=False,access_log=False)
