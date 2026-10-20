"""Explicit approved 033/034 installation; no activation or account creation."""
import os,sys,json,hashlib
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from psycopg import sql

def snapshot(c):
    c.execute("SET LOCAL timezone='UTC'")
    c.execute("SET LOCAL datestyle='ISO,YMD'")
    result={}
    for schema,name in c.execute("SELECT schemaname,tablename FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema') ORDER BY 1,2").fetchall():
        result[schema+'.'+name]=list(c.execute(sql.SQL("SELECT count(*),md5(coalesce(string_agg(v,E'\\n' ORDER BY v COLLATE \"C\"),'')) FROM (SELECT row_to_json(t)::text v FROM {}.{} t) q").format(sql.Identifier(schema),sql.Identifier(name))).fetchone())
    return result

def main():
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    if not args.apply:raise SystemExit('Explicit --apply required')
    os.environ['APP_DB_PROFILE']='test'
    from app.database.db import get_connection
    os.environ.update(DB_NAME='ai_excel_agent_test',DB_SCHEMA='test_construction_identity_stage46',APP_TEST_ALLOWED_DB_SCHEMAS='test_construction_identity_stage46')
    from app.database.migrate_personnel_transfers import apply_migration,apply_movements_migration
    backup_dir=ROOT/'output/security/personnel_integration/20261020T111759Z_e62293203cff479eb9612633d6ea9327'
    manifest=backup_dir/'backup_verification.json'
    old=json.loads((backup_dir/'report.json').read_text(encoding='utf-8'))
    output=ROOT/'output/security'/('personnel_working_install_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    output.mkdir()
    report={'migration_applied':False,'accounts_created':False,'settings_activated':False}
    try:
        with get_connection() as c:
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            before=snapshot(c)
        report['before']=before
        if before!=old['full_after']:raise RuntimeError('Source changed since verified backup; obtain a fresh verified backup')
        with get_connection() as c:
            with c.transaction():
                apply_migration(c,manifest)
                apply_movements_migration(c,manifest,expected_database='ai_excel_agent_test')
                after=snapshot(c)
                if any(after.get(k)!=v for k,v in before.items()):raise RuntimeError('Original table fingerprints changed; rolling back')
                report['settings']=list(c.execute('SELECT enabled,dk_context_verified,date_readers_verified,legacy_history_policy FROM personnel_settings').fetchone())
                report['new_tables']=sorted(set(after)-set(before))
                if len(report['new_tables'])!=7:raise RuntimeError('Unexpected table delta')
                report['after']=after
        report['migration_applied']=True
        report['original_tables_unchanged']=True
        report['migration_sha256']={n:hashlib.sha256((ROOT/'app/database/migrations'/n).read_bytes()).hexdigest() for n in ('033_personnel_transfers.sql','034_personnel_movements.sql')}
    finally:
        (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print(json.dumps({'report':str(output/'report.json'),'migration_applied':report['migration_applied'],'original_tables_unchanged':report['original_tables_unchanged'],'new_tables':len(report['new_tables'])}))

if __name__=='__main__':main()
