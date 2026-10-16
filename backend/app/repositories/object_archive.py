from psycopg.rows import dict_row
from app.database.db import get_connection
from app.repositories.directory_errors import DirectoryConflict, DirectoryNotFound


def archive_state(cursor, object_id, subobject_id=None, lock=False):
    # JSON access keeps older isolated schemas readable; deployed schema uses migration 023.
    cursor.execute("SELECT COALESCE((to_jsonb(o)->>'is_archived')::boolean,false) FROM construction_objects o WHERE id=%s" + (' FOR SHARE' if lock else ''), (object_id,))
    row=cursor.fetchone()
    if row is None: raise DirectoryNotFound('Объект не найден')
    archived=next(iter(row.values())) if isinstance(row,dict) else row[0]
    if subobject_id is not None:
        cursor.execute("SELECT object_id,COALESCE((to_jsonb(s)->>'is_archived')::boolean,false) FROM construction_subobjects s WHERE id=%s" + (' FOR SHARE' if lock else ''), (subobject_id,))
        child=cursor.fetchone()
        if isinstance(child,dict): child=tuple(child.values())
        if child is None or child[0]!=object_id: raise DirectoryConflict('Подобъект не принадлежит объекту')
        archived=archived or child[1]
    return archived


def require_assignable(cursor, object_id, subobject_id=None):
    if archive_state(cursor,object_id,subobject_id,lock=True):
        raise DirectoryConflict('Объект или подобъект находится в архиве. Новое назначение запрещено')


def change(kind, item_id, *, is_archived=None, activity_status=None):
    table={'objects':'construction_objects','subobjects':'construction_subobjects'}[kind]
    with get_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        from app.repositories.construction_identity import enabled
        if enabled(conn):conn.execute('SELECT pg_advisory_xact_lock(20261013,24)')
        cur.execute(f'SELECT * FROM {table} WHERE id=%s FOR UPDATE',(item_id,))
        old=cur.fetchone()
        if old is None: raise DirectoryNotFound('Запись не найдена')
        if activity_status is not None:
            if activity_status not in ('ACTIVE','SUSPENDED','COMPLETED'): raise ValueError('Недопустимый статус')
            cur.execute(f'UPDATE {table} SET activity_status=%s WHERE id=%s',(activity_status,item_id))
        if is_archived is not None and old['is_archived']!=is_archived:
            cur.execute(f'UPDATE {table} SET is_archived=%s, archived_at=CASE WHEN %s THEN CURRENT_TIMESTAMP ELSE NULL END WHERE id=%s',(is_archived,is_archived,item_id))
        cur.execute(f'SELECT * FROM {table} WHERE id=%s',(item_id,))
        return cur.fetchone()
