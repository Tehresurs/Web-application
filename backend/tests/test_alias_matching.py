import os
import unittest
from unittest.mock import patch

from app.services import employee_matcher, object_matcher, po_matcher
from app.services.processing_service import prepare_report
from test_processing import document_result
import test_references
from test_daily_control import http_request


class AliasMatchingTests(unittest.TestCase):
    def setUp(self):
        mock = patch.object(object_matcher, "get_subobjects", return_value=[])
        mock.start()
        self.addCleanup(mock.stop)

    def test_exact_alias_fuzzy_and_new_for_each_directory(self):
        for module, kind, loader, matcher, name_key in (
            (employee_matcher, "employee", "get_all_employees", "match_employee", "full_name"),
            (object_matcher, "object", "get_all_objects", "match_object", "name"),
            (po_matcher, "po", "get_all_po_types", "match_po", "name"),
        ):
            with self.subTest(kind=kind):
                target = {"id": 17, name_key: "Правильное название", "position_name": "Инженер"}
                with patch.object(module, loader, return_value=[target]), patch.object(module, "resolve_value_alias") as resolve:
                    exact = getattr(module, matcher)(target[name_key])
                    self.assertEqual(exact["status"], "found")
                    self.assertNotIn("match_source", exact)
                    resolve.assert_not_called()
                    resolve.return_value = {"id": 8, "target_id": 17, "target_name": target[name_key]}
                    alias = getattr(module, matcher)("Исходная ошибка")
                    self.assertEqual(alias[kind], target)
                    self.assertEqual(alias["match_source"], "alias")
                    self.assertEqual(alias["status"], "found")
                    self.assertEqual(alias["candidates"], [])
                    resolve.assert_called_with(kind, "Исходная ошибка")
                    resolve.return_value = None
                    self.assertEqual(getattr(module, matcher)("Правильное названи")['status'], "similar")
                    self.assertEqual(getattr(module, matcher)("XXXX")['status'], "new")
                    resolve.return_value = {"id": 9, "target_id": 999, "target_name": "Deleted"}
                    self.assertEqual(getattr(module, matcher)("XXXX")['status'], "new")

    def test_report_preserves_source_and_resolves_all_fields(self):
        document = document_result()
        for kind, entity in (("employee", {"id":17,"full_name":"Правильное ФИО"}), ("object", {"id":23,"name":"Правильный объект"})):
            document["business_data"][kind + "_match"] = {"status":"found",kind:entity,"match_source":"alias"}
        po = {"status":"found","po":{"id":31,"name":"Правильное ПО"},"match_source":"alias"}
        with patch("app.services.processing_service.match_po",return_value=po):
            report = prepare_report(document)
        self.assertEqual(report["employee_id"],17)
        self.assertEqual(report["object_id"],23)
        self.assertEqual(report["general_contractor_id"],31)
        self.assertEqual(report["full_name"],document["business_data"]["inspector"]["full_name"]["value"])
        self.assertEqual(report["object_name"],"Объект")
        self.assertEqual(report["resolved_employee"]["name"],"Правильное ФИО")
        self.assertEqual(report["resolved_object"]["name"],"Правильный объект")
        self.assertEqual(report["resolved_general_contractor"]["name"],"Правильное ПО")
        self.assertEqual(report["status"],"ok")
        self.assertEqual(report["problems"],[])


@unittest.skipUnless(os.getenv("DAILY_CONTROL_TEST_DB") == "1", "Requires isolated PostgreSQL tests")
class AliasRepeatTests(unittest.TestCase):
    setUp = test_references.ReferenceDatabaseTests.setUp

    def test_save_then_repeat_subobject_and_subcontractor(self):
        from app.repositories.subobjects import create_subobject
        child = create_subobject(1, "Подъезд к объекту")
        source = "Подезд к объекту"
        status, body = http_request("POST", "/api/value-aliases", {
            "entity_type": "subobject", "source_value": source, "target_id": child["id"],
        })
        self.assertEqual(status, 200)
        self.assertEqual(body["item"]["source_value"], source)
        with patch.object(object_matcher, "get_all_objects", return_value=[{"id":1,"name":"Объект А"}]), \
                patch.object(object_matcher, "get_subobjects", return_value=[child]):
            result = object_matcher.match_object(source)
        self.assertEqual(result["match_source"], "subobject_alias")
        self.assertEqual(result["subobject_id"], child["id"])
        status, body = http_request("POST", "/api/value-aliases", {
            "entity_type": "subcontractor", "source_value": "Исходная организация", "target_id": 1,
        })
        self.assertEqual(status, 200)
        with patch.object(po_matcher, "get_all_po_types", return_value=[{"id":1,"name":"ПО А"}]):
            result = po_matcher.match_subcontractor("Исходная организация")
        self.assertEqual(result["status"], "found")
        self.assertEqual(result["match_source"], "alias")
        self.assertEqual(result["po"]["id"], 1)

    def test_save_then_repeat_for_all_entity_types(self):
        for module, kind, loader, matcher, name_key in (
            (employee_matcher,"employee","get_all_employees","match_employee","full_name"),
            (object_matcher,"object","get_all_objects","match_object","name"),
            (po_matcher,"po","get_all_po_types","match_po","name"),
        ):
            with self.subTest(kind=kind):
                target = {"id":1,name_key:"Правильное название"}
                with patch.object(module,loader,return_value=[target]):
                    self.assertEqual(getattr(module,matcher)("Правильное названи")["status"],"similar")
                    status, body = http_request("POST","/api/value-aliases",{
                        "entity_type":kind,"source_value":"Правильное названи","target_id":1})
                    self.assertEqual(status,200)
                    self.assertTrue(body["created"])
                    for _ in range(2):
                        match = getattr(module,matcher)("  ПРАВИЛЬНОЕ названи  ")
                        self.assertEqual(match["match_source"],"alias")
                        self.assertEqual(match[kind]["id"],1)
                    self.assertEqual(http_request("POST","/api/value-aliases",{
                        "entity_type":kind,"source_value":"правильное названи","target_id":2})[0],409)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM value_aliases").fetchone()[0],3)
