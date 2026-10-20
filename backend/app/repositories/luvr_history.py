"""Stored facts only: no calendar calculation, inferred events or monthly copies."""
from datetime import datetime, time

from psycopg import sql
from psycopg.errors import ForeignKeyViolation, RestrictViolation
from psycopg.rows import dict_row

from app.database.db import get_connection
from app.repositories.directory_errors import DirectoryNotFound, DirectoryConflict


# Internal whitelist, never table/column names supplied by an HTTP client.
_KINDS = {
    "movements": ("employee_movements", "event_datetime", ("movement_type", "transport_type", "event_datetime", "departure_station", "arrival_station", "source_file")),
    "sick-periods": ("employee_sick_periods", "date_from", ("date_from", "date_to", "comment")),
    "duration-exceptions": ("employee_duration_exceptions", "date_from", ("exception_type", "date_from", "date_to", "comment")),
    "day-overrides": ("employee_luvr_day_overrides", "work_date", ("work_date", "value", "comment")),
}


def _employee(cursor, employee_id):
    from app.access_context import read_only_request
    lock='' if read_only_request.get() else ' FOR KEY SHARE'
    cursor.execute('SELECT id FROM employees WHERE id=%s'+lock, (employee_id,))
    if cursor.fetchone() is None:
        raise DirectoryNotFound("Сотрудник не найден")


def _validate(kind, values):
    if kind == "movements":
        if values.get("movement_type") not in ("ARRIVAL", "DEPARTURE"):
            raise ValueError("Укажите заезд или выезд")
        if values.get("transport_type") not in ("RAIL", "SELF"):
            raise ValueError("Некорректный способ перемещения")
        event = values.get("event_datetime")
        if not isinstance(event, datetime) or event.tzinfo is not None:
            raise ValueError("Укажите местные дату и время без часового пояса")
        if values["transport_type"] == "SELF" and values.get("source_file") is not None:
            raise ValueError("Для самостоятельного перемещения файл не указывается")
    elif kind in ("sick-periods", "duration-exceptions"):
        start, end = values.get("date_from"), values.get("date_to")
        if start is None or (kind == "duration-exceptions" and end is None):
            raise ValueError("Укажите даты периода")
        if end is not None and end < start:
            raise ValueError("Дата окончания не может быть раньше даты начала")
        if kind == "duration-exceptions":
            if values.get("exception_type") not in ("SHIFT", "OFF_SHIFT"):
                raise ValueError("Некорректный тип исключения")
            if not (values.get("comment") or "").strip():
                raise ValueError("Укажите комментарий к исключению")
    elif values.get("work_date") is None or values.get("value") not in ("FULL", "HALF", "TRAVEL", "OFF_SHIFT", "DOWNTIME", "DISMISSED", "EMPTY"):
        raise ValueError("Укажите дату и допустимое ручное значение дня")


def get_history(kind, employee_id, date_from=None, date_to=None):
    table, order, _ = _KINDS[kind]
    if date_from and date_to and date_to < date_from:
        raise ValueError("Дата окончания фильтра не может быть раньше даты начала")
    clauses, params = [sql.SQL("employee_id=%s")], [employee_id]
    if kind == "movements":
        if date_from:
            clauses.append(sql.SQL("event_datetime >= %s")); params.append(datetime.combine(date_from, time.min))
        if date_to:
            # Inclusive whole local day; no timezone conversion or max-date overflow.
            clauses.append(sql.SQL("event_datetime <= %s")); params.append(datetime.combine(date_to, time.max))
    elif kind == "day-overrides":
        if date_from:
            clauses.append(sql.SQL("work_date >= %s")); params.append(date_from)
        if date_to:
            clauses.append(sql.SQL("work_date <= %s")); params.append(date_to)
    else:
        # Intersecting periods, including an open illness beginning before the filter.
        if date_from:
            clauses.append(sql.SQL("(date_to IS NULL OR date_to >= %s)")); params.append(date_from)
        if date_to:
            clauses.append(sql.SQL("date_from <= %s")); params.append(date_to)
    with get_connection() as conn, conn.cursor(row_factory=dict_row) as cursor:
        _employee(cursor, employee_id)
        cursor.execute(sql.SQL("SELECT * FROM {} WHERE {} ORDER BY {},id").format(
            sql.Identifier(table), sql.SQL(" AND ").join(clauses), sql.Identifier(order)), params)
        records = cursor.fetchall()
        if kind == "movements":
            # Read-only provenance for the employee card; never infer confirmation
            # from transport_type or a source filename.
            cursor.execute("SELECT to_regclass('rail_tickets') AS relation")
            if cursor.fetchone()['relation']:
                cursor.execute("""SELECT movement_id, id FROM rail_tickets
                    WHERE employee_id=%s AND status='CONFIRMED' AND movement_id IS NOT NULL
                    ORDER BY id""", (employee_id,))
                tickets = {row['movement_id']: row['id'] for row in cursor.fetchall()}
                for record in records:
                    record['confirmed_ticket_id'] = tickets.get(record['id'])
        return records


def create_history(kind, employee_id, **values):
    table, _, columns = _KINDS[kind]
    _validate(kind, values)
    with get_connection() as conn, conn.cursor(row_factory=dict_row) as cursor:
        _employee(cursor, employee_id)
        names = ("employee_id",) + columns
        conflict = sql.SQL("")
        if kind == "day-overrides":
            conflict = sql.SQL(" ON CONFLICT (employee_id,work_date) DO UPDATE SET value=EXCLUDED.value,comment=EXCLUDED.comment,updated_at=CURRENT_TIMESTAMP")
        cursor.execute(sql.SQL("INSERT INTO {} ({}) VALUES ({}){} RETURNING *").format(
            sql.Identifier(table), sql.SQL(",").join(map(sql.Identifier, names)),
            sql.SQL(",").join(sql.Placeholder() for _ in names), conflict),
            (employee_id,) + tuple(values.get(c) for c in columns))
        return cursor.fetchone()


def _protect_ticket_movement(cursor, kind, employee_id, item_id):
    if kind != "movements":return
    # Older isolated migration fixtures do not yet have the ticket table.
    cursor.execute("SELECT to_regclass('rail_tickets') AS tickets")
    if cursor.fetchone()["tickets"] is None:return
    cursor.execute("SELECT id FROM rail_tickets WHERE employee_id=%s AND movement_id=%s",(employee_id,item_id))
    if cursor.fetchone():
        raise DirectoryConflict("Событие создано подтверждённым билетом. Его нельзя изменить или удалить отдельно от источника.")


def update_history(kind, employee_id, item_id, **changes):
    table, _, columns = _KINDS[kind]
    if not changes or not set(changes) <= set(columns):
        raise ValueError("Укажите изменяемые поля записи")
    with get_connection() as conn, conn.cursor(row_factory=dict_row) as cursor:
        _employee(cursor, employee_id)
        cursor.execute(sql.SQL("SELECT * FROM {} WHERE employee_id=%s AND id=%s FOR UPDATE").format(sql.Identifier(table)), (employee_id, item_id))
        previous = cursor.fetchone()
        if previous is None:
            raise DirectoryNotFound("Запись истории не найдена")
        _protect_ticket_movement(cursor, kind, employee_id, item_id)
        merged = {**previous, **changes}
        _validate(kind, merged)
        cursor.execute(sql.SQL("UPDATE {} SET {},updated_at=CURRENT_TIMESTAMP WHERE employee_id=%s AND id=%s RETURNING *").format(
            sql.Identifier(table), sql.SQL(",").join(sql.SQL("{}=%s").format(sql.Identifier(c)) for c in columns)),
            tuple(merged.get(c) for c in columns) + (employee_id, item_id))
        return cursor.fetchone()


def delete_ticket_movement(employee_id, item_id):
    try:
        with get_connection() as conn, conn.transaction(), conn.cursor(row_factory=dict_row) as cursor:
            _employee(cursor, employee_id)
            # Same lock order as ticket confirmation: ticket before movement.
            cursor.execute('SELECT id,employee_id,status FROM rail_tickets WHERE movement_id=%s FOR UPDATE',(item_id,))
            ticket=cursor.fetchone()
            cursor.execute('SELECT id,transport_type FROM employee_movements WHERE id=%s AND employee_id=%s FOR UPDATE',(item_id,employee_id))
            movement=cursor.fetchone()
            if movement is None:raise DirectoryNotFound('Запись истории не найдена')
            if movement['transport_type']!='RAIL':raise DirectoryConflict('Совместное удаление доступно только для ЖД-события')
            if not ticket or ticket['employee_id']!=employee_id or ticket['status']!='CONFIRMED':
                raise DirectoryConflict('Источник ЖД-события не найден или связь некорректна. Удаление не выполнено.')
            # The FK points from ticket to movement. Delete just this record, never a file/hash group.
            cursor.execute('DELETE FROM rail_tickets WHERE id=%s',(ticket['id'],))
            cursor.execute('DELETE FROM employee_movements WHERE id=%s AND employee_id=%s',(item_id,employee_id))
            return {'id':item_id,'ticket_id':ticket['id'],'deleted':True}
    except (ForeignKeyViolation, RestrictViolation) as error:
        raise DirectoryConflict('Удаление не выполнено: с ЖД-событием или билетом связаны другие данные. Билет и событие сохранены.') from error


def delete_history(kind, employee_id, item_id, *, delete_ticket=False):
    if kind=='movements' and delete_ticket:return delete_ticket_movement(employee_id,item_id)
    table = _KINDS[kind][0]
    with get_connection() as conn, conn.cursor(row_factory=dict_row) as cursor:
        _employee(cursor, employee_id)
        _protect_ticket_movement(cursor, kind, employee_id, item_id)
        cursor.execute(sql.SQL("DELETE FROM {} WHERE employee_id=%s AND id=%s RETURNING id").format(sql.Identifier(table)), (employee_id, item_id))
        if cursor.fetchone() is None:
            raise DirectoryNotFound("Запись истории не найдена")
        return {"id": item_id, "deleted": True}
