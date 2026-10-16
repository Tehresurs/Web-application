import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
import psycopg
from psycopg import sql
from contextlib import contextmanager
from unittest.mock import patch
from test_daily_control import http_request
import test_production_assignments
from app.database.migrate_object_archive import apply_migration as archive_migration
from app.database.migrate_construction_identity import apply_migration
from app.repositories.construction_identity import resolve,reparent
from app.repositories.directory_errors import DirectoryConflict


@unittest.skipUnless(os.getenv('DAILY_CONTROL_TEST_DB')=='1','Requires isolated PostgreSQL')
class ConstructionIdentityTests(unittest.TestCase):
    movement=test_production_assignments.ProductionAssignmentTests.movement
    upload=test_production_assignments.ProductionAssignmentTests.upload
    action=test_production_assignments.ProductionAssignmentTests.action
    def setUp(self):
        test_production_assignments.ProductionAssignmentTests.setUp(self)
        archive_migration(self.conn)
        self.child=self.conn.execute("INSERT INTO construction_subobjects(object_id,name) VALUES(1,'Identity child') RETURNING id").fetchone()[0]
        apply_migration(self.conn)
        self.a=resolve(self.conn,object_id=1)['entity_id']
        self.b=resolve(self.conn,object_id=2)['entity_id']
        self.s=resolve(self.conn,subobject_id=self.child)['entity_id']
        @contextmanager
        def connection():
            with self.conn.transaction():yield self.conn
        mocked=patch('app.api.construction_identity.get_connection',connection)
        mocked.start();self.addCleanup(mocked.stop)

    def test_round_trip_preserves_old_rows(self):
        tables=['construction_objects','construction_subobjects','daily_control_results','employee_assignments','rail_tickets']
        def snapshot():return [self.conn.execute(f'SELECT to_jsonb(t) FROM {t} t ORDER BY id').fetchall() for t in tables]
        before=snapshot()
        result=reparent(self.conn,self.b,self.a,1)
        self.assertEqual(result['parent_entity_id'],self.a)
        self.assertEqual(resolve(self.conn,object_id=2)['entity_id'],self.b)
        result=reparent(self.conn,self.b,None,result['version'])
        self.assertIsNone(result['parent_entity_id'])
        self.assertEqual(before,snapshot())

    def test_original_child_becomes_root_and_returns(self):
        item=reparent(self.conn,self.s,None,1)
        self.assertIsNone(item['parent_entity_id'])
        self.assertEqual(resolve(self.conn,object_id=1,subobject_id=self.child)['entity_id'],self.s)
        item=reparent(self.conn,self.s,self.b,item['version'])
        self.assertEqual(item['parent_entity_id'],self.b)
        self.assertEqual(self.conn.execute('SELECT object_id FROM construction_subobjects WHERE id=%s',(self.child,)).fetchone()[0],1)

    def test_no_third_level_self_or_parent_with_children(self):
        for entity,parent in [(self.a,self.b),(self.b,self.b),(self.b,self.s)]:
            with self.assertRaises(DirectoryConflict):reparent(self.conn,entity,parent,1)

    def test_stale_version_rejected(self):
        reparent(self.conn,self.b,self.a,1)
        with self.assertRaises(DirectoryConflict):reparent(self.conn,self.b,None,1)
        self.assertEqual(resolve(self.conn,entity_id=self.b)['parent_entity_id'],self.a)

    def test_archived_parent_and_own_archive(self):
        self.conn.execute('UPDATE construction_objects SET is_archived=true WHERE id=1')
        with self.assertRaises(DirectoryConflict):reparent(self.conn,self.b,self.a,1)
        self.assertTrue(resolve(self.conn,entity_id=self.s)['effectively_archived'])
        self.conn.execute('UPDATE construction_subobjects SET is_archived=true WHERE id=%s',(self.child,))
        self.assertTrue(reparent(self.conn,self.s,None,1)['is_archived'])

    def test_mismatched_identity_and_duplicates(self):
        with self.assertRaises(DirectoryConflict):resolve(self.conn,entity_id=self.b,object_id=1)
        self.conn.execute("UPDATE construction_objects SET name='Identity child' WHERE id=2")
        with self.assertRaises(DirectoryConflict):reparent(self.conn,self.b,self.a,1)

    def test_repeat_migration_keeps_current_hierarchy(self):
        reparent(self.conn,self.b,self.a,1)
        before=resolve(self.conn,entity_id=self.b)
        apply_migration(self.conn)
        self.assertEqual(resolve(self.conn,entity_id=self.b),before)

    def test_database_guard_rejects_direct_third_level(self):
        with self.assertRaises(Exception),self.conn.transaction():
            self.conn.execute('UPDATE construction_entity_hierarchy SET parent_entity_id=%s WHERE entity_id=%s',(self.s,self.b))

    def test_entity_api_requires_confirmation_and_version(self):
        path=f'/api/construction-entities/{self.b}/hierarchy'
        body=dict(parent_entity_id=self.a,version=1,confirmed=False)
        self.assertEqual(http_request('PATCH',path,body)[0],409)
        status,result=http_request('PATCH',path,{**body,'confirmed':True})
        self.assertEqual(status,200,result)
        self.assertEqual(result['item']['parent_entity_id'],self.a)
        self.assertEqual(http_request('PATCH',path,{**body,'confirmed':True})[0],409)
        self.assertEqual(http_request('PATCH',path,{'parent_entity_id':None,'version':2,'confirmed':True})[0],200)

    def test_parent_list_excludes_children_self_and_archive(self):
        self.conn.execute('UPDATE construction_objects SET is_archived=true WHERE id=2')
        status,body=http_request('GET','/api/construction-entities',query=f'parents_for={self.a}')
        self.assertEqual(status,200,body)
        ids={i['entity_id'] for i in body['items']}
        self.assertFalse(ids & {self.a,self.b,self.s})

    def test_existing_apis_expose_identity_without_replacing_legacy_ids(self):
        reparent(self.conn,self.b,self.a,1)
        status,body=http_request('GET','/api/objects')
        self.assertEqual(status,200,body)
        self.assertNotIn(2,[i['id'] for i in body['items']])
        status,children=http_request('GET','/api/subobjects',query=f'parent_entity_id={self.a}')
        self.assertEqual(status,200,children)
        item=next(i for i in children['items'] if i['entity_id']==self.b)
        self.assertEqual(item['object_id'],2)
        self.assertIsNone(item['id'])  # No invented subobject ID for an original object.
        self.assertEqual(item['entity_id'],self.b)
        self.assertEqual(item['current_hierarchy']['parent_entity_id'],self.a)
        child=http_request('GET',f'/api/subobjects/{self.child}')[1]['item']
        self.assertEqual(child['entity_id'],self.s)

    def test_legacy_move_uses_hierarchy_and_keeps_facts(self):
        self.conn.execute('UPDATE daily_control_results SET subobject_id=%s WHERE object_id=1',(self.child,))
        before=self.conn.execute('SELECT to_jsonb(r) FROM daily_control_results r ORDER BY id').fetchall()
        path=f'/api/subobjects/{self.child}/move'
        status,plan=http_request('POST',path+'/check',{'object_id':2})
        self.assertEqual(status,200,plan)
        status,body=http_request('PATCH',path,{'object_id':2,'confirmation_token':plan['item']['confirmation_token']})
        self.assertEqual(status,200,body)
        self.assertEqual(body['updated_facts'],0)
        self.assertEqual(resolve(self.conn,subobject_id=self.child)['parent_entity_id'],self.b)
        self.assertEqual(self.conn.execute('SELECT object_id FROM construction_subobjects WHERE id=%s',(self.child,)).fetchone()[0],1)
        self.assertEqual(before,self.conn.execute('SELECT to_jsonb(r) FROM daily_control_results r ORDER BY id').fetchall())

    def test_concurrent_connections_reject_stale_conversion(self):
        schema = self.conn.execute('SELECT current_schema()').fetchone()[0]
        self.assertTrue(schema.startswith('test_'))
        dsn = self.conn.info.dsn
        password = os.getenv('DB_PASSWORD')
        # Publish only this isolated fixture so independent transactions can see it.
        self.conn.commit()
        def cleanup_schema():
            self.conn.rollback()
            with psycopg.connect(dsn, password=password, autocommit=True) as cleanup:
                cleanup.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
        self.addCleanup(cleanup_schema)
        self.conn.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
        barrier = Barrier(2)
        def convert():
            with psycopg.connect(dsn, password=password) as connection:
                connection.execute(sql.SQL('SET LOCAL search_path TO {}').format(sql.Identifier(schema)))
                connection.execute("SET LOCAL lock_timeout='5s'")
                barrier.wait(timeout=5)
                try:
                    reparent(connection, self.b, self.a, 1)
                    return 'saved'
                except DirectoryConflict:
                    return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: convert(), range(2)))
        self.assertCountEqual(results, ['saved', 'conflict'])
        item = resolve(self.conn, entity_id=self.b)
        self.assertEqual((item['parent_entity_id'], item['version']), (self.a, 2))

    def test_api_blocks_non_test_schema_even_when_view_is_visible(self):
        schema = self.conn.execute('SELECT current_schema()').fetchone()[0]
        self.conn.execute(sql.SQL('SET LOCAL search_path TO public, {}').format(sql.Identifier(schema)))
        try:
            self.assertEqual(http_request('GET', '/api/construction-entities')[0], 409)
            self.assertEqual(http_request('PATCH', f'/api/construction-entities/{self.b}/hierarchy',
                dict(parent_entity_id=self.a, version=1, confirmed=True))[0], 409)
        finally:
            self.conn.execute(sql.SQL('SET LOCAL search_path TO {}').format(sql.Identifier(schema)))
        self.assertIsNone(resolve(self.conn, entity_id=self.b)['parent_entity_id'])

    def test_api_rejects_archived_parent_and_third_level(self):
        path = f'/api/construction-entities/{self.b}/hierarchy'
        self.assertEqual(http_request('PATCH', path,
            dict(parent_entity_id=self.s, version=1, confirmed=True))[0], 409)
        self.conn.execute('UPDATE construction_objects SET is_archived=true WHERE id=1')
        self.assertEqual(http_request('PATCH', path,
            dict(parent_entity_id=self.a, version=1, confirmed=True))[0], 409)
        self.assertIsNone(resolve(self.conn, entity_id=self.b)['parent_entity_id'])

    def test_entity_only_assignment_and_legacy_duplicate(self):
        # The minimal shared fixture has no sequence, unlike the deployed table.
        self.conn.execute('CREATE SEQUENCE test_assignment_ids START 100')
        self.conn.execute("ALTER TABLE employee_assignments ALTER COLUMN id SET DEFAULT nextval('test_assignment_ids')")
        reparent(self.conn,self.s,None,1)
        status,body=http_request('POST','/api/employees/2/assignments',dict(entity_id=self.s,po_id=1,category_id=1))
        self.assertEqual(status,200,body)
        raw=self.conn.execute('SELECT object_id,entity_id FROM employee_assignments WHERE id=%s',(body['item']['id'],)).fetchone()
        self.assertEqual(raw,(None,self.s))
        status,body=http_request('GET','/api/employees/2/assignments')
        self.assertEqual(status,200,body)
        self.assertEqual(body['items'][0]['entity_id'],self.s)
        status,_=http_request('POST','/api/employees/1/assignments',dict(entity_id=self.a,po_id=1,category_id=1))
        self.assertEqual(status,400)  # Existing legacy assignment still counts.

    def production_payload(self,items):
        return dict(effective_from='2026-10-01',arrival_movement_ref=self.anchor,assignment_state='OBJECTS',items=items)

    def test_entity_production_items_and_read_current_hierarchy(self):
        reparent(self.conn,self.s,None,1)
        items=[dict(entity_id=e,initial_control_mode='INSPECTION') for e in (self.s,self.b)]
        status,body=http_request('POST','/api/employees/2/production-assignments',self.production_payload(items))
        self.assertEqual(status,200,body)
        self.assertEqual({i['entity_id'] for i in body['item']['items']},{self.s,self.b})
        self.assertTrue(all(i['object_id'] is None for i in body['item']['items']))
        reparent(self.conn,self.b,self.s,1)
        status,body=http_request('GET','/api/employees/2/production-assignments',query='date_from=2026-10-01&date_to=2026-10-02')
        self.assertEqual(status,200,body)
        child=next(i for i in body['item']['periods'][0]['items'] if i['entity_id']==self.b)
        self.assertEqual(child['current_hierarchy']['parent_entity_id'],self.s)
        self.assertIsNone(child['object_id'])

    def test_production_mixed_references_duplicate_rolls_back(self):
        items=[dict(entity_id=self.b),dict(object_id=2)]
        status,body=http_request('POST','/api/employees/2/production-assignments',self.production_payload(items))
        self.assertEqual(status,409,body)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM production_assignment_changes').fetchone()[0],0)

    def test_ticket_entity_only_confirm_restore_and_read(self):
        reparent(self.conn,self.s,None,1)
        ticket=self.upload()
        status,body=http_request('PATCH',f"/api/rail-tickets/{ticket['id']}/object",dict(entity_id=self.s))
        self.assertEqual(status,200,body)
        self.assertIsNone(body['item']['object_id'])
        self.assertEqual(body['item']['entity_id'],self.s)
        status,body=self.action(ticket,'confirm')
        self.assertEqual(status,200,body)
        self.assertEqual(self.conn.execute('SELECT object_id,entity_id FROM production_assignment_items').fetchall(),[(None,self.s)])
        self.assertEqual(self.action(ticket,'annul')[0],200)
        self.conn.execute('UPDATE construction_subobjects SET is_archived=true WHERE id=%s',(self.child,))
        status,body=self.action(ticket,'restore')
        self.assertEqual(status,200,body)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM production_assignment_items').fetchone()[0],1)

    def test_new_directory_records_receive_identity(self):
        self.conn.execute("INSERT INTO construction_objects(id,name) VALUES(44,'New entity')")
        entity=resolve(self.conn,object_id=44)
        self.assertIsNone(entity['parent_entity_id'])
        child=self.conn.execute("INSERT INTO construction_subobjects(object_id,name) VALUES(44,'New child') RETURNING id").fetchone()[0]
        self.assertEqual(resolve(self.conn,subobject_id=child)['parent_entity_id'],entity['entity_id'])
        with self.assertRaises(DirectoryConflict):reparent(self.conn,entity['entity_id'],self.b,1)

    def test_entity_writers_reject_archived_current_parent(self):
        reparent(self.conn,self.s,self.b,1)
        self.conn.execute('UPDATE construction_objects SET is_archived=true WHERE id=2')
        status,_=http_request('POST','/api/employees/2/production-assignments',self.production_payload([dict(entity_id=self.s)]))
        self.assertEqual(status,409)
        ticket=self.upload()
        status,_=http_request('PATCH',f"/api/rail-tickets/{ticket['id']}/object",dict(entity_id=self.s))
        self.assertEqual(status,409)

    def _publish_isolated_fixture(self):
        schema=self.conn.execute('SELECT current_schema()').fetchone()[0]
        self.assertTrue(schema.startswith('test_'))
        dsn=self.conn.info.dsn
        password=os.getenv('DB_PASSWORD')
        self.conn.commit()
        def cleanup():
            self.conn.rollback()
            with psycopg.connect(dsn,password=password,autocommit=True) as c:
                c.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
        self.addCleanup(cleanup)
        self.conn.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
        def connect():
            c=psycopg.connect(dsn,password=password)
            c.execute(sql.SQL('SET LOCAL search_path TO {}').format(sql.Identifier(schema)))
            c.execute("SET LOCAL lock_timeout='5s'")
            return c
        return connect

    def test_assignment_waits_for_concurrent_archive(self):
        from app.repositories.construction_identity import prepare
        connect=self._publish_isolated_fixture()
        started=Event()
        with connect() as archiver:
            archiver.execute('UPDATE construction_objects SET is_archived=true WHERE id=1')
            def assign():
                with connect() as writer:
                    started.set()
                    with self.assertRaises(DirectoryConflict):prepare(writer,dict(entity_id=self.s))
            with ThreadPoolExecutor(max_workers=1) as executor:
                future=executor.submit(assign)
                self.assertTrue(started.wait(5))
                archiver.commit()
                future.result(timeout=10)

    def test_assignment_reads_concurrently_changed_parent(self):
        from app.repositories.construction_identity import prepare
        connect=self._publish_isolated_fixture()
        started=Event()
        with connect() as mover:
            reparent(mover,self.s,self.b,1)
            def assign():
                with connect() as writer:
                    started.set()
                    item=prepare(writer,dict(entity_id=self.s))
                    writer.execute('''INSERT INTO employee_assignments(id,employee_id,entity_id,po_id,category_id)
                        VALUES(100,2,%s,1,1)''',(item['entity_id'],))
                    return resolve(writer,entity_id=item['entity_id'])['parent_entity_id']
            with ThreadPoolExecutor(max_workers=1) as executor:
                future=executor.submit(assign)
                self.assertTrue(started.wait(5))
                mover.commit()
                self.assertEqual(future.result(timeout=10),self.b)
        self.assertEqual(self.conn.execute('SELECT object_id,entity_id FROM employee_assignments WHERE id=100').fetchone(),(None,self.s))

    def test_database_rejects_missing_mismatched_and_duplicate_references(self):
        for entity,obj in [(None,None),(self.b,1),(self.a,None)]:
            with self.assertRaises(psycopg.IntegrityError),self.conn.transaction():
                self.conn.execute('''INSERT INTO employee_assignments(id,employee_id,entity_id,object_id,po_id,category_id)
                    VALUES(100,1,%s,%s,1,1)''',(entity,obj))
        self.assertEqual(self.conn.execute('SELECT count(*) FROM employee_assignments WHERE id=100').fetchone()[0],0)
