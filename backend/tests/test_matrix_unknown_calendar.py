import unittest
from datetime import date
from unittest.mock import patch
from app.services.production_matrix import employee_matrix

class UnknownCalendarTests(unittest.TestCase):
    def calculate(self,code='EMPTY',status='UNKNOWN',source='UNKNOWN',periods=None,has_fact=True):
        fact=dict(id=1,report_date='2026-09-04',object_id=1,category_id=9,po_id=1)
        employee=dict(employee_id=1,full_name='Test',production=dict(facts=[fact] if has_fact else []),matrix_overrides=[])
        day=dict(date=date(2026,9,4),final_code=code,calculation_status=status,final_source_type=source,warnings=[])
        names={key:{1:'Test',9:'RPO'} for key in ['construction_objects','construction_subobjects','object_categories','po_types']}
        with patch('app.services.production_matrix.calculate_employee_month',return_value={'days':[day]}), \
             patch('app.services.production_matrix.project',return_value={'periods':periods or [],'warnings':[]}), \
             patch('app.services.production_matrix.resolve',return_value={'intervals':[]}):
            return employee_matrix(employee,names,2026,9)
    def test_unknown_calendar_warns_without_false_nonworking_conflict(self):
        result=self.calculate();check=result['checks'][0]
        self.assertEqual(check['status'],'WARNING')
        self.assertIn('LUVR_UNKNOWN',check['warnings'])
        self.assertNotIn('FACT_ON_NONWORK_DAY',check['warnings'])
        self.assertEqual(check['available_cents'],0)
        cell=result['rows'][0]['cells']['2026-09-04']
        self.assertEqual((cell['source'],cell['source_fact_id'],cell['share_cents']),('FACT',1,0))
    def test_nonworking_day_keeps_independent_period_conflict(self):
        for code,status,source in [('OFF_SHIFT','CALCULATED','STATE'),('TRAVEL','CALCULATED','RAIL_TRAVEL'),('EMPTY','CALCULATED','SICK'),('EMPTY','UNKNOWN','SICK'),('EMPTY','CALCULATED','OVERRIDE')]:
            check=self.calculate(code,status,source)['checks'][0]
            self.assertEqual(check['status'],'CONFLICT')
            self.assertNotIn('FACT_ON_NONWORK_DAY',check['warnings'])
            self.assertIn('FACT_OUTSIDE_KNOWN_PERIOD',check['warnings'])
    def test_unknown_calendar_does_not_hide_overlapping_assignments(self):
        period=dict(effective_from='2026-09-01',effective_to=None)
        check=self.calculate(periods=[period,period])['checks'][0]
        self.assertEqual(check['status'],'CONFLICT')
        self.assertIn('OVERLAPPING_ASSIGNMENT_PERIODS',check['warnings'])

    def test_empty_calendar_and_no_matrix_entry_match(self):
        result=self.calculate(has_fact=False)
        self.assertEqual(result['rows'],[])
        check=result['checks'][0]
        self.assertEqual(check['status'],'OK')
        self.assertEqual(check['warnings'],[])
        self.assertEqual((check['available_cents'],check['distributed_cents']),(0,0))
        self.assertEqual(result['totals']['warning_days'],0)
    def test_empty_calendar_does_not_hide_existing_review_conflict(self):
        check=self.calculate(status='NEEDS_REVIEW',has_fact=False)['checks'][0]
        self.assertEqual(check['status'],'CONFLICT')
        self.assertIn('LUVR_NEEDS_REVIEW',check['warnings'])
