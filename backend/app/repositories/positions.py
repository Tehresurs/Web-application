from app.database.db import get_connection


def get_all_positions():
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT id, name, action_description
                FROM positions
                ORDER BY name;
            """)
            return cursor.fetchall()


def create_position(name: str, action_description: str | None = None):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO positions (name, action_description)
                VALUES (%s, %s)
                RETURNING id;
            """, (name.strip(), action_description))

            position_id = cursor.fetchone()[0]

        conn.commit()

    return position_id


def update_position(
    position_id: int,
    name: str,
    action_description: str | None = None
):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE positions
                SET
                    name = %s,
                    action_description = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                RETURNING id;
            """, (
                name.strip(),
                action_description,
                position_id
            ))

            result = cursor.fetchone()

        conn.commit()

    return result is not None
