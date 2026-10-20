from contextlib import nullcontext
from datetime import date
from psycopg.rows import dict_row
from psycopg.pq import TransactionStatus
from app.database.db import get_connection
from app.repositories.luvr_calendar import CALENDAR_SELECT, decode_calendar_inputs
from app.repositories.production_assignments import _inputs
from app.repositories.production_control_modes import policy


def get_inputs(year, month, employee_id=None, connection=None):
    """One read-only repeatable snapshot; reuse existing calendar/source loaders."""
    with (nullcontext(connection) if connection is not None else get_connection()) as conn:
        if conn.info.transaction_status == TransactionStatus.IDLE:
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute('SELECT EXISTS(SELECT 1 FROM luvr_months WHERE year=%s AND month=%s) AS formed',(year,month))
            formed = cur.fetchone()['formed']
            cur.execute('''SELECT cal.*,e.position_id,p.requires_daily_report FROM (''' + CALENDAR_SELECT + '''
                JOIN luvr_month_employees member ON member.employee_id=e.id
                WHERE member.year=%s AND member.month=%s AND (%s::bigint IS NULL OR e.id=%s)
                ) cal JOIN employees e ON e.id=cal.employee_id LEFT JOIN positions p ON p.id=e.position_id''',
                (year,month,employee_id,employee_id))
            employees = cur.fetchall()
            from app.repositories.personnel_transfers import attach_context
            attach_context(conn,employees)
            # Keep approval metadata separate from source facts: adding fields to
            # production['facts'] would invalidate existing override revisions.
            cur.execute("SELECT to_regclass('report_review_events') IS NOT NULL AS installed")
            review_events_installed=cur.fetchone()['installed']
            cur.execute("SELECT to_regclass('production_matrix_dk') IS NOT NULL AS installed")
            dk_installed=cur.fetchone()['installed']
            for employee in employees:
                employee.update(policy(conn,employee['employee_id']))
                employee['dk_dates']=[]
                if dk_installed:
                    cur.execute('SELECT work_date FROM production_matrix_dk WHERE employee_id=%s AND EXTRACT(YEAR FROM work_date)=%s AND EXTRACT(MONTH FROM work_date)=%s',
                                (employee['employee_id'],year,month))
                    employee['dk_dates']=[r['work_date'].isoformat() for r in cur.fetchall()]

                if employee['dismissal_date']:
                    employee['dismissal_date'] = date.fromisoformat(employee['dismissal_date']) if isinstance(employee['dismissal_date'],str) else employee['dismissal_date']
                decode_calendar_inputs(employee)
                employee['production'] = _inputs(conn,employee['employee_id'])
                employee['approved_po_absence_fact_ids']=[]
                if review_events_installed:
                    cur.execute('''SELECT f.id FROM daily_control_results f
                        WHERE f.employee_id=%s AND f.po_id IS NULL AND EXISTS (
                            SELECT 1 FROM report_review_events ev
                            WHERE ev.source_sha256=trim(f.source_sha256)
                              AND ev.field='general_contractor' AND ev.action='absence_saved')''',
                        (employee['employee_id'],))
                    employee['approved_po_absence_fact_ids']=[r['id'] for r in cur.fetchall()]
                cur.execute('SELECT * FROM production_matrix_overrides WHERE employee_id=%s ORDER BY effective_from,id',(employee['employee_id'],))
                employee['matrix_overrides'] = cur.fetchall()
            names = {}
            for table in ('construction_objects','construction_subobjects','po_types','object_categories'):
                cur.execute(f'SELECT id,name FROM {table}')
                names[table] = {r['id']:r['name'] for r in cur.fetchall()}
            from app.repositories import construction_identity as identity
            if identity.enabled(conn):
                names['entities']={}
                for r in identity.directory(conn):
                    entity=identity.resolve(conn,entity_id=r['entity_id'])
                    names['entities'][('entity',r['entity_id'])]=entity
                    if r['legacy_object_id'] is not None:names['entities'][('object',r['legacy_object_id'])]=entity
                    if r['legacy_subobject_id'] is not None:names['entities'][('subobject',r['legacy_subobject_id'])]=entity
    employees.sort(key=lambda e: (' '.join(e['full_name'].split()).casefold().replace('ё','е'),e['employee_id']))
    return {'formed':formed,'employees':employees,'names':names}
