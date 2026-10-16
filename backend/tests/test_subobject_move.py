import os
import unittest
from unittest.mock import patch

import psycopg
import test_references
from test_daily_control import http_request
from app.repositories import subobjects
from app.repositories.directory_errors import DirectoryConflict


@unittest.skipUnless(os.getenv("DAILY_CONTROL_TEST_DB") == "1", "Requires isolated PostgreSQL tests")
class SubobjectMoveTests(unittest.TestCase):
    setUp = test_references.ReferenceDatabaseTests.setUp

    def child(self, name="Подъезд", parent=1):
        return subobjects.create_subobject(parent, name)

    def link(self, child):
        self.conn.execute("UPDATE daily_control_results SET subobject_id=%s WHERE id=1", (child["id"],))

    def preview(self, child, **payload):
        return http_request("POST", f'/api/subobjects/{child["id"]}/move/check', {"object_id":2, **payload})

    def move(self, child, **payload):
        return http_request("PATCH", f'/api/subobjects/{child["id"]}/move', {"object_id":2, **payload})

    def test_zero_one_many_and_order(self):
        self.assertEqual(subobjects.get_subobjects(1), [])
        self.child("Яма")
        self.assertEqual(len(subobjects.get_subobjects(1)), 1)
        self.child("Арка")
        self.child("Дорога")
        self.assertEqual([x["name"] for x in subobjects.get_subobjects(1)], ["Арка", "Дорога", "Яма"])
        self.assertEqual(subobjects.get_subobjects(2), [])

    def test_create_duplicate_rename_and_active_status(self):
        child = self.child()
        status, _ = http_request("POST", "/api/subobjects", {"object_id":1,"name":"  ПОДЪЕЗД  "})
        self.assertEqual(status, 409)
        self.assertEqual(subobjects.update_subobject(child["id"],name="Подъезд №55")["name"], "Подъезд №55")
        self.link(child)
        subobjects.update_subobject(child["id"],is_active=False)
        self.assertEqual(subobjects.get_subobjects(1), [])
        self.assertFalse(subobjects.get_subobjects(1,True)[0]["is_active"])
        status, result = http_request("GET", "/api/daily-control-results", query="date_from=2026-09-24&date_to=2026-09-24")
        self.assertEqual(status, 200)
        self.assertEqual(result["items"][0]["subobject_name"], "Подъезд №55")
        self.assertTrue(subobjects.update_subobject(child["id"],is_active=True)["is_active"])

    def test_unused_move_needs_no_confirmation(self):
        child = self.child()
        status, preview = self.preview(child)
        self.assertEqual(status, 200)
        self.assertFalse(preview["item"]["requires_confirmation"])
        self.assertEqual(subobjects.get_subobject(child["id"])["object_id"], 1)
        status, body = self.move(child)
        self.assertEqual(status, 200)
        self.assertEqual(body["item"]["object_id"], 2)
        self.assertEqual(body["updated_facts"], 0)

    def test_used_move_updates_only_parent_and_preserves_assignments(self):
        child = self.child(); self.link(child)
        before = self.conn.execute("SELECT to_jsonb(r)-'object_id' FROM daily_control_results r").fetchall()
        assignments = self.conn.execute("SELECT * FROM employee_assignments").fetchall()
        self.assertEqual(self.move(child)[0], 409)
        status, preview = self.preview(child,name="Новый подъезд",is_active=False)
        plan = preview["item"]
        self.assertEqual(plan["linked_facts"], 1)
        self.assertEqual(plan["missing_assignments"], 1)
        self.assertTrue(plan["requires_confirmation"])
        status, body = self.move(child,name="Новый подъезд",is_active=False,confirmation_token=plan["confirmation_token"])
        self.assertEqual(status, 200, body)
        self.assertEqual(body["updated_facts"], 1)
        self.assertEqual(body["item"]["object_id"], 2)
        self.assertFalse(body["item"]["is_active"])
        self.assertEqual(before, self.conn.execute("SELECT to_jsonb(r)-'object_id' FROM daily_control_results r").fetchall())
        self.assertEqual(assignments, self.conn.execute("SELECT * FROM employee_assignments").fetchall())
        self.assertEqual(self.conn.execute("SELECT object_id FROM daily_control_results WHERE subobject_id=%s", (child["id"],)).fetchone()[0], 2)
        status, journal = http_request("GET", "/api/daily-control-results", query="date_from=2026-09-24&date_to=2026-09-24&object_id=2")
        self.assertEqual(status, 200)
        self.assertEqual(journal["items"][0]["object_name"], "Объект Б")

    def test_existing_assignment_removes_warning(self):
        child = self.child(); self.link(child)
        self.conn.execute("INSERT INTO employee_assignments VALUES(2,1,2,1,1)")
        self.assertEqual(self.preview(child)[1]["item"]["missing_assignments"], 0)

    def test_stale_confirmation_after_new_fact_is_rejected(self):
        child = self.child(); self.link(child)
        token = self.preview(child)[1]["item"]["confirmation_token"]
        self.conn.execute("""INSERT INTO daily_control_results(report_date,employee_id,object_id,subobject_id,po_id,category_id,source_file,source_sha256)
            VALUES('2026-09-25',1,1,%s,1,1,'new.docx',%s)""", (child["id"], "b"*64))
        self.assertEqual(self.move(child,confirmation_token=token)[0], 409)
        self.assertEqual(subobjects.get_subobject(child["id"])["object_id"], 1)
        self.assertEqual(self.conn.execute("SELECT DISTINCT object_id FROM daily_control_results").fetchall(), [(1,)])

    def test_name_collision_including_inactive_rolls_back(self):
        child = self.child(); self.link(child)
        other = self.child(parent=2)
        subobjects.update_subobject(other["id"],is_active=False)
        self.assertEqual(self.move(child,name=" ПОДЪЕЗД ",is_active=False)[0], 409)
        self.assertEqual(subobjects.get_subobject(child["id"]), child)
        self.assertEqual(self.conn.execute("SELECT object_id FROM daily_control_results").fetchone()[0], 1)

    def test_projected_unique_collision_rolls_back(self):
        child = self.child(); self.link(child)
        # A pre-existing inconsistent legacy pair must not become a duplicate on transfer.
        self.conn.execute("""INSERT INTO daily_control_results(report_date,employee_id,object_id,subobject_id,po_id,category_id,source_file,source_sha256)
            VALUES('2026-09-24',1,2,%s,1,1,'legacy.docx',%s)""", (child["id"],"b"*64))
        status, body = self.move(child)
        self.assertEqual(status, 409)
        self.assertIn("дубли", body["message"])
        self.assertEqual(subobjects.get_subobject(child["id"])["object_id"], 1)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM daily_control_results").fetchone()[0], 2)

    def test_failure_after_child_update_rolls_back_both_tables(self):
        child = self.child(); self.link(child)
        plan = self.preview(child)[1]["item"]
        self.conn.execute("""CREATE FUNCTION reject_parent_update() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'simulated failure'; END $$;
            CREATE TRIGGER reject_parent BEFORE UPDATE ON daily_control_results
            FOR EACH ROW EXECUTE FUNCTION reject_parent_update()""")
        with self.assertRaises(psycopg.errors.RaiseException):
            subobjects.move_subobject(child["id"],2,confirmation_token=plan["confirmation_token"])
        self.assertEqual(subobjects.get_subobject(child["id"])["object_id"], 1)
        self.assertEqual(self.conn.execute("SELECT object_id FROM daily_control_results").fetchone()[0], 1)

    def test_invalid_parent_child_and_direct_patch_cannot_bypass_move(self):
        child = self.child()
        self.assertEqual(self.move(child,object_id=999)[0],404)
        self.assertEqual(self.move({"id":999})[0],404)
        self.assertEqual(self.move(child,object_id=0)[0],422)
        self.assertEqual(http_request("PATCH", f'/api/subobjects/{child["id"]}', {"object_id":2})[0],422)

    def test_used_child_cannot_be_deleted_and_parent_delete_is_guarded(self):
        from app.database.migrate_object_archive import apply_migration
        apply_migration(self.conn)
        child = self.child(); self.link(child)
        self.assertEqual(http_request("DELETE", f'/api/subobjects/{child["id"]}')[0],405)
        with self.assertRaises(psycopg.IntegrityError), self.conn.transaction():
            self.conn.execute("DELETE FROM construction_subobjects WHERE id=%s",(child["id"],))
        self.child(parent=2)
        status, body = http_request("DELETE", "/api/objects/2")
        self.assertEqual(status,200)
        self.assertTrue(body['archived'])
        self.assertFalse(body['deleted'])
        self.assertTrue(self.conn.execute('SELECT is_archived FROM construction_objects WHERE id=2').fetchone()[0])

    def test_openapi_move_endpoints(self):
        status, schema = http_request("GET", "/openapi.json")
        self.assertEqual(status,200)
        self.assertIn("post",schema["paths"]["/api/subobjects/{subobject_id}/move/check"])
        self.assertIn("patch",schema["paths"]["/api/subobjects/{subobject_id}/move"])
