"""Identity-aware persistence and reading; source fact columns remain immutable."""
from psycopg.rows import dict_row
from app.repositories import construction_identity as identity


SELECT = '''SELECT r.*,e.full_name,e.full_name employee_name,p.name po_name,c.name category_name,
    sc.name subcontractor_name FROM daily_control_results r
    JOIN employees e ON e.id=r.employee_id LEFT JOIN po_types p ON p.id=r.po_id
    LEFT JOIN object_categories c ON c.id=r.category_id LEFT JOIN po_types sc ON sc.id=r.subcontractor_id'''


def read(conn, where, params):
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(SELECT+' WHERE '+where+' ORDER BY r.report_date,r.id',params)
        rows=cur.fetchall()
    for row in rows:row.update(identity.presentation(identity.reference(conn,row)))
    return rows


def insert(conn,report_date,assignment,source_file,digest):
    identity.require_enabled(conn)
    conn.execute('SELECT pg_advisory_xact_lock(20261013,24)')
    item=identity.prepare(conn,dict(assignment),assignable=False)
    entity=identity.reference(conn,item)
    if not entity['is_active']:raise ValueError('Подобъект неактивен')
    key=(report_date,item['employee_id'],item['entity_id'],item['po_id'],item['category_id'],item.get('subcontractor_id'))
    where='''r.report_date=%s AND r.employee_id=%s AND construction_reference(r.entity_id,r.object_id,r.subobject_id)=%s
        AND r.po_id IS NOT DISTINCT FROM %s AND r.category_id IS NOT DISTINCT FROM %s AND r.subcontractor_id IS NOT DISTINCT FROM %s'''
    previous=read(conn,where,key)
    if previous:return {**previous[0],'created':False}
    fact_id=conn.execute('''INSERT INTO daily_control_results
        (report_date,employee_id,entity_id,object_id,subobject_id,po_id,category_id,subcontractor_id,source_file,source_sha256)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''',
        (report_date,item['employee_id'],item['entity_id'],item.get('object_id'),item.get('subobject_id'),
         item['po_id'],item['category_id'],item.get('subcontractor_id'),source_file,digest)).fetchone()[0]
    return {**read(conn,'r.id=%s',(fact_id,))[0],'created':True}


def assignments(conn,employee_id,entity_id,po_id,assignment_id=None):
    entity=identity.resolve(conn,entity_id=entity_id)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute('''SELECT a.id assignment_id,a.employee_id,a.object_id,a.po_id,a.category_id,
            construction_reference(a.entity_id,a.object_id) entity_id FROM employee_assignments a
            WHERE a.employee_id=%s AND a.po_id IS NOT DISTINCT FROM %s AND (%s::bigint IS NULL OR a.id=%s)
            AND construction_reference(a.entity_id,a.object_id)=ANY(%s) ORDER BY a.id FOR SHARE''',
            (employee_id,po_id,assignment_id,assignment_id,[entity_id,entity['parent_entity_id']]))
        rows=cur.fetchall()
    exact=[r for r in rows if r['entity_id']==entity_id]
    return exact or rows


def journal(conn,date_from,date_to,employee_id,object_id,view,subobject_id,include_subobjects,subcontractor_id,entity_id):
    from app.repositories.daily_control import summarize_journal
    all_rows=read(conn,'r.report_date BETWEEN %s AND %s',(date_from,date_to))
    selected=None
    if entity_id is not None or object_id is not None or subobject_id is not None:
        selected=identity.resolve(conn,entity_id=entity_id,object_id=object_id,subobject_id=subobject_id)['entity_id']
    rows=[r for r in all_rows if (employee_id is None or r['employee_id']==employee_id)
        and (subcontractor_id is None or r['subcontractor_id']==subcontractor_id)
        and (selected is None or r['entity_id']==selected or (include_subobjects and subobject_id is None and r['parent_entity_id']==selected))]
    options=dict(employees=list({r['employee_id']:dict(employee_id=r['employee_id'],full_name=r['full_name']) for r in all_rows}.values()),
        control_items=list({r['entity_id']:{k:r.get(k) for k in ('entity_id','parent_entity_id','control_item_key','control_item_type','control_item_name','object_id','subobject_id','object_name')} for r in all_rows}.values()),
        subcontractors=list({r['subcontractor_id']:dict(id=r['subcontractor_id'],name=r['subcontractor_name']) for r in all_rows if r['subcontractor_id'] is not None}.values()))
    return {**summarize_journal(rows,view),'options':options}
