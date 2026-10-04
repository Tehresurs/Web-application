import os
import unittest
from copy import deepcopy
from datetime import date
from unittest.mock import patch
from app.services.luvr_duration import calculate_duration, duration_indicator, month_as_of
from app.services.luvr_calendar import calculate_employee_month
from app.services.luvr_month import calendar_totals
from test_luvr_calendar import inputs, movement
import test_luvr_month
from test_daily_control import http_request


def facts(kind='ARRIVAL',stamp='2026-10-01T10:00',**changes):
    return inputs([movement(1,kind,stamp)],max_shift_days=30,max_off_shift_days=14,**changes)


def sick(start,end=None):
    return dict(id=1,date_from=date.fromisoformat(start),date_to=date.fromisoformat(end) if end else None,comment=None)


def exception(kind='SHIFT',start='2026-11-01',end='2026-11-15',id=1):
    return dict(id=id,exception_type=kind,date_from=date.fromisoformat(start),date_to=date.fromisoformat(end),comment='Согласовано')


class DurationTests(unittest.TestCase):
    def test_shift_thresholds(self):
        for day,expected in [(14,'NORMAL'),(15,'WARNING_50'),(29,'WARNING_50'),(30,'MAX_REACHED'),(31,'EXCEEDED')]:
            result=calculate_duration(facts(),date(2026,10,day))
            self.assertEqual(result['current_shift_days'],day);self.assertEqual(result['indicator_status'],expected)
            self.assertEqual(result['ratio'],day/30)

    def test_off_shift_thresholds_and_departure_day(self):
        for day,expected in [(1,'NORMAL'),(6,'NORMAL'),(7,'WARNING_50'),(14,'MAX_REACHED'),(15,'EXCEEDED')]:
            result=calculate_duration(facts('DEPARTURE',stamp='2026-10-01T23:00'),date(2026,10,day))
            self.assertEqual(result['current_off_shift_days'],day);self.assertEqual(result['indicator_status'],expected)

    def test_odd_maximum_exact_integer_threshold(self):
        self.assertEqual(duration_indicator(7,15),'NORMAL');self.assertEqual(duration_indicator(8,15),'WARNING_50')

    def test_shift_previous_month(self):
        r=calculate_duration(facts(stamp='2026-09-20T10:00'),date(2026,10,10))
        self.assertEqual(r['current_shift_days'],21);self.assertEqual(r['state_since'],date(2026,9,20))

    def test_off_shift_previous_month(self):
        r=calculate_duration(facts('DEPARTURE','2026-09-25T20:00'),date(2026,10,10))
        self.assertEqual(r['current_off_shift_days'],16);self.assertEqual(r['state_since'],date(2026,9,25))

    def test_year_boundary(self):
        self.assertEqual(calculate_duration(facts(stamp='2025-12-25T07:00'),date(2026,1,5))['current_shift_days'],12)

    def test_sick_excluded_and_indicator_disabled_then_resumes(self):
        data=facts(sick_periods=[sick('2026-10-06','2026-10-10')])
        r=calculate_duration(data,date(2026,10,15));self.assertEqual(r['current_shift_days'],10);self.assertEqual(r['excluded_sick_days'],5)
        for day in [6,8,10]:
            r=calculate_duration(data,date(2026,10,day));self.assertEqual(r['current_shift_days'],5)
            self.assertTrue(r['is_sick']);self.assertFalse(r['indicator_enabled']);self.assertEqual(r['current_state'],'ON_SHIFT')
        self.assertEqual(calculate_duration(data,date(2026,10,11))['current_shift_days'],6)

    def test_overlapping_open_sick_periods_are_union_clipped_to_state(self):
        data=facts(sick_periods=[sick('2026-09-01','2026-10-02'),sick('2026-10-05','2026-10-08'),sick('2026-10-07'),sick('2026-11-01')])
        r=calculate_duration(data,date(2026,10,15));self.assertEqual(r['current_shift_days'],2);self.assertEqual(r['excluded_sick_days'],13)

    def test_off_shift_sickness(self):
        r=calculate_duration(facts('DEPARTURE',sick_periods=[sick('2026-10-02','2026-10-04')]),date(2026,10,7))
        self.assertEqual(r['current_off_shift_days'],4);self.assertEqual(r['indicator_status'],'NORMAL')

    def test_extension_keeps_duration_and_expires(self):
        data=facts(duration_exceptions=[exception()])
        r=calculate_duration(data,date(2026,11,3));self.assertEqual(r['current_duration_days'],34);self.assertEqual(r['maximum_days'],30)
        self.assertEqual(r['indicator_status'],'APPROVED_EXTENSION');self.assertEqual(r['active_exception']['comment'],'Согласовано')
        self.assertEqual(calculate_duration(data,date(2026,11,15))['indicator_status'],'APPROVED_EXTENSION')
        self.assertEqual(calculate_duration(data,date(2026,11,16))['indicator_status'],'EXCEEDED')

    def test_exception_type_and_start_date(self):
        data=facts('DEPARTURE',duration_exceptions=[exception('SHIFT'),exception('OFF_SHIFT',id=2)])
        self.assertEqual(calculate_duration(data,date(2026,10,31))['indicator_status'],'EXCEEDED')
        r=calculate_duration(data,date(2026,11,1));self.assertEqual(r['active_exception']['id'],2);self.assertEqual(r['current_duration_days'],32)

    def test_sick_wins_over_exception_without_deleting_it(self):
        r=calculate_duration(facts(duration_exceptions=[exception()],sick_periods=[sick('2026-11-01')]),date(2026,11,3))
        self.assertEqual(r['current_duration_days'],31);self.assertEqual(r['indicator_status'],'NONE');self.assertFalse(r['indicator_enabled']);self.assertIsNotNone(r['active_exception'])

    def test_multiple_exceptions_return_all_deterministically(self):
        data=facts(duration_exceptions=[exception(end='2026-11-10'),exception(end='2026-11-15',id=2)])
        r=calculate_duration(data,date(2026,11,3));self.assertEqual(r['active_exception']['id'],2);self.assertEqual(len(r['active_exceptions']),2)

    def test_no_maximum_has_no_ratio_or_threshold(self):
        data=facts();data['max_shift_days']=None
        r=calculate_duration(data,date(2026,10,20));self.assertEqual(r['current_shift_days'],20);self.assertIsNone(r['ratio']);self.assertEqual(r['indicator_status'],'NONE');self.assertFalse(r['indicator_enabled'])

    def test_five_two_not_applicable_and_office_shift_supported(self):
        for location in ['OBJECT','OFFICE']:
            self.assertEqual(calculate_duration(facts(work_location=location),date(2026,10,10))['current_shift_days'],10)
        r=calculate_duration(facts(work_location='OFFICE',work_schedule='FIVE_TWO'),date(2026,10,10))
        self.assertEqual(r['current_state'],'NOT_APPLICABLE');self.assertIsNone(r['current_duration_days']);self.assertFalse(r['indicator_enabled'])

    def test_unknown_and_future_movement_have_null_duration(self):
        for data in [inputs(),facts(stamp='2026-11-01T07:00')]:
            r=calculate_duration(data,date(2026,10,10));self.assertEqual(r['current_state'],'UNKNOWN');self.assertIsNone(r['current_duration_days']);self.assertEqual(r['indicator_status'],'UNKNOWN')

    def test_same_timestamp_conflict_is_unknown(self):
        data=facts();data['movements'].append(movement(2,'DEPARTURE','2026-10-01T10:00'))
        r=calculate_duration(data,date(2026,10,10));self.assertEqual(r['current_state'],'UNKNOWN');self.assertIsNone(r['state_since'])

    def test_latest_confirmed_event_starts_period_and_future_events_ignored(self):
        data=facts();data['movements'] += [movement(2,'DEPARTURE','2026-10-05T10:00'),movement(3,'ARRIVAL','2026-10-20T07:00')]
        r=calculate_duration(data,date(2026,10,10));self.assertEqual(r['current_off_shift_days'],6);self.assertEqual(r['state_since'],date(2026,10,5))

    def test_repeated_same_type_uses_last_event_with_warning(self):
        data=facts();data['movements'].append(movement(2,'ARRIVAL','2026-10-05T07:00'))
        r=calculate_duration(data,date(2026,10,10));self.assertEqual(r['current_shift_days'],6);self.assertTrue(r['warnings'])

    def test_dismissal_stops_status_and_archived_history_works(self):
        data=facts(dismissal_date=date(2026,10,15),is_archived=True)
        self.assertEqual(calculate_duration(data,date(2026,10,14))['current_shift_days'],14)
        for day in [15,31]:
            r=calculate_duration(data,date(2026,10,day));self.assertEqual(r['current_state'],'DISMISSED');self.assertIsNone(r['current_duration_days']);self.assertFalse(r['indicator_enabled'])

    def test_rail_prearrival_travel_not_shift_and_half_day_counts_one(self):
        data=inputs([movement(1,'ARRIVAL','2026-10-21T10:00','RAIL','2026-10-20T23:00')])
        self.assertIsNone(calculate_duration(data,date(2026,10,20))['current_shift_days'])
        self.assertEqual(calculate_duration(data,date(2026,10,21))['current_shift_days'],1)
        self.assertEqual(calculate_employee_month(data,2026,10)['days'][20]['final_code'],'HALF')

    def test_overrides_and_exceptions_do_not_change_duration_or_month(self):
        data=facts(overrides=[dict(id=1,work_date=date(2026,10,2),value='DISMISSED')],duration_exceptions=[exception()]);before=deepcopy(data)
        month=calculate_employee_month(data,2026,10)
        r=calculate_duration(data,date(2026,11,3));self.assertEqual(r['current_duration_days'],34)
        self.assertEqual(month,calculate_employee_month(data,2026,10));self.assertEqual(data,before)
        self.assertNotEqual(calendar_totals(month['days'])['work_days_total'],r['current_duration_days'])

    def test_default_and_explicit_calculation_dates(self):
        today=date(2026,10,10)
        for year,month,expected in [(2026,9,date(2026,9,30)),(2026,10,today),(2026,11,today),(2024,2,date(2024,2,29))]:
            self.assertEqual(month_as_of(year,month,today=today),expected)
        self.assertEqual(month_as_of(2026,10,date(2026,10,20),today),date(2026,10,20))


@unittest.skipUnless(os.getenv('DAILY_CONTROL_TEST_DB')=='1','Requires isolated PostgreSQL tests')
class DurationApiTests(unittest.TestCase):
    def setUp(self):
        test_luvr_month.MonthApiTests.setUp(self)
        self.conn.execute("UPDATE employees SET max_shift_days=30,max_off_shift_days=14 WHERE id=2")
        self.conn.execute("INSERT INTO employee_movements(employee_id,movement_type,transport_type,event_datetime) VALUES(2,'ARRIVAL','SELF','2026-09-20 10:00')")
        http_request('POST','/api/luvr/month/form',dict(year=2026,month=10))

    def month(self,as_of='2026-10-10'):
        return http_request('GET','/api/luvr/month',query='year=2026&month=10'+('&as_of_date='+as_of if as_of else ''))

    def test_month_status_schema_explicit_date_and_totals_unchanged(self):
        status,body=self.month();self.assertEqual(status,200,body)
        row=next(e for e in body['item']['employees'] if e['employee_id']==2)
        self.assertEqual(row['duration']['current_shift_days'],21);self.assertEqual(row['duration']['ratio'],0.7)
        other=next(e for e in self.month('2026-10-30')[1]['item']['employees'] if e['employee_id']==2)
        self.assertEqual(row['totals'],other['totals']);self.assertEqual(row['days'],other['days'])

    def test_repository_loads_sick_and_exceptions_and_get_writes_nothing(self):
        self.conn.execute("INSERT INTO employee_duration_exceptions(employee_id,exception_type,date_from,date_to,comment) VALUES(2,'SHIFT','2026-10-01','2026-10-31','Одобрено')")
        self.conn.execute("INSERT INTO employee_sick_periods(employee_id,date_from,date_to) VALUES(2,'2026-10-06','2026-10-10')")
        names=[r[0] for r in self.conn.execute('SELECT tablename FROM pg_tables WHERE schemaname=current_schema()')]
        snapshot=lambda:{t:self.conn.execute(f'SELECT to_jsonb(r) FROM {t} r ORDER BY to_jsonb(r)::text').fetchall() for t in names}
        before=snapshot();row=next(e for e in self.month()[1]['item']['employees'] if e['employee_id']==2)
        self.assertEqual(row['duration']['current_shift_days'],16);self.assertFalse(row['duration']['indicator_enabled']);self.assertEqual(row['duration']['active_exception']['comment'],'Одобрено')
        after=next(e for e in self.month('2026-10-11')[1]['item']['employees'] if e['employee_id']==2)
        self.assertEqual(after['duration']['indicator_status'],'APPROVED_EXTENSION');self.assertEqual(before,snapshot())

    def test_default_dates_projection_and_validation(self):
        with patch('app.services.luvr_month.local_today',return_value=date(2026,10,2)):
            self.assertEqual(self.month('')[1]['item']['as_of_date'],'2026-10-02')
            self.assertFalse(self.month('')[1]['item']['is_projection']);self.assertTrue(self.month()[1]['item']['is_projection'])
        self.assertEqual(self.month('2026-02-30')[0],422)
        params=http_request('GET','/openapi.json')[1]['paths']['/api/luvr/month']['get']['parameters']
        self.assertIn('as_of_date',[p['name'] for p in params])
