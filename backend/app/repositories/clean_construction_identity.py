"""Opt-in adapter for future consumers. Does not dispatch to or change legacy code.

Use within a caller-owned transaction. Set CONSTRUCTION_MODEL=clean_start and
the same explicit test environment as the isolated catalog API.
"""
import os
import re

from psycopg.rows import dict_row


class ModelUnavailable(ValueError):
    pass


def validate(conn):
    if os.getenv('CONSTRUCTION_MODEL', 'legacy') != 'clean_start':
        raise ModelUnavailable('Clean-start model is not explicitly selected')
    expected = os.getenv('CLEAN_START_DB_NAME', '')
    allowed = expected in {
        'ai_excel_agent_stage41210_20261014_1634',
        'ai_excel_agent_stage4151_20261019_86bf41ed',
    } or re.fullmatch(
        r'ai_excel_agent_test_categories_[a-f0-9]{12}', expected)
    if (not allowed or os.getenv('APP_DB_PROFILE') != 'test'
            or os.getenv('CLEAN_START_DB_PROFILE') != 'test'
            or os.getenv('CLEAN_START_DB_SCHEMA') != 'public'):
        raise ModelUnavailable('An explicitly approved test environment is required')
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute('SELECT current_database() db,current_schema() schema')
        if cur.fetchone() != {'db': expected, 'schema': 'public'}:
            raise ModelUnavailable('Actual database/schema does not match configuration')
        cur.execute("""SELECT table_name,column_name,data_type,is_identity FROM information_schema.columns
            WHERE table_schema='public' AND table_name IN (
                'construction_entities','construction_entity_current',
                'construction_entity_aliases'
            )""")
        columns = {(r['table_name'], r['column_name']): r for r in cur.fetchall()}
        required = dict(entity_id='bigint', name='text', parent_entity_id='bigint', category_id='bigint',
                        activity_status='text', is_active='boolean', is_archived='boolean',
                        archived_at='timestamp with time zone', version='bigint')
        for table in ('construction_entities', 'construction_entity_current'):
            if any(columns.get((table, name), {}).get('data_type') != kind for name, kind in required.items()):
                raise ModelUnavailable('Incompatible clean-start table/view contract')
        if columns[('construction_entities', 'entity_id')]['is_identity'] != 'YES':
            raise ModelUnavailable('Expected native entity identity')
        alias_required = {
            'alias_id': 'bigint',
            'entity_id': 'bigint',
            'source_value': 'text',
            'normalized_source_value': 'text',
            'created_at': 'timestamp with time zone',
        }
        if any(
            columns.get(('construction_entity_aliases', name), {}).get('data_type') != kind
            for name, kind in alias_required.items()
        ):
            raise ModelUnavailable('Incompatible construction entity aliases contract')
        if columns[('construction_entity_aliases', 'alias_id')]['is_identity'] != 'YES':
            raise ModelUnavailable('Expected native construction alias identity')


FIELDS = 'entity_id,name,activity_status,category_id,parent_entity_id,is_active,is_archived,archived_at,version'


def _read(conn, entity_id):
    if isinstance(entity_id, bool) or not isinstance(entity_id, int) or entity_id <= 0:
        raise ValueError('A positive entity_id is required')
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f'SELECT {FIELDS} FROM public.construction_entity_current WHERE entity_id=%s', (entity_id,))
        row = cur.fetchone()
    if row is None:
        raise LookupError('Construction entity not found')
    return row


def resolve(conn, entity_id):
    validate(conn)
    item = _read(conn, entity_id)
    parent = _read(conn, item['parent_entity_id']) if item['parent_entity_id'] is not None else None
    if parent and (parent['parent_entity_id'] is not None or parent['entity_id'] == entity_id):
        raise ModelUnavailable('Invalid two-level hierarchy')
    return {**item, 'parent': parent,
            'effectively_archived': item['is_archived'] or bool(parent and parent['is_archived']),
            'available': item['is_active'] and not item['is_archived'] and
                (parent is None or parent['is_active'] and not parent['is_archived'])}


def directory(conn):
    validate(conn)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute('SELECT entity_id FROM public.construction_entities ORDER BY name,entity_id')
        ids = [r['entity_id'] for r in cur.fetchall()]
    return [resolve(conn, entity_id) for entity_id in ids]


def require_available(conn, entity_id, *, as_parent=False):
    """Call in the same transaction as the future write; lock shared with SQL guards."""
    validate(conn)
    conn.execute('SELECT pg_advisory_xact_lock(20261014,25)')
    item = resolve(conn, entity_id)
    if not item['available'] or (as_parent and item['parent_entity_id'] is not None):
        raise ValueError('Entity is unavailable for a new reference or parent link')
    return item
