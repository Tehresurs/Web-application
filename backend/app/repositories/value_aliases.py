from psycopg import sql

from app.database.db import get_connection
from app.repositories.directory_errors import DirectoryConflict, DirectoryNotFound


TARGETS = {"employee": "employees", "object": "construction_objects",
            "subobject": "construction_subobjects", "po": "po_types", "subcontractor": "po_types"}
_SELECT = """SELECT a.id, a.entity_type, a.source_value, a.normalized_source_value,
    a.target_id, COALESCE(e.full_name, o.name, s.name, p.name), s.object_id, parent.name,
    COALESCE(e.id, o.id, s.id, p.id) IS NOT NULL, s.is_active
    FROM value_aliases a
    LEFT JOIN employees e ON a.entity_type = 'employee' AND e.id = a.target_id
    LEFT JOIN construction_objects o ON a.entity_type = 'object' AND o.id = a.target_id
    LEFT JOIN construction_subobjects s ON a.entity_type = 'subobject' AND s.id = a.target_id
    LEFT JOIN po_types p ON a.entity_type IN ('po', 'subcontractor') AND p.id = a.target_id
    LEFT JOIN construction_objects parent ON parent.id = s.object_id"""


def _item(row):
    return dict(zip(("id", "entity_type", "source_value", "normalized_source_value",
                     "target_id", "target_name", "object_id", "object_name", "target_exists", "target_is_active"), row)) if row else None


def _validate_type(entity_type):
    if entity_type not in TARGETS:
        raise ValueError("Недопустимый entity_type")


def _validate_target(cursor, entity_type, target_id):
    _validate_type(entity_type)
    # Table identifiers come only from the allowlist. Lock prevents deletion or
    # deactivation between validation and saving this transaction.
    cursor.execute(sql.SQL("SELECT {} FROM {} WHERE id = %s FOR SHARE").format(
        sql.SQL("is_active" if entity_type == "subobject" else "id"),
        sql.Identifier(TARGETS[entity_type])), (target_id,))
    row = cursor.fetchone()
    if row is None:
        raise DirectoryNotFound("Целевая запись не найдена")
    if entity_type == "subobject" and not row[0]:
        raise ValueError("Нельзя создать соответствие на неактивный подобъект")


def get_value_aliases(entity_type=None, source_value=None):
    if entity_type is not None:
        _validate_type(entity_type)
    with get_connection() as conn, conn.cursor() as cursor:
        cursor.execute(_SELECT + """ WHERE (%s::text IS NULL OR a.entity_type = %s)
            AND (%s::text IS NULL OR a.normalized_source_value = normalize_known_value(a.entity_type, %s))
            ORDER BY a.entity_type, a.normalized_source_value, a.id""",
                       (entity_type, entity_type, source_value, source_value))
        return [_item(row) for row in cursor.fetchall()]


def get_value_alias(alias_id):
    with get_connection() as conn, conn.cursor() as cursor:
        cursor.execute(_SELECT + " WHERE a.id = %s", (alias_id,))
        return _item(cursor.fetchone())


def resolve_value_alias(entity_type, source_value):
    """Return the exact alias with target/parent names, or None. Never learns."""
    _validate_type(entity_type)
    if source_value is None:
        return None
    items = get_value_aliases(entity_type, source_value)
    if not items or not items[0]["target_exists"] or items[0]["target_is_active"] is False:
        return None
    return items[0]


def create_value_alias(entity_type, source_value, target_id):
    _validate_type(entity_type)
    with get_connection() as conn, conn.cursor() as cursor:
        cursor.execute("SELECT normalize_known_value(%s, %s)", (entity_type, source_value))
        if not cursor.fetchone()[0]:
            raise ValueError("Исходное значение не заполнено")
        _validate_target(cursor, entity_type, target_id)
        cursor.execute("""INSERT INTO value_aliases(entity_type, source_value, target_id)
            VALUES (%s, %s, %s) ON CONFLICT (entity_type, normalized_source_value) DO NOTHING
            RETURNING id""", (entity_type, source_value, target_id))
        inserted = cursor.fetchone()
        if inserted:
            cursor.execute(_SELECT + " WHERE a.id = %s", (inserted[0],))
        else:
            cursor.execute(_SELECT + """ WHERE a.entity_type = %s
                AND a.normalized_source_value = normalize_known_value(%s, %s) FOR UPDATE OF a""",
                           (entity_type, entity_type, source_value))
        item = _item(cursor.fetchone())
        if item is None or item["target_id"] != target_id:
            raise DirectoryConflict("Для этого значения уже существует другое соответствие.")
        return {"item": item, "created": inserted is not None}


def update_value_alias_target(alias_id, target_id):
    with get_connection() as conn, conn.cursor() as cursor:
        cursor.execute("SELECT entity_type FROM value_aliases WHERE id = %s FOR UPDATE", (alias_id,))
        row = cursor.fetchone()
        if row is None:
            raise DirectoryNotFound("Соответствие не найдено")
        _validate_target(cursor, row[0], target_id)
        cursor.execute("UPDATE value_aliases SET target_id = %s WHERE id = %s", (target_id, alias_id))
        cursor.execute(_SELECT + " WHERE a.id = %s", (alias_id,))
        return _item(cursor.fetchone())


def delete_value_alias(alias_id):
    with get_connection() as conn, conn.cursor() as cursor:
        cursor.execute("DELETE FROM value_aliases WHERE id = %s RETURNING id", (alias_id,))
        if cursor.fetchone() is None:
            raise DirectoryNotFound("Соответствие не найдено")
        return {"id": alias_id, "deleted": True}
