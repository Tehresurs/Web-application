import argparse
from pathlib import Path
from app.database.db import get_connection


def apply_migration(conn,agreed_name=None,allow_incomplete=False):
    with conn.transaction():
        conn.execute("SET LOCAL lock_timeout='5s'")
        conn.execute('SELECT pg_advisory_xact_lock(20261003,11)')
        conn.execute("SELECT set_config('luvr.initial_agreed_name',%s,true)",(agreed_name.strip() if agreed_name else '',))
        conn.execute((Path(__file__).with_name('migrations')/'011_luvr_footer.sql').read_text(encoding='utf-8'))
        name=conn.execute('SELECT agreed_name FROM luvr_settings WHERE id=1').fetchone()[0]
        if (not name or not name.strip()) and not allow_incomplete:raise ValueError('Укажите ФИО согласующего: --agreed-name. Миграция отменена.')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--agreed-name');parser.add_argument('--allow-incomplete',action='store_true');args=parser.parse_args()
    with get_connection() as conn:apply_migration(conn,args.agreed_name,args.allow_incomplete)
    print('Migration 011 applied')
