"""Identity and hierarchy operations, available only with migration 024 installed."""
from psycopg.rows import dict_row
from app.repositories.directory_errors import DirectoryConflict, DirectoryNotFound


def enabled(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('construction_entity_current')")
        row = cur.fetchone()
        return (next(iter(row.values())) if isinstance(row,dict) else row[0]) is not None


def reference(conn, item):
    return resolve(conn, **{k:item.get(k) for k in ('entity_id','object_id','subobject_id')})


def prepare(conn, item, *, assignable=True):
    """Validate a real reference without inventing legacy IDs."""
    if not enabled(conn):
        if item.get('entity_id') is not None:
            raise DirectoryConflict('Операции по entity_id требуют завершения интеграции 024')
        item.pop('entity_id',None)
        return item
    require_enabled(conn)
    conn.execute('SELECT pg_advisory_xact_lock(20261013,24)')
    entity=reference(conn,item)
    if assignable and (entity['effectively_archived'] or not entity['is_active']):
        raise DirectoryConflict('Объект или подобъект недоступен для нового назначения')
    item['entity_id']=entity['entity_id']
    return item


def describe(conn, item):
    if enabled(conn) and any(item.get(k) is not None for k in ('entity_id','object_id','subobject_id')):
        entity=reference(conn,item)
        item.update(entity_id=entity['entity_id'],current_hierarchy=entity)
    return item


def presentation(entity):
    parent=entity.get('parent')
    return dict(entity_id=entity['entity_id'],current_hierarchy=entity,
        parent_entity_id=entity['parent_entity_id'],
        object_name=parent['name'] if parent else entity['name'],
        subobject_name=entity['name'] if parent else None,
        control_item_key=f"entity:{entity['entity_id']}",
        control_item_type='subobject' if parent else 'object',control_item_name=entity['name'])


def catalog(conn, *, children=False, parent_entity_id=None, archive='all', include_inactive=False):
    result=[]
    for row in directory(conn):
        entity=resolve(conn,entity_id=row['entity_id'])
        if (entity['parent_entity_id'] is not None)!=children:continue
        if parent_entity_id is not None and entity['parent_entity_id']!=parent_entity_id:continue
        if not include_inactive and not entity['is_active']:continue
        if archive!='all' and entity['effectively_archived']!=(archive=='archived'):continue
        result.append(dict(id=entity['legacy_subobject_id'] if children else entity['legacy_object_id'],
            object_id=entity['legacy_object_id'],legacy_subobject_id=entity['legacy_subobject_id'],
            name=entity['name'],is_active=entity['is_active'],is_archived=entity['is_archived'],
            archived_at=str(entity['archived_at']) if entity['archived_at'] else None,
            activity_status=entity['activity_status'],parent_is_archived=bool(entity['parent'] and entity['parent']['is_archived']),
            **presentation(entity)))
    return result


def check_catalog_name(conn, name, *, object_id=None, subobject_id=None):
    """Serialize catalog writes with hierarchy/archive changes; compare current siblings."""
    if not enabled(conn):
        return
    require_enabled(conn)
    conn.execute('SELECT pg_advisory_xact_lock(20261013,24)')
    entity = resolve(conn, object_id=object_id, subobject_id=subobject_id) if object_id is not None or subobject_id is not None else None
    parent = entity['parent_entity_id'] if entity else None
    duplicate = conn.execute('''SELECT 1 FROM construction_entity_current
        WHERE parent_entity_id IS NOT DISTINCT FROM %s AND entity_id IS DISTINCT FROM %s
        AND normalize_known_value('object',name)=normalize_known_value('object',%s) LIMIT 1''',
        (parent, entity['entity_id'] if entity else None, name)).fetchone()
    if duplicate:
        raise DirectoryConflict('Запись с таким названием уже существует в текущей иерархии')


def require_enabled(conn):
    schema = conn.execute('SELECT current_schema()').fetchone()[0]
    if not schema or not schema.startswith('test_'):
        raise DirectoryConflict('Преобразование недоступно до завершения интеграции 024')
    if not enabled(conn):
        raise DirectoryConflict('Преобразование недоступно: интеграция миграции 024 не завершена')


def directory(conn, *, parents_for=None):
    require_enabled(conn)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute('SELECT * FROM construction_entity_current ORDER BY name,entity_id')
        rows=cur.fetchall()
    if parents_for is not None:
        resolve(conn,entity_id=parents_for)
        rows=[r for r in rows if r['entity_id']!=parents_for and r['parent_entity_id'] is None and not r['is_archived']]
    return rows


def enrich(conn, items, *, subobjects=False):
    if not enabled(conn): return items
    for item in items:
        entity=resolve(conn,**({'subobject_id':item['id']} if subobjects else {'object_id':item['id']}))
        item.update(entity_id=entity['entity_id'],current_hierarchy=entity)
        if subobjects:
            item.update(object_name=entity['parent']['name'] if entity['parent'] else None,
                        parent_is_archived=bool(entity['parent'] and entity['parent']['is_archived']))
    return items


def resolve(conn, *, entity_id=None, object_id=None, subobject_id=None):
    with conn.cursor(row_factory=dict_row) as cur:
        if entity_id is not None:
            cur.execute('SELECT * FROM construction_entity_current WHERE entity_id=%s',(entity_id,))
        elif subobject_id is not None:
            cur.execute('SELECT * FROM construction_entity_current WHERE legacy_subobject_id=%s',(subobject_id,))
        else:
            cur.execute('SELECT * FROM construction_entity_current WHERE legacy_object_id=%s',(object_id,))
        item=cur.fetchone()
        if item is None: raise DirectoryNotFound('Сущность объекта не найдена')
        if entity_id is not None:
            if subobject_id is not None and item['legacy_subobject_id']!=subobject_id:
                raise DirectoryConflict('entity_id и subobject_id противоречат друг другу')
            if object_id is not None:
                source=item['legacy_object_id']
                if item['legacy_subobject_id'] is not None:
                    cur.execute('SELECT object_id FROM construction_subobjects WHERE id=%s',(item['legacy_subobject_id'],))
                    source=cur.fetchone()['object_id']
                if source!=object_id: raise DirectoryConflict('entity_id и object_id противоречат друг другу')
        parent=None
        if item['parent_entity_id'] is not None:
            cur.execute('SELECT * FROM construction_entity_current WHERE entity_id=%s',(item['parent_entity_id'],))
            parent=cur.fetchone()
        return {**item,'parent':parent,'effectively_archived':item['is_archived'] or bool(parent and parent['is_archived'])}


def reparent(conn, entity_id, parent_entity_id, version):
    require_enabled(conn)
    with conn.transaction():
        conn.execute('SELECT pg_advisory_xact_lock(20261013,24)')
        current=resolve(conn,entity_id=entity_id)
        if current['version']!=version: raise DirectoryConflict('Иерархия изменена. Обновите карточку')
        if parent_entity_id==entity_id: raise DirectoryConflict('Объект нельзя поместить в самого себя')
        if parent_entity_id is not None:
            parent=resolve(conn,entity_id=parent_entity_id)
            if parent['parent_entity_id'] is not None or parent['is_archived']:
                raise DirectoryConflict('Выберите самостоятельный объект вне архива')
            if conn.execute('SELECT 1 FROM construction_entity_hierarchy WHERE parent_entity_id=%s',(entity_id,)).fetchone():
                raise DirectoryConflict('У объекта есть подобъекты. Сначала упорядочите структуру')
        duplicate=conn.execute("""SELECT 1 FROM construction_entity_current
            WHERE entity_id<>%s AND parent_entity_id IS NOT DISTINCT FROM %s
            AND normalize_known_value('object',name)=normalize_known_value('object',%s)""",
            (entity_id,parent_entity_id,current['name'])).fetchone()
        if duplicate: raise DirectoryConflict('В выбранном уровне уже есть запись с таким названием')
        if current['parent_entity_id']!=parent_entity_id:
            conn.execute('UPDATE construction_entity_hierarchy SET parent_entity_id=%s,version=version+1 WHERE entity_id=%s',
                         (parent_entity_id,entity_id))
        return resolve(conn,entity_id=entity_id)


def legacy_move(conn, subobject_id, object_id, name=None, is_active=None, token=None, apply=False):
    """Compatibility adapter: source IDs remain source IDs, never current parents."""
    import hashlib
    import json
    require_enabled(conn)
    with conn.transaction():
        conn.execute('SELECT pg_advisory_xact_lock(20261013,24)')
        child=resolve(conn,subobject_id=subobject_id)
        parent=resolve(conn,object_id=object_id)
        if parent['parent_entity_id'] is not None or parent['is_archived']:
            raise DirectoryConflict('Выберите самостоятельный объект вне архива')
        proposed_name=child['name'] if name is None else name.strip()
        if not proposed_name: raise ValueError('Название не заполнено')
        active=child['is_active'] if is_active is None else is_active
        fingerprint=hashlib.sha256(json.dumps([child,parent,proposed_name,active],sort_keys=True,default=str).encode()).hexdigest()
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute('SELECT s.*,o.name AS object_name FROM construction_subobjects s LEFT JOIN construction_objects o ON o.id=s.object_id WHERE s.id=%s',(subobject_id,))
            source=cur.fetchone()
            cur.execute('SELECT count(*) AS n FROM daily_control_results WHERE subobject_id=%s',(subobject_id,))
            count=cur.fetchone()['n']
        plan=dict(subobject_id=subobject_id,name=proposed_name,is_active=active,
                  old_object_id=source['object_id'],old_object_name=source['object_name'],
                  object_id=object_id,object_name=parent['name'],linked_facts=count,
                  missing_assignments=0,confirmation_token=fingerprint,requires_confirmation=True)
        if not apply:return plan
        if token!=fingerprint:raise DirectoryConflict('Повторите проверку и подтвердите текущую иерархию')
        # Metadata edits and hierarchy change share a transaction; failure rolls back both.
        conn.execute('UPDATE construction_subobjects SET name=%s,is_active=%s WHERE id=%s',(proposed_name,active,subobject_id))
        result=reparent(conn,child['entity_id'],parent['entity_id'],child['version'])
        source.update(name=proposed_name,is_active=active,entity_id=child['entity_id'],current_hierarchy=result)
        return dict(item=source,updated_facts=0,missing_assignments=0)
