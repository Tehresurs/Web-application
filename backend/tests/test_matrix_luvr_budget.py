import unittest
from datetime import date
from unittest.mock import patch
from app.services.production_matrix import employee_matrix

class LuvrBudgetTests(unittest.TestCase):
    def calculate(self,code,count,requires_report=True):
        facts=[dict(id=i+1,report_date='2026-10-01',object_id=1,po_id=1,category_id=1) for i in range(count)]
        employee=dict(employee_id=1,full_name='Test',requires_daily_report=requires_report,production=dict(facts=facts),matrix_overrides=[])
        day=dict(date=date(2026,10,1),final_code=code,calculation_status='CALCULATED',final_source_type='STATE',warnings=[])
        period=dict(effective_from='2026-10-01',effective_to=None,basis_kind='FACTS',assignment_state='OBJECTS',period_key='test',basis_id=[f['id'] for f in facts],items=facts)
        names={k:{1:'Test'} for k in ['construction_objects','construction_subobjects','po_types','object_categories']}
        with patch('app.services.production_matrix.calculate_employee_month',return_value=dict(days=[day])), \
             patch('app.services.production_matrix.project',return_value=dict(periods=[period],warnings=[])), \
             patch('app.services.production_matrix.resolve',return_value=dict(intervals=[])):
            return employee_matrix(employee,names,2026,10)
    def test_facts_distribute_exactly_the_luvr_budget(self):
        for code,budget in [('FULL',100),('HALF',50),('TRAVEL',0),('OFF_SHIFT',0),('EMPTY',0)]:
            for count in [1,2,3,7]:
                result=self.calculate(code,count);check=result['checks'][0]
                cells=[c for row in result['rows'] for c in row['cells'].values()]
                self.assertEqual(len(cells),count)
                self.assertTrue(all(c['source']=='FACT' and c['report_received'] for c in cells))
                self.assertEqual(sum(c['share_cents'] for c in cells),budget)
                self.assertEqual(check['distributed_cents'],check['available_cents'])
                self.assertEqual(check['status'],'OK')
                self.assertEqual(check['warnings'],[])
    def test_half_day_two_facts_each_get_quarter_day(self):
        result=self.calculate('HALF',2)
        self.assertEqual([c['share_cents'] for row in result['rows'] for c in row['cells'].values()],[25,25])

    def test_no_daily_report_position_is_cameral_despite_received_facts(self):
        for code,budget in [('FULL',100),('HALF',50),('TRAVEL',0),('OFF_SHIFT',0),('EMPTY',0)]:
            result=self.calculate(code,3,requires_report=False)
            cells=[c for row in result['rows'] for c in row['cells'].values()]
            self.assertEqual(result['totals']['object_cents'],0)
            self.assertEqual(result['totals']['cameral_cents'],budget)
            self.assertEqual(result['totals']['distributed_cents'],budget)
            self.assertTrue(all(c['kind']=='CAMERAL' and c['source']=='PLAN' and not c['report_received'] and not c['report_required'] for c in cells))
            self.assertEqual(len(cells),1 if budget else 0)
            self.assertEqual(result['source_warnings'],[])
