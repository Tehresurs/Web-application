from psycopg.rows import dict_row
from app.database.db import get_connection
from app.repositories.directory_errors import DirectoryNotFound
from app.repositories.luvr_history import _employee


def list_absences(employee_id):
    with get_connection() as conn,conn.cursor(row_factory=dict_row) as cur:
        _employee(cur,employee_id)
        cur.execute('''SELECT id,employee_id,'other' AS source,reason,date_from,date_to,comment FROM employee_absences WHERE employee_id=%s
            UNION ALL SELECT s.id,s.employee_id,'sick' AS source,COALESCE(l.reason,'Больничный') AS reason,s.date_from,s.date_to,s.comment
            FROM employee_sick_periods s LEFT JOIN employee_sick_absence_labels l ON l.sick_period_id=s.id
            WHERE s.employee_id=%s ORDER BY date_from,id,source''',(employee_id,employee_id))
        return cur.fetchall()


def save_absence(employee_id,reason,date_from,date_to,comment=None,source='other',item_id=None):
    if source not in ('other','sick') or (source=='sick' and item_id is None):raise ValueError('Некорректный источник отсутствия')
    reason=reason.strip()
    if not reason:raise ValueError('Укажите причину отсутствия')
    if (source=='other' and date_to is None) or (date_to is not None and date_to<date_from):raise ValueError('Укажите корректную дату окончания периода')
    table='employee_absences' if source=='other' else 'employee_sick_periods'
    with get_connection() as conn,conn.cursor(row_factory=dict_row) as cur:
        _employee(cur,employee_id)
        if item_id is None:
            cur.execute('INSERT INTO employee_absences(employee_id,reason,date_from,date_to,comment) VALUES(%s,%s,%s,%s,%s) RETURNING id',(employee_id,reason,date_from,date_to,comment))
        elif source=='other':
            # Identifiers selected only from the whitelist above.
            cur.execute('UPDATE employee_absences SET reason=%s,date_from=%s,date_to=%s,comment=%s,updated_at=CURRENT_TIMESTAMP WHERE employee_id=%s AND id=%s RETURNING id',(reason,date_from,date_to,comment,employee_id,item_id))
        else:
            cur.execute('UPDATE employee_sick_periods SET date_from=%s,date_to=%s,comment=%s,updated_at=CURRENT_TIMESTAMP WHERE employee_id=%s AND id=%s RETURNING id',(date_from,date_to,comment,employee_id,item_id))
        row=cur.fetchone()
        if not row:raise DirectoryNotFound('Отсутствие не найдено')
        if source=='sick':cur.execute('INSERT INTO employee_sick_absence_labels(sick_period_id,reason) VALUES(%s,%s) ON CONFLICT(sick_period_id) DO UPDATE SET reason=EXCLUDED.reason',(item_id,reason))
        return dict(id=row['id'],employee_id=employee_id,source=source,reason=reason,date_from=date_from,date_to=date_to,comment=comment)


def delete_absence(employee_id,source,item_id):
    if source not in ('other','sick'):raise ValueError('Некорректный источник отсутствия')
    table='employee_absences' if source=='other' else 'employee_sick_periods'
    with get_connection() as conn,conn.cursor(row_factory=dict_row) as cur:
        _employee(cur,employee_id)
        cur.execute(f'DELETE FROM {table} WHERE employee_id=%s AND id=%s RETURNING id',(employee_id,item_id))
        if not cur.fetchone():raise DirectoryNotFound('Отсутствие не найдено')
        return dict(id=item_id,deleted=True)
