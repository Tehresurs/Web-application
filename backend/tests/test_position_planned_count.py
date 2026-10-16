import os
import unittest
import test_luvr_directories
from test_daily_control import http_request
from app.database.migrate_position_planned_count import apply_migration


@unittest.skipUnless(os.getenv('DAILY_CONTROL_TEST_DB')=='1','Requires isolated PostgreSQL')
class PlannedCountTests(unittest.TestCase):
    def setUp(self):
        test_luvr_directories.LuvrDirectoryTests.setUp(self)

    def test_create_edit_read_and_omission(self):
        payload=dict(name='Planned position',planned_count=12,requires_daily_report=True,
                     specialty='Spec',action_description='Action',report_description='Report',aos_description='AOS')
        status,body=http_request('POST','/api/positions',payload)
        self.assertEqual(status,200,body)
        original=body['item'];self.assertEqual(original['planned_count'],12)
        route=f"/api/positions/{original['id']}"
        for count in (0,7):
            status,body=http_request('PATCH',route,{**payload,'planned_count':count})
            self.assertEqual(status,200,body)
            self.assertEqual(body['item'],{**original,'planned_count':count})
            self.assertIn(body['item'],http_request('GET','/api/positions')[1]['items'])
        del payload['planned_count']
        self.assertEqual(http_request('PATCH',route,payload)[1]['item']['planned_count'],7)
        self.assertEqual(http_request('POST','/api/positions',{'name':'Default count'})[1]['item']['planned_count'],0)

    def test_invalid_values(self):
        for value in (-1,1.5,None,True,'4',2147483648):
            for method,route in [('POST','/api/positions'),('PATCH','/api/positions/1')]:
                self.assertEqual(http_request(method,route,{'name':'Invalid','planned_count':value})[0],422)

    def test_migration_preserves_data_and_repeat(self):
        self.conn.execute('ALTER TABLE positions DROP COLUMN planned_count')
        before=self.conn.execute('SELECT to_jsonb(p) FROM positions p ORDER BY id').fetchall()
        apply_migration(self.conn)
        self.assertEqual(before,self.conn.execute("SELECT to_jsonb(p)-'planned_count' FROM positions p ORDER BY id").fetchall())
        self.assertEqual(self.conn.execute('SELECT planned_count FROM positions').fetchall(),[(0,)])
        self.conn.execute('UPDATE positions SET planned_count=9')
        apply_migration(self.conn)
        self.assertEqual(self.conn.execute('SELECT planned_count FROM positions').fetchall(),[(9,)])
        for value in (-1,None):
            with self.assertRaises(Exception),self.conn.transaction():
                self.conn.execute('UPDATE positions SET planned_count=%s',(value,))
