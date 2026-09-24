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


def create_object(
    name: str,
    category_id: int | None,
    po_ids: list[int],
):
    """
    Создаёт объект и связи с ПО одной транзакцией.
    """

    clean_name = " ".join(name.split())

    if not clean_name:
        raise ValueError(
            "Наименование объекта не заполнено"
        )

    unique_po_ids = list(dict.fromkeys(po_ids))

    with get_connection() as conn:

        with conn.cursor() as cursor:

            # ---------------------------------
            # 1. Проверяем дублирование объекта
            # ---------------------------------

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
                    f"Объект уже существует в базе: "
                    f"{existing[1]}"
                )

            # ---------------------------------
            # 2. Проверяем категорию
            # ---------------------------------

            if category_id is not None:

                cursor.execute(
                    """
                    SELECT id
                    FROM object_categories
                    WHERE id = %s;
                    """,
                    (category_id,),
                )

                if cursor.fetchone() is None:
                    raise ValueError(
                        "Выбранная категория объекта "
                        "не найдена"
                    )

            # ---------------------------------
            # 3. Проверяем ПО
            # ---------------------------------

            if unique_po_ids:

                cursor.execute(
                    """
                    SELECT id
                    FROM po_types
                    WHERE id = ANY(%s);
                    """,
                    (unique_po_ids,),
                )

                found_po_ids = {
                    row[0]
                    for row in cursor.fetchall()
                }

                missing_po_ids = (
                    set(unique_po_ids)
                    - found_po_ids
                )

                if missing_po_ids:
                    raise ValueError(
                        "Некоторые выбранные ПО "
                        "не найдены в базе"
                    )

            # ---------------------------------
            # 4. Создаём объект
            # ---------------------------------

            cursor.execute(
                """
                INSERT INTO construction_objects
                    (name, category_id)
                VALUES
                    (%s, %s)
                RETURNING id, name, category_id;
                """,
                (
                    clean_name,
                    category_id,
                ),
            )

            row = cursor.fetchone()

            object_id = row[0]

            # ---------------------------------
            # 5. Создаём связи объект ↔ ПО
            # ---------------------------------

            for po_id in unique_po_ids:

                cursor.execute(
                    """
                    INSERT INTO object_po
                        (object_id, po_id)
                    VALUES
                        (%s, %s);
                    """,
                    (
                        object_id,
                        po_id,
                    ),
                )

        # psycopg context выполнит COMMIT,
        # если исключения не возникло.

    return {
        "id": row[0],
        "name": row[1],
        "category_id": row[2],
        "po_ids": unique_po_ids,
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

            # Проверяем использование подкатегории объектами.
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM construction_objects
                WHERE category_id = %s;
                """,
                (category_id_db,),
            )

            object_count = cursor.fetchone()[0]

            if object_count > 0:
                raise ValueError(
                    f'Подкатегория "{category_name}" '
                    f"используется для {object_count} объектов. "
                    f"Сначала необходимо перенести объекты."
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
                FROM object_po
                WHERE po_id = %s;
                """,
                (po_id,),
            )

            object_count = cursor.fetchone()[0]

            if object_count > 0:
                raise ValueError(
                    f'ПО "{po[1]}" используется для '
                    f"{object_count} объектов и не может быть удалено."
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
