"""Excel presentation of existing deployment analysis; no new calculations."""
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

METRICS = (
    ('total', 'Работающие специалисты, чел.'),
    ('reports', 'Отчёты: подтверждено + прогноз, шт.'),
    ('confirmed_reports', 'Подтверждённые отчёты, шт.'),
    ('forecast_reports', 'Прогноз отчётов, шт.'),
    ('objects', 'Уникальные объекты, шт.'),
    ('with_reports', 'Специалисты с отчётами / планом, чел.'),
    ('confirmed_specialists', 'Подтверждённые специалисты, чел.'),
    ('forecast_specialists', 'Прогнозные специалисты, чел.'),
    ('without_reports', 'Специалисты без отчётов / плана, чел.'),
    ('average', 'Средняя нагрузка на специалиста'),
    ('confirmed_average', 'Подтверждённая нагрузка'),
    ('forecast_average', 'Прогнозная нагрузка'),
)
SOURCES = {'FACT':'Подтверждено', 'PLAN':'Прогноз', 'MIXED':'FACT + PLAN',
           'NONE':'Нет объектных отчётов/плана'}


def append_analysis_sheet(book, analysis):
    from math import ceil
    from datetime import date
    from openpyxl.styles import Border, Side
    from openpyxl.chart import BarChart, LineChart, Reference
    from openpyxl.worksheet.page import PageMargins
    sheet = book.create_sheet('Анализ')
    sheet.sheet_view.showGridLines=False
    headings=set(); sections=set(); paragraphs=set(); totals=set()
    def row(values, heading=False):
        sheet.append(values)
        if heading: headings.add(sheet.max_row)
        return sheet.max_row
    def section(title):
        n=row([title],True);sections.add(n)
        sheet.merge_cells(start_row=n,start_column=1,end_row=n,end_column=9)
    def paragraph(text):
        n=row([text]);paragraphs.add(n)
        sheet.merge_cells(start_row=n,start_column=1,end_row=n,end_column=9)
    row(['Анализ расстановки',date.fromisoformat(analysis['date'])],True)
    section('Штатная численность')
    row(['Должность','План, чел.','Факт, чел.','Отклонение, чел.','Укомплектованность, %'],True)
    for item in [*analysis['staffing'],analysis['staffing_total']]:
        n=row([item.get(k) for k in ('position_name','planned','actual','deviation','completeness')])
    totals.add(n);staff_end=n
    row([]);section('Производственная расстановка')
    production=analysis.get('production') or {}
    row(['Источник',SOURCES.get(production.get('source'),'Показатели не определены')])
    for key,label in METRICS:
        n=row([label,production.get(key)])
        if 'average' in key: sheet.cell(n,2).number_format='0.00'
    row([]);section('Динамика за предыдущие семь календарных дней')
    history=analysis['history']
    history_header=row(['Показатель',*[date.fromisoformat(p['date']) for p in history]],True)
    row(['Источник',*[SOURCES.get((p.get('production') or {}).get('source'),'Нет данных') for p in history]])
    metric_rows={}
    for key,label in METRICS:
        n=row([label,*[(p.get('production') or {}).get(key) for p in history]])
        metric_rows[key]=n
        if 'average' in key:
            for c in range(2,len(history)+2):sheet.cell(n,c).number_format='0.00'
    row([]);section('Динамика общей штатной численности')
    staff_header=row(['Показатель',*[date.fromisoformat(p['date']) for p in history]],True)
    plan_row=row(['План',*[p['staffing_total'].get('planned') for p in history]])
    actual_row=row(['Факт по ЛУВР',*[p['staffing_total'].get('actual') for p in history]])
    row([]);section('Графики')
    chart_top=sheet.max_row+1
    # Charts reference only exported values, with gaps for unknown indicators.
    def line_chart(title,keys,anchor,header,rows):
        chart=LineChart();chart.title=title;chart.style=13
        chart.width=21;chart.height=10;chart.display_blanks='gap'
        chart.y_axis.title='Значение';chart.x_axis.title='Дата';chart.legend.position='b'
        for key in keys:
            chart.add_data(Reference(sheet,min_row=rows[key],max_row=rows[key],min_col=1,max_col=len(history)+1),titles_from_data=True,from_rows=True)
        chart.set_categories(Reference(sheet,min_row=header,min_col=2,max_col=len(history)+1))
        for series,color in zip(chart.series,['245DB0','20805C','D59424','8064A2']):
            series.graphicalProperties.line.solidFill=color
            series.graphicalProperties.line.width=24000
        sheet.add_chart(chart,anchor)
    if history:
        line_chart('Численность: план / факт',['plan','actual'],f'A{chart_top}',staff_header,{'plan':plan_row,'actual':actual_row})
        line_chart('Отчёты: подтверждено и прогноз',['reports','confirmed_reports','forecast_reports'],f'A{chart_top+21}',history_header,metric_rows)
        line_chart('Средняя нагрузка на специалиста',['average','confirmed_average','forecast_average'],f'A{chart_top+42}',history_header,metric_rows)
    chart=BarChart();chart.type='bar';chart.title='Штатная численность по должностям';chart.style=13
    chart.width=28;chart.height=max(12,len(analysis['staffing'])*.65);chart.legend.position='b'
    if analysis['staffing']:
        chart.add_data(Reference(sheet,min_col=2,max_col=3,min_row=3,max_row=staff_end-1),titles_from_data=True)
        chart.set_categories(Reference(sheet,min_col=1,min_row=4,max_row=staff_end-1))
        sheet.add_chart(chart,f'A{chart_top+63}')
    footer=chart_top+63+ceil(chart.height*2.1)+3
    # Reserve real row heights so charts do not overlap the following tables.
    for n in range(chart_top,footer):sheet.row_dimensions[n].height=15
    sheet.cell(footer,1,'Детальные данные')
    section('Динамика штатной численности по должностям')
    row(['Дата','Должность','План, чел.','Факт, чел.','Отклонение, чел.','Укомплектованность, %'],True)
    for point in history:
        for item in [*point['staffing'],point['staffing_total']]:
            n=row([date.fromisoformat(point['date']),*[item.get(k) for k in ('position_name','planned','actual','deviation','completeness')]])
            sheet.cell(n,6).number_format='0.00"%"'
            if item is point['staffing_total']:totals.add(n)
    row([]);section('Ограничения и пояснения')
    paragraph('Пустая ячейка показателя означает: значение не определено. Графики показывают предыдущие семь дней, без выбранной даты.')
    for text in analysis['limitations']:paragraph(text)
    row([]);section('Предупреждения')
    row(['Дата','Сотрудник (ID)','Код','Подробности'],True)
    for point in [*history,analysis]:
        for warning in point['warnings']:
            n=row([date.fromisoformat(point['date']),warning.get('employee_id'),warning['code'],str({k:v for k,v in warning.items() if k not in ('employee_id','code')})])
            sheet.merge_cells(start_row=n,start_column=4,end_row=n,end_column=9)
    thin=Side(style='thin',color='D6DFEA')
    for cells in sheet:
        for cell in cells:
            if cell.value is None:continue
            if isinstance(cell.value,str):cell.data_type='s'
            cell.font=Font(name='Calibri',size=11,bold=cell.row in headings or cell.row in totals,color='FFFFFF' if cell.row in sections else '17324D')
            cell.alignment=Alignment(vertical='center',wrap_text=True,horizontal='left' if isinstance(cell.value,str) else 'center')
            if isinstance(cell.value,date):cell.number_format='DD.MM.YYYY'
            cell.border=Border(bottom=thin)
            color='245DB0' if cell.row in sections else 'DFEAF7' if cell.row in headings or cell.row in totals else 'F3F6FA' if cell.row%2==0 else 'FFFFFF'
            cell.fill=PatternFill('solid',fgColor=color)
        n=cells[0].row
        if any(c.value is not None for c in cells):
            height=30 if n in sections else 48 if n in headings else 42
            if n in paragraphs:height=max(36,ceil(len(str(cells[0].value))/130)*16)
            if n not in headings and n not in paragraphs:
                height=max(height,16*max(ceil(len(str(c.value or ''))/(45 if c.column<=2 else 22)) for c in cells if c.value is not None))
            sheet.row_dimensions[n].height=height
    for col,width in zip('ABCDEFGHI',(48,42,22,24,25,24,24,24,24)):
        sheet.column_dimensions[col].width=width
    for n in range(4,staff_end+1):sheet.cell(n,5).number_format='0.00"%"'
    sheet.freeze_panes='B4'
    sheet.sheet_properties.pageSetUpPr.fitToPage=True
    sheet.page_setup.orientation='landscape';sheet.page_setup.paperSize=sheet.PAPERSIZE_A3
    sheet.page_setup.fitToWidth=1;sheet.page_setup.fitToHeight=0
    sheet.page_margins=PageMargins(left=.25,right=.25,top=.4,bottom=.4)
    sheet.oddFooter.center.text='Страница &P из &N'
    sheet.print_area=f'A1:I{sheet.max_row}'
