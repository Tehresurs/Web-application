"""Personnel projections consume existing cells; no DB or alternative allocations."""
import unittest
from copy import deepcopy
from datetime import date
from app.services.personnel_positions import dated_personnel,acting_label,split_luvr_rows
from app.services.vou_data import prepare_data,VouDataError
import test_vou_data as vou

class PersonnelMovementProjectionTests(unittest.TestCase):
 def employee(self,report=False):
  return {'employee_id':1,'full_name':'Synthetic','requires_daily_report':True,'personnel_context':{'legacy_history_policy':'REQUIRE_HISTORY','baseline':{'position_id':2},'periods':[{'position_id':2,'known_from':'2030-01-01','known_to':None}],'definitions':[{'id':1,'position_id':2,'known_from':'2030-01-01','definition':{'name':'Engineer','requires_daily_report':True}},{'id':2,'position_id':14,'known_from':'2030-01-01','definition':{'name':'Руководитель СК','requires_daily_report':report}}],'acting':[{'root_id':'a','position_id':14,'kind':'ASSIGN','starts_on':'2030-01-05','ends_on':'2030-01-07'}]}}
 def test_only_non_reporting_acting_position_exempts(self):
  self.assertFalse(dated_personnel(self.employee(),'2030-01-06')['engineering_report_required'])
  self.assertTrue(dated_personnel(self.employee(True),'2030-01-06')['engineering_report_required'])
 def test_expiry_requires_new_plan_but_does_not_extend_acting(self):
  value=dated_personnel(self.employee(),'2030-01-08');self.assertIsNone(value['acting_assignment']);self.assertTrue(value['return_plan_required']);self.assertTrue(value['engineering_report_required'])
 def test_explicit_end_has_linked_return_plan(self):
  e=self.employee();e['personnel_context']['acting'][0]['kind']='END'
  self.assertFalse(dated_personnel(e,'2030-01-08')['return_plan_required'])
 def test_label_does_not_duplicate_acting_prefix(self):
  self.assertEqual(acting_label('И. О. Руководителя СК'),'И. О. Руководителя СК');self.assertEqual(acting_label('Руководитель СК'),'И.О. Руководителя СК')
 def test_vou_uses_dated_matrix_positions_and_directory_versions(self):
  args=vou.inputs([vou.cell(position_id=2,position_name='Old',position_definition_version_id=100),vou.cell(fid=2,day='2026-10-02',position_id=3,position_name='New',position_definition_version_id=200)])
  for p in args[1]:
   if p['id']==2:p['_definitions']={100:{'aos_description':'Historical A'}}
   if p['id']==3:p['_definitions']={200:{'aos_description':'Historical B'}}
  original=deepcopy(args);r=prepare_data(*args);rows=r['sections'][0]['rows'];self.assertEqual(r['total_cents'],200);self.assertEqual([x['position_id'] for x in rows],[2,3]);self.assertEqual([x['aos_description'] for x in rows],['Historical A','Historical B']);self.assertEqual(args,original)
 def test_vou_ta_unapproved_mapping_remains_refusal(self):
  args=vou.inputs([vou.cell(position_id=16)]);self.assertIn(16,[p['id'] for p in args[1]])
  with self.assertRaises(VouDataError) as caught:prepare_data(*args)
  self.assertEqual(caught.exception.code,'POSITION_ORDER_NOT_AGREED')
 def test_luvr_partition_preserves_sickness_and_work_total(self):
  from app.services.luvr_month import calendar_totals,calendar_day_totals
  days=[{'date':date(2030,1,d),'final_code':'FULL' if d!=6 else 'EMPTY','final_display':'1' if d!=6 else '','auto_code':'FULL','auto_display':'1','is_sick':d==6,'manually_changed':False,'final_source_type':'SICK' if d==6 else 'MOVEMENT','warnings':[]} for d in range(1,32)]
  row={'employee_id':1,'full_name':'Synthetic','days':days};original=deepcopy(row);rows=split_luvr_rows(row,self.employee())
  self.assertEqual(sum(calendar_totals(r['days'])['work_days_total'] for r in rows),30);self.assertEqual(sum(calendar_totals(r['days'])['sick_days_count'] for r in rows),1);self.assertEqual(calendar_day_totals(rows,2030,1),calendar_day_totals([row],2030,1));self.assertEqual(row,original)
