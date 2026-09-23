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


def create_employee(
    full_name: str,
    position_id: int | None = None,
    phone: str | None = None,
    crew_id: int | None = None,
):
    """Добавить сотрудника."""

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO employees (
                    full_name,
                    position_id,
                    phone,
                    crew_id
                )
                VALUES (%s, %s, %s, %s)
                RETURNING id;
            """, (
                full_name.strip(),
                position_id,
                phone,
                crew_id,
            ))

            employee_id = cursor.fetchone()[0]

        conn.commit()

    return employee_id


def update_employee(
    employee_id: int,
    full_name: str,
    position_id: int | None,
    phone: str | None,
    crew_id: int | None,
):
    """Редактировать сотрудника."""

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE employees
                SET
                    full_name = %s,
                    position_id = %s,
                    phone = %s,
                    crew_id = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                RETURNING id;
            """, (
                full_name.strip(),
                position_id,
                phone,
                crew_id,
                employee_id,
            ))

            result = cursor.fetchone()

        conn.commit()

    return result is not None


def delete_employee(employee_id: int):
    """Удалить сотрудника."""

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                DELETE FROM employees
                WHERE id = %s
                RETURNING id;
            """, (employee_id,))

            result = cursor.fetchone()

        conn.commit()

    return result is not None
