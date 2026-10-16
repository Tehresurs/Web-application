import os
import unittest
from contextlib import contextmanager
from unittest.mock import patch
import test_construction_identity_facts as fixtures
from app.repositories import objects, subobjects, object_archive
from app.repositories.construction_identity import resolve, reparent
from app.repositories.directory_errors import DirectoryConflict


@unittest.skipUnless(os.getenv('DAILY_CONTROL_TEST_DB') == '1', 'Requires isolated PostgreSQL')
class CatalogIdentityTests(unittest.TestCase):
    for name in ('movement','payload','create','history','fact','snapshot','upload','action','request','write','read','matrix','assert_history'):
        locals()[name] = getattr(fixtures.IdentityFactTests, name)

    def setUp(self):
        fixtures.IdentityFactTests.setUp(self)
        # The shared minimal fixture omits defaults present in the application catalog.
        self.conn.execute('CREATE SEQUENCE catalog_object_ids START 100')
        self.conn.execute("ALTER TABLE construction_objects ALTER COLUMN id SET DEFAULT nextval('catalog_object_ids')")
        self.conn.execute('ALTER TABLE construction_objects ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ')
        @contextmanager
        def connection():
            with self.conn.transaction():
                yield self.conn
        for target in ('objects', 'subobjects', 'object_archive'):
            mock = patch(f'app.repositories.{target}.get_connection', connection)
            mock.start(); self.addCleanup(mock.stop)

    def test_create_and_rename_return_identity(self):
        obj = objects.create_object('New catalog root')
        self.assertEqual(obj['entity_id'], resolve(self.conn, object_id=obj['id'])['entity_id'])
        child = subobjects.create_subobject(obj['id'], 'New catalog child')
        self.assertEqual(child['current_hierarchy']['parent_entity_id'], obj['entity_id'])
        renamed = objects.update_object(obj['id'], 'Renamed root')
        self.assertEqual(renamed['entity_id'], obj['entity_id'])
        renamed_child = subobjects.update_subobject(child['id'], 'Renamed child')
        self.assertEqual(renamed_child['entity_id'], child['entity_id'])
        self.assertEqual(renamed_child['object_name'], 'Renamed root')
        self.assert_history()

    def test_promoted_parent_child_rename_and_independent_archive(self):
        reparent(self.conn, self.s, None, 1)
        parent = subobjects.update_subobject(self.child, 'Promoted root')
        self.assertIsNone(parent['current_hierarchy']['parent_entity_id'])
        child = subobjects.create_subobject(None, 'Descendant', parent_entity_id=self.s)
        self.assertIsNone(child['object_id'])
        renamed = subobjects.update_subobject(child['id'], 'Renamed descendant')
        self.assertEqual(renamed['object_name'], 'Promoted root')
        self.assertEqual(renamed['entity_id'], child['entity_id'])
        original_parent = self.conn.execute('SELECT object_id,initial_parent_entity_id FROM construction_subobjects WHERE id=%s', (child['id'],)).fetchone()
        object_archive.change('subobjects', child['id'], is_archived=True)
        object_archive.change('subobjects', self.child, is_archived=True)
        with self.assertRaises(DirectoryConflict):
            subobjects.create_subobject(None, 'Blocked', parent_entity_id=self.s)
        object_archive.change('subobjects', self.child, is_archived=False)
        self.assertTrue(resolve(self.conn, entity_id=child['entity_id'])['is_archived'])
        object_archive.change('subobjects', child['id'], is_archived=False)
        self.assertFalse(resolve(self.conn, entity_id=child['entity_id'])['effectively_archived'])
        self.assertEqual(original_parent, self.conn.execute('SELECT object_id,initial_parent_entity_id FROM construction_subobjects WHERE id=%s', (child['id'],)).fetchone())
        self.assertEqual(self.conn.execute('SELECT object_id FROM construction_subobjects WHERE id=%s',(self.child,)).fetchone()[0],1)
        self.assert_history()

    def test_rename_and_create_reject_cross_table_sibling_duplicates(self):
        reparent(self.conn, self.s, None, 1)
        with self.assertRaises(DirectoryConflict): objects.create_object('Identity child')
        with self.assertRaises(DirectoryConflict): objects.update_object(2, 'Identity child')
        with self.assertRaises(DirectoryConflict): subobjects.update_subobject(self.child, resolve(self.conn, entity_id=self.b)['name'])
        reparent(self.conn, self.b, self.a, 1)
        reparent(self.conn, self.s, self.a, 2)
        with self.assertRaises(DirectoryConflict): subobjects.update_subobject(self.child, resolve(self.conn, entity_id=self.b)['name'])
        with self.assertRaises(DirectoryConflict): objects.update_object(2, 'Identity child')
        self.assert_history()

    def test_legacy_parent_creation_rejects_archived_or_child_parent(self):
        object_archive.change('objects', 2, is_archived=True)
        with self.assertRaises(DirectoryConflict): subobjects.create_subobject(2, 'Archived child')
        object_archive.change('objects', 2, is_archived=False)
        reparent(self.conn, self.b, self.a, 1)
        with self.assertRaises(DirectoryConflict): subobjects.create_subobject(2, 'Third level')
        self.assert_history()

    def test_object_archive_is_repeatable_and_does_not_modify_children(self):
        before = self.conn.execute('SELECT to_jsonb(s) FROM construction_subobjects s ORDER BY id').fetchall()
        first = object_archive.change('objects', 1, is_archived=True)
        again = object_archive.change('objects', 1, is_archived=True)
        self.assertEqual(first['archived_at'], again['archived_at'])
        self.assertTrue(resolve(self.conn, entity_id=self.s)['effectively_archived'])
        for _ in range(2): object_archive.change('objects', 1, is_archived=False)
        self.assertEqual(before, self.conn.execute('SELECT to_jsonb(s) FROM construction_subobjects s ORDER BY id').fetchall())
        self.assert_history()
