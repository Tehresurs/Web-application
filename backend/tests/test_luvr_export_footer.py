from hashlib import sha256
from io import BytesIO
from pathlib import Path
import os,re,unittest
from zipfile import ZipFile
from openpyxl import load_workbook
from app.services.luvr_export_footer import FOOTER_MAPPING,LEGEND_CELLS,footer_values,fill_footer,export_final_month
from app.services.luvr_export_table import render_table
from app.services.luvr_export import DEFAULT_TEMPLATE
from app.repositories import luvr_month
from app.services.luvr_month import month_calendar
from app.database.migrate_luvr_footer import apply_migration
import test_luvr_month
from test_luvr_export import snapshot
from test_luvr_export_table import data_set
from test_daily_control import http_request

LEGEND='(1) - рабочий день\n(0,5) - половина рабочего дня\n(Д) - день в пути\n(МВ) - межвахтовый отдых\n(П) - простой\n(Уволен) - увольнение сотрудника'


def complete_snapshot():
    return {**snapshot(),'developer_position_snapshot':'Ведущий инженер - руководитель группы','developer_name_snapshot':'Аниськов В.И.',
            'agreed_position_snapshot':'Руководитель проекта СК','agreed_name_snapshot':'Тестовый согласующий','legend_snapshot':LEGEND}


class FooterTests(unittest.TestCase):
    def test_signatures_and_legend(self):
        data=complete_snapshot();table=render_table(data,data_set(),[11,10]);sheet=load_workbook(BytesIO(fill_footer(table,footer_values(data)))).active
        for cell,key in FOOTER_MAPPING.items():self.assertEqual(sheet[cell].value,data[key])
        self.assertEqual([sheet[c].value for c in LEGEND_CELLS],LEGEND.splitlines())
        self.assertEqual(sheet['A90'].value.strip(),'Разработал');self.assertEqual(sheet['A93'].value.strip(),'Согласовано')
        self.assertNotIn('прогул',' '.join(sheet[c].value for c in LEGEND_CELLS))

    def test_only_footer_changes_master_unchanged(self):
        before=sha256(DEFAULT_TEMPLATE.read_bytes()).hexdigest();data=complete_snapshot()
        table=render_table(data,data_set());final=fill_footer(table,footer_values(data));allowed=set(FOOTER_MAPPING)|set(LEGEND_CELLS)
        def strip(xml):return re.sub(r'<c\b[^>]*\br="([A-Z]+[0-9]+)"[^>]*?(?:/>|>.*?</c>)',lambda m:'' if m.group(1) in allowed else m.group(),xml.decode(),flags=re.S)
        with ZipFile(BytesIO(table)) as a,ZipFile(BytesIO(final)) as b:
            for filename in a.namelist():
                first,second=a.read(filename),b.read(filename)
                self.assertEqual(strip(first),strip(second)) if filename=='xl/worksheets/sheet1.xml' else self.assertEqual(first,second)
        a,b=load_workbook(BytesIO(table)).active,load_workbook(BytesIO(final)).active
        for row in a:
            for cell in row:
                self.assertEqual(cell.style_id,b[cell.coordinate].style_id)
                if cell.coordinate not in allowed:self.assertEqual(cell.value,b[cell.coordinate].value)
        self.assertEqual(a.page_setup,b.page_setup);self.assertEqual(str(a.print_area),str(b.print_area))
        self.assertEqual(before,sha256(DEFAULT_TEMPLATE.read_bytes()).hexdigest())

    def test_missing_snapshot_all_fields_blocked(self):
        for key in (*FOOTER_MAPPING.values(),'legend_snapshot'):
            for value in (None,'','  '):
                data=complete_snapshot();data[key]=value
                with self.assertRaises(ValueError):footer_values(data)

    def test_legend_must_fit_six_lines(self):
        for legend in ('one','\n'.join(['line']*7),'\n'.join(['line']*5+[''])):
            data=complete_snapshot();data['legend_snapshot']=legend
            with self.assertRaises(ValueError):footer_values(data)


@unittest.skipUnless(os.getenv('DAILY_CONTROL_TEST_DB')=='1','Requires isolated PostgreSQL tests')
class FooterDatabaseTests(unittest.TestCase):
    def setUp(self):
        test_luvr_month.MonthApiTests.setUp(self)
        self.conn.execute("UPDATE positions SET specialty='ОС'")
        self.conn.execute('UPDATE employees SET position_id=9001 WHERE position_id IS NULL')

    def test_api_all_settings_and_required_fields(self):
        status,body=http_request('GET','/api/luvr/month/settings');self.assertEqual(status,200);data=body['item']
        self.assertEqual(set(data),{'approver_position','approver_name','document_title','developer_position','developer_name','agreed_position','agreed_name','legend'})
        self.assertEqual(http_request('PUT','/api/luvr/month/settings',data)[0],200)
        for key in data:
            self.assertEqual(http_request('PUT','/api/luvr/month/settings',{**data,key:''})[0],422)
            self.assertEqual(http_request('PUT','/api/luvr/month/settings',{**data,key:'   '})[0],400)
        self.assertEqual(http_request('PUT','/api/luvr/month/settings',{**data,'legend':'only one line'})[0],400)

    def test_snapshot_all_footer_fields_frozen_old_and_new_month(self):
        old=luvr_month.get_settings();luvr_month.form_month(2026,10);before=luvr_month.get_header_snapshot(2026,10)
        changes={key:'Новый '+old[key] for key in ('developer_position','developer_name','agreed_position','agreed_name')}
        changes['legend']=old['legend'].replace('рабочий день','рабочий день (новый)')
        luvr_month.update_settings(**{**old,**changes});luvr_month.form_month(2026,10)
        self.assertEqual(before,luvr_month.get_header_snapshot(2026,10))
        for _ in range(2):
            sheet=load_workbook(BytesIO(export_final_month(2026,10))).active
            offset=76-len(month_calendar(2026,10)['employees'])
            for cell,key in FOOTER_MAPPING.items():
                mapped=re.sub(r'\d+',lambda m:str(int(m[0])-offset),cell)
                self.assertEqual(sheet[mapped].value,before[key])
            self.assertEqual([sheet.cell(r-offset,1).value for r in range(96,102)],old['legend'].splitlines())
        luvr_month.form_month(2026,11);new=luvr_month.get_header_snapshot(2026,11)
        for key,value in changes.items():self.assertEqual(new[key+'_snapshot'],value)
        self.assertEqual(load_workbook(BytesIO(export_final_month(2026,11))).active.cell(14+len(month_calendar(2026,11)['employees']),11).value,changes['developer_name'])
        self.assertIn('legend_snapshot',http_request('GET','/api/luvr/month/header-snapshot',query='year=2026&month=10')[1]['item'])

    def test_migration_initialization_and_repeat_safe(self):
        self.conn.execute('INSERT INTO luvr_months(year,month) VALUES(2026,10)')
        apply_migration(self.conn)
        row=self.conn.execute('SELECT developer_name_snapshot,agreed_name_snapshot,legend_snapshot FROM luvr_months WHERE month=10').fetchone()
        self.assertEqual(row[0],'Аниськов В.И.');self.assertEqual(row[1],'Тестовый согласующий');self.assertEqual(row[2],LEGEND)
        luvr_month.update_settings(**{**luvr_month.get_settings(),'developer_name':'Изменён'})
        apply_migration(self.conn)
        self.assertEqual(row,self.conn.execute('SELECT developer_name_snapshot,agreed_name_snapshot,legend_snapshot FROM luvr_months WHERE month=10').fetchone())

    def test_no_fallback_to_global_settings_on_export(self):
        luvr_month.form_month(2026,10)
        self.conn.execute('UPDATE luvr_months SET agreed_name_snapshot=NULL WHERE month=10')
        with self.assertRaisesRegex(ValueError,'отсутствуют'):export_final_month(2026,10)
        self.assertIsNone(self.conn.execute('SELECT agreed_name_snapshot FROM luvr_months WHERE month=10').fetchone()[0])

    def test_incomplete_settings_readable_but_new_month_blocked(self):
        self.conn.execute('UPDATE luvr_settings SET agreed_name=NULL')
        apply_migration(self.conn,allow_incomplete=True)
        status,body=http_request('GET','/api/luvr/month/settings')
        self.assertEqual(status,200);self.assertIsNone(body['item']['agreed_name'])
        self.assertEqual(http_request('PUT','/api/luvr/month/settings',body['item'])[0],422)
        with self.assertRaises(ValueError):luvr_month.form_month(2026,10)
        self.assertIsNone(self.conn.execute('SELECT 1 FROM luvr_months WHERE year=2026 AND month=10').fetchone())
        self.assertEqual(self.conn.execute('SELECT 1').fetchone()[0],1)

    def test_missing_name_migration_rolls_back_then_initializes_once(self):
        self.conn.execute('UPDATE luvr_settings SET agreed_name=NULL,developer_name=NULL')
        with self.assertRaises(ValueError):apply_migration(self.conn)
        self.assertIsNone(self.conn.execute('SELECT developer_name FROM luvr_settings').fetchone()[0])
        apply_migration(self.conn,'Тестовый согласующий')
        self.assertEqual(luvr_month.get_settings()['agreed_name'],'Тестовый согласующий')
