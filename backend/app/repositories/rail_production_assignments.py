"""Connect a confirmed ticket to the existing dated-assignment writer, atomically."""
from app.repositories.directory_errors import DirectoryConflict
from app.repositories.production_assignments import _inputs, save
from app.services.production_assignments import ticket_revision
from app.repositories.production_control_modes import policy
from app.repositories import construction_identity as identity

ITEM_FIELDS=('object_id','subobject_id','po_id','subcontractor_id','initial_category_id',
             'initial_control_mode','source_assignment_id')


def sync(conn,ticket,previous_object_id=None,previous_entity_id=None,assignment_fields=None):
    if ticket['status']!='CONFIRMED' or ticket['movement_type']!='ARRIVAL' or not (ticket.get('object_id') or ticket.get('entity_id')):
        return
    # Older isolated schemas have no stage-3A tables. No new storage is created here.
    if conn.execute("SELECT to_regclass('production_assignment_changes')").fetchone()[0] is None:
        return
    if identity.enabled(conn):
        return _sync_identity(conn,ticket,previous_object_id,previous_entity_id,assignment_fields)
    data=_inputs(conn,ticket['employee_id'])
    day=str(ticket['arrival_datetime'])[:10]
    linked=[c for c in data['changes'] if c.get('source_ticket_id')==ticket['id']]
    if any(c['arrival_movement_ref']!=ticket['movement_id'] for c in linked):
        raise DirectoryConflict('Источник назначения относится к другому заезду. Проверьте историю назначения.')
    if not linked:
        existing=next((c for c in data['changes'] if c['arrival_movement_ref']==ticket['movement_id'] and c['effective_from']==day),None)
        if existing:
            # Never silently replace an independent multi-object set or change its source.
            if any(i['object_id']==ticket['object_id'] for i in existing['items']):
                if assignment_fields is not None:raise DirectoryConflict('На дату заезда уже есть независимое назначение. Измените его в производственных назначениях.')
                return
            raise DirectoryConflict('На дату заезда уже есть независимый набор объектов. Измените этот набор в производственном назначении; билет не изменён.')
        linked=[None]
    for old in linked:
        if old and old['source_revision']==ticket_revision(ticket) and assignment_fields is None:continue
        items=[{k:i.get(k) for k in ITEM_FIELDS} for i in old['items']] if old else []
        previous=previous_object_id
        if old and previous is None:
            previous=next((i['object_id'] for i in items if ticket_revision({**ticket,'object_id':i['object_id']})==old['source_revision']),None)
        if previous is not None and previous!=ticket['object_id']:
            items=[i for i in items if i['object_id']!=previous]
        if not any(i['object_id']==ticket['object_id'] for i in items):
            # Only object_id is known from the ticket. Do not borrow attributes
            # from another object, a previous shift or static employee assignments.
            items.append({'object_id':ticket['object_id'],
                          'initial_control_mode':policy(conn,ticket['employee_id'])['default_control_mode']})
        if assignment_fields is not None:
            for item in items:
                if item['object_id']==ticket['object_id']:item.update(assignment_fields)
            if old and old['source_revision']==ticket_revision(ticket) and all(
                all(item.get(k)==prior.get(k) for k in ITEM_FIELDS) for item,prior in zip(items,old['items'])
            ) and len(items)==len(old['items']):continue
        payload=dict(effective_from=old['effective_from'] if old else day,
            period_kind='ARRIVAL',arrival_movement_ref=ticket['movement_id'],period_start=None,period_end=None,
            source_kind='TICKET',source_ticket_id=ticket['id'],assignment_state='OBJECTS',items=items)
        save(ticket['employee_id'],payload,old['id'] if old else None,old['version'] if old else None,connection=conn)


def _sync_identity(conn,ticket,previous_object_id,previous_entity_id,assignment_fields=None):
    target=identity.reference(conn,ticket)['entity_id']
    previous=None
    if previous_object_id is not None or previous_entity_id is not None:
        previous=identity.reference(conn,dict(object_id=previous_object_id,entity_id=previous_entity_id))['entity_id']
    data=_inputs(conn,ticket['employee_id'])
    day=str(ticket['arrival_datetime'])[:10]
    linked=[c for c in data['changes'] if c.get('source_ticket_id')==ticket['id']]
    if any(c['arrival_movement_ref']!=ticket['movement_id'] for c in linked):
        raise DirectoryConflict('Источник назначения относится к другому заезду')
    if not linked:
        existing=next((c for c in data['changes'] if c['arrival_movement_ref']==ticket['movement_id'] and c['effective_from']==day),None)
        if existing:
            if any(identity.reference(conn,i)['entity_id']==target for i in existing['items']):
                if assignment_fields is not None:raise DirectoryConflict('На дату заезда уже есть независимое назначение. Измените его в производственных назначениях.')
                return
            raise DirectoryConflict('На дату заезда уже есть независимый набор объектов')
    for old in linked or [None]:
        if old and old['source_revision']==ticket_revision(ticket) and assignment_fields is None:continue
        items=[{k:i.get(k) for k in (*ITEM_FIELDS,'entity_id')} for i in old['items']] if old else []
        if previous is not None and previous!=target:
            items=[i for i in items if identity.reference(conn,i)['entity_id']!=previous]
        if not any(identity.reference(conn,i)['entity_id']==target for i in items):
            items.append(dict(entity_id=target,object_id=None,subobject_id=None,
                initial_control_mode=policy(conn,ticket['employee_id'])['default_control_mode']))
        if assignment_fields is not None:
            for item in items:
                if identity.reference(conn,item)['entity_id']==target:item.update(assignment_fields)
            if old and old['source_revision']==ticket_revision(ticket) and all(
                all(item.get(k)==prior.get(k) for k in (*ITEM_FIELDS,'entity_id')) for item,prior in zip(items,old['items'])
            ) and len(items)==len(old['items']):continue
        payload=dict(effective_from=old['effective_from'] if old else day,
            period_kind='ARRIVAL',arrival_movement_ref=ticket['movement_id'],period_start=None,period_end=None,
            source_kind='TICKET',source_ticket_id=ticket['id'],assignment_state='OBJECTS',items=items)
        save(ticket['employee_id'],payload,old['id'] if old else None,old['version'] if old else None,connection=conn)
