import os
import unittest
from datetime import date
from copy import deepcopy
from app.services.luvr_month import calendar_day_totals
from app.services.luvr_calendar import calculate_employee_month
from test_luvr_calendar import inputs, movement
import test_luvr_month
from test_daily_control import http_request


class DayTotalsTests(unittest.TestCase):
    def test_required_example_uses_final(self):
        days=[dict(date=date(2026,10,1),auto_code='FULL',final_code=code,is_sick=False,final_source_type='OVERRIDE')
              for code in ['FULL']*10+['HALF']*2+['TRAVEL']*3+['OFF_SHIFT']*4+['DOWNTIME']]
        days += [dict(date=date(2026,10,1),final_code='EMPTY',is_sick=True,final_source_type='SICK') for _ in range(2)]
        days += [dict(date=date(2026,10,1),final_code='EMPTY',is_sick=False,final_source_type='UNKNOWN')]
        rows=[{'days':[d]} for d in days];before=deepcopy(rows)
        result=calendar_day_totals(rows,2026,10)
        self.assertEqual(result[0],dict(date=date(2026,10,1),full_count=10,half_count=2,travel_count=3,off_shift_count=4,
            downtime_count=1,dismissed_count=0,sick_count=2,unknown_count=1,present_people_count=12,work_equivalent=11.0))
        self.assertEqual(rows,before);self.assertEqual(result,calendar_day_totals(list(reversed(rows)),2026,10))

    def test_sickness_unknown_and_nonworking_weekend_are_distinct(self):
        rows=[calculate_employee_month(inputs(work_location='OFFICE',work_schedule='FIVE_TWO'),2026,10),
              calculate_employee_month(inputs(),2026,10),
              calculate_employee_month(inputs(sick_periods=[dict(date_from=date(2026,10,1),date_to=None)]),2026,10)]
        result=calendar_day_totals(rows,2026,10)
        self.assertEqual(result[0]['full_count'],1);self.assertEqual(result[2]['full_count'],0)
        self.assertEqual(result[2]['unknown_count'],1);self.assertEqual(result[2]['sick_count'],1)

    def test_dismissal_and_explicit_empty_not_unknown(self):
        rows=[calculate_employee_month(inputs(dismissal_date=date(2026,10,1)),2026,10),
              calculate_employee_month(inputs(overrides=[dict(id=1,work_date=date(2026,10,1),value='EMPTY')]),2026,10)]
        result=calendar_day_totals(rows,2026,10)
        self.assertEqual(result[0]['dismissed_count'],1);self.assertEqual(result[0]['unknown_count'],0)
        self.assertEqual(result[1]['dismissed_count'],0);self.assertEqual(result[1]['unknown_count'],1)

    def test_empty_membership_real_month_lengths(self):
        for year,month,count in [(2026,2,28),(2024,2,29),(2026,4,30),(2026,10,31)]:
            result=calendar_day_totals([],year,month);self.assertEqual(len(result),count)
            self.assertTrue(all(all(v==0 for k,v in d.items() if k!='date') for d in result))


@unittest.skipUnless(os.getenv('DAILY_CONTROL_TEST_DB')=='1','Requires isolated PostgreSQL tests')
class DayTotalsApiTests(unittest.TestCase):
    def setUp(self):test_luvr_month.MonthApiTests.setUp(self)

    def month(self):
        status,body=http_request('GET','/api/luvr/month',query='year=2026&month=10');self.assertEqual(status,200,body);return body['item']

    def test_membership_override_reset_and_removal(self):
        self.conn.execute("INSERT INTO employee_movements(employee_id,movement_type,transport_type,event_datetime) VALUES(2,'ARRIVAL','SELF','2026-10-01 07:00')")
        self.assertEqual(self.month()['day_totals'][0]['full_count'],0)
        http_request('POST','/api/luvr/month/form',dict(year=2026,month=10))
        before=self.month()['day_totals'][0];self.assertEqual(before['full_count'],1)
        status,body=http_request('POST','/api/employees/2/luvr/day-overrides',dict(work_date='2026-10-01',value='DOWNTIME'))
        self.assertEqual(status,200);after=self.month()['day_totals'][0]
        self.assertEqual(after['full_count'],0);self.assertEqual(after['downtime_count'],1)
        http_request('DELETE',f'/api/employees/2/luvr/day-overrides/{body["item"]["id"]}')
        self.assertEqual(self.month()['day_totals'][0],before)
        http_request('DELETE','/api/luvr/month/employees/2',query='year=2026&month=10')
        self.assertEqual(self.month()['day_totals'][0]['full_count'],0)

    def test_added_employee_only_contributes_after_membership(self):
        http_request('POST','/api/luvr/month/form',dict(year=2026,month=10));before=self.month()['day_totals']
        self.conn.execute("UPDATE positions SET work_location='OFFICE',work_schedule='FIVE_TWO' WHERE id=9001")
        eid=self.conn.execute("INSERT INTO employees(full_name,position_id) VALUES('Новый',9001) RETURNING id").fetchone()[0]
        existing=self.month()['day_totals']
        http_request('POST','/api/luvr/month/employees',dict(year=2026,month=10,employee_id=eid))
        after=self.month()['day_totals'];self.assertEqual(after[0]['full_count'],existing[0]['full_count']+1)
        self.assertEqual(after[2]['full_count'],existing[2]['full_count'])
