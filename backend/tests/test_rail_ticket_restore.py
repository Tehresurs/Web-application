import os
import unittest
from unittest.mock import patch

import test_luvr_calendar
import test_rail_tickets
from test_daily_control import http_request
from app.repositories import rail_tickets
from app.repositories.directory_errors import DirectoryConflict
from app.database.migrate_rail_ticket_restore import apply_migration


@unittest.skipUnless(os.getenv('DAILY_CONTROL_TEST_DB')=='1','Requires isolated PostgreSQL')
class TicketRestoreTests(unittest.TestCase):
    def setUp(self):
        test_luvr_calendar.CalendarApiTests.setUp(self)

    upload=test_rail_tickets.RailTicketTests.upload
    action=test_rail_tickets.RailTicketTests.action

    def calendar(self):
        status,data=http_request('GET','/api/employees/2/luvr/calendar',query='year=2026&month=9')
        self.assertEqual(status,200,data)
        return data['item']

    def test_confirmed_round_trip_preserves_movement_and_calendar(self):
        ticket=self.upload();status,data=self.action(ticket,'confirm');self.assertEqual(status,200,data)
        mid=data['item']['movement_id']
        original=self.conn.execute('SELECT to_jsonb(m) FROM employee_movements m WHERE id=%s',(mid,)).fetchone()[0]
        calendar=self.calendar()
        for _ in range(2):
            self.assertEqual(self.action(ticket,'annul')[1]['item']['status'],'ANNULLED')
            self.assertEqual(self.action(ticket,'annul')[0],200)
            self.assertIsNone(self.conn.execute('SELECT id FROM employee_movements WHERE id=%s',(mid,)).fetchone())
            self.assertNotEqual(self.calendar(),calendar)
            restored=self.action(ticket,'restore');self.assertEqual(restored[0],200,restored)
            self.assertEqual(restored[1]['item']['status'],'CONFIRMED')
            self.assertEqual(restored[1]['item']['movement_id'],mid)
            self.assertEqual(self.action(ticket,'restore')[0],200)
            self.assertEqual(self.conn.execute('SELECT to_jsonb(m) FROM employee_movements m WHERE id=%s',(mid,)).fetchone()[0],original)
            self.assertEqual(self.calendar(),calendar)
            self.assertEqual(self.conn.execute('SELECT count(*) FROM employee_movements').fetchone()[0],1)

    def test_review_states_are_not_promoted_to_confirmed(self):
        ticket=self.upload()
        for state in ('PARSED','PARSE_ERROR','REJECTED'):
            self.conn.execute('UPDATE rail_tickets SET status=%s WHERE id=%s',(state,ticket['id']))
            before=rail_tickets.get_ticket(ticket['id'])['processing_status']
            self.assertEqual(self.action(ticket,'annul')[0],200)
            restored=self.action(ticket,'restore');self.assertEqual(restored[0],200,restored)
            self.assertEqual(restored[1]['item']['status'],state)
            self.assertEqual(restored[1]['item']['processing_status'],before)
            self.assertEqual(self.conn.execute('SELECT count(*) FROM employee_movements').fetchone()[0],0)

    def test_reupload_preserves_annulled_state_and_duplicate_identity(self):
        ticket=self.upload();self.action(ticket,'confirm');self.action(ticket,'annul')
        again=self.upload()
        self.assertEqual(again['id'],ticket['id']);self.assertEqual(again['status'],'ANNULLED')
        self.assertEqual(self.action(ticket,'restore')[0],200)
        self.assertEqual(self.upload()['id'],ticket['id'])
        self.assertEqual(self.conn.execute('SELECT count(*) FROM rail_tickets').fetchone()[0],1)

    def test_legacy_annulment_does_not_guess(self):
        ticket=self.upload()
        self.conn.execute("UPDATE rail_tickets SET status='ANNULLED',annul_snapshot=NULL WHERE id=%s",(ticket['id'],))
        self.assertEqual(self.action(ticket,'restore')[0],409)
        self.assertEqual(rail_tickets.get_ticket(ticket['id'])['status'],'ANNULLED')

    def test_failed_restore_rolls_back_movement_and_status(self):
        ticket=self.upload();self.action(ticket,'confirm');self.action(ticket,'annul')
        with patch.object(rail_tickets,'_view',side_effect=DirectoryConflict('test rollback')):
            self.assertEqual(self.action(ticket,'restore')[0],409)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM employee_movements').fetchone()[0],0)
        self.assertEqual(rail_tickets.get_ticket(ticket['id'])['status'],'ANNULLED')
        self.assertEqual(self.action(ticket,'restore')[0],200)

    def test_annulled_cannot_be_rejected_or_reassigned(self):
        ticket=self.upload();self.action(ticket,'annul')
        self.assertEqual(self.action(ticket,'reject')[0],409)
        self.assertEqual(http_request('PATCH',f'/api/rail-tickets/{ticket["id"]}/object',{'object_id':1})[0],409)
        self.assertEqual(self.action(ticket,'restore')[1]['item']['status'],'PARSED')

    def test_migration_idempotent_preserves_snapshot(self):
        ticket=self.upload();self.action(ticket,'confirm');self.action(ticket,'annul')
        before=self.conn.execute('SELECT to_jsonb(t) FROM rail_tickets t').fetchall()
        apply_migration(self.conn);apply_migration(self.conn)
        self.assertEqual(before,self.conn.execute('SELECT to_jsonb(t) FROM rail_tickets t').fetchall())
