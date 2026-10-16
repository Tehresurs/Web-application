from pathlib import Path
from app.database.db import get_connection


def apply_migration(conn):
    with conn.transaction():
        conn.execute("SET LOCAL lock_timeout='5s'")
        conn.execute('SELECT pg_advisory_xact_lock(20261012,21)')
        before = conn.execute("SELECT to_jsonb(p)-'planned_count' FROM positions p ORDER BY id").fetchall()
        conn.execute((Path(__file__).with_name('migrations') / '021_position_planned_count.sql').read_text(encoding='utf-8'))
        after = conn.execute("SELECT to_jsonb(p)-'planned_count' FROM positions p ORDER BY id").fetchall()
        if before != after:
            raise ValueError('Existing position data changed; migration rolled back')


if __name__ == '__main__':
    with get_connection() as conn:
        apply_migration(conn)
    print('Migration 021 applied; existing position data unchanged')
