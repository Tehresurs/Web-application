"""Read-only regression against the isolated 8001 snapshot."""
import os
import unittest
from copy import deepcopy
from unittest.mock import patch
from app.repositories.production_matrix import get_inputs
from app.services.production_matrix import employee_matrix

class ApprovedPoAbsenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env=patch.dict(os.environ,APP_DB_PROFILE='test',DB_NAME='ai_excel_agent_test',DB_SCHEMA='test_construction_identity_stage46')
        cls.env.start()
        try:cls.inputs=get_inputs(2026,10,82)
        except Exception:
            cls.env.stop();raise
    @classmethod
    def tearDownClass(cls):cls.env.stop()
    def calculate(self,data):return employee_matrix(data,self.inputs['names'],2026,10)
    def target(self,result,day):return next(c for r in result['rows'] for d,c in r['cells'].items() if d==day and c.get('source_fact_id')==49)
    def test_rpo_fact_and_inherited_plan_accept_saved_absence(self):
        data=deepcopy(self.inputs['employees'][0]);before=deepcopy(data)
        result=self.calculate(data)
        self.assertIn(49,data['approved_po_absence_fact_ids'])
        for day,source in [('2026-10-14','FACT'),('2026-10-15','PLAN')]:
            cell=self.target(result,day)
            self.assertEqual((cell['category_id'],cell['control_mode'],cell['source'],cell['share_cents']),(9,'INSPECTION',source,100))
            self.assertEqual(cell['status'],'OK')
            self.assertNotIn('ASSIGNMENT_INCOMPLETE',cell['warnings'])
        self.assertEqual(data,before)
    def test_unapproved_absence_stays_incomplete_and_shares_unchanged(self):
        data=deepcopy(self.inputs['employees'][0]);approved=self.calculate(data)
        data['approved_po_absence_fact_ids']=[];unapproved=self.calculate(data)
        self.assertIn('ASSIGNMENT_INCOMPLETE',self.target(unapproved,'2026-10-14')['warnings'])
        for key in ['available_cents','object_cents','cameral_cents','distributed_cents','working_days']:
            self.assertEqual(approved['totals'][key],unapproved['totals'][key])
        for a,b in zip(approved['rows'],unapproved['rows']):
            for day,c in a['cells'].items():
                self.assertEqual({k:v for k,v in c.items() if k not in ('status','warnings')},
                                 {k:v for k,v in b['cells'][day].items() if k not in ('status','warnings')})
    def test_approved_absence_uses_inspection_default(self):
        data=deepcopy(self.inputs['employees'][0]);data['matrix_overrides']=[]
        result=self.calculate(data)
        self.assertEqual(self.target(result,'2026-10-14')['control_mode'],'INSPECTION')
        self.assertNotIn('ASSIGNMENT_INCOMPLETE',self.target(result,'2026-10-14')['warnings'])
