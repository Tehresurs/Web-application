"""Explicit protected launcher. Default is --check; never imported by the live launcher."""
import argparse,os,sys,json,hashlib,socket,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parent
BACKEND=ROOT/'backend'
SCHEMA='test_construction_identity_stage46'

def build(isolated=False):
    if Path(sys.executable).resolve()!=(ROOT/'backend.venv/Scripts/python.exe').resolve():raise RuntimeError('Independent interpreter required')
    if Path(sys.prefix).resolve()!=(ROOT/'backend.venv').resolve():raise RuntimeError('Independent prefix required')
    if any(str(p).replace('\\','/').lower().startswith('c:/projects/excel-ai-agent/') for p in sys.path):raise RuntimeError('Old project path refused')
    os.chdir(BACKEND);sys.path.insert(0,str(BACKEND))
    if isolated:
        from scripts.auth_launch_test_adapter import build_isolated
        app,target=build_isolated()
    else:
        os.environ['APP_DB_PROFILE']='test'
        from app.main import app as base
        os.environ.update(DB_NAME='ai_excel_agent_test',DB_SCHEMA=SCHEMA,APP_TEST_ALLOWED_DB_SCHEMAS=SCHEMA)
        from app.access_context import read_only_request
        from app.database.db import get_connection
        ctx=read_only_request.set(True)
        try:
            with get_connection() as c:
                target=tuple(c.execute('SELECT current_database(),current_schema()').fetchone())
                if target!=('ai_excel_agent_test',SCHEMA) or c.execute('SHOW transaction_read_only').fetchone()[0]!='on':raise RuntimeError('Invalid target')
        finally:read_only_request.reset(ctx)
        from app.auth_ui import create_auth_ui
        app=create_auth_ui(base)
    from app.auth_ui import AuthUI
    from app.auth_protected import ProtectedApp
    if not isinstance(app,AuthUI) or not isinstance(app.protected,ProtectedApp):raise RuntimeError('Protected wrapper missing')
    import argon2,uvicorn
    return app,target

def main():
    parser=argparse.ArgumentParser()
    mode=parser.add_mutually_exclusive_group();mode.add_argument('--check',action='store_true');mode.add_argument('--start',action='store_true')
    parser.add_argument('--isolated-test',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--port',type=int,default=8001,help=argparse.SUPPRESS)
    args=parser.parse_args()
    if args.isolated_test:
        if os.getenv('AUTH_ISOLATED_WORKER')!='1' or args.port in (8000,8001) or not 1024<=args.port<=65535:raise RuntimeError('Isolated harness required')
    elif args.port!=8001:raise RuntimeError('Production port is fixed at 8001')
    app,target=build(args.isolated_test)
    info=dict(mode='isolated' if args.isolated_test else 'authenticated',database=target[0],schema=target[1],python=sys.executable,protected=True,host='127.0.0.1',port=args.port)
    if not args.start:
        print(json.dumps(dict(info,server_started=False,read_only_check=True)));return
    # No owner replacement or process termination. Uvicorn also fails if a bind races.
    with socket.socket() as probe:
        probe.bind(('127.0.0.1',args.port))
    state=BACKEND/'output/launcher_8001'/('authenticated-'+str(args.port)+'.json');state.parent.mkdir(parents=True,exist_ok=True)
    info.update(pid=os.getpid(),launcher=str(Path(__file__).resolve()),launcher_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    temp=state.with_suffix('.'+uuid.uuid4().hex+'.tmp');temp.write_text(json.dumps(info),encoding='utf-8');os.replace(temp,state)
    try:
        import uvicorn
        if args.isolated_test:
            import threading,time
            stopfile=state.with_suffix('.stop')
            stopfile.unlink(missing_ok=True)
            server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=args.port,reload=False,workers=1,proxy_headers=False,access_log=False,lifespan='off'))
            def watch():
                while not server.should_exit:
                    if stopfile.exists():server.should_exit=True;return
                    time.sleep(.1)
            threading.Thread(target=watch,daemon=True).start()
            try:server.run()
            finally:server.should_exit=True;stopfile.unlink(missing_ok=True)
        else:uvicorn.run(app,host='127.0.0.1',port=args.port,reload=False,workers=1,proxy_headers=False,access_log=False)
    finally:
        if state.is_file() and json.loads(state.read_text()).get('pid')==os.getpid():state.unlink()

if __name__=='__main__':
    try:main()
    except Exception:
        print('Protected launch check/start failed. Details suppressed to protect configuration.',file=sys.stderr);raise SystemExit(1)
