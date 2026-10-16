from types import SimpleNamespace
from contextlib import contextmanager
from unittest.mock import patch
from test_report_review_existing import ReviewTests,document
from app.repositories import report_review as rr
from app.services.daily_control_service import ReviewRequest,review_result

class DefaultCategoryTests(ReviewTests):
    def request(self,automatic=True,category_id=None):
        return SimpleNamespace(path=str(self.path),employee_id=self.employee,entity_id=self.eid,
                               po_id=self.po,category_id=category_id,automatic=automatic)
    def prepare(self,default):
        document(self.path,'Review rollback fixture',self.name,self.po_name)
        rr.approve(self.c,str(self.path),'subcontractor')
        self.c.execute('UPDATE po_types SET default_category_id=%s WHERE id=%s',(default,self.po))
    def test_default_is_applied_without_changing_rule(self):
        self.prepare(self.categories[0])
        result=rr.category(self.c,self.request())
        self.assertEqual(result['category_id'],self.categories[0])
        self.assertEqual(self.c.execute('SELECT default_category_id FROM po_types WHERE id=%s',(self.po,)).fetchone()[0],self.categories[0])
    def test_missing_default_keeps_manual_selection(self):
        self.prepare(None)
        self.assertIsNone(rr.category(self.c,self.request()))
        result=rr.category(self.c,self.request(False,self.categories[1]))
        self.assertEqual(result['category_id'],self.categories[1])
    def test_manual_exception_survives_repeat_and_rule_change(self):
        self.prepare(self.categories[0])
        a=rr.category(self.c,self.request())
        rr.category(self.c,self.request(False,self.categories[1]))
        self.assertEqual(rr.category(self.c,self.request())['category_id'],self.categories[1])
        self.assertEqual(self.c.execute('SELECT category_id FROM employee_assignments WHERE id=%s',(a['id'],)).fetchone()[0],self.categories[0])
        self.assertEqual(self.c.execute('SELECT default_category_id FROM po_types WHERE id=%s',(self.po,)).fetchone()[0],self.categories[0])
    def test_confirmed_fact_is_snapshot_after_rule_change(self):
        self.prepare(self.categories[0]);assignment=rr.category(self.c,self.request())
        rr.category(self.c,self.request(False,self.categories[1]))
        @contextmanager
        def connection():yield self.c
        request=ReviewRequest(path=str(self.path),employee_id=self.employee,entity_id=self.eid,
                              general_contractor_id=self.po,assignments={self.po:assignment['id']})
        with patch('app.services.daily_control_service.get_connection',connection),patch('app.services.daily_control_service.prepare_report',return_value={}):
            saved=review_result(request,save=True)
            self.assertTrue(saved['saved'],saved)
            self.assertEqual(saved['results'][0]['category_id'],self.categories[1])
            self.c.execute('UPDATE po_types SET default_category_id=NULL WHERE id=%s',(self.po,))
            again=review_result(request,save=True)
            self.assertEqual(again['results'][0]['category_id'],self.categories[1])
            self.assertFalse(again['created'])

    def test_directory_binding_can_change_clear_and_preserve_on_rename(self):
        from app.repositories.objects import rename_po_type,get_po_types,create_po_type
        @contextmanager
        def connection():yield self.c
        with patch('app.repositories.objects.get_connection',connection):
            rename_po_type(self.po,self.po_name,self.categories[0])
            rename_po_type(self.po,self.po_name)
            self.assertEqual(next(p for p in get_po_types() if p['id']==self.po)['default_category_id'],self.categories[0])
            rename_po_type(self.po,self.po_name,self.categories[1])
            self.assertEqual(next(p for p in get_po_types() if p['id']==self.po)['default_category_id'],self.categories[1])
            rename_po_type(self.po,self.po_name,None)
            self.assertIsNone(next(p for p in get_po_types() if p['id']==self.po)['default_category_id'])
            added=create_po_type('PO category rollback fixture',self.categories[0])
            self.assertEqual(added['default_category_id'],self.categories[0])
