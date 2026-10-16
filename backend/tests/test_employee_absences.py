import os,unittest
from contextlib import contextmanager
from unittest.mock import patch
import test_luvr_month
from test_daily_control import http_request
from app.database.migrate_employee_absences import apply_migration


@unittest.skipUnless(os.getenv('DAILY_CONTROL_TEST_DB')=='1','Requires isolated PostgreSQL')
class AbsenceTests(unittest.TestCase):
    def setUp(self):
        test_luvr_month.MonthApiTests.setUp(self)
        apply_migration(self.conn)
        @contextmanager
        def connection():
            with self.conn.transaction():yield self.conn
        mock=patch('app.repositories.employee_absences.get_connection',connection);mock.start();self.addCleanup(mock.stop)
        self.payload=dict(reason='Отпуск',date_from='2026-10-01',date_to='2026-10-10',comment='Согласовано')

    def request(self,method='GET',suffix='',payload=None,employee=2):
        return http_request(method,f'/api/employees/{employee}/absences'+suffix,payload)

    def test_create_edit_delete_and_source(self):
        status,body=self.request('POST',payload=self.payload);self.assertEqual(status,200)
        row=body['item'];self.assertEqual(row['reason'],'Отпуск');self.assertEqual(row['source'],'other')
        status,body=self.request('PATCH',f"/other/{row['id']}",{**self.payload,'reason':'Медосмотр','comment':None});self.assertEqual(status,200)
        self.assertEqual(self.request()[1]['items'][0]['reason'],'Медосмотр')
        self.assertEqual(self.request('DELETE',f"/other/{row['id']}")[0],200)
        self.assertEqual(self.request()[1]['items'],[])

    def test_invalid_values(self):
        for change in ({'reason':''},{'reason':'  '},{'date_from':'bad'},{'date_to':'2026-09-01'},{'date_to':None}):
            self.assertIn(self.request('POST',payload={**self.payload,**change})[0],(400,422))
        self.assertEqual(self.request('POST',payload={**self.payload,'dismissal_date':'2026-10-01'})[0],422)
        self.assertEqual(self.request()[1]['items'],[])

    def test_missing_employee_and_record_ownership(self):
        self.assertEqual(self.request('POST',payload=self.payload,employee=999999)[0],404)
        row=self.request('POST',payload=self.payload)[1]['item']
        for method in ('PATCH','DELETE'):
            self.assertEqual(self.request(method,f"/other/{row['id']}",self.payload if method=='PATCH' else None,employee=1)[0],404)
        self.assertEqual(len(self.request()[1]['items']),1)

    def test_existing_sickness_is_not_copied_and_remains_calculated(self):
        _,body=http_request('POST','/api/employees/2/luvr/sick-periods',dict(date_from='2026-10-02',date_to=None,comment='Старый'))
        record=body['item'];rows=self.request()[1]['items'];self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['source'],'sick');self.assertEqual(rows[0]['reason'],'Больничный')
        before=http_request('GET','/api/employees/2/luvr/calendar',query='year=2026&month=10')[1]
        self.assertEqual(self.request('PATCH',f"/sick/{record['id']}",dict(reason='Лечение',date_from='2026-10-02',date_to=None,comment='Старый'))[0],200)
        self.assertEqual(before,http_request('GET','/api/employees/2/luvr/calendar',query='year=2026&month=10')[1])
        self.assertEqual(self.conn.execute('SELECT count(*) FROM employee_absences').fetchone()[0],0)
        self.assertEqual(self.request('DELETE',f"/sick/{record['id']}")[0],200)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM employee_sick_periods').fetchone()[0],0)

    def test_other_does_not_change_calendar_or_dismissal(self):
        before=http_request('GET','/api/employees/2/luvr/calendar',query='year=2026&month=10')[1]
        self.request('POST',payload={**self.payload,'reason':'Больничный'})
        self.assertEqual(before,http_request('GET','/api/employees/2/luvr/calendar',query='year=2026&month=10')[1])
        self.assertIsNone(self.conn.execute('SELECT dismissal_date FROM employees WHERE id=2').fetchone()[0])

    def test_migration_repeat_preserves_history_and_absences(self):
        row=self.request('POST',payload=self.payload)[1]['item'];apply_migration(self.conn);apply_migration(self.conn)
        self.assertEqual(self.request()[1]['items'],[row])

    def test_absence_protects_employee_history(self):
        self.request('POST',payload=self.payload)
        from psycopg.errors import ForeignKeyViolation,RestrictViolation
        with self.assertRaises((ForeignKeyViolation,RestrictViolation)):
            with self.conn.transaction():self.conn.execute('DELETE FROM employees WHERE id=2')
        self.assertEqual(len(self.request()[1]['items']),1)
        self.assertEqual(self.conn.execute('SELECT 1').fetchone()[0],1)
