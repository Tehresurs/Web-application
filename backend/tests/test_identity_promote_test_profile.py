import os
import unittest
from contextlib import contextmanager
from unittest.mock import patch, MagicMock
from test_daily_control import http_request
from app.database.db import get_connection
from app.api.construction_identity import require_test_database
from app.repositories.directory_errors import DirectoryConflict


class TestProfilePromotion(unittest.TestCase):
    def setUp(self):
        from uuid import uuid4
        from app.repositories.construction_identity import resolve
        self.conn=get_connection()
        self.addCleanup(self.conn.close)
        self.addCleanup(self.conn.rollback)
        require_test_database(self.conn)
        self.original=self.conn.execute('SELECT id,to_jsonb(r) FROM daily_control_results r ORDER BY id').fetchall()
        suffix=uuid4().hex
        self.aid=self.conn.execute("INSERT INTO construction_objects(name) VALUES(%s) RETURNING id",('Root A '+suffix,)).fetchone()[0]
        self.bid=self.conn.execute("INSERT INTO construction_objects(name) VALUES(%s) RETURNING id",('Root B '+suffix,)).fetchone()[0]
        self.child=self.conn.execute("INSERT INTO construction_subobjects(object_id,name) VALUES(%s,%s) RETURNING id",(self.aid,'Identity child '+suffix)).fetchone()[0]
        self.child_name='Identity child '+suffix
        self.a=resolve(self.conn,object_id=self.aid)['entity_id']
        self.b=resolve(self.conn,object_id=self.bid)['entity_id']
        self.s=resolve(self.conn,subobject_id=self.child)['entity_id']
        @contextmanager
        def connection():
            with self.conn.transaction():yield self.conn
        for target in ('app.api.construction_identity','app.repositories.objects','app.repositories.subobjects'):
            mock=patch(target+'.get_connection',connection);mock.start();self.addCleanup(mock.stop)

    def assert_history(self):
        self.assertEqual(self.original,self.conn.execute('SELECT id,to_jsonb(r) FROM daily_control_results r ORDER BY id').fetchall())

    def convert(self, entity, parent, version=1):
        require_test_database(self.conn)
        return http_request('PATCH',f'/api/construction-entities/{entity}/hierarchy',
                            dict(parent_entity_id=parent,version=version,confirmed=True))

    def test_conversion_preserves_sources_and_updates_current_catalog(self):
        tables=('construction_objects','construction_subobjects','daily_control_results','employee_assignments','rail_tickets')
        def snapshot():return {t:self.conn.execute(f'SELECT to_jsonb(r) FROM {t} r ORDER BY id').fetchall() for t in tables}
        before=snapshot()
        status,parents=http_request('GET','/api/construction-entities',query=f'parents_for={self.b}')
        self.assertEqual(status,200);self.assertIn(self.a,[p['entity_id'] for p in parents['items']]);self.assertTrue(all(p['parent_entity_id'] is None and not p['is_archived'] and p['entity_id'] != self.b for p in parents['items']))
        status,result=self.convert(self.b,self.a)
        self.assertEqual(status,200,result);self.assertEqual(result['item']['entity_id'],self.b)
        roots=http_request('GET','/api/objects')[1]['items']
        children=http_request('GET','/api/subobjects',query=f'parent_entity_id={self.a}')[1]['items']
        self.assertNotIn(self.b,[r['entity_id'] for r in roots])
        self.assertEqual(sum(r['entity_id']==self.b for r in children),1)
        self.assertEqual(before,snapshot());self.assert_history()
        self.assertEqual(self.convert(self.b,self.a)[0],409)

    def test_structural_conflicts_do_not_write(self):
        for entity,parent in ((self.a,self.b),(self.b,self.b),(self.b,self.s)):
            self.assertEqual(self.convert(entity,parent)[0],409)
        self.assert_history()

    def test_standalone_preserves_source_and_appears_once(self):
        before=self.conn.execute('SELECT to_jsonb(s) FROM construction_subobjects s WHERE id=%s',(self.child,)).fetchone()
        status,result=self.convert(self.s,None)
        self.assertEqual(status,200,result)
        self.assertEqual(result['item']['entity_id'],self.s)
        self.assertIsNone(result['item']['parent_entity_id'])
        self.assertEqual(result['item']['name'],self.child_name)
        roots=http_request('GET','/api/objects')[1]['items']
        children=http_request('GET','/api/subobjects')[1]['items']
        self.assertEqual(sum(r['entity_id']==self.s for r in roots),1)
        self.assertNotIn(self.s,[r['entity_id'] for r in children])
        self.assertEqual(before,self.conn.execute('SELECT to_jsonb(s) FROM construction_subobjects s WHERE id=%s',(self.child,)).fetchone())
        self.assertEqual(self.convert(self.s,None)[0],409)
        self.assert_history()

    def test_standalone_conflict_and_unconfirmed_request_preserve_hierarchy(self):
        self.conn.execute('UPDATE construction_objects SET name=%s WHERE id=%s',(self.child_name,self.bid))
        before=self.conn.execute('SELECT * FROM construction_entity_hierarchy ORDER BY entity_id').fetchall()
        self.assertEqual(self.convert(self.s,None)[0],409)
        status,_=http_request('PATCH',f'/api/construction-entities/{self.s}/hierarchy',
            dict(parent_entity_id=None,version=1,confirmed=False))
        self.assertEqual(status,409)
        self.assertEqual(before,self.conn.execute('SELECT * FROM construction_entity_hierarchy ORDER BY entity_id').fetchall())
        self.assert_history()

    def test_environment_rejects_other_database_profile_or_schema(self):
        for changes in ({'APP_DB_PROFILE':'production'},{'DB_SCHEMA':'test_other'}):
            with patch.dict(os.environ,changes),self.assertRaises(DirectoryConflict):require_test_database(self.conn)
        wrong=MagicMock();wrong.execute.return_value.fetchone.return_value=('other_database',os.environ['DB_SCHEMA'])
        with self.assertRaises(DirectoryConflict):require_test_database(wrong)

    def test_archived_parent_and_duplicate_name_are_rejected(self):
        require_test_database(self.conn)
        self.conn.execute('UPDATE construction_objects SET is_archived=true WHERE id=%s',(self.aid,))
        self.assertEqual(self.convert(self.b,self.a)[0],409)
        self.conn.execute('UPDATE construction_objects SET is_archived=false WHERE id=%s',(self.aid,))
        self.conn.execute('UPDATE construction_objects SET name=%s WHERE id=%s',(self.child_name,self.bid))
        self.assertEqual(self.convert(self.b,self.a)[0],409)
        self.assert_history()
