import os
import unittest
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from unittest.mock import patch
import test_luvr_calendar
from test_luvr_calendar import inputs, movement
from test_daily_control import http_request
from app.services.luvr_calendar import calculate_employee_month
from app.services.luvr_month import calendar_totals


class MonthCalculationTests(unittest.TestCase):
    def test_five_two_real_months_ignore_movements(self):
        for year,month,count in [(2026,2,28),(2024,2,29),(2026,4,30),(2026,10,31)]:
            result=calculate_employee_month(inputs([movement(1,'DEPARTURE','2024-01-01T10:00')],work_location='OFFICE',work_schedule='FIVE_TWO'),year,month)
            self.assertEqual(result['mode'],'FIVE_TWO');self.assertEqual(len(result['days']),count)
            for day in result['days']:
                self.assertEqual(day['final_code'],'FULL' if day['date'].weekday()<5 else 'EMPTY')
                self.assertEqual(day['movement_ids'],[])

    def test_five_two_sickness_override_dismissal(self):
        data=inputs(work_location='OFFICE',work_schedule='FIVE_TWO',dismissal_date=date(2026,10,15),
            sick_periods=[{'date_from':date(2026,10,7),'date_to':date(2026,10,9)}],
            overrides=[{'id':1,'work_date':date(2026,10,10),'value':'FULL'}])
        days=calculate_employee_month(data,2026,10)['days']
        self.assertEqual([d['final_code'] for d in days[4:11]],['FULL','FULL','EMPTY','EMPTY','EMPTY','FULL','EMPTY'])
        self.assertEqual(days[9]['auto_code'],'EMPTY');self.assertEqual(days[14]['final_code'],'DISMISSED')
        self.assertTrue(all(d['final_code']=='EMPTY' for d in days[15:]))
        self.assertEqual(calendar_totals(days)['sick_days_count'],3)

    def test_final_totals(self):
        codes=['FULL']*10+['HALF']*2+['TRAVEL']*3+['OFF_SHIFT']*5+['DOWNTIME']+['EMPTY','DISMISSED']
        totals=calendar_totals([dict(final_code=c,auto_code='FULL',manually_changed=False,is_sick=False) for c in codes])
        self.assertEqual([totals[k] for k in ['work_days_total','travel_days_total','off_shift_days_total','downtime_days_total']],[11,3,5,1])

    def test_shift_cycle_totals(self):
        data=inputs([movement(1,'DEPARTURE','2026-10-06T10:00'),movement(2,'ARRIVAL','2026-10-21T10:00','RAIL','2026-10-20T23:00')])
        totals=calendar_totals(calculate_employee_month(data,2026,10)['days'])
        self.assertEqual(totals['work_days_total'],10.5);self.assertEqual(totals['travel_days_total'],2);self.assertEqual(totals['off_shift_days_total'],13)

    def test_invalid_configuration_diagnostic(self):
        result=calculate_employee_month(inputs(work_schedule='FIVE_TWO'),2026,10)
        self.assertEqual(result['mode'],'CONFIGURATION_ERROR')
        self.assertTrue(all(d['warnings'][0]['code']=='INVALID_WORK_CONFIGURATION' for d in result['days']))


@unittest.skipUnless(os.getenv('DAILY_CONTROL_TEST_DB')=='1','Requires isolated PostgreSQL tests')
class MonthApiTests(unittest.TestCase):
    def setUp(self):
        test_luvr_calendar.CalendarApiTests.setUp(self)
        self.conn.execute(Path('app/database/migrations/009_luvr_month.sql').read_text(encoding='utf-8'))
        self.conn.execute(Path('app/database/migrations/010_luvr_header.sql').read_text(encoding='utf-8'))
        from app.database.migrate_luvr_footer import apply_migration
        apply_migration(self.conn,'Тестовый согласующий')
        @contextmanager
        def connection():
            with self.conn.transaction():yield self.conn
        mock=patch('app.repositories.luvr_month.get_connection',connection);mock.start();self.addCleanup(mock.stop)

    def request(self,method='GET',suffix='',payload=None,month=10):
        return http_request(method,'/api/luvr/month'+suffix,payload,query=f'year=2026&month={month}')

    def form(self,month=10):
        status,body=self.request('POST','/form',{'year':2026,'month':month});self.assertEqual(status,200,body)

    def test_get_unformed_is_read_only(self):
        self.assertFalse(self.request()[1]['item']['formed'])
        self.assertEqual(self.conn.execute('SELECT count(*) FROM luvr_months').fetchone()[0],0)

    def test_form_repeat_and_empty_month_stays_formed(self):
        self.form();ids=[e['employee_id'] for e in self.request()[1]['item']['employees']]
        for employee in ids:self.assertEqual(self.request('DELETE',f'/employees/{employee}')[0],200)
        self.form();result=self.request()[1]['item'];self.assertTrue(result['formed']);self.assertEqual(result['employees'],[])

    def test_add_new_employee_explicitly_and_idempotently(self):
        self.form();eid=self.conn.execute("INSERT INTO employees(full_name) VALUES('Новый Сотрудник') RETURNING id").fetchone()[0]
        self.form();self.assertNotIn(eid,[e['employee_id'] for e in self.request()[1]['item']['employees']])
        for _ in range(2):self.assertEqual(self.request('POST','/employees',{'year':2026,'month':10,'employee_id':eid})[0],200)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM luvr_month_employees WHERE employee_id=%s',(eid,)).fetchone()[0],1)

    def test_archive_and_dismissal_preserve_membership(self):
        self.form();self.conn.execute("UPDATE employees SET is_archived=true,dismissal_date='2026-10-15' WHERE id=2")
        row=next(e for e in self.request()[1]['item']['employees'] if e['employee_id']==2)
        self.assertEqual(row['days'][14]['final_code'],'DISMISSED');self.assertTrue(row['is_archived'])
        self.form(11);self.assertNotIn(2,[e['employee_id'] for e in self.request(month=11)[1]['item']['employees']])
        self.assertEqual(self.request('POST','/employees',{'year':2026,'month':11,'employee_id':2})[0],200)

    def test_dismissed_within_month_included_before_month_excluded(self):
        self.conn.execute("UPDATE employees SET dismissal_date='2026-10-15' WHERE id=2")
        self.form();self.assertIn(2,[e['employee_id'] for e in self.request()[1]['item']['employees']])
        self.form(11);self.assertNotIn(2,[e['employee_id'] for e in self.request(month=11)[1]['item']['employees']])

    def test_remove_only_membership_preserves_all_existing_rows(self):
        test_luvr_calendar.CalendarApiTests.create(self,'movements',{'movement_type':'ARRIVAL','transport_type':'SELF','event_datetime':'2026-10-01T07:00'})
        self.form()
        tables=[r[0] for r in self.conn.execute("SELECT tablename FROM pg_tables WHERE schemaname=current_schema() AND tablename<>'luvr_month_employees'").fetchall()]
        snapshot=lambda:{t:self.conn.execute(f'SELECT to_jsonb(r) FROM {t} r ORDER BY to_jsonb(r)::text').fetchall() for t in tables}
        before=snapshot();self.assertEqual(self.request('DELETE','/employees/2')[0],200);self.assertEqual(snapshot(),before)

    def test_five_two_override_recalculates_totals_and_reset(self):
        self.conn.execute("UPDATE positions SET work_location='OFFICE',work_schedule='FIVE_TWO' WHERE id=9001");self.form()
        row=lambda:next(e for e in self.request()[1]['item']['employees'] if e['employee_id']==2)
        self.assertEqual(row()['totals']['work_days_total'],22)
        override=test_luvr_calendar.CalendarApiTests.create(self,'day-overrides',{'work_date':'2026-10-03','value':'FULL'})
        self.assertEqual(row()['totals']['work_days_total'],23)
        test_luvr_calendar.CalendarApiTests.create(self,'day-overrides',{'work_date':'2026-10-03','value':'DOWNTIME'})
        self.assertEqual(row()['totals']['downtime_days_total'],1);self.assertEqual(row()['totals']['work_days_total'],22)
        http_request('DELETE',f'/api/employees/2/luvr/day-overrides/{override["id"]}')
        self.assertEqual(row()['totals']['downtime_days_total'],0)

    def test_validation_and_add_before_form(self):
        self.assertEqual(self.request('POST','/employees',{'year':2026,'month':10,'employee_id':2})[0],409)
        self.form();self.assertEqual(self.request('POST','/employees',{'year':2026,'month':10,'employee_id':99999})[0],404)
        self.assertEqual(self.request(month=13)[0],422)
        self.assertIn('/api/luvr/month',http_request('GET','/openapi.json')[1]['paths'])

    def test_sorting_sickness_and_read_only_formed_get(self):
        self.conn.execute("UPDATE employees SET full_name='  Яковлев   Яков Яковлевич' WHERE id=2")
        self.conn.execute("INSERT INTO employees(full_name) VALUES('Абрамов Иван Иванович')")
        self.conn.execute("UPDATE positions SET work_location='OFFICE',work_schedule='FIVE_TWO' WHERE id=9001")
        test_luvr_calendar.CalendarApiTests.create(self,'sick-periods',{'date_from':'2026-10-07','date_to':'2026-10-09'})
        self.form();before=self.conn.execute('SELECT * FROM luvr_month_employees ORDER BY id').fetchall()
        result=self.request()[1]['item'];names=[e['full_name'] for e in result['employees']]
        self.assertEqual(names,sorted(names,key=lambda s:' '.join(s.split()).casefold()))
        row=next(e for e in result['employees'] if e['employee_id']==2)
        self.assertEqual(row['totals']['work_days_total'],19);self.assertEqual(row['totals']['sick_days_count'],3)
        self.assertEqual(before,self.conn.execute('SELECT * FROM luvr_month_employees ORDER BY id').fetchall())

    def test_membership_constraints_and_employee_delete_stays_forbidden(self):
        import psycopg
        self.form()
        with self.assertRaises(psycopg.errors.UniqueViolation),self.conn.transaction():
            self.conn.execute('INSERT INTO luvr_month_employees(year,month,employee_id) VALUES(2026,10,2)')
        with self.assertRaises(psycopg.errors.ForeignKeyViolation),self.conn.transaction():
            self.conn.execute('INSERT INTO luvr_month_employees(year,month,employee_id) VALUES(2026,10,99999)')
        self.assertEqual(http_request('DELETE','/api/employees/2')[0],409)
        self.assertTrue(self.conn.execute('SELECT id FROM employees WHERE id=2').fetchone())

    def test_migration_idempotent_and_metadata_current(self):
        self.form();before=self.conn.execute('SELECT * FROM luvr_month_employees ORDER BY id').fetchall()
        self.conn.execute(Path('app/database/migrations/009_luvr_month.sql').read_text(encoding='utf-8'))
        self.assertEqual(before,self.conn.execute('SELECT * FROM luvr_month_employees ORDER BY id').fetchall())
        self.conn.execute("UPDATE employees SET nrs_number='NR-123' WHERE id=2")
        row=next(e for e in self.request()[1]['item']['employees'] if e['employee_id']==2)
        self.assertEqual(row['nrs_number'],'NR-123');self.assertEqual(row['position_name'],'Вахта')
