from app.database.db import get_connection


def get_contractors():
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, name
                FROM contractors
                ORDER BY name;
                """
            )
            rows = cursor.fetchall()

    return [{"id": row[0], "name": row[1]} for row in rows]


def create_contractor(name: str):
    clean_name = " ".join(name.split())
    if not clean_name:
        raise ValueError("Укажите наименование организации")

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id
                FROM contractors
                WHERE LOWER(TRIM(name)) = LOWER(TRIM(%s));
                """,
                (clean_name,),
            )
            if cursor.fetchone():
                raise ValueError("Такая организация уже существует")

            cursor.execute(
                """
                INSERT INTO contractors (name)
                VALUES (%s)
                RETURNING id, name;
                """,
                (clean_name,),
            )
            row = cursor.fetchone()

    return {"id": row[0], "name": row[1]}


def update_contractor(contractor_id: int, name: str):
    clean_name = " ".join(name.split())
    if not clean_name:
        raise ValueError("Укажите наименование организации")

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id
                FROM contractors
                WHERE id = %s;
                """,
                (contractor_id,),
            )
            if cursor.fetchone() is None:
                raise ValueError("Организация не найдена")

            cursor.execute(
                """
                SELECT id
                FROM contractors
                WHERE LOWER(TRIM(name)) = LOWER(TRIM(%s))
                  AND id <> %s;
                """,
                (clean_name, contractor_id),
            )
            if cursor.fetchone():
                raise ValueError("Такая организация уже существует")

            cursor.execute(
                """
                UPDATE contractors
                SET
                    name = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                RETURNING id, name;
                """,
                (clean_name, contractor_id),
            )
            row = cursor.fetchone()

    return {"id": row[0], "name": row[1]}


def delete_contractor(contractor_id: int):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM object_contractors
                WHERE contractor_id = %s;
                """,
                (contractor_id,),
            )
            object_count = cursor.fetchone()[0]
            if object_count > 0:
                raise ValueError(
                    f"Организация используется на объектах: {object_count}"
                )

            cursor.execute(
                """
                DELETE FROM contractors
                WHERE id = %s
                RETURNING id, name;
                """,
                (contractor_id,),
            )
            row = cursor.fetchone()
            if row is None:
                raise ValueError("Организация не найдена")

    return {"id": row[0], "name": row[1], "deleted": True}
