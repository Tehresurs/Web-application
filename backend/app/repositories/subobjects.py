import logging
import hashlib
import json

from psycopg.errors import UniqueViolation

from app.database.db import get_connection
from app.repositories.directory_errors import DirectoryConflict, DirectoryNotFound


_SELECT = """SELECT s.id, s.object_id, s.name, s.is_active, o.name
    FROM construction_subobjects s JOIN construction_objects o ON o.id = s.object_id"""


def _item(row):
    return dict(zip(("id", "object_id", "name", "is_active", "object_name"), row)) if row else None


def get_subobjects(object_id=None, include_inactive=False):
    with get_connection() as conn, conn.cursor() as cursor:
        cursor.execute(_SELECT + " WHERE (%s OR s.is_active) AND (%s::bigint IS NULL OR s.object_id = %s) ORDER BY s.name, s.id",
                       (include_inactive, object_id, object_id))
        return [_item(row) for row in cursor.fetchall()]


def get_subobject(subobject_id):
    with get_connection() as conn, conn.cursor() as cursor:
        cursor.execute(_SELECT + " WHERE s.id = %s", (subobject_id,))
        return _item(cursor.fetchone())


def find_subobject_exact(object_id, name):
    """Find an identity within its parent, including inactive entries."""
    with get_connection() as conn, conn.cursor() as cursor:
        cursor.execute(_SELECT + """ WHERE s.object_id = %s
            AND normalize_known_value('subobject', s.name) = normalize_known_value('subobject', %s)""",
                       (object_id, name))
        return _item(cursor.fetchone())


def _validate_name(cursor, name):
    cursor.execute("SELECT normalize_known_value('subobject', %s)", (name,))
    if not cursor.fetchone()[0]:
        raise ValueError("Название подобъекта не заполнено")


def create_subobject(object_id, name):
    try:
        with get_connection() as conn, conn.cursor() as cursor:
            _validate_name(cursor, name)
            cursor.execute("SELECT id FROM construction_objects WHERE id = %s FOR KEY SHARE", (object_id,))
            if cursor.fetchone() is None:
                raise DirectoryNotFound("Родительский объект не найден")
            cursor.execute("INSERT INTO construction_subobjects(object_id, name) VALUES (%s, %s) RETURNING id",
                           (object_id, name.strip()))
            item_id = cursor.fetchone()[0]
            logging.getLogger(__name__).info("SUBOBJECT_CREATED: %r -> subobject_id=%s object_id=%s", name, item_id, object_id)
            cursor.execute(_SELECT + " WHERE s.id = %s", (item_id,))
            return _item(cursor.fetchone())
    except UniqueViolation as error:
        raise DirectoryConflict("Подобъект с таким названием уже существует в этом объекте (включая неактивные)") from error


def update_subobject(subobject_id, name=None, is_active=None):
    if name is None and is_active is None:
        raise ValueError("Укажите name или is_active")
    try:
        with get_connection() as conn, conn.cursor() as cursor:
            if name is not None:
                _validate_name(cursor, name)
            cursor.execute("""UPDATE construction_subobjects
                SET name = COALESCE(%s, name), is_active = COALESCE(%s, is_active)
                WHERE id = %s RETURNING id""", (name.strip() if name is not None else None, is_active, subobject_id))
            if cursor.fetchone() is None:
                raise DirectoryNotFound("Подобъект не найден")
            cursor.execute(_SELECT + " WHERE s.id = %s", (subobject_id,))
            return _item(cursor.fetchone())
    except UniqueViolation as error:
        raise DirectoryConflict("Подобъект с таким названием уже существует в этом объекте (включая неактивные)") from error


def find_subobjects_by_name(name, object_id=None):
    """Active exact matches; a list preserves ambiguity across parent objects."""
    with get_connection() as conn, conn.cursor() as cursor:
        cursor.execute(_SELECT + """ WHERE s.is_active
            AND (%s::bigint IS NULL OR s.object_id = %s)
            AND normalize_known_value('subobject', s.name) = normalize_known_value('subobject', %s)
            ORDER BY s.object_id, s.id""", (object_id, object_id, name))
        return [_item(row) for row in cursor.fetchall()]


def _plan_move(cursor, subobject_id, object_id, name=None, is_active=None):
    # Same order as fact saving: lock the child before touching journal rows.
    cursor.execute(_SELECT + " WHERE s.id = %s FOR UPDATE OF s", (subobject_id,))
    child = _item(cursor.fetchone())
    if child is None:
        raise DirectoryNotFound("Подобъект не найден")
    cursor.execute("SELECT name FROM construction_objects WHERE id = %s FOR KEY SHARE", (object_id,))
    parent = cursor.fetchone()
    if parent is None:
        raise DirectoryNotFound("Родительский объект не найден")
    name = child["name"] if name is None else name.strip()
    _validate_name(cursor, name)
    cursor.execute("""SELECT id FROM construction_subobjects WHERE object_id = %s AND id <> %s
        AND normalize_known_value('subobject',name) = normalize_known_value('subobject',%s)""",
                   (object_id, subobject_id, name))
    if cursor.fetchone():
        raise DirectoryConflict("Такой подобъект уже существует у этого объекта.")
    # Prevent writes during conflict checking + transfer. Readers remain available.
    cursor.execute("LOCK TABLE daily_control_results IN SHARE ROW EXCLUSIVE MODE")
    cursor.execute("""SELECT id, report_date, employee_id, object_id, po_id, subcontractor_id, category_id
        FROM daily_control_results WHERE subobject_id = %s ORDER BY id""", (subobject_id,))
    facts = cursor.fetchall()
    # Project every linked row onto the new parent; nullable dimensions group together.
    cursor.execute("""SELECT 1 FROM daily_control_results WHERE subobject_id = %s
        GROUP BY report_date, employee_id, po_id, subcontractor_id, category_id HAVING count(*) > 1 LIMIT 1""", (subobject_id,))
    if cursor.fetchone():
        raise DirectoryConflict("Перенос создаст дубли фактов контроля. Данные не изменены.")
    cursor.execute("""SELECT count(*) FROM daily_control_results r WHERE r.subobject_id = %s
        AND NOT EXISTS (SELECT 1 FROM employee_assignments a WHERE a.employee_id = r.employee_id
            AND a.object_id = %s AND a.po_id = r.po_id AND a.category_id = r.category_id)""", (subobject_id, object_id))
    missing = cursor.fetchone()[0]
    active = child["is_active"] if is_active is None else is_active
    token = hashlib.sha256(json.dumps([child, object_id, parent[0], name, active, facts, missing],
                                      ensure_ascii=False, default=str, sort_keys=True).encode()).hexdigest()
    return {"subobject_id": subobject_id, "name": name, "is_active": active,
            "old_object_id": child["object_id"], "old_object_name": child["object_name"],
            "object_id": object_id, "object_name": parent[0], "linked_facts": len(facts),
            "missing_assignments": missing, "confirmation_token": token,
            "requires_confirmation": bool(facts) and child["object_id"] != object_id}


def preview_subobject_move(subobject_id, object_id, name=None, is_active=None):
    with get_connection() as conn, conn.cursor() as cursor:
        return _plan_move(cursor, subobject_id, object_id, name, is_active)


def move_subobject(subobject_id, object_id, name=None, is_active=None, confirmation_token=None):
    try:
        with get_connection() as conn, conn.cursor() as cursor:
            plan = _plan_move(cursor, subobject_id, object_id, name, is_active)
            if plan["requires_confirmation"] and confirmation_token != plan["confirmation_token"]:
                raise DirectoryConflict("Подтвердите перенос связанных записей журнала. Если данные изменились, повторите проверку переноса.")
            cursor.execute("UPDATE construction_subobjects SET object_id=%s, name=%s, is_active=%s WHERE id=%s",
                           (object_id, plan["name"], plan["is_active"], subobject_id))
            cursor.execute("UPDATE daily_control_results SET object_id=%s WHERE subobject_id=%s AND object_id<>%s",
                           (object_id, subobject_id, object_id))
            updated = cursor.rowcount
            cursor.execute(_SELECT + " WHERE s.id=%s", (subobject_id,))
            return {"item": _item(cursor.fetchone()), "updated_facts": updated,
                    "missing_assignments": plan["missing_assignments"]}
    except UniqueViolation as error:
        raise DirectoryConflict("Перенос конфликтует с существующим подобъектом или фактом контроля. Данные не изменены.") from error
