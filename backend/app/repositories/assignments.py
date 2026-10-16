from app.database.db import get_connection
from app.repositories.object_archive import require_assignable
from app.repositories import construction_identity as identity
from psycopg.rows import dict_row
from psycopg.errors import IntegrityError


def _ensure_employee_exists(cursor, employee_id: int):
    cursor.execute("SELECT id FROM employees WHERE id = %s;", (employee_id,))
    if cursor.fetchone() is None:
        raise ValueError("Сотрудник не найден")


def _ensure_refs_exist(cursor, object_id: int, po_id: int, category_id: int):
    checks = (
        ("construction_objects", object_id, "Объект не найден"),
        ("po_types", po_id, "ПО не найдено"),
        ("object_categories", category_id, "Категория не найдена"),
    )
    for table, value, message in checks:
        cursor.execute(f"SELECT id FROM {table} WHERE id = %s;", (value,))
        if cursor.fetchone() is None:
            raise ValueError(message)


def get_employee_assignments(employee_id: int):
    with get_connection() as conn:
        if identity.enabled(conn):
            with conn.cursor() as cur:_ensure_employee_exists(cur,employee_id)
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute('''SELECT a.*,p.name po_name,c.name category_name FROM employee_assignments a
                    JOIN po_types p ON p.id=a.po_id JOIN object_categories c ON c.id=a.category_id
                    WHERE employee_id=%s ORDER BY a.id''',(employee_id,))
                items=[identity.describe(conn,dict(r)) for r in cur.fetchall()]
            for item in items:item['object_name']=item['current_hierarchy']['name']
            return dict(items=items,objects_count=len({i['entity_id'] for i in items}))
        with conn.cursor() as cursor:
            _ensure_employee_exists(cursor, employee_id)
            cursor.execute(
                """
                SELECT
                    ea.id,
                    ea.employee_id,
                    ea.object_id,
                    co.name,
                    ea.po_id,
                    pt.name,
                    ea.category_id,
                    oc.name
                FROM employee_assignments ea
                JOIN construction_objects co ON co.id = ea.object_id
                JOIN po_types pt ON pt.id = ea.po_id
                JOIN object_categories oc ON oc.id = ea.category_id
                WHERE ea.employee_id = %s
                ORDER BY co.name, pt.name, oc.name, ea.id;
                """,
                (employee_id,),
            )
            rows = cursor.fetchall()

    items = [
        {
            "id": row[0],
            "employee_id": row[1],
            "object_id": row[2],
            "object_name": row[3],
            "po_id": row[4],
            "po_name": row[5],
            "category_id": row[6],
            "category_name": row[7],
        }
        for row in rows
    ]
    return {
        "items": items,
        "objects_count": len({item["object_id"] for item in items}),
    }


def create_employee_assignment(
    employee_id: int,
    object_id: int,
    po_id: int,
    category_id: int,
    entity_id=None,
):
    with get_connection() as conn:
        if identity.enabled(conn) or entity_id is not None:
            return _save_identity(conn,employee_id,object_id,po_id,category_id,entity_id)
        with conn.cursor() as cursor:
            _ensure_employee_exists(cursor, employee_id)
            _ensure_refs_exist(cursor, object_id, po_id, category_id)
            require_assignable(cursor, object_id)

            cursor.execute(
                """
                SELECT id
                FROM employee_assignments
                WHERE employee_id = %s
                  AND object_id = %s
                  AND po_id = %s
                  AND category_id = %s;
                """,
                (employee_id, object_id, po_id, category_id),
            )
            if cursor.fetchone():
                raise ValueError("Такое назначение у сотрудника уже существует")

            cursor.execute(
                """
                INSERT INTO employee_assignments (
                    employee_id, object_id, po_id, category_id
                )
                VALUES (%s, %s, %s, %s)
                RETURNING id;
                """,
                (employee_id, object_id, po_id, category_id),
            )
            assignment_id = cursor.fetchone()[0]

    return {"id": assignment_id}


def update_employee_assignment(
    employee_id: int,
    assignment_id: int,
    object_id: int,
    po_id: int,
    category_id: int,
    entity_id=None,
):
    with get_connection() as conn:
        if identity.enabled(conn) or entity_id is not None:
            return _save_identity(conn,employee_id,object_id,po_id,category_id,entity_id,assignment_id)
        with conn.cursor() as cursor:
            _ensure_employee_exists(cursor, employee_id)
            _ensure_refs_exist(cursor, object_id, po_id, category_id)
            cursor.execute('SELECT object_id FROM employee_assignments WHERE id=%s AND employee_id=%s FOR UPDATE', (assignment_id, employee_id))
            previous=cursor.fetchone()
            if previous and previous[0]!=object_id:
                require_assignable(cursor, object_id)

            cursor.execute(
                """
                SELECT id
                FROM employee_assignments
                WHERE id = %s AND employee_id = %s;
                """,
                (assignment_id, employee_id),
            )
            if cursor.fetchone() is None:
                raise ValueError("Назначение сотрудника не найдено")

            cursor.execute(
                """
                SELECT id
                FROM employee_assignments
                WHERE employee_id = %s
                  AND object_id = %s
                  AND po_id = %s
                  AND category_id = %s
                  AND id <> %s;
                """,
                (employee_id, object_id, po_id, category_id, assignment_id),
            )
            if cursor.fetchone():
                raise ValueError("Такое назначение у сотрудника уже существует")

            cursor.execute(
                """
                UPDATE employee_assignments
                SET object_id = %s,
                    po_id = %s,
                    category_id = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s AND employee_id = %s
                RETURNING id;
                """,
                (object_id, po_id, category_id, assignment_id, employee_id),
            )

    return {"id": assignment_id}


def delete_employee_assignment(employee_id: int, assignment_id: int):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM employee_assignments
                WHERE id = %s AND employee_id = %s
                RETURNING id;
                """,
                (assignment_id, employee_id),
            )
            row = cursor.fetchone()
            if row is None:
                raise ValueError("Назначение сотрудника не найдено")

    return {"id": row[0], "deleted": True}


def _save_identity(conn,employee_id,object_id,po_id,category_id,entity_id,assignment_id=None):
    identity.require_enabled(conn)
    conn.execute('SELECT pg_advisory_xact_lock(20261013,24)')
    with conn.cursor(row_factory=dict_row) as cur:
        _ensure_employee_exists(cur,employee_id)
        for table,value in (('po_types',po_id),('object_categories',category_id)):
            cur.execute(f'SELECT id FROM {table} WHERE id=%s',(value,))
            if cur.fetchone() is None:raise ValueError('ПО или категория не найдены')
        old=None
        if assignment_id is not None:
            cur.execute('SELECT * FROM employee_assignments WHERE id=%s AND employee_id=%s FOR UPDATE',(assignment_id,employee_id))
            old=cur.fetchone()
            if old is None:raise ValueError('Назначение сотрудника не найдено')
        item=dict(entity_id=entity_id,object_id=object_id)
        target=identity.reference(conn,item)
        unchanged=old and identity.reference(conn,old)['entity_id']==target['entity_id']
        identity.prepare(conn,item,assignable=not unchanged)
        try:
            with conn.transaction():
                if old:
                    # An unchanged target retains its original historical references.
                    cur.execute('''UPDATE employee_assignments SET object_id=%s,entity_id=%s,po_id=%s,category_id=%s,
                        updated_at=CURRENT_TIMESTAMP WHERE id=%s RETURNING id''',
                        (old['object_id'] if unchanged else object_id,old['entity_id'] if unchanged else item['entity_id'],po_id,category_id,assignment_id))
                else:
                    cur.execute('''INSERT INTO employee_assignments(employee_id,object_id,entity_id,po_id,category_id)
                        VALUES(%s,%s,%s,%s,%s) RETURNING id''',(employee_id,object_id,item['entity_id'],po_id,category_id))
                return dict(id=cur.fetchone()['id'])
        except IntegrityError as error:
            raise ValueError('Нарушены ссылки или назначение уже существует') from error
