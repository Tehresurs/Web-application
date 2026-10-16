"""Read-only aggregation of existing matrix cells, never a PLAN/FACT projection."""
from datetime import timedelta
from psycopg.rows import dict_row
from app.database.db import get_connection
from app.repositories.employees import get_positions
from app.services.production_matrix import calculate_month
from app.services.deployment import POSITION_PRIORITY, normalized_name

LIMITATIONS = [
    'План штатной численности — текущее planned_count для всех дат; история изменений отсутствует.',
    'Должности сотрудников — текущие, исторические снимки отсутствуют.',
    'Подтверждённые отчёты считаются по уникальным SHA-256 сохранённых источников фактов, не по числу загруженных файлов.',
    'При «Д» в ЛУВР время равно 0: отчёт хранится в истории, но не учитывается в количестве отчётов, численности на объектах и средней нагрузке.',
    'Прогноз: один отчёт на пару сотрудник–объект в день; подобъекты, ПО и категории не увеличивают число.',
]


def load_document_keys(ids):
    if not ids:
        return {}
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute('SELECT id,employee_id,report_date,source_sha256 FROM daily_control_results WHERE id=ANY(%s)',(sorted(ids),))
            return {r['id']:dict(r) for r in cur.fetchall()}


def staffing_row(position, actual):
    planned=position['planned_count']
    return dict(position_id=position['id'],position_name=position['name'],planned=planned,actual=actual,
                deviation=None if actual is None else actual-planned,
                completeness=None if not planned or actual is None else round(actual/planned*100,2))


def analyze_day(target, matrix, positions, documents):
    day=target.isoformat()
    warnings=[]
    working={}
    objects=set(); confirmed_people=set(); forecast_people=set(); hashes=set(); pairs=set()
    incomplete=False
    for employee in matrix['employees'] if matrix['formed'] else []:
        eid=employee['employee_id']
        calendar=next((d for d in employee['luvr_days'] if str(d['date'])==day),None)
        cells=[row['cells'][day] for row in employee['rows'] if day in row['cells']]
        facts=[c for c in cells if c['source']=='FACT']
        for check in employee['checks']:
            if str(check['date'])==day and check['status']!='OK':
                warnings.append(dict(employee_id=eid,code=check['status'],details=check['warnings']))
        if not calendar:
            incomplete=True
            warnings.append(dict(employee_id=eid,code='CALENDAR_MISSING'))
            continue
        if calendar['final_code'] not in ('FULL','HALF'):
            # Travel reports remain in history, but are not accepted for accounting.
            if facts and calendar['final_code']!='TRAVEL':
                warnings.append(dict(employee_id=eid,code='FACT_ON_NONWORKING_DAY',fact_ids=[c.get('source_fact_id') for c in facts]))
            continue
        working[eid]=employee.get('position_id')
        selected=facts or [c for c in cells if c['source']=='PLAN']
        for c in selected:
            if c.get('object_id') is None and c.get('entity_id') is None:
                continue
            object_key=('entity',c['entity_id']) if c.get('entity_id') is not None else c['object_id']
            objects.add(object_key)
            if c['source']=='FACT':
                confirmed_people.add(eid)
                doc=documents.get(c.get('source_fact_id'))
                if not doc or not doc.get('source_sha256') or doc['employee_id']!=eid or str(doc['report_date'])!=day:
                    incomplete=True
                    warnings.append(dict(employee_id=eid,code='DOCUMENT_IDENTITY_UNAVAILABLE',fact_id=c.get('source_fact_id')))
                else:
                    hashes.add(doc['source_sha256'].strip())
            else:
                forecast_people.add(eid)
                pairs.add((eid,object_key))
    known={p['id'] for p in positions}
    rows=[staffing_row(p,sum(pid==p['id'] for pid in working.values()) if matrix['formed'] else None) for p in positions]
    unmatched=sum(pid not in known for pid in working.values())
    if unmatched:
        rows.append(staffing_row(dict(id=None,name='Должность не определена',planned_count=0),unmatched))
        warnings.append(dict(code='POSITION_UNKNOWN',count=unmatched))
    total=len(working) if matrix['formed'] else None
    staff_total=staffing_row(dict(id=None,name='Итого по всем должностям',planned_count=sum(p['planned_count'] for p in positions)),total)
    production=None
    if matrix['formed']:
        confirmed=None if incomplete else len(hashes)
        forecast=len(pairs)
        reports=None if confirmed is None else confirmed+forecast
        with_reports=len(confirmed_people|forecast_people)
        source='MIXED' if confirmed_people and forecast_people else 'FACT' if confirmed_people else 'PLAN' if forecast_people else 'NONE'
        production=dict(total=total,reports=reports,confirmed_reports=confirmed,forecast_reports=forecast,
                        objects=len(objects),with_reports=with_reports,confirmed_specialists=len(confirmed_people),
                        forecast_specialists=len(forecast_people),without_reports=total-with_reports,
                        average=None if not with_reports or reports is None else round(reports/with_reports,2),
                        confirmed_average=round(confirmed/len(confirmed_people),2) if confirmed_people and confirmed is not None else None,
                        forecast_average=round(forecast/len(forecast_people),2) if forecast_people else None,source=source)
    else:
        warnings.append(dict(code='LUVR_MONTH_NOT_FORMED'))
    return dict(date=day,formed=matrix['formed'],staffing=rows,staffing_total=staff_total,production=production,warnings=warnings)


def get_analysis(target):
    dates=[target-timedelta(days=i) for i in range(7,0,-1)]+[target]
    positions=sorted(get_positions(),key=lambda p:(POSITION_PRIORITY.get(normalized_name(p['name']),len(POSITION_PRIORITY)),normalized_name(p['name']),p['id']))
    matrices={key:calculate_month(*key) for key in sorted({(d.year,d.month) for d in dates})}
    days={d.isoformat() for d in dates}
    ids={c['source_fact_id'] for m in matrices.values() for e in m['employees'] for r in e['rows']
         for day,c in r['cells'].items() if day in days and c.get('source')=='FACT' and c.get('source_fact_id') is not None}
    documents=load_document_keys(ids)
    points=[analyze_day(d,matrices[(d.year,d.month)],positions,documents) for d in dates]
    limitations=list(LIMITATIONS)
    if any(c.get('entity_id') is not None for m in matrices.values() for e in m['employees'] for r in e['rows'] for c in r['cells'].values()):
        limitations[-1]='Прогноз: один отчёт на пару сотрудник–сущность контроля в день; общий родитель не объединяет разные сущности, ПО и категории не увеличивают число.'
    return dict(**points[-1],history=points[:-1],window=dict(date_from=dates[0].isoformat(),date_to=dates[-2].isoformat()),limitations=limitations)
