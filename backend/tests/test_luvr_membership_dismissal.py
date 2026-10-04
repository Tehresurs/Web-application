import os
import unittest
from datetime import date
import test_luvr_month
from app.repositories import luvr_month
from app.services.luvr_month import month_calendar


@unittest.skipUnless(os.getenv('DAILY_CONTROL_TEST_DB')=='1','Requires isolated PostgreSQL tests')
class MembershipDismissalTests(unittest.TestCase):
    def setUp(self):test_luvr_month.MonthApiTests.setUp(self)

    def check_membership(self,dismissal,month,included,archived=False):
        self.conn.execute('UPDATE employees SET dismissal_date=%s,is_archived=%s WHERE id=2',(dismissal,archived))
        luvr_month.form_month(2026,month)
        exists=self.conn.execute('SELECT 1 FROM luvr_month_employees WHERE year=2026 AND month=%s AND employee_id=2',(month,)).fetchone()
        self.assertEqual(bool(exists),included)
        self.assertEqual(self.conn.execute('SELECT dismissal_date,is_archived FROM employees WHERE id=2').fetchone(),(date.fromisoformat(dismissal) if dismissal else None,archived))

    def test_null_active_included(self):self.check_membership(None,10,True)
    def test_september_dismissal_in_september(self):self.check_membership('2026-09-15',9,True)
    def test_september_dismissal_not_in_october(self):self.check_membership('2026-09-15',10,False)
    def test_first_day_included(self):self.check_membership('2026-10-01',10,True)
    def test_last_day_included(self):self.check_membership('2026-10-31',10,True)
    def test_last_day_not_in_next_month(self):self.check_membership('2026-10-31',11,False)
    def test_archived_dismissed_in_current_month_included(self):self.check_membership('2026-10-15',10,True,True)
    def test_archived_dismissed_not_in_next_month(self):self.check_membership('2026-10-15',11,False,True)
    def test_archived_without_dismissal_still_excluded(self):self.check_membership(None,10,False,True)
    def test_archived_future_dismissal_in_historical_month(self):self.check_membership('2026-11-15',10,True,True)

    def test_current_month_calendar_unchanged(self):
        self.conn.execute("INSERT INTO employee_movements(employee_id,movement_type,transport_type,event_datetime) VALUES(2,'ARRIVAL','SELF','2026-10-01 07:00')")
        self.check_membership('2026-10-15',10,True,True)
        row=next(e for e in month_calendar(2026,10)['employees'] if e['employee_id']==2)
        self.assertTrue(all(d['final_code']=='FULL' for d in row['days'][:14]))
        self.assertEqual(row['days'][14]['final_code'],'DISMISSED')
        self.assertTrue(all(d['final_code']=='EMPTY' for d in row['days'][15:]))

    def test_existing_membership_and_snapshot_unchanged_after_later_dismissal(self):
        luvr_month.form_month(2026,10)
        before=self.conn.execute('SELECT * FROM luvr_month_employees ORDER BY id').fetchall()
        header=luvr_month.get_header_snapshot(2026,10)
        self.conn.execute("UPDATE employees SET dismissal_date='2026-09-15',is_archived=true WHERE id=2")
        luvr_month.form_month(2026,10);month_calendar(2026,10)
        self.assertEqual(before,self.conn.execute('SELECT * FROM luvr_month_employees ORDER BY id').fetchall())
        self.assertEqual(header,luvr_month.get_header_snapshot(2026,10))

    def test_manual_add_still_allowed_and_repeat_form_does_not_remove(self):
        self.check_membership('2026-09-15',10,False,True)
        luvr_month.change_member(2026,10,2)
        luvr_month.form_month(2026,10)
        self.assertTrue(self.conn.execute('SELECT 1 FROM luvr_month_employees WHERE year=2026 AND month=10 AND employee_id=2').fetchone())

    def test_restore_does_not_reinclude_dismissed_in_new_month(self):
        self.check_membership('2026-09-15',10,False,True)
        from test_daily_control import http_request
        status,_=http_request('POST','/api/employees/2/restore')
        self.assertEqual(status,200)
        luvr_month.form_month(2026,11)
        self.assertIsNone(self.conn.execute('SELECT 1 FROM luvr_month_employees WHERE year=2026 AND month=11 AND employee_id=2').fetchone())
