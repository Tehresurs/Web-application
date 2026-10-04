import logging

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.database.db import get_connection
from app.repositories.directory_errors import DirectoryConflict, DirectoryNotFound
from app.services.rail_ticket_parser import normalize_passenger, luvr_route

log=logging.getLogger(__name__)


def _ticket(cursor, ticket_id, lock=False):
    cursor.execute("SELECT * FROM rail_tickets WHERE id=%s"+(" FOR UPDATE" if lock else ""),(ticket_id,))
    ticket=cursor.fetchone()
    if ticket is None:raise DirectoryNotFound("Билет не найден")
    return ticket


def _employee(cursor, full_name, lock=False):
    # Deliberately independent of daily-report matching, aliases and SQL normalization.
    cursor.execute("SELECT id,full_name,is_archived FROM employees ORDER BY id")
    matches=[row for row in cursor.fetchall() if normalize_passenger(row["full_name"])==normalize_passenger(full_name)]
    if len(matches)!=1:return None,len(matches)>1
    row=matches[0]
    if lock:
        # FOR SHARE blocks archival/name changes until confirmation commits.
        cursor.execute("SELECT id,full_name,is_archived FROM employees WHERE id=%s FOR SHARE",(row["id"],))
        row=cursor.fetchone()
        if row is None or normalize_passenger(row["full_name"])!=normalize_passenger(full_name):return None,False
    return row,False


def _view(cursor,ticket,duplicate=False):
    item=dict(ticket)
    item['full_name_raw']=ticket['full_name']
    item["duplicate"]=duplicate
    item["employee_name"]=None;item["employee_is_archived"]=False
    item["match_status"]="NOT_FOUND";item["match_ambiguous"]=False
    item["movement"]=None
    eligible,candidate=luvr_route(ticket["departure_station"],ticket["arrival_station"])
    item["direction_candidate"]=candidate
    item["is_luvr_route"]=eligible if ticket["status"]!="PARSE_ERROR" else None
    if ticket["status"]=="PARSED":
        item["movement_type"]=candidate
        if ticket["parse_errors"] or not all(ticket[key] for key in ("full_name","departure_station","departure_datetime","arrival_station","arrival_datetime")) or (eligible and candidate is None):
            item.update(processing_status="PARSE_ERROR",employee_id=None,movement_type=None,
                        parse_errors=ticket["parse_errors"] or ["Маршрут неполный или противоречивый. Проверьте исходный билет."])
            return item
    if ticket["status"]=="PARSED" and not eligible:
        item.update(processing_status="NOT_LUVR_ROUTE",employee_id=None,movement_type=None)
        return item
    if ticket["status"]=="CONFIRMED":
        cursor.execute("SELECT id,employee_id,movement_type,transport_type,event_datetime,departure_station,arrival_station,source_file FROM employee_movements WHERE id=%s",(ticket["movement_id"],))
        item["movement"]=cursor.fetchone()
        cursor.execute("SELECT full_name,is_archived FROM employees WHERE id=%s",(ticket["employee_id"],))
        employee=cursor.fetchone()
        item.update(employee_name=employee["full_name"],employee_is_archived=employee["is_archived"],match_status="FOUND",processing_status="DUPLICATE" if duplicate else "CONFIRMED")
    elif ticket["status"] in ("PARSE_ERROR","REJECTED"):
        item["processing_status"]=ticket["status"]
    else:
        employee,ambiguous=_employee(cursor,ticket["full_name"])
        item["employee_id"]=employee["id"] if employee else None
        item["employee_name"]=employee["full_name"] if employee else None
        item["match_status"]="FOUND" if employee else "NOT_FOUND"
        item["match_ambiguous"]=ambiguous
        item["employee_is_archived"]=bool(employee and employee["is_archived"])
        item["processing_status"]=("EMPLOYEE_NOT_FOUND" if not employee else "ARCHIVED_EMPLOYEE" if employee["is_archived"] else "READY")
        log.info("RAIL_%s ticket_id=%s", "EMPLOYEE_NOT_FOUND" if not employee else "ARCHIVED_EMPLOYEE" if employee["is_archived"] else "EMPLOYEE_FOUND",ticket["id"])
    return item


def store_parsed_ticket(file_hash, parsed):
    with get_connection() as conn, conn.cursor(row_factory=dict_row) as cursor:
        direction=luvr_route(parsed.departure_station,parsed.arrival_station)[1] if parsed.parse_status=="PARSED" else None
        cursor.execute("""INSERT INTO rail_tickets(file_hash,source_filename,full_name,departure_station,departure_datetime,arrival_station,arrival_datetime,status,parse_errors,movement_type)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(file_hash) DO NOTHING RETURNING id""",
            (file_hash,parsed.source_filename,parsed.full_name,parsed.departure_station,parsed.departure_datetime,parsed.arrival_station,parsed.arrival_datetime,parsed.parse_status,Jsonb(parsed.parse_errors),direction))
        inserted=cursor.fetchone()
        if inserted and parsed.source_page is not None:
            cursor.execute("UPDATE rail_tickets SET source_page=%s,source_sha256=%s WHERE id=%s",(parsed.source_page,parsed.source_sha256,inserted['id']))
        cursor.execute("SELECT * FROM rail_tickets WHERE file_hash=%s",(file_hash,))
        ticket=cursor.fetchone()
        view=_view(cursor,ticket,duplicate=inserted is None)
        log.info("RAIL_%s ticket_id=%s", "DUPLICATE" if inserted is None else view["processing_status"], ticket["id"])
        return view


def get_ticket(ticket_id):
    with get_connection() as conn, conn.cursor(row_factory=dict_row) as cursor:
        return _view(cursor,_ticket(cursor,ticket_id))


def choose_direction(ticket_id,movement_type):
    if movement_type not in ("ARRIVAL","DEPARTURE"):raise ValueError("Выберите заезд или выезд")
    with get_connection() as conn, conn.cursor(row_factory=dict_row) as cursor:
        ticket=_ticket(cursor,ticket_id,lock=True)
        if ticket["status"]!="PARSED":raise DirectoryConflict("Направление можно выбрать только для неподтверждённого разобранного билета")
        if not luvr_route(ticket["departure_station"],ticket["arrival_station"])[0]:
            raise DirectoryConflict("Не относится к ЛУВР — маршрут без станции Салым")
        # Compatibility only: the old endpoint cannot override route-derived facts.
        view=_view(cursor,ticket)
        if view["processing_status"]=="PARSE_ERROR" or movement_type!=view["movement_type"]:
            raise DirectoryConflict("Направление определяется автоматически по станции Салым; ручное изменение недоступно")
        return view


def reject_ticket(ticket_id):
    with get_connection() as conn, conn.cursor(row_factory=dict_row) as cursor:
        ticket=_ticket(cursor,ticket_id,lock=True)
        if ticket["status"]=="CONFIRMED":raise DirectoryConflict("Билет уже подтверждён")
        cursor.execute("UPDATE rail_tickets SET status='REJECTED',updated_at=CURRENT_TIMESTAMP WHERE id=%s RETURNING *",(ticket_id,))
        return _view(cursor,cursor.fetchone())


def confirm_ticket(ticket_id):
    with get_connection() as conn, conn.cursor(row_factory=dict_row) as cursor:
        ticket=_ticket(cursor,ticket_id,lock=True)
        if ticket["status"]=="CONFIRMED":return _view(cursor,ticket,duplicate=True)
        if ticket["status"]!="PARSED":raise DirectoryConflict("Билет не готов к подтверждению")
        if ticket["parse_errors"] or not all(ticket[key] for key in ("full_name","departure_station","departure_datetime","arrival_station","arrival_datetime")):
            raise DirectoryConflict("В билете не хватает обязательных данных. Требуется проверка.")
        eligible,direction=luvr_route(ticket["departure_station"],ticket["arrival_station"])
        if not eligible:raise DirectoryConflict("Не относится к ЛУВР — маршрут без станции Салым")
        if direction is None:raise DirectoryConflict("Маршрут противоречивый. Требуется проверка исходного билета.")
        employee,ambiguous=_employee(cursor,ticket["full_name"],lock=True)
        if employee is None:raise DirectoryConflict("Найдено несколько сотрудников с одинаковым ФИО" if ambiguous else "Сотрудник не найден")
        if employee["is_archived"]:raise DirectoryConflict("Сотрудник находится в архиве. Решение о восстановлении принимается отдельно в карточке сотрудника.")
        event=ticket["arrival_datetime"] if direction=="ARRIVAL" else ticket["departure_datetime"]
        cursor.execute("""INSERT INTO employee_movements(employee_id,movement_type,transport_type,event_datetime,departure_station,arrival_station,source_file)
            VALUES(%s,%s,'RAIL',%s,%s,%s,%s) RETURNING id""",
            (employee["id"],direction,event,ticket["departure_station"],ticket["arrival_station"],ticket["source_filename"]))
        movement_id=cursor.fetchone()["id"]
        cursor.execute("UPDATE rail_tickets SET status='CONFIRMED',employee_id=%s,movement_id=%s,movement_type=%s,updated_at=CURRENT_TIMESTAMP WHERE id=%s RETURNING *",(employee["id"],movement_id,direction,ticket_id))
        view=_view(cursor,cursor.fetchone())
        log.info("RAIL_MOVEMENT_CONFIRMED ticket_id=%s movement_id=%s employee_id=%s",ticket_id,movement_id,employee["id"])
        return view
