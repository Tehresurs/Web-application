"""Contract report projection. Calendar and object allocation belong to the matrix."""
from app.services.production_matrix import calculate_month
from app.repositories.deployment import employee_details

HEADERS = [
    '№ п/п', 'Наименование объектов', 'Наименование ПО / Субподрядчик',
    'ФИО закреплённого специалиста СК, номер и дата распоряжения о закреплении',
    'Оснащение специалиста ТН', 'Телефон', 'Закреплённое транспортное средство',
]
TITLE = 'Отчет-расстановка специалистов строительного контроля'
SUBTITLE = 'ООО «Техресурс» на объектах строительства ООО «СПД»'
MONTHS = ('января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря')
POSITION_ORDER = (
    'Инженер СК (общестроительные работы, сварочные технологии)',
    'Инженер СК (общестроительные работы)',
    'Инженер СК (электромонтажные работы, КИПиА)',
    'Инженер СК (ТА)',
    'Инженер НК,УЗК',
    'Инженер ОЗОТОБОС',
    'Инженер СК (Геодезические работы)',
    'Инженер ПТО СПД СГМ',
    'Инженер ПТО СГМ',
    'Инженер ПТО Тюмень',
    'Инженер СПД Тюмень',
    'Инженер СПД Москва',
    'Инженер СК (Геологоизыскательские работы)',
    'Ведущий инженер СК',
)


def normalized_name(value):
    return ' '.join((value or '').split()).casefold()


POSITION_PRIORITY = {normalized_name(name): index for index, name in enumerate(POSITION_ORDER)}


def report_row_order(row):
    # Position names come from the matrix's existing positions JOIN.
    position = normalized_name(row.get('position_name'))
    priority = POSITION_PRIORITY.get(position, len(POSITION_ORDER))
    return (priority, position, normalized_name(row['employee_name']).replace('ё', 'е'), row['employee_id'])


def date_label(target):
    return f'на «{target.day:02}» {MONTHS[target.month-1]} {target.year} г.'


def build_report(target, matrix, details):
    day = target.isoformat()
    report = dict(date=day, date_label=date_label(target), title=TITLE, subtitle=SUBTITLE,
                  formed=matrix['formed'], headers=HEADERS, rows=[], totals=None, warnings=[])
    if not matrix['formed']:
        report['warnings'].append(dict(code='LUVR_MONTH_NOT_FORMED', message='ЛУВР на выбранный месяц не сформирован. Численность не определена.'))
        return report
    objects, organizations, people = set(), set(), set()
    for employee in matrix['employees']:
        eid = employee['employee_id']
        cells = [row['cells'][day] for row in employee['rows'] if day in row['cells']]
        facts = [cell for cell in cells if cell['source'] == 'FACT']
        selected = facts or [cell for cell in cells if cell['source'] == 'PLAN']
        calendar = next((d for d in employee['luvr_days'] if str(d['date']) == day), None)
        check = next((c for c in employee['checks'] if c['date'] == day), {})
        def warn(code, message, **extra):
            report['warnings'].append(dict(code=code, employee_id=eid, employee_name=employee['full_name'], message=message, **extra))
        if not calendar:
            warn('CALENDAR_MISSING', 'Нет итогового расчёта ЛУВР на выбранную дату.')
            continue
        if check.get('status') in ('WARNING', 'CONFLICT'):
            warn(check['status'], 'Матрица содержит неполные или противоречивые данные.', details=check.get('warnings', []))
        if calendar['final_code'] not in ('FULL', 'HALF'):
            if facts and calendar['final_code']!='TRAVEL':
                warn('FACT_ON_NONWORKING_DAY', 'Подтверждённая объектная работа противоречит ЛУВР; сотрудник не включён в обычную расстановку.', facts=facts, luvr_code=calendar['final_code'])
            continue
        info = details.get(eid, {})
        transport = '\n'.join(str(info.get(k) or '') for k in ('vehicle_make', 'vehicle_plate', 'driver_full_name', 'driver_phone') if info.get(k))
        if not info.get('phone') or not transport:
            warn('CONTACTS_INCOMPLETE', 'Не заполнены телефон сотрудника или сведения о транспорте.')
        if not selected:
            warn('ASSIGNMENT_UNKNOWN', 'Конкретное назначение неизвестно; в форме указано «Все объекты контроля».')
        # Presentation deduplication only: preserve all source cells in each row.
        groups = {}
        for cell in selected or [None]:
            key = (cell.get('object_id'), cell.get('subobject_id'), cell.get('subcontractor_id') or cell.get('po_id')) if cell else (None, None, None)
            if cell and cell.get('entity_id') is not None:key=('entity',cell['entity_id'],key[2])
            groups.setdefault(key, []).append(cell)
        for (_, _, organization_id), sources in groups.items():
            cell = sources[0] or {}
            object_id,subobject_id=cell.get('object_id'),cell.get('subobject_id')
            concrete=object_id is not None or cell.get('entity_id') is not None
            name = cell.get('object_name') or '' if concrete else 'Все объекты контроля'
            if cell.get('subobject_name'):
                name += '\n' + cell['subobject_name']
            organization = (cell.get('subcontractor_name') if cell.get('subcontractor_id') else cell.get('po_name')) or ''
            if concrete:
                objects.add(('entity',cell['entity_id']) if cell.get('entity_id') is not None else object_id)
                if not organization_id or not organization:
                    warn('ORGANIZATION_MISSING', 'Для объекта не заполнены ПО / субподрядчик.', object_id=object_id)
            if organization_id is not None:
                organizations.add(organization_id)
            people.add(eid)
            report['rows'].append(dict(number=len(report['rows'])+1, employee_id=eid,
                object_id=object_id, subobject_id=subobject_id, object_name=name,
                organization_id=organization_id, organization_name=organization,
                employee_name=employee['full_name'], position_name=cell.get('position_name',employee.get('position_name')),
                report_description=info.get('report_description') or '',
                equipment=info.get('equipment_description') or '',
                phone=info.get('phone') or '', transport=transport,
                source=cell.get('source'), sources=[s for s in sources if s], luvr_code=calendar['final_code']))
            if cell.get('entity_id') is not None:
                report['rows'][-1].update({k:cell[k] for k in ('entity_id','parent_entity_id','current_hierarchy')})
    report['totals'] = dict(objects=len(objects), organizations=len(organizations), specialists=len(people))
    # Stable sort keeps the existing object order within each employee.
    report['rows'].sort(key=report_row_order)
    for number, row in enumerate(report['rows'], 1):
        row['number'] = number
    return report


def get_report(target):
    matrix = calculate_month(target.year, target.month)
    details = employee_details([e['employee_id'] for e in matrix['employees']]) if matrix['formed'] else {}
    return build_report(target, matrix, details)
