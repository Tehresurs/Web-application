"""Day-wide non-production event. Never edits source facts, plans or LUVR."""
import os
from datetime import date
from psycopg.rows import dict_row
from app.database.db import get_connection
from app.repositories.directory_errors import DirectoryConflict
from app.repositories.luvr_calendar import CALENDAR_SELECT, decode_calendar_inputs
from app.services.luvr_calendar import calculate_employee_day

POSITION = 'Инженер ПИЛ (НК, УЗК)'
COMMENT = 'Проведен ДК'
LOCK = (20261017, 29)

def role():
    from app.access_context import read_only_request
    if read_only_request.get():return 'READ_ONLY'
    # Single-user installation: role comes from server config, never request data.
    return os.environ.get('TEHRESURS_USER_ROLE', 'LEADER').strip().upper()

def capabilities():
    return dict(role=role(), can_manage_dk=role()=='LEADER', single_user=True)

def require_leader():
    if role()!='LEADER':
        raise PermissionError('Назначать и отменять ДК может только руководитель')

def installed(conn):
    return conn.execute("SELECT to_regclass('production_matrix_dk')").fetchone()[0] is not None

def eligible(conn, employee_id, target):
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(CALENDAR_SELECT+' WHERE e.id=%s',(employee_id,))
        row=cur.fetchone()
        if not row:return False
        if row['position_name']!=POSITION or row['is_archived']:return False
        day=calculate_employee_day(decode_calendar_inputs(row),target)
        if day['final_code'] not in ('FULL','HALF'):return False
        cur.execute("""SELECT 1 FROM employee_absences WHERE employee_id=%s
            AND date_from<=%s AND (date_to IS NULL OR date_to>=%s) LIMIT 1""",(employee_id,target,target))
        return cur.fetchone() is None

def reconcile(conn):
    """Run inside the source-change transaction, before commit."""
    if not installed(conn):return
    conn.execute('SELECT pg_advisory_xact_lock(%s,%s)',LOCK)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute('SELECT employee_id,work_date FROM production_matrix_dk ORDER BY employee_id,work_date FOR UPDATE')
        events=cur.fetchall()
    for event in events:
        if not eligible(conn,event['employee_id'],event['work_date']):
            conn.execute('DELETE FROM production_matrix_dk WHERE employee_id=%s AND work_date=%s',
                         (event['employee_id'],event['work_date']))

def set_event(employee_id, target, enabled):
    require_leader()
    with get_connection() as conn:
        if not installed(conn):raise DirectoryConflict('Для ДК требуется миграция 029')
        conn.execute('SELECT pg_advisory_xact_lock(%s,%s)',LOCK)
        if enabled:
            if not eligible(conn,employee_id,target):
                raise DirectoryConflict('ДК доступен только для должности «'+POSITION+'» при ЛУВР 1 или 0,5, без отсутствия')
            # Assignment must belong to the same matrix membership visible in UI.
            if not conn.execute('SELECT 1 FROM luvr_month_employees WHERE employee_id=%s AND year=%s AND month=%s',
                                (employee_id,target.year,target.month)).fetchone():
                raise DirectoryConflict('Сотрудник не включён в ЛУВР выбранного месяца')
            conn.execute('INSERT INTO production_matrix_dk(employee_id,work_date) VALUES(%s,%s) ON CONFLICT DO NOTHING',
                         (employee_id,target))
        else:
            conn.execute('DELETE FROM production_matrix_dk WHERE employee_id=%s AND work_date=%s',(employee_id,target))
    return dict(employee_id=employee_id,date=target,is_dk=enabled,day_event='DK' if enabled else None,
                comment=COMMENT if enabled else None)

def projection_enabled(employee, day, available):
    return (day in employee.get('dk_dates',[]) and employee.get('position_name')==POSITION and available>0)
