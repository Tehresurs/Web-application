import asyncio
import json
import os
import tempfile
import unittest
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError

from app.api.daily_control import journal, review_response
from app.database.db import get_connection
from app.repositories.daily_control import get_journal, insert_fact
from app.services.daily_control_service import ReviewRequest, review_result


def http_request(method, path, payload=None, query=""):
    from app.main import app

    async def run():
        messages = []

        async def receive():
            return {"type": "http.request", "body": json.dumps(payload or {}).encode(), "more_body": False}

        async def send(message):
            messages.append(message)

        await app({"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                   "method": method, "scheme": "http", "path": path, "raw_path": path.encode(),
                   "query_string": query.encode(), "root_path": "",
                   "headers": [(b"content-type", b"application/json")],
                   "server": ("test", 80), "client": ("test", 1234)}, receive, send)
        return messages[0]["status"], json.loads(b"".join(item.get("body", b"") for item in messages[1:]))

    return asyncio.run(run())


class RequestTests(unittest.TestCase):
    def test_http_validation_and_conflict_serialization(self):
        route = "/api/daily-control-results"
        for query in ("date_from=bad&date_to=2026-09-30",
                      "date_from=2026-09-01&date_to=2026-09-30&employee_id=0",
                      "date_from=2026-09-01&date_to=2026-09-30&view=invalid"):
            self.assertEqual(http_request("GET", route, query=query)[0], 422)
        with patch("app.api.daily_control.review_result", return_value={
            "saved": False, "can_save": False, "report_date": date(2026, 9, 24),
            "problems": ["Назначение не выбрано"],
        }):
            status, body = http_request("POST", route, {"path": "report.docx"})
            self.assertEqual(status, 409)
            self.assertEqual(body["detail"]["report_date"], "2026-09-24")

    def test_client_cannot_supply_date_or_can_save(self):
        for extra in ({"can_save": True}, {"report_date": "2026-09-27"}):
            with self.assertRaises(ValidationError):
                ReviewRequest(path="report.docx", **extra)
        with self.assertRaises(ValidationError):
            ReviewRequest(path="report.docx", employee_id=0)

    def test_period_and_unresolved_save(self):
        with self.assertRaises(HTTPException) as error:
            journal(date(2026, 10, 1), date(2026, 9, 1))
        self.assertEqual(error.exception.status_code, 400)
        with patch("app.api.daily_control.review_result", return_value={
            "can_save": False, "saved": False, "problems": ["Назначение не выбрано"],
        }), self.assertRaises(HTTPException) as error:
            review_response(ReviewRequest(path="report.docx"), True)
        self.assertEqual(error.exception.status_code, 409)


@unittest.skipUnless(os.getenv("DAILY_CONTROL_TEST_DB") == "1", "Set DAILY_CONTROL_TEST_DB=1 for isolated PostgreSQL tests")
class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.conn = get_connection()
        self.addCleanup(self.conn.close)
        self.addCleanup(self.conn.rollback)
        schema = "test_daily_control_" + uuid4().hex
        # Everything, including this isolated schema, is rolled back at test end.
        self.conn.execute(f'CREATE SCHEMA "{schema}"')
        self.conn.execute(f'SET LOCAL search_path TO "{schema}"')
        self.conn.execute("""
            CREATE TABLE employees(id BIGINT PRIMARY KEY, full_name TEXT);
            CREATE TABLE construction_objects(id BIGINT PRIMARY KEY, name TEXT);
            CREATE TABLE po_types(id BIGINT PRIMARY KEY, name TEXT);
            CREATE TABLE object_categories(id BIGINT PRIMARY KEY, name TEXT);
            CREATE TABLE employee_assignments(
                id BIGINT PRIMARY KEY, employee_id BIGINT, object_id BIGINT,
                po_id BIGINT, category_id BIGINT);
            INSERT INTO employees VALUES (1, 'Engineer A'), (2, 'Engineer B');
            INSERT INTO construction_objects VALUES (1, 'Object A'), (2, 'Object B');
            INSERT INTO po_types VALUES (1, 'PO A'), (2, 'PO B');
            INSERT INTO object_categories VALUES (1, 'Category A'), (2, 'Category B');
            INSERT INTO employee_assignments VALUES
                (1, 1, 1, 1, 1), (2, 1, 1, 2, 2), (3, 2, 2, 1, 1);
        """)
        sql = Path("app/database/migrations/001_daily_control_results.sql").read_text(encoding="utf-8")
        self.conn.execute(sql)
        self.conn.execute(sql)  # migration is repeatable
        self.conn.execute(Path("app/database/migrations/002_subobjects_aliases.sql").read_text(encoding="utf-8"))
        self.conn.execute(Path("app/database/migrations/003_control_item_unique.sql").read_text(encoding="utf-8"))
        self.conn.execute(Path("app/database/migrations/004_subcontractor.sql").read_text(encoding="utf-8"))

        @contextmanager
        def connection():
            with self.conn.transaction():
                yield self.conn

        for target in ("app.services.daily_control_service.get_connection", "app.repositories.daily_control.get_connection"):
            mock = patch(target, connection)
            mock.start()
            self.addCleanup(mock.stop)
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "report.docx"
        self.path.write_bytes(b"immutable report bytes")
        self.request = ReviewRequest(path=str(self.path))
        self.document = {"filename": "report.docx", "business_data": {
            "report_date": {"found": True, "value": "2026-09-24"},
            "inspector": {"found": True}, "object": {"found": True},
            "general_contractor": {"found": True}, "subcontractor": {"found": False},
        }}
        self.report = {
            "employee_id": 1, "object_id": 1, "general_contractor_id": 1,
            "employee_status": "found", "object_status": "found", "general_contractor_status": "found",
        }
        for target, value in (("read_document", self.document), ("prepare_report", self.report)):
            mock = patch("app.services.daily_control_service." + target, return_value=value)
            mock.start()
            self.addCleanup(mock.stop)

    def test_manual_save_date_and_duplicate(self):
        check = review_result(self.request)
        self.assertTrue(check["can_save"])
        self.assertEqual(self.conn.execute("SELECT count(*) FROM daily_control_results").fetchone()[0], 0)
        first = review_result(self.request, save=True)
        second = review_result(self.request, save=True)
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertFalse(second["can_save"])
        self.assertEqual(first["results"][0]["id"], second["results"][0]["id"])
        row = self.conn.execute("SELECT report_date, source_file FROM daily_control_results").fetchone()
        self.assertEqual(row, (date(2026, 9, 24), "report.docx"))
        self.path.write_bytes(b"repacked copy of same logical report")
        self.assertFalse(review_result(self.request, save=True)["created"])
        self.assertEqual(self.conn.execute("SELECT count(*) FROM daily_control_results").fetchone()[0], 1)

    def test_real_docx_snapshot_and_http_roundtrip(self):
        from docx import Document
        from app.parsers.word_parser import read_document
        from app.services.processing_service import prepare_report
        document = Document()
        table = document.add_table(rows=0, cols=4)
        for values in [
            ["Объект", "Object A", "", ""],
            ["Генподрядчик", "PO A", "", ""],
            ["Дата", "24.09.2026", "Направление контроля", "СК"],
            ["Иванов Алексей Викторович", "", "", ""],
            ["Подпись", "", "", ""],
        ]:
            for cell, value in zip(table.add_row().cells, values):
                cell.text = value
        document.save(self.path)
        with patch("app.services.daily_control_service.read_document", read_document), \
                patch("app.services.daily_control_service.prepare_report", prepare_report), \
                patch("app.parsers.word_parser.find_employee_by_full_name", return_value={
                    "status": "found", "employee": {"id": 1, "position_name": "Инженер"}}), \
                patch("app.parsers.word_parser.match_object", return_value={"status": "found", "object": {"id": 1}}), \
                patch("app.services.processing_service.match_po", return_value={"status": "found", "po": {"id": 1}}):
            route = "/api/daily-control-results"
            status, body = http_request("POST", route + "/check", {"path": str(self.path)})
            self.assertEqual(status, 200)
            self.assertTrue(body["can_save"])
            status, body = http_request("POST", route, {"path": str(self.path)})
            self.assertEqual(status, 200)
            self.assertTrue(body["saved"])
            self.assertEqual(body["report_date"], "2026-09-24")
            status, body = http_request("GET", route, query="date_from=2026-09-24&date_to=2026-09-24&view=employee")
            self.assertEqual(status, 200)
            self.assertEqual(body["groups"][0]["items"][0]["dates"], ["2026-09-24"])

    def test_all_required_fields_and_unresolved_entities(self):
        for key in ("report_date", "inspector", "object", "general_contractor"):
            self.document["business_data"][key]["found"] = False
            self.assertFalse(review_result(self.request, save=True)["saved"])
            self.document["business_data"][key]["found"] = True
        for key in ("employee_status", "object_status", "general_contractor_status"):
            for status in ("similar", "new", "not_checked"):
                self.report[key] = status
                self.assertFalse(review_result(self.request)["can_save"])
            self.report[key] = "found"
        self.document["business_data"]["report_date"]["value"] = "31.02.2026"
        self.assertFalse(review_result(self.request)["can_save"])
        self.assertEqual(self.conn.execute("SELECT count(*) FROM daily_control_results").fetchone()[0], 0)

    def test_explicit_resolution_requires_matching_assignment(self):
        self.report["employee_status"] = "similar"
        self.assertTrue(review_result(self.request.model_copy(update={"employee_id": 1}))["can_save"])
        self.assertFalse(review_result(self.request.model_copy(update={"employee_id": 999}))["can_save"])
        self.assertFalse(review_result(self.request.model_copy(update={"employee_id": 2}))["can_save"])

    def test_ambiguous_and_stale_assignments(self):
        self.conn.execute("INSERT INTO employee_assignments VALUES (4, 1, 1, 1, 2)")
        self.assertFalse(review_result(self.request)["can_save"])
        chosen = self.request.model_copy(update={"assignments": {1: 4}})
        self.assertTrue(review_result(chosen)["can_save"])
        self.conn.execute("DELETE FROM employee_assignments WHERE id = 4")
        self.assertFalse(review_result(chosen, save=True)["saved"])

    def test_one_fact_with_po_and_subcontractor(self):
        self.document["business_data"]["subcontractor"].update(found=True, raw="PO B")
        self.report.update(subcontractor_id=2, subcontractor_status="new")
        self.assertFalse(review_result(self.request, save=True)["saved"])
        self.report["subcontractor_status"] = "found"
        result = review_result(self.request, save=True)
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual((result["results"][0]["po_id"], result["results"][0]["subcontractor_id"]), (1, 2))
        data = get_journal(date(2026, 9, 24), date(2026, 9, 24))
        self.assertEqual(data["summary"], {"facts_count": 1, "objects_count": 1, "subobjects_count": 0, "employees_count": 1, "days_count": 1})
        self.assertEqual(data["groups"][0]["items"][0]["days_count"], 1)

    def test_failure_rolls_back_whole_report(self):
        self.document["business_data"]["subcontractor"].update(found=True, raw="PO B")
        self.report.update(subcontractor_id=2, subcontractor_status="found")
        def insert(*args):
            insert_fact(*args)
            raise RuntimeError("Simulated write failure after insert")

        with patch("app.services.daily_control_service.insert_fact", side_effect=insert):
            with self.assertRaises(RuntimeError):
                review_result(self.request, save=True)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM daily_control_results").fetchone()[0], 0)

    def test_filters_views_and_dates(self):
        with self.conn.cursor() as cursor:
            for day, employee, obj in ((24, 1, 1), (25, 1, 2), (26, 2, 2)):
                insert_fact(cursor, date(2026, 9, day), {"employee_id": employee, "object_id": obj,
                            "po_id": 1, "category_id": 1}, "test.docx", str(day) * 32)
        for employee, obj, count in ((None, None, 3), (1, None, 2), (None, 2, 2), (1, 2, 1)):
            for view in ("object", "employee"):
                result = get_journal(date(2026, 9, 24), date(2026, 9, 26), employee, obj, view)
                self.assertEqual(result["summary"]["facts_count"], count)
        result = get_journal(date(2026, 9, 25), date(2026, 9, 25), 1, 2, "employee")
        self.assertEqual(result["groups"][0]["items"][0]["dates"], [date(2026, 9, 25)])
        self.assertEqual(get_journal(date(2026, 10, 1), date(2026, 10, 31))["groups"], [])

    def test_foreign_keys_preserve_history(self):
        review_result(self.request, save=True)
        import psycopg
        with self.assertRaises(psycopg.IntegrityError):
            with self.conn.transaction():
                self.conn.execute("DELETE FROM employees WHERE id = 1")


if __name__ == "__main__":
    unittest.main()
