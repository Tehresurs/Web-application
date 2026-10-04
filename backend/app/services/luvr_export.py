"""Stage 1: change only three header cells in a copy of the approved MASTER."""
from io import BytesIO
import os
from pathlib import Path
import re
from zipfile import ZipFile, BadZipFile
from openpyxl import load_workbook
from app.repositories.luvr_month import get_header_snapshot

DEFAULT_TEMPLATE = Path('C:/Projects/Билеты/ЛУВР ООО Салым Петролеум Девелопмент rev1.xlsx')
MONTHS = ('Январь','Февраль','Март','Апрель','Май','Июнь','Июль','Август','Сентябрь','Октябрь','Ноябрь','Декабрь')
HEADER_CELLS = ('Q2','A5','F7')


def export_month(year, month):
    return render_month(get_header_snapshot(year, month))


def render_month(snapshot, template=None):
    path=Path(template or os.environ.get('LUVR_TEMPLATE_PATH',DEFAULT_TEMPLATE))
    try:
        master=path.read_bytes()
        workbook=load_workbook(BytesIO(master))
    except (OSError, ValueError, KeyError, BadZipFile) as exc:
        raise ValueError('Не удалось прочитать утверждённый шаблон ЛУВР.') from exc
    if len(workbook.worksheets)!=1:
        raise ValueError('Структура MASTER изменилась: ожидается один лист.')
    sheet=workbook.active
    if not {'Q2:AL4','A5:AL6','F7:AJ7'}.issubset({str(r) for r in sheet.merged_cells.ranges}) or not str(sheet['Q2'].value).startswith('Утверждаю'):
        raise ValueError('В MASTER не найдены утверждённые области верхней части.')
    values={
        'Q2':f'Утверждаю\n{snapshot["approver_position_snapshot"]}\n__________________ {snapshot["approver_name_snapshot"]}',
        'A5':snapshot['document_title_snapshot'],
        'F7':f'{MONTHS[snapshot["month"]-1]} {snapshot["year"]} года',
    }
    for address,value in values.items():
        sheet[address].value=value
        sheet[address].data_type='s'
    temporary=BytesIO();workbook.save(temporary)
    # Transplant only the openpyxl-serialized values into the original ZIP.
    # Shared formulas, caches, styles and printer settings remain byte-identical.
    output=BytesIO()
    with ZipFile(BytesIO(master)) as original, ZipFile(temporary) as edited, ZipFile(output,'w') as result:
        filename='xl/worksheets/sheet1.xml'
        source=original.read(filename).decode('utf-8')
        generated=edited.read(filename).decode('utf-8')
        for address in HEADER_CELLS:
            pattern=rf'<c\b[^>]*\br="{address}"[^>]*>.*?</c>'
            old=re.search(pattern,source,re.S);new=re.search(pattern,generated,re.S)
            if not old or not new:raise ValueError(f'Не найдена ячейка шаблона {address}.')
            opening=old.group().split('>',1)[0]
            opening=re.sub(r'\s+t="[^"]*"','',opening)+' t="inlineStr">'
            content=new.group().split('>',1)[1]
            source=source[:old.start()]+opening+content+source[old.end():]
        for entry in original.infolist():
            result.writestr(entry,source.encode('utf-8') if entry.filename==filename else original.read(entry.filename))
    return output.getvalue()
