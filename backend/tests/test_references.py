import os
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode
from uuid import uuid4

from app.database.db import get_connection
from app.repositories import subobjects, value_aliases
from test_daily_control import http_request


class SchemaTests(unittest.TestCase):
    def test_openapi(self):
        status, schema = http_request("GET", "/openapi.json")
        self.assertEqual(status, 200)
        for path, methods in {
            "/api/subobjects": ("get", "post"),
            "/api/subobjects/{subobject_id}": ("get", "patch"),
            "/api/value-aliases": ("get", "post"),
            "/api/value-aliases/{alias_id}": ("get", "patch", "delete"),
        }.items():
            for method in methods:
                self.assertIn("schema", schema["paths"][path][method]["responses"]["200"]["content"]["application/json"])

    def test_invalid_requests(self):
        for path, method, payload in (
            ("/api/value-aliases", "POST", {"entity_type": "bad", "source_value": "x", "target_id": 1}),
            ("/api/value-aliases/1", "PATCH", {"target_id": 1, "source_value": "changed"}),
            ("/api/subobjects/1", "PATCH", {}),
            ("/api/subobjects/1", "PATCH", {"name": None}),
            ("/api/subobjects/1", "PATCH", {"is_active": None}),
        ):
            with self.subTest(payload=payload):
                self.assertEqual(http_request(method, path, payload)[0], 422)


@unittest.skipUnless(os.getenv("DAILY_CONTROL_TEST_DB") == "1", "Requires isolated PostgreSQL tests")
class ReferenceDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.conn = get_connection()
        self.addCleanup(self.conn.close)
        self.addCleanup(self.conn.rollback)
        schema = "test_references_" + uuid4().hex
        self.conn.execute(f'CREATE SCHEMA "{schema}"')
        self.conn.execute(f'SET LOCAL search_path TO "{schema}"')
        self.conn.execute("""
            CREATE TABLE employees(id BIGINT PRIMARY KEY, full_name TEXT, position_id BIGINT, phone TEXT, crew_id BIGINT);
            CREATE TABLE positions(id BIGINT PRIMARY KEY, name TEXT, action_description TEXT);
            CREATE TABLE crews(id BIGINT PRIMARY KEY, name TEXT);
            CREATE TABLE construction_objects(id BIGINT PRIMARY KEY, name TEXT);
            CREATE TABLE po_types(id BIGINT PRIMARY KEY, name TEXT);
            CREATE TABLE object_categories(id BIGINT PRIMARY KEY, name TEXT, parent_id BIGINT, sort_order INT, is_system BOOLEAN);
            CREATE TABLE employee_assignments(id BIGINT PRIMARY KEY, employee_id BIGINT, object_id BIGINT, po_id BIGINT, category_id BIGINT);
            INSERT INTO employees(id,full_name) VALUES (1,'Кецких Игорь Валерьевич'),(2,'Другой сотрудник');
            INSERT INTO construction_objects VALUES (1,'Объект А'),(2,'Объект Б');
            INSERT INTO po_types VALUES (1,'ПО А'),(2,'ПО Б');
            INSERT INTO object_categories VALUES (1,'Категория',NULL,1,TRUE);
            INSERT INTO employee_assignments VALUES (1,1,1,1,1);
        """)
        for name in ("001_daily_control_results.sql", "002_subobjects_aliases.sql", "003_control_item_unique.sql", "004_subcontractor.sql", "005_luvr_directories.sql", "006_luvr_history.sql"):
            self.conn.execute((Path(__file__).resolve().parents[1] / "app/database/migrations" / name).read_text(encoding="utf-8"))
        self.conn.execute("""INSERT INTO daily_control_results
            (report_date,employee_id,object_id,po_id,category_id,source_file,source_sha256)
            VALUES ('2026-09-24',1,1,1,1,'existing.docx',%s)""", ("a" * 64,))

        @contextmanager
        def connection():
            with self.conn.transaction():
                yield self.conn

        for module in ("subobjects", "value_aliases", "employees", "objects", "assignments", "daily_control"):
            mock = patch(f"app.repositories.{module}.get_connection", connection)
            mock.start()
            self.addCleanup(mock.stop)

    def sub(self, name="Подъезд № 55", object_id=1):
        status, body = http_request("POST", "/api/subobjects", {"object_id": object_id, "name": name})
        self.assertEqual(status, 200, body)
        return body["item"]

    def alias(self, kind="employee", source="  Кецких  Игорь Валерьевич  ", target=1):
        return http_request("POST", "/api/value-aliases", {"entity_type": kind, "source_value": source, "target_id": target})

    def test_subobject_create(self):
        item = self.sub()
        self.assertEqual(item["object_name"], "Объект А")
        self.assertTrue(item["is_active"])
        self.assertEqual(http_request("GET", f'/api/subobjects/{item["id"]}')[1]["item"], item)

    def test_subobject_list(self):
        first, second = self.sub(), self.sub("Другой")
        self.assertEqual({i["id"] for i in http_request("GET", "/api/subobjects")[1]["items"]}, {first["id"],second["id"]})

    def test_subobject_filter(self):
        first = self.sub()
        self.sub(object_id=2)
        self.assertEqual(http_request("GET", "/api/subobjects", query="object_id=1")[1]["items"], [first])

    def test_subobject_duplicate(self):
        self.sub("Ёлка № 55")
        self.assertEqual(http_request("POST", "/api/subobjects", {"object_id":1,"name":"  елка №55  "})[0],409)
        self.sub("елка №55", 2)

    def test_subobject_missing_parent(self):
        self.assertEqual(http_request("POST", "/api/subobjects", {"object_id":999,"name":"Test"})[0],404)

    def test_subobject_rename(self):
        item = self.sub()
        status, body = http_request("PATCH", f'/api/subobjects/{item["id"]}', {"name":"Новое"})
        self.assertEqual(status,200)
        self.assertEqual(body["item"]["name"],"Новое")

    def test_subobject_rename_duplicate(self):
        first = self.sub()
        self.sub("Другое")
        self.assertEqual(http_request("PATCH", f'/api/subobjects/{first["id"]}', {"name":" другое "})[0],409)
        self.assertEqual(subobjects.get_subobject(first["id"])["name"], first["name"])

    def test_subobject_deactivate(self):
        item = self.sub()
        path = f'/api/subobjects/{item["id"]}'
        self.assertFalse(http_request("PATCH", path, {"is_active":False})[1]["item"]["is_active"])
        self.assertEqual(http_request("GET", "/api/subobjects")[1]["items"], [])
        self.assertEqual(http_request("POST", "/api/subobjects", {"object_id":1,"name":item["name"]})[0],409)
        self.assertTrue(http_request("PATCH", path, {"is_active":True})[1]["item"]["is_active"])

    def test_exact_normalized_match(self):
        item = self.sub("Ёлка № 55")
        self.assertEqual(subobjects.find_subobject_exact(1,"\tЕЛКА №55\u00a0"),item)
        self.assertIsNone(subobjects.find_subobject_exact(2,"елка №55"))

    def test_blank_values(self):
        self.assertEqual(http_request("POST", "/api/subobjects", {"object_id":1,"name":"\u00a0\t "})[0],422)
        self.assertEqual(self.alias(source="\u00a0\t ")[0],422)

    def test_employee_alias(self):
        status, body = self.alias()
        self.assertEqual(status,200)
        self.assertEqual(body["item"]["target_name"],"Кецких Игорь Валерьевич")

    def test_object_alias(self):
        status, body = self.alias("object")
        self.assertEqual(status,200)
        self.assertEqual(body["item"]["target_name"],"Объект А")

    def test_subobject_alias(self):
        item = self.sub()
        status, body = self.alias("subobject",target=item["id"])
        self.assertEqual(status,200)
        self.assertEqual(body["item"]["target_name"],item["name"])
        self.assertEqual(body["item"]["object_id"],1)
        self.assertEqual(body["item"]["object_name"],"Объект А")

    def test_po_alias(self):
        status, body = self.alias("po", "ООО «ЁЛКА»")
        self.assertEqual(status,200)
        self.assertEqual(body["item"]["target_name"],"ПО А")
        self.assertEqual(value_aliases.resolve_value_alias("po", 'ооо "елка"'),body["item"])

    def test_invalid_entity(self):
        self.assertEqual(self.alias("invalid")[0],422)
        with self.assertRaises(ValueError):
            value_aliases.resolve_value_alias("invalid","x")

    def test_missing_targets(self):
        for kind in ("employee","object","subobject","po"):
            with self.subTest(kind=kind):
                self.assertEqual(self.alias(kind,target=999)[0],404)

    def test_same_alias_idempotent(self):
        first = self.alias()[1]["item"]
        status, body = self.alias(source="кецких игорь валерьевич")
        self.assertEqual(status,200)
        self.assertEqual(body["item"],first)
        self.assertEqual(len(value_aliases.get_value_aliases()),1)

    def test_alias_conflict(self):
        first = self.alias()[1]["item"]
        status, body = self.alias(target=2)
        self.assertEqual(status,409)
        self.assertEqual(body["message"],"Для этого значения уже существует другое соответствие.")
        self.assertEqual(value_aliases.get_value_alias(first["id"]),first)

    def test_resolve_and_search(self):
        first = self.alias()[1]["item"]
        self.alias("object")
        self.assertEqual(value_aliases.resolve_value_alias("employee","КЕЦКИХ\tИгорь Валерьевич"),first)
        self.assertIsNone(value_aliases.resolve_value_alias("employee","Кецких"))
        query = urlencode({"entity_type":"employee","source_value":"КЕЦКИХ Игорь Валерьевич"})
        self.assertEqual(http_request("GET", "/api/value-aliases", query=query)[1]["items"],[first])
        self.assertEqual(len(value_aliases.get_value_aliases(source_value="КЕЦКИХ Игорь Валерьевич")),2)

    def test_update_alias_target(self):
        first = self.alias()[1]["item"]
        path = f'/api/value-aliases/{first["id"]}'
        status, body = http_request("PATCH", path, {"target_id":2})
        self.assertEqual(status,200)
        self.assertEqual(body["item"]["target_name"],"Другой сотрудник")
        self.assertEqual(body["item"]["source_value"],first["source_value"])
        self.assertEqual(body["item"]["normalized_source_value"],first["normalized_source_value"])
        self.assertEqual(http_request("PATCH", path, {"target_id":999})[0],404)
        self.assertEqual(http_request("GET",path)[1],body)

    def test_inactive_subobject_target(self):
        first, second = self.sub(), self.sub("Другой")
        alias = self.alias("subobject",target=first["id"])[1]["item"]
        subobjects.update_subobject(second["id"],is_active=False)
        self.assertEqual(self.alias("subobject",source="Новое",target=second["id"])[0],400)
        self.assertEqual(http_request("PATCH",f'/api/value-aliases/{alias["id"]}',{"target_id":second["id"]})[0],400)

    def test_delete_alias(self):
        item = self.alias()[1]["item"]
        path = f'/api/value-aliases/{item["id"]}'
        self.assertTrue(http_request("DELETE",path)[1]["deleted"])
        self.assertEqual(http_request("GET",path)[0],404)
        self.assertEqual(http_request("DELETE",path)[0],404)
        self.assertIsNone(value_aliases.resolve_value_alias("employee",item["source_value"]))

    def test_missing_records(self):
        for path in ("/api/subobjects/999", "/api/value-aliases/999"):
            self.assertEqual(http_request("GET",path)[0],404)
        self.assertEqual(http_request("PATCH","/api/subobjects/999",{"name":"x"})[0],404)
        self.assertEqual(http_request("PATCH","/api/value-aliases/999",{"target_id":1})[0],404)

    def test_existing_employees_api(self):
        status, body = http_request("GET","/api/employees")
        self.assertEqual(status,200)
        self.assertEqual(len(body["items"]),2)

    def test_existing_objects_api(self):
        self.assertEqual(http_request("GET","/api/objects"),(200,{"status":"ok","items":[{"id":1,"name":"Объект А"},{"id":2,"name":"Объект Б"}]}))

    def test_existing_po_api(self):
        self.assertEqual(http_request("GET","/api/po-types")[1]["items"][0],{"id":1,"name":"ПО А"})

    def test_existing_categories_api(self):
        status, body = http_request("GET","/api/object-categories")
        self.assertEqual(status,200)
        self.assertEqual(body["items"][0]["name"],"Категория")

    def test_existing_assignments_api(self):
        status, body = http_request("GET","/api/employees/1/assignments")
        self.assertEqual(status,200)
        self.assertEqual(body["objects_count"],1)

    def test_existing_journal_api(self):
        status, body = http_request("GET","/api/daily-control-results",query="date_from=2026-09-01&date_to=2026-09-30")
        self.assertEqual(status,200)
        self.assertEqual(body["summary"]["facts_count"],1)
        self.assertEqual(body["items"][0]["source_file"],"existing.docx")
