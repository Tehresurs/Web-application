"""Explicit approved HR-only migration with fresh full backup and rollback rehearsal."""
import os,sys,json,hashlib,subprocess,getpass
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from run_auth_isolated import SOURCE,SOURCE_DB,SCHEMA,BIN,NO_WINDOW
from apply_personnel_033_034_approved import snapshot
from app.database.db import get_connection
from psycopg import sql

def main():
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--apply',action='store_true');args=p.parse_args()
    if not args.apply:raise SystemExit('Explicit --apply required')
    os.environ['APP_TEST_ALLOWED_DB_SCHEMAS']=SCHEMA
    run=ROOT/'output/security'/('personnel_local_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'));run.mkdir()
    account=os.environ.get('USERDOMAIN','')+'\\'+getpass.getuser()
    subprocess.run(['icacls',str(run),'/inheritance:r','/grant:r',account+':(OI)(CI)F'],capture_output=True,check=True,creationflags=NO_WINDOW)
    report={'applied':False,'accounts_created':False,'sessions_created':False}
    with get_connection() as c:
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        if c.execute('SELECT current_database(),current_schema()').fetchone()!=(SOURCE_DB,SCHEMA):raise RuntimeError('Wrong target')
        before=snapshot(c)
    dump=run/'before_local.dump';env=dict(os.environ);env['PGPASSWORD']=SOURCE['password']
    command=[str(BIN/'pg_dump.exe'),'-h',SOURCE['host'],'-p',str(SOURCE['port']),'-U',SOURCE['user'],'-d',SOURCE_DB,'-Fc','-f',str(dump)]
    with (run/'backup_tools.log').open('wb') as log:subprocess.run(command,env=env,stdout=log,stderr=log,check=True,creationflags=NO_WINDOW,timeout=90)
    # Parse every archived data stream, not only its table of contents. No database/server is created.
    subprocess.run([str(BIN/'pg_restore.exe'),'--file=NUL',str(dump)],capture_output=True,check=True,creationflags=NO_WINDOW,timeout=90)
    report.update(backup_path=str(dump),backup_sha256=hashlib.sha256(dump.read_bytes()).hexdigest(),archive_fully_readable=True,before=before)
    text=(ROOT/'app/database/migrations/035_personnel_local_audit.sql').read_text(encoding='utf-8')
    report['migration_sha256']=hashlib.sha256(text.encode()).hexdigest()
    try:
        # Rehearse DDL inside a transaction that is always rolled back.
        for rehearsal in (True,False):
            with get_connection() as c:
                c.execute("SET LOCAL lock_timeout='3s'");c.execute("SET LOCAL statement_timeout='30s'")
                c.execute('SELECT pg_advisory_xact_lock(20261017,29)')
                if c.execute("SELECT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='personnel_settings' AND column_name='local_enabled')").fetchone()[0]:raise RuntimeError('035 already installed')
                current=snapshot(c)
                if current!=before:raise RuntimeError('Source changed during backup; refusing migration')
                c.execute(sql.SQL(text.replace('__SCHEMA__',sql.Identifier(SCHEMA).as_string(c))))
                if rehearsal:
                    c.rollback();report['ddl_rehearsal_rolled_back']=True
                else:
                    report['after_ddl']=snapshot(c)
        report['applied']=True
    finally:
        (run/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
        (ROOT/'output/security/personnel_local_current.txt').write_text(str(run),encoding='utf-8')
    print(json.dumps({'report':str(run/'report.json'),'applied':report['applied'],'archive_fully_readable':True,'rehearsal_rolled_back':True}))

if __name__=='__main__':main()
