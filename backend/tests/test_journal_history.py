import os
import unittest
from datetime import date
from urllib.parse import urlencode

import test_daily_control
from app.repositories.daily_control import get_journal, insert_fact
from test_daily_control import http_request


@unittest.skipUnless(os.getenv("DAILY_CONTROL_TEST_DB") == "1", "Requires isolated PostgreSQL tests")
class JournalHistoryTests(unittest.TestCase):
    def setUp(self):
        test_daily_control.DatabaseTests.setUp(self)
        self.a = self.conn.execute("INSERT INTO construction_subobjects(object_id,name) VALUES(1,'Подъезд') RETURNING id").fetchone()[0]
        self.b = self.conn.execute("INSERT INTO construction_subobjects(object_id,name) VALUES(1,'Площадка') RETURNING id").fetchone()[0]
        self.c = self.conn.execute("INSERT INTO construction_subobjects(object_id,name) VALUES(2,'Подъезд') RETURNING id").fetchone()[0]
        self.ids = []
        for day, employee, obj, child, po in (
            (3,1,1,None,1), (3,1,1,self.a,1), (3,1,1,self.a,2),
            (4,1,1,self.a,1), (11,1,1,self.b,1), (18,2,1,self.a,1),
            (18,1,2,self.c,1), (30,2,2,None,1),
        ):
            with self.conn.cursor() as cursor:
                self.ids.append(insert_fact(cursor,date(2026,9,day),{"employee_id":employee,"object_id":obj,
                    "subobject_id":child,"po_id":po,"category_id":1},f"report-{day}-{po}.docx","a"*64)["id"])
        self.start, self.end = date(2026,9,1), date(2026,9,30)

    def query(self, **kwargs):
        return get_journal(self.start,self.end,**kwargs)

    def test_period_all_and_counts(self):
        result=self.query()
        self.assertEqual(result["summary"],{"facts_count":8,"objects_count":2,"subobjects_count":3,"employees_count":2,"days_count":5})
        self.assertEqual(len(result["groups"]),5)
        self.assertEqual(get_journal(date(2026,10,1),date(2026,10,31))["items"],[])
        self.assertEqual(get_journal(date(2026,9,3),date(2026,9,3))["summary"]["facts_count"],3)

    def test_employee_unique_dates(self):
        result=self.query(employee_id=1,view="employee")
        expected=[date(2026,9,d) for d in (3,4,11,18)]
        self.assertEqual(result["dates"],expected)
        self.assertEqual(result["groups"][0]["dates"],expected)
        self.assertEqual(result["groups"][0]["days_count"],4)
        pair=next(p for p in result["groups"][0]["items"] if p["subobject_id"]==self.a)
        self.assertEqual(pair["dates"],[date(2026,9,3),date(2026,9,4)])
        self.assertEqual(len(pair["fact_ids"]),3)

    def test_parent_only_and_including_subobjects(self):
        only=self.query(object_id=1,include_subobjects=False)
        self.assertEqual(len(only["items"]),1)
        self.assertIsNone(only["items"][0]["subobject_id"])
        all_items=self.query(object_id=1,include_subobjects=True)
        self.assertEqual(all_items["summary"]["facts_count"],6)
        self.assertEqual(all_items["summary"]["objects_count"],1)
        self.assertEqual(all_items["summary"]["subobjects_count"],2)
        self.assertEqual(self.query(object_id=1)["items"],all_items["items"])

    def test_subobject_and_employee_combinations_both_views(self):
        for view in ("object","employee"):
            for filters,count in (({"subobject_id":self.a},4),
                                  ({"employee_id":1,"subobject_id":self.a},3),
                                  ({"employee_id":1,"object_id":1,"include_subobjects":False},1),
                                  ({"employee_id":1,"object_id":1,"include_subobjects":True},5),
                                  ({"object_id":2,"subobject_id":self.a},0)):
                with self.subTest(view=view,filters=filters):
                    self.assertEqual(self.query(view=view,**filters)["summary"]["facts_count"],count)

    def test_old_rows_source_and_control_item_identity(self):
        result=self.query()
        old=next(r for r in result["items"] if r["subobject_id"] is None)
        self.assertEqual(old["control_item_name"],"Object A")
        self.assertEqual(old["control_item_key"],"object:1")
        self.assertEqual(old["source_file"],"report-3-1.docx")
        child=next(r for r in result["items"] if r["subobject_id"]==self.a)
        self.assertEqual(child["control_item_name"],"Подъезд")
        self.assertEqual(child["object_name"],"Object A")
        self.assertNotEqual(old["control_item_key"],child["control_item_key"])

    def test_options_have_parent_even_when_only_children_controlled(self):
        result=get_journal(date(2026,9,4),date(2026,9,4),employee_id=999)
        self.assertEqual(result["items"],[])
        choices=result["options"]["control_items"]
        self.assertEqual({c["control_item_key"] for c in choices},{"object:1",f"subobject:{self.a}"})
        self.assertEqual(len(result["options"]["employees"]),1)

    def test_inactive_child_history_remains_visible(self):
        self.conn.execute("UPDATE construction_subobjects SET is_active=FALSE WHERE id=%s",(self.a,))
        result=self.query(subobject_id=self.a)
        self.assertEqual(len(result["items"]),4)
        self.assertTrue(any(item["subobject_id"]==self.a for item in result["options"]["control_items"]))

    def test_http_filters_and_validation(self):
        base={"date_from":"2026-09-01","date_to":"2026-09-30"}
        status,body=http_request("GET","/api/daily-control-results",query=urlencode({**base,"subobject_id":self.a,"employee_id":1,"view":"employee"}))
        self.assertEqual(status,200)
        self.assertEqual(body["summary"]["facts_count"],3)
        self.assertEqual(body["dates"],["2026-09-03","2026-09-04"])
        for invalid in ({"subobject_id":0},{"employee_id":0},{"object_id":0},{"include_subobjects":"bad"}):
            self.assertEqual(http_request("GET","/api/daily-control-results",query=urlencode({**base,**invalid}))[0],422)
        status,body=http_request("GET","/api/daily-control-results",query=urlencode({**base,"object_id":1,"include_subobjects":"false"}))
        self.assertEqual(status,200)
        self.assertEqual(len(body["items"]),1)
