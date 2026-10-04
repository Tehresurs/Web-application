import os
import unittest
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql

from app.database.db import get_connection
from app.database.migrate_subobjects_aliases import apply_migration
from app.services.employee_matcher import normalize_full_name
from app.services.object_matcher import normalize_object_name
from app.services.po_matcher import normalize_po_name


@unittest.skipUnless(os.getenv("DAILY_CONTROL_TEST_DB") == "1", "Requires isolated PostgreSQL migration test")
class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.conn = get_connection()
        self.addCleanup(self.conn.close)
        self.addCleanup(self.conn.rollback)
        name = "test_subobjects_" + uuid4().hex
        self.conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(name)))
        self.conn.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(name)))
        self.conn.execute("""
            CREATE TABLE employees(id BIGINT PRIMARY KEY);
            CREATE TABLE construction_objects(id BIGINT PRIMARY KEY);
            CREATE TABLE po_types(id BIGINT PRIMARY KEY);
            CREATE TABLE object_categories(id BIGINT PRIMARY KEY);
            CREATE TABLE employee_assignments(id BIGINT PRIMARY KEY, employee_id BIGINT,
                object_id BIGINT, po_id BIGINT, category_id BIGINT);
            INSERT INTO employees VALUES (1);
            INSERT INTO construction_objects VALUES (1),(2);
            INSERT INTO po_types VALUES (1);
            INSERT INTO object_categories VALUES (1);
            INSERT INTO employee_assignments VALUES (1,1,1,1,1);
        """)
        migration = Path(__file__).resolve().parents[1] / "app/database/migrations/001_daily_control_results.sql"
        self.conn.execute(migration.read_text(encoding="utf-8"))
        self.conn.execute("""INSERT INTO daily_control_results
            (report_date,employee_id,object_id,po_id,category_id,source_file,source_sha256)
            VALUES ('2026-09-24',1,1,1,1,'existing.docx',%s)""", ("a" * 64,))

    def test_repeatable_and_old_data_preserved(self):
        before = self.conn.execute("SELECT to_jsonb(r) FROM daily_control_results r").fetchall()
        assignments = self.conn.execute("SELECT * FROM employee_assignments").fetchall()
        apply_migration(self.conn)
        self.conn.execute("INSERT INTO construction_subobjects(object_id,name) VALUES(1,'Test')")
        self.conn.execute("INSERT INTO value_aliases(entity_type,source_value,target_id) VALUES('employee','Test',1)")
        apply_migration(self.conn)
        self.assertEqual(before, self.conn.execute("SELECT to_jsonb(r)-'subobject_id' FROM daily_control_results r").fetchall())
        self.assertEqual(assignments, self.conn.execute("SELECT * FROM employee_assignments").fetchall())
        self.assertIsNone(self.conn.execute("SELECT subobject_id FROM daily_control_results").fetchone()[0])
        self.assertEqual(self.conn.execute("SELECT count(*) FROM construction_subobjects").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM value_aliases").fetchone()[0], 1)
        constraint = self.conn.execute("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid='daily_control_results'::regclass AND conname='uq_daily_control_fact'").fetchone()[0]
        self.assertEqual(constraint, "UNIQUE (report_date, employee_id, object_id, po_id, category_id)")

    def test_normalization_matches_existing_services(self):
        apply_migration(self.conn)
        for kind, normalizer in (("employee", normalize_full_name), ("object", normalize_object_name),
                                  ("subobject", normalize_object_name), ("po", normalize_po_name)):
            for value in ('  Ёлка\t № 55  ', 'ООО «ТЕСТ»', '\n Иванов   Пётр\r\n', 'А\u00a0Б', ''):
                with self.subTest(kind=kind, value=value):
                    actual = self.conn.execute("SELECT normalize_known_value(%s,%s)", (kind,value)).fetchone()[0]
                    self.assertEqual(actual, normalizer(value))

    def test_duplicates_and_deactivation(self):
        apply_migration(self.conn)
        self.conn.execute("INSERT INTO construction_subobjects(object_id,name) VALUES(1,'Куст № 55')")
        self.conn.execute("UPDATE construction_subobjects SET is_active=FALSE")
        with self.assertRaises(psycopg.errors.UniqueViolation), self.conn.transaction():
            self.conn.execute("INSERT INTO construction_subobjects(object_id,name) VALUES(1,'  куст №55  ')")
        self.conn.execute("INSERT INTO construction_subobjects(object_id,name) VALUES(2,'Куст №55')")
        self.assertTrue(self.conn.execute("SELECT is_active FROM construction_subobjects WHERE object_id=2").fetchone()[0])
        self.conn.execute("INSERT INTO value_aliases(entity_type,source_value,target_id) VALUES('po','ООО «ЁЛКА»',1)")
        with self.assertRaises(psycopg.errors.UniqueViolation), self.conn.transaction():
            self.conn.execute("INSERT INTO value_aliases(entity_type,source_value,target_id) VALUES('po',%s,2)", ('ооо "елка"',))

    def test_constraints_and_journal_fk(self):
        apply_migration(self.conn)
        for statement in (
            "INSERT INTO construction_subobjects(object_id,name) VALUES(999,'Test')",
            "INSERT INTO construction_subobjects(object_id,name) VALUES(1,'  ')",
            "INSERT INTO value_aliases(entity_type,source_value,target_id) VALUES('bad','Test',1)",
            "INSERT INTO value_aliases(entity_type,source_value,target_id) VALUES('employee',' ',1)",
            "INSERT INTO value_aliases(entity_type,source_value,target_id) VALUES('employee','Test',0)",
            "UPDATE daily_control_results SET subobject_id=999",
        ):
            with self.subTest(statement=statement), self.assertRaises(psycopg.IntegrityError), self.conn.transaction():
                self.conn.execute(statement)
        sub = self.conn.execute("INSERT INTO construction_subobjects(object_id,name) VALUES(1,'Test') RETURNING id").fetchone()[0]
        self.conn.execute("UPDATE daily_control_results SET subobject_id=%s", (sub,))
        with self.assertRaises(psycopg.IntegrityError), self.conn.transaction():
            self.conn.execute("DELETE FROM construction_subobjects WHERE id=%s", (sub,))
        self.conn.execute("UPDATE construction_subobjects SET is_active=FALSE WHERE id=%s", (sub,))
        self.assertEqual(self.conn.execute("SELECT subobject_id FROM daily_control_results").fetchone()[0], sub)
