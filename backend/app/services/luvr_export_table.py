"""Stage 2 table mapping. Calendar values come only from the monthly service."""
from calendar import monthrange
from datetime import date
from io import BytesIO
import re
from zipfile import ZipFile

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from app.repositories.luvr_month import get_header_snapshot
from app.services.luvr_export import render_month
from app.services.luvr_month import month_calendar

VALUES = {'FULL':1,'HALF':0.5,'TRAVEL':'Д','OFF_SHIFT':'МВ','DOWNTIME':'П','DISMISSED':'Уволен','EMPTY':None}
TOTAL_KEYS = ('work_days_total','downtime_days_total','travel_days_total')


def export_table_month(year, month, employee_ids=None):
    snapshot=get_header_snapshot(year,month)
    data=month_calendar(year,month)
    return render_table(snapshot,data,employee_ids)


def ordered_employees(data, employee_ids):
    if not data['formed']:raise ValueError('Сначала сформируйте ЛУВР за выбранный месяц.')
    employees=data['employees']
    if len(employees)>76:
        raise ValueError(f'В утверждённом шаблоне предусмотрено 76 строк сотрудников. В сформированном ЛУВР: {len(employees)}. Экспорт не выполнен.')
    by_id={e['employee_id']:e for e in employees}
    if employee_ids is not None:
        if any(type(i) is not int or i<=0 for i in employee_ids) or len(set(employee_ids))!=len(employee_ids) or set(employee_ids)!=set(by_id):
            raise ValueError('Порядок сотрудников не соответствует составу месяца. Обновите ЛУВР и повторите экспорт.')
        employees=[by_id[i] for i in employee_ids]
    # No new sorting: omitted IDs retain the existing monthly repository order.
    missing=[e['full_name'] for e in employees if not (e.get('specialty') or '').strip()]
    if missing:raise ValueError('Невозможно сформировать Excel. У сотрудников не указана специальность:\n- '+'\n- '.join(missing))
    return employees


def render_table(snapshot,data,employee_ids=None,template=None):
    employees=ordered_employees(data,employee_ids)
    year,month=data['year'],data['month']
    if (snapshot['year'],snapshot['month'])!=(year,month):raise ValueError('Период snapshot не совпадает с месяцем ЛУВР.')
    count=monthrange(year,month)[1]
    daily={}
    for item in data['day_totals']:
        when=date.fromisoformat(item['date']) if isinstance(item['date'],str) else item['date']
        daily[when]=item['work_equivalent']
    expected={date(year,month,d) for d in range(1,count+1)}
    if set(daily)!=expected:raise ValueError('Неполные дневные итоги ЛУВР. Обновите месяц.')
    for employee in employees:
        dates=[date.fromisoformat(d['date']) if isinstance(d['date'],str) else d['date'] for d in employee['days']]
        if len(dates)!=count or set(dates)!=expected or any(d['final_code'] not in VALUES for d in employee['days']):
            raise ValueError('Неполный FINAL-календарь ЛУВР. Обновите месяц.')
    grand=[sum(e['totals'][key] for e in employees) for key in TOTAL_KEYS]
    if grand[0]!=sum(daily.values()):raise ValueError('Итоги сотрудников и дневные итоги ЛУВР не совпадают. Экспорт не выполнен.')
    header=render_month(snapshot,template)
    workbook=load_workbook(BytesIO(header));sheet=workbook.active
    if [sheet.cell(7,c).value for c in (2,3,5,37,38,39)]!=['ФИО','должность','специальность','Итого','Простой','Дорога'] or sheet['E85'].value!='Итого':
        raise ValueError('Не найдена утверждённая область таблицы MASTER.')
    values={f'{get_column_letter(c)}{r}':None for r in range(9,85) for c in range(1,40)}
    for d in range(1,32):
        values[f'{get_column_letter(d+5)}8']=date(year,month,d) if d<=count else None
        values[f'{get_column_letter(d+5)}85']=daily.get(date(year,month,d)) if d<=count else None
    for r,employee in enumerate(employees,9):
        nrs=employee.get('nrs_number')
        for c,value in enumerate([r-8,employee['full_name'],employee.get('position_name'),nrs if nrs and nrs.strip() else 'Нет',employee['specialty']],1):
            values[f'{get_column_letter(c)}{r}']=value
        for day in employee['days']:
            when=date.fromisoformat(day['date']) if isinstance(day['date'],str) else day['date']
            values[f'{get_column_letter(when.day+5)}{r}']=VALUES[day['final_code']]
        for c,key in enumerate(TOTAL_KEYS,37):values[f'{get_column_letter(c)}{r}']=employee['totals'][key]
    for c,value in enumerate(grand,37):values[f'{get_column_letter(c)}85']=value
    for address,value in values.items():
        sheet[address].value=value
        if isinstance(value,str):sheet[address].data_type='s'
    temporary=BytesIO();workbook.save(temporary)
    # Retain the original style IDs and all XML outside the permitted cells.
    cell_pattern=r'<c\b[^>]*\br="([A-Z]+[0-9]+)"[^>]*?(?:/>|>.*?</c>)'
    output=BytesIO()
    with ZipFile(BytesIO(header)) as original,ZipFile(temporary) as edited,ZipFile(output,'w') as result:
        filename='xl/worksheets/sheet1.xml'
        generated={m.group(1):m.group() for m in re.finditer(cell_pattern,edited.read(filename).decode('utf-8'),re.S)}
        seen=set()
        def replace(match):
            address=match.group(1)
            if address not in values:return match.group()
            seen.add(address)
            opening=re.sub(r'\s+t="[^"]*"','',match.group().split('>',1)[0].rstrip('/'))
            cell=generated.get(address,'')
            if values[address] is None:return opening+'></c>'
            cell_type=re.search(r'\bt="([^"]+)"',cell.split('>',1)[0])
            if cell_type:opening+=' t="'+cell_type.group(1)+'"'
            return opening+'>'+cell.split('>',1)[1]
        source=re.sub(cell_pattern,replace,original.read(filename).decode('utf-8'),flags=re.S)
        if seen!=set(values):raise ValueError('В MASTER отсутствуют подготовленные ячейки таблицы.')
        for entry in original.infolist():
            result.writestr(entry,source.encode('utf-8') if entry.filename==filename else original.read(entry.filename))
    return output.getvalue()
