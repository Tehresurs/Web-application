"""B3 orchestration: existing B2 -> existing native Excel COM -> verified archive."""
from datetime import datetime, timezone
import json
from pathlib import Path
from threading import Lock
from uuid import uuid4
from zipfile import ZipFile
import xml.etree.ElementTree as ET
from app.services import vou_data, vou_excel_com as com, vou_settings
from app.services.vou_layout import build_plan
from app.services.vou_archive import VouArchive
from app.services.vou_dk_display import empty_dk_rows

_LOCK=Lock()


def equal(actual,expected):
    if expected is None:return actual in (None,'')
    if type(expected) in (int,float):
        return type(actual) in (int,float) and abs(actual-expected)<0.0000001
    return actual==expected


def verify_workbook(path,data,plan,result,pdf):
    fresh=result['fresh_excel']
    if not fresh.get('reopened') or not fresh.get('excel_process_exited'):
        raise ValueError('Не подтверждено повторное открытие Excel')
    grid=fresh['readback_blocks'][plan['readback_range']]
    blank_days=0
    for item in plan['rows']:
        index=item['row']-14
        for day_index,(day,cents) in enumerate(item['days_cents'].items()):
            expected=cents/100 if cents else None
            if not equal(grid[index][day_index+4],expected):
                raise ValueError(f"Дневная ячейка не совпадает с Б2: сотрудник {item['employee_id']}, {day}")
            if cents==0:blank_days+=1
    # All AL body cells, including category totals, must be truly empty.
    if any(line[36] not in (None,'') for line in grid):
        raise ValueError('Колонка AL содержит значения')
    for address,expected in plan['expected'].items():
        cell=fresh['readback'][address]
        if not equal(cell['value'],expected):
            raise ValueError(f'Значение Excel не совпадает с ожидаемым: {address}')
    original=com.inventory(com.MASTER)
    current=result['inventory']
    if current['vba_streams']!=original['vba_streams']:raise ValueError('Изменился VBA')
    if set(current['sheets'])!=set(original['sheets']):raise ValueError('Изменился состав листов')
    if len(current['drawings'])!=len(original['drawings']) or len(current['controls'])!=len(original['controls']):
        raise ValueError('Изменился состав рисунков/элементов управления')
    with ZipFile(com.MASTER) as source,ZipFile(path) as book:
        media=[name for name in source.namelist() if name.startswith('xl/media/')]
        if media!=[name for name in book.namelist() if name.startswith('xl/media/')]:
            raise ValueError('Изменился состав изображений')
        for name in media:
            if source.read(name)!=book.read(name):raise ValueError('Изменилось изображение '+name)
        sheet=ET.fromstring(book.read(current['sheets']['Персонал']['path']))
        cells={c.get('r'):c for c in sheet.findall('m:sheetData/m:row/m:c',com.NS)}
        for address,formula in plan['formulas'].items():
            element=cells[address].find('m:f',com.NS)
            if element is None or element.text!=formula[1:]:raise ValueError('Потеряна формула '+address)
        for item in plan['rows']:
            row=item['row']
            for day_index,cents in enumerate(item['days_cents'].values()):
                if cents:continue
                from app.services.vou_layout import column
                address=column(day_index+6)+str(row)
                cell=cells.get(address)
                if cell is not None and (cell.find('m:f',com.NS) is not None or
                    cell.find('m:v',com.NS) is not None or cell.find('m:is',com.NS) is not None):
                    raise ValueError('Нулевая/ДК ячейка не полностью пуста: '+address)
    if fresh['print_area']!=f"$A$1:$AL${plan['signature_row']}":
        raise ValueError('Подписи не включены в печатную область')
    from pypdf import PdfReader
    pages=PdfReader(pdf).pages
    texts=[' '.join((page.extract_text() or '').split()) for page in pages]
    if not pages or any(len(text)<20 for text in texts):raise ValueError('Обнаружена пустая страница PDF')
    all_text=' '.join(texts)
    for marker in ('6.1','6.2','6.3','6.4','ИТОГО','Представитель','Генеральный'):
        if marker not in all_text:raise ValueError('В PDF не найден раздел или подпись: '+marker)
    for name in plan['signer_names']:
        if ' '.join(name.split()) not in all_text:raise ValueError('В PDF обрезано ФИО подписанта')
    for page in pages:
        if abs(float(page.mediabox.width)-841.9)>1 or abs(float(page.mediabox.height)-595.3)>1:
            raise ValueError('Неверный формат страницы контрольного PDF')
    return dict(excel_reopened=True,preservation_accepted=True,data_totals_match=True,
        total_cents=data['total_cents'],blank_day_cells=blank_days,al_empty=True,
        template_sha256=com.sha256(com.MASTER),media_files=len(media),vba_streams=len(current['vba_streams']),
        pdf_pages=len(pages),signatures_in_print_area=True,verified_at=datetime.now(timezone.utc).isoformat())


def render(data,settings,*,technical_only=False,context=None):
    requisites=vou_settings.require_configured(settings)
    display_data,dk_controls=empty_dk_rows(data,context)
    plan=build_plan(display_data,requisites,technical_only=technical_only)
    token=uuid4().hex
    prefix='B3_TECHNICAL' if technical_only else 'VOU'
    destination=com.OUTPUT/f"{prefix}_{data['year']}_{data['month']:02d}_{token}.xlsm"
    pdf=destination.with_suffix('.pdf')
    result=com.fill_copy(destination,plan['operations'],readback=list(plan['expected']),
        readback_ranges=[plan['readback_range']],calculate_personnel=True,timeout=240,
        technical_only=technical_only,control_pdf=pdf)
    checks=verify_workbook(destination,data,plan,result,pdf)
    dk_cells=[]
    from app.services.vou_layout import column
    grid=result['fresh_excel']['readback_blocks'][plan['readback_range']]
    for control in dk_controls:
        row=next(r for r in plan['rows'] if r['employee_id']==control['employee_id'] and
                 r['matrix_row_key']==control['matrix_row_key'] and r['category_id']==control['category_id'])
        index=int(control['date'][-2:])-1
        value=grid[row['row']-14][index+4]
        if value not in (None,''):raise ValueError('Ячейка ДК не пуста')
        dk_cells.append(dict(**control,address=column(index+6)+str(row['row']),value=value))
    checks['dk_cells']=dk_cells
    checks['technical_only']=bool(technical_only)
    checks['com']=result
    audit=dict(data=data,settings=requisites,layout={k:v for k,v in plan.items() if k!='operations'},verification=checks)
    destination.with_suffix('.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
    return destination,pdf,checks


def generate(year,month):
    if not _LOCK.acquire(blocking=False):raise ValueError('Формирование ВОУ уже выполняется. Дождитесь завершения.')
    try:
        # Snapshot only user-saved requisites BEFORE reading data/starting Excel.
        settings=vou_settings.require_configured(vou_settings.get_settings())
        data,context=vou_data.prepare_month(year,month,with_context=True)
        path,pdf,checks=render(data,settings,context=context)
        item=VouArchive().publish(path,data=data,settings=settings,verification=checks)
        return dict(item=item,warnings=data['warnings'],pdf_path=str(pdf))
    finally:_LOCK.release()
