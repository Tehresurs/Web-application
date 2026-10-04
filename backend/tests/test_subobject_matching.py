import unittest
from unittest.mock import patch

from app.services import object_matcher as matcher
from app.services.processing_service import prepare_report
from test_processing import document_result


class SubobjectMatchingTests(unittest.TestCase):
    def setUp(self):
        self.parent = {"id":5,"name":"Обустройство куста скважин №55"}
        self.child = {"id":12,"object_id":5,"name":"Подъезд к кусту скважин №55",
                      "object_name":self.parent["name"],"is_active":True}
        for name, value in (("get_all_objects",[self.parent]),("get_subobjects",[self.child]),("resolve_value_alias",None)):
            mock = patch.object(matcher,name,return_value=value)
            setattr(self,name,mock.start())
            self.addCleanup(mock.stop)

    def test_exact_parent_precedes_all_aliases(self):
        result = matcher.match_object(self.parent["name"])
        self.assertEqual(result["object"],self.parent)
        self.assertIsNone(result.get("subobject_id"))
        self.resolve_value_alias.assert_not_called()

    def test_object_alias_precedes_subobject(self):
        self.resolve_value_alias.return_value = {"id":1,"target_id":5,"target_name":self.parent["name"]}
        result = matcher.match_object(self.child["name"])
        self.assertEqual(result["match_source"],"alias")
        self.assertIsNone(result.get("subobject_id"))
        self.get_subobjects.assert_not_called()

    def test_exact_child_parent_and_raw_report(self):
        with self.assertLogs(matcher.__name__,level="INFO") as logs:
            result = matcher.match_object(self.child["name"])
        self.assertIn("SUBOBJECT_EXACT_MATCH",logs.output[0])
        self.assertEqual(result["object"],self.parent)
        self.assertEqual(result["subobject_id"],12)
        doc = document_result()
        doc["business_data"]["object_match"] = result
        doc["business_data"]["object"]["raw"] = self.child["name"]
        with patch("app.services.processing_service.match_po",return_value={"status":"found","po":{"id":1}}):
            report = prepare_report(doc)
        self.assertEqual(report["object_name"],self.child["name"])
        self.assertEqual(report["resolved_object"],self.parent)
        self.assertEqual(report["resolved_subobject"]["id"],12)
        self.assertEqual(report["status"],"ok")

    def test_child_alias(self):
        self.resolve_value_alias.side_effect = lambda kind, value: {"id":1,"target_id":12} if kind == "subobject" else None
        with self.assertLogs(matcher.__name__,level="INFO") as logs:
            result = matcher.match_object("Ошибка в названии")
        self.assertEqual(result["match_source"],"subobject_alias")
        self.assertEqual((result["object_id"],result["subobject_id"]),(5,12))
        self.assertIn("SUBOBJECT_ALIAS_MATCH",logs.output[0])

    def test_fuzzy_parent(self):
        result = matcher.match_object("Обустройсто куста скважин №55")
        self.assertEqual(result["status"],"similar")
        candidate = next(c for c in result["candidates"] if c["entity_kind"] == "object")
        self.assertEqual(candidate["object_id"],5)
        self.assertIsNone(candidate["subobject_id"])

    def test_fuzzy_child(self):
        result = matcher.match_object("Подезд к кусту скважин №55")
        self.assertEqual(result["status"],"similar")
        child = next(c for c in result["candidates"] if c["entity_kind"] == "subobject")
        self.assertEqual(child["subobject_id"],12)
        self.assertEqual(child["object_name"],self.parent["name"])
        self.assertGreaterEqual(child["score"],matcher.SIMILARITY_THRESHOLD)

    def test_ambiguous_child_is_not_automatically_selected(self):
        self.get_subobjects.return_value = [self.child,{**self.child,"id":13,"object_id":6,"object_name":"Другой родитель"}]
        result = matcher.match_object(self.child["name"])
        self.assertEqual(result["status"],"similar")
        self.assertEqual({c["object_id"] for c in result["candidates"] if c["entity_kind"] == "subobject"},{5,6})

    def test_unknown_remains_new(self):
        result = matcher.match_object("Совсем неизвестное")
        self.assertEqual(result["status"],"new")
