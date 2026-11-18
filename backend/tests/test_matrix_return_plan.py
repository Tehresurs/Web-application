import unittest
from datetime import date
from unittest.mock import patch

from app.services.production_matrix import employee_matrix
from app.services.production_assignments import movement_revision


class ReturnPlanMatrixTests(unittest.TestCase):
    def calculate(self, assignment_from):
        item = dict(id=101, object_id=7, po_id=1, category_id=1,
                    initial_category_id=1, initial_control_mode='INSPECTION')
        fact = dict(id=301, report_date='2030-01-08', object_id=7, po_id=1,
                    category_id=1, source_file='report.docx')
        movement = {
            'id': 5, 'employee_id': 1, 'movement_type': 'ARRIVAL',
            'transport_type': 'SELF', 'event_datetime': '2030-01-01T07:00',
        }
        employee = {
            'employee_id': 1,
            'full_name': 'Synthetic',
            'position_id': 2,
            'position_name': 'Инженер СК',
            'requires_daily_report': True,
            'default_control_mode': 'INSPECTION',
            'personnel_context': {
                'legacy_history_policy': 'REQUIRE_HISTORY',
                'baseline': {'position_id': 2},
                'periods': [{'position_id': 2, 'known_from': '2030-01-01', 'known_to': None}],
                'definitions': [
                    {'id': 1, 'position_id': 2, 'known_from': '2030-01-01',
                     'definition': {'name': 'Инженер СК', 'requires_daily_report': True}},
                    {'id': 2, 'position_id': 14, 'known_from': '2030-01-01',
                     'definition': {'name': 'Руководитель СК', 'requires_daily_report': False}},
                ],
                'acting': [{
                    'root_id': 'acting-1', 'position_id': 14, 'kind': 'ASSIGN',
                    'starts_on': '2030-01-05', 'ends_on': '2030-01-07',
                }],
            },
            'production': {
                'id': 1, 'employee_id': 1, 'dismissal_date': None,
                'work_location': 'FIELD', 'work_schedule': 'SHIFT',
                'movements': [movement], 'tickets': [], 'facts': [fact],
                'changes': [{
                    'id': 11, 'employee_id': 1, 'version': 1,
                    'period_kind': 'ARRIVAL',
                    'arrival_movement_ref': 5,
                    'period_revision': movement_revision(movement),
                    'period_start': '2030-01-01', 'period_end': None,
                    'effective_from': assignment_from, 'source_kind': 'MANUAL',
                    'assignment_state': 'OBJECTS', 'items': [item],
                }],
            },
            'matrix_overrides': [],
        }
        days = [
            {'date': date(2030, 1, day), 'final_code': 'FULL',
             'calculation_status': 'CALCULATED', 'final_source_type': 'MOVEMENT',
             'warnings': []}
            for day in (8, 9, 10)
        ]
        names = {
            'construction_objects': {7: 'Object 7'},
            'construction_subobjects': {},
            'po_types': {1: 'PO 1'},
            'object_categories': {1: 'Category 1'},
        }
        with patch('app.services.production_matrix.calculate_employee_month',
                   return_value={'days': days}), \
             patch('app.services.production_matrix.resolve', return_value={'intervals': []}), \
             patch('app.services.production_matrix.projection_enabled', return_value=False):
            return employee_matrix(employee, names, 2030, 1)

    @staticmethod
    def cells(result, day):
        return [row['cells'][day] for row in result['rows'] if day in row['cells']]

    def test_return_plan_survives_fact_and_supplies_following_dates(self):
        result = self.calculate('2030-01-08')
        fact = self.cells(result, '2030-01-08')
        self.assertEqual(len(fact), 1)
        self.assertEqual(fact[0]['source'], 'FACT')
        for day in ('2030-01-09', '2030-01-10'):
            plan = self.cells(result, day)
            self.assertEqual(len(plan), 1)
            self.assertEqual(plan[0]['source'], 'PLAN')
            self.assertEqual(plan[0]['source_fact_id'], 301)

    def test_pre_acting_assignment_does_not_count_as_return_plan(self):
        result = self.calculate('2030-01-01')
        self.assertEqual(self.cells(result, '2030-01-08')[0]['source'], 'FACT')
        self.assertEqual(self.cells(result, '2030-01-09'), [])
        check = next(item for item in result['checks'] if item['date'] == '2030-01-09')
        self.assertIn('ASSIGNMENT_UNKNOWN', check['warnings'])


if __name__ == '__main__':
    unittest.main()
