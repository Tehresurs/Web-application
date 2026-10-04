import os
import unittest
from datetime import date

import test_daily_control
from app.services.daily_control_service import ReviewRequest, review_result
from app.repositories.daily_control import get_journal, insert_fact, summarize_journal
from app.repositories.directory_errors import DirectoryConflict


@unittest.skipUnless(os.getenv("DAILY_CONTROL_TEST_DB") == "1", "Requires isolated PostgreSQL tests")
class SubobjectControlTests(unittest.TestCase):
    setUp = test_daily_control.DatabaseTests.setUp

    def child(self, object_id=1, name="Подъезд"):
        return self.conn.execute("INSERT INTO construction_subobjects(object_id,name) VALUES(%s,%s) RETURNING id",(object_id,name)).fetchone()[0]

    def test_save_subobject_uses_parent_assignment(self):
        child = self.child()
        self.report["subobject_id"] = child
        result = review_result(self.request,save=True)
        self.assertTrue(result["saved"])
        self.assertEqual(result["facts"][0]["assignment_id"],1)
        row = self.conn.execute("SELECT employee_id,object_id,subobject_id,po_id,category_id FROM daily_control_results").fetchone()
        self.assertEqual(row,(1,1,child,1,1))
        journal = get_journal(date(2026,9,1),date(2026,9,30))
        self.assertEqual(journal["items"][0]["subobject_name"],"Подъезд")
        self.assertEqual(journal["summary"]["objects_count"],1)
        self.assertEqual(journal["summary"]["subobjects_count"],1)

    def test_normal_and_explicit_clear_save_null(self):
        self.report["subobject_id"] = self.child()
        request = ReviewRequest(path=str(self.path),object_id=1,subobject_id=None)
        self.assertTrue(review_result(request,save=True)["saved"])
        self.assertIsNone(self.conn.execute("SELECT subobject_id FROM daily_control_results").fetchone()[0])

    def test_invalid_inactive_and_wrong_parent(self):
        child = self.child(object_id=2)
        for value in (999,child):
            self.assertFalse(review_result(ReviewRequest(path=str(self.path),subobject_id=value))["can_save"])
        child = self.child()
        self.conn.execute("UPDATE construction_subobjects SET is_active=FALSE WHERE id=%s",(child,))
        self.assertFalse(review_result(ReviewRequest(path=str(self.path),subobject_id=child))["can_save"])

    def test_two_subobjects_are_separate_facts(self):
        first, second = self.child(), self.child(name="Platform")
        self.report["subobject_id"] = first
        self.assertTrue(review_result(self.request,save=True)["saved"])
        self.path.write_bytes(b"different source report")
        self.report["subobject_id"] = second
        result = review_result(self.request,save=True)
        self.assertTrue(result["saved"])
        self.assertEqual(self.conn.execute("SELECT subobject_id FROM daily_control_results ORDER BY id").fetchall(),[(first,),(second,)])

    def test_old_rows_remain_readable(self):
        review_result(self.request,save=True)
        item = get_journal(date(2026,9,1),date(2026,9,30))["items"][0]
        self.assertIsNone(item["subobject_id"])
        self.assertIsNone(item["subobject_name"])


class SubobjectSummaryTests(unittest.TestCase):
    def test_three_children_count_as_one_parent(self):
        rows=[{"id":n,"object_id":5,"object_name":"Объект","employee_id":1,"full_name":"Инженер",
               "report_date":date(2026,9,24),"subobject_id":n} for n in (11,12,13)]
        summary=summarize_journal(rows,"object")["summary"]
        self.assertEqual((summary["objects_count"],summary["subobjects_count"],summary["facts_count"]),(1,3,3))
