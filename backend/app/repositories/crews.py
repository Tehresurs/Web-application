from app.database.db import get_connection


def get_all_crews():
    """Получить все экипажи."""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT
                    id,
                    name,
                    driver_full_name,
                    driver_phone,
                    vehicle_make,
                    vehicle_plate
                FROM crews
                ORDER BY name;
            """)
            return cursor.fetchall()


def get_crew(crew_id: int):
    """Получить один экипаж."""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT
                    id,
                    name,
                    driver_full_name,
                    driver_phone,
                    vehicle_make,
                    vehicle_plate
                FROM crews
                WHERE id = %s;
            """, (crew_id,))

            return cursor.fetchone()


def create_crew(
    name: str,
    driver_full_name: str,
    driver_phone: str | None = None,
    vehicle_make: str | None = None,
    vehicle_plate: str | None = None,
):
    """Создать экипаж."""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO crews (
                    name,
                    driver_full_name,
                    driver_phone,
                    vehicle_make,
                    vehicle_plate
                )
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id;
            """, (
                name.strip(),
                driver_full_name.strip(),
                driver_phone,
                vehicle_make,
                vehicle_plate,
            ))

            crew_id = cursor.fetchone()[0]

        conn.commit()

    return crew_id


def update_crew(
    crew_id: int,
    name: str,
    driver_full_name: str,
    driver_phone: str | None,
    vehicle_make: str | None,
    vehicle_plate: str | None,
):
    """Редактировать экипаж."""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE crews
                SET
                    name = %s,
                    driver_full_name = %s,
                    driver_phone = %s,
                    vehicle_make = %s,
                    vehicle_plate = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                RETURNING id;
            """, (
                name.strip(),
                driver_full_name.strip(),
                driver_phone,
                vehicle_make,
                vehicle_plate,
                crew_id,
            ))

            result = cursor.fetchone()

        conn.commit()

    return result is not None


def delete_crew(crew_id: int):
    """Удалить экипаж."""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                DELETE FROM crews
                WHERE id = %s
                RETURNING id;
            """, (crew_id,))

            result = cursor.fetchone()

        conn.commit()

    return result is not None
