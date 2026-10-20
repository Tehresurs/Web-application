import logging
from datetime import timedelta

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg.errors import ForeignKeyViolation, UniqueViolation

from app.database.db import get_connection
from app.repositories.directory_errors import DirectoryConflict, DirectoryNotFound
from app.services.rail_ticket_parser import normalize_passenger, luvr_route
from app.repositories.rail_production_assignments import sync as sync_production_assignment
from app.repositories import construction_identity as identity

log=logging.getLogger(__name__)


def _ticket(cursor, ticket_id, lock=False):
    if lock and identity.enabled(cursor.connection):
        # Keep the same order as production-assignment writes, before row locks.
        cursor.execute('SELECT pg_advisory_xact_lock(20261007,1601)')
        cursor.execute('SELECT pg_advisory_xact_lock(20261013,24)')
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
    identity.describe(cursor.connection,item)
    item['assignment_po_id']=None;item['assignment_category_id']=None
    cursor.execute("SELECT to_regclass('production_assignment_items') AS installed")
    if cursor.fetchone()['installed'] is not None:
        cursor.execute("""SELECT i.po_id,i.initial_category_id FROM production_assignment_items i
            JOIN production_assignment_changes c ON c.id=i.change_id WHERE c.source_ticket_id=%s
            AND ((%s::bigint IS NOT NULL AND i.entity_id=%s) OR
                 (%s::bigint IS NULL AND i.object_id=%s)) ORDER BY c.effective_from DESC,c.id DESC LIMIT 1""",
            (ticket['id'],ticket.get('entity_id'),ticket.get('entity_id'),ticket.get('entity_id'),ticket.get('object_id'))) if identity.enabled(cursor.connection) else cursor.execute(
            """SELECT i.po_id,i.initial_category_id FROM production_assignment_items i
            JOIN production_assignment_changes c ON c.id=i.change_id
            WHERE c.source_ticket_id=%s AND i.object_id=%s ORDER BY c.effective_from DESC,c.id DESC LIMIT 1""",
            (ticket['id'],ticket.get('object_id')))
        assignment=cursor.fetchone()
        if assignment:item.update(assignment_po_id=assignment['po_id'],assignment_category_id=assignment['initial_category_id'])
    item['full_name_raw']=ticket['full_name']
    item["duplicate"]=duplicate
    item["employee_name"]=None;item["employee_is_archived"]=False
    item["match_status"]="NOT_FOUND";item["match_ambiguous"]=False
    item["movement"]=None
    item["object_name"]=None;item["employee_state"]=None;item["employee_state_label"]=None;item["planned_date"]=None
    item["position_name"]=None
    if ticket.get("object_id"):
        cursor.execute("SELECT name FROM construction_objects WHERE id=%s",(ticket["object_id"],))
        obj=cursor.fetchone();item["object_name"]=obj["name"] if obj else None
    if item.get('current_hierarchy'):item['object_name']=item['current_hierarchy']['name']
    eligible,candidate=luvr_route(ticket["departure_station"],ticket["arrival_station"])
    item["direction_candidate"]=candidate
    item["is_luvr_route"]=eligible if ticket["status"]!="PARSE_ERROR" else None
    if ticket["status"]=="ANNULLED":
        item["processing_status"]="ANNULLED"
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
    elif ticket["status"] in ("PARSE_ERROR","REJECTED","ANNULLED"):
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
    employee_id=item.get("employee_id")
    trip_dt=(ticket.get("arrival_datetime") if item.get("movement_type")=="ARRIVAL" else ticket.get("departure_datetime"))
    if employee_id:
        cursor.execute("""SELECT e.dismissal_date,e.is_archived,e.max_shift_days,e.max_off_shift_days,p.name AS position_name
                        FROM employees e LEFT JOIN positions p ON p.id=e.position_id WHERE e.id=%s""",(employee_id,))
        emp=cursor.fetchone()
        if emp:item["position_name"]=emp["position_name"]
        trip_date=trip_dt.date() if trip_dt else None
        if emp and (emp["is_archived"] or (emp["dismissal_date"] and trip_date and emp["dismissal_date"]<=trip_date)):
            item.update(employee_state="DISMISSED",employee_state_label="Уволен")
        else:
            absence=None
            if trip_date:
                cursor.execute("SELECT to_regclass('employee_absences') AS absences, to_regclass('employee_sick_absence_labels') AS labels")
                tables=cursor.fetchone()
                if tables["absences"]:
                    cursor.execute("SELECT reason FROM employee_absences WHERE employee_id=%s AND %s BETWEEN date_from AND date_to ORDER BY date_from DESC LIMIT 1",(employee_id,trip_date))
                    absence=cursor.fetchone()
                if not absence:
                    if tables["labels"]:
                        cursor.execute("SELECT COALESCE(l.reason,'Больничный') AS reason FROM employee_sick_periods s LEFT JOIN employee_sick_absence_labels l ON l.sick_period_id=s.id WHERE s.employee_id=%s AND %s BETWEEN s.date_from AND s.date_to ORDER BY s.date_from DESC LIMIT 1",(employee_id,trip_date))
                    else:
                        cursor.execute("SELECT 'Больничный' AS reason FROM employee_sick_periods s WHERE s.employee_id=%s AND %s BETWEEN s.date_from AND s.date_to ORDER BY s.date_from DESC LIMIT 1",(employee_id,trip_date))
                    absence=cursor.fetchone()
            if absence:item.update(employee_state="ABSENT",employee_state_label=absence["reason"] or "Отсутствует")
            else:item.update(employee_state="ACTIVE",employee_state_label="Действующий")
        if emp and trip_dt:
            days=emp["max_shift_days"] if item.get("movement_type")=="ARRIVAL" else emp["max_off_shift_days"]
            if days is not None:item["planned_date"]=trip_dt+timedelta(days=days)
    elif ticket.get("full_name"):
        item.update(employee_state="NEW",employee_state_label="Новый")
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

def list_tickets():
    """Return saved tickets newest first for the management screen."""
    with get_connection() as conn, conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute("SELECT * FROM rail_tickets ORDER BY COALESCE(arrival_datetime,departure_datetime,created_at) DESC, id DESC")
        return [_view(cursor,row) for row in cursor.fetchall()]



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
        if ticket["status"] in ("CONFIRMED","ANNULLED"):raise DirectoryConflict("Подтверждённый или аннулированный билет нельзя отклонить")
        cursor.execute("UPDATE rail_tickets SET status='REJECTED',updated_at=CURRENT_TIMESTAMP WHERE id=%s RETURNING *",(ticket_id,))
        return _view(cursor,cursor.fetchone())


def _guard_confirmed_trip(cursor,ticket,employee_id):
    cursor.execute("""SELECT id,departure_station,arrival_station FROM rail_tickets
        WHERE employee_id=%s AND status='CONFIRMED' AND id<>%s
          AND departure_datetime=%s AND arrival_datetime=%s FOR SHARE""",
        (employee_id,ticket['id'],ticket['departure_datetime'],ticket['arrival_datetime']))
    station=lambda value:' '.join((value or '').split()).casefold()
    for other in cursor.fetchall():
        if (station(other['departure_station'])==station(ticket['departure_station'])
                and station(other['arrival_station'])==station(ticket['arrival_station'])):
            raise DirectoryConflict(f"Эта поездка уже подтверждена билетом №{other['id']}. Повторное перемещение не создано.")


def confirm_ticket(ticket_id, employee_id=None):
    with get_connection() as conn, conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute('SELECT pg_advisory_xact_lock(20261007,1601)')
        ticket=_ticket(cursor,ticket_id,lock=True)
        if ticket["status"]=="CONFIRMED":
            sync_production_assignment(conn,ticket)
            return _view(cursor,ticket,duplicate=True)
        if ticket["status"]!="PARSED":raise DirectoryConflict("Билет не готов к подтверждению")
        if ticket["parse_errors"] or not all(ticket[key] for key in ("full_name","departure_station","departure_datetime","arrival_station","arrival_datetime")):
            raise DirectoryConflict("В билете не хватает обязательных данных. Требуется проверка.")
        eligible,direction=luvr_route(ticket["departure_station"],ticket["arrival_station"])
        if not eligible:raise DirectoryConflict("Не относится к ЛУВР — маршрут без станции Салым")
        if direction is None:raise DirectoryConflict("Маршрут противоречивый. Требуется проверка исходного билета.")
        employee,ambiguous=_employee(cursor,ticket["full_name"],lock=True)
        if employee_id is not None:
            if employee and employee['id']!=employee_id:
                raise DirectoryConflict('ФИО точно соответствует другому сотруднику. Обновите билет и проверьте выбор.')
            cursor.execute('SELECT id,full_name,is_archived FROM employees WHERE id=%s FOR SHARE',(employee_id,))
            employee=cursor.fetchone()
            if employee is None:raise DirectoryNotFound('Выбранный сотрудник не найден')
        if employee is None:raise DirectoryConflict("Найдено несколько сотрудников с одинаковым ФИО" if ambiguous else "Сотрудник не найден")
        if employee["is_archived"]:raise DirectoryConflict("Сотрудник находится в архиве. Решение о восстановлении принимается отдельно в карточке сотрудника.")
        _guard_confirmed_trip(cursor,ticket,employee['id'])
        event=ticket["arrival_datetime"] if direction=="ARRIVAL" else ticket["departure_datetime"]
        cursor.execute("""SELECT m.* FROM employee_movements m WHERE m.employee_id=%s
            AND m.movement_type=%s AND m.transport_type='RAIL' AND m.event_datetime=%s
            ORDER BY m.id FOR UPDATE""",(employee['id'],direction,event))
        station=lambda value:' '.join((value or '').split()).casefold()
        matches=[m for m in cursor.fetchall() if station(m['departure_station'])==station(ticket['departure_station'])
                 and station(m['arrival_station'])==station(ticket['arrival_station'])]
        if len(matches)>1:
            raise DirectoryConflict('Найдено несколько одинаковых ЖД-перемещений: '+', '.join(str(m['id']) for m in matches)+'. Требуется проверить историю.')
        if matches:
            movement_id=matches[0]['id']
            cursor.execute("SELECT id FROM rail_tickets WHERE movement_id=%s AND status='CONFIRMED'",(movement_id,))
            used=cursor.fetchone()
            if used:raise DirectoryConflict(f"Перемещение уже связано с билетом №{used['id']}. Проверьте данные поездки.")
        else:
            cursor.execute("""INSERT INTO employee_movements(employee_id,movement_type,transport_type,event_datetime,departure_station,arrival_station,source_file)
                VALUES(%s,%s,'RAIL',%s,%s,%s,%s) RETURNING id""",
                (employee['id'],direction,event,ticket['departure_station'],ticket['arrival_station'],ticket['source_filename']))
            movement_id=cursor.fetchone()['id']
        cursor.execute("UPDATE rail_tickets SET status='CONFIRMED',employee_id=%s,movement_id=%s,movement_type=%s,updated_at=CURRENT_TIMESTAMP WHERE id=%s RETURNING *",(employee["id"],movement_id,direction,ticket_id))
        updated=cursor.fetchone()
        sync_production_assignment(conn,updated)
        view=_view(cursor,updated)
        log.info("RAIL_MOVEMENT_CONFIRMED ticket_id=%s movement_id=%s employee_id=%s",ticket_id,movement_id,employee["id"])
        return view


def set_ticket_object(ticket_id,object_id,entity_id=None,assignment_fields=None):
    from app.repositories.object_archive import require_assignable
    with get_connection() as conn, conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute('SELECT pg_advisory_xact_lock(20261007,1601)')
        identities=identity.enabled(conn)
        if identities:conn.execute('SELECT pg_advisory_xact_lock(20261013,24)')
        elif entity_id is not None:identity.prepare(conn,dict(entity_id=entity_id))
        ticket=_ticket(cursor,ticket_id,lock=True)
        if ticket['status']=='ANNULLED':raise DirectoryConflict('Сначала восстановите билет')
        if assignment_fields is not None:
            if ticket['status']!='CONFIRMED':raise DirectoryConflict('Сначала подтвердите сотрудника по билету, затем сохраните ПО и категорию')
            if not (object_id or entity_id) or not assignment_fields.get('po_id') or not assignment_fields.get('initial_category_id'):
                raise ValueError('Выберите объект, ПО и категорию вместе')
            for table,field in (('po_types','po_id'),('object_categories','initial_category_id')):
                cursor.execute(f'SELECT id FROM {table} WHERE id=%s',(assignment_fields[field],))
                if cursor.fetchone() is None:raise DirectoryNotFound('ПО или категория не найдены')
        view=_view(cursor,ticket)
        if view.get("movement_type")!="ARRIVAL":raise DirectoryConflict("Объект назначается только для заезда")
        if identities:
            item=dict(object_id=object_id,entity_id=entity_id)
            if object_id is not None or entity_id is not None:
                unchanged=(ticket.get('object_id') is not None or ticket.get('entity_id') is not None) and identity.reference(conn,ticket)['entity_id']==identity.reference(conn,item)['entity_id']
                identity.prepare(conn,item,assignable=not unchanged)
                if unchanged:item={k:ticket.get(k) for k in ('object_id','entity_id')}
            cursor.execute('UPDATE rail_tickets SET object_id=%s,entity_id=%s,updated_at=CURRENT_TIMESTAMP WHERE id=%s RETURNING *',(item['object_id'],item['entity_id'],ticket_id))
            updated=cursor.fetchone()
            sync_production_assignment(conn,updated,previous_object_id=ticket.get('object_id'),previous_entity_id=ticket.get('entity_id'),assignment_fields=assignment_fields)
            return _view(cursor,updated)
        if object_id is not None:
            if object_id != ticket.get('object_id'):
                require_assignable(cursor,object_id)
            cursor.execute("SELECT id FROM construction_objects WHERE id=%s",(object_id,))
            if cursor.fetchone() is None:raise DirectoryNotFound("Объект не найден")
        cursor.execute("UPDATE rail_tickets SET object_id=%s,updated_at=CURRENT_TIMESTAMP WHERE id=%s RETURNING *",(object_id,ticket_id))
        updated=cursor.fetchone()
        sync_production_assignment(conn,updated,previous_object_id=ticket.get('object_id'),assignment_fields=assignment_fields)
        return _view(cursor,updated)


def annul_ticket(ticket_id):
    with get_connection() as conn, conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute('SELECT pg_advisory_xact_lock(20261007,1601)')
        ticket=_ticket(cursor,ticket_id,lock=True)
        if ticket["status"]=="ANNULLED":return _view(cursor,ticket)
        movement_id=ticket.get("movement_id")
        if movement_id:
            cursor.execute('SELECT id FROM employee_movements WHERE id=%s FOR UPDATE',(movement_id,))
            if cursor.fetchone() is None:raise DirectoryConflict('Связанное перемещение не найдено')
        cursor.execute("""UPDATE rail_tickets SET
            annul_snapshot=jsonb_build_object('status',status,'movement',
                (SELECT to_jsonb(m) FROM employee_movements m WHERE m.id=movement_id)),
            status='ANNULLED',movement_id=NULL,updated_at=CURRENT_TIMESTAMP
            WHERE id=%s RETURNING *""",(ticket_id,))
        updated=cursor.fetchone()
        if movement_id:
            # Do not remove an employee movement if another active confirmed ticket
            # still uses the same movement as its basis.
            cursor.execute("SELECT 1 FROM rail_tickets WHERE movement_id=%s AND id<>%s AND status='CONFIRMED' LIMIT 1",(movement_id,ticket_id))
            if cursor.fetchone() is None:
                cursor.execute("DELETE FROM employee_movements WHERE id=%s",(movement_id,))
        return _view(cursor,updated)


def restore_ticket(ticket_id):
    try:
        with get_connection() as conn, conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(20261007,1601)')
            ticket=_ticket(cursor,ticket_id,lock=True)
            if ticket['status']!='ANNULLED':return _view(cursor,ticket)
            snapshot=ticket.get('annul_snapshot')
            if not snapshot or snapshot.get('status') not in ('CONFIRMED','PARSED','PARSE_ERROR','REJECTED'):
                raise DirectoryConflict('Прежнее состояние билета не сохранено. Автоматическое восстановление невозможно; требуется проверка истории.')
            movement_id=None
            if snapshot['status']=='CONFIRMED':
                _guard_confirmed_trip(cursor,ticket,ticket['employee_id'])
                movement=snapshot.get('movement')
                if not movement or movement.get('employee_id')!=ticket['employee_id'] or movement.get('transport_type')!='RAIL' or movement.get('movement_type')!=ticket['movement_type']:
                    raise DirectoryConflict('Снимок подтверждённого перемещения отсутствует или противоречив')
                movement_id=movement['id']
                cursor.execute('SELECT to_jsonb(m) AS data FROM employee_movements m WHERE id=%s FOR UPDATE',(movement_id,))
                existing=cursor.fetchone()
                if existing and existing['data']!=movement:
                    raise DirectoryConflict('Перемещение с этим идентификатором изменено. Требуется проверка истории.')
                if not existing:
                    cursor.execute('''INSERT INTO employee_movements
                        (id,employee_id,movement_type,transport_type,event_datetime,departure_station,arrival_station,source_file,created_at,updated_at)
                        SELECT id,employee_id,movement_type,transport_type,event_datetime,departure_station,arrival_station,source_file,created_at,updated_at
                        FROM jsonb_populate_record(NULL::employee_movements,%s)''',(Jsonb(movement),))
            cursor.execute('''UPDATE rail_tickets SET status=%s,movement_id=%s,updated_at=CURRENT_TIMESTAMP
                WHERE id=%s RETURNING *''',(snapshot['status'],movement_id,ticket_id))
            updated=cursor.fetchone()
            sync_production_assignment(conn,updated)
            return _view(cursor,updated)
    except (ForeignKeyViolation,UniqueViolation) as error:
        raise DirectoryConflict('Не удалось восстановить связь с перемещением. Данные не изменены; требуется проверка истории.') from error
