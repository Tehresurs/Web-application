from hashlib import sha256
from io import BytesIO
from pathlib import Path
import os,re,unittest
from zipfile import ZipFile
from unittest.mock import patch
from openpyxl import load_workbook
from app.services.luvr_export import render_month,export_month,DEFAULT_TEMPLATE,HEADER_CELLS
from app.repositories import luvr_month
from app.api.luvr_month import download_month
import test_luvr_month
from test_daily_control import http_request


def snapshot(month=10):
    return dict(year=2026,month=month,approver_position_snapshot='Директор',approver_name_snapshot='Иванов И.И.',document_title_snapshot='Заголовок\nВторая строка')


class HeaderExportTests(unittest.TestCase):
    def test_values_october_november_master_hash(self):
        before=sha256(DEFAULT_TEMPLATE.read_bytes()).hexdigest()
        for month,name in [(10,'Октябрь'),(11,'Ноябрь')]:
            result=render_month(snapshot(month));sheet=load_workbook(BytesIO(result)).active
            self.assertEqual(sheet['Q2'].value,'Утверждаю\nДиректор\n__________________ Иванов И.И.')
            self.assertEqual(sheet['A5'].value,'Заголовок\nВторая строка')
            self.assertEqual(sheet['F7'].value,f'{name} 2026 года')
        self.assertEqual(before,sha256(DEFAULT_TEMPLATE.read_bytes()).hexdigest())

    def test_only_three_cells_changed_zip_and_workbook(self):
        result=render_month(snapshot())
        with ZipFile(DEFAULT_TEMPLATE) as master,ZipFile(BytesIO(result)) as output:
            self.assertEqual(master.namelist(),output.namelist())
            for filename in master.namelist():
                a,b=master.read(filename),output.read(filename)
                if filename=='xl/worksheets/sheet1.xml':
                    for address in HEADER_CELLS:
                        pattern=rf'<c\b[^>]*\br="{address}"[^>]*>.*?</c>'.encode()
                        a=re.sub(pattern,b'',a,flags=re.S);b=re.sub(pattern,b'',b,flags=re.S)
                self.assertEqual(a,b,filename)
        a,b=load_workbook(DEFAULT_TEMPLATE).active,load_workbook(BytesIO(result)).active
        self.assertEqual(str(a.merged_cells),str(b.merged_cells))
        self.assertEqual(str(a.print_area),str(b.print_area));self.assertEqual(a.page_setup,b.page_setup)
        for row in a:
            for cell in row:
                self.assertEqual(cell._style,b[cell.coordinate]._style)
                if cell.coordinate not in HEADER_CELLS:self.assertEqual(cell.value,b[cell.coordinate].value)

    def test_text_not_formula(self):
        data=snapshot();data['document_title_snapshot']='=1+1'
        self.assertEqual(load_workbook(BytesIO(render_month(data))).active['A5'].data_type,'s')

    def test_missing_template(self):
        with self.assertRaises(ValueError):render_month(snapshot(),template='missing.xlsx')

    def test_download_contract(self):
        with patch('app.api.luvr_month.export_month',return_value=render_month(snapshot())):
            response=download_month(2026,10);self.assertEqual(response.status_code,200)
            self.assertIn('LUVR_2026-10.xlsx',response.headers['content-disposition'])
            self.assertEqual(load_workbook(BytesIO(response.body)).active['F7'].value,'Октябрь 2026 года')


@unittest.skipUnless(os.getenv('DAILY_CONTROL_TEST_DB')=='1','Requires isolated PostgreSQL tests')
class HeaderSnapshotTests(unittest.TestCase):
    def setUp(self):test_luvr_month.MonthApiTests.setUp(self)

    def test_first_form_settings_change_and_repeat_export(self):
        initial=luvr_month.get_settings();luvr_month.form_month(2026,10)
        old=luvr_month.get_header_snapshot(2026,10)
        luvr_month.update_settings(**{**initial,'approver_position':'Новая должность','approver_name':'Новый директор','document_title':'Новый\nзаголовок'})
        luvr_month.form_month(2026,10)
        self.assertEqual(old,luvr_month.get_header_snapshot(2026,10))
        for _ in range(2):
            sheet=load_workbook(BytesIO(export_month(2026,10))).active
            self.assertEqual(sheet['A5'].value,initial['document_title'])
        luvr_month.form_month(2026,11)
        self.assertEqual(luvr_month.get_header_snapshot(2026,11)['approver_name_snapshot'],'Новый директор')

    def test_get_calculation_membership_override_do_not_change_snapshot(self):
        luvr_month.form_month(2026,10);before=luvr_month.get_header_snapshot(2026,10)
        http_request('GET','/api/luvr/month',query='year=2026&month=10')
        http_request('POST','/api/employees/2/luvr/day-overrides',dict(work_date='2026-10-01',value='DOWNTIME'))
        luvr_month.change_member(2026,10,2,remove=True);luvr_month.change_member(2026,10,2)
        self.assertEqual(before,luvr_month.get_header_snapshot(2026,10))

    def test_unformed_export_does_not_create_month(self):
        with self.assertRaises(ValueError):export_month(2026,10)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM luvr_months').fetchone()[0],0)

    def test_settings_api_and_validation(self):
        status,body=http_request('GET','/api/luvr/month/settings');self.assertEqual(status,200)
        data=body['item'];data['document_title']='Изменённый\nзаголовок'
        self.assertEqual(http_request('PUT','/api/luvr/month/settings',data)[0],200)
        data['approver_name']=' ';self.assertEqual(http_request('PUT','/api/luvr/month/settings',data)[0],400)

    def test_migration_idempotence_preserves_snapshot(self):
        luvr_month.form_month(2026,10);before=luvr_month.get_header_snapshot(2026,10)
        luvr_month.update_settings(**{**luvr_month.get_settings(),'approver_position':'Другая','approver_name':'Другой','document_title':'Другой'})
        self.conn.execute(Path('app/database/migrations/010_luvr_header.sql').read_text(encoding='utf-8'))
        self.assertEqual(before,luvr_month.get_header_snapshot(2026,10))
