from pathlib import Path
from app.database.db import get_connection


def apply_migration(conn):
    with conn.transaction():
        conn.execute("SET LOCAL lock_timeout='5s'")
        conn.execute('SELECT pg_advisory_xact_lock(20261008,19)')
        conn.execute((Path(__file__).with_name('migrations') / '019_production_matrix_overrides.sql').read_text(encoding='utf-8'))


if __name__ == '__main__':
    with get_connection() as conn:
        apply_migration(conn)
    print('Migration 019 applied')
