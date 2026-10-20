"""One SELECT gives a consistent PostgreSQL snapshot; no writes or row locks."""
from datetime import date, datetime
from psycopg.rows import dict_row
from app.database.db import get_connection
from app.repositories.directory_errors import DirectoryNotFound


CALENDAR_SELECT = """
            SELECT e.id AS employee_id,e.full_name,e.dismissal_date,e.is_archived,
                   p.work_location,p.work_schedule,p.name AS position_name,p.specialty,e.nrs_number,
                   e.max_shift_days,e.max_off_shift_days,
                COALESCE((SELECT jsonb_agg(to_jsonb(h) ORDER BY h.event_datetime,h.id)
                    FROM (SELECT m.*,t.id AS ticket_id,t.departure_datetime AS ticket_departure,
                            t.arrival_datetime AS ticket_arrival,t.departure_station AS ticket_origin,
                            t.arrival_station AS ticket_destination,t.source_page
                          FROM employee_movements m LEFT JOIN rail_tickets t
                            ON t.movement_id=m.id AND t.employee_id=m.employee_id AND t.status='CONFIRMED'
                          WHERE m.employee_id=e.id) h),'[]'::jsonb) AS movements,
                COALESCE((SELECT jsonb_agg(to_jsonb(s) ORDER BY s.date_from,s.id)
                    FROM employee_sick_periods s WHERE s.employee_id=e.id),'[]'::jsonb) AS sick_periods,
                COALESCE((SELECT jsonb_agg(to_jsonb(x) ORDER BY x.date_from,x.id)
                    FROM employee_duration_exceptions x WHERE x.employee_id=e.id),'[]'::jsonb) AS duration_exceptions,
                COALESCE((SELECT jsonb_agg(to_jsonb(o) ORDER BY o.work_date,o.id)
                    FROM employee_luvr_day_overrides o WHERE o.employee_id=e.id),'[]'::jsonb) AS overrides
            FROM employees e LEFT JOIN positions p ON p.id=e.position_id
        """


def decode_calendar_inputs(result):
    for movement in result['movements']:
        for key in ('event_datetime','ticket_departure','ticket_arrival'):
            if movement.get(key):movement[key]=datetime.fromisoformat(movement[key])
    for item in result['sick_periods']+result['duration_exceptions']:
        for key in ('date_from','date_to'):
            if item.get(key):item[key]=date.fromisoformat(item[key])
    for item in result['overrides']:item['work_date']=date.fromisoformat(item['work_date'])
    return result


def get_calendar_inputs(employee_id):
    with get_connection() as conn, conn.cursor(row_factory=dict_row) as cursor:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        cursor.execute(CALENDAR_SELECT+" WHERE e.id=%s",(employee_id,))
        result=cursor.fetchone()
        if result is None: raise DirectoryNotFound('Сотрудник не найден')
        from app.repositories.personnel_transfers import attach_context
        attach_context(conn,[result])
        return decode_calendar_inputs(result)
