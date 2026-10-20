import unittest
from copy import deepcopy
from app.services.personnel_positions import position_on,PositionHistoryUnavailable
class PositionReadModelTests(unittest.TestCase):
    def setUp(self):
        self.row={'employee_id':1,'position_id':1,'position_name':'Legacy','crew_id':7,'category_id':3,'max_shift_days':30,'movements':[{'id':1}], 'personnel_context':{'legacy_history_policy':'UNRESOLVED','baseline':{'position_id':1},'periods':[{'position_id':1,'known_from':'2030-01-01','known_to':'2030-01-15'},{'position_id':2,'known_from':'2030-01-15','known_to':None}],'definitions':[{'id':1,'position_id':1,'known_from':'2030-01-01','definition':{'name':'A','work_schedule':'SHIFT','work_location':'OBJECT'}},{'id':2,'position_id':2,'known_from':'2030-01-01','definition':{'name':'B','work_schedule':'SHIFT','work_location':'OBJECT'}},{'id':3,'position_id':2,'known_from':'2030-02-01','definition':{'name':'B renamed','work_schedule':'SHIFT','work_location':'OBJECT'}}]}}
    def test_legacy_without_context_unchanged(self):
        self.assertEqual(position_on({'position_id':1},'2020-01-01'),{'position_id':1})
    def test_boundary_and_definition_version(self):
        self.assertEqual(position_on(self.row,'2030-01-14')['position_name'],'A')
        self.assertEqual(position_on(self.row,'2030-01-15')['position_name'],'B')
        self.assertEqual(position_on(self.row,'2030-02-01')['position_name'],'B renamed')
    def test_unresolved_history_refuses(self):
        with self.assertRaises(PositionHistoryUnavailable):position_on(self.row,'2029-12-31')
    def test_existing_card_is_valid_without_inventing_start_date(self):
        self.row['personnel_context']['legacy_history_policy']='LEGACY_WITH_WARNING'
        value=position_on(self.row,'2029-12-31');self.assertEqual(value['position_name'],'A');self.assertEqual(value['position_history_status'],'EXISTING_CARD');self.assertTrue(value['position_effective_start_unknown']);self.assertNotIn('position_history_warning',value)
    def test_strict_policy_refuses(self):
        self.row['personnel_context']['legacy_history_policy']='REQUIRE_HISTORY'
        with self.assertRaises(PositionHistoryUnavailable):position_on(self.row,'2029-12-31')
    def test_employee_and_sources_preserved(self):
        original=deepcopy(self.row);value=position_on(self.row,'2030-01-20')
        for key in ('employee_id','crew_id','category_id','max_shift_days','movements'):self.assertEqual(value[key],original[key])
        self.assertEqual(self.row,original)
    def test_known_period_with_missing_definition_cannot_fall_back(self):
        self.row['personnel_context']['legacy_history_policy']='LEGACY_WITH_WARNING';self.row['personnel_context']['definitions']=self.row['personnel_context']['definitions'][:1]
        with self.assertRaises(PositionHistoryUnavailable):position_on(self.row,'2030-01-20')
    def test_no_overlap_daily_resolution(self):
        values=[position_on(self.row,'2030-01-'+str(d).zfill(2))['position_id'] for d in range(1,32)]
        self.assertEqual(values.count(1),14);self.assertEqual(values.count(2),17)

    def test_new_position_missing_dated_definition_still_warns(self):
        self.row['personnel_context']['legacy_history_policy']='LEGACY_WITH_WARNING'
        self.row['personnel_context']['definitions'][1]['known_from']='2030-01-20'
        value=position_on(self.row,'2030-01-16')
        self.assertEqual(value['position_history_status'],'LEGACY_UNVERIFIED')
        self.assertIn('position_history_warning',value)

    def test_migrated_directory_definition_does_not_invalidate_backdated_transfer(self):
        self.row['personnel_context']['legacy_history_policy']='LEGACY_WITH_WARNING'
        self.row['personnel_context']['definitions'][1].update(known_from='2030-01-20',start_unknown=True)
        value=position_on(self.row,'2030-01-16')
        self.assertEqual(value['position_id'],2)
        self.assertEqual(value['position_history_status'],'EXISTING_DIRECTORY')
        self.assertTrue(value['position_effective_start_unknown'])
        self.assertNotIn('position_history_warning',value)
