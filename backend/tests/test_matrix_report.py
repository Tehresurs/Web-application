"""Rollback-only checks for the isolated 8001 single-report workflow."""
from datetime import date
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch
from docx import Document
from test_report_review_existing import ReviewTests,document
from app.services.daily_control_service import ReviewRequest,review_result
from app.services import matrix_report_service as mr
from app.repositories import report_review as rr
from app.repositories.directory_errors import DirectoryConflict


class MatrixReportTests(ReviewTests):
    def connection(self):
        @contextmanager
        def connection():yield self.c
        return connection

    def prepare_request(self,path=None,category=None,**extra):
        path=path or self.path
        for field in rr.FIELDS:rr.approve(self.c,str(path),field)
        from types import SimpleNamespace
        a=rr.category(self.c,SimpleNamespace(path=str(path),employee_id=self.employee,entity_id=self.eid,
                      po_id=None,category_id=category or self.categories[0],automatic=False))
        return ReviewRequest(path=str(path),employee_id=self.employee,entity_id=self.eid,
             absence_assignment_id=a['id'],expected_employee_id=self.employee,
             expected_report_date=date(2026,10,15),**extra)

    def test_single_upload_checks_date_employee_and_duplicate_without_inserting_fact(self):
        content=self.path.read_bytes()
        count=self.c.execute('SELECT count(*) FROM daily_control_results').fetchone()[0]
        uploaded=None
        with patch('app.services.matrix_report_service.get_connection',self.connection()):
            with self.assertRaises(ValueError):mr.upload_report(content,'report.docx',self.employee,date(2026,10,14))
            other=self.c.execute('SELECT id FROM employees WHERE id<>%s LIMIT 1',(self.employee,)).fetchone()[0]
            with self.assertRaises(ValueError):mr.upload_report(content,'report.docx',other,date(2026,10,15))
            uploaded=mr.upload_report(content,'report.docx')
            self.assertEqual(uploaded['report']['matrix_context']['employee_id'],self.employee)
            self.assertEqual(uploaded['report']['matrix_context']['date'],'2026-10-15')
        try:
            self.assertFalse(uploaded['report']['control_saved'])
            self.assertEqual(self.c.execute('SELECT count(*) FROM daily_control_results').fetchone()[0],count)
            request=self.prepare_request()
            with patch('app.services.daily_control_service.get_connection',self.connection()),patch('app.services.daily_control_service.prepare_report',return_value={}):
                saved=review_result(request,save=True)
                again=review_result(request,save=True)
            self.assertTrue(saved['saved']);self.assertFalse(again['created'])
            with patch('app.services.matrix_report_service.get_connection',self.connection()):
                duplicate=mr.upload_report(content,'report.docx',self.employee,date(2026,10,15))
            self.assertTrue(duplicate['report']['control_saved'])
            self.assertEqual(duplicate['report']['control_results'][0]['id'],saved['results'][0]['id'])
        finally:
            if uploaded:
                path=Path(uploaded['report']['source_path'])
                root=Path(__file__).resolve().parents[1]/'uploads'/'matrix_reports'
                self.assertTrue(path.resolve().is_relative_to(root.resolve()))
                path.unlink();path.parent.rmdir()

    def test_explicit_replacement_archives_old_fact_and_overrides_atomically(self):
        request=self.prepare_request()
        with patch('app.services.daily_control_service.get_connection',self.connection()),patch('app.services.daily_control_service.prepare_report',return_value={}):
            first=review_result(request,save=True)['results'][0]
            self.c.execute("INSERT INTO production_matrix_overrides(employee_id,effective_from,scope,field_name,control_mode,fact_id,period_key,basis_revision) VALUES(%s,'2026-10-15','FACT','CONTROL_MODE','INSPECTION',%s,%s,'test-revision')",(self.employee,first['id'],'FACT:'+str(first['id'])))
            corrected=Path(self.tmp.name)/'corrected.docx'
            document(corrected,'Review rollback fixture',self.name)
            digest=sha256(self.path.read_bytes()).hexdigest()
            replacement=self.prepare_request(corrected,self.categories[1],replace_fact_id=first['id'],replace_source_sha256=digest)
            preview=review_result(replacement)
            self.assertEqual(preview['replacement']['old_facts'][0]['id'],first['id'])
            self.assertEqual(preview['replacement']['new_facts'][0]['category_id'],self.categories[1])
            self.assertEqual(len(preview['replacement']['old_overrides']),1)
            with self.assertRaises(ValueError):review_result(replacement,save=True)
            self.assertEqual(self.c.execute('SELECT count(*) FROM daily_control_results WHERE id=%s',(first['id'],)).fetchone()[0],1)
            result=review_result(replacement.model_copy(update={'confirm_replacement':True,'replacement_token':preview['replacement']['token']}),save=True)
            self.assertTrue(result['saved'])
            self.assertEqual(result['results'][0]['category_id'],self.categories[1])
            archived=self.c.execute('SELECT old_facts,old_overrides,new_facts FROM daily_control_fact_replacements WHERE old_source_sha256=%s',(digest,)).fetchone()
            self.assertEqual(archived[0][0]['id'],first['id'])
            self.assertEqual(len(archived[1]),1)
            self.assertEqual(archived[2][0]['id'],result['results'][0]['id'])
            self.assertEqual(self.c.execute('SELECT count(*) FROM daily_control_results WHERE id=%s',(first['id'],)).fetchone()[0],0)
            with self.assertRaises(DirectoryConflict):review_result(request,save=True)
            again=review_result(replacement.model_copy(update={'replace_fact_id':None,'replace_source_sha256':None}))
            self.assertTrue(again['saved'])
            with patch('app.services.matrix_report_service.get_connection',self.connection()):
                info=mr.inspect_fact(result['results'][0]['id'])
            self.assertTrue(info['replacement_history'])

    def test_stale_replacement_and_changed_target_are_blocked(self):
        request=self.prepare_request()
        with patch('app.services.daily_control_service.get_connection',self.connection()),patch('app.services.daily_control_service.prepare_report',return_value={}):
            first=review_result(request,save=True)['results'][0]
            corrected=Path(self.tmp.name)/'other.docx';document(corrected,'Review rollback fixture',self.name)
            bad=self.prepare_request(corrected,self.categories[1],replace_fact_id=first['id'],replace_source_sha256='0'*64,confirm_replacement=True)
            with self.assertRaises(DirectoryConflict):review_result(bad,save=True)
            wrong=request.model_copy(update={'expected_report_date':date(2026,10,14)})
            with self.assertRaises(ValueError):review_result(wrong,save=True)
            self.assertEqual(self.c.execute('SELECT category_id FROM daily_control_results WHERE id=%s',(first['id'],)).fetchone()[0],self.categories[0])

    def test_collision_with_another_fact_rolls_back_replacement(self):
        request=self.prepare_request()
        with patch('app.services.daily_control_service.get_connection',self.connection()),patch('app.services.daily_control_service.prepare_report',return_value={}):
            first=review_result(request,save=True)['results'][0]
            other=Path(self.tmp.name)/'already-existing.docx';document(other,'Review rollback fixture',self.name)
            other_request=self.prepare_request(other,self.categories[1])
            second=review_result(other_request,save=True)['results'][0]
            corrected=Path(self.tmp.name)/'colliding-correction.docx';document(corrected,'Review rollback fixture',self.name)
            replacement=self.prepare_request(corrected,self.categories[1],replace_fact_id=first['id'],replace_source_sha256=sha256(self.path.read_bytes()).hexdigest())
            preview=review_result(replacement)
            confirm=replacement.model_copy(update={'confirm_replacement':True,'replacement_token':preview['replacement']['token']})
            with self.assertRaises(DirectoryConflict):
                with self.c.transaction():review_result(confirm,save=True)
            self.assertEqual(self.c.execute('SELECT count(*) FROM daily_control_results WHERE id=ANY(%s)',([first['id'],second['id']],)).fetchone()[0],2)
            self.assertEqual(self.c.execute('SELECT count(*) FROM daily_control_fact_replacements WHERE old_source_sha256=%s',(sha256(self.path.read_bytes()).hexdigest(),)).fetchone()[0],0)
