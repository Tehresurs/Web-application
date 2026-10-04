import os
import unittest
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import patch

import psycopg
import test_luvr_directories
from test_daily_control import http_request
from app.database.migrate_luvr_history import apply_migration
from app.repositories import luvr_history


@unittest.skipUnless(os.getenv("DAILY_CONTROL_TEST_DB") == "1", "Requires isolated PostgreSQL tests")
class LuvrHistoryTests(unittest.TestCase):
    def setUp(self):
        test_luvr_directories.LuvrDirectoryTests.setUp(self)
        self.conn.execute("ALTER TABLE employee_assignments ADD CONSTRAINT fk_test_employee FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE CASCADE")

        @contextmanager
        def connection():
            with self.conn.transaction():
                yield self.conn

        mock=patch("app.repositories.luvr_history.get_connection",connection)
        mock.start();self.addCleanup(mock.stop)

    def request(self, kind, method="GET", payload=None, item_id=None, employee=2, query=""):
        route=f"/api/employees/{employee}/luvr/{kind}"+(f"/{item_id}" if item_id else "")
        return http_request(method,route,payload,query=query)

    def movement(self, **changes):
        return {"movement_type":"ARRIVAL","transport_type":"SELF","event_datetime":"2026-09-20T07:59:00",**changes}

    def create(self,kind,payload,employee=2):
        status,body=self.request(kind,"POST",payload,employee=employee)
        self.assertEqual(status,200,body)
        return body["item"]

    def samples(self):
        return {
            "movements":self.movement(),
            "sick-periods":{"date_from":"2026-10-10","date_to":"2026-10-15","comment":"Комментарий"},
            "duration-exceptions":{"exception_type":"SHIFT","date_from":"2026-10-01","date_to":"2026-10-05","comment":"Согласовано"},
            "day-overrides":{"work_date":"2026-10-01","value":"HALF","comment":"Вручную"},
        }

    def test_arrival_and_departure_self_without_counterevents(self):
        for movement in ("ARRIVAL","DEPARTURE","ARRIVAL","ARRIVAL","DEPARTURE","DEPARTURE"):
            item=self.create("movements",self.movement(movement_type=movement))
            self.assertEqual(item["movement_type"],movement)
            self.assertIsNone(item["source_file"])
        self.assertEqual(len(self.request("movements")[1]["items"]),6)

    def test_departure_can_be_only_event(self):
        self.create("movements",self.movement(movement_type="DEPARTURE"))
        self.assertEqual(len(self.request("movements")[1]["items"]),1)

    def test_rail_ready_with_route_and_source(self):
        item=self.create("movements",self.movement(transport_type="RAIL",source_file="ticket.pdf",departure_station="А",arrival_station="Б"))
        self.assertEqual((item["source_file"],item["departure_station"],item["arrival_station"]),("ticket.pdf","А","Б"))

    def test_movement_invalid_enum_timestamp_and_employee(self):
        for changes in ({"movement_type":"BAD"},{"transport_type":"BUS"},{"event_datetime":None},{"event_datetime":"2026-10-01"},{"event_datetime":0},{"event_datetime":"2026-10-01T00:10:00Z"},{"event_datetime":"2026-10-01T00:10:00+05:00"}):
            self.assertEqual(self.request("movements","POST",self.movement(**changes))[0],422,changes)
        for kind,payload in self.samples().items():
            self.assertEqual(self.request(kind,"POST",payload,employee=999)[0],404)
            self.assertEqual(self.request(kind,employee=999)[0],404)

    def test_self_source_rejected_and_patch_checks_merged_state(self):
        self.assertEqual(self.request("movements","POST",self.movement(source_file="x.pdf"))[0],400)
        item=self.create("movements",self.movement(transport_type="RAIL",source_file="x.pdf"))
        self.assertEqual(self.request("movements","PATCH",{"transport_type":"SELF"},item["id"])[0],400)
        status,body=self.request("movements","PATCH",{"transport_type":"SELF","source_file":None},item["id"])
        self.assertEqual(status,200);self.assertIsNone(body["item"]["source_file"])

    def test_chronology_across_months_and_inclusive_filter(self):
        self.create("movements",self.movement(movement_type="DEPARTURE",event_datetime="2026-10-06T23:59:59.999999"))
        self.create("movements",self.movement())
        items=self.request("movements")[1]["items"]
        self.assertEqual([i["movement_type"] for i in items],["ARRIVAL","DEPARTURE"])
        self.assertEqual(len(self.request("movements",query="date_from=2026-10-06&date_to=2026-10-06")[1]["items"]),1)
        self.assertEqual(self.request("movements",query="date_from=2026-11-01&date_to=2026-10-01")[0],400)

    def test_time_boundaries_preserved_without_timezone_shift(self):
        for clock in ("07:59","08:00","12:59","13:00","19:59","20:00","00:00"):
            item=self.create("movements",self.movement(event_datetime="2026-10-01T"+clock))
            self.assertEqual(item["event_datetime"],"2026-10-01T"+clock+":00")
            row=self.conn.execute("SELECT event_datetime FROM employee_movements WHERE id=%s",(item["id"],)).fetchone()[0]
            self.assertIsNone(row.tzinfo);self.assertEqual(row.strftime("%H:%M"),clock)

    def test_crud_and_employee_ownership(self):
        for kind,payload in self.samples().items():
            item=self.create(kind,payload)
            self.assertIn("created_at",item);self.assertIn("updated_at",item)
            if kind!="day-overrides":
                patch_data={"arrival_station":"Новое место"} if kind=="movements" else {"comment":"Изменено"}
                self.assertEqual(self.request(kind,"PATCH",patch_data,item["id"],employee=1)[0],404)
                self.assertEqual(self.request(kind,"PATCH",patch_data,item["id"])[0],200)
                self.assertEqual(self.request(kind,"PATCH",{},item["id"])[0],422)
            self.assertEqual(self.request(kind,"DELETE",item_id=item["id"],employee=1)[0],404)
            self.assertEqual(self.request(kind,"DELETE",item_id=item["id"])[0],200)
            self.assertEqual(self.request(kind,"DELETE",item_id=item["id"])[0],404)
            self.assertEqual(self.request(kind)[1]["items"],[])

    def test_sick_period_open_closed_and_date_validation(self):
        item=self.create("sick-periods",{"date_from":"2026-09-25"})
        self.assertIsNone(item["date_to"])
        self.assertEqual(len(self.request("sick-periods",query="date_from=2026-10-01&date_to=2026-10-31")[1]["items"]),1)
        self.assertEqual(self.request("sick-periods","PATCH",{"date_to":"2026-09-24"},item["id"])[0],400)
        self.assertEqual(self.request("sick-periods","PATCH",{"date_to":"2026-10-04"},item["id"])[0],200)
        self.assertEqual(self.request("sick-periods","PATCH",{"date_from":"2026-10-05"},item["id"])[0],400)
        self.assertEqual(self.request("sick-periods","PATCH",{"date_to":None},item["id"])[0],200)
        self.assertEqual(self.request("sick-periods","POST",{"date_from":"2026-10-10","date_to":"2026-10-09"})[0],400)

    def test_sickness_and_exceptions_never_change_movements(self):
        self.create("movements",self.movement())
        before=self.request("movements")[1]
        for kind in ("sick-periods","duration-exceptions"):
            item=self.create(kind,self.samples()[kind]);self.assertEqual(before,self.request("movements")[1])
            self.request(kind,"DELETE",item_id=item["id"]);self.assertEqual(before,self.request("movements")[1])

    def test_exception_types_history_and_required_comment(self):
        payload=self.samples()["duration-exceptions"]
        for kind in ("SHIFT","OFF_SHIFT"):
            self.create("duration-exceptions",{**payload,"exception_type":kind})
        self.assertEqual(len(self.request("duration-exceptions")[1]["items"]),2)
        for comment in (""," ","\t\n"):
            self.assertEqual(self.request("duration-exceptions","POST",{**payload,"comment":comment})[0],400)
        for changes in ({"date_to":"2026-09-30"},{"date_from":"2026-10-06"}):
            self.assertEqual(self.request("duration-exceptions","POST",{**payload,**changes})[0],400)
        self.assertEqual(self.request("duration-exceptions","POST",{**payload,"exception_type":"BAD"})[0],422)

    def test_patch_cannot_clear_required_fields(self):
        for kind,fields in (("movements",("movement_type","transport_type","event_datetime")),("sick-periods",("date_from",)),("duration-exceptions",("exception_type","date_from","date_to","comment"))):
            item=self.create(kind,self.samples()[kind])
            for field in fields:
                self.assertEqual(self.request(kind,"PATCH",{field:None},item["id"])[0],422)

    def test_override_codes_and_explicit_upsert(self):
        ids=[]
        for value in ("FULL","HALF","TRAVEL","OFF_SHIFT","DOWNTIME","DISMISSED","EMPTY"):
            item=self.create("day-overrides",{"work_date":"2026-10-01","value":value})
            ids.append(item["id"]);self.assertEqual(item["value"],value)
        self.assertEqual(len(set(ids)),1)
        self.assertEqual(len(self.request("day-overrides")[1]["items"]),1)
        for value in ("Болеет",0.5,"SICK"):
            self.assertEqual(self.request("day-overrides","POST",{"work_date":"2026-10-01","value":value})[0],422)

    def test_override_delete_preserves_employee_and_movement(self):
        movement=self.create("movements",self.movement())
        item=self.create("day-overrides",self.samples()["day-overrides"])
        self.request("day-overrides","DELETE",item_id=item["id"])
        self.assertEqual(self.request("movements")[1]["items"],[movement])
        self.assertIsNotNone(self.conn.execute("SELECT id FROM employees WHERE id=2").fetchone())

    def test_dismissal_set_change_omit_clear_preserves_history(self):
        self.create("movements",self.movement(),employee=1)
        before=self.conn.execute("SELECT to_jsonb(r) FROM daily_control_results r").fetchall()
        movement=self.request("movements",employee=1)[1]
        for dismissal in (None,"2026-10-15","2026-11-01",None):
            status,_=http_request("PATCH","/api/employees/1",{"full_name":"Сотрудник","dismissal_date":dismissal})
            self.assertEqual(status,200)
            item=next(e for e in http_request("GET","/api/employees")[1]["items"] if e["id"]==1)
            self.assertEqual(item["dismissal_date"],dismissal)
            self.assertEqual(http_request("PATCH","/api/employees/1",{"full_name":"Сотрудник"})[0],200)
            self.assertEqual(self.conn.execute("SELECT dismissal_date::text FROM employees WHERE id=1").fetchone()[0],dismissal)
        self.assertEqual(before,self.conn.execute("SELECT to_jsonb(r) FROM daily_control_results r").fetchall())
        self.assertEqual(movement,self.request("movements",employee=1)[1])
        self.assertEqual(self.conn.execute("SELECT count(*) FROM employee_assignments WHERE employee_id=1").fetchone()[0],1)

    def test_employee_post_accepts_dismissal_date(self):
        status,body=http_request("POST","/api/employees",{"full_name":"Новый сотрудник","dismissal_date":"2026-10-21"})
        self.assertEqual(status,200,body)
        self.assertEqual(self.conn.execute("SELECT dismissal_date::text FROM employees WHERE id=%s",(body["id"],)).fetchone()[0],"2026-10-21")

    def test_delete_disabled_even_without_protected_history(self):
        self.conn.execute("INSERT INTO employee_assignments VALUES(2,2,1,1,1)")
        self.assert_delete_conflict_atomic(2)
        self.assertIsNotNone(self.conn.execute("SELECT id FROM employees WHERE id=2").fetchone())
        self.assertIsNotNone(self.conn.execute("SELECT id FROM employee_assignments WHERE employee_id=2").fetchone())
        self.assertEqual(self.conn.execute("SELECT count(*) FROM employee_assignments WHERE employee_id=1").fetchone()[0],1)

    def snapshot(self):
        tables=("employees","employee_assignments","daily_control_results",*(v[0] for v in luvr_history._KINDS.values()))
        return {t:self.conn.execute(f"SELECT to_jsonb(r) FROM {t} r ORDER BY id").fetchall() for t in tables}

    def assert_delete_conflict_atomic(self,employee):
        before=self.snapshot()
        status,body=http_request("DELETE",f"/api/employees/{employee}")
        self.assertEqual(status,409,body);self.assertIn("архив",body["message"])
        self.assertEqual(self.snapshot(),before)
        self.assertEqual(http_request("GET","/api/employees")[0],200)
        self.assertEqual(self.conn.execute("SELECT 1").fetchone()[0],1)

    def test_delete_journal_conflict_rolls_back_assignment_cascade(self):
        self.assert_delete_conflict_atomic(1)

    def test_delete_each_luvr_history_conflict_atomic_with_assignments(self):
        self.conn.execute("INSERT INTO employee_assignments VALUES(2,2,1,1,1)")
        for kind,payload in self.samples().items():
            with self.subTest(kind=kind):
                item=self.create(kind,payload)
                self.assert_delete_conflict_atomic(2)
                self.request(kind,"DELETE",item_id=item["id"])
        self.assertEqual(http_request("DELETE","/api/employees/2")[0],409)

    def test_database_constraints_and_all_employee_fks(self):
        for kind,payload in self.samples().items():
            item=self.create(kind,payload);table=luvr_history._KINDS[kind][0]
            with self.assertRaises(psycopg.errors.ForeignKeyViolation),self.conn.transaction():
                self.conn.execute(f"UPDATE {table} SET employee_id=999 WHERE id=%s",(item["id"],))
            with self.assertRaises((psycopg.errors.ForeignKeyViolation, psycopg.errors.RestrictViolation)),self.conn.transaction():
                self.conn.execute("DELETE FROM employees WHERE id=2")
            if kind=="day-overrides":
                with self.assertRaises(psycopg.errors.UniqueViolation),self.conn.transaction():
                    self.conn.execute("INSERT INTO employee_luvr_day_overrides(employee_id,work_date,value) VALUES(2,'2026-10-01','EMPTY')")
            self.request(kind,"DELETE",item_id=item["id"])
        invalid=[("employee_movements","movement_type='BAD'"),("employee_movements","transport_type='BUS'"),("employee_movements","source_file='x'"),("employee_sick_periods","date_to='2020-01-01'"),("employee_duration_exceptions","date_to='2020-01-01'"),("employee_duration_exceptions","comment=E' \\t\\n'"),("employee_duration_exceptions","exception_type='BAD'"),("employee_luvr_day_overrides","value='SICK'")]
        for kind,payload in self.samples().items(): self.create(kind,payload)
        for table,change in invalid:
            with self.subTest(change=change),self.assertRaises(psycopg.errors.CheckViolation),self.conn.transaction():
                self.conn.execute(f"UPDATE {table} SET {change}")

    def test_migration_additive_and_idempotent(self):
        for table in (v[0] for v in luvr_history._KINDS.values()):self.conn.execute(f"DROP TABLE {table}")
        self.conn.execute("ALTER TABLE employees DROP COLUMN dismissal_date, DROP COLUMN is_archived, DROP COLUMN archived_at")
        tables=("employees","positions","crews","employee_assignments","construction_objects","construction_subobjects","po_types","object_categories","daily_control_results","value_aliases")
        before={t:self.conn.execute(f"SELECT to_jsonb(r) FROM {t} r ORDER BY id").fetchall() for t in tables}
        apply_migration(self.conn)
        for kind,payload in self.samples().items():self.create(kind,payload)
        history=self.snapshot();apply_migration(self.conn);self.assertEqual(history,self.snapshot())
        for table in tables:
            subtract="-'dismissal_date'-'is_archived'-'archived_at'" if table=="employees" else ""
            self.assertEqual(before[table],self.conn.execute(f"SELECT to_jsonb(r){subtract} FROM {table} r ORDER BY id").fetchall())
        self.assertEqual(self.conn.execute("SELECT count(*) FROM employees WHERE is_archived OR archived_at IS NOT NULL").fetchone()[0],0)

    def archive(self,employee=1,restore=False):
        status,body=http_request("POST",f"/api/employees/{employee}/{'restore' if restore else 'archive'}")
        self.assertEqual(status,200,body)
        return body["item"]

    def test_archive_preserves_id_and_every_linked_history(self):
        for kind,payload in self.samples().items():self.create(kind,payload,employee=1)
        before=self.snapshot()
        item=self.archive()
        self.assertEqual(item["id"],1);self.assertTrue(item["is_archived"]);self.assertIsNotNone(item["archived_at"])
        after=self.snapshot()
        for table in before:
            if table!="employees":self.assertEqual(before[table],after[table],table)
        old=before["employees"][0][0];new=after["employees"][0][0]
        for key in old.keys()-{"is_archived","archived_at","updated_at"}:self.assertEqual(old[key],new[key],key)

    def test_archive_filters_and_restore_keep_dismissal(self):
        self.assertEqual(http_request("PATCH","/api/employees/1",{"full_name":"Сотрудник","dismissal_date":"2026-10-15"})[0],200)
        item=self.archive()
        self.assertEqual(item["dismissal_date"],"2026-10-15")
        self.assertEqual([i["id"] for i in http_request("GET","/api/employees")[1]["items"]],[2])
        archived=http_request("GET","/api/employees",query="archived=true")[1]["items"]
        self.assertEqual([i["id"] for i in archived],[1])
        for field in ("full_name","position_name","dismissal_date","archived_at"):self.assertIn(field,archived[0])
        self.assertEqual(len(http_request("GET","/api/employees",query="include_archived=true")[1]["items"]),2)
        restored=self.archive(restore=True)
        self.assertFalse(restored["is_archived"]);self.assertIsNone(restored["archived_at"])
        self.assertEqual(restored["dismissal_date"],"2026-10-15")
        self.assertEqual(len(http_request("GET","/api/employees")[1]["items"]),2)

    def test_archive_idempotent_and_missing_employee(self):
        item=self.archive();self.assertEqual(item,self.archive())
        item=self.archive(restore=True);self.assertEqual(item,self.archive(restore=True))
        for operation in ("archive","restore"):
            self.assertEqual(http_request("POST",f"/api/employees/999/{operation}")[0],404)

    def test_archived_history_queries_and_journal_remain_available(self):
        for kind,payload in self.samples().items():self.create(kind,payload,employee=1)
        queries=[(f"/api/employees/1/luvr/{kind}","") for kind in self.samples()]
        queries+=[("/api/employees/1/assignments",""),("/api/daily-control-results","date_from=2026-09-01&date_to=2026-10-31&employee_id=1")]
        before=[http_request("GET",url,query=query) for url,query in queries]
        self.archive()
        after=[http_request("GET",url,query=query) for url,query in queries]
        self.assertEqual(before,after)
        self.assertTrue(all(status==200 for status,_ in after))

    def test_dismissal_does_not_archive_and_employee_edit_does_not_restore(self):
        self.assertEqual(http_request("PATCH","/api/employees/2",{"full_name":"Сотрудник","dismissal_date":"2026-10-15"})[0],200)
        self.assertFalse(self.conn.execute("SELECT is_archived FROM employees WHERE id=2").fetchone()[0])
        self.archive(employee=2)
        self.assertEqual(http_request("PATCH","/api/employees/2",{"full_name":"Новое имя","dismissal_date":None})[0],200)
        self.assertTrue(self.conn.execute("SELECT is_archived FROM employees WHERE id=2").fetchone()[0])

    def test_delete_guard_never_opens_connection(self):
        with patch("app.repositories.employees.get_connection",side_effect=AssertionError("DELETE must not issue SQL")):
            self.assertEqual(http_request("DELETE","/api/employees/2")[0],409)

    def test_existing_assignment_cascade_constraint_unchanged(self):
        self.assertEqual(self.conn.execute("SELECT confdeltype FROM pg_constraint WHERE conname='fk_test_employee' AND conrelid='employee_assignments'::regclass").fetchone()[0],'c')

    def test_openapi_and_no_month_copies(self):
        schema=http_request("GET","/openapi.json")[1]
        for kind in self.samples():
            path=f"/api/employees/{{employee_id}}/luvr/{kind}"
            for method in ("get","post"):
                self.assertIn("schema",schema["paths"][path][method]["responses"]["200"]["content"]["application/json"])
            self.assertIn("delete",schema["paths"][path+"/{item_id}"])
        self.assertIn("dismissal_date",schema["components"]["schemas"]["EmployeeRequest"]["properties"])
        self.assertIsNone(self.conn.execute("SELECT to_regclass('luvr_month_employees')").fetchone()[0])
