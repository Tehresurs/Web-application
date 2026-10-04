import os
import unittest
from datetime import date
from unittest.mock import patch

import psycopg
import test_daily_control
from app.database.migrate_control_item_unique import apply_migration
from app.repositories.daily_control import insert_fact, get_journal
from app.services.daily_control_service import ReviewRequest, review_result
from app.services.report_dates import parsed_date


@unittest.skipUnless(os.getenv("DAILY_CONTROL_TEST_DB") == "1", "Requires isolated PostgreSQL tests")
class FinalizationTests(unittest.TestCase):
    setUp = test_daily_control.DatabaseTests.setUp

    def child(self, name="A", parent=1):
        return self.conn.execute("INSERT INTO construction_subobjects(object_id,name) VALUES(%s,%s) RETURNING id",(parent,name)).fetchone()[0]

    def fact(self, subobject_id=None, day=24, employee=1, obj=1, po=1, category=1, source="report.docx"):
        with self.conn.cursor() as cursor:
            return insert_fact(cursor,date(2026,9,day),{"employee_id":employee,"object_id":obj,
                "subobject_id":subobject_id,"po_id":po,"category_id":category},source,"a"*64)

    def test_parent_children_and_duplicates(self):
        a,b=self.child(),self.child("B")
        parent,first,second=self.fact(),self.fact(a),self.fact(b)
        self.assertEqual(len({r["id"] for r in (parent,first,second)}),3)
        self.assertEqual(parent["control_item_type"],"object")
        self.assertIsNone(parent["subobject_id"])
        self.assertEqual(first["control_item_type"],"subobject")
        self.assertEqual(first["control_item_name"],"A")
        self.assertEqual(first["object_id"],1)
        for child,original in ((None,parent),(a,first),(b,second)):
            duplicate=self.fact(child,source="renamed.docx")
            self.assertFalse(duplicate["created"])
            self.assertEqual(duplicate["id"],original["id"])
            self.assertEqual(duplicate["source_file"],"report.docx")
        summary=get_journal(date(2026,9,1),date(2026,9,30))["summary"]
        self.assertEqual((summary["facts_count"],summary["objects_count"],summary["subobjects_count"]),(3,1,2))

    def test_each_business_dimension_separates_facts(self):
        rows=[self.fact(),self.fact(day=25),self.fact(employee=2),self.fact(obj=2),
              self.fact(po=2),self.fact(category=2)]
        self.assertEqual(len({r["id"] for r in rows}),6)

    def test_wrong_pair_rejected_in_repository(self):
        with self.assertRaises(ValueError):
            self.fact(self.child(parent=2))
        self.assertEqual(self.conn.execute("SELECT count(*) FROM daily_control_results").fetchone()[0],0)

    def test_saved_source_returns_enriched_result_and_is_idempotent(self):
        self.report["subobject_id"]=self.child()
        first=review_result(self.request,save=True)
        again=review_result(self.request,save=True)
        self.assertTrue(first["created"])
        self.assertFalse(again["created"])
        for result in (first,again):
            item=result["results"][0]
            for key in ("id","report_date","employee_id","employee_name","object_id","subobject_id",
                        "control_item_type","control_item_name","po_id","category_id","source_file"):
                self.assertIn(key,item)
            self.assertEqual(item["report_date"],date(2026,9,24))
        self.assertEqual(first["results"][0]["id"],again["results"][0]["id"])

    def test_alias_ids_remain_target_ids(self):
        for kind in ("object","subobject"):
            with self.subTest(kind=kind):
                self.path.write_bytes(kind.encode())
                self.report["object_match_source"]="alias" if kind=="object" else "subobject_alias"
                self.report["subobject_id"]=None if kind=="object" else self.child()
                result=review_result(self.request,save=True)
                self.assertTrue(result["saved"])
                self.assertEqual(result["results"][0]["object_id"],1)
                self.assertEqual(result["results"][0]["subobject_id"],self.report["subobject_id"])

    def test_alias_conflict_blocks_save(self):
        request=ReviewRequest(path=str(self.path),unresolved_aliases=["object"])
        result=review_result(request,save=True)
        self.assertFalse(result["saved"])
        self.assertFalse(result["can_save"])
        self.assertEqual(self.conn.execute("SELECT count(*) FROM daily_control_results").fetchone()[0],0)

    def test_migration_preserves_rows_and_is_repeatable(self):
        self.fact()
        self.conn.execute("ALTER TABLE daily_control_results DROP CONSTRAINT uq_daily_control_fact")
        self.conn.execute("ALTER TABLE daily_control_results ADD CONSTRAINT uq_daily_control_fact UNIQUE(report_date,employee_id,object_id,po_id,category_id)")
        before=self.conn.execute("SELECT to_jsonb(r) FROM daily_control_results r").fetchall()
        apply_migration(self.conn)
        apply_migration(self.conn)
        self.assertEqual(before,self.conn.execute("SELECT to_jsonb(r) FROM daily_control_results r").fetchall())
        self.assertIn("NULLS NOT DISTINCT",self.conn.execute("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid='daily_control_results'::regclass AND conname='uq_daily_control_fact'").fetchone()[0])

    def test_migration_rejects_bad_parent_without_dropping_old_constraint(self):
        self.fact()
        bad=self.child(parent=2)
        self.conn.execute("UPDATE daily_control_results SET subobject_id=%s",(bad,))
        before=self.conn.execute("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid='daily_control_results'::regclass AND conname='uq_daily_control_fact'").fetchone()
        with self.assertRaises(psycopg.errors.RaiseException):
            apply_migration(self.conn)
        self.assertEqual(before,self.conn.execute("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid='daily_control_results'::regclass AND conname='uq_daily_control_fact'").fetchone())

    def test_migration_rejects_null_duplicates_without_deleting_rows(self):
        self.fact()
        self.conn.execute("ALTER TABLE daily_control_results DROP CONSTRAINT uq_daily_control_fact")
        self.conn.execute("ALTER TABLE daily_control_results ADD CONSTRAINT uq_daily_control_fact UNIQUE(report_date,employee_id,object_id,subobject_id,po_id,category_id)")
        self.fact()
        before=self.conn.execute("SELECT to_jsonb(r) FROM daily_control_results r ORDER BY id").fetchall()
        with self.assertRaises(psycopg.errors.RaiseException):
            apply_migration(self.conn)
        self.assertEqual(before,self.conn.execute("SELECT to_jsonb(r) FROM daily_control_results r ORDER BY id").fetchall())


class ReportDateTests(unittest.TestCase):
    def test_date_is_from_word_only(self):
        self.assertEqual(parsed_date("24.09.2026"),date(2026,9,24))
        self.assertEqual(parsed_date("2026-09-24"),date(2026,9,24))
        self.assertIsNone(parsed_date("31.02.2026"))
        self.assertIsNone(parsed_date(None))
