import unittest
import os
from datetime import date
from app.services.deployment import build_report


DAY = '2026-10-12'


def cell(obj=1, source='PLAN', **kw):
    return dict(object_id=obj, object_name=f'Object {obj}' if obj else None,
                source=source, po_id=10 if obj else None, po_name='PO' if obj else None, **kw)


def employee(eid=1, code='FULL', cells=None):
    return dict(employee_id=eid, full_name=f'Employee {eid}',
                rows=[{'cells': {DAY: c}} for c in (cells or [])],
                luvr_days=[{'date': DAY, 'final_code': code}], checks=[])


class DeploymentTests(unittest.TestCase):
    def test_equipment_from_position_multiline_and_empty_excel(self):
        from io import BytesIO
        from openpyxl import load_workbook
        from app.services.deployment_excel import export_report
        employees=[employee(cells=[cell(),cell(2)]),employee(2,cells=[cell(None)]),employee(3)]
        matrix=dict(formed=True,employees=employees)
        value='Набор ВИК\nЛинейка\nРулетка\nПрибор\nИнструмент\nУровень'
        r=build_report(date(2026,10,12),matrix,{1:{'equipment_description':value}})
        self.assertEqual([x['equipment'] for x in r['rows']],[value,value,'',''])
        self.assertEqual(r['totals'],build_report(date(2026,10,12),matrix,{})['totals'])
        sheet=load_workbook(BytesIO(export_report(r))).active
        self.assertEqual(sheet['E8'].value,value)
        self.assertEqual(sheet['E9'].value,value)
        self.assertIsNone(sheet['E10'].value)
        self.assertTrue(sheet['E8'].alignment.wrap_text)
        self.assertGreaterEqual(sheet.row_dimensions[8].height,90)
    def report(self, *employees, formed=True):
        return build_report(date(2026,10,12), dict(formed=formed, employees=list(employees)), {})

    def test_all_fourteen_positions_and_normalization(self):
        names = [
            'Инженер СК (общестроительные работы, сварочные технологии)',
            'Инженер СК (общестроительные работы)',
            'Инженер СК (электромонтажные работы, КИПиА)', 'Инженер СК (ТА)',
            'Инженер НК,УЗК', 'Инженер ОЗОТОБОС', 'Инженер СК (Геодезические работы)',
            'Инженер ПТО СПД СГМ', 'Инженер ПТО СГМ', 'Инженер ПТО Тюмень',
            'Инженер СПД Тюмень', 'Инженер СПД Москва',
            'Инженер СК (Геологоизыскательские работы)', 'Ведущий инженер СК',
        ]
        employees = [{**employee(i+1), 'position_name':'  '+name.upper().replace(' ', '  ')+'  '}
                     for i,name in enumerate(names)]
        r=self.report(*reversed(employees))
        self.assertEqual([x['employee_id'] for x in r['rows']],list(range(1,15)))
        self.assertEqual([x['position_name'] for x in r['rows']],[e['position_name'] for e in employees])

    def test_names_ids_unknown_positions_and_employee_blocks(self):
        def person(eid,name,position):
            return {**employee(eid,cells=[cell(2),cell(1)]),'full_name':name,'position_name':position}
        people=[person(9,'Андреев А.А.','Я другая должность'),
                person(8,'Яковлев Я.Я.','А другая должность'),
                person(7,'Белов Б.Б.','Ведущий инженер СК'),
                person(4,'Андреев А.А.','Ведущий инженер СК'),
                person(2,'Андреев А.А.','Ведущий инженер СК'),
                person(6,'Андреев А.А.','А другая должность')]
        r=self.report(*people)
        self.assertEqual([x['employee_id'] for x in r['rows']],[2,2,4,4,7,7,6,6,8,8,9,9])
        self.assertEqual([x['object_id'] for x in r['rows']],[2,1]*6)
        self.assertEqual([x['number'] for x in r['rows']],list(range(1,13)))
        self.assertEqual(r['totals'],dict(objects=2,organizations=1,specialists=6))
        expected=[{k:v for k,v in row.items() if k!='number'} for p in people for row in self.report(p)['rows']]
        actual=[{k:v for k,v in row.items() if k!='number'} for row in r['rows']]
        self.assertCountEqual(actual,expected)

    def test_api_and_excel_share_sorted_rows(self):
        from unittest.mock import patch
        from io import BytesIO
        from openpyxl import load_workbook
        from test_daily_control import http_request
        from app.api.deployment import export
        employees=[{**employee(1,cells=[cell(),cell(2)]),'position_name':'Ведущий инженер СК'},
                   {**employee(2),'position_name':'Инженер СК (ТА)'}]
        with patch('app.services.deployment.calculate_month',return_value=dict(formed=True,employees=employees)), \
             patch('app.services.deployment.employee_details',return_value={}):
            status,data=http_request('GET','/api/deployment/report',query='date=2026-10-12')
            sheet=load_workbook(BytesIO(export(date(2026,10,12)).body)).active
        self.assertEqual(status,200)
        rows=data['item']['rows']
        self.assertEqual([r['employee_id'] for r in rows],[2,1,1])
        keys=('number','object_name','organization_name','employee_name','equipment','phone','transport')
        for n,row in enumerate(rows,8):
            self.assertEqual([sheet.cell(n,i+1).value or '' for i in range(7)], [row[k] or '' for k in keys])
        self.assertEqual([sheet.cell(len(rows)+8+i,7).value for i in range(3)],
                         [data['item']['totals'][k] for k in ('objects','organizations','specialists')])

    def test_one_and_multiple_objects_count_unique_people(self):
        r=self.report(employee(cells=[cell(),cell(2)]),employee(2,cells=[cell()]))
        self.assertEqual(len(r['rows']),3)
        self.assertEqual(r['totals'],dict(objects=2,organizations=1,specialists=2))

    def test_fact_priority_is_per_employee(self):
        r=self.report(employee(cells=[cell(1),cell(2,'FACT')]), employee(2,cells=[cell(3)]))
        self.assertEqual([(x['object_id'],x['source']) for x in r['rows']],[(2,'FACT'),(3,'PLAN')])

    def test_half_day_counts_person_and_missing_references_are_blank(self):
        r=self.report(employee(code='HALF',cells=[cell()]))
        self.assertEqual(r['totals']['specialists'],1)
        self.assertEqual(r['rows'][0]['phone'],'')
        self.assertEqual(r['rows'][0]['transport'],'')

    def test_no_object_and_unknown_do_not_create_fake_objects(self):
        r=self.report(employee(cells=[cell(None)]),employee(2))
        self.assertEqual(r['totals']['objects'],0)
        self.assertEqual(r['totals']['specialists'],2)
        self.assertTrue(all(x['object_name']=='Все объекты контроля' for x in r['rows']))
        self.assertTrue(any(w['code']=='ASSIGNMENT_UNKNOWN' for w in r['warnings']))

    def test_conflicting_fact_visible_in_warning_not_working_roster(self):
        for code in ('TRAVEL','OFF_SHIFT','DOWNTIME'):
            r=self.report(employee(code=code,cells=[cell(source='FACT')]))
            self.assertEqual(r['rows'],[])
            if code=='TRAVEL':
                self.assertEqual(r['warnings'],[])
            else:
                self.assertEqual(r['warnings'][-1]['facts'][0]['object_id'],1)

    def test_missing_month_is_not_zero(self):
        self.assertIsNone(self.report(formed=False)['totals'])

    def test_duplicate_presentations_keep_sources_not_duplicate_counts(self):
        r=self.report(employee(cells=[cell(),cell()]))
        self.assertEqual(len(r['rows']),1)
        self.assertEqual(len(r['rows'][0]['sources']),2)

    def test_subcontractor_takes_precedence(self):
        r=self.report(employee(cells=[cell(subcontractor_id=11,subcontractor_name='Sub')]))
        self.assertEqual(r['rows'][0]['organization_id'],11)
        self.assertEqual(r['rows'][0]['organization_name'],'Sub')

    def test_excel_contract_and_formula_safety(self):
        from io import BytesIO
        from openpyxl import load_workbook
        from app.services.deployment_excel import export_report
        from app.services.deployment import HEADERS
        r=self.report(employee(cells=[cell(),cell(2)]))
        r['rows'][0]['employee_name']='=1+1'
        sheet=load_workbook(BytesIO(export_report(r))).active
        self.assertEqual(sheet.max_column,7)
        self.assertEqual([c.value for c in sheet[7]],HEADERS)
        self.assertEqual(sheet['A5'].value,'на «12» октября 2026 г.')
        self.assertEqual(sheet['D8'].value,'=1+1')
        self.assertEqual(sheet['D8'].data_type,'s')
        self.assertEqual(sheet['G12'].value,1)

    def test_api_and_missing_month_export(self):
        from unittest.mock import patch
        from test_daily_control import http_request
        with patch('app.api.deployment.get_report',return_value=self.report(formed=False)):
            status,body=http_request('GET','/api/deployment/report',query='date=2026-10-12')
            self.assertEqual(status,200)
            self.assertIsNone(body['item']['totals'])
            status,_=http_request('GET','/api/deployment/report/export',query='date=2026-10-12')
            self.assertEqual(status,409)
        self.assertEqual(http_request('GET','/api/deployment/report',query='date=invalid')[0],422)


@unittest.skipUnless(os.getenv('DAILY_CONTROL_TEST_DB')=='1','Requires isolated PostgreSQL')
class DeploymentIntegrationTests(unittest.TestCase):
    def setUp(self):
        import test_production_matrix
        from contextlib import contextmanager
        from unittest.mock import patch
        for name in ('movement','payload','create','history','fact','snapshot'):
            setattr(self,name,getattr(test_production_matrix.ProductionMatrixTests,name).__get__(self))
        test_production_matrix.ProductionMatrixTests.setUp(self)
        self.conn.execute('ALTER TABLE positions ADD COLUMN IF NOT EXISTS report_description TEXT')
        self.conn.execute('ALTER TABLE positions ADD COLUMN IF NOT EXISTS equipment_description TEXT')
        for column in ('vehicle_make','vehicle_plate','driver_full_name','driver_phone'):
            self.conn.execute(f'ALTER TABLE crews ADD COLUMN IF NOT EXISTS {column} TEXT')
        @contextmanager
        def connection():
            with self.conn.transaction():yield self.conn
        mock=patch('app.repositories.deployment.get_connection',connection)
        mock.start();self.addCleanup(mock.stop)

    def test_real_matrix_plan_fact_half_day_and_read_only_report(self):
        from app.services.deployment import get_report
        self.conn.execute('UPDATE positions SET equipment_description=%s',('ВИК\nРулетка',))
        self.create({**self.payload('2026-10-02'),'items':[self.item,{**self.item,'object_id':2}]})
        before=self.snapshot()
        report=get_report(date(2026,10,3))
        self.assertEqual(len(report['rows']),2)
        self.assertEqual([r['equipment'] for r in report['rows']],['ВИК\nРулетка']*2)
        self.assertEqual(report['totals']['specialists'],1)
        self.assertTrue(all(r['source']=='PLAN' for r in report['rows']))
        self.assertEqual(before,self.snapshot())
        self.fact('2026-10-04',3)
        self.assertEqual(get_report(date(2026,10,4))['rows'][0]['source'],'FACT')
        self.assertEqual(get_report(date(2026,10,5))['rows'][0]['object_id'],3)
        self.movement('DEPARTURE','2026-10-06T15:00')
        half=get_report(date(2026,10,6))
        self.assertEqual(half['rows'][0]['luvr_code'],'HALF')
        self.assertEqual(half['totals']['specialists'],1)
        self.assertEqual(get_report(date(2026,10,7))['totals']['specialists'],0)
