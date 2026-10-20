from psycopg.rows import dict_row
from psycopg.errors import IntegrityError
from app.database.db import get_connection
from app.repositories.directory_errors import DirectoryConflict, DirectoryNotFound
from app.repositories.production_assignments import _inputs
from app.services.production_assignments import project
from app.services.production_matrix_overrides import match_source, resolve, editable_periods
from app.repositories.production_control_modes import policy, validate_mode


def get_overrides(employee_id, date_from, date_to, period_key=None):
    if date_to < date_from:
        raise ValueError('Дата окончания раньше начала')
    with get_connection() as conn:
        data = _inputs(conn, employee_id)
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute('''SELECT * FROM production_matrix_overrides WHERE employee_id=%s AND effective_from<=%s
                AND (%s::text IS NULL OR period_key=%s) ORDER BY effective_from,id''',
                (employee_id,date_to,period_key,period_key))
            changes = cur.fetchall()
        result = resolve(data, changes, str(date_from), str(date_to))
        if period_key:
            result['intervals'] = [r for r in result['intervals'] if r['period_key'] == period_key]
        return result


def upsert(employee_id, payload):
    values = dict(payload)
    expected = values.pop('version')
    values['assignment_item_ref'] = values.get('assignment_item_id')
    values['employee_id'] = employee_id
    try:
        with get_connection() as conn, conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
            conn.execute('SELECT pg_advisory_xact_lock(20261007,1601)')
            conn.execute('SELECT id FROM rail_tickets WHERE employee_id=%s FOR SHARE',(employee_id,)).fetchall()
            conn.execute('SELECT id FROM employee_movements WHERE employee_id=%s FOR SHARE',(employee_id,)).fetchall()
            conn.execute('SELECT id FROM daily_control_results WHERE employee_id=%s FOR SHARE',(employee_id,)).fetchall()
            data = _inputs(conn, employee_id)
            validate_mode(values.get('control_mode'),policy(conn,employee_id,lock=True))
            _,periods = editable_periods(data)
            if not match_source(periods, values):
                raise DirectoryConflict('Исходная строка, дата или период изменились либо не принадлежат сотруднику. Обновите данные')
            if values['category_id'] is not None:
                cur.execute('SELECT id FROM object_categories WHERE id=%s FOR SHARE',(values['category_id'],))
                if not cur.fetchone():
                    raise ValueError('Категория не найдена')
            if values.get('po_id') is not None:
                cur.execute('SELECT id FROM po_types WHERE id=%s FOR SHARE',(values['po_id'],))
                if not cur.fetchone():raise ValueError('ПО не найдено')
            key_fields = ('employee_id','period_key','basis_revision','scope','fact_id','assignment_item_ref','field_name','effective_from')
            where = ' AND '.join(f'{field} IS NOT DISTINCT FROM %s' for field in key_fields)
            cur.execute(f'SELECT * FROM production_matrix_overrides WHERE {where} FOR UPDATE', tuple(values[f] for f in key_fields))
            old = cur.fetchone()
            if old:
                if expected != old['version']:
                    raise DirectoryConflict('Корректировка уже изменена. Обновите данные и версию')
                cur.execute('''UPDATE production_matrix_overrides SET category_id=%s,control_mode=%s,po_id=%s,
                    is_deleted=false,version=version+1,updated_at=CURRENT_TIMESTAMP WHERE id=%s RETURNING *''',
                    (values['category_id'],values['control_mode'],values.get('po_id'),old['id']))
            else:
                if expected != 0:
                    raise DirectoryConflict('Корректировка не существует. Для создания требуется version=0')
                columns = ','.join(values)
                placeholders = ','.join(['%s']*len(values))
                cur.execute(f'INSERT INTO production_matrix_overrides ({columns}) VALUES ({placeholders}) RETURNING *',tuple(values.values()))
            return cur.fetchone()
    except IntegrityError as exc:
        raise DirectoryConflict('Нарушена связь с исходной записью или ограничение корректировки') from exc


def remove(override_id, version):
    with get_connection() as conn, conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
        conn.execute('SELECT pg_advisory_xact_lock(20261007,1601)')
        cur.execute('SELECT * FROM production_matrix_overrides WHERE id=%s FOR UPDATE',(override_id,))
        old = cur.fetchone()
        if not old:
            raise DirectoryNotFound('Корректировка не найдена')
        if old['version'] != version or old['is_deleted']:
            raise DirectoryConflict('Корректировка уже изменена или удалена. Обновите данные')
        cur.execute('''UPDATE production_matrix_overrides SET is_deleted=true,version=version+1,
            updated_at=CURRENT_TIMESTAMP WHERE id=%s RETURNING *''',(override_id,))
        return cur.fetchone()
