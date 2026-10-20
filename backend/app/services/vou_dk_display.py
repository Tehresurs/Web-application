"""Display-only empty DK object rows. Never change B2 shares or report totals."""
from copy import deepcopy
from app.services.vou_data import position_order, VouDataError


def empty_dk_rows(data,context):
    result=deepcopy(data)
    if context is None:return result,[]
    matrix=context['matrix']
    if (matrix['year'],matrix['month'])!=(data['year'],data['month']):raise ValueError('Разные периоды Б2 и матрицы')
    positions={p['id']:p for p in context['positions']}
    targets=[*result['sections'][:5],*result['sections'][5]['subsections']]
    by_category={t['category_id']:t for t in targets if t['category_id'] is not None}
    known={(r['employee_id'],r.get('matrix_row_key'),r['category_id']):r for t in targets for r in t['rows']}
    controls=[]
    for employee in matrix['employees']:
        for source_row in employee['rows']:
            for day,cell in source_row['cells'].items():
                if not cell.get('is_dk') or cell.get('kind')!='OBJECT':continue
                if cell['share_cents']!=0:raise ValueError('ДК не обнулён в матрице')
                key=(employee['employee_id'],source_row['row_key'],cell.get('category_id'))
                target=by_category.get(cell.get('category_id'))
                if target is None:
                    raise ValueError('У объекта ДК отсутствует категория для отображения в ВОУ')
                pid=employee['position_id'];order=position_order(target['code'])
                if pid not in order:raise VouDataError('POSITION_ORDER_NOT_AGREED',position_id=pid,subsection=target['code'])
                if key not in known:
                    pos=positions[pid]
                    row=dict(employee_id=employee['employee_id'],full_name=employee['full_name'],
                        position_id=pid,position_name=employee['position_name'],category_id=cell['category_id'],
                        matrix_row_key=source_row['row_key'],kind='OBJECT',entity_id=cell.get('entity_id'),
                        object_id=cell.get('object_id'),subobject_id=cell.get('subobject_id'),
                        object_name=cell.get('object_name'),subobject_name=cell.get('subobject_name'),
                        po_id=cell.get('po_id'),subcontractor_id=cell.get('subcontractor_id'),
                        aos_description=pos.get('aos_description'),days_cents={d:0 for d in data['days_cents']},
                        total_cents=0,sources=[],display_only_dk=True)
                    known[key]=row;target['rows'].append(row)
                    if not pos.get('aos_description') and not any(w.get('code')=='MISSING_AOS_DESCRIPTION' and w.get('position_id')==pid for w in result['warnings']):
                        result['warnings'].append(dict(code='MISSING_AOS_DESCRIPTION',position_id=pid,position_name=pos['name']))
                if known[key]['days_cents'][day]!=0:raise ValueError('ДК возвращён в данные ВОУ')
                controls.append(dict(employee_id=employee['employee_id'],matrix_row_key=source_row['row_key'],
                                     category_id=cell['category_id'],date=day))
    for target in targets:
        order=position_order(target['code'])
        target['rows'].sort(key=lambda r:(order.index(r['position_id']),
            ' '.join(r['full_name'].split()).casefold().replace('ё','е'),r['employee_id'],
            r.get('entity_id') or 0,r.get('object_id') or 0,r.get('subobject_id') or 0))
    if sum(r['total_cents'] for t in targets for r in t['rows'])!=data['total_cents']:
        raise ValueError('Пустые строки ДК изменили контрольную сумму')
    return result,controls
