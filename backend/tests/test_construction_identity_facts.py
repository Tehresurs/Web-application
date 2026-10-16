import os
import unittest
import tempfile
from pathlib import Path
from datetime import date
from io import BytesIO
from contextlib import contextmanager
from unittest.mock import patch
from openpyxl import load_workbook
import test_production_matrix as fixtures
from test_daily_control import http_request
from app.database.migrate_object_archive import apply_migration as archive_migration
from app.database.migrate_construction_identity import apply_migration
from app.repositories.construction_identity import resolve,reparent
from app.repositories.daily_control import insert_fact,get_journal
from app.services.deployment import build_report
from app.services.deployment_analysis import analyze_day,load_document_keys
from app.services.deployment_excel import export_report


@unittest.skipUnless(os.getenv('DAILY_CONTROL_TEST_DB')=='1','Requires isolated PostgreSQL')
class IdentityFactTests(unittest.TestCase):
    for name in ('movement','payload','create','history','fact','snapshot','upload','action','request','write','read','matrix'):
        locals()[name]=getattr(fixtures.ProductionMatrixTests,name)

    def setUp(self):
        fixtures.ProductionMatrixTests.setUp(self)
        archive_migration(self.conn)
        self.child=self.conn.execute("INSERT INTO construction_subobjects(object_id,name) VALUES(1,'Identity child') RETURNING id").fetchone()[0]
        self.legacy=self.fact('2026-10-04',2)
        self.write(self.request('2026-10-04',scope='FACT'))
        self.before_matrix=self.matrix()
        self.original=self.conn.execute('SELECT id,to_jsonb(r) FROM daily_control_results r ORDER BY id').fetchall()
        apply_migration(self.conn)
        self.a=resolve(self.conn,object_id=1)['entity_id']
        self.b=resolve(self.conn,object_id=2)['entity_id']
        self.s=resolve(self.conn,subobject_id=self.child)['entity_id']
        @contextmanager
        def connection():
            with self.conn.transaction():yield self.conn
        for target in ('app.services.daily_control_service.get_connection','app.services.object_matcher.get_connection',
                       'app.services.deployment_analysis.get_connection','app.repositories.deployment.get_connection'):
            mocked=patch(target,connection);mocked.start();self.addCleanup(mocked.stop)

    def add(self,entity,day='2026-10-05',digest='b'):
        with self.conn.cursor() as cur:
            return insert_fact(cur,date.fromisoformat(day),dict(entity_id=entity,employee_id=2,po_id=1,category_id=1),
                               'confirmed.docx',digest*64)

    def assert_history(self):
        rows=self.conn.execute("SELECT id,to_jsonb(r)-'entity_id' FROM daily_control_results r WHERE id=ANY(%s) ORDER BY id",
                               ([r[0] for r in self.original],)).fetchall()
        self.assertEqual(rows,self.original)

    def test_promoted_child_can_have_new_child_without_fake_parent(self):
        reparent(self.conn,self.s,None,1)
        status,body=http_request('POST','/api/subobjects',dict(parent_entity_id=self.s,name='New descendant'))
        self.assertEqual(status,200,body)
        item=body['item'];self.assertIsNone(item['object_id'])
        self.assertEqual(item['current_hierarchy']['parent_entity_id'],self.s)
        status,_=http_request('POST','/api/subobjects',dict(parent_entity_id=item['entity_id'],name='Third level'))
        self.assertEqual(status,409)
        fact=self.add(item['entity_id'])
        self.assertIsNone(fact['object_id']);self.assertIsNone(fact['subobject_id'])
        self.assertEqual(fact['object_name'],'Identity child')
        self.assertEqual(fact['subobject_name'],'New descendant')
        self.assert_history()

    def test_legacy_and_entity_fact_are_one_identity(self):
        result=self.add(self.b,'2026-10-04','c')
        self.assertFalse(result['created']);self.assertEqual(result['id'],self.legacy)
        new=self.add(self.b)
        self.assertTrue(new['created']);self.assertIsNone(new['object_id'])
        self.assertFalse(self.add(self.b,digest='d')['created'])
        self.assert_history()

    def test_matrix_roundtrip_keeps_time_and_fact_overrides(self):
        before=self.matrix()
        self.assertEqual(before['totals'],self.before_matrix['totals'])
        for parent in (self.a,None):
            item=resolve(self.conn,entity_id=self.b)
            reparent(self.conn,self.b,parent,item['version'])
            matrix=self.matrix()
            self.assertEqual(matrix['totals'],before['totals'])
            cell=next(r['cells']['2026-10-04'] for r in matrix['employees'][0]['rows'] if '2026-10-04' in r['cells'])
            self.assertEqual(cell['source_fact_id'],self.legacy)
            self.assertEqual(cell['control_mode'],'OPERATIONAL')
            self.assertEqual(cell['parent_entity_id'],parent)
            self.assertEqual(cell['object_id'],2)
            self.assert_history()

    def test_siblings_remain_distinct_in_matrix_report_analysis_and_excel(self):
        reparent(self.conn,self.b,self.a,1)
        f1=self.add(self.b,digest='b');f2=self.add(self.s,digest='c')
        matrix=self.matrix();day=date(2026,10,5)
        cells=[r['cells'][str(day)] for r in matrix['employees'][0]['rows'] if str(day) in r['cells']]
        self.assertEqual({c['entity_id'] for c in cells},{self.b,self.s})
        self.assertEqual(sorted(c['share_cents'] for c in cells),[50,50])
        report=build_report(day,matrix,{})
        self.assertEqual(report['totals']['objects'],2)
        self.assertEqual(report['totals']['specialists'],1)
        self.assertEqual(len(report['rows']),2)
        analysis=analyze_day(day,matrix,[],load_document_keys({f1['id'],f2['id']}))['production']
        self.assertEqual((analysis['objects'],analysis['confirmed_reports'],analysis['total']),(2,2,1))
        book=load_workbook(BytesIO(export_report(report)))
        self.assertEqual([book.active.cell(i,2).value for i in (8,9)],[r['object_name'] for r in report['rows']])
        self.assertEqual(book.active.max_column,7)
        self.assert_history()

    def test_journal_uses_current_parent_and_preserves_source_ids(self):
        reparent(self.conn,self.b,self.a,1)
        journal=get_journal(date(2026,10,4),date(2026,10,4),entity_id=self.a)
        self.assertEqual(len(journal['items']),1)
        row=journal['items'][0]
        self.assertEqual((row['object_id'],row['entity_id'],row['parent_entity_id']),(2,self.b,self.a))
        self.assertEqual(row['control_item_type'],'subobject')
        self.assertEqual(get_journal(date(2026,10,4),date(2026,10,4),entity_id=self.a,include_subobjects=False)['items'],[])
        self.assert_history()

    def test_archive_late_report_via_confirmation_api(self):
        from app.services.daily_control_service import ReviewRequest,review_result
        reparent(self.conn,self.s,None,1)
        self.conn.execute('INSERT INTO employee_assignments(id,employee_id,entity_id,po_id,category_id) VALUES(100,2,%s,1,1)',(self.s,))
        self.conn.execute('UPDATE construction_subobjects SET is_archived=true WHERE id=%s',(self.child,))
        document=dict(filename='late.docx',business_data=dict(report_date=dict(found=True,value='2026-10-06'),
            inspector=dict(found=True),object=dict(found=True),general_contractor=dict(found=True),subcontractor=dict(found=False)))
        report=dict(employee_id=2,entity_id=self.s,general_contractor_id=1,employee_status='found',object_status='found',general_contractor_status='found')
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'late.docx';path.write_bytes(b'late confirmed source')
            with patch('app.services.daily_control_service.read_document',return_value=document),patch('app.services.daily_control_service.prepare_report',return_value=report):
                status,body=http_request('POST','/api/daily-control-results',dict(path=str(path),entity_id=self.s))
                self.assertEqual(status,200,body)
                self.assertTrue(body['warnings']);self.assertTrue(body['created'])
                self.assertIsNone(body['results'][0]['object_id'])
                again=review_result(ReviewRequest(path=str(path),entity_id=self.s),save=True)
                self.assertFalse(again['created']);self.assertTrue(again['warnings'])
        self.assert_history()

    def test_matcher_resolves_promoted_and_demoted_entities(self):
        from app.services.object_matcher import match_object
        reparent(self.conn,self.s,None,1)
        reparent(self.conn,self.b,self.s,1)
        for entity in (self.s,self.b):
            row=resolve(self.conn,entity_id=entity)
            match=match_object(row['name'])
            self.assertEqual(match['entity_id'],entity)
            self.assertEqual(match['current_hierarchy']['parent_entity_id'],row['parent_entity_id'])
        apply_migration(self.conn)
        self.assert_history()
