import os
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode
from uuid import uuid4

from psycopg import sql

from app.database.db import get_connection
from app.database.migrate_subobjects_aliases import apply_migration
from app.repositories import subobjects as sub, value_aliases as aliases
from app.repositories.directory_errors import DirectoryConflict, DirectoryNotFound
from test_daily_control import http_request


@unittest.skipUnless(os.getenv("DAILY_CONTROL_TEST_DB") == "1", "Requires isolated PostgreSQL tests")
class KnownValuesTests(unittest.TestCase):
    def setUp(self):
        self.conn = get_connection()
        self.addCleanup(self.conn.close)
        self.addCleanup(self.conn.rollback)
        schema = "test_known_values_" + uuid4().hex
        self.conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        self.conn.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(schema)))
        self.conn.execute("""
            CREATE TABLE employees(id BIGINT PRIMARY KEY, full_name TEXT);
            CREATE TABLE construction_objects(id BIGINT PRIMARY KEY, name TEXT);
            CREATE TABLE po_types(id BIGINT PRIMARY KEY, name TEXT);
            CREATE TABLE object_categories(id BIGINT PRIMARY KEY);
            CREATE TABLE employee_assignments(id BIGINT PRIMARY KEY);
            INSERT INTO employees VALUES (1,'Employee A'), (2,'Employee B');
            INSERT INTO construction_objects VALUES (1,'Object A'), (2,'Object B');
            INSERT INTO po_types VALUES (1,'PO A'), (2,'PO B');
        """)
        migration = Path(__file__).resolve().parents[1] / "app/database/migrations/001_daily_control_results.sql"
        self.conn.execute(migration.read_text(encoding="utf-8"))
        apply_migration(self.conn)
        for name in ("003_control_item_unique.sql", "004_subcontractor.sql"):
            self.conn.execute((migration.parent / name).read_text(encoding="utf-8"))

        @contextmanager
        def connection():
            with self.conn.transaction():
                yield self.conn

        for target in ("app.repositories.subobjects.get_connection", "app.repositories.value_aliases.get_connection"):
            mocked = patch(target, connection)
            mocked.start()
            self.addCleanup(mocked.stop)

    def alias(self, kind="employee", source="Typo", target=1):
        return aliases.create_value_alias(kind, source, target)["item"]

    def test_subobject_create(self):
        status, body = http_request("POST", "/api/subobjects", {"object_id": 1, "name": "Куст №55"})
        self.assertEqual(status, 200)
        self.assertEqual(body["item"]["object_name"], "Object A")
        self.assertTrue(body["item"]["is_active"])

    def test_subobject_list(self):
        sub.create_subobject(1, "A")
        sub.create_subobject(2, "B")
        status, body = http_request("GET", "/api/subobjects")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["items"]), 2)

    def test_subobject_filter(self):
        sub.create_subobject(1, "A")
        sub.create_subobject(2, "B")
        status, body = http_request("GET", "/api/subobjects", query="object_id=2")
        self.assertEqual(status, 200)
        self.assertEqual([r["object_id"] for r in body["items"]], [2])

    def test_subobject_duplicate(self):
        sub.create_subobject(1, "Куст № 55")
        status, body = http_request("POST", "/api/subobjects", {"object_id": 1, "name": "  куст №55 "})
        self.assertEqual(status, 409)
        self.assertEqual(body["status"], "error")
        self.assertEqual(len(sub.get_subobjects()), 1)
        self.assertEqual(sub.create_subobject(2, "Куст №55")["object_id"], 2)

    def test_subobject_missing_parent(self):
        self.assertEqual(http_request("POST", "/api/subobjects", {"object_id": 999, "name": "A"})[0], 404)

    def test_subobject_rename_and_duplicate(self):
        item = sub.create_subobject(1, "A")
        sub.create_subobject(1, "B")
        route = f'/api/subobjects/{item["id"]}'
        status, body = http_request("PATCH", route, {"name": "Changed"})
        self.assertEqual(status, 200)
        self.assertEqual(body["item"]["name"], "Changed")
        self.assertEqual(http_request("PATCH", route, {"name": " b "})[0], 409)
        self.assertEqual(sub.get_subobject(item["id"])["name"], "Changed")

    def test_subobject_deactivation_and_reactivation(self):
        item = sub.create_subobject(1, "A")
        route = f'/api/subobjects/{item["id"]}'
        self.assertEqual(http_request("PATCH", route, {"is_active": False})[0], 200)
        self.assertEqual(sub.get_subobjects(), [])
        self.assertEqual(len(sub.get_subobjects(include_inactive=True)), 1)
        self.assertFalse(http_request("GET", route)[1]["item"]["is_active"])
        self.assertEqual(http_request("POST", "/api/subobjects", {"object_id": 1, "name": "A"})[0], 409)
        self.assertEqual(http_request("PATCH", route, {"is_active": True})[0], 200)

    def test_subobject_exact_normalized_and_ambiguity(self):
        a = sub.create_subobject(1, "Ёлка № 55")
        sub.create_subobject(2, "Ёлка №55")
        self.assertEqual(len(sub.find_subobjects_by_name(" елка №55 ")), 2)
        self.assertEqual(sub.find_subobjects_by_name("ЕЛКА №55", 1)[0]["id"], a["id"])
        sub.update_subobject(a["id"], is_active=False)
        self.assertEqual(sub.find_subobjects_by_name("ЕЛКА №55", 1), [])

    def test_subobject_invalid_requests(self):
        for payload in ({"object_id": 1, "name": " "}, {"object_id": 0, "name": "A"}):
            self.assertEqual(http_request("POST", "/api/subobjects", payload)[0], 422)
        for payload in ({}, {"name": None}, {"is_active": None}, {"object_id": 2}):
            self.assertEqual(http_request("PATCH", "/api/subobjects/1", payload)[0], 422)
        self.assertEqual(http_request("GET", "/api/subobjects/999")[0], 404)

    def check_alias_kind(self, kind, target, name):
        status, body = http_request("POST", "/api/value-aliases", {
            "entity_type": kind, "source_value": "TYPO", "target_id": target,
        })
        self.assertEqual(status, 200)
        self.assertTrue(body["created"])
        self.assertEqual(body["item"]["target_name"], name)
        return body["item"]

    def test_employee_alias(self):
        self.check_alias_kind("employee", 1, "Employee A")

    def test_object_alias(self):
        self.check_alias_kind("object", 1, "Object A")

    def test_po_alias(self):
        self.check_alias_kind("po", 1, "PO A")

    def test_subobject_alias(self):
        subobject = sub.create_subobject(1, "Sub A")
        item = self.check_alias_kind("subobject", subobject["id"], "Sub A")
        self.assertEqual((item["object_id"], item["object_name"]), (1, "Object A"))

    def test_alias_invalid_type(self):
        self.assertEqual(http_request("POST", "/api/value-aliases", {
            "entity_type": "bad", "source_value": "A", "target_id": 1,
        })[0], 422)
        self.assertEqual(http_request("GET", "/api/value-aliases", query="entity_type=bad")[0], 422)
        with self.assertRaises(ValueError):
            aliases.resolve_value_alias("bad", "A")

    def test_alias_missing_targets(self):
        for kind in aliases.TARGETS:
            self.assertEqual(http_request("POST", "/api/value-aliases", {
                "entity_type": kind, "source_value": "A", "target_id": 999,
            })[0], 404)

    def test_alias_idempotency(self):
        first = self.alias(source="  ЁЛКА  ")
        result = aliases.create_value_alias("employee", "елка", 1)
        self.assertFalse(result["created"])
        self.assertEqual(result["item"]["id"], first["id"])
        self.assertEqual(result["item"]["source_value"], "  ЁЛКА  ")
        self.assertEqual(len(aliases.get_value_aliases()), 1)

    def test_alias_conflict(self):
        first = self.alias()
        status, body = http_request("POST", "/api/value-aliases", {
            "entity_type": "employee", "source_value": "typo", "target_id": 2,
        })
        self.assertEqual(status, 409)
        self.assertIn("другое соответствие", body["message"])
        self.assertEqual(aliases.get_value_alias(first["id"])["target_id"], 1)

    def test_alias_resolve_and_normalized_search(self):
        item = self.alias("po", 'ООО «ЁЛКА»')
        query = urlencode({"entity_type": "po", "source_value": ' ооо "елка" '})
        status, body = http_request("GET", "/api/value-aliases", query=query)
        self.assertEqual(status, 200)
        self.assertEqual(body["items"][0]["id"], item["id"])
        self.assertEqual(aliases.resolve_value_alias("po", 'ООО "ЕЛКА"')["target_name"], "PO A")
        self.assertIsNone(aliases.resolve_value_alias("po", "missing"))
        self.assertIsNone(aliases.resolve_value_alias("po", None))

    def test_alias_explicit_update_keeps_source(self):
        item = self.alias(source="  TYPO  ")
        route = f'/api/value-aliases/{item["id"]}'
        status, body = http_request("PATCH", route, {"target_id": 2})
        self.assertEqual(status, 200)
        self.assertEqual(body["item"]["target_name"], "Employee B")
        self.assertEqual(body["item"]["source_value"], "  TYPO  ")
        self.assertEqual(http_request("PATCH", route, {"target_id": 999})[0], 404)
        self.assertEqual(http_request("PATCH", route, {"target_id": 1, "source_value": "Other"})[0], 422)

    def test_alias_target_name_tracks_rename(self):
        item = self.alias()
        self.conn.execute("UPDATE employees SET full_name='Renamed' WHERE id=1")
        self.assertEqual(http_request("GET", f'/api/value-aliases/{item["id"]}')[1]["item"]["target_name"], "Renamed")

    def test_alias_inactive_and_deleted_targets(self):
        child = sub.create_subobject(1, "Sub A")
        item = self.alias("subobject", target=child["id"])
        sub.update_subobject(child["id"], is_active=False)
        self.assertIsNone(aliases.resolve_value_alias("subobject", "Typo"))
        self.assertFalse(aliases.get_value_alias(item["id"])["target_is_active"])
        self.assertEqual(http_request("POST", "/api/value-aliases", {
            "entity_type": "subobject", "source_value": "Another", "target_id": child["id"],
        })[0], 400)
        employee_alias = self.alias()
        self.conn.execute("DELETE FROM employees WHERE id=1")
        self.assertIsNone(aliases.resolve_value_alias("employee", "Typo"))
        self.assertFalse(aliases.get_value_alias(employee_alias["id"])["target_exists"])

    def test_alias_delete_keeps_target(self):
        item = self.alias()
        route = f'/api/value-aliases/{item["id"]}'
        self.assertEqual(http_request("DELETE", route)[1]["deleted"], True)
        self.assertEqual(http_request("GET", route)[0], 404)
        self.assertEqual(http_request("DELETE", route)[0], 404)
        self.assertIsNotNone(self.conn.execute("SELECT id FROM employees WHERE id=1").fetchone())

    def test_alias_empty_and_unknown_ids(self):
        self.assertEqual(http_request("POST", "/api/value-aliases", {
            "entity_type": "employee", "source_value": " \n", "target_id": 1,
        })[0], 422)
        self.assertEqual(http_request("PATCH", "/api/value-aliases/999", {"target_id": 1})[0], 404)


@unittest.skipUnless(os.getenv("DAILY_CONTROL_TEST_DB") == "1", "Requires configured PostgreSQL (read-only API calls)")
class ExistingAPITests(unittest.TestCase):
    def check_get(self, path, query=""):
        status, body = http_request("GET", path, query=query)
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")
        return body

    def test_employees(self): self.check_get("/api/employees")
    def test_objects(self): self.check_get("/api/objects")
    def test_po(self): self.check_get("/api/po-types")
    def test_categories(self): self.check_get("/api/object-categories")
    def test_journal(self):
        self.check_get("/api/daily-control-results", "date_from=2026-01-01&date_to=2026-12-31")
    def test_assignments(self):
        items = self.check_get("/api/employees")["items"]
        if not items: self.skipTest("No employees in configured database")
        self.check_get(f'/api/employees/{items[0]["id"]}/assignments')
