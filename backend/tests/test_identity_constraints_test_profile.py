"""Server rejection checks in the designated test schema, with complete rollback."""
import os
import unittest
from contextlib import contextmanager
from unittest.mock import patch
from psycopg import sql
from app.database.db import get_connection
from app.api.construction_identity import require_test_database
from app.repositories import construction_identity as identity
from app.repositories.directory_errors import DirectoryConflict
from test_daily_control import http_request


class IdentityConstraintsTest(unittest.TestCase):
    def setUp(self):
        self.conn=get_connection()
        self.addCleanup(self.conn.close)
        self.addCleanup(self.conn.rollback)
        require_test_database(self.conn)
        self.conn.execute('SELECT pg_advisory_xact_lock(20261013,24)')
        self.tables=[r[0] for r in self.conn.execute('SELECT tablename FROM pg_tables WHERE schemaname=current_schema() ORDER BY tablename')]
        self.original=self.snapshot()
        self.addCleanup(self.verify_rollback)
        rows=identity.directory(self.conn)
        self.parent=next(r for r in rows if r['parent_entity_id'] is None and not r['is_archived'])
        self.child=next(r for r in rows if r['parent_entity_id']==self.parent['entity_id'] and r['legacy_subobject_id'] is not None)
        self.object=next(r for r in rows if r['parent_entity_id']==self.parent['entity_id'] and r['legacy_object_id'] is not None)
        @contextmanager
        def connection():
            with self.conn.transaction():yield self.conn
        mock=patch('app.api.construction_identity.get_connection',connection)
        mock.start();self.addCleanup(mock.stop)

    def snapshot(self):
        rows={t:self.conn.execute(sql.SQL('SELECT to_jsonb(r) FROM {} r ORDER BY to_jsonb(r)::text').format(sql.Identifier(t))).fetchall() for t in self.tables}
        rows['__sequences__']=self.conn.execute('SELECT sequencename,last_value FROM pg_sequences WHERE schemaname=current_schema() ORDER BY sequencename').fetchall()
        return rows

    def verify_rollback(self):
        self.conn.rollback()
        require_test_database(self.conn)
        self.assertEqual(self.snapshot(),self.original,'Data survived test rollback')

    def request(self, entity, parent, version=None):
        if version is None:version=identity.resolve(self.conn,entity_id=entity)['version']
        return http_request('PATCH',f'/api/construction-entities/{entity}/hierarchy',
                            dict(parent_entity_id=parent,version=version,confirmed=True))

    def reject(self, entity, parent, status=409, version=None):
        before=self.snapshot()
        code,body=self.request(entity,parent,version)
        self.assertEqual(code,status,body)
        self.assertEqual(body['status'],'error');self.assertTrue(body['message'])
        self.assertEqual(self.snapshot(),before,'Rejected operation changed data')

    def make_root(self):
        require_test_database(self.conn)
        code,body=self.request(self.object['entity_id'],None)
        self.assertEqual(code,200,body)

    def test_third_level_and_parent_with_children_rejected(self):
        self.reject(self.object['entity_id'],self.child['entity_id'])
        self.make_root()
        self.reject(self.parent['entity_id'],self.object['entity_id'])

    def test_cycles_and_self_parent_rejected(self):
        self.reject(self.parent['entity_id'],self.child['entity_id'])
        self.reject(self.object['entity_id'],self.object['entity_id'])
        self.reject(self.parent['entity_id'],self.parent['entity_id'])

    def test_archived_parent_rejected(self):
        self.make_root()
        require_test_database(self.conn)
        self.conn.execute('UPDATE construction_objects SET is_archived=true,archived_at=CURRENT_TIMESTAMP WHERE id=%s',
                          (self.parent['legacy_object_id'],))
        self.reject(self.object['entity_id'],self.parent['entity_id'])

    def test_normalized_sibling_name_conflict_rejected(self):
        self.make_root()
        require_test_database(self.conn)
        self.conn.execute('UPDATE construction_objects SET name=%s WHERE id=%s',
                          ('  '+self.child['name'].upper()+'  ',self.object['legacy_object_id']))
        self.reject(self.object['entity_id'],self.parent['entity_id'])

    def test_missing_entity_and_parent_rejected(self):
        missing=self.conn.execute('SELECT max(id)+1000 FROM construction_entities').fetchone()[0]
        self.reject(missing,self.parent['entity_id'],404,1)
        self.reject(self.object['entity_id'],missing,404)

    def test_error_after_update_rolls_back_partial_change(self):
        self.make_root()
        original_resolve=identity.resolve
        entity=self.object['entity_id'];parent=self.parent['entity_id']
        version=original_resolve(self.conn,entity_id=entity)['version']
        observed=[]
        def failing_read(conn,**kwargs):
            value=original_resolve(conn,**kwargs)
            if value['entity_id']==entity and value['version']==version+1:
                observed.append(value['parent_entity_id'])
                raise DirectoryConflict('Injected failure after hierarchy UPDATE')
            return value
        with patch.object(identity,'resolve',side_effect=failing_read):
            self.reject(entity,parent,version=version)
        self.assertEqual(observed,[parent],'Failure must occur after a real UPDATE')

    def test_wrong_database_profile_rejected_on_server(self):
        # The connection remains in the verified test DB even with an invalid profile.
        for profile in ('production',''):
            with self.subTest(profile=profile),patch.dict(os.environ,{'APP_DB_PROFILE':profile}):
                self.reject(self.object['entity_id'],None)


if __name__=='__main__':unittest.main(failfast=True)
