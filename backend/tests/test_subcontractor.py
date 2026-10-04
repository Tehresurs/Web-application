import os
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

import psycopg

import test_daily_control as control
import test_references as references
from test_processing import document_result
from app.database.migrate_subcontractor import apply_migration
from app.repositories import value_aliases
from app.repositories.daily_control import insert_fact, get_journal
from app.services.daily_control_service import review_result
from app.services.po_matcher import match_po, match_subcontractor
from app.services.processing_service import prepare_report


class AnalysisTests(unittest.TestCase):
    def test_absent_values_do_not_match_or_create_problems(self):
        for raw in (None, "", " \t\n", "-", " — ", "–", "−", "‑", "‒"):
            with self.subTest(raw=raw), patch("app.services.po_matcher.get_all_po_types") as lookup, \
                    patch("app.services.po_matcher.resolve_value_alias") as alias, \
                    patch("app.services.processing_service.match_po", return_value={"status": "found", "po": {"id": 1}}):
                document = document_result()
                document["business_data"]["subcontractor"].update(raw=raw, value=raw)
                result = prepare_report(document)
                self.assertEqual(result["subcontractor_status"], "not_applicable")
                self.assertIsNone(result["subcontractor_id"])
                self.assertIsNone(result["subcontractor"])
                self.assertEqual(result["raw_subcontractor"], raw)
                self.assertEqual(result["problems"], [])
                lookup.assert_not_called()
                alias.assert_not_called()

    def test_exact_normalization_precedes_alias(self):
        with patch("app.services.po_matcher.get_all_po_types", return_value=[{"id": 27, "name": 'ООО «Ёлка»'}]), \
                patch("app.services.po_matcher.resolve_value_alias") as alias, \
                self.assertLogs("app.services.po_matcher", level="INFO") as logs:
            result = match_subcontractor('  ооо  "елка" ')
        self.assertEqual(result["po"]["id"], 27)
        self.assertEqual(result["entity_type"], "subcontractor")
        alias.assert_not_called()
        self.assertIn("SUBCONTRACTOR_EXACT_MATCH", logs.output[0])

    def test_fuzzy_uses_existing_organization_algorithm(self):
        with patch("app.services.po_matcher.get_all_po_types", return_value=[{"id": 27, "name": "ООО СтройМонтаж"}]), \
                patch("app.services.po_matcher.resolve_value_alias", return_value=None):
            result = match_subcontractor("ООО СтройМантаж")
            main = match_po("ООО СтройМантаж")
            self.assertEqual(result["status"], "similar")
            self.assertEqual(result["candidates"], main["candidates"])
            self.assertEqual(result["candidates"][0]["po"]["id"], 27)
            self.assertEqual(match_subcontractor("XYZ") ["status"], "new")


@unittest.skipUnless(os.getenv("DAILY_CONTROL_TEST_DB") == "1", "Requires isolated PostgreSQL tests")
class AliasTests(unittest.TestCase):
    setUp = references.ReferenceDatabaseTests.setUp

    def test_role_separation_repeat_conflict_update_and_resolve(self):
        route = "/api/value-aliases"
        source = ' ООО «Ёлка» '
        po = {"entity_type": "po", "source_value": source, "target_id": 1}
        sub = {**po, "entity_type": "subcontractor", "target_id": 2}
        self.assertEqual(control.http_request("POST", route, po)[0], 200)
        status, body = control.http_request("POST", route, sub)
        self.assertEqual(status, 200)
        self.assertEqual(body["item"]["target_name"], "ПО Б")
        alias_id = body["item"]["id"]
        self.assertFalse(control.http_request("POST", route, sub)[1]["created"])
        self.assertEqual(control.http_request("POST", route, {**sub, "target_id": 1})[0], 409)
        self.assertEqual(control.http_request("POST", route, {**sub, "target_id": 999})[0], 404)
        normalized = 'ооо "елка"'
        items = control.http_request("GET", route, query=urlencode({"entity_type": "subcontractor", "source_value": normalized}))[1]["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["target_id"], 2)
        with patch("app.services.po_matcher.get_all_po_types", return_value=[{"id": 1, "name": "ПО А"}, {"id": 2, "name": "ПО Б"}]):
            self.assertEqual(match_po(normalized)["po"]["id"], 1)
            with self.assertLogs("app.services.po_matcher", level="INFO") as logs:
                result = match_subcontractor(normalized)
            self.assertEqual(result["po"]["id"], 2)
            self.assertEqual(result["match_source"], "alias")
            self.assertIn("SUBCONTRACTOR_ALIAS_MATCH", logs.output[0])
            doc = document_result()
            doc["business_data"]["subcontractor"]["raw"] = source
            with patch("app.services.processing_service.match_po", return_value={"status": "found", "po": {"id": 1}}):
                report = prepare_report(doc)
            self.assertEqual(report["general_contractor_id"], 1)
            self.assertEqual(report["subcontractor_id"], 2)
            self.assertEqual(report["resolved_subcontractor"]["name"], "ПО Б")
        updated = control.http_request("PATCH", f"{route}/{alias_id}", {"target_id": 1})[1]["item"]
        self.assertEqual(updated["source_value"], source)
        self.assertEqual(updated["target_id"], 1)

    def test_po_alias_does_not_resolve_subcontractor(self):
        value_aliases.create_value_alias("po", "XYZ", 1)
        with patch("app.services.po_matcher.get_all_po_types", return_value=[{"id": 1, "name": "ПО А"}]):
            self.assertEqual(match_subcontractor("XYZ")["status"], "new")

    def test_new_organization_uses_existing_api_without_alias(self):
        self.conn.execute("ALTER TABLE po_types ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (START WITH 3)")
        status, body = control.http_request("POST", "/api/po-types", {"name": "Новая организация"})
        self.assertEqual(status, 200)
        self.assertEqual(body["item"]["name"], "Новая организация")
        self.assertEqual(self.conn.execute("SELECT count(*) FROM value_aliases").fetchone()[0], 0)
        rows = [{"id": row[0], "name": row[1]} for row in self.conn.execute("SELECT id,name FROM po_types").fetchall()]
        with patch("app.services.po_matcher.get_all_po_types", return_value=rows):
            self.assertEqual(match_subcontractor("Новая организация")["po"]["id"], body["item"]["id"])


@unittest.skipUnless(os.getenv("DAILY_CONTROL_TEST_DB") == "1", "Requires isolated PostgreSQL tests")
class FactTests(unittest.TestCase):
    setUp = control.DatabaseTests.setUp

    def fact(self, sub=None, child=None, filename="one.docx"):
        with self.conn.cursor() as cursor:
            return insert_fact(cursor, date(2026, 9, 24), {"employee_id": 1, "object_id": 1,
                "po_id": 1, "category_id": 1, "subobject_id": child, "subcontractor_id": sub}, filename, "b" * 64)

    def test_real_word_with_both_roles_saves_one_fact(self):
        from docx import Document
        from app.parsers.word_parser import read_document
        word = Document()
        table = word.add_table(rows=0, cols=4)
        for values in (("Объект", "Object A"), ("Генподрядчик", "PO A"),
                       ("Субподрядчик", "PO B"), ("Дата", "24.09.2026", "Направление контроля", "СК"),
                       ("Иванов Алексей Викторович", ""), ("Подпись", "")):
            for cell, value in zip(table.add_row().cells, values):
                cell.text = value
        word.save(self.path)
        with patch("app.services.daily_control_service.read_document", read_document), \
                patch("app.services.daily_control_service.prepare_report", prepare_report), \
                patch("app.parsers.word_parser.find_employee_by_full_name", return_value={"status": "found", "employee": {"id": 1}}), \
                patch("app.parsers.word_parser.match_object", return_value={"status": "found", "object": {"id": 1}}), \
                patch("app.services.po_matcher.get_all_po_types", return_value=[{"id": 1, "name": "PO A"}, {"id": 2, "name": "PO B"}]):
            status, result = control.http_request("POST", "/api/daily-control-results", {"path": str(self.path)})
        self.assertEqual(status, 200, result)
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual((result["results"][0]["po_id"], result["results"][0]["subcontractor_id"]), (1, 2))

    def test_unique_null_subcontractors_and_subobjects(self):
        children = self.conn.execute("INSERT INTO construction_subobjects(object_id,name) VALUES (1,'Child A'),(1,'Child B') RETURNING id").fetchall()
        ids = set()
        for child in (None, children[0][0], children[1][0]):
            for sub in (None, 1, 2):
                item = self.fact(sub, child)
                self.assertTrue(item["created"])
                ids.add(item["id"])
                duplicate = self.fact(sub, child, "renamed.docx")
                self.assertFalse(duplicate["created"])
                self.assertEqual(item["id"], duplicate["id"])
        self.assertEqual(len(ids), 9)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM daily_control_results").fetchone()[0], 9)

    def test_absent_source_saves_null_and_rejects_invented_target(self):
        for raw in (None, "", "  ", "-", "—"):
            self.document["business_data"]["subcontractor"].update(found=True, raw=raw)
            self.report.update(subcontractor_id=2, subcontractor_status="found")
            result = review_result(self.request)
            self.assertTrue(result["can_save"])
            self.assertIsNone(result["facts"][0]["subcontractor_id"])
            self.assertFalse(review_result(self.request.model_copy(update={"subcontractor_id": 2}))["can_save"])
        self.assertIsNone(review_result(self.request, save=True)["results"][0]["subcontractor_id"])

    def test_present_source_requires_resolution_and_valid_target_without_assignment(self):
        before = self.conn.execute("SELECT * FROM employee_assignments ORDER BY id").fetchall()
        self.document["business_data"]["subcontractor"].update(found=True, raw="PO B")
        self.report.update(subcontractor_id=None, subcontractor_status="similar")
        for status in ("similar", "new"):
            self.report["subcontractor_status"] = status
            self.assertFalse(review_result(self.request, save=True)["saved"])
        self.assertFalse(review_result(self.request.model_copy(update={"subcontractor_id": 999}))["can_save"])
        request = self.request.model_copy(update={"subcontractor_id": 2})
        # No subcontractor assignment exists for this role; only main PO is used.
        self.conn.execute("DELETE FROM employee_assignments WHERE po_id=2")
        remaining = self.conn.execute("SELECT * FROM employee_assignments ORDER BY id").fetchall()
        status, body = control.http_request("POST", "/api/daily-control-results", request.model_dump(mode="json"))
        self.assertEqual(status, 200, body)
        self.assertEqual(len(body["results"]), 1)
        fact = body["results"][0]
        self.assertEqual((fact["po_id"], fact["subcontractor_id"], fact["category_id"]), (1, 2, 1))
        self.assertEqual(fact["subcontractor_name"], "PO B")
        self.assertEqual(self.conn.execute("SELECT * FROM employee_assignments ORDER BY id").fetchall(), remaining)
        self.assertEqual(len(before), 3)

    def test_journal_names_filters_and_legacy_nulls(self):
        for sub in (None, 1, 2):
            self.fact(sub)
        query = "date_from=2026-09-24&date_to=2026-09-24"
        route = "/api/daily-control-results"
        for view in ("object", "employee"):
            status, result = control.http_request("GET", route, query=query + "&view=" + view + "&subcontractor_id=2")
            self.assertEqual(status, 200)
            self.assertEqual(result["summary"]["facts_count"], 1)
            self.assertEqual(result["items"][0]["subcontractor_name"], "PO B")
            self.assertEqual(result["filters"]["subcontractor_id"], 2)
            self.assertEqual(len(result["options"]["subcontractors"]), 2)
        all_items = get_journal(date(2026, 9, 24), date(2026, 9, 24))["items"]
        self.assertIsNone(all_items[0]["subcontractor_name"])
        self.assertEqual(control.http_request("GET", route, query=query + "&subcontractor_id=0")[0], 422)

    def test_saved_source_returns_history_without_reinterpretation(self):
        first = review_result(self.request, save=True)["results"][0]
        self.document["business_data"]["subcontractor"].update(found=True, raw="PO B")
        self.report.update(subcontractor_id=2, subcontractor_status="found")
        repeated = review_result(self.request, save=True)
        self.assertFalse(repeated["created"])
        self.assertEqual(repeated["results"][0]["id"], first["id"])
        self.assertIsNone(repeated["results"][0]["subcontractor_id"])

    def test_subcontractor_fk_preserves_history(self):
        self.fact(2)
        with self.assertRaises(psycopg.IntegrityError), self.conn.transaction():
            self.conn.execute("DELETE FROM po_types WHERE id=2")

    def test_migration_preserves_historic_rows_and_assignments_and_is_repeatable(self):
        self.fact()
        self.conn.execute("ALTER TABLE daily_control_results DROP COLUMN subcontractor_id CASCADE")
        self.conn.execute("ALTER TABLE daily_control_results ADD CONSTRAINT uq_daily_control_fact UNIQUE(report_date,employee_id,object_id,po_id,category_id)")
        self.conn.execute(Path("app/database/migrations/003_control_item_unique.sql").read_text(encoding="utf-8"))
        before = self.conn.execute("SELECT to_jsonb(r) FROM daily_control_results r ORDER BY id").fetchall()
        assignments = self.conn.execute("SELECT * FROM employee_assignments ORDER BY id").fetchall()
        apply_migration(self.conn)
        apply_migration(self.conn)
        self.assertEqual(before, self.conn.execute("SELECT to_jsonb(r)-'subcontractor_id' FROM daily_control_results r ORDER BY id").fetchall())
        self.assertEqual(assignments, self.conn.execute("SELECT * FROM employee_assignments ORDER BY id").fetchall())
        self.assertEqual(self.conn.execute("SELECT count(*) FROM daily_control_results WHERE subcontractor_id IS NOT NULL").fetchone()[0], 0)

    def test_migration_conflict_keeps_existing_constraint_and_rows(self):
        self.fact()
        self.conn.execute("ALTER TABLE daily_control_results DROP CONSTRAINT uq_daily_control_fact")
        self.conn.execute("ALTER TABLE daily_control_results ADD CONSTRAINT uq_daily_control_fact UNIQUE (report_date,employee_id,object_id,subobject_id,po_id,category_id)")
        self.conn.execute("""INSERT INTO daily_control_results(report_date,employee_id,object_id,po_id,category_id,source_file,source_sha256)
            SELECT report_date,employee_id,object_id,po_id,category_id,source_file,source_sha256 FROM daily_control_results""")
        before = self.conn.execute("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid='daily_control_results'::regclass AND conname='uq_daily_control_fact'").fetchone()
        with self.assertRaisesRegex(psycopg.errors.RaiseException, "Duplicate control facts"):
            apply_migration(self.conn)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM daily_control_results").fetchone()[0], 2)
        self.assertEqual(before, self.conn.execute("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid='daily_control_results'::regclass AND conname='uq_daily_control_fact'").fetchone())
