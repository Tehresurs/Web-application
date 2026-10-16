from pathlib import Path
from app.database.db import get_connection


def apply_migration(conn):
    with conn.transaction():
        conn.execute("SET LOCAL lock_timeout='5s'")
        conn.execute('SELECT pg_advisory_xact_lock(20261013,23)')
        tables=('construction_objects','construction_subobjects')
        for table in tables:
            conn.execute(f'LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE')
        def snapshot():
            return [conn.execute(f"SELECT to_jsonb(t)-'is_archived'-'archived_at'-'activity_status' FROM {table} t ORDER BY id").fetchall() for table in tables]
        before=snapshot()
        conn.execute((Path(__file__).with_name('migrations')/'023_object_archive.sql').read_text(encoding='utf-8'))
        if before != snapshot():
            raise ValueError('Existing object data changed; migration rolled back')


if __name__ == '__main__':
    with get_connection() as conn:
        apply_migration(conn)
    print('Migration 023 applied; existing object and subobject data unchanged')
