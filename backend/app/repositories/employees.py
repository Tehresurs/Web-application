from app.database.db import get_connection
from app.repositories.directory_errors import DirectoryConflict, DirectoryNotFound

_UNSET = object()


def _validate_position_settings(work_location, work_schedule):
    if work_location not in (None, "OBJECT", "OFFICE"):
        raise ValueError("Место работы: выберите Объект или Офис")
    if work_schedule not in (None, "SHIFT", "FIVE_TWO"):
        raise ValueError("График: выберите Вахта или 5/2")
    if work_location == "OBJECT" and work_schedule != "SHIFT":
        raise ValueError("Для места работы Объект обязателен график Вахта")


def _validate_day_limits(*values):
    for value in values:
        if value is not _UNSET and value is not None and (type(value) is not int or not 0 < value <= 2147483647):
            raise ValueError("Количество дней должно быть положительным целым числом")


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
                    c.name AS crew, e.nrs_number, e.max_shift_days, e.max_off_shift_days,
                    p.specialty, p.work_location, p.work_schedule, e.dismissal_date,
                    e.is_archived, e.archived_at
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
                    action_description, specialty, work_location, work_schedule, report_description, aos_description, requires_daily_report, planned_count, equipment_description
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
            "specialty": row[3],
            "work_location": row[4],
            "work_schedule": row[5],
            "report_description": row[6] or "",
            "aos_description": row[7] or "", "requires_daily_report": row[8], "planned_count": row[9], "equipment_description": row[10],
        }
        for row in rows
    ]


def create_position(
    name: str,
    action_description: str | None = None,
    specialty=None, work_location=None, work_schedule=None,
    report_description=None, aos_description=None, requires_daily_report=False, planned_count=0, equipment_description=None,
):
    _validate_position_settings(work_location, work_schedule)
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
                    action_description, specialty, work_location, work_schedule, report_description, aos_description, requires_daily_report, planned_count, equipment_description
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING
                    id,
                    name,
                    action_description, specialty, work_location, work_schedule, report_description, aos_description, requires_daily_report, planned_count, equipment_description;
                """,
                (clean_name, clean_description, specialty, work_location, work_schedule, report_description, aos_description, requires_daily_report, planned_count, equipment_description),
            )

            row = cursor.fetchone()

    return {
        "id": row[0],
        "name": row[1],
        "action_description": row[2] or "",
        "specialty": row[3], "work_location": row[4], "work_schedule": row[5],
        "report_description": row[6] or "", "aos_description": row[7] or "", "requires_daily_report": row[8], "planned_count": row[9], "equipment_description": row[10],
    }


def rename_position(
    position_id: int,
    name: str,
    action_description: str | None = None,
    specialty=_UNSET, work_location=_UNSET, work_schedule=_UNSET,
    report_description=_UNSET, aos_description=_UNSET, requires_daily_report=_UNSET, planned_count=_UNSET, equipment_description=_UNSET,
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
                SELECT specialty, work_location, work_schedule, report_description, aos_description, requires_daily_report, planned_count, equipment_description
                FROM positions
                WHERE id = %s FOR UPDATE;
                """,
                (position_id,),
            )

            previous = cursor.fetchone()
            if previous is None:
                raise ValueError("Должность не найдена")

            specialty = previous[0] if specialty is _UNSET else specialty
            work_location = previous[1] if work_location is _UNSET else work_location
            work_schedule = previous[2] if work_schedule is _UNSET else work_schedule
            report_description = previous[3] if report_description is _UNSET else report_description
            aos_description = previous[4] if aos_description is _UNSET else aos_description
            equipment_description = previous[7] if equipment_description is _UNSET else equipment_description
            planned_count = previous[6] if planned_count is _UNSET else planned_count
            requires_daily_report = previous[5] if requires_daily_report is _UNSET else requires_daily_report
            _validate_position_settings(work_location, work_schedule)

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
                    specialty = %s, work_location = %s, work_schedule = %s,
                    report_description = %s, aos_description = %s, requires_daily_report = %s, planned_count = %s, equipment_description = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                RETURNING
                    id,
                    name,
                    action_description, specialty, work_location, work_schedule, report_description, aos_description, requires_daily_report, planned_count, equipment_description;
                """,
                (clean_name, clean_description, specialty, work_location, work_schedule, report_description, aos_description, requires_daily_report, planned_count, equipment_description, position_id),
            )

            row = cursor.fetchone()

    return {
        "id": row[0],
        "name": row[1],
        "action_description": row[2] or "",
        "specialty": row[3], "work_location": row[4], "work_schedule": row[5],
        "report_description": row[6] or "", "aos_description": row[7] or "", "requires_daily_report": row[8], "planned_count": row[9], "equipment_description": row[10],
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


def get_employees(archived=False):
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
                    COUNT(DISTINCT ea.object_id) AS objects_count,
                    e.nrs_number, e.max_shift_days, e.max_off_shift_days,
                    p.specialty, p.work_location, p.work_schedule, e.dismissal_date,
                    e.is_archived, e.archived_at, e.email
                FROM employees e
                LEFT JOIN positions p
                    ON p.id = e.position_id
                LEFT JOIN crews c
                    ON c.id = e.crew_id
                LEFT JOIN employee_assignments ea
                    ON ea.employee_id = e.id
                WHERE (%s::boolean IS NULL OR e.is_archived=%s)
                GROUP BY
                    e.id,
                    e.full_name,
                    e.position_id,
                    p.name,
                    p.action_description,
                    e.phone,
                    e.crew_id,
                    c.name, p.specialty, p.work_location, p.work_schedule
                ORDER BY e.full_name;
                """, (archived, archived)
            )
            rows = cursor.fetchall()

        items = [
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
            "nrs_number": row[9], "max_shift_days": row[10], "max_off_shift_days": row[11],
            "specialty": row[12], "work_location": row[13], "work_schedule": row[14],
            "dismissal_date": row[15],
            "is_archived": row[16],
            "archived_at": row[17], "email": row[18],
        }
        for row in rows
        ]
        from app.repositories.personnel_transfers import current_positions
        return current_positions(conn,items)


def create_employee(
    full_name: str,
    position_id: int | None = None,
    phone: str | None = None,
    crew_id: int | None = None,
    nrs_number=None, max_shift_days=None, max_off_shift_days=None, dismissal_date=None, email=None,
):
    _validate_day_limits(max_shift_days, max_off_shift_days)
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
                    crew_id, nrs_number, max_shift_days, max_off_shift_days, dismissal_date, email
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id;
                """,
                (
                    clean_name,
                    position_id,
                    phone.strip() if phone else None,
                    crew_id, nrs_number, max_shift_days, max_off_shift_days, dismissal_date, email.strip() if email else None,
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
    nrs_number=_UNSET, max_shift_days=_UNSET, max_off_shift_days=_UNSET, dismissal_date=_UNSET, email=_UNSET,
):
    _validate_day_limits(max_shift_days, max_off_shift_days)
    clean_name = " ".join(full_name.split())

    if not clean_name:
        raise ValueError("ФИО сотрудника не заполнено")

    with get_connection() as conn:
        from app.repositories.personnel_transfers import installed
        if installed(conn):
            conn.execute('SELECT pg_advisory_xact_lock(20261017,29)')
            stored=conn.execute('SELECT position_id FROM employees WHERE id=%s FOR UPDATE',(employee_id,)).fetchone()
            if stored is None:raise DirectoryNotFound('Сотрудник не найден')
            from app.services.luvr_duration import local_today
            effective=conn.execute('SELECT personnel_position_at(%s,%s)',(employee_id,local_today())).fetchone()[0]
            current=effective.get('position_id') if effective.get('status')=='KNOWN' else stored[0]
            if position_id!=current:raise DirectoryConflict('Для изменения основной должности оформите перевод')
            # position_id is a retained legacy observation, never a current cache.
            position_id=stored[0]
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
                    email = CASE WHEN %s THEN %s ELSE email END,
                    dismissal_date = CASE WHEN %s THEN %s ELSE dismissal_date END,
                    nrs_number = CASE WHEN %s THEN %s ELSE nrs_number END,
                    max_shift_days = CASE WHEN %s THEN %s ELSE max_shift_days END,
                    max_off_shift_days = CASE WHEN %s THEN %s ELSE max_off_shift_days END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s;
                """,
                (
                    clean_name,
                    position_id,
                    phone.strip() if phone else None,
                    crew_id,
                    email is not _UNSET, None if email is _UNSET or not email else email.strip(),
                    dismissal_date is not _UNSET, None if dismissal_date is _UNSET else dismissal_date,
                    nrs_number is not _UNSET, None if nrs_number is _UNSET else nrs_number,
                    max_shift_days is not _UNSET, None if max_shift_days is _UNSET else max_shift_days,
                    max_off_shift_days is not _UNSET, None if max_off_shift_days is _UNSET else max_off_shift_days,
                    employee_id,
                ),
            )

    return employee_id


def delete_employee(employee_id: int):
    """Compatibility guard: employees can only be archived, never deleted here."""
    raise DirectoryConflict("Физическое удаление сотрудников отключено. Используйте действие «В архив». История сотрудника будет сохранена.")


def set_employee_archived(employee_id: int, archived: bool):
    with get_connection() as conn, conn.cursor() as cursor:
        cursor.execute("""UPDATE employees SET
            is_archived=%s,
            archived_at=CASE WHEN %s THEN COALESCE(archived_at,LOCALTIMESTAMP) ELSE NULL END,
            updated_at=CASE WHEN is_archived IS DISTINCT FROM %s THEN CURRENT_TIMESTAMP ELSE updated_at END
            WHERE id=%s
            RETURNING id,full_name,is_archived,archived_at,dismissal_date""",
            (archived, archived, archived, employee_id))
        row=cursor.fetchone()
        if row is None:
            raise DirectoryNotFound("Сотрудник не найден")
        return dict(zip(("id","full_name","is_archived","archived_at","dismissal_date"),row))


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
