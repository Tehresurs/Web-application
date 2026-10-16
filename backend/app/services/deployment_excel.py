from io import BytesIO
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, Side, PatternFill
from openpyxl.worksheet.page import PageMargins
from app.services.deployment import HEADERS
from app.services.deployment_analysis_excel import append_analysis_sheet


def export_report(report, analysis=None):
    if not report['formed']:
        raise ValueError('ЛУВР на выбранный месяц не сформирован')
    book = Workbook()
    sheet = book.active
    sheet.title = 'Отчёт-расстановка'
    for row, text in enumerate(('Приложение № 21', 'к Договору № MOS/25/0008',
                                 report['title'], report['subtitle'], report['date_label']), 1):
        sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=7)
        sheet.cell(row,1,text)
        sheet.cell(row,1).alignment = Alignment(horizontal='right' if row<3 else 'center')
        sheet.cell(row,1).font = Font(name='Times New Roman',size=12,bold=row in (3,4))
    sheet.append([])
    sheet.append(HEADERS)
    for row in report['rows']:
        sheet.append([row[k] for k in ('number','object_name','organization_name','employee_name','equipment','phone','transport')])
    thin = Side(style='thin',color='808080')
    for row in sheet.iter_rows(min_row=7):
        for c in row:
            # Explicit strings prevent formulas in user-entered names and telephone numbers.
            if isinstance(c.value,str): c.data_type='s'
            c.font=Font(name='Times New Roman',size=11,bold=c.row==7)
            c.alignment=Alignment(wrap_text=True,vertical='center',horizontal='center' if c.column==1 else 'left')
            c.border=Border(left=thin,right=thin,top=thin,bottom=thin)
            c.fill=PatternFill('solid',fgColor='DFEAF7' if c.row==7 else 'F3F6FA' if c.row%2==0 else 'FFFFFF')
        sheet.row_dimensions[row[0].row].height=78 if row[0].row==7 else max(65,15*max(sum(max(1,(len(line)+23)//24) for line in str(c.value or '').split('\n')) for c in row))
    for label,key in (('Всего объектов','objects'),('Всего ПО','organizations'),('Всего специалистов СК на объектах','specialists')):
        line=sheet.max_row+1
        sheet.merge_cells(start_row=line,start_column=1,end_row=line,end_column=6)
        sheet.cell(line,1,label)
        sheet.cell(line,7,report['totals'][key])
    for col,width in zip('ABCDEFG',(7,40,30,38,28,22,38)):
        sheet.column_dimensions[col].width=width
    sheet.sheet_view.showGridLines=False
    sheet.auto_filter.ref=f'A7:G{7+len(report["rows"])}'
    for cells in sheet.iter_rows(min_row=8+len(report['rows'])):
        for c in cells:
            c.font=Font(name='Times New Roman',size=11,bold=True)
            c.fill=PatternFill('solid',fgColor='DFEAF7')
    sheet.oddFooter.center.text='Страница &P из &N'
    sheet.freeze_panes='C8'
    sheet.print_title_rows='7:7'
    sheet.print_area=f'A1:G{sheet.max_row}'
    sheet.sheet_properties.pageSetUpPr.fitToPage=True
    sheet.page_setup.orientation='landscape'
    sheet.page_setup.paperSize=sheet.PAPERSIZE_A3
    sheet.page_setup.fitToWidth=1
    sheet.page_setup.fitToHeight=0
    sheet.page_margins=PageMargins(left=.25,right=.25,top=.35,bottom=.35,header=.1,footer=.1)
    if analysis is not None:
        append_analysis_sheet(book, analysis)
    stream=BytesIO()
    book.save(stream)
    return stream.getvalue()
