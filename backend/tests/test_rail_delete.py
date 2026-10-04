import os
import unittest
from pathlib import Path
import test_luvr_month
from test_rail_tickets import upload_request
from test_daily_control import http_request
from rail_fixture import coupon_pdf


@unittest.skipUnless(os.getenv('DAILY_CONTROL_TEST_DB')=='1','Requires isolated PostgreSQL tests')
class RailDeleteTests(unittest.TestCase):
    def setUp(self):
        test_luvr_month.MonthApiTests.setUp(self)

    def upload(self,data=None):
        status,body=upload_request([('ticket.pdf',data or coupon_pdf(departure_datetime='20.10.2026 23:00',arrival_datetime='21.10.2026 10:00'))])
        self.assertEqual(status,200,body);return body['items']

    def confirm(self,ticket):
        status,body=http_request('POST',f'/api/rail-tickets/{ticket["id"]}/confirm',{})
        self.assertEqual(status,200,body);return body['item']

    def delete(self,item,employee=2):
        return http_request('DELETE',f'/api/employees/{employee}/luvr/movements/{item["movement_id"]}',query='delete_ticket=true')

    def test_joint_delete_and_explicit_flag_edit_still_forbidden(self):
        item=self.confirm(self.upload()[0]);url=f'/api/employees/2/luvr/movements/{item["movement_id"]}'
        self.assertEqual(http_request('PATCH',url,{'movement_type':'DEPARTURE'})[0],409)
        self.assertEqual(http_request('DELETE',url)[0],409)
        status,body=self.delete(item);self.assertEqual(status,200,body);self.assertEqual(body['ticket_id'],item['id'])
        self.assertIsNone(self.conn.execute('SELECT id FROM rail_tickets WHERE id=%s',(item['id'],)).fetchone())
        self.assertIsNone(self.conn.execute('SELECT id FROM employee_movements WHERE id=%s',(item['movement_id'],)).fetchone())

    def test_self_delete_unchanged(self):
        status,body=http_request('POST','/api/employees/2/luvr/movements',dict(movement_type='ARRIVAL',transport_type='SELF',event_datetime='2026-10-01T07:00'))
        self.assertEqual(status,200);mid=body['item']['id']
        self.assertEqual(http_request('DELETE',f'/api/employees/2/luvr/movements/{mid}')[1],{'status':'ok','id':mid,'deleted':True})

    def test_multipage_delete_one_reupload_only_deleted_fingerprint(self):
        self.conn.execute("UPDATE employees SET full_name='Каньшин Егор Викторович' WHERE id=2")
        pdf=(Path(__file__).parent/'fixtures/rail/round_trip.pdf').read_bytes()
        a,b=[self.confirm(t) for t in self.upload(pdf)]
        before_ticket=self.conn.execute('SELECT to_jsonb(t) FROM rail_tickets t WHERE id=%s',(b['id'],)).fetchone()
        before_movement=self.conn.execute('SELECT to_jsonb(m) FROM employee_movements m WHERE id=%s',(b['movement_id'],)).fetchone()
        self.assertEqual(self.delete(a)[0],200)
        self.assertEqual(before_ticket,self.conn.execute('SELECT to_jsonb(t) FROM rail_tickets t WHERE id=%s',(b['id'],)).fetchone())
        self.assertEqual(before_movement,self.conn.execute('SELECT to_jsonb(m) FROM employee_movements m WHERE id=%s',(b['movement_id'],)).fetchone())
        new,other=self.upload(pdf)
        self.assertFalse(new['duplicate']);self.assertEqual(new['source_page'],1);self.assertNotEqual(new['id'],a['id'])
        self.assertTrue(other['duplicate']);self.assertEqual(other['id'],b['id']);self.assertEqual(other['movement_id'],b['movement_id'])
        created=self.confirm(new);again=self.confirm(new);self.assertEqual(created['movement_id'],again['movement_id'])
        self.assertEqual(self.conn.execute('SELECT count(*) FROM rail_tickets').fetchone()[0],2)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM employee_movements').fetchone()[0],2)

    def test_failure_rolls_back_both_and_connection_remains_usable(self):
        item=self.confirm(self.upload()[0])
        self.conn.execute('CREATE TABLE test_delete_guard(movement_id BIGINT REFERENCES employee_movements(id) ON DELETE RESTRICT)')
        self.conn.execute('INSERT INTO test_delete_guard VALUES(%s)',(item['movement_id'],))
        status,body=self.delete(item);self.assertEqual(status,409,body)
        self.assertTrue(self.conn.execute('SELECT id FROM rail_tickets WHERE id=%s',(item['id'],)).fetchone())
        self.assertTrue(self.conn.execute('SELECT id FROM employee_movements WHERE id=%s',(item['movement_id'],)).fetchone())
        self.assertEqual(http_request('GET','/api/employees/2/luvr/movements')[0],200)
        self.conn.execute('DELETE FROM test_delete_guard');self.assertEqual(self.delete(item)[0],200)

    def test_other_employee_and_all_unrelated_data_preserved(self):
        item=self.confirm(self.upload()[0])
        http_request('POST','/api/employees/2/luvr/movements',dict(movement_type='DEPARTURE',transport_type='SELF',event_datetime='2026-10-05T09:00'))
        http_request('POST','/api/employees/2/luvr/sick-periods',dict(date_from='2026-10-22'))
        http_request('POST','/api/employees/2/luvr/day-overrides',dict(work_date='2026-10-25',value='HALF'))
        self.assertEqual(self.delete(item,employee=1)[0],404)
        names=[r[0] for r in self.conn.execute('SELECT tablename FROM pg_tables WHERE schemaname=current_schema()')]
        def snapshot():
            return {t:self.conn.execute(f'SELECT to_jsonb(r) FROM {t} r'+(' WHERE id<>%s' if t in ('rail_tickets','employee_movements') else '')+' ORDER BY to_jsonb(r)::text',
                    (item['id'] if t=='rail_tickets' else item['movement_id'],) if t in ('rail_tickets','employee_movements') else ()).fetchall() for t in names}
        before=snapshot();self.assertEqual(self.delete(item)[0],200);self.assertEqual(before,snapshot())

    def test_calendar_month_totals_duration_recalculate_and_reupload(self):
        item=self.confirm(self.upload()[0]);http_request('POST','/api/luvr/month/form',dict(year=2026,month=10))
        self.conn.execute('UPDATE employees SET max_shift_days=10 WHERE id=2')
        def row():return next(e for e in http_request('GET','/api/luvr/month',query='year=2026&month=10&as_of_date=2026-10-30')[1]['item']['employees'] if e['employee_id']==2)
        before=row();self.assertEqual(before['days'][19]['final_code'],'TRAVEL');self.assertEqual(before['duration']['indicator_status'],'MAX_REACHED')
        self.assertEqual(self.delete(item)[0],200);after=row();self.assertTrue(all(d['final_code']=='EMPTY' for d in after['days']))
        self.assertEqual(after['totals']['work_days_total'],0);self.assertEqual(after['duration']['current_state'],'UNKNOWN')
        detail=http_request('GET','/api/employees/2/luvr/calendar',query='year=2026&month=10')[1]['item'];self.assertEqual(detail['days'],after['days'])
        new=self.upload()[0];self.assertFalse(new['duplicate']);confirmed=self.confirm(new);self.assertNotEqual(confirmed['movement_id'],item['movement_id'])
        restored=row();self.assertEqual(restored['totals'],before['totals']);self.assertEqual(restored['duration']['current_duration_days'],10)

    def test_missing_source_and_repeat_delete_are_safe(self):
        orphan=http_request('POST','/api/employees/2/luvr/movements',dict(movement_type='ARRIVAL',transport_type='RAIL',event_datetime='2026-10-01T07:00'))[1]['item']
        self.assertEqual(self.delete({'movement_id':orphan['id']})[0],409)
        item=self.confirm(self.upload()[0]);self.assertEqual(self.delete(item)[0],200);self.assertEqual(self.delete(item)[0],404)
