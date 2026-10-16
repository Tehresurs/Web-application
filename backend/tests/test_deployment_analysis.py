import unittest
import os
from datetime import date
from unittest.mock import patch
from app.services.deployment_analysis import analyze_day,get_analysis

D=date(2026,10,12)
POSITIONS=[dict(id=1,name='Инженер СК (ТА)',planned_count=2),dict(id=2,name='Другая',planned_count=0)]


def employee(eid,code='FULL',cells=(),day=D,position=1):
    return dict(employee_id=eid,position_id=position,luvr_days=[dict(date=day,final_code=code)],
                checks=[],rows=[dict(cells={day.isoformat():c}) for c in cells])


def plan(obj=1,**kw):return dict(source='PLAN',object_id=obj,**kw)
def fact(fid,obj=1):return dict(source='FACT',object_id=obj,source_fact_id=fid)
def document(eid,digest,day=D):return dict(employee_id=eid,report_date=day,source_sha256=digest)


class AnalysisTests(unittest.TestCase):
    def day(self,employees,documents=None,formed=True):
        return analyze_day(D,dict(formed=formed,employees=employees),POSITIONS,documents or {})

    def test_staff_half_zero_plan_and_missing_reports(self):
        r=self.day([employee(1,'HALF'),employee(2,position=2),employee(3,'TRAVEL'),employee(4,'OFF_SHIFT'),employee(5,'DOWNTIME')])
        self.assertEqual([(s['actual'],s['deviation'],s['completeness']) for s in r['staffing']],[(1,-1,50),(1,1,None)])
        self.assertEqual(r['staffing_total']['actual'],2)
        self.assertEqual(r['production']['without_reports'],2)
        self.assertIsNone(r['production']['average'])

    def test_mixed_example_and_employee_fact_precedence(self):
        r=self.day([employee(1,cells=[fact(1),plan(99)]),employee(2,cells=[plan(2),plan(3)])],{1:document(1,'a')})['production']
        self.assertEqual((r['reports'],r['confirmed_reports'],r['forecast_reports']),(3,1,2))
        self.assertEqual((r['with_reports'],r['objects'],r['average'],r['source']),(2,3,1.5,'MIXED'))

    def test_objects_and_people_are_unique_forecast_ignores_subobjects(self):
        r=self.day([employee(1,cells=[plan(1,subobject_id=1),plan(1,subobject_id=2),plan(2)]),employee(2,cells=[plan(1)]),employee(3,cells=[plan(None)])])['production']
        self.assertEqual((r['reports'],r['objects'],r['with_reports'],r['without_reports']),(3,2,2,1))

    def test_documents_not_matrix_row_count_and_missing_identity(self):
        employees=[employee(1,cells=[fact(1),fact(2)])]
        r=self.day(employees,{1:document(1,'a'),2:document(1,'a')})['production']
        self.assertEqual(r['confirmed_reports'],1)
        self.assertEqual(r['average'],1)
        r=self.day(employees,{1:document(1,'a')})
        self.assertIsNone(r['production']['reports'])
        self.assertIsNone(r['production']['average'])
        self.assertTrue(r['warnings'])

    def test_conflict_preserved_missing_month_not_zero(self):
        r=self.day([employee(1,'OFF_SHIFT',[fact(1)])],{1:document(1,'a')})
        self.assertEqual(r['production']['total'],0)
        self.assertEqual(r['warnings'][0]['code'],'FACT_ON_NONWORKING_DAY')
        r=self.day([],formed=False)
        self.assertIsNone(r['production'])
        self.assertIsNone(r['staffing_total']['actual'])
        self.assertEqual(len(r['staffing']),2)

    def test_travel_reports_are_kept_in_source_but_excluded_from_accounting(self):
        from copy import deepcopy
        entries=[employee(1,'TRAVEL',[fact(1),fact(2)]),employee(2,'HALF',[fact(3)])]
        before=deepcopy(entries)
        docs={1:document(1,'a'),2:document(1,'b'),3:document(2,'c')}
        result=self.day(entries,docs)
        baseline=self.day([entries[1]],{3:docs[3]})
        self.assertEqual(result['production'],baseline['production'])
        self.assertEqual(result['staffing_total'],baseline['staffing_total'])
        self.assertEqual(result['warnings'],[])
        self.assertEqual(entries,before)
        only_travel=self.day([entries[0]])
        self.assertEqual(only_travel['production']['confirmed_reports'],0)
        self.assertEqual(only_travel['production']['reports'],0)
        self.assertEqual(only_travel['production']['objects'],0)
        self.assertIsNone(only_travel['production']['average'])
        self.assertEqual(only_travel['warnings'],[])

    def test_seven_days_cross_month_and_same_daily_calculator(self):
        target=date(2026,11,3)
        with patch('app.services.deployment_analysis.get_positions',return_value=list(reversed(POSITIONS))), \
             patch('app.services.deployment_analysis.calculate_month',return_value=dict(formed=True,employees=[])) as calc, \
             patch('app.services.deployment_analysis.load_document_keys',return_value={}):
            r=get_analysis(target)
        self.assertEqual([c.args for c in calc.call_args_list],[(2026,10),(2026,11)])
        self.assertEqual([p['date'] for p in r['history']],['2026-10-27','2026-10-28','2026-10-29','2026-10-30','2026-10-31','2026-11-01','2026-11-02'])
        self.assertEqual([s['position_id'] for s in r['staffing']],[1,2])
        for point in r['history']:
            expected=analyze_day(date.fromisoformat(point['date']),dict(formed=True,employees=[]),POSITIONS,{})
            self.assertEqual(point,expected)

    def test_api(self):
        from test_daily_control import http_request
        with patch('app.api.deployment.get_analysis',return_value=self.day([])):
            status,body=http_request('GET','/api/deployment/analysis',query='date=2026-10-12')
            self.assertEqual(status,200)
            self.assertEqual(body['item']['production']['total'],0)
        for value in ('bad','0001-01-01'):
            self.assertEqual(http_request('GET','/api/deployment/analysis',query='date='+value)[0],422)


@unittest.skipUnless(os.getenv('DAILY_CONTROL_TEST_DB')=='1','Requires isolated PostgreSQL')
class AnalysisIntegrationTests(unittest.TestCase):
    def setUp(self):
        import test_deployment
        from contextlib import contextmanager
        test_deployment.DeploymentIntegrationTests.setUp(self)
        @contextmanager
        def connection():
            with self.conn.transaction():yield self.conn
        mock=patch('app.services.deployment_analysis.get_connection',connection)
        mock.start();self.addCleanup(mock.stop)

    def test_existing_matrix_and_document_join_read_only(self):
        self.fact('2026-10-04',1)
        before=self.snapshot()
        r=get_analysis(date(2026,10,5))
        self.assertEqual(r['production']['forecast_reports'],1)
        self.assertEqual(r['history'][-1]['production']['confirmed_reports'],1)
        self.assertEqual(r['history'][-1]['production']['forecast_reports'],0)
        self.assertEqual(r['history'][0]['production'],None)
        self.assertEqual(before,self.snapshot())
