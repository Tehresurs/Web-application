from calendar import monthrange
from copy import deepcopy
from datetime import date
from hashlib import sha256
from io import BytesIO
import os,re,unittest
from zipfile import ZipFile
from unittest.mock import patch
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from app.services.luvr_export import DEFAULT_TEMPLATE,HEADER_CELLS
from app.services.luvr_export_table import render_table,export_table_month,VALUES
from app.services.luvr_month import calendar_totals,calendar_day_totals,month_calendar
from app.repositories import luvr_month
from app.api.luvr_month import OrderedExportRequest,download_ordered_month
import test_luvr_month
from test_luvr_export import snapshot
from test_daily_control import http_request


def data_set(count=2,year=2026,month=10):
    employees=[]
    codes=['FULL','FULL','HALF','HALF','TRAVEL','TRAVEL','OFF_SHIFT','DOWNTIME','DISMISSED','EMPTY']
    for i in range(count):
        days=[dict(date=date(year,month,d),final_code=codes[d-1] if d<=len(codes) else 'EMPTY',
                   auto_code='FULL',is_sick=d==11,manually_changed=d==8,final_source_type='OVERRIDE')
              for d in range(1,monthrange(year,month)[1]+1)]
        employees.append(dict(employee_id=i+10,full_name=f'Сотрудник {i}',position_name=f'Должность {i}',
                              specialty='ОС',nrs_number='НРС-007' if i==0 else None,days=days,totals=calendar_totals(days)))
    return dict(year=year,month=month,formed=True,employees=employees,day_totals=calendar_day_totals(employees,year,month))


def book(data,ids=None):
    header=snapshot(data['month']);header['year']=data['year']
    return load_workbook(BytesIO(render_table(header,data,ids))).active


class ExportTableTests(unittest.TestCase):
    def test_metadata_number_and_order(self):
        data=data_set();sheet=book(data,[11,10])
        self.assertEqual([sheet.cell(9,c).value for c in range(1,6)],[1,'Сотрудник 1','Должность 1','Нет','ОС'])
        self.assertEqual([sheet.cell(10,c).value for c in range(1,6)],[2,'Сотрудник 0','Должность 0','НРС-007','ОС'])

    def test_all_final_values_and_sickness(self):
        data=data_set();sheet=book(data)
        for day in data['employees'][0]['days']:
            self.assertEqual(sheet.cell(9,day['date'].day+5).value,VALUES[day['final_code']])
        self.assertEqual(sheet['H9'].value,.5);self.assertEqual(sheet['H9'].data_type,'n')
        self.assertEqual(sheet['M9'].value,'П');self.assertIsNone(sheet['P9'].value)

    def test_totals_match_final(self):
        sheet=book(data_set())
        self.assertEqual([sheet.cell(9,c).value for c in (37,38,39)],[3,1,2])
        self.assertEqual([sheet.cell(85,c).value for c in (37,38,39)],[6,2,4])
        self.assertEqual(sheet['F85'].value,2);self.assertEqual(sheet['H85'].value,1)
        self.assertEqual(sum(sheet.cell(85,c).value or 0 for c in range(6,37)),sheet['AK85'].value)
        self.assertEqual(sum(sheet.cell(r,37).value or 0 for r in range(9,85)),sheet['AK85'].value)

    def test_unused_rows_cleared_and_styles_preserved(self):
        sheet=book(data_set(1));master=load_workbook(DEFAULT_TEMPLATE).active
        for row in range(10,85):
            for col in range(1,40):
                self.assertIsNone(sheet.cell(row,col).value)
                self.assertEqual(sheet.cell(row,col)._style,master.cell(row,col)._style)

    def test_missing_specialty_blocks_all_empty_variants(self):
        for value in (None,'','   '):
            data=data_set();data['employees'][0]['specialty']=value
            with self.assertRaisesRegex(ValueError,'Сотрудник 0'):book(data)

    def test_nrs_empty_variants_not_errors(self):
        for value in (None,'','   '):
            data=data_set(1);data['employees'][0]['nrs_number']=value
            self.assertEqual(book(data)['D9'].value,'Нет')

    def test_order_missing_foreign_duplicate_and_wrong_type_rejected(self):
        for ids in ([10],[10,999],[10,10],[10,11,11],['10',11],[True,11],[]):
            with self.assertRaisesRegex(ValueError,'Порядок'):book(data_set(),ids)

    def test_fallback_retains_existing_order_no_sort(self):
        data=data_set();data['employees'].reverse();self.assertEqual(book(data)['B9'].value,'Сотрудник 1')

    def test_more_than_template_capacity_expands_rows_without_changing_master(self):
        before=sha256(DEFAULT_TEMPLATE.read_bytes()).hexdigest()
        sheet=book(data_set(77))
        self.assertEqual(sheet['A85'].value,77)
        self.assertEqual(sheet['B85'].value,'Сотрудник 76')
        self.assertEqual(sheet['E86'].value,'Итого')
        self.assertEqual(before,sha256(DEFAULT_TEMPLATE.read_bytes()).hexdigest())
        self.assertEqual(book(data_set(76))['A84'].value,76)

    def test_real_month_lengths(self):
        for year,month,days in [(2026,2,28),(2028,2,29),(2026,4,30),(2026,10,31)]:
            sheet=book(data_set(1,year,month))
            for day in range(1,days+1):self.assertEqual(sheet.cell(8,day+5).value.date(),date(year,month,day))
            for day in range(days+1,32):
                for row in (8,9,85):self.assertIsNone(sheet.cell(row,day+5).value)

    def test_inconsistent_totals_rejected(self):
        data=data_set();data['day_totals'][0]['work_equivalent']+=1
        with self.assertRaisesRegex(ValueError,'не совпадают'):book(data)

    def test_outside_table_and_master_unchanged(self):
        before=DEFAULT_TEMPLATE.read_bytes();data=data_set();unchanged=deepcopy(data)
        output=render_table(snapshot(),data)
        allowed=set(HEADER_CELLS)|{f'{get_column_letter(c)}{r}' for r in range(9,85) for c in range(1,40)}|{f'{get_column_letter(c)}{r}' for r in (8,85) for c in range(6,40) if r==85 or c<37}
        cell_pattern=r'<c\b[^>]*\br="([A-Z]+[0-9]+)"[^>]*?(?:/>|>.*?</c>)'
        def strip(xml):return re.sub(cell_pattern,lambda m:'' if m.group(1) in allowed else m.group(),xml.decode(),flags=re.S)
        with ZipFile(BytesIO(before)) as master,ZipFile(BytesIO(output)) as result:
            for name in master.namelist():
                a,b=master.read(name),result.read(name)
                self.assertEqual(strip(a),strip(b),name) if name=='xl/worksheets/sheet1.xml' else self.assertEqual(a,b,name)
        a,b=load_workbook(BytesIO(before)).active,load_workbook(BytesIO(output)).active
        for row in a:
            for cell in row:self.assertEqual(cell._style,b[cell.coordinate]._style)
        self.assertEqual(str(a.merged_cells),str(b.merged_cells));self.assertEqual(a.page_setup,b.page_setup)
        self.assertEqual(str(a.print_area),str(b.print_area));self.assertEqual(data,unchanged)
        self.assertEqual(sha256(before).hexdigest(),sha256(DEFAULT_TEMPLATE.read_bytes()).hexdigest())

    def test_api_order_contract(self):
        with patch('app.api.luvr_month.export_month',return_value=b'xlsx') as export:
            response=download_ordered_month(OrderedExportRequest(year=2026,month=10,employee_ids=[11,10]))
            export.assert_called_once_with(2026,10,[11,10]);self.assertEqual(response.status_code,200)
            self.assertIn('LUVR_2026-10.xlsx',response.headers['content-disposition'])


@unittest.skipUnless(os.getenv('DAILY_CONTROL_TEST_DB')=='1','Requires isolated PostgreSQL tests')
class ExportTableDatabaseTests(unittest.TestCase):
    def setUp(self):
        test_luvr_month.MonthApiTests.setUp(self)
        self.conn.execute("UPDATE positions SET specialty='ОС'")
        self.conn.execute('UPDATE employees SET position_id=9001 WHERE position_id IS NULL')

    def test_membership_changes_and_stale_order_rejected(self):
        luvr_month.form_month(2026,10);data=month_calendar(2026,10);ids=[e['employee_id'] for e in data['employees']]
        before=load_workbook(BytesIO(export_table_month(2026,10,ids))).active
        self.assertEqual(before['B9'].value,data['employees'][0]['full_name'])
        removed=ids[0];luvr_month.change_member(2026,10,removed,remove=True)
        with self.assertRaises(ValueError):export_table_month(2026,10,ids)
        reduced=load_workbook(BytesIO(export_table_month(2026,10,ids[1:]))).active
        self.assertIsNone(reduced.cell(8+len(ids),2).value)
        luvr_month.change_member(2026,10,removed)
        restored=load_workbook(BytesIO(export_table_month(2026,10,list(reversed(ids))))).active
        self.assertEqual(restored['B9'].value,data['employees'][-1]['full_name'])

    def test_final_override_sickness_and_snapshot(self):
        self.conn.execute("INSERT INTO employee_movements(employee_id,movement_type,transport_type,event_datetime) VALUES(2,'ARRIVAL','SELF','2026-10-01 07:00')")
        luvr_month.form_month(2026,10);snapshot_before=luvr_month.get_header_snapshot(2026,10)
        def value():
            data=month_calendar(2026,10);ids=[e['employee_id'] for e in data['employees']];sheet=load_workbook(BytesIO(export_table_month(2026,10,ids))).active
            return sheet.cell(9+ids.index(2),6).value
        self.assertEqual(value(),1)
        status,body=http_request('POST','/api/employees/2/luvr/day-overrides',dict(work_date='2026-10-01',value='DOWNTIME'))
        self.assertEqual(status,200);self.assertEqual(value(),'П')
        http_request('DELETE',f'/api/employees/2/luvr/day-overrides/{body["item"]["id"]}')
        self.assertEqual(value(),1)
        self.conn.execute("INSERT INTO employee_sick_periods(employee_id,date_from,date_to) VALUES(2,'2026-10-01','2026-10-02')")
        self.assertIsNone(value());self.assertEqual(snapshot_before,luvr_month.get_header_snapshot(2026,10))

    def test_http_errors_for_specialty_and_order(self):
        luvr_month.form_month(2026,10);ids=[e['employee_id'] for e in month_calendar(2026,10)['employees']]
        self.assertEqual(http_request('POST','/api/luvr/month/export',dict(year=2026,month=10,employee_ids=ids+[999]))[0],400)
        self.assertEqual(http_request('POST','/api/luvr/month/export',dict(year=2026,month=10,employee_ids=['2']))[0],422)
        self.conn.execute("UPDATE positions SET specialty=NULL")
        status,body=http_request('POST','/api/luvr/month/export',dict(year=2026,month=10,employee_ids=ids))
        self.assertEqual(status,400);self.assertIn('специальность',body['message'])
