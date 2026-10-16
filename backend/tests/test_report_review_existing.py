"""Addressed checks on existing 8001 schema; every data change rolls back."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.main import app
from app.database.db import get_connection
from app.repositories import report_review as rr
from app.repositories.daily_control_identity import insert
from app.services.daily_control_service import ReviewRequest,validate_review
from docx import Document

def document(path, name, employee, po='—', sub='—'):
    d=Document();t=d.add_table(rows=0,cols=4)
    for values in [('Дата','15.10.2026','Направление контроля','Качество'),('Объект',name,'',''),
                   ('Генподрядчик',po,'',''),('Субподрядчик',sub,'',''),(employee,'','',''),('Подпись','','','')]:
        for c,v in zip(t.add_row().cells,values):c.text=v
    d.add_paragraph(Path(path).name)
    d.save(path)

class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{'APP_DB_PROFILE':'test','DB_NAME':'ai_excel_agent_test','DB_SCHEMA':'test_construction_identity_stage46'})
        self.env.start();self.addCleanup(self.env.stop)
        self.c=get_connection();self.addCleanup(self.c.close);self.addCleanup(self.c.rollback)
        self.assertEqual(self.c.execute('SELECT current_database(),current_schema()').fetchone(),('ai_excel_agent_test','test_construction_identity_stage46'))
        self.c.execute('SELECT pg_advisory_xact_lock(20261013,24)')
        self.c.execute('UPDATE report_absence_rules SET enabled=false')
        self.employee,self.name=self.c.execute('SELECT id,full_name FROM employees WHERE NOT is_archived ORDER BY id LIMIT 1').fetchone()
        self.categories=[r[0] for r in self.c.execute('SELECT id FROM object_categories ORDER BY id LIMIT 2')]
        self.po,self.po_name=self.c.execute('SELECT id,name FROM po_types ORDER BY id LIMIT 1').fetchone()
        obj=self.c.execute("INSERT INTO construction_objects(name) VALUES('Review rollback fixture') RETURNING id").fetchone()[0]
        self.eid=self.c.execute('SELECT id FROM construction_entities WHERE legacy_object_id=%s',(obj,)).fetchone()[0]
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'report.docx';document(self.path,'Review rollback fixture',self.name)

    def category(self,po=None,category=None):
        return rr.category(self.c,SimpleNamespace(path=str(self.path),employee_id=self.employee,entity_id=self.eid,po_id=po,category_id=category or self.categories[0]))

    def test_independent_approvals_and_rule_cancel(self):
        state=rr.approve(self.c,str(self.path),'general_contractor')
        self.assertTrue(state['fields']['general_contractor']['approved']);self.assertFalse(state['fields']['subcontractor']['approved'])
        rr.approve(self.c,str(self.path),'subcontractor',True)
        rr.cancel_rule(self.c,'subcontractor')
        digest,doc=rr.source(self.path);state=rr.options(self.c,digest,doc)
        self.assertTrue(state['fields']['general_contractor']['approved']);self.assertFalse(state['fields']['subcontractor']['approved'])

    def test_rule_on_future_report_not_filled(self):
        rr.approve(self.c,str(self.path),'general_contractor',True)
        other=Path(self.tmp.name)/'other.docx';document(other,'Other report',self.name)
        digest,doc=rr.source(other);self.assertTrue(rr.options(self.c,digest,doc)['fields']['general_contractor']['approved'])
        document(other,'Other report',self.name,self.po_name)
        with self.assertRaisesRegex(ValueError,'Заполненное'):rr.approve(self.c,str(other),'general_contractor')

    def test_category_upsert_and_null_fact(self):
        for f in rr.FIELDS:rr.approve(self.c,str(self.path),f)
        a=self.category();b=self.category(category=self.categories[1]);self.assertEqual(a['id'],b['id'])
        self.assertEqual(self.c.execute('SELECT count(*) FROM employee_assignments WHERE entity_id=%s',(self.eid,)).fetchone()[0],1)
        digest,doc=rr.source(self.path)
        request=ReviewRequest(path=str(self.path),employee_id=self.employee,entity_id=self.eid,absence_assignment_id=a['id'])
        with self.c.cursor() as cur:result=validate_review(cur,doc,{},request,rr.options(self.c,digest,doc))
        self.assertTrue(result['can_save'],result)
        row=insert(self.c,result['report_date'],result['facts'][0],'report.docx',digest)
        self.assertIsNone(row['po_id']);self.assertIsNone(row['subcontractor_id'])
        self.assertFalse(insert(self.c,result['report_date'],result['facts'][0],'report.docx',digest)['created'])

    def test_missing_approval_and_category_block(self):
        with self.assertRaisesRegex(ValueError,'согласуйте'):self.category()
        for f in rr.FIELDS:rr.approve(self.c,str(self.path),f)
        digest,doc=rr.source(self.path)
        with self.c.cursor() as cur:r=validate_review(cur,doc,{},ReviewRequest(path=str(self.path),employee_id=self.employee,entity_id=self.eid),rr.options(self.c,digest,doc))
        self.assertFalse(r['can_save']);self.assertIn('Нет категории',r['problems'][0])

    def test_filled_po_category_upsert(self):
        document(self.path,'Review rollback fixture',self.name,self.po_name)
        a=self.category(po=self.po);b=self.category(po=self.po,category=self.categories[1])
        self.assertEqual(a['id'],b['id']);self.assertEqual(b['po_id'],self.po)

if __name__=='__main__':unittest.main(verbosity=2)
