from app.database.db import get_connection


def get_all_employees():
    """Получить всех сотрудников."""

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT
                    e.id,
                    e.full_name,
                    p.name AS position,
                    e.phone,
                    c.name AS crew
                FROM employees e
                LEFT JOIN positions p
                    ON e.position_id = p.id
                LEFT JOIN crews c
                    ON e.crew_id = c.id
                ORDER BY e.full_name;
            """)

            return cursor.fetchall()


def get_employee(employee_id: int):
    """Получить одного сотрудника."""

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT
                    e.id,
                    e.full_name,
                    e.position_id,
                    p.name AS position,
                    p.action_description,
                    e.phone,
                    e.crew_id,
                    c.name AS crew
                FROM employees e
                LEFT JOIN positions p
                    ON e.position_id = p.id
                LEFT JOIN crews c
                    ON e.crew_id = c.id
                WHERE e.id = %s;
            """, (employee_id,))

            return cursor.fetchone()








def get_positions():
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    id,
                    name,
                    action_description
                FROM positions
                ORDER BY name;
                """
            )
            rows = cursor.fetchall()

    return [
        {
            "id": row[0],
            "name": row[1],
            "action_description": row[2] or "",
        }
        for row in rows
    ]


def create_position(
    name: str,
    action_description: str | None = None,
):
    clean_name = " ".join(name.split())
    clean_description = (
        action_description.strip()
        if action_description
        else None
    )

    if not clean_name:
        raise ValueError("Название должности не заполнено")

    with get_connection() as conn:
        with conn.cursor() as cursor:

            cursor.execute(
                """
                SELECT id
                FROM positions
                WHERE LOWER(TRIM(name)) = LOWER(TRIM(%s));
                """,
                (clean_name,),
            )

            if cursor.fetchone():
                raise ValueError(
                    "Должность с таким названием уже существует"
                )

            cursor.execute(
                """
                INSERT INTO positions (
                    name,
                    action_description
                )
                VALUES (%s, %s)
                RETURNING
                    id,
                    name,
                    action_description;
                """,
                (clean_name, clean_description),
            )

            row = cursor.fetchone()

    return {
        "id": row[0],
        "name": row[1],
        "action_description": row[2] or "",
    }


def rename_position(
    position_id: int,
    name: str,
    action_description: str | None = None,
):
    clean_name = " ".join(name.split())
    clean_description = (
        action_description.strip()
        if action_description
        else None
    )

    if not clean_name:
        raise ValueError("Название должности не заполнено")

    with get_connection() as conn:
        with conn.cursor() as cursor:

            cursor.execute(
                """
                SELECT id
                FROM positions
                WHERE id = %s;
                """,
                (position_id,),
            )

            if cursor.fetchone() is None:
                raise ValueError("Должность не найдена")

            cursor.execute(
                """
                SELECT id
                FROM positions
                WHERE LOWER(TRIM(name)) = LOWER(TRIM(%s))
                  AND id <> %s;
                """,
                (clean_name, position_id),
            )

            if cursor.fetchone():
                raise ValueError(
                    "Должность с таким названием уже существует"
                )

            cursor.execute(
                """
                UPDATE positions
                SET
                    name = %s,
                    action_description = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                RETURNING
                    id,
                    name,
                    action_description;
                """,
                (clean_name, clean_description, position_id),
            )

            row = cursor.fetchone()

    return {
        "id": row[0],
        "name": row[1],
        "action_description": row[2] or "",
    }


def delete_position(position_id: int):
    with get_connection() as conn:
        with conn.cursor() as cursor:

            cursor.execute(
                """
                SELECT id, name
                FROM positions
                WHERE id = %s;
                """,
                (position_id,),
            )

            position = cursor.fetchone()

            if position is None:
                raise ValueError("Должность не найдена")

            cursor.execute(
                """
                DELETE FROM positions
                WHERE id = %s;
                """,
                (position_id,),
            )

    return {
        "id": position[0],
        "name": position[1],
        "deleted": True,
    }


def get_employees():
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    e.id,
                    e.full_name,
                    e.position_id,
                    p.name AS position_name,
                    p.action_description,
                    e.phone,
                    e.crew_id,
                    c.name AS crew_name,
                    COUNT(DISTINCT ea.object_id) AS objects_count
                FROM employees e
                LEFT JOIN positions p
                    ON p.id = e.position_id
                LEFT JOIN crews c
                    ON c.id = e.crew_id
                LEFT JOIN employee_assignments ea
                    ON ea.employee_id = e.id
                GROUP BY
                    e.id,
                    e.full_name,
                    e.position_id,
                    p.name,
                    p.action_description,
                    e.phone,
                    e.crew_id,
                    c.name
                ORDER BY e.full_name;
                """
            )
            rows = cursor.fetchall()

    return [
        {
            "id": row[0],
            "full_name": row[1],
            "position_id": row[2],
            "position_name": row[3],
            "action_description": row[4] or "",
            "phone": row[5] or "",
            "crew_id": row[6],
            "crew_name": row[7],
            "objects_count": row[8],
        }
        for row in rows
    ]


def create_employee(
    full_name: str,
    position_id: int | None = None,
    phone: str | None = None,
    crew_id: int | None = None,
):
    clean_name = " ".join(full_name.split())

    if not clean_name:
        raise ValueError("ФИО сотрудника не заполнено")

    with get_connection() as conn:
        with conn.cursor() as cursor:

            cursor.execute(
                """
                SELECT id
                FROM employees
                WHERE LOWER(TRIM(full_name)) = LOWER(TRIM(%s));
                """,
                (clean_name,),
            )

            if cursor.fetchone():
                raise ValueError("Сотрудник с таким ФИО уже существует")

            cursor.execute(
                """
                INSERT INTO employees (
                    full_name,
                    position_id,
                    phone,
                    crew_id
                )
                VALUES (%s, %s, %s, %s)
                RETURNING id;
                """,
                (
                    clean_name,
                    position_id,
                    phone.strip() if phone else None,
                    crew_id,
                ),
            )

            employee_id = cursor.fetchone()[0]

    return employee_id


def update_employee(
    employee_id: int,
    full_name: str,
    position_id: int | None = None,
    phone: str | None = None,
    crew_id: int | None = None,
):
    clean_name = " ".join(full_name.split())

    if not clean_name:
        raise ValueError("ФИО сотрудника не заполнено")

    with get_connection() as conn:
        with conn.cursor() as cursor:

            cursor.execute(
                """
                SELECT id
                FROM employees
                WHERE id = %s;
                """,
                (employee_id,),
            )

            if cursor.fetchone() is None:
                raise ValueError("Сотрудник не найден")

            cursor.execute(
                """
                SELECT id
                FROM employees
                WHERE LOWER(TRIM(full_name)) = LOWER(TRIM(%s))
                  AND id <> %s;
                """,
                (clean_name, employee_id),
            )

            if cursor.fetchone():
                raise ValueError("Сотрудник с таким ФИО уже существует")

            cursor.execute(
                """
                UPDATE employees
                SET
                    full_name = %s,
                    position_id = %s,
                    phone = %s,
                    crew_id = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s;
                """,
                (
                    clean_name,
                    position_id,
                    phone.strip() if phone else None,
                    crew_id,
                    employee_id,
                ),
            )

    return employee_id


def delete_employee(employee_id: int):
    with get_connection() as conn:
        with conn.cursor() as cursor:

            cursor.execute(
                """
                DELETE FROM employees
                WHERE id = %s
                RETURNING id, full_name;
                """,
                (employee_id,),
            )

            row = cursor.fetchone()

            if row is None:
                raise ValueError("Сотрудник не найден")

    return {
        "id": row[0],
        "full_name": row[1],
        "deleted": True,
    }


def get_crews():
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    id,
                    name,
                    driver_full_name,
                    driver_phone,
                    vehicle_make,
                    vehicle_plate
                FROM crews
                ORDER BY name;
                """
            )
            rows = cursor.fetchall()

    return [
        {
            "id": row[0],
            "name": row[1],
            "driver_full_name": row[2] or "",
            "driver_phone": row[3] or "",
            "vehicle_make": row[4] or "",
            "vehicle_plate": row[5] or "",
        }
        for row in rows
    ]


def create_crew(
    driver_full_name: str,
    driver_phone: str | None = None,
    vehicle_make: str | None = None,
    vehicle_plate: str | None = None,
):
    driver = " ".join(driver_full_name.split())

    if not driver:
        raise ValueError("Укажите ФИО водителя")

    with get_connection() as conn:
        with conn.cursor() as cursor:
            # Не допускаем двух экипажей с одним водителем.
            cursor.execute(
                """
                SELECT id
                FROM crews
                WHERE LOWER(TRIM(driver_full_name)) = LOWER(TRIM(%s));
                """,
                (driver,),
            )

            if cursor.fetchone():
                raise ValueError("Экипаж с таким водителем уже существует")

            # Формируем техническое уникальное название.
            cursor.execute(
                """
                SELECT COALESCE(MAX(id), 0) + 1
                FROM crews;
                """
            )
            next_number = cursor.fetchone()[0]
            technical_name = f"Экипаж №{next_number}"

            cursor.execute(
                """
                INSERT INTO crews (
                    name,
                    driver_full_name,
                    driver_phone,
                    vehicle_make,
                    vehicle_plate
                )
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id;
                """,
                (
                    technical_name,
                    driver,
                    driver_phone.strip() if driver_phone else None,
                    vehicle_make.strip() if vehicle_make else None,
                    vehicle_plate.strip() if vehicle_plate else None,
                ),
            )

            crew_id = cursor.fetchone()[0]

    return crew_id


def update_crew(
    crew_id: int,
    driver_full_name: str,
    driver_phone: str | None = None,
    vehicle_make: str | None = None,
    vehicle_plate: str | None = None,
):
    driver = " ".join(driver_full_name.split())

    if not driver:
        raise ValueError("Укажите ФИО водителя")

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id
                FROM crews
                WHERE id = %s;
                """,
                (crew_id,),
            )

            if cursor.fetchone() is None:
                raise ValueError("Экипаж не найден")

            cursor.execute(
                """
                SELECT id
                FROM crews
                WHERE LOWER(TRIM(driver_full_name)) = LOWER(TRIM(%s))
                  AND id <> %s;
                """,
                (driver, crew_id),
            )

            if cursor.fetchone():
                raise ValueError("Экипаж с таким водителем уже существует")

            cursor.execute(
                """
                UPDATE crews
                SET
                    driver_full_name = %s,
                    driver_phone = %s,
                    vehicle_make = %s,
                    vehicle_plate = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s;
                """,
                (
                    driver,
                    driver_phone.strip() if driver_phone else None,
                    vehicle_make.strip() if vehicle_make else None,
                    vehicle_plate.strip() if vehicle_plate else None,
                    crew_id,
                ),
            )

    return crew_id


def delete_crew(crew_id: int):
    with get_connection() as conn:
        with conn.cursor() as cursor:

            # Сначала узнаём, сколько сотрудников закреплено за экипажем.
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM employees
                WHERE crew_id = %s;
                """,
                (crew_id,),
            )

            employee_count = cursor.fetchone()[0]

            cursor.execute(
                """
                DELETE FROM crews
                WHERE id = %s
                RETURNING id, driver_full_name;
                """,
                (crew_id,),
            )

            row = cursor.fetchone()

            if row is None:
                raise ValueError("Экипаж не найден")

    return {
        "id": row[0],
        "driver_full_name": row[1],
        "employee_count": employee_count,
        "deleted": True,
    }
