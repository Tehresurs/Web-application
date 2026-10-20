"""DK projections and rollback-only API/database checks on isolated 8001."""
import os
import unittest
from contextlib import contextmanager
from datetime import date
from uuid import uuid4
from copy import deepcopy
from unittest.mock import patch
from app.services import matrix_dk as dk
from app.services.production_matrix import employee_matrix
from app.database.db import get_connection
from app.repositories.directory_errors import DirectoryConflict
from test_daily_control import http_request

class ProjectionTests(unittest.TestCase):
    def project(self,code='FULL',count=2,event=True,source='FACT',position=dk.POSITION):
        items=[dict(id=i+1,object_id=i+1,po_id=1,category_id=1,report_date='2030-01-15') for i in range(count)]
        e=dict(employee_id=1,full_name='DK test',position_name=position,requires_daily_report=True,
               production=dict(facts=deepcopy(items) if source=='FACT' else []),matrix_overrides=[],
               dk_dates=['2030-01-15'] if event else [])
        before=deepcopy(e['production'])
        day=dict(date=date(2030,1,15),final_code=code,calculation_status='CALCULATED',final_source_type='STATE',warnings=[])
        period=dict(effective_from='2030-01-01',effective_to=None,basis_kind='FACTS',assignment_state='OBJECTS',
                    period_key='test',basis_id=[i['id'] for i in items],items=items)
        names={t:{i:'Test '+str(i) for i in range(1,20)} for t in ['construction_objects','construction_subobjects','po_types','object_categories']}
        with patch('app.services.production_matrix.calculate_employee_month',return_value=dict(days=[day])), \
             patch('app.services.production_matrix.project',return_value=dict(periods=[period] if items else [],warnings=[])), \
             patch('app.services.production_matrix.resolve',return_value=dict(intervals=[])):
            result=employee_matrix(e,names,2030,1)
        self.assertEqual(e['production'],before)
        self.assertEqual(result['luvr_days'][0],day)
        return result

    def cells(self,result):
        return [c for row in result['rows'] for c in row['cells'].values()]

    def test_full_and_half_fact_and_plan_are_zero_without_luvr_change(self):
        for code,budget in [('FULL',100),('HALF',50)]:
            for source in ['FACT','PLAN']:
                r=self.project(code=code,source=source)
                self.assertEqual([c['share_cents'] for c in self.cells(r)],[0,0])
                self.assertTrue(all(c['day_event']=='DK' and c['excluded_from_production'] and c['comment']=='Проведен ДК' for c in self.cells(r)))
                self.assertEqual(r['totals']['available_cents'],budget)
                self.assertEqual(r['totals']['distributed_cents'],0)
                self.assertEqual(r['totals']['dk_cents'],budget)
                self.assertEqual(r['checks'][0]['status'],'OK')

    def test_new_reports_do_not_remove_day_event(self):
        for count in [1,2,3,7]:
            self.assertTrue(all(c['is_dk'] for c in self.cells(self.project(count=count))))

    def test_cancel_restores_current_facts_or_plan(self):
        for source in ['FACT','PLAN']:
            self.assertEqual([c['share_cents'] for c in self.cells(self.project(event=False,source=source))],[50,50])
            self.assertEqual([c['share_cents'] for c in self.cells(self.project(code='HALF',event=False,source=source))],[25,25])
            self.assertTrue(all('comment' not in c for c in self.cells(self.project(event=False,source=source))))

    def test_other_positions_and_nonworking_days_are_unchanged(self):
        self.assertEqual(self.project(position='Инженер СК СЛ')['totals']['distributed_cents'],100)
        for code in ['TRAVEL','OFF_SHIFT','EMPTY','DOWNTIME','DISMISSED']:
            self.assertFalse(self.project(code=code)['checks'][0]['is_dk'])

    def test_day_without_object_still_displays_dk(self):
        r=self.project(count=0)
        self.assertEqual(self.cells(r)[0]['kind'],'DK')
        self.assertEqual(r['checks'][0]['status'],'OK')

class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.c=get_connection();self.addCleanup(self.c.close);self.addCleanup(self.c.rollback)
        self.assertEqual(self.c.execute('SELECT current_database(),current_schema()').fetchone(),('ai_excel_agent_test','test_construction_identity_stage46'))
        self.c.execute('SELECT pg_advisory_xact_lock(20261017,29)')
        pid=self.c.execute('SELECT id FROM positions WHERE name=%s',(dk.POSITION,)).fetchone()[0]
        self.employee=self.c.execute('INSERT INTO employees(full_name,position_id) VALUES(%s,%s) RETURNING id',('DK rollback '+uuid4().hex,pid)).fetchone()[0]
        self.target=date(2030,1,15)
        self.c.execute('INSERT INTO luvr_months(year,month) VALUES(2030,1) ON CONFLICT DO NOTHING')
        self.c.execute('INSERT INTO luvr_month_employees(year,month,employee_id) VALUES(2030,1,%s)',(self.employee,))
        self.code('FULL')
        @contextmanager
        def connection():yield self.c
        self.patcher=patch.object(dk,'get_connection',connection);self.patcher.start();self.addCleanup(self.patcher.stop)
        self.env=patch.dict(os.environ,{'TEHRESURS_USER_ROLE':'LEADER'});self.env.start();self.addCleanup(self.env.stop)

    def code(self,value):
        self.c.execute('INSERT INTO employee_luvr_day_overrides(employee_id,work_date,value) VALUES(%s,%s,%s) ON CONFLICT(employee_id,work_date) DO UPDATE SET value=EXCLUDED.value',(self.employee,self.target,value))

    def count(self):
        return self.c.execute('SELECT count(*) FROM production_matrix_dk WHERE employee_id=%s',(self.employee,)).fetchone()[0]

    def path(self):
        return '/api/employees/'+str(self.employee)+'/production-matrix/dk/'+str(self.target)

    def test_assign_unique_cancel_and_reassign(self):
        for value in ['FULL','HALF']:
            self.code(value)
            for _ in range(2):
                status,body=http_request('PUT',self.path())
                self.assertEqual(status,200,body)
            self.assertEqual(self.count(),1)
            self.assertEqual(http_request('DELETE',self.path())[0],200)
            self.assertEqual(self.count(),0)

    def test_nonworking_and_wrong_position_rejected(self):
        for value in ['TRAVEL','OFF_SHIFT','EMPTY','DOWNTIME']:
            self.code(value)
            self.assertEqual(http_request('PUT',self.path())[0],409)
        self.code('FULL')
        other=self.c.execute('SELECT id FROM positions WHERE name<>%s LIMIT 1',(dk.POSITION,)).fetchone()[0]
        self.c.execute('UPDATE employees SET position_id=%s WHERE id=%s',(other,self.employee))
        self.assertEqual(http_request('PUT',self.path())[0],409)

    def test_roles_enforced_on_server_for_both_actions(self):
        dk.set_event(self.employee,self.target,True)
        for role in ['ENGINEER','SYSTEM_TECHNICIAN','UNKNOWN']:
            with patch.dict(os.environ,{'TEHRESURS_USER_ROLE':role}):
                for method in ['PUT','DELETE']:
                    self.assertEqual(http_request(method,self.path())[0],403)
                self.assertFalse(http_request('GET','/api/production-matrix/capabilities')[1]['item']['can_manage_dk'])
        self.assertEqual(self.count(),1)

    def test_source_trigger_cancels_persistently_before_commit(self):
        dk.set_event(self.employee,self.target,True)
        self.code('TRAVEL')
        self.assertEqual(self.c.execute("SELECT current_setting('tehresurs.dk_calendar_dirty')").fetchone()[0],'1')
        self.c._reconcile_dk()
        self.assertEqual(self.count(),0)
        self.code('FULL');self.c._reconcile_dk()
        self.assertEqual(self.count(),0)

    def test_sickness_cancels(self):
        dk.set_event(self.employee,self.target,True)
        self.c.execute('INSERT INTO employee_sick_periods(employee_id,date_from,date_to) VALUES(%s,%s,%s)',(self.employee,self.target,self.target))
        self.c._reconcile_dk();self.assertEqual(self.count(),0)

    def test_other_absence_forbids_and_cancels(self):
        dk.set_event(self.employee,self.target,True)
        self.c.execute("INSERT INTO employee_absences(employee_id,reason,date_from,date_to) VALUES(%s,'DK test',%s,%s)",(self.employee,self.target,self.target))
        self.c._reconcile_dk();self.assertEqual(self.count(),0)
        self.assertEqual(http_request('PUT',self.path())[0],409)

    def test_nested_transaction_hook_and_rollback_are_safe(self):
        dk.set_event(self.employee,self.target,True)
        with self.assertRaisesRegex(RuntimeError,'test rollback'):
            with self.c.transaction():
                self.code('TRAVEL')
                raise RuntimeError('test rollback')
        self.assertEqual(self.count(),1)
        with self.c.transaction():self.code('TRAVEL')
        self.assertEqual(self.count(),0)

    def test_position_change_cancels_without_return(self):
        dk.set_event(self.employee,self.target,True)
        original=self.c.execute('SELECT position_id FROM employees WHERE id=%s',(self.employee,)).fetchone()[0]
        other=self.c.execute('SELECT id FROM positions WHERE name<>%s LIMIT 1',(dk.POSITION,)).fetchone()[0]
        self.c.execute('UPDATE employees SET position_id=%s WHERE id=%s',(other,self.employee))
        self.c._reconcile_dk();self.assertEqual(self.count(),0)
        self.c.execute('UPDATE employees SET position_id=%s WHERE id=%s',(original,self.employee))
        self.c._reconcile_dk();self.assertEqual(self.count(),0)

    def test_all_calendar_source_tables_mark_transactions(self):
        actual={r[0] for r in self.c.execute("SELECT c.relname FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid WHERE t.tgname='matrix_dk_calendar_change' AND c.relnamespace=current_schema()::regnamespace")}
        self.assertEqual(actual,{'employees','positions','employee_movements','rail_tickets','employee_sick_periods','employee_luvr_day_overrides','employee_duration_exceptions','employee_absences'})

    def test_commit_hook_runs_before_database_commit(self):
        dk.set_event(self.employee,self.target,True)
        self.code('TRAVEL')
        with patch('psycopg.Connection.commit') as commit:
            self.c.commit()
            commit.assert_called_once()
        self.assertEqual(self.count(),0)

    def test_matrix_repository_exposes_event_and_zero_totals(self):
        from app.services.production_matrix import calculate_month
        dk.set_event(self.employee,self.target,True)
        @contextmanager
        def connection():yield self.c
        with patch('app.repositories.production_matrix.get_connection',connection):
            m=calculate_month(2030,1,self.employee)
        e=m['employees'][0]
        self.assertEqual(e['totals']['dk_cents'],100)
        self.assertEqual(e['checks'][14]['day_event'],'DK')
        self.assertEqual(e['checks'][14]['distributed_cents'],0)
        self.assertEqual(e['checks'][14]['available_cents'],100)

    def test_saved_report_keeps_dk_and_cancel_restores_latest_fact(self):
        from app.services.production_matrix import calculate_month
        self.c.execute('UPDATE positions SET requires_daily_report=true WHERE id=(SELECT position_id FROM employees WHERE id=%s)',(self.employee,))
        dk.set_event(self.employee,self.target,True)
        fact=self.c.execute("""INSERT INTO daily_control_results(report_date,employee_id,object_id,subobject_id,entity_id,
            po_id,category_id,subcontractor_id,source_file,source_sha256)
            SELECT %s,%s,object_id,subobject_id,entity_id,po_id,category_id,subcontractor_id,
                   'DK rollback report.docx',repeat('d',64) FROM daily_control_results LIMIT 1 RETURNING id""",
            (self.target,self.employee)).fetchone()[0]
        self.c._reconcile_dk();self.assertEqual(self.count(),1)
        @contextmanager
        def connection():yield self.c
        with patch('app.repositories.production_matrix.get_connection',connection):
            e=calculate_month(2030,1,self.employee)['employees'][0]
            cell=next(c for r in e['rows'] for c in r['cells'].values() if c.get('source_fact_id')==fact)
            self.assertEqual((cell['source'],cell['share_cents'],cell['day_event']),('FACT',0,'DK'))
            dk.set_event(self.employee,self.target,False)
            e=calculate_month(2030,1,self.employee)['employees'][0]
            cell=next(c for r in e['rows'] for c in r['cells'].values() if c.get('source_fact_id')==fact)
            self.assertEqual((cell['source'],cell['share_cents']),('FACT',100))
            self.assertNotIn('comment',cell)
        self.assertEqual(self.c.execute('SELECT count(*) FROM daily_control_results WHERE id=%s',(fact,)).fetchone()[0],1)
