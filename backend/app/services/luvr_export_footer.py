"""Complete the stage 2 workbook by replacing only signatures and legend."""
from io import BytesIO
import re
from zipfile import ZipFile
from openpyxl import load_workbook
from app.repositories.luvr_month import get_header_snapshot
from app.services.luvr_month import month_calendar
from app.services.luvr_export_table import render_table
from app.services.luvr_export_layout import compact_month

FOOTER_MAPPING={'E90':'developer_position_snapshot','K90':'developer_name_snapshot',
                'E93':'agreed_position_snapshot','K93':'agreed_name_snapshot'}
LEGEND_CELLS=tuple(f'A{row}' for row in range(96,102))


def export_final_month(year,month,employee_ids=None,*,row_keys=None):
    snapshot=get_header_snapshot(year,month)
    values=footer_values(snapshot)
    data=month_calendar(year,month)
    table=render_table(snapshot,data,employee_ids) if row_keys is None else render_table(snapshot,data,employee_ids,row_keys=row_keys)
    return compact_month(fill_footer(table,values),len(data['employees']))


def footer_values(snapshot):
    fields=tuple(FOOTER_MAPPING.values())+('legend_snapshot',)
    missing=[key for key in fields if not isinstance(snapshot.get(key),str) or not snapshot[key].strip()]
    if missing:raise ValueError('У сформированного месяца отсутствуют обязательные реквизиты подписей или легенды. Экспорт не выполнен.')
    lines=snapshot['legend_snapshot'].splitlines()
    if len(lines)!=6 or not all(line.strip() for line in lines):raise ValueError('В snapshot легенды должно быть ровно 6 непустых строк.')
    return {**{cell:snapshot[key] for cell,key in FOOTER_MAPPING.items()},**dict(zip(LEGEND_CELLS,lines))}


def fill_footer(table,values):
    workbook=load_workbook(BytesIO(table));sheet=workbook.active
    if not str(sheet['A90'].value).strip()=='Разработал' or not str(sheet['A93'].value).strip()=='Согласовано':
        raise ValueError('В MASTER не найдены утверждённые блоки подписей.')
    if any(cell in merged for merged in sheet.merged_cells.ranges for cell in values):
        raise ValueError('Объединения блоков подписей или легенды в MASTER изменились.')
    for cell,value in values.items():sheet[cell].value=value;sheet[cell].data_type='s'
    generated=BytesIO();workbook.save(generated)
    pattern=r'<c\b[^>]*\br="([A-Z]+[0-9]+)"[^>]*?(?:/>|>.*?</c>)'
    result=BytesIO()
    with ZipFile(BytesIO(table)) as original,ZipFile(generated) as edited,ZipFile(result,'w') as output:
        filename='xl/worksheets/sheet1.xml'
        new={m.group(1):m.group() for m in re.finditer(pattern,edited.read(filename).decode(),re.S)}
        seen=set()
        def replace(match):
            cell=match.group(1)
            if cell not in values:return match.group()
            seen.add(cell)
            opening=re.sub(r'\s+t="[^"]*"','',match.group().split('>',1)[0].rstrip('/'))
            return opening+' t="inlineStr">'+new[cell].split('>',1)[1]
        xml=re.sub(pattern,replace,original.read(filename).decode(),flags=re.S)
        # K93 is an existing blank position aligned with K90, not a stored XML cell.
        missing=set(values)-seen
        if missing-{'K93'}:raise ValueError('Область подписей или легенды MASTER изменилась.')
        if 'K93' in missing:
            row=re.search(r'(<row\b[^>]*\br="93"[^>]*>)(.*?)(</row>)',xml,re.S)
            if not row:raise ValueError('В MASTER отсутствует строка согласующего.')
            cells=row.group(2);matches=list(re.finditer(pattern,cells,re.S))
            insert_at=next((m.start() for m in matches if sheet[m.group(1)].column>11),len(cells))
            content=cells[:insert_at]+new['K93']+cells[insert_at:]
            xml=xml[:row.start(2)]+content+xml[row.end(2):]
        for entry in original.infolist():
            output.writestr(entry,xml.encode() if entry.filename==filename else original.read(entry.filename))
    return result.getvalue()
