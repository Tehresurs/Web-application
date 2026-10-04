import os
import unittest
from copy import deepcopy
from datetime import date, datetime
from contextlib import contextmanager
from unittest.mock import patch
from app.services.luvr_calendar import calculate_employee_day, calculate_employee_month
from test_daily_control import http_request
import test_rail_tickets
from rail_fixture import coupon_pdf


def movement(mid,kind,stamp,transport='SELF',departure=None):
    item={'id':mid,'employee_id':2,'movement_type':kind,'transport_type':transport,'event_datetime':datetime.fromisoformat(stamp)}
    if departure:
        item.update(ticket_id=mid,ticket_departure=datetime.fromisoformat(departure),ticket_arrival=item['event_datetime'],ticket_origin='Тюмень',ticket_destination='Салым')
    return item


def inputs(movements=(),**changes):
    return {'employee_id':2,'full_name':'Иванов Иван Иванович','work_schedule':'SHIFT','work_location':'OBJECT','is_archived':False,'dismissal_date':None,'movements':list(movements),'sick_periods':[],'overrides':[],**changes}


def day(data,number=1,month=10,year=2026):return calculate_employee_day(data,date(year,month,number))


class CalendarCalculationTests(unittest.TestCase):
    def test_arrival_boundaries_for_rail_and_self(self):
        for transport in ('RAIL','SELF'):
            for clock,code in [('07:59','FULL'),('07:59:59.999999','FULL'),('08:00','HALF'),('12:59','HALF'),('12:59:59.999999','HALF'),('13:00','TRAVEL')]:
                m=movement(1,'ARRIVAL','2026-10-01T'+clock,transport,'2026-10-01T00:00' if transport=='RAIL' else None)
                self.assertEqual(day(inputs([m]))['auto_code'],code,(transport,clock))

    def test_departure_boundaries_for_rail_and_self(self):
        for transport in ('RAIL','SELF'):
            for clock,code in [('12:59','TRAVEL'),('12:59:59.999999','TRAVEL'),('13:00','HALF'),('19:59','HALF'),('19:59:59.999999','HALF'),('20:00','FULL')]:
                self.assertEqual(day(inputs([movement(1,'DEPARTURE','2026-10-01T'+clock,transport)]))['auto_code'],code,(transport,clock))

    def test_full_cycle_and_multiday_rail_travel(self):
        for departure in ('2026-10-20T23:00','2026-10-18T22:00'):
            data=inputs([movement(1,'DEPARTURE','2026-10-06T10:00'),movement(2,'ARRIVAL','2026-10-21T10:00','RAIL',departure)])
            self.assertEqual(day(data,6)['auto_code'],'TRAVEL')
            for n in range(7,int(departure[8:10])):self.assertEqual(day(data,n)['auto_code'],'OFF_SHIFT')
            for n in range(int(departure[8:10]),21):
                result=day(data,n);self.assertEqual(result['auto_code'],'TRAVEL');self.assertEqual(result['source_type'],'RAIL_TRAVEL');self.assertIn(2,result['movement_ids'])
            self.assertEqual(day(data,21)['auto_code'],'HALF');self.assertEqual(day(data,22)['auto_code'],'FULL')

    def test_rail_arrival_at_0730_after_three_travel_days(self):
        data=inputs([movement(1,'ARRIVAL','2026-10-21T07:30','RAIL','2026-10-18T22:00')])
        self.assertEqual([day(data,n)['auto_code'] for n in range(18,23)],['TRAVEL','TRAVEL','TRAVEL','FULL','FULL'])

    def test_previous_month_sets_initial_state(self):
        for first,code in [('ARRIVAL','FULL'),('DEPARTURE','OFF_SHIFT')]:
            data=inputs([movement(1,first,'2026-09-25T12:00'),movement(2,'ARRIVAL' if first=='DEPARTURE' else 'DEPARTURE','2026-10-12T07:30')])
            self.assertTrue(all(day(data,n)['auto_code']==code for n in range(1,12)))

    def test_next_month_arrival_supplies_previous_month_travel(self):
        data=inputs([movement(1,'DEPARTURE','2026-09-25T10:00'),movement(2,'ARRIVAL','2026-11-02T07:30','RAIL','2026-10-30T22:00')])
        self.assertEqual(day(data,29)['auto_code'],'OFF_SHIFT')
        for n in (30,31):self.assertEqual(day(data,n)['auto_code'],'TRAVEL')
        self.assertEqual(day(data,1,11)['auto_code'],'TRAVEL');self.assertEqual(day(data,2,11)['auto_code'],'FULL')

    def test_unknown_before_first_event_not_inferred_backwards(self):
        for kind in ('ARRIVAL','DEPARTURE'):
            data=inputs([movement(1,kind,'2026-10-10T10:00')])
            for n in range(1,10):self.assertEqual((day(data,n)['state'],day(data,n)['auto_code']),('UNKNOWN','EMPTY'))
        self.assertTrue(all(d['auto_code']=='EMPTY' for d in calculate_employee_month(inputs(),2026,10)['days']))

    def test_open_state_no_invented_events_or_max_duration(self):
        for kind,expected in [('ARRIVAL','FULL'),('DEPARTURE','OFF_SHIFT')]:
            data=inputs([movement(1,kind,'2026-10-01T07:00')],max_shift_days=1,max_off_shift_days=1)
            before=deepcopy(data)
            self.assertTrue(all(day(data,n)['auto_code']==expected for n in range(2,32)))
            self.assertEqual(data,before)

    def test_departure_does_not_create_multiday_travel(self):
        data=inputs([movement(1,'DEPARTURE','2026-10-06T10:00','RAIL')])
        self.assertEqual([day(data,n)['auto_code'] for n in (6,7,8)],['TRAVEL','OFF_SHIFT','OFF_SHIFT'])

    def test_self_arrival_has_no_travel_before_event(self):
        data=inputs([movement(1,'DEPARTURE','2026-10-01T10:00'),movement(2,'ARRIVAL','2026-10-21T10:00')])
        self.assertEqual(day(data,20)['auto_code'],'OFF_SHIFT')

    def test_sickness_and_open_sickness_do_not_change_state(self):
        for end in (date(2026,10,10),None):
            data=inputs([movement(1,'ARRIVAL','2026-10-01T07:00')],sick_periods=[{'date_from':date(2026,10,6),'date_to':end}])
            self.assertEqual(day(data,5)['final_code'],'FULL')
            for n in range(6,11):
                d=day(data,n);self.assertEqual(d['auto_code'],'FULL');self.assertEqual(d['final_code'],'EMPTY');self.assertTrue(d['is_sick']);self.assertEqual(d['state'],'ON_SHIFT')
            self.assertEqual(day(data,11)['final_code'],'FULL' if end else 'EMPTY')

    def test_override_preserves_auto_sickness_wins_and_reports_conflict(self):
        data=inputs([movement(1,'ARRIVAL','2026-10-01T07:00')],overrides=[{'id':1,'work_date':date(2026,10,15),'value':'DOWNTIME'}])
        d=day(data,15);self.assertEqual((d['auto_code'],d['final_code'],d['manually_changed']),('FULL','DOWNTIME',True))
        data['sick_periods']=[{'date_from':date(2026,10,15),'date_to':date(2026,10,15)}]
        d=day(data,15);self.assertEqual(d['final_code'],'EMPTY');self.assertEqual(d['override_code'],'DOWNTIME')
        self.assertIn('SICK_OVERRIDE_CONFLICT',[w['code'] for w in d['warnings']])
        self.assertEqual(len(data['overrides']),1)

    def test_dismissal_and_archived_history(self):
        data=inputs([movement(1,'ARRIVAL','2026-09-01T07:00')],is_archived=True,dismissal_date=date(2026,10,15))
        self.assertEqual(day(data,14)['final_code'],'FULL');self.assertEqual(day(data,15)['auto_code'],'DISMISSED');self.assertEqual(day(data,16)['final_code'],'EMPTY')
        self.assertEqual(day(data,30,9)['final_code'],'FULL')
        self.assertEqual(day(data,1,11)['final_code'],'EMPTY')

    def test_dismissal_priority_preserves_conflicting_override(self):
        data=inputs(dismissal_date=date(2026,10,15),sick_periods=[{'date_from':date(2026,10,15),'date_to':None}],overrides=[{'id':1,'work_date':date(2026,10,15),'value':'FULL'}])
        d=day(data,15);self.assertEqual(d['final_code'],'DISMISSED');self.assertTrue(d['manually_changed']);self.assertTrue(d['warnings'])

    def test_schedule_modes_and_both_shift_locations(self):
        for location in ('OBJECT','OFFICE'):
            data=inputs([movement(1,'ARRIVAL','2026-10-01T07:00')],work_location=location)
            self.assertEqual(day(data,2)['auto_code'],'FULL')
        for schedule,mode in [('FIVE_TWO','CONFIGURATION_ERROR'),(None,'UNKNOWN_WORK_SCHEDULE')]:
            data=inputs([movement(1,'ARRIVAL','2026-10-01T07:00')],work_schedule=schedule)
            result=calculate_employee_month(data,2026,10)
            self.assertEqual(result['mode'],mode);self.assertTrue(all(d['auto_code']=='EMPTY' for d in result['days']))

    def test_repeated_events_warn_and_continue_last_state(self):
        for kind,state in [('ARRIVAL','ON_SHIFT'),('DEPARTURE','OFF_SHIFT')]:
            data=inputs([movement(2,kind,'2026-10-05T10:00'),movement(1,kind,'2026-10-01T10:00')])
            self.assertEqual(day(data,6)['state'],state)
            self.assertIn('MOVEMENT_SEQUENCE_WARNING',[w['code'] for w in day(data,5)['warnings']])

    def test_two_events_one_day_needs_review_but_next_day_uses_last(self):
        data=inputs([movement(1,'ARRIVAL','2026-10-01T07:00'),movement(2,'DEPARTURE','2026-10-01T21:00')])
        d=day(data);self.assertEqual(d['auto_code'],'EMPTY');self.assertEqual(d['calculation_status'],'NEEDS_REVIEW');self.assertEqual(d['movement_ids'],[1,2])
        self.assertEqual(day(data,2)['auto_code'],'OFF_SHIFT')

    def test_opposite_events_same_timestamp_do_not_use_id_to_guess_state(self):
        data=inputs([movement(1,'ARRIVAL','2026-10-01T07:00'),movement(2,'DEPARTURE','2026-10-01T07:00')])
        self.assertEqual(day(data,2)['state'],'UNKNOWN');self.assertEqual(day(data,2)['auto_code'],'EMPTY')

    def test_travel_overlaps_on_shift_or_another_trip_requires_review(self):
        data=inputs([movement(1,'ARRIVAL','2026-10-01T07:00'),movement(2,'ARRIVAL','2026-10-21T07:00','RAIL','2026-10-20T23:00')])
        self.assertEqual(day(data,20)['calculation_status'],'NEEDS_REVIEW')

    def test_missing_or_contradictory_ticket_never_invents_travel(self):
        data=inputs([movement(1,'ARRIVAL','2026-10-21T07:00','RAIL')])
        self.assertEqual(day(data,20)['auto_code'],'EMPTY');self.assertIn('RAIL_SOURCE_MISSING',[w['code'] for w in day(data,21)['warnings']])
        data['movements'][0].update(ticket_id=1,ticket_departure=datetime(2026,10,22),ticket_arrival=datetime(2026,10,21,7),ticket_origin='Тюмень',ticket_destination='Салым')
        self.assertEqual(day(data,21)['calculation_status'],'NEEDS_REVIEW')

    def test_month_and_day_equivalence_leap_year_and_no_mutation(self):
        data=inputs([movement(1,'ARRIVAL','2024-01-31T07:00')]);before=deepcopy(data)
        result=calculate_employee_month(data,2024,2);self.assertEqual(len(result['days']),29)
        for d in result['days']:self.assertEqual(d,calculate_employee_day(data,d['date']))
        self.assertEqual(data,before)


@unittest.skipUnless(os.getenv('DAILY_CONTROL_TEST_DB')=='1','Requires isolated PostgreSQL tests')
class CalendarApiTests(unittest.TestCase):
    def setUp(self):
        test_rail_tickets.RailTicketTests.setUp(self)
        self.conn.execute("INSERT INTO positions(id,name,work_location,work_schedule) VALUES(9001,'Вахта','OBJECT','SHIFT')")
        self.conn.execute('UPDATE employees SET position_id=9001 WHERE id=2')
        @contextmanager
        def connection():
            with self.conn.transaction():yield self.conn
        mock=patch('app.repositories.luvr_calendar.get_connection',connection);mock.start();self.addCleanup(mock.stop)

    def calendar(self,query='year=2026&month=10',employee=2):
        return http_request('GET',f'/api/employees/{employee}/luvr/calendar',query=query)

    def create(self,kind,payload):
        status,body=http_request('POST',f'/api/employees/2/luvr/{kind}',payload)
        self.assertEqual(status,200,body);return body['item']

    def test_calendar_get_is_read_only_and_day_matches_month(self):
        self.create('movements',{'movement_type':'ARRIVAL','transport_type':'SELF','event_datetime':'2026-09-25T07:00'})
        names=['employees','positions','employee_movements','employee_sick_periods','employee_luvr_day_overrides','rail_tickets','daily_control_results','employee_assignments']
        snapshot=lambda:{t:self.conn.execute(f'SELECT to_jsonb(r) FROM {t} r ORDER BY id').fetchall() for t in names}
        before=snapshot();status,data=self.calendar();self.assertEqual(status,200)
        self.assertEqual(data['item']['days'][0]['auto_code'],'FULL')
        status,d=http_request('GET','/api/employees/2/luvr/calendar/day',query='target=2026-10-01')
        self.assertEqual(status,200);self.assertEqual(d['item'],data['item']['days'][0]);self.assertEqual(snapshot(),before)

    def test_override_upsert_delete_and_movement_recalculation(self):
        m=self.create('movements',{'movement_type':'ARRIVAL','transport_type':'SELF','event_datetime':'2026-10-01T07:00'})
        o=self.create('day-overrides',{'work_date':'2026-10-15','value':'DOWNTIME'})
        result=self.calendar()[1]['item']['days'][14];self.assertEqual((result['auto_code'],result['final_code']),('FULL','DOWNTIME'))
        http_request('PATCH',f'/api/employees/2/luvr/movements/{m["id"]}',{'movement_type':'DEPARTURE'})
        result=self.calendar()[1]['item']['days'][14];self.assertEqual((result['auto_code'],result['final_code']),('OFF_SHIFT','DOWNTIME'))
        http_request('DELETE',f'/api/employees/2/luvr/day-overrides/{o["id"]}')
        result=self.calendar()[1]['item']['days'][14];self.assertEqual(result['final_code'],'OFF_SHIFT');self.assertFalse(result['manually_changed'])

    def test_rail_confirmation_joins_exact_ticket_and_recalculates(self):
        data=coupon_pdf(departure_datetime='20.10.2026 23:00',arrival_datetime='21.10.2026 10:00')
        item=test_rail_tickets.upload_request([('arrival.pdf',data)])[1]['items'][0]
        self.assertTrue(all(d['auto_code']=='EMPTY' for d in self.calendar()[1]['item']['days']))
        http_request('POST',f'/api/rail-tickets/{item["id"]}/confirm',{})
        days=self.calendar()[1]['item']['days'];self.assertEqual([days[n-1]['auto_code'] for n in (20,21,22)],['TRAVEL','HALF','FULL'])

    def test_archived_employee_historical_month_and_five_two(self):
        http_request('POST','/api/employees/2/archive')
        result=self.calendar()[1]['item'];self.assertTrue(result['is_archived'])
        self.conn.execute("UPDATE positions SET work_location='OFFICE',work_schedule='FIVE_TWO' WHERE id=9001")
        self.assertEqual(self.calendar()[1]['item']['mode'],'FIVE_TWO')

    def test_sick_dismissal_and_override_retained(self):
        self.create('sick-periods',{'date_from':'2026-10-05'})
        override=self.create('day-overrides',{'work_date':'2026-10-06','value':'FULL'})
        self.conn.execute("UPDATE employees SET dismissal_date='2026-10-15' WHERE id=2")
        result=self.calendar()[1]['item']['days'];self.assertEqual(result[5]['final_code'],'EMPTY');self.assertTrue(result[5]['manually_changed'])
        self.assertEqual(result[14]['final_code'],'DISMISSED');self.assertEqual(result[15]['final_code'],'EMPTY')
        self.assertEqual(self.conn.execute('SELECT value FROM employee_luvr_day_overrides WHERE id=%s',(override['id'],)).fetchone()[0],'FULL')

    def test_validation_missing_employee_and_swagger(self):
        for query in ('year=2026&month=0','year=2026&month=13','year=0&month=1','year=10000&month=1','year=x&month=1'):
            self.assertEqual(self.calendar(query)[0],422)
        self.assertEqual(self.calendar(employee=999999)[0],404)
        self.assertEqual(http_request('GET','/api/employees/2/luvr/calendar/day',query='target=2026-02-30')[0],422)
        paths=http_request('GET','/openapi.json')[1]['paths']
        self.assertIn('/api/employees/{employee_id}/luvr/calendar',paths)
