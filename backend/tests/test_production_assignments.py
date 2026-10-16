import os
import unittest
from contextlib import contextmanager
from unittest.mock import patch
import psycopg
import test_luvr_calendar
import test_rail_tickets
from test_daily_control import http_request
from app.database.migrate_production_assignments import apply_migration


@unittest.skipUnless(os.getenv('DAILY_CONTROL_TEST_DB') == '1', 'Requires isolated PostgreSQL')
class ProductionAssignmentTests(unittest.TestCase):
    def setUp(self):
        test_luvr_calendar.CalendarApiTests.setUp(self)
        apply_migration(self.conn)
        @contextmanager
        def connection():
            with self.conn.transaction():
                yield self.conn
        mock = patch('app.repositories.production_assignments.get_connection', connection)
        mock.start()
        self.addCleanup(mock.stop)
        self.anchor = self.movement('ARRIVAL', '2026-10-01T07:00')
        self.item = dict(object_id=1, po_id=1, initial_category_id=1, initial_control_mode='INSPECTION')

    upload = test_rail_tickets.RailTicketTests.upload
    action = test_rail_tickets.RailTicketTests.action

    def movement(self, kind, stamp):
        status, body = http_request('POST', '/api/employees/2/luvr/movements',
            dict(movement_type=kind, transport_type='SELF', event_datetime=stamp))
        self.assertEqual(status, 200, body)
        return body['item']['id']

    def payload(self, day='2026-10-01', **extra):
        return dict(effective_from=day, arrival_movement_ref=self.anchor,
                    assignment_state='OBJECTS', items=[self.item], **extra)

    def create(self, payload=None):
        status, body = http_request('POST', '/api/employees/2/production-assignments', payload or self.payload())
        self.assertEqual(status, 200, body)
        return body['item']

    def history(self, start='2026-10-01', end='2026-10-31'):
        status, body = http_request('GET', '/api/employees/2/production-assignments', query=f'date_from={start}&date_to={end}')
        self.assertEqual(status, 200, body)
        return body['item']

    def fact(self, day, obj=1, employee=2):
        return self.conn.execute('''INSERT INTO daily_control_results
            (report_date,employee_id,object_id,po_id,category_id,source_file,source_sha256)
            VALUES(%s,%s,%s,1,1,'confirmed.docx',%s) RETURNING id''', (day,employee,obj,'a'*64)).fetchone()[0]

    def snapshot(self):
        return {t:self.conn.execute(f'SELECT to_jsonb(r) FROM {t} r ORDER BY id').fetchall()
                for t in ['employees','positions','employee_assignments','daily_control_results','employee_movements','rail_tickets']}

    def test_multiple_objects_replace_remove_reassign(self):
        first = self.create({**self.payload(), 'items':[self.item, {**self.item,'object_id':2}]})
        second = self.create({**self.payload('2026-10-04'), 'items':[{**self.item,'object_id':2}]})
        self.create({**self.payload('2026-10-07'), 'assignment_state':'NO_OBJECT','items':[]})
        last = self.create(self.payload('2026-10-09'))
        result = self.history()['periods']
        self.assertEqual([r['effective_from'] for r in result], ['2026-10-01','2026-10-04','2026-10-07','2026-10-09'])
        self.assertEqual([r['effective_to'] for r in result], ['2026-10-03','2026-10-06','2026-10-08',None])
        self.assertEqual(len(result[0]['items']),2)
        self.assertEqual(result[1]['basis_id'],second['id'])
        self.assertEqual(result[2]['automatic_control_mode'],'CAMERAL')
        self.assertNotEqual(first['items'][0]['id'],last['items'][0]['id'])
        self.assertEqual(self.conn.execute('SELECT count(*) FROM production_assignment_changes').fetchone()[0],4)

    def test_departure_and_new_arrival_never_restore_old_set(self):
        self.create()
        self.movement('DEPARTURE','2026-10-12T17:00')
        second_anchor = self.movement('ARRIVAL','2026-10-20T07:00')
        periods = self.history()['periods']
        self.assertEqual(periods[0]['effective_to'],'2026-10-12')
        self.assertEqual(periods[1]['assignment_state'],'UNKNOWN')
        self.create({**self.payload('2026-10-20'),'arrival_movement_ref':second_anchor})
        self.assertNotEqual(self.history()['periods'][0]['period_key'],self.history()['periods'][1]['period_key'])
        self.assertEqual(http_request('POST','/api/employees/2/production-assignments',self.payload('2026-10-21'))[0],400)

    def test_all_facts_of_day_replace_plan_and_do_not_change_sources(self):
        self.create()
        self.create({**self.payload('2026-10-05'),'assignment_state':'NO_OBJECT','items':[]})
        ids = [self.fact('2026-10-05',obj) for obj in (1,2)]
        before = self.snapshot()
        periods = self.history()['periods']
        self.assertEqual(periods[1]['basis_kind'],'FACTS')
        self.assertEqual(periods[1]['basis_id'],ids)
        self.assertEqual(len(periods[1]['items']),2)
        self.assertEqual(before,self.snapshot())
        self.fact('2026-10-10',2)
        self.assertEqual(self.history()['periods'][1]['effective_to'],'2026-10-09')

    def test_read_includes_prior_basis_and_is_month_independent(self):
        self.create()
        result = self.history('2026-11-01','2026-11-30')['periods']
        self.assertEqual(result[0]['effective_from'],'2026-10-01')
        self.assertEqual(result[0]['visible_from'],'2026-11-01')
        self.assertEqual(self.conn.execute('SELECT count(*) FROM production_assignment_changes').fetchone()[0],1)

    def test_patch_keeps_snapshot_and_version(self):
        old = self.create()
        before = self.snapshot()
        status, body = http_request('PATCH',f"/api/production-assignments/{old['id']}",
            {**self.payload(), 'version':1, 'items':[{**self.item,'object_id':2}]})
        self.assertEqual(status,200,body)
        new = body['item']
        self.assertEqual(new['version'],2)
        self.assertEqual(new['correction_history'][0]['items'],old['items'])
        self.assertEqual(before,self.snapshot())
        self.assertEqual(http_request('PATCH',f"/api/production-assignments/{old['id']}",{**self.payload(),'version':1})[0],409)

    def test_invalid_shapes_duplicates_and_references(self):
        for update in ({'items':[]}, {'assignment_state':'NO_OBJECT'}, {'items':[self.item,self.item]},
                       {'items':[{**self.item,'initial_control_mode':'CAMERAL'}]}, {'employee_id':1}):
            self.assertEqual(http_request('POST','/api/employees/2/production-assignments',{**self.payload(),**update})[0],422)
        self.assertEqual(http_request('POST','/api/employees/2/production-assignments',{**self.payload(),'items':[{'object_id':99999}]})[0],409)
        self.create()
        self.assertEqual(http_request('POST','/api/employees/2/production-assignments',self.payload())[0],409)
        self.assertEqual(http_request('POST','/api/employees/99999/production-assignments',self.payload())[0],404)
        self.assertEqual(http_request('POST','/api/employees/1/production-assignments',self.payload())[0],400)

    def test_subobject_belongs_to_object_db_guard(self):
        sub = self.conn.execute("INSERT INTO construction_subobjects(object_id,name) VALUES(1,'Child') RETURNING id").fetchone()[0]
        self.assertEqual(http_request('POST','/api/employees/2/production-assignments',
            {**self.payload(),'items':[{**self.item,'object_id':2,'subobject_id':sub}]})[0],409)
        saved = self.create({**self.payload(),'items':[{**self.item,'subobject_id':sub}]})
        with self.assertRaises(psycopg.IntegrityError), self.conn.transaction():
            self.conn.execute('UPDATE production_assignment_items SET object_id=2 WHERE id=%s',(saved['items'][0]['id'],))

    def test_shape_constraint_and_migration_repeat(self):
        saved = self.create()
        with self.assertRaises(psycopg.IntegrityError), self.conn.transaction():
            self.conn.execute('DELETE FROM production_assignment_items WHERE change_id=%s',(saved['id'],))
            self.conn.execute('SET CONSTRAINTS ALL IMMEDIATE')
        before = self.history()
        apply_migration(self.conn)
        self.assertEqual(before,self.history())

    def test_ticket_annul_restore_preserves_history_and_ids(self):
        ticket = self.upload()
        confirmed = self.action(ticket,'confirm')[1]['item']
        self.conn.execute('UPDATE rail_tickets SET object_id=1 WHERE id=%s',(ticket['id'],))
        day = confirmed['arrival_datetime'][:10]
        saved = self.create({**self.payload(day), 'arrival_movement_ref':confirmed['movement_id'],
                             'source_kind':'TICKET','source_ticket_id':ticket['id']})
        before = self.history('2026-09-01','2026-09-30')
        self.assertTrue(before['history'][0]['applicable'])
        self.assertEqual(self.action(ticket,'annul')[0],200)
        annulled = self.history('2026-09-01','2026-09-30')
        self.assertFalse(annulled['history'][0]['applicable'])
        self.assertEqual(annulled['history'][0]['items'],saved['items'])
        self.assertEqual(self.action(ticket,'restore')[0],200)
        self.assertEqual(before,self.history('2026-09-01','2026-09-30'))

    def test_changed_ticket_object_and_movement_invalidate_old_assignment(self):
        saved = self.create()
        self.conn.execute("UPDATE employee_movements SET event_datetime='2026-10-02 07:00' WHERE id=%s",(self.anchor,))
        result = self.history()
        self.assertEqual(result['history'][0]['inapplicable_reason'],'ARRIVAL_CHANGED')
        self.assertTrue(all(p['basis_id'] != saved['id'] for p in result['periods']))

    def test_explicit_office_period_and_no_implicit_cameral(self):
        self.assertEqual(self.history()['periods'][0]['assignment_state'],'UNKNOWN')
        self.conn.execute('DELETE FROM employee_movements WHERE employee_id=2')
        self.conn.execute("UPDATE positions SET work_location='OFFICE',work_schedule='FIVE_TWO' WHERE id=9001")
        payload = dict(effective_from='2026-10-01',period_kind='EXPLICIT',period_start='2026-10-01',
                       period_end='2026-10-31',assignment_state='NO_OBJECT',items=[])
        self.create(payload)
        result = self.history()['periods'][0]
        self.assertEqual(result['automatic_control_mode'],'CAMERAL')
        self.assertEqual(result['effective_to'],'2026-10-31')
        self.assertEqual(http_request('POST','/api/employees/2/production-assignments',
            {**payload,'period_start':'2026-10-02','effective_from':'2026-10-02','period_end':'2026-11-30'})[0],409)

    def test_fact_outside_period_and_dismissal(self):
        fact = self.fact('2026-09-20')
        self.create()
        self.conn.execute("UPDATE employees SET dismissal_date='2026-10-15' WHERE id=2")
        result = self.history('2026-09-01','2026-10-31')
        self.assertIn({'code':'FACT_OUTSIDE_KNOWN_PERIOD','fact_id':fact},result['warnings'])
        self.assertEqual(result['periods'][0]['effective_to'],'2026-10-14')

    def test_arrival_ticket_changed_object_is_not_reused(self):
        ticket = self.upload()
        confirmed = self.action(ticket,'confirm')[1]['item']
        self.conn.execute('UPDATE rail_tickets SET object_id=1 WHERE id=%s',(ticket['id'],))
        self.create({**self.payload(confirmed['arrival_datetime'][:10]),
                     'arrival_movement_ref':confirmed['movement_id'],'source_kind':'TICKET','source_ticket_id':ticket['id']})
        self.conn.execute('UPDATE rail_tickets SET object_id=2 WHERE id=%s',(ticket['id'],))
        self.assertEqual(self.history()['history'][0]['inapplicable_reason'],'SOURCE_TICKET_CHANGED')

    def test_departure_ticket_annul_restore_changes_bound_not_history(self):
        self.create()
        mid = self.conn.execute("""INSERT INTO employee_movements(employee_id,movement_type,transport_type,event_datetime,
            departure_station,arrival_station,source_file) VALUES(2,'DEPARTURE','RAIL','2026-10-12 17:00','Salym','City','departure.pdf') RETURNING id""").fetchone()[0]
        tid = self.conn.execute("""INSERT INTO rail_tickets(file_hash,source_filename,status,employee_id,movement_type,movement_id,
            departure_station,arrival_station,departure_datetime,arrival_datetime,full_name)
            VALUES(%s,'departure.pdf','CONFIRMED',2,'DEPARTURE',%s,'Salym','City','2026-10-12 17:00','2026-10-13 17:00','Test Employee') RETURNING id""",('d'*64,mid)).fetchone()[0]
        before = self.history()
        self.assertEqual(before['periods'][0]['effective_to'],'2026-10-12')
        self.assertEqual(self.action({'id':tid},'annul')[0],200)
        self.assertIsNone(self.history()['periods'][0]['effective_to'])
        self.assertEqual(self.history()['history'],before['history'])
        self.assertEqual(self.action({'id':tid},'restore')[0],200)
        self.assertEqual(self.history(),before)

    def test_consecutive_arrival_starts_new_unknown_period(self):
        self.create()
        self.movement('ARRIVAL','2026-10-05T07:00')
        periods = self.history()['periods']
        self.assertEqual(periods[0]['effective_to'],'2026-10-04')
        self.assertEqual(periods[1]['assignment_state'],'UNKNOWN')

    def test_ambiguous_same_day_does_not_choose_a_period(self):
        self.movement('DEPARTURE','2026-10-01T17:00')
        self.assertEqual(http_request('POST','/api/employees/2/production-assignments',self.payload())[0],400)
        self.assertEqual(self.history()['periods'],[])
        self.assertTrue(self.history()['warnings'])

    def test_patch_does_not_move_event_to_new_arrival(self):
        old = self.create()
        mid = self.movement('ARRIVAL','2026-10-20T07:00')
        status, body = http_request('PATCH',f"/api/production-assignments/{old['id']}",
            {**self.payload('2026-10-20'),'arrival_movement_ref':mid,'version':1})
        self.assertEqual(status,400,body)
        self.assertEqual(self.history()['history'][0]['version'],1)

    def test_no_change_to_existing_calendar_and_tables(self):
        self.fact('2026-10-05')
        before = self.snapshot()
        calendar = http_request('GET','/api/employees/2/luvr/calendar',query='year=2026&month=10')[1]
        self.create()
        self.create({**self.payload('2026-10-08'),'assignment_state':'NO_OBJECT','items':[]})
        self.history()
        self.assertEqual(before,self.snapshot())
        self.assertEqual(calendar,http_request('GET','/api/employees/2/luvr/calendar',query='year=2026&month=10')[1])

    def test_foreign_keys_and_unchanged_item_id_on_correction(self):
        old = self.create()
        status, body = http_request('PATCH',f"/api/production-assignments/{old['id']}",{**self.payload(),'version':1})
        self.assertEqual(status,200,body)
        self.assertEqual(body['item']['items'],old['items'])
        for table in ('employees','construction_objects','po_types','object_categories'):
            with self.assertRaises(psycopg.IntegrityError), self.conn.transaction():
                self.conn.execute(f'DELETE FROM {table} WHERE id=%s',(2 if table=='employees' else 1,))

    def test_office_period_does_not_duplicate_old_arrival(self):
        self.conn.execute("UPDATE employee_movements SET event_datetime='2026-09-01 07:00' WHERE id=%s",(self.anchor,))
        self.conn.execute("UPDATE positions SET work_location='OFFICE',work_schedule='FIVE_TWO' WHERE id=9001")
        self.create(dict(effective_from='2026-10-01',period_kind='EXPLICIT',period_start='2026-10-01',
                         period_end='2026-10-31',assignment_state='NO_OBJECT',items=[]))
        self.assertEqual(len(self.history()['periods']),1)
        self.assertEqual(http_request('POST','/api/employees/2/production-assignments',self.payload('2026-10-02'))[0],400)
