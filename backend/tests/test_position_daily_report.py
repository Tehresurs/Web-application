import os
import unittest
import test_luvr_directories
from test_daily_control import http_request
from app.database.migrate_position_requires_daily_report import apply_migration


@unittest.skipUnless(os.getenv('DAILY_CONTROL_TEST_DB') == '1', 'Requires isolated PostgreSQL')
class PositionDailyReportTests(unittest.TestCase):
    def setUp(self):
        test_luvr_directories.LuvrDirectoryTests.setUp(self)

    def test_migration_default_preservation_and_repeat(self):
        self.conn.execute('ALTER TABLE positions DROP COLUMN requires_daily_report')
        before = self.conn.execute('SELECT to_jsonb(p) FROM positions p ORDER BY id').fetchall()
        apply_migration(self.conn)
        self.assertEqual(before, self.conn.execute("SELECT to_jsonb(p)-'requires_daily_report' FROM positions p ORDER BY id").fetchall())
        self.assertEqual(self.conn.execute('SELECT requires_daily_report FROM positions').fetchall(), [(False,)])
        self.conn.execute('UPDATE positions SET requires_daily_report=true')
        apply_migration(self.conn)
        self.assertEqual(self.conn.execute('SELECT requires_daily_report FROM positions').fetchall(), [(True,)])
        with self.assertRaises(Exception), self.conn.transaction():
            self.conn.execute('UPDATE positions SET requires_daily_report=NULL')

    def test_api_create_update_list_and_omitted_value(self):
        payload = dict(name='Report position', specialty='Spec', action_description='Action',
                       report_description='Report', aos_description='AOS',
                       work_location='OBJECT', work_schedule='SHIFT', requires_daily_report=True)
        status, body = http_request('POST', '/api/positions', payload)
        self.assertEqual(status, 200, body)
        original = body['item']
        route = f"/api/positions/{original['id']}"
        for value in (False, True):
            status, body = http_request('PATCH', route, {**payload, 'requires_daily_report': value})
            self.assertEqual(status, 200, body)
            expected = {**original, 'requires_daily_report': value}
            self.assertEqual(body['item'], expected)
            self.assertIn(expected, http_request('GET', '/api/positions')[1]['items'])
        omitted = {k:v for k,v in payload.items() if k != 'requires_daily_report'}
        self.assertTrue(http_request('PATCH', route, omitted)[1]['item']['requires_daily_report'])
        default = http_request('POST', '/api/positions', {'name':'Default position'})[1]['item']
        self.assertFalse(default['requires_daily_report'])

    def test_invalid_boolean_rejected(self):
        for value in (None, 'false', 1):
            self.assertEqual(http_request('POST', '/api/positions', {'name':'Invalid', 'requires_daily_report':value})[0], 422)
