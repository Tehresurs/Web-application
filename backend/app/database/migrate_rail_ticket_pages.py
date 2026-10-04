from pathlib import Path
from app.database.db import get_connection


def apply_migration(conn):
    with conn.transaction():
        conn.execute("SET LOCAL lock_timeout='5s'")
        conn.execute("SET LOCAL statement_timeout='60s'")
        conn.execute("SELECT pg_advisory_xact_lock(20261002,8)")
        conn.execute((Path(__file__).with_name('migrations')/'008_rail_ticket_pages.sql').read_text(encoding='utf-8'))


if __name__=='__main__':
    with get_connection() as conn:apply_migration(conn)
    print('Migration 008 applied')
