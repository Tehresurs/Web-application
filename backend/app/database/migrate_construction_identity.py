"""Isolated-schema runner. Production activation is deliberately unavailable."""
from pathlib import Path


def apply_migration(conn):
    with conn.transaction():
        schema=conn.execute('SELECT current_schema()').fetchone()[0]
        if not schema.startswith('test_'):
            raise ValueError('024 is not ready for production: consumers and write constraints require adaptation')
        conn.execute("SET LOCAL lock_timeout='5s'")
        conn.execute('SELECT pg_advisory_xact_lock(20261013,24)')
        tables=('construction_objects','construction_subobjects','employee_assignments',
                'rail_tickets','production_assignment_items','daily_control_results')
        for table in tables:
            conn.execute(f'LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE')
        columns={table:[r[0] for r in conn.execute('SELECT attname FROM pg_attribute WHERE attrelid=%s::regclass AND attnum>0 AND NOT attisdropped',(table,)).fetchall()] for table in tables}
        def snapshot():
            return [conn.execute(f"SELECT (SELECT jsonb_object_agg(key,value) FROM jsonb_each(to_jsonb(t)) WHERE key=ANY(%s)) FROM {t} t ORDER BY id",(columns[t],)).fetchall() for t in tables]
        before=snapshot()
        conn.execute((Path(__file__).with_name('migrations')/'024_construction_identity.sql').read_text(encoding='utf-8'))
        if before!=snapshot():
            raise ValueError('Historical data changed; migration rolled back')
