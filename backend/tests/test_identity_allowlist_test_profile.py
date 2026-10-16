import os
import unittest
from contextlib import contextmanager, nullcontext
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.api.construction_identity import require_test_database
from app.database.db import get_connection
from app.repositories import construction_identity as identity
from app.repositories.directory_errors import DirectoryConflict
from test_daily_control import http_request


class IdentityAllowlistTest(unittest.TestCase):
    def setUp(self):
        self.conn = get_connection()
        self.addCleanup(self.conn.close)
        self.addCleanup(self.conn.rollback)
        self.assertEqual(require_test_database(self.conn)['schema'], os.environ['DB_SCHEMA'])
        suffix = uuid4().hex
        self.parent_object = self.conn.execute(
            'INSERT INTO construction_objects(name) VALUES (%s) RETURNING id',
            (f'Allowlist parent {suffix}',),
        ).fetchone()[0]
        self.child_object = self.conn.execute(
            'INSERT INTO construction_objects(name) VALUES (%s) RETURNING id',
            (f'Allowlist child {suffix}',),
        ).fetchone()[0]
        self.parent_entity = identity.resolve(self.conn, object_id=self.parent_object)['entity_id']
        self.child_entity = identity.resolve(self.conn, object_id=self.child_object)['entity_id']

    @contextmanager
    def connection(self):
        with self.conn.transaction():
            yield self.conn

    def request_conversion(self):
        return http_request(
            'PATCH',
            f'/api/construction-entities/{self.child_entity}/hierarchy',
            {'parent_entity_id': self.parent_entity, 'version': 1, 'confirmed': True},
        )

    def test_allowed_isolated_schema_permits_conversion(self):
        with patch('app.api.construction_identity.get_connection', self.connection):
            status, body = self.request_conversion()
        self.assertEqual(status, 200, body)
        self.assertEqual(
            identity.resolve(self.conn, entity_id=self.child_entity)['parent_entity_id'],
            self.parent_entity,
        )

    def test_unlisted_schema_is_rejected_before_write(self):
        denied_schema = 'test_not_allowlisted_4113'
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = ('ai_excel_agent_test', denied_schema)
        with (
            patch.dict(os.environ, {'APP_DB_PROFILE': 'test', 'DB_SCHEMA': denied_schema}),
            patch('app.api.construction_identity.get_connection', return_value=nullcontext(conn)),
            patch('app.api.construction_identity.identity.reparent') as reparent,
        ):
            status, body = self.request_conversion()
        self.assertEqual(status, 409, body)
        reparent.assert_not_called()
        with patch.dict(os.environ, {'APP_DB_PROFILE': 'test', 'DB_SCHEMA': denied_schema}):
            with self.assertRaises(DirectoryConflict):
                require_test_database(conn)

    def test_wrong_profile_is_rejected_without_database_changes(self):
        before = self.conn.execute(
            'SELECT entity_id,parent_entity_id,version FROM construction_entity_hierarchy '
            'WHERE entity_id=%s',
            (self.child_entity,),
        ).fetchone()
        with (
            patch.dict(os.environ, {'APP_DB_PROFILE': 'production'}),
            patch('app.api.construction_identity.get_connection', self.connection),
            patch('app.api.construction_identity.identity.reparent') as reparent,
        ):
            status, body = self.request_conversion()
        self.assertEqual(status, 409, body)
        reparent.assert_not_called()
        after = self.conn.execute(
            'SELECT entity_id,parent_entity_id,version FROM construction_entity_hierarchy '
            'WHERE entity_id=%s',
            (self.child_entity,),
        ).fetchone()
        self.assertEqual(after, before)


if __name__ == '__main__':
    unittest.main()
