from app.database.db import get_connection


def get_object_categories():
    """Возвращает основные категории вместе с подкатегориями."""

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    id,
                    name,
                    parent_id,
                    sort_order,
                    is_system
                FROM object_categories
                ORDER BY
                    CASE
                        WHEN parent_id IS NULL THEN sort_order
                        ELSE (
                            SELECT parent.sort_order
                            FROM object_categories parent
                            WHERE parent.id = object_categories.parent_id
                        )
                    END,
                    CASE
                        WHEN parent_id IS NULL THEN 0
                        ELSE 1
                    END,
                    sort_order,
                    name;
                """
            )

            rows = cursor.fetchall()

    categories = {}
    roots = []

    for row in rows:
        item = {
            "id": row[0],
            "name": row[1],
            "parent_id": row[2],
            "sort_order": row[3],
            "is_system": row[4],
            "children": [],
        }

        categories[item["id"]] = item

        if item["parent_id"] is None:
            roots.append(item)

    for item in categories.values():
        parent_id = item["parent_id"]

        if parent_id is not None:
            parent = categories.get(parent_id)

            if parent:
                parent["children"].append(item)

    return roots


def get_po_types():
    """Возвращает доступные типы ПО."""

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, name
                FROM po_types
                ORDER BY name;
                """
            )

            rows = cursor.fetchall()

    return [
        {
            "id": row[0],
            "name": row[1],
        }
        for row in rows
    ]



def get_objects():
    """Возвращает все объекты строительства."""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, name
                FROM construction_objects
                ORDER BY name;
                """
            )
            rows = cursor.fetchall()

    return [{"id": row[0], "name": row[1]} for row in rows]


def update_object(object_id: int, name: str):
    """Переименовывает объект строительства."""
    clean_name = " ".join(name.split())
    if not clean_name:
        raise ValueError("Наименование объекта не заполнено")

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM construction_objects WHERE id = %s;",
                (object_id,),
            )
            if cursor.fetchone() is None:
                raise ValueError("Объект не найден")

            cursor.execute(
                """
                SELECT id
                FROM construction_objects
                WHERE LOWER(TRIM(name)) = LOWER(TRIM(%s))
                  AND id <> %s
                LIMIT 1;
                """,
                (clean_name, object_id),
            )
            if cursor.fetchone():
                raise ValueError("Объект с таким наименованием уже существует")

            cursor.execute(
                """
                UPDATE construction_objects
                SET name = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                RETURNING id, name;
                """,
                (clean_name, object_id),
            )
            row = cursor.fetchone()

    return {"id": row[0], "name": row[1]}


def delete_object(object_id: int):
    """Удаляет объект, если он не используется в назначениях сотрудников."""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, name FROM construction_objects WHERE id = %s;",
                (object_id,),
            )
            row = cursor.fetchone()
            if row is None:
                raise ValueError("Объект не найден")

            cursor.execute(
                """
                SELECT COUNT(*)
                FROM employee_assignments
                WHERE object_id = %s;
                """,
                (object_id,),
            )
            assignment_count = cursor.fetchone()[0]
            if assignment_count > 0:
                raise ValueError(
                    f'Объект "{row[1]}" используется в '
                    f'{assignment_count} назначениях сотрудников '
                    f'и не может быть удалён.'
                )

            cursor.execute(
                "DELETE FROM construction_objects WHERE id = %s;",
                (object_id,),
            )

    return {"id": object_id, "deleted": True}

def create_object(name: str):
    """Создаёт объект строительства."""

    clean_name = " ".join(name.split())

    if not clean_name:
        raise ValueError("Наименование объекта не заполнено")

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, name
                FROM construction_objects
                WHERE LOWER(TRIM(name)) = LOWER(TRIM(%s))
                LIMIT 1;
                """,
                (clean_name,),
            )

            existing = cursor.fetchone()

            if existing:
                raise ValueError(
                    f"Объект уже существует в базе: {existing[1]}"
                )

            cursor.execute(
                """
                INSERT INTO construction_objects (name)
                VALUES (%s)
                RETURNING id, name;
                """,
                (clean_name,),
            )

            row = cursor.fetchone()

    return {
        "id": row[0],
        "name": row[1],
    }

def create_subcategory(parent_id: int, name: str):
    clean_name = " ".join(name.split())

    if not clean_name:
        raise ValueError("Название подкатегории не заполнено")

    with get_connection() as conn:
        with conn.cursor() as cursor:

            # Родитель должен существовать.
            cursor.execute(
                """
                SELECT id, name
                FROM object_categories
                WHERE id = %s
                  AND parent_id IS NULL;
                """,
                (parent_id,),
            )

            parent = cursor.fetchone()

            if parent is None:
                raise ValueError("Основная категория не найдена")

            # Пока разрешаем пользовательские подкатегории
            # только внутри категории «Прочее».
            if parent[1] != "Прочее":
                raise ValueError(
                    "Подкатегории можно добавлять только в «Прочее»"
                )

            # Проверяем название.
            cursor.execute(
                """
                SELECT id
                FROM object_categories
                WHERE LOWER(TRIM(name)) = LOWER(TRIM(%s));
                """,
                (clean_name,),
            )

            if cursor.fetchone():
                raise ValueError(
                    "Категория или подкатегория с таким названием уже существует"
                )

            # Определяем следующий номер внутри «Прочее».
            cursor.execute(
                """
                SELECT COALESCE(MAX(sort_order), 0) + 1
                FROM object_categories
                WHERE parent_id = %s;
                """,
                (parent_id,),
            )

            next_order = cursor.fetchone()[0]

            cursor.execute(
                """
                INSERT INTO object_categories
                    (
                        name,
                        parent_id,
                        sort_order,
                        is_system
                    )
                VALUES (%s, %s, %s, FALSE)
                RETURNING
                    id,
                    name,
                    parent_id,
                    sort_order,
                    is_system;
                """,
                (
                    clean_name,
                    parent_id,
                    next_order,
                ),
            )

            row = cursor.fetchone()

    return {
        "id": row[0],
        "name": row[1],
        "parent_id": row[2],
        "sort_order": row[3],
        "is_system": row[4],
        "number": f"6.{row[3]}",
    }


def rename_subcategory(category_id: int, name: str):
    clean_name = " ".join(name.split())

    if not clean_name:
        raise ValueError("Название подкатегории не заполнено")

    with get_connection() as conn:
        with conn.cursor() as cursor:

            cursor.execute(
                """
                SELECT id, is_system, parent_id
                FROM object_categories
                WHERE id = %s;
                """,
                (category_id,),
            )

            category = cursor.fetchone()

            if category is None:
                raise ValueError("Подкатегория не найдена")

            if category[1]:
                raise ValueError(
                    "Основную категорию изменять нельзя"
                )

            if category[2] is None:
                raise ValueError(
                    "Можно изменять только подкатегории"
                )

            cursor.execute(
                """
                SELECT id
                FROM object_categories
                WHERE LOWER(TRIM(name)) = LOWER(TRIM(%s))
                  AND id <> %s;
                """,
                (clean_name, category_id),
            )

            if cursor.fetchone():
                raise ValueError(
                    "Такое название уже используется"
                )

            cursor.execute(
                """
                UPDATE object_categories
                SET
                    name = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                RETURNING id, name, parent_id, sort_order;
                """,
                (clean_name, category_id),
            )

            row = cursor.fetchone()

    return {
        "id": row[0],
        "name": row[1],
        "parent_id": row[2],
        "sort_order": row[3],
    }


def delete_subcategory(category_id: int):
    with get_connection() as conn:
        with conn.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    id,
                    name,
                    parent_id,
                    sort_order,
                    is_system
                FROM object_categories
                WHERE id = %s;
                """,
                (category_id,),
            )

            category = cursor.fetchone()

            if category is None:
                raise ValueError("Подкатегория не найдена")

            category_id_db = category[0]
            category_name = category[1]
            parent_id = category[2]
            deleted_sort_order = category[3]
            is_system = category[4]

            if is_system:
                raise ValueError(
                    "Основную категорию удалять нельзя"
                )

            if parent_id is None:
                raise ValueError(
                    "Удалять можно только подкатегории"
                )

            # Проверяем использование категории в назначениях сотрудников.
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM employee_assignments
                WHERE category_id = %s;
                """,
                (category_id_db,),
            )

            assignment_count = cursor.fetchone()[0]

            if assignment_count > 0:
                raise ValueError(
                    f'Подкатегория "{category_name}" '
                    f"используется в {assignment_count} назначениях сотрудников "
                    f"и не может быть удалена."
                )

            # Удаляем.
            cursor.execute(
                """
                DELETE FROM object_categories
                WHERE id = %s;
                """,
                (category_id_db,),
            )

            # Закрываем образовавшийся разрыв.
            cursor.execute(
                """
                UPDATE object_categories
                SET
                    sort_order = sort_order - 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE parent_id = %s
                  AND sort_order > %s;
                """,
                (
                    parent_id,
                    deleted_sort_order,
                ),
            )

    return {
        "id": category_id_db,
        "name": category_name,
        "deleted": True,
    }


def create_po_type(name: str):
    clean_name = " ".join(name.split())

    if not clean_name:
        raise ValueError("Наименование ПО не заполнено")

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id
                FROM po_types
                WHERE LOWER(TRIM(name)) = LOWER(TRIM(%s));
                """,
                (clean_name,),
            )

            if cursor.fetchone():
                raise ValueError("ПО с таким наименованием уже существует")

            cursor.execute(
                """
                INSERT INTO po_types (name)
                VALUES (%s)
                RETURNING id, name;
                """,
                (clean_name,),
            )

            row = cursor.fetchone()

    return {
        "id": row[0],
        "name": row[1],
    }


def rename_po_type(po_id: int, name: str):
    clean_name = " ".join(name.split())

    if not clean_name:
        raise ValueError("Наименование ПО не заполнено")

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id
                FROM po_types
                WHERE id = %s;
                """,
                (po_id,),
            )

            if cursor.fetchone() is None:
                raise ValueError("ПО не найдено")

            cursor.execute(
                """
                SELECT id
                FROM po_types
                WHERE LOWER(TRIM(name)) = LOWER(TRIM(%s))
                  AND id <> %s;
                """,
                (clean_name, po_id),
            )

            if cursor.fetchone():
                raise ValueError("ПО с таким наименованием уже существует")

            cursor.execute(
                """
                UPDATE po_types
                SET name = %s
                WHERE id = %s
                RETURNING id, name;
                """,
                (clean_name, po_id),
            )

            row = cursor.fetchone()

    return {
        "id": row[0],
        "name": row[1],
    }


def delete_po_type(po_id: int):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, name
                FROM po_types
                WHERE id = %s;
                """,
                (po_id,),
            )

            po = cursor.fetchone()

            if po is None:
                raise ValueError("ПО не найдено")

            cursor.execute(
                """
                SELECT COUNT(*)
                FROM employee_assignments
                WHERE po_id = %s;
                """,
                (po_id,),
            )

            assignment_count = cursor.fetchone()[0]

            if assignment_count > 0:
                raise ValueError(
                    f'ПО "{po[1]}" используется в '
                    f"{assignment_count} назначениях сотрудников "
                    f"и не может быть удалено."
                )

            cursor.execute(
                """
                DELETE FROM po_types
                WHERE id = %s;
                """,
                (po_id,),
            )

    return {
        "id": po[0],
        "name": po[1],
        "deleted": True,
    }
