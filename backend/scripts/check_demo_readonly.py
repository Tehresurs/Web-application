"""Read-only integration checks against 8001 data; optional localhost test UI."""
import argparse
import asyncio
import base64
import json
import os
from pathlib import Path
import secrets
import sys
from tempfile import TemporaryDirectory
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ['APP_DB_PROFILE']='test'
from app.main import app
os.environ.update(DB_NAME='ai_excel_agent_test',DB_SCHEMA='test_construction_identity_stage46',
                  APP_TEST_ALLOWED_DB_SCHEMAS='test_construction_identity_stage46')
from app.access_context import read_only_request
from app.database.db import get_connection
from app.demo_access import DemoAccess,make_user
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
from test_demo_access import request
from psycopg import sql
from psycopg.errors import ReadOnlySqlTransaction


def fingerprint():
    token=read_only_request.set(True)
    try:
        with get_connection() as conn:
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            names=conn.execute("SELECT tablename FROM pg_tables WHERE schemaname=current_schema() ORDER BY tablename").fetchall()
            result={}
            for (name,) in names:
                query=sql.SQL("SELECT count(*),md5(COALESCE(string_agg(md5(to_jsonb(t)::text),'' ORDER BY md5(to_jsonb(t)::text)),'')) FROM {} t").format(sql.Identifier(name))
                result[name]=conn.execute(query).fetchone()
            return result
    finally:read_only_request.reset(token)


def connection_check():
    token=read_only_request.set(True)
    try:
        with get_connection() as conn:
            assert conn.execute('SHOW transaction_read_only').fetchone()[0]=='on'
            try:conn.execute('UPDATE positions SET name=name WHERE false')
            except ReadOnlySqlTransaction:conn.rollback()
            else:raise AssertionError('Database accepted an UPDATE in viewer transaction')
    finally:read_only_request.reset(token)


async def check(gate,authorization):
    before=fingerprint();connection_check()
    with get_connection() as conn:
        conn.execute('SET TRANSACTION READ ONLY')
        eid=conn.execute('SELECT id FROM employees ORDER BY id LIMIT 1').fetchone()[0]
        ticket=conn.execute('SELECT id FROM rail_tickets ORDER BY id LIMIT 1').fetchone()[0]
        fact=conn.execute('SELECT id FROM daily_control_results ORDER BY id LIMIT 1').fetchone()[0]
    paths=['/','/api/demo/me','/api/employees','/api/positions','/api/objects','/api/subobjects?include_inactive=true',
      '/api/object-categories','/api/po-types','/api/crews','/api/construction-entities',
      '/api/construction-entities/environment','/api/production-matrix?year=2026&month=10',
      '/api/production-matrix/capabilities','/api/luvr/month?year=2026&month=10',
      '/api/luvr/month/settings','/api/luvr/month/header-snapshot?year=2026&month=10',
      '/api/daily-control-results?date_from=2026-10-01&date_to=2026-10-31',
      f'/api/daily-control-results/facts/{fact}',f'/api/employees/{eid}/assignments',
      f'/api/employees/{eid}/production-assignments?date_from=2026-10-01&date_to=2026-10-31',f'/api/employees/{eid}/production-matrix-overrides?date_from=2026-10-01&date_to=2026-10-31',
      f'/api/employees/{eid}/absences',f'/api/employees/{eid}/luvr/calendar?year=2026&month=10',
      *[f'/api/employees/{eid}/luvr/'+s for s in ['movements','sick-periods','duration-exceptions','day-overrides']],
      '/api/rail-tickets',f'/api/rail-tickets/{ticket}',
      '/api/deployment/report?date=2026-10-18','/api/deployment/analysis?date=2026-10-18',
      '/api/vou/settings','/api/vou/reports','/static/js/demo_viewer.js','/static/css/demo_viewer.css']
    errors=[]
    for path in paths:
        try:
            status,_,body=await request(gate,path,authorization=authorization)
            if status!=200:errors.append((path,status,body.decode(errors='replace')[:150]))
        except Exception as exc:errors.append((path,type(exc).__name__,str(exc)[:180]))
    for method in ['POST','PUT','PATCH','DELETE']:
        status,_,_=await request(gate,'/api/employees',method,authorization)
        assert status==403
    after=fingerprint()
    assert before==after,'Business table fingerprints changed during check'
    print(json.dumps(dict(get_requests=len(paths),errors=errors,business_tables_checked=len(before),
      table_fingerprints_unchanged=True,database_update_blocked=True,mutating_methods_blocked=True),ensure_ascii=False),flush=True)
    if errors:raise SystemExit(1)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--serve',action='store_true');args=parser.parse_args()
    with TemporaryDirectory(prefix='tehresurs-demo-check-') as folder:
        password=secrets.token_urlsafe(28)
        authorization='Basic '+base64.b64encode(('viewer@example.test:'+password).encode()).decode()
        users=Path(folder)/'users.json';users.write_text(json.dumps({'users':{'viewer@example.test':make_user(password)}}),encoding='utf-8')
        gate=DemoAccess(app,users,{'localhost','127.0.0.1'})
        if args.serve:
            output=Path(__file__).resolve().parents[1]/'output/demo-check';output.mkdir(parents=True,exist_ok=True)
            connection=output/'browser.json';connection.write_text(json.dumps({'authorization':authorization}),encoding='utf-8')
            try:
                import uvicorn
                uvicorn.run(gate,host='127.0.0.1',port=18001,proxy_headers=False,access_log=False)
            finally:connection.unlink(missing_ok=True)
        else:asyncio.run(check(gate,authorization))


if __name__=='__main__':main()
