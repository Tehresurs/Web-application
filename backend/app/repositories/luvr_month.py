from datetime import date
from psycopg.rows import dict_row
from app.database.db import get_connection
from app.repositories.directory_errors import DirectoryConflict, DirectoryNotFound
from app.repositories.luvr_calendar import CALENDAR_SELECT, decode_calendar_inputs


def get_month_inputs(year, month):
    # Header and facts belong to the same statement snapshot, even during edits.
    with get_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        cur.execute('''SELECT EXISTS(SELECT 1 FROM luvr_months WHERE year=%s AND month=%s) AS formed,
            COALESCE((SELECT jsonb_agg(to_jsonb(facts)) FROM ('''+CALENDAR_SELECT+'''
            JOIN luvr_month_employees member ON member.employee_id=e.id
            WHERE member.year=%s AND member.month=%s) facts),'[]'::jsonb) AS employees''',
            (year,month,year,month))
        result=cur.fetchone()
        from app.repositories.personnel_transfers import attach_context
        attach_context(conn,result['employees'])
    for employee in result['employees']:
        if employee['dismissal_date']: employee['dismissal_date']=date.fromisoformat(employee['dismissal_date'])
        decode_calendar_inputs(employee)
    result['employees'].sort(key=lambda e:(' '.join(e['full_name'].split()).casefold().replace('ё','е'),e['employee_id']))
    return result


def form_month(year, month):
    with get_connection() as conn, conn.transaction():
        if not conn.execute('SELECT 1 FROM luvr_months WHERE year=%s AND month=%s',(year,month)).fetchone():
            settings=conn.execute('SELECT agreed_name FROM luvr_settings WHERE id=1').fetchone()
            if not settings or not settings[0] or not settings[0].strip():
                raise ValueError('Перед формированием нового месяца укажите ФИО согласующего в настройках ЛУВР.')
        created=conn.execute('''INSERT INTO luvr_months(year,month,approver_position_snapshot,approver_name_snapshot,document_title_snapshot,
            developer_position_snapshot,developer_name_snapshot,agreed_position_snapshot,agreed_name_snapshot,legend_snapshot)
            SELECT %s,%s,approver_position,approver_name,document_title,developer_position,developer_name,agreed_position,agreed_name,legend FROM luvr_settings WHERE id=1
            ON CONFLICT DO NOTHING RETURNING year''', (year,month)).fetchone()
        if created:
            conn.execute('''INSERT INTO luvr_month_employees(year,month,employee_id)
                SELECT %s,%s,id FROM employees
                WHERE dismissal_date>=%s
                   OR (dismissal_date IS NULL AND NOT is_archived)''',(year,month,date(year,month,1)))
    return {'formed':True}


def get_settings():
    with get_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute('SELECT approver_position,approver_name,document_title,developer_position,developer_name,agreed_position,agreed_name,legend FROM luvr_settings WHERE id=1')
        return cur.fetchone()


def update_settings(approver_position, approver_name, document_title,developer_position,developer_name,agreed_position,agreed_name,legend):
    values=[value.strip() for value in (approver_position,approver_name,document_title,developer_position,developer_name,agreed_position,agreed_name,legend)]
    if not all(values):raise ValueError('Заполните все реквизиты документа, подписи и легенду.')
    lines=values[-1].splitlines()
    if len(lines)!=6 or not all(line.strip() for line in lines):raise ValueError('Легенда должна содержать ровно 6 непустых строк по области MASTER.')
    with get_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute('''UPDATE luvr_settings SET approver_position=%s,approver_name=%s,document_title=%s,
            developer_position=%s,developer_name=%s,agreed_position=%s,agreed_name=%s,legend=%s
            WHERE id=1 RETURNING approver_position,approver_name,document_title,developer_position,developer_name,agreed_position,agreed_name,legend''',values)
        return cur.fetchone()


def get_header_snapshot(year, month):
    with get_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute('''SELECT year,month,approver_position_snapshot,approver_name_snapshot,document_title_snapshot,
            developer_position_snapshot,developer_name_snapshot,agreed_position_snapshot,agreed_name_snapshot,legend_snapshot
            FROM luvr_months WHERE year=%s AND month=%s''',(year,month))
        result=cur.fetchone()
    if not result:raise ValueError('Сначала сформируйте ЛУВР за выбранный месяц.')
    if any(result[k] is None for k in ('approver_position_snapshot','approver_name_snapshot','document_title_snapshot')):
        raise ValueError('У месяца отсутствует snapshot верхней части документа.')
    return result


def change_member(year, month, employee_id, remove=False):
    with get_connection() as conn, conn.transaction():
        if not conn.execute('SELECT year FROM luvr_months WHERE year=%s AND month=%s FOR UPDATE',(year,month)).fetchone():
            raise DirectoryConflict('Сначала сформируйте месяц')
        if remove:
            conn.execute('DELETE FROM luvr_month_employees WHERE year=%s AND month=%s AND employee_id=%s',(year,month,employee_id))
        else:
            if not conn.execute('SELECT id FROM employees WHERE id=%s FOR KEY SHARE',(employee_id,)).fetchone():
                raise DirectoryNotFound('Сотрудник не найден')
            conn.execute('INSERT INTO luvr_month_employees(year,month,employee_id) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING',(year,month,employee_id))
    return {'formed':True}
