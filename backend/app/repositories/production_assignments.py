import json
from contextlib import nullcontext
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg.errors import IntegrityError
from app.database.db import get_connection
from app.repositories.directory_errors import DirectoryConflict, DirectoryNotFound
from app.services.production_assignments import project, period_for, movement_revision, ticket_revision
from app.repositories.production_control_modes import policy, validate_mode
from app.repositories.object_archive import require_assignable
from app.repositories import construction_identity as identity


def _inputs(conn, employee_id):
    # A single statement gives facts, movements, tickets and changes one snapshot.
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute('''SELECT e.id,e.dismissal_date,p.work_location,p.work_schedule,
            COALESCE((SELECT jsonb_agg(to_jsonb(m)) FROM employee_movements m WHERE m.employee_id=e.id),'[]') movements,
            COALESCE((SELECT jsonb_agg(to_jsonb(t)) FROM rail_tickets t WHERE t.employee_id=e.id),'[]') tickets,
            COALESCE((SELECT jsonb_agg(to_jsonb(f)) FROM daily_control_results f WHERE f.employee_id=e.id),'[]') facts,
            COALESCE((SELECT jsonb_agg(to_jsonb(c)||jsonb_build_object('items',
                COALESCE((SELECT jsonb_agg(to_jsonb(i) ORDER BY i.id) FROM production_assignment_items i WHERE i.change_id=c.id),'[]'))
                ORDER BY c.effective_from,c.id) FROM production_assignment_changes c WHERE c.employee_id=e.id),'[]') changes
            FROM employees e LEFT JOIN positions p ON p.id=e.position_id WHERE e.id=%s''', (employee_id,))
        result = cur.fetchone()
    if not result:
        raise DirectoryNotFound('Сотрудник не найден')
    if result['dismissal_date']:
        result['dismissal_date'] = result['dismissal_date'].isoformat()
    # A nullable migration column must not invalidate legacy fact revisions.
    for fact in result['facts']:
        if fact.get('entity_id') is None:fact.pop('entity_id',None)
    return result


def get_history(employee_id, date_from, date_to):
    if date_to < date_from:
        raise ValueError('Дата окончания раньше начала')
    with get_connection() as conn:
        result={**project(_inputs(conn, employee_id), str(date_from), str(date_to)),**policy(conn,employee_id)}
        if identity.enabled(conn):
            for group in result['history']+result['periods']:
                for item in group['items']:identity.describe(conn,item)
            for item in result['facts']:identity.describe(conn,item)
        return result


def save(employee_id, payload, change_id=None, version=None, connection=None):
    try:
        with (nullcontext(connection) if connection is not None else get_connection()) as conn, conn.transaction():
            conn.execute('SET CONSTRAINTS production_change_shape, production_items_shape DEFERRED')
            # Same lock as existing ticket annul/restore; also serialize employee edits.
            conn.execute('SELECT pg_advisory_xact_lock(20261007,1601)')
            identities=identity.enabled(conn)
            if identities:conn.execute('SELECT pg_advisory_xact_lock(20261013,24)')
            found = conn.execute('SELECT id FROM employees WHERE id=%s FOR KEY SHARE', (employee_id,)).fetchone()
            if not found:
                raise DirectoryNotFound('Сотрудник не найден')
            conn.execute('SELECT id FROM rail_tickets WHERE employee_id=%s FOR SHARE', (employee_id,)).fetchall()
            conn.execute('SELECT id FROM employee_movements WHERE employee_id=%s FOR SHARE', (employee_id,)).fetchall()
            data = _inputs(conn, employee_id)
            old = next((c for c in data['changes'] if c['id'] == change_id), None)
            if change_id is not None and old is None:
                raise DirectoryNotFound('Назначение не найдено')
            if old and old['version'] != version:
                raise DirectoryConflict('Назначение уже изменено. Обновите данные')
            values = json.loads(json.dumps(payload, default=str))
            items = values.pop('items')
            rules=policy(conn,employee_id,lock=True)
            for item in items:
                if identities:
                    existing=old and old['effective_from']==values['effective_from'] and any(
                        identity.reference(conn,i)['entity_id']==identity.reference(conn,item)['entity_id'] for i in old['items'])
                    identity.prepare(conn,item,assignable=not existing)
                    # Preserve legacy references on an unchanged item.
                    if existing:
                        prior=next(i for i in old['items'] if identity.reference(conn,i)['entity_id']==item['entity_id'])
                        item.update({k:prior.get(k) for k in ('object_id','subobject_id','entity_id')})
                else:
                    identity.prepare(conn,item)
                existing = old and old['effective_from']==values['effective_from'] and any(i['object_id']==item['object_id'] and i.get('subobject_id')==item.get('subobject_id') for i in old['items'])
                if not existing and not identities:
                    with conn.cursor() as archive_cursor:
                        try:
                            require_assignable(archive_cursor,item['object_id'],item.get('subobject_id'))
                        except DirectoryNotFound as error:
                            raise DirectoryConflict(str(error)) from error
                if change_id is None and 'initial_control_mode' not in item:
                    item['initial_control_mode']=rules['default_control_mode']
                validate_mode(item.get('initial_control_mode'),rules)
            values.update(employee_id=employee_id, arrival_ticket_id=None, source_revision=None)
            if values['period_kind'] == 'ARRIVAL':
                anchor = next((m for m in data['movements'] if m['id'] == values['arrival_movement_ref']), None)
                if not anchor or anchor['movement_type'] != 'ARRIVAL':
                    raise ValueError('Укажите существующий заезд этого сотрудника')
                values['period_start'] = anchor['event_datetime'][:10]
                values['period_revision'] = movement_revision(anchor)
                ticket = next((t for t in data['tickets'] if t.get('movement_id') == anchor['id'] and t['status'] == 'CONFIRMED'), None)
                values['arrival_ticket_id'] = ticket['id'] if ticket else None
            else:
                values['period_revision'] = f"EXPLICIT:{values['period_start']}:{values['period_end']}"
                for c in data['changes']:
                    if c['id'] == change_id or c['period_kind'] != 'EXPLICIT':
                        continue
                    same = (c['period_start'], c['period_end']) == (values['period_start'], values['period_end'])
                    overlap = c['period_start'] <= values['period_end'] and values['period_start'] <= c['period_end']
                    if overlap and not same:
                        raise DirectoryConflict('Явные периоды не должны пересекаться')
            if values['effective_from'] < values['period_start']:
                raise ValueError('Назначение не может начинаться раньше периода')
            if values.get('period_end') and values['period_end'] < values['effective_from']:
                raise ValueError('Назначение находится за пределами периода')
            if values['source_kind'] == 'TICKET':
                ticket = next((t for t in data['tickets'] if t['id'] == values['source_ticket_id']), None)
                if not ticket or ticket['status'] != 'CONFIRMED' or ticket.get('movement_id') != values['arrival_movement_ref']:
                    raise ValueError('Нужен подтверждённый билет выбранного заезда')
                if identities:
                    matches=(ticket.get('entity_id') is not None or ticket.get('object_id') is not None) and any(
                        identity.reference(conn,ticket)['entity_id']==identity.reference(conn,i)['entity_id'] for i in items)
                else:
                    matches=ticket.get('object_id') is not None and ticket['object_id'] in [i['object_id'] for i in items]
                if not matches:
                    raise ValueError('Набор должен содержать назначенный в билете объект')
                values['source_revision'] = ticket_revision(ticket)
            period, reason = period_for(values, data)
            if not period:
                raise ValueError(f'Назначение неприменимо: {reason}')
            if old and (old['period_kind'], old['arrival_movement_ref'], old['period_start'], old['period_end']) != (
                values['period_kind'], values['arrival_movement_ref'], values['period_start'], values['period_end']
            ):
                raise ValueError('Для другого периода создайте новое событие')
            for item in items:
                aid = item.get('source_assignment_id')
                if aid:
                    if identities:
                        with conn.cursor(row_factory=dict_row) as cur:
                            cur.execute('SELECT * FROM employee_assignments WHERE id=%s FOR SHARE',(aid,))
                            source=cur.fetchone()
                        if not source or (source['employee_id'],identity.reference(conn,source)['entity_id'],source['po_id'],source['category_id']) != (employee_id,identity.reference(conn,item)['entity_id'],item.get('po_id'),item.get('initial_category_id')):
                            raise ValueError('Закрепление не соответствует назначению')
                        continue
                    row = conn.execute('''SELECT employee_id,object_id,po_id,category_id FROM employee_assignments
                        WHERE id=%s FOR SHARE''', (aid,)).fetchone()
                    if row != (employee_id, item['object_id'], item['po_id'], item['initial_category_id']):
                        raise ValueError('Закрепление не соответствует сотруднику и назначению')
            if old:
                history = old['correction_history'] + [{k:v for k,v in old.items() if k != 'correction_history'}]
                fields = ','.join(f'{k}=%s' for k in values)
                conn.execute(f'''UPDATE production_assignment_changes SET {fields}, version=version+1,
                    correction_history=%s,updated_at=CURRENT_TIMESTAMP WHERE id=%s''',
                    (*values.values(), Jsonb(history), change_id))
                # IDs of identical items survive PATCH; replaced ones remain in correction_history.
                retained = set()
                for item in items:
                    match = next((i for i in old['items'] if all(i.get(k) == v for k,v in item.items())), None)
                    if match:
                        item['_retained_id'] = match['id']
                        retained.add(match['id'])
                conn.execute('DELETE FROM production_assignment_items WHERE change_id=%s AND NOT (id=ANY(%s))', (change_id, list(retained)))
            else:
                columns = ','.join(values)
                placeholders = ','.join(['%s'] * len(values))
                change_id = conn.execute(f'INSERT INTO production_assignment_changes ({columns}) VALUES ({placeholders}) RETURNING id', tuple(values.values())).fetchone()[0]
            for item in items:
                if item.pop('_retained_id', None):
                    continue
                columns = ','.join(item)
                placeholders = ','.join(['%s'] * len(item))
                conn.execute(f'INSERT INTO production_assignment_items (change_id,{columns}) VALUES (%s,{placeholders})', (change_id, *item.values()))
            conn.execute('SET CONSTRAINTS production_change_shape, production_items_shape IMMEDIATE')
            return next(c for c in _inputs(conn, employee_id)['changes'] if c['id'] == change_id)
    except IntegrityError as exc:
        raise DirectoryConflict('Нарушены связи или ограничения назначения: проверьте объекты, подобъекты и повтор даты') from exc


def correct(change_id, payload, version):
    with get_connection() as conn:
        row = conn.execute('SELECT employee_id FROM production_assignment_changes WHERE id=%s', (change_id,)).fetchone()
    if not row:
        raise DirectoryNotFound('Назначение не найдено')
    return save(row[0], payload, change_id, version)
