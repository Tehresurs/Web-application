import os
import unittest
from contextlib import contextmanager
from unittest.mock import patch
from app.database.db import get_connection
from app.repositories.production_matrix import get_inputs
from app.repositories.production_matrix_overrides import upsert
from app.services.production_matrix import employee_matrix

class ControlPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,APP_DB_PROFILE='test',DB_NAME='ai_excel_agent_test',DB_SCHEMA='test_construction_identity_stage46')
        self.env.start();self.addCleanup(self.env.stop)
        self.conn=get_connection();self.addCleanup(self.conn.close);self.addCleanup(self.conn.rollback)
        self.assertEqual(self.conn.execute('select current_database(),current_schema()').fetchone(),('ai_excel_agent_test','test_construction_identity_stage46'))
        self.conn.execute('SELECT pg_advisory_xact_lock(20261007,1601)')
        @contextmanager
        def connection():yield self.conn
        for module in ['app.repositories.production_matrix','app.repositories.production_matrix_overrides']:
            mock=patch(module+'.get_connection',connection);mock.start();self.addCleanup(mock.stop)
    def matrix(self):
        data=get_inputs(2026,10,11)
        return employee_matrix(data['employees'][0],data['names'],2026,10)
    def fact(self,result,fact_id):
        return next(c for row in result['rows'] for c in row['cells'].values() if c['source']=='FACT' and c['source_fact_id']==fact_id)
    def change(self,cell,mode):
        target=cell['edit_target']
        payload={k:target[k] for k in ['scope','period_key','basis_revision','fact_id','assignment_item_id','effective_from']}
        payload.update(field_name='CONTROL_MODE',category_id=None,control_mode=mode,version=target['fields']['CONTROL_MODE']['version'])
        return upsert(11,payload)
    def test_inspection_default_and_conflicted_fact_is_editable(self):
        result=self.matrix()
        for fid in [563,564,40]:
            cell=self.fact(result,fid)
            self.assertEqual(cell['control_mode'],'INSPECTION')
            self.assertIsNotNone(cell['edit_target'])
            # Missing confirmed tickets remain a genuine period warning.
            self.assertIsNotNone(cell['edit_target'])
    def test_manual_mode_persists_to_next_fact_until_changed(self):
        before=self.matrix();self.change(self.fact(before,564),'OPERATIONAL')
        result=self.matrix()
        self.assertEqual(self.fact(result,564)['control_mode'],'OPERATIONAL')
        self.assertEqual(self.fact(result,40)['control_mode'],'OPERATIONAL')
        self.assertEqual(self.fact(result,563)['control_mode'],'INSPECTION')
        self.change(self.fact(result,40),'INSPECTION')
        after=self.matrix()
        self.assertEqual(self.fact(after,564)['control_mode'],'OPERATIONAL')
        self.assertEqual(self.fact(after,40)['control_mode'],'INSPECTION')
        for key in ['available_cents','object_cents','distributed_cents']:
            self.assertEqual(before['totals'][key],after['totals'][key])
        for fid in [563,564,40]:
            a=self.fact(before,fid);b=self.fact(after,fid)
            self.assertEqual((a['category_id'],a['share_cents']),(b['category_id'],b['share_cents']))
