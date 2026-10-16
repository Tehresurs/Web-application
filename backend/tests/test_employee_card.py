import os
import unittest
import test_luvr_directories
from test_daily_control import http_request
from app.database.migrate_employee_email import apply_migration


@unittest.skipUnless(os.getenv('DAILY_CONTROL_TEST_DB') == '1', 'Requires isolated PostgreSQL')
class EmployeeCardTests(unittest.TestCase):
    def setUp(self):
        test_luvr_directories.LuvrDirectoryTests.setUp(self)

    def test_email_crud_omission_and_clear(self):
        status, data = http_request('POST','/api/employees',{'full_name':'Email test','email':' person@example.com '})
        self.assertEqual(status,200,data)
        employee_id=data['id']
        def email():
            return next(x for x in http_request('GET','/api/employees')[1]['items'] if x['id']==employee_id)['email']
        self.assertEqual(email(),'person@example.com')
        self.assertEqual(http_request('PATCH',f'/api/employees/{employee_id}',{'full_name':'Email test'})[0],200)
        self.assertEqual(email(),'person@example.com')
        self.assertEqual(http_request('PATCH',f'/api/employees/{employee_id}',{'full_name':'Email test','email':None})[0],200)
        self.assertIsNone(email())

    def test_migration_preserves_existing_data_and_email(self):
        self.conn.execute("UPDATE employees SET email='kept@example.com' WHERE id=1")
        before=self.conn.execute('SELECT to_jsonb(e) FROM employees e ORDER BY id').fetchall()
        apply_migration(self.conn)
        apply_migration(self.conn)
        self.assertEqual(before,self.conn.execute('SELECT to_jsonb(e) FROM employees e ORDER BY id').fetchall())

    def test_email_limit(self):
        self.assertEqual(http_request('POST','/api/employees',{'full_name':'Email test','email':'a'*255})[0],422)
