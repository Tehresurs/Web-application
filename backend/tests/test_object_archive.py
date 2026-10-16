import os
import unittest
from contextlib import contextmanager
from unittest.mock import patch
import test_references
import test_daily_control
import test_production_assignments
from test_daily_control import http_request
from app.database.migrate_object_archive import apply_migration
from app.repositories.object_archive import require_assignable


@unittest.skipUnless(os.getenv('DAILY_CONTROL_TEST_DB')=='1','Requires isolated PostgreSQL')
class ObjectArchiveTests(unittest.TestCase):
    def setUp(self):
        test_references.ReferenceDatabaseTests.setUp(self)
        apply_migration(self.conn)

    def operation(self,kind='objects',item=1,action='archive'):
        status,body=http_request('POST',f'/api/{kind}/{item}/{action}')
        self.assertEqual(status,200,body)
        return body['item']

    def test_archive_preserves_all_links_and_history(self):
        before=self.conn.execute('SELECT to_jsonb(r) FROM daily_control_results r ORDER BY id').fetchall()
        assignments=self.conn.execute('SELECT * FROM employee_assignments').fetchall()
        item=self.operation()
        self.assertTrue(item['is_archived']);self.assertIsNotNone(item['archived_at'])
        self.assertEqual(before,self.conn.execute('SELECT to_jsonb(r) FROM daily_control_results r ORDER BY id').fetchall())
        self.assertEqual(assignments,self.conn.execute('SELECT * FROM employee_assignments').fetchall())
        self.assertEqual(len(http_request('GET','/api/objects')[1]['items']),2)

    def test_parent_restore_preserves_child_states(self):
        ids=[self.conn.execute('INSERT INTO construction_subobjects(object_id,name,is_active) VALUES(1,%s,%s) RETURNING id',(str(i),bool(i))).fetchone()[0] for i in range(2)]
        self.operation('subobjects',ids[1]);self.operation()
        children=http_request('GET','/api/subobjects',query='include_inactive=true&archive=active')[1]['items']
        self.assertEqual(children,[])
        self.operation(action='restore')
        rows=self.conn.execute('SELECT id,object_id,is_active,is_archived FROM construction_subobjects ORDER BY id').fetchall()
        self.assertEqual(rows,[(ids[0],1,False,False),(ids[1],1,True,True)])
        self.operation('subobjects',ids[1],'restore')
        self.assertFalse(self.conn.execute('SELECT is_archived FROM construction_subobjects WHERE id=%s',(ids[1],)).fetchone()[0])

    def test_idempotence_and_independent_status(self):
        status,body=http_request('PATCH','/api/objects/1/activity-status',{'activity_status':'COMPLETED'})
        self.assertEqual(status,200,body)
        first=self.operation();self.assertEqual(first,self.operation())
        restored=self.operation(action='restore');self.assertEqual(restored,self.operation(action='restore'))
        self.assertEqual(restored['activity_status'],'COMPLETED');self.assertIsNone(restored['archived_at'])
        self.assertEqual(http_request('PATCH','/api/objects/1/activity-status',{'activity_status':'DELETED'})[0],422)

    def test_old_delete_archives_even_with_history(self):
        status,body=http_request('DELETE','/api/objects/1')
        self.assertEqual(status,200,body);self.assertFalse(body['deleted']);self.assertTrue(body['archived'])
        self.assertEqual(self.conn.execute('SELECT count(*) FROM construction_objects').fetchone()[0],2)

    def test_new_assignment_blocked(self):
        self.operation()
        status,_=http_request('POST','/api/employees/2/assignments',{'object_id':1,'po_id':1,'category_id':1})
        self.assertIn(status,(400,409))
        self.assertEqual(self.conn.execute('SELECT count(*) FROM employee_assignments').fetchone()[0],1)

    def test_child_or_parent_prevents_new_link(self):
        child=self.conn.execute("INSERT INTO construction_subobjects(object_id,name) VALUES(1,'Child') RETURNING id").fetchone()[0]
        self.operation('subobjects',child)
        with self.conn.cursor() as cur:
            with self.assertRaises(ValueError):require_assignable(cur,1,child)
        self.operation('subobjects',child,'restore');self.operation()
        with self.conn.cursor() as cur:
            with self.assertRaises(ValueError):require_assignable(cur,1,child)

    def test_filters_and_missing(self):
        self.operation()
        for state,ids in [('active',[2]),('archived',[1]),('all',[1,2])]:
            self.assertEqual(sorted(i['id'] for i in http_request('GET','/api/objects',query='archive='+state)[1]['items']),ids)
        self.assertEqual(http_request('POST','/api/objects/999/archive')[0],404)

    def test_migration_repeat_preserves_original_columns(self):
        before=self.conn.execute('SELECT to_jsonb(o) FROM construction_objects o ORDER BY id').fetchall()
        apply_migration(self.conn)
        self.assertEqual(before,self.conn.execute('SELECT to_jsonb(o) FROM construction_objects o ORDER BY id').fetchall())


@unittest.skipUnless(os.getenv('DAILY_CONTROL_TEST_DB')=='1','Requires isolated PostgreSQL')
class ArchivedReportTests(unittest.TestCase):
    def setUp(self):
        test_daily_control.DatabaseTests.setUp(self)
        apply_migration(self.conn)

    def test_late_report_is_saved_with_warning(self):
        self.conn.execute('UPDATE construction_objects SET is_archived=true,archived_at=CURRENT_TIMESTAMP WHERE id=1')
        result=test_daily_control.review_result(self.request,save=True)
        self.assertTrue(result['saved']);self.assertTrue(result['warnings'])
        self.assertEqual(str(result['report_date']),'2026-09-24')

    def test_archived_child_is_saved_and_remains_under_parent(self):
        child=self.conn.execute("INSERT INTO construction_subobjects(object_id,name,is_archived) VALUES(1,'Child',true) RETURNING id").fetchone()[0]
        result=test_daily_control.review_result(self.request.model_copy(update={'subobject_id':child}),save=True)
        self.assertTrue(result['saved']);self.assertTrue(result['warnings'])
        self.assertEqual(self.conn.execute('SELECT object_id,subobject_id FROM daily_control_results').fetchone(),(1,child))


@unittest.skipUnless(os.getenv('DAILY_CONTROL_TEST_DB')=='1','Requires isolated PostgreSQL')
class ArchivedProductionTests(unittest.TestCase):
    movement=test_production_assignments.ProductionAssignmentTests.movement
    payload=test_production_assignments.ProductionAssignmentTests.payload
    create=test_production_assignments.ProductionAssignmentTests.create
    history=test_production_assignments.ProductionAssignmentTests.history
    def setUp(self):
        test_production_assignments.ProductionAssignmentTests.setUp(self)
        apply_migration(self.conn)

    def test_new_plan_blocked_existing_plan_remains(self):
        first=self.create()
        self.conn.execute('UPDATE construction_objects SET is_archived=true,archived_at=CURRENT_TIMESTAMP WHERE id=1')
        status,body=http_request('POST','/api/employees/2/production-assignments',self.payload('2026-10-02'))
        self.assertEqual(status,409,body)
        self.assertEqual(self.history()['periods'][0]['basis_id'],first['id'])
