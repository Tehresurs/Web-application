from psycopg import errors

from app.repositories import clean_construction_identity as identity


def _employee_exists(conn, employee_id):
    if conn.execute('SELECT 1 FROM public.employees WHERE id=%s', (employee_id,)).fetchone() is None:
        raise ValueError('Сотрудник не найден')


def _reference_exists(conn, table, reference_id, message):
    if conn.execute(f'SELECT 1 FROM public.{table} WHERE id=%s', (reference_id,)).fetchone() is None:
        raise ValueError(message)


def _assignment(conn, row):
    hierarchy = identity.resolve(conn, row['entity_id'])
    parent = hierarchy['parent']
    return {
        'id': row['id'],
        'employee_id': row['employee_id'],
        'entity_id': row['entity_id'],
        'object_name': hierarchy['name'],
        'parent_entity_id': hierarchy['parent_entity_id'],
        'parent_name': parent['name'] if parent else None,
        'current_hierarchy': hierarchy,
        'po_id': row['po_id'],
        'po_name': row['po_name'],
        'category_id': row['category_id'],
        'category_name': row['category_name'],
    }


def list_for_employee(conn, employee_id):
    _employee_exists(conn, employee_id)
    rows = conn.execute(
        '''SELECT a.id,a.employee_id,a.entity_id,a.po_id,p.name AS po_name,
                  a.category_id,c.name AS category_name
           FROM public.employee_assignments a
           JOIN public.po_types p ON p.id=a.po_id
           JOIN public.object_categories c ON c.id=a.category_id
           WHERE a.employee_id=%s ORDER BY a.id''',
        (employee_id,),
    ).fetchall()
    items = [_assignment(conn, row) for row in rows]
    return {'items': items, 'objects_count': len({item['entity_id'] for item in items})}


def _validate_references(conn, employee_id, po_id, category_id):
    _employee_exists(conn, employee_id)
    _reference_exists(conn, 'po_types', po_id, 'ПО не найдено')
    _reference_exists(conn, 'object_categories', category_id, 'Категория не найдена')


def _require_available(conn, entity_id):
    try:
        return identity.require_available(conn, entity_id)
    except LookupError:
        raise ValueError('Объект или подобъект не найден') from None


def _duplicate_exists(conn, employee_id, entity_id, po_id, category_id, assignment_id=None):
    return conn.execute(
        '''SELECT 1 FROM public.employee_assignments
           WHERE employee_id=%s AND entity_id=%s AND po_id=%s AND category_id=%s
             AND (%s::bigint IS NULL OR id<>%s)''',
        (employee_id, entity_id, po_id, category_id, assignment_id, assignment_id),
    ).fetchone() is not None


def create(conn, employee_id, entity_id, po_id, category_id):
    _validate_references(conn, employee_id, po_id, category_id)
    _require_available(conn, entity_id)
    if _duplicate_exists(conn, employee_id, entity_id, po_id, category_id):
        raise ValueError('Такое закрепление у сотрудника уже существует')
    try:
        with conn.transaction():
            row = conn.execute(
                '''INSERT INTO public.employee_assignments
                       (employee_id,object_id,entity_id,po_id,category_id)
                   VALUES (%s,NULL,%s,%s,%s) RETURNING id,employee_id,entity_id,po_id,category_id''',
                (employee_id, entity_id, po_id, category_id),
            ).fetchone()
    except errors.UniqueViolation as error:
        raise ValueError('Такое закрепление у сотрудника уже существует') from error
    return _assignment(conn, {
        **row,
        'po_name': conn.execute('SELECT name FROM public.po_types WHERE id=%s', (po_id,)).fetchone()['name'],
        'category_name': conn.execute(
            'SELECT name FROM public.object_categories WHERE id=%s', (category_id,)
        ).fetchone()['name'],
    })


def update(conn, employee_id, assignment_id, entity_id, po_id, category_id):
    _validate_references(conn, employee_id, po_id, category_id)
    old = conn.execute(
        '''SELECT id,employee_id,entity_id,po_id,category_id
           FROM public.employee_assignments
           WHERE id=%s AND employee_id=%s FOR UPDATE''',
        (assignment_id, employee_id),
    ).fetchone()
    if old is None:
        raise ValueError('Закрепление сотрудника не найдено')
    if old['entity_id'] != entity_id:
        _require_available(conn, entity_id)
    if _duplicate_exists(conn, employee_id, entity_id, po_id, category_id, assignment_id):
        raise ValueError('Такое закрепление у сотрудника уже существует')
    try:
        with conn.transaction():
            row = conn.execute(
                '''UPDATE public.employee_assignments
                   SET object_id=NULL,entity_id=%s,po_id=%s,category_id=%s,updated_at=CURRENT_TIMESTAMP
                   WHERE id=%s AND employee_id=%s
                   RETURNING id,employee_id,entity_id,po_id,category_id''',
                (entity_id, po_id, category_id, assignment_id, employee_id),
            ).fetchone()
    except errors.UniqueViolation as error:
        raise ValueError('Такое закрепление у сотрудника уже существует') from error
    return _assignment(conn, {
        **row,
        'po_name': conn.execute('SELECT name FROM public.po_types WHERE id=%s', (po_id,)).fetchone()['name'],
        'category_name': conn.execute(
            'SELECT name FROM public.object_categories WHERE id=%s', (category_id,)
        ).fetchone()['name'],
    })


def delete(conn, employee_id, assignment_id):
    row = conn.execute(
        '''DELETE FROM public.employee_assignments
           WHERE id=%s AND employee_id=%s RETURNING id''',
        (assignment_id, employee_id),
    ).fetchone()
    if row is None:
        raise ValueError('Закрепление сотрудника не найдено')
    return {'id': row['id'], 'deleted': True}
