import os
from fastapi import APIRouter, Path, Query
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from app.database.db import get_connection
from app.api.known_values import _response
from app.repositories import construction_identity as identity
from app.repositories.directory_errors import DirectoryConflict


def change_entity(entity_id, *, name=None, is_active=None, is_archived=None, activity_status=None):
    """Explicit entity addressing for existing catalog routes; source IDs stay immutable."""
    from psycopg.errors import UniqueViolation
    try:
        with get_connection() as conn:
            require_test_database(conn)
            conn.execute('SELECT pg_advisory_xact_lock(20261013,24)')
            item = identity.resolve(conn, entity_id=entity_id)
            source_child = item['legacy_subobject_id'] is not None
            source_id = item['legacy_subobject_id'] if source_child else item['legacy_object_id']
            table = 'construction_subobjects' if source_child else 'construction_objects'
            if name is not None:
                name = ' '.join(name.split())
                if not name: raise ValueError('Введите наименование')
                identity.check_catalog_name(conn, name, **({'subobject_id':source_id} if source_child else {'object_id':source_id}))
                conn.execute(f'UPDATE {table} SET name=%s WHERE id=%s', (name,source_id))
            if is_active is not None:
                if source_child:
                    conn.execute(f'UPDATE {table} SET is_active=%s WHERE id=%s',(is_active,source_id))
                elif not is_active:
                    raise DirectoryConflict('Для этой записи используйте архивирование или статус деятельности')
            if activity_status is not None:
                conn.execute(f'UPDATE {table} SET activity_status=%s WHERE id=%s',(activity_status,source_id))
            if is_archived is not None and is_archived != item['is_archived']:
                conn.execute(f'''UPDATE {table} SET is_archived=%s,
                    archived_at=CASE WHEN %s THEN CURRENT_TIMESTAMP ELSE NULL END WHERE id=%s''',
                    (is_archived,is_archived,source_id))
            return next(r for r in identity.catalog(conn,children=item['parent_entity_id'] is not None,include_inactive=True)
                        if r['entity_id']==entity_id)
    except UniqueViolation:
        raise DirectoryConflict('Запись с таким названием уже существует') from None

router=APIRouter(prefix='/api/construction-entities',tags=['Текущая иерархия объектов'])

class ReparentRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    parent_entity_id: int | None = Field(...,gt=0,strict=True)
    version: int = Field(gt=0,strict=True)
    confirmed: StrictBool

def read(parents_for=None):
    with get_connection() as conn:
        return identity.directory(conn,parents_for=parents_for)

def require_test_database(conn):
    database, schema = conn.execute('SELECT current_database(),current_schema()').fetchone()
    expected = os.getenv('DB_SCHEMA', '')
    allowed_schemas = {
        item.strip()
        for item in os.getenv('APP_TEST_ALLOWED_DB_SCHEMAS', '').split(',')
        if item.strip()
    }
    if (os.getenv('APP_DB_PROFILE') != 'test' or database != 'ai_excel_agent_test'
            or schema != expected or schema not in allowed_schemas):
        raise DirectoryConflict('Преобразование разрешено только в настроенной тестовой схеме ai_excel_agent_test')
    identity.require_enabled(conn)
    return dict(profile='test', database=database, schema=schema)

def test_environment():
    with get_connection() as conn:
        return require_test_database(conn)

@router.get('/environment')
def environment():
    return _response(test_environment)

def transform(entity_id,payload):
    if not payload.confirmed: raise DirectoryConflict('Подтвердите преобразование')
    with get_connection() as conn:
        require_test_database(conn)
        return identity.reparent(conn,entity_id,payload.parent_entity_id,payload.version)

@router.get('')
def entities(parents_for:int|None=Query(default=None,gt=0)):
    return _response(read,parents_for,key='items')

@router.patch('/{entity_id}/hierarchy')
def hierarchy(payload:ReparentRequest,entity_id:int=Path(gt=0)):
    return _response(transform,entity_id,payload)
