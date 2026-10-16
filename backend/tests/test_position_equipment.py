import os
import unittest
import test_luvr_directories
from test_daily_control import http_request
from app.database.migrate_position_equipment import apply_migration


@unittest.skipUnless(os.getenv('DAILY_CONTROL_TEST_DB')=='1','Requires isolated PostgreSQL')
class EquipmentTests(unittest.TestCase):
    def setUp(self):
        test_luvr_directories.LuvrDirectoryTests.setUp(self)

    def test_create_update_read_clear_and_preserve_omitted(self):
        payload=dict(name='Equipment position',action_description='Action',report_description='Report',
                     aos_description='AOS',requires_daily_report=True,planned_count=12,
                     equipment_description='Набор ВИК\nЛинейка\nРулетка')
        status,result=http_request('POST','/api/positions',payload)
        self.assertEqual(status,200,result)
        original=result['item'];route=f"/api/positions/{original['id']}"
        for value in ('Прибор\n\n  Инструмент  ','',None):
            status,result=http_request('PATCH',route,{**payload,'equipment_description':value})
            self.assertEqual(status,200,result)
            self.assertEqual(result['item'],{**original,'equipment_description':value})
            self.assertIn(result['item'],http_request('GET','/api/positions')[1]['items'])
            omitted={k:v for k,v in payload.items() if k!='equipment_description'}
            self.assertEqual(http_request('PATCH',route,omitted)[1]['item']['equipment_description'],value)
        self.assertIsNone(http_request('POST','/api/positions',{'name':'Empty equipment'})[1]['item']['equipment_description'])

    def test_migration_preserves_all_fields_and_is_idempotent(self):
        self.conn.execute('ALTER TABLE positions DROP COLUMN equipment_description')
        before=self.conn.execute('SELECT to_jsonb(p) FROM positions p ORDER BY id').fetchall()
        apply_migration(self.conn)
        self.assertEqual(before,self.conn.execute("SELECT to_jsonb(p)-'equipment_description' FROM positions p ORDER BY id").fetchall())
        self.assertTrue(all(r[0] is None for r in self.conn.execute('SELECT equipment_description FROM positions')))
        self.conn.execute("UPDATE positions SET equipment_description=%s",('A\nB',))
        before=self.conn.execute('SELECT to_jsonb(p) FROM positions p ORDER BY id').fetchall()
        apply_migration(self.conn)
        self.assertEqual(before,self.conn.execute('SELECT to_jsonb(p) FROM positions p ORDER BY id').fetchall())
