"""Report-scoped approvals and category changes; source Word data is immutable."""
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from app.parsers.word_parser import read_document
from app.services.po_matcher import subcontractor_is_absent
from app.repositories import construction_identity as identity

FIELDS = ('general_contractor', 'subcontractor')

def enabled(conn):
    return conn.execute("SELECT to_regclass('report_absence_rules')").fetchone()[0] is not None

def source(path):
    p = Path(path)
    if p.suffix.lower() != '.docx' or not p.is_file():
        raise ValueError('Укажите существующий Word-отчёт .docx')
    content = p.read_bytes()
    stream = BytesIO(content)
    stream.name = p.name
    return sha256(content).hexdigest(), read_document(stream)

def event(conn, digest, field, action, **details):
    conn.execute('INSERT INTO report_review_events(source_sha256,field,action,details) VALUES(%s,%s,%s,%s)',
                 (digest, field, action, Jsonb(details)))

def options(conn, digest, document):
    if not enabled(conn):
        return {'enabled': False, 'fields': {}}
    conn.execute('SELECT pg_advisory_xact_lock(20261015,25)')
    rules = dict(conn.execute('SELECT field,enabled FROM report_absence_rules').fetchall())
    manual = {r[0] for r in conn.execute('SELECT field FROM report_absence_approvals WHERE source_sha256=%s',(digest,))}
    fields = {}
    for field in FIELDS:
        data = document['business_data'][field]
        absent = subcontractor_is_absent(data.get('raw', data.get('value')))
        fields[field] = dict(absent=absent, rule=rules.get(field,False), manual=field in manual,
                             approved=absent and (field in manual or rules.get(field,False)))
    return dict(enabled=True,fields=fields)

def approve(conn, path, field, as_rule=False):
    if field not in FIELDS: raise ValueError('Неизвестное поле')
    digest, doc = source(path)
    state = options(conn,digest,doc)
    if not state['enabled']: raise ValueError('Хранение согласований не подготовлено')
    if not state['fields'][field]['absent']:
        raise ValueError('Заполненное значение нельзя согласовать как отсутствующее')
    if as_rule:
        conn.execute('''INSERT INTO report_absence_rules(field,enabled) VALUES(%s,true)
            ON CONFLICT(field) DO UPDATE SET enabled=true,version=report_absence_rules.version+1,updated_at=CURRENT_TIMESTAMP''',(field,))
    else:
        conn.execute('INSERT INTO report_absence_approvals(source_sha256,field) VALUES(%s,%s) ON CONFLICT DO NOTHING',(digest,field))
    event(conn,digest,field,'rule_enabled' if as_rule else 'absence_approved')
    return options(conn,digest,doc)

def cancel_rule(conn,field):
    if field not in FIELDS: raise ValueError('Неизвестное поле')
    conn.execute('SELECT pg_advisory_xact_lock(20261015,25)')
    conn.execute('UPDATE report_absence_rules SET enabled=false,version=version+1,updated_at=CURRENT_TIMESTAMP WHERE field=%s',(field,))
    event(conn,None,field,'rule_disabled')

def selected_category(conn, digest, employee_id, entity_id, po_id):
    scope=dict(employee_id=employee_id,entity_id=entity_id,po_id=po_id)
    row=conn.execute("SELECT details FROM report_review_events WHERE source_sha256=%s AND action='report_category_selected' AND details @> %s ORDER BY id DESC LIMIT 1",(digest,Jsonb(scope))).fetchone()
    return row[0] if row else None


def category(conn, request):
    conn.execute('SELECT pg_advisory_xact_lock(20261013,24)')
    digest,doc = source(request.path)
    state = options(conn,digest,doc)
    if not state['enabled']: raise ValueError('Обновление категории отчёта не подготовлено')
    if request.po_id is None and not state['fields']['general_contractor']['approved']:
        raise ValueError('Сначала согласуйте отсутствие ПО')
    if request.po_id is not None and state['fields']['general_contractor']['absent']:
        raise ValueError('ПО отсутствует в исходном отчёте; сохраняется пустое значение')
    saved=selected_category(conn,digest,request.employee_id,request.entity_id,request.po_id)
    category_id=request.category_id
    if getattr(request,'automatic',False):
        if saved:category_id=saved['category_id']
        elif request.po_id is not None:
            value=conn.execute('SELECT default_category_id FROM po_types WHERE id=%s FOR SHARE',(request.po_id,)).fetchone()
            category_id=value[0] if value else None
        if category_id is None:return None
    if category_id is None:raise ValueError('Выберите категорию')
    conn.execute('SELECT pg_advisory_xact_lock(20261013,24)')
    for table,value,label in [('employees',request.employee_id,'Сотрудник'),('object_categories',category_id,'Категория'),('po_types',request.po_id,'ПО')]:
        if value is not None and conn.execute(f'SELECT id FROM {table} WHERE id=%s FOR SHARE',(value,)).fetchone() is None:
            raise ValueError(label+' не найдены в справочнике')
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute('''SELECT * FROM employee_assignments WHERE employee_id=%s
            AND construction_reference(entity_id,object_id)=%s AND po_id IS NOT DISTINCT FROM %s FOR UPDATE''',
            (request.employee_id,request.entity_id,request.po_id))
        old = cur.fetchall()
        if len(old)>1: raise ValueError('Найдено несколько закреплений для сотрудника, сущности и ПО. Требуется выбрать и проверить существующие закрепления')
        identity.prepare(conn,dict(entity_id=request.entity_id),assignable=not old)
        if old:
            item=dict(old[0])
        else:
            cur.execute('''INSERT INTO employee_assignments(employee_id,entity_id,po_id,category_id)
                VALUES(%s,%s,%s,%s) RETURNING *''',(request.employee_id,request.entity_id,request.po_id,category_id))
        if not old:item = cur.fetchone()
    item['entity_id']=request.entity_id
    item['category_id']=category_id
    item['category_name']=conn.execute('SELECT name FROM object_categories WHERE id=%s',(category_id,)).fetchone()[0]
    if not getattr(request,'automatic',False) or not saved:
        event(conn,digest,None,'report_category_selected',employee_id=request.employee_id,entity_id=request.entity_id,po_id=request.po_id,assignment_id=item['id'],category_id=category_id,automatic=getattr(request,'automatic',False))
    return item
