"""Standalone SQL checks: python tests/test_clean_start_categories_sql.py.

Copies only the named rehearsal DB; never invokes application connections/servers.
Fresh-path fixture reverses the empty consumer DDL in its disposable copy only.
"""
import os
from pathlib import Path
import unittest
import uuid

import psycopg
from psycopg import sql
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'ai_excel_agent_stage41210_20261014_1634'
MIGRATIONS = ROOT / 'app/database/migrations'


class CategoryChecks:
    fresh = False

    @classmethod
    def setUpClass(cls):
        load_dotenv(ROOT / '.env')
        cls.params = dict(host=os.getenv('DB_HOST'), port=os.getenv('DB_PORT'),
                          user=os.getenv('DB_USER'), password=os.getenv('DB_PASSWORD'))
        cls.database = 'ai_excel_agent_test_categories_' + uuid.uuid4().hex[:12]
        with psycopg.connect(**cls.params, dbname=SOURCE, autocommit=True) as admin:
            assert admin.execute('SELECT current_database()').fetchone()[0] == SOURCE
            admin.execute(sql.SQL('CREATE DATABASE {} TEMPLATE {}').format(
                sql.Identifier(cls.database), sql.Identifier(SOURCE)))
        cls.addClassCleanup(cls.drop_copy)
        with psycopg.connect(**cls.params, dbname=cls.database, autocommit=True) as c:
            assert c.execute('SELECT current_database(), current_schema()').fetchone() == (cls.database, 'public')
            before = c.execute('SELECT * FROM object_categories ORDER BY id').fetchall()
            if cls.fresh:
                # Restore the pre-clean-start empty consumer constraints in the copy.
                for table in ('employee_assignments', 'daily_control_results', 'production_assignment_items'):
                    assert c.execute(sql.SQL('SELECT count(*) FROM {}').format(sql.Identifier(table))).fetchone()[0] == 0
                assert c.execute('SELECT count(*) FROM construction_entities').fetchone()[0] == 0
                for table in ('employee_assignments', 'daily_control_results', 'production_assignment_items', 'rail_tickets'):
                    c.execute(sql.SQL('ALTER TABLE {} DROP COLUMN entity_id CASCADE').format(sql.Identifier(table)))
                    c.execute(sql.SQL('ALTER TABLE {} DROP CONSTRAINT {}').format(
                        sql.Identifier(table), sql.Identifier(table + '_entity_only')))
                c.execute('DROP TABLE construction_entities CASCADE')
                c.execute('DROP FUNCTION guard_clean_construction_entity() CASCADE')
                c.execute('DROP FUNCTION validate_clean_entity_reference() CASCADE')
                c.execute('ALTER TABLE employee_assignments ADD CONSTRAINT uq_employee_assignment UNIQUE (employee_id, object_id, po_id, category_id)')
                c.execute('ALTER TABLE daily_control_results ADD CONSTRAINT uq_daily_control_fact UNIQUE NULLS NOT DISTINCT (report_date, employee_id, object_id, subobject_id, po_id, subcontractor_id, category_id)')
                c.execute('ALTER TABLE production_assignment_items ADD CONSTRAINT production_assignment_items_change_id_object_id_subobject_i_key UNIQUE NULLS NOT DISTINCT (change_id, object_id, subobject_id, po_id, subcontractor_id)')
                filename = '024_construction_entities_clean_start.sql'
            else:
                filename = '024_clean_start_categories_correction.sql'
            c.execute("SELECT set_config('app.allow_clean_start_migration', 'yes', false)")
            c.execute("SELECT set_config('app.stage4129_rehearsal_database', %s, false)", (cls.database,))
            c.execute((MIGRATIONS / filename).read_text(encoding='utf-8'))
            assert c.execute('SELECT * FROM object_categories ORDER BY id').fetchall() == before

    @classmethod
    def drop_copy(cls):
        assert cls.database.startswith('ai_excel_agent_test_categories_')
        with psycopg.connect(**cls.params, dbname=SOURCE, autocommit=True) as c:
            c.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(cls.database)))

    def setUp(self):
        self.c = psycopg.connect(**self.params, dbname=self.database)
        self.addCleanup(self.c.close)
        self.addCleanup(self.c.rollback)
        self.category = self.c.execute("INSERT INTO object_categories(name, sort_order) VALUES ('category SQL check', 37) RETURNING id").fetchone()[0]
        self.root = self.c.execute("INSERT INTO construction_entities(name,category_id) VALUES ('root SQL check',%s) RETURNING entity_id", (self.category,)).fetchone()[0]

    def test_create_and_view(self):
        self.assertEqual(self.c.execute('SELECT category_id FROM construction_entity_current WHERE entity_id=%s', (self.root,)).fetchone(), (self.category,))
        self.assertEqual(self.c.execute('SELECT count(*) FROM construction_objects').fetchone(), (0,))
        self.assertEqual(self.c.execute('SELECT count(*) FROM construction_subobjects').fetchone(), (0,))

    def test_change_and_explicit_unassign(self):
        other = self.c.execute("INSERT INTO object_categories(name,parent_id,sort_order) VALUES ('child category SQL check',%s,8) RETURNING id", (self.category,)).fetchone()[0]
        self.c.execute('UPDATE construction_entities SET category_id=%s WHERE entity_id=%s', (other, self.root))
        self.assertEqual(self.c.execute('SELECT category_id FROM construction_entity_current WHERE entity_id=%s', (self.root,)).fetchone(), (other,))
        self.assertEqual(self.c.execute('SELECT parent_id,sort_order FROM object_categories WHERE id=%s', (other,)).fetchone(), (self.category, 8))
        self.c.execute('UPDATE construction_entities SET category_id=NULL WHERE entity_id=%s', (self.root,))
        self.assertEqual(self.c.execute('SELECT category_id FROM construction_entity_current WHERE entity_id=%s', (self.root,)).fetchone(), (None,))

    def test_invalid_category_insert_and_update(self):
        for statement, params in [
            ("INSERT INTO construction_entities(name,category_id) VALUES ('invalid category',-9223372036854775808)", ()),
            ('UPDATE construction_entities SET category_id=-9223372036854775808 WHERE entity_id=%s', (self.root,)),
        ]:
            with self.assertRaises(psycopg.errors.ForeignKeyViolation):
                with self.c.transaction():
                    self.c.execute(statement, params)
        self.assertEqual(self.c.execute('SELECT category_id FROM construction_entities WHERE entity_id=%s', (self.root,)).fetchone(), (self.category,))

    def test_category_delete_restricted(self):
        with self.assertRaises(psycopg.errors.RestrictViolation):
            with self.c.transaction():
                self.c.execute('DELETE FROM object_categories WHERE id=%s', (self.category,))
        self.assertEqual(self.c.execute('SELECT category_id FROM construction_entities WHERE entity_id=%s', (self.root,)).fetchone(), (self.category,))

    def test_roundtrip_and_child(self):
        parent = self.c.execute("INSERT INTO construction_entities(name) VALUES ('destination SQL check') RETURNING entity_id").fetchone()[0]
        for target in (parent, None):
            self.c.execute('UPDATE construction_entities SET parent_entity_id=%s WHERE entity_id=%s', (target, self.root))
            self.assertEqual(self.c.execute('SELECT entity_id,category_id,parent_entity_id FROM construction_entity_current WHERE entity_id=%s', (self.root,)).fetchone(), (self.root, self.category, target))
        child = self.c.execute("INSERT INTO construction_entities(name,parent_entity_id,category_id) VALUES ('child SQL check',%s,%s) RETURNING entity_id", (self.root, self.category)).fetchone()[0]
        self.c.execute('UPDATE construction_entities SET parent_entity_id=NULL WHERE entity_id=%s', (child,))
        self.assertEqual(self.c.execute('SELECT category_id FROM construction_entity_current WHERE entity_id=%s', (child,)).fetchone(), (self.category,))


class CorrectedModel(CategoryChecks, unittest.TestCase):
    pass


class FreshModel(CategoryChecks, unittest.TestCase):
    fresh = True


if __name__ == '__main__':
    unittest.main(verbosity=2, failfast=True)
