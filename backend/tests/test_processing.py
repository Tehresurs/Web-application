import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from docx import Document

from app.main import app, ProcessFolderRequest, process_reports
from app.services.processing_service import build_report_result, get_field_value, prepare_report, process_folder


def document_result(employee_status="found", object_status="found"):
    def field(value):
        return {"found": True, "raw": value, "value": value}

    return {
        "filename": "report.docx",
        "business_data": {
            "inspector": {"found": True, "full_name": {"value": "Иванов Алексей Викторович"}},
            "employee_match": {"status": employee_status, "employee": {"id": 12, "position_name": "Мастер"}},
            "object_match": {"status": object_status, "object": {"id": 34}},
            "report_date": field("19.09.2026"),
            "object": field("Объект"),
            "general_contractor": field("Генподрядчик"),
            "subcontractor": field(""),
        },
    }


class ProcessingTests(unittest.TestCase):
    def test_http_json_contract(self):
        async def request(payload):
            messages = []

            async def receive():
                return {"type": "http.request", "body": json.dumps(payload).encode(), "more_body": False}

            async def send(message):
                messages.append(message)

            await app({
                "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                "method": "POST", "scheme": "http", "path": "/api/process-folder",
                "raw_path": b"/api/process-folder", "query_string": b"",
                "root_path": "", "headers": [(b"content-type", b"application/json")],
                "server": ("test", 80), "client": ("test", 1234),
            }, receive, send)
            return messages[0]["status"], json.loads(b"".join(
                message.get("body", b"") for message in messages[1:]))

        with tempfile.TemporaryDirectory() as directory:
            status, result = asyncio.run(request({"path": directory}))
            self.assertEqual(status, 200)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["total"], 0)
            self.assertEqual(result["reports"], [])
            self.assertEqual(result["processing_errors"], [])
        self.assertEqual(asyncio.run(request({}))[0], 422)
        with patch("app.main.process_folder", side_effect=ValueError("Invalid folder")):
            status, result = asyncio.run(request({"path": "missing"}))
            self.assertEqual(status, 400)
            self.assertEqual(result, {"status": "error", "message": "Invalid folder"})
        with patch("app.main.process_folder", side_effect=RuntimeError("Processing failed")):
            status, result = asyncio.run(request({"path": "folder"}))
            self.assertEqual(status, 500)
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["message"], "Ошибка обработки отчётов")
            self.assertEqual(result["details"], "Processing failed")

    def test_mapping_and_statuses(self):
        for employee, obj, expected in [
            ("found", "found", "ok"), ("found", "new", "warning"),
            ("similar", "found", "warning"), ("new", "similar", "warning"),
        ]:
            with self.subTest(employee=employee, obj=obj):
                result = build_report_result(document_result(employee, obj))
                self.assertEqual(result["status"], expected)
                self.assertEqual(result["full_name"], "Иванов Алексей Викторович")
                self.assertEqual(result["report_date"], "19.09.2026")
        for missing in ("report_date", "object", "inspector", "general_contractor"):
            with self.subTest(missing=missing):
                document = document_result(object_status="new")
                document["business_data"][missing]["found"] = False
                self.assertEqual(prepare_report(document)["status"], "error")

    def test_ids_nullable_fields_and_raw_values(self):
        document = document_result()
        document["business_data"]["report_date"]["value"] = "2026-09-19"
        result = prepare_report(document)
        self.assertEqual((result["employee_id"], result["object_id"]), (12, 34))
        self.assertEqual(result["report_date"], "19.09.2026")
        self.assertEqual(get_field_value(document["business_data"]["report_date"]), "2026-09-19")
        self.assertIsNone(get_field_value({"found": False, "raw": "ignored"}, raw=True))
        document["business_data"]["inspector"]["found"] = False
        document["business_data"]["employee_match"]["status"] = "not_checked"
        document["business_data"]["object_match"]["status"] = "similar"
        result = prepare_report(document)
        for key in ("full_name", "employee_id", "position", "object_id"):
            self.assertIsNone(result[key])

    def test_sorting_by_name(self):
        with tempfile.TemporaryDirectory() as directory:
            for filename in ("a.docx", "b.docx", "c.docx"):
                (Path(directory) / filename).touch()
            documents = [document_result() for _ in range(3)]
            for document, name in zip(documents, ("Яковлев Иван Петрович", "борисов Иван Петрович", "Алексеев Иван Петрович")):
                document["business_data"]["inspector"]["full_name"]["value"] = name
            with patch("app.services.processing_service.read_document", side_effect=documents):
                result = process_folder(directory)
            self.assertEqual([r["full_name"].split()[0] for r in result["reports"]],
                             ["Алексеев", "борисов", "Яковлев"])

    def test_real_docx_and_corrupt_file(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            document = Document()
            table = document.add_table(rows=0, cols=4)
            for values in [
                ["Объект", "Тестовый объект", "", ""],
                ["Генподрядчик", "Строймонтаж", "", ""],
                ["Дата", "19.09.2026", "Направление контроля", "СК"],
                ["Субподрядчик", "СПК", "", ""],
                ["Иванов Алексей Викторович", "", "", ""],
                ["Подпись", "", "", ""],
            ]:
                for cell, value in zip(table.add_row().cells, values):
                    cell.text = value
            document.save(folder / "valid.DOCX")
            (folder / "broken.docx").write_text("not a document")
            (folder / "~$locked.docx").write_text("lock")
            (folder / "directory.docx").mkdir()
            with patch("app.parsers.word_parser.find_employee_by_full_name", return_value={
                "status": "found", "employee": {"position_name": "Мастер"},
            }), patch("app.parsers.word_parser.match_object", return_value={"status": "new"}):
                result = process_reports(ProcessFolderRequest(path=directory))
            json.dumps(result, ensure_ascii=False)
            self.assertEqual([result[key] for key in ("total", "ok", "warning", "error")], [2, 0, 1, 1])
            self.assertEqual(len(result["reports"]) + len(result["processing_errors"]), result["total"])
            self.assertEqual(result["processing_errors"][0]["filename"], "broken.docx")
            self.assertTrue(result["processing_errors"][0]["error"])
            valid = next(report for report in result["reports"] if report["filename"] == "valid.DOCX")
            self.assertEqual(valid["full_name"], "Иванов Алексей Викторович")
            self.assertEqual(valid["position"], "Мастер")
            self.assertEqual(valid["subcontractor"], "СПК")

    def test_folder_validation_and_empty_result(self):
        with tempfile.TemporaryDirectory() as directory:
            result = process_folder(directory)
            self.assertEqual(result["total"], 0)
            self.assertEqual(result["reports"], [])
            self.assertEqual(process_reports(ProcessFolderRequest(path=directory + "/missing")).status_code, 400)
            file_path = Path(directory) / "file.txt"
            file_path.touch()
            self.assertEqual(process_reports(ProcessFolderRequest(path=str(file_path))).status_code, 400)
        self.assertEqual(process_reports(ProcessFolderRequest(path=" ")).status_code, 400)


if __name__ == "__main__":
    unittest.main()
