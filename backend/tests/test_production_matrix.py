import os
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
import test_production_matrix_overrides
from test_daily_control import http_request
from app.services.production_matrix import distribute


class DistributionTests(unittest.TestCase):
    def test_exact_hundredths_for_many_counts(self):
        for available in (0,50,100):
            for count in range(1,151):
                values=distribute(available,count)
                self.assertEqual(sum(values),available)
                self.assertEqual(values[:-1],[available//count]*(count-1))
        self.assertEqual(distribute(100,3),[33,33,34])


@unittest.skipUnless(os.getenv('DAILY_CONTROL_TEST_DB')=='1','Requires isolated PostgreSQL')
class ProductionMatrixTests(unittest.TestCase):
    movement=test_production_matrix_overrides.MatrixOverrideTests.movement
    payload=test_production_matrix_overrides.MatrixOverrideTests.payload
    create=test_production_matrix_overrides.MatrixOverrideTests.create
    history=test_production_matrix_overrides.MatrixOverrideTests.history
    fact=test_production_matrix_overrides.MatrixOverrideTests.fact
    snapshot=test_production_matrix_overrides.MatrixOverrideTests.snapshot
    upload=test_production_matrix_overrides.MatrixOverrideTests.upload
    action=test_production_matrix_overrides.MatrixOverrideTests.action
    request=test_production_matrix_overrides.MatrixOverrideTests.request
    write=test_production_matrix_overrides.MatrixOverrideTests.write
    read=test_production_matrix_overrides.MatrixOverrideTests.read

    def setUp(self):
        test_production_matrix_overrides.MatrixOverrideTests.setUp(self)
        self.conn.execute(Path('app/database/migrations/009_luvr_month.sql').read_text(encoding='utf-8'))
        self.conn.execute('INSERT INTO luvr_months(year,month) VALUES(2026,10)')
        self.conn.execute('INSERT INTO luvr_month_employees(year,month,employee_id) VALUES(2026,10,2)')
        self.conn.execute("INSERT INTO construction_objects(id,name) VALUES(3,'Object 3')")
        self.conn.execute('UPDATE positions SET requires_daily_report=true WHERE id=9001')
        @contextmanager
        def connection():
            with self.conn.transaction():yield self.conn
        mock=patch('app.repositories.production_matrix.get_connection',connection)
        mock.start();self.addCleanup(mock.stop)

    def matrix(self,query='year=2026&month=10'):
        status,body=http_request('GET','/api/production-matrix',query=query)
        self.assertEqual(status,200,body)
        return body['item']

    def employee(self):return self.matrix()['employees'][0]

    def test_departure_travel_uses_calendar_availability_across_month(self):
        from rail_fixture import coupon_pdf
        from test_rail_tickets import upload_request
        self.conn.execute('INSERT INTO luvr_months(year,month) VALUES(2026,11)')
        self.conn.execute('INSERT INTO luvr_month_employees(year,month,employee_id) VALUES(2026,11,2)')
        pdf=coupon_pdf(departure_station='Салым',arrival_station='Тюмень',
                       departure_datetime='30.10.2026 15:00',arrival_datetime='02.11.2026 07:30')
        ticket=upload_request([('departure.pdf',pdf)])[1]['items'][0]
        status,result=http_request('POST',f'/api/rail-tickets/{ticket["id"]}/confirm',{})
        self.assertEqual(status,200,result)
        october=self.employee()
        november=self.matrix('year=2026&month=11')['employees'][0]
        self.assertEqual([d['final_code'] for d in october['luvr_days'][29:]+november['luvr_days'][:2]],
                         ['HALF','TRAVEL','TRAVEL','TRAVEL'])
        self.assertEqual([d['available_cents'] for d in october['checks'][29:]+november['checks'][:2]],
                         [50,0,0,0])
        self.assertTrue(all(not r['cells'] for r in november['rows']))

    def geodetic_migration(self):
        from app.database.migrate_geodetic_control import apply_migration
        self.conn.execute('UPDATE positions SET name=%s WHERE id=9001',('Инженер СК (Геодезические работы)',))
        apply_migration(self.conn)

    def test_geodetic_migration_preserves_history_and_binds_by_id(self):
        from app.database.migrate_geodetic_control import apply_migration
        self.write(self.request())
        self.fact('2026-10-05')
        tables=['daily_control_results','production_assignment_changes','production_assignment_items','production_matrix_overrides']
        before={t:self.conn.execute(f'SELECT to_jsonb(r) FROM {t} r ORDER BY id').fetchall() for t in tables}
        self.geodetic_migration()
        self.conn.execute("UPDATE positions SET name='Renamed position' WHERE id=9001")
        apply_migration(self.conn)
        self.assertEqual(before,{t:self.conn.execute(f'SELECT to_jsonb(r) FROM {t} r ORDER BY id').fetchall() for t in tables})
        self.assertEqual(self.history()['default_control_mode'],'GEODETIC')
        self.assertEqual(self.cells('2026-10-02')[0]['control_mode'],'INSPECTION')

    def test_geodetic_new_assignment_defaults_and_explicit_modes(self):
        self.geodetic_migration()
        base={'object_id':1,'po_id':1,'initial_category_id':1}
        created=self.create({**self.payload('2026-10-02'),'items':[base]})
        self.assertEqual(created['items'][0]['initial_control_mode'],'GEODETIC')
        self.assertEqual(self.cells('2026-10-03')[0]['control_mode'],'GEODETIC')
        for day,mode in [('04','INSPECTION'),('06','OPERATIONAL'),('08',None)]:
            created=self.create({**self.payload('2026-10-'+day),'items':[{**base,'initial_control_mode':mode}]})
            self.assertEqual(created['items'][0]['initial_control_mode'],mode)
        status,body=http_request('PATCH',f"/api/production-assignments/{created['id']}",
            {**self.payload('2026-10-08'),'items':[base],'version':1})
        self.assertEqual(status,200,body)
        self.assertIsNone(body['item']['items'][0]['initial_control_mode'])

    def test_geodetic_override_inherits_across_month_and_stops_at_new_basis(self):
        self.geodetic_migration()
        self.write(self.request('2026-10-03','CONTROL_MODE','GEODETIC'))
        self.write(self.request('2026-10-05','CATEGORY',90))
        self.conn.execute('INSERT INTO luvr_months(year,month) VALUES(2026,11)')
        self.conn.execute('INSERT INTO luvr_month_employees(year,month,employee_id) VALUES(2026,11,2)')
        row=self.matrix('year=2026&month=11')['employees'][0]['rows'][0]
        self.assertEqual(row['cells']['2026-11-01']['control_mode'],'GEODETIC')
        self.assertEqual(row['cells']['2026-11-01']['category_id'],90)
        self.fact('2026-10-10',1)
        self.assertIsNone(self.cells('2026-10-11')[0]['control_mode'])
        self.assertEqual(len(self.employee()['rows']),1)
        self.create({**self.payload('2026-10-12'),'items':[{'object_id':2,'po_id':1,'initial_category_id':1}]})
        self.assertEqual(self.cells('2026-10-13')[0]['object_id'],2)
        self.assertEqual(self.cells('2026-10-13')[0]['control_mode'],'GEODETIC')

    def test_geodetic_rejected_for_other_position_and_cameral_stays_automatic(self):
        from app.database.migrate_geodetic_control import apply_migration
        apply_migration(self.conn)
        status,body=http_request('POST','/api/employees/2/production-assignments',
            {**self.payload('2026-10-02'),'items':[{**self.item,'initial_control_mode':'GEODETIC'}]})
        self.assertEqual(status,400,body)
        self.assertEqual(http_request('PATCH','/api/employees/2/production-matrix-overrides',self.request(value='GEODETIC'))[0],400)
        self.geodetic_migration()
        self.create({**self.payload('2026-10-05'),'assignment_state':'NO_OBJECT','items':[]})
        self.assertEqual(self.cells('2026-10-06')[0]['control_mode'],'CAMERAL')
        self.assertIsNone(self.cells('2026-10-06')[0]['edit_target'])
        self.assertEqual(http_request('PATCH','/api/employees/2/production-matrix-overrides',self.request(value='CAMERAL'))[0],422)

    def cells(self,day):
        return sorted([r['cells'][day] for r in self.employee()['rows'] if day in r['cells']],key=lambda r:r['object_id'] or 0)

    def check(self,day):return next(d for d in self.employee()['checks'] if d['date']==day)

    def test_one_two_three_objects_stable_rounding_and_details(self):
        for count in (1,2,3):
            status,body=http_request('PATCH',f"/api/production-assignments/{self.saved['id']}",
                {**self.payload(),'version':count,'items':[{**self.item,'object_id':i} for i in reversed(range(1,count+1))]})
            self.assertEqual(status,200,body)
            cells=self.cells('2026-10-03')
            self.assertEqual([c['share_cents'] for c in cells],{1:[100],2:[50,50],3:[33,33,34]}[count])
            self.assertTrue(all(c['report_required'] for c in cells))
            self.assertEqual(self.check('2026-10-03')['status'],'OK')
            for cell in cells:
                self.assertEqual(cell['employee_id'],2)
                self.assertEqual(cell['source'],'PLAN')
                self.assertEqual(cell['category_id'],1)
                self.assertTrue(cell['object_name'])
                self.assertIsNotNone(cell['edit_target'])
        before=[c['share_cents'] for c in self.cells('2026-10-03')]
        self.conn.execute("UPDATE construction_objects SET name='Renamed' WHERE id=1")
        self.assertEqual([c['share_cents'] for c in self.cells('2026-10-03')],before)

    def test_half_day_uses_existing_calendar(self):
        self.create({**self.payload('2026-10-02'),'items':[self.item,{**self.item,'object_id':2}]})
        self.conn.execute("INSERT INTO employee_luvr_day_overrides(employee_id,work_date,value) VALUES(2,'2026-10-03','HALF')")
        self.assertEqual([c['share_cents'] for c in self.cells('2026-10-03')],[25,25])
        self.assertEqual(self.check('2026-10-03')['available_cents'],50)

    def test_new_fact_and_multiple_facts_override_plan(self):
        ids=[self.fact('2026-10-05',obj) for obj in (1,2,3)]
        cells=self.cells('2026-10-05')
        self.assertEqual([c['source_fact_id'] for c in cells],ids)
        self.assertEqual([c['share_cents'] for c in cells],[33,33,34])
        self.assertTrue(all(c['source']=='FACT' and c['report_received'] for c in cells))
        next_day=self.cells('2026-10-06')
        self.assertTrue(all(c['source']=='PLAN' for c in next_day))
        self.assertEqual([c['source_fact_id'] for c in next_day],ids)
        self.fact('2026-10-10',2)
        self.assertEqual([c['object_id'] for c in self.cells('2026-10-11')],[2])

    def test_category_mode_changes_and_api_edit_tokens(self):
        self.write(self.request())
        self.write(self.request('2026-10-05','CATEGORY',90))
        cell=self.cells('2026-10-06')[0]
        self.assertEqual((cell['category_id'],cell['control_mode']),(90,'OPERATIONAL'))
        target=cell['edit_target']
        fields=target.pop('fields')
        self.assertEqual(fields['CONTROL_MODE']['version'],0)
        status,body=http_request('PATCH','/api/employees/2/production-matrix-overrides',
            {**target,'field_name':'CONTROL_MODE','control_mode':'INSPECTION','version':0})
        self.assertEqual(status,200,body)
        self.assertEqual(self.cells('2026-10-07')[0]['control_mode'],'INSPECTION')
        self.assertEqual(self.cells('2026-10-07')[0]['category_id'],90)

    def test_assignment_change_and_cameral_accounting(self):
        self.create({**self.payload('2026-10-05'),'items':[{**self.item,'object_id':2}]})
        self.create({**self.payload('2026-10-10'),'assignment_state':'NO_OBJECT','items':[]})
        self.assertEqual(self.cells('2026-10-06')[0]['object_id'],2)
        cameral=self.cells('2026-10-11')[0]
        self.assertEqual(cameral['control_mode'],'CAMERAL')
        self.assertIsNone(cameral['category_id'])
        self.assertFalse(cameral['report_required'])
        self.assertIsNone(cameral['edit_target'])
        check=self.check('2026-10-11')
        self.assertEqual((check['object_cents'],check['cameral_cents'],check['distributed_cents'],check['status']),(0,100,100,'OK'))

    def test_incomplete_and_unknown_are_not_cameral(self):
        self.create({**self.payload('2026-10-05'),'items':[{'object_id':2}]})
        self.assertEqual(self.check('2026-10-06')['status'],'WARNING')
        self.assertIn('ASSIGNMENT_INCOMPLETE',self.check('2026-10-06')['warnings'])
        self.assertIsNone(self.cells('2026-10-06')[0]['control_mode'])
        self.movement('DEPARTURE','2026-10-12T10:00')
        self.movement('ARRIVAL','2026-10-20T07:00')
        self.assertEqual(self.cells('2026-10-21'),[])
        self.assertEqual(self.check('2026-10-21')['status'],'WARNING')
        self.assertEqual(self.check('2026-10-21')['cameral_cents'],0)

    def test_departure_partial_day_and_repeat_arrival(self):
        self.movement('DEPARTURE','2026-10-12T17:00')
        self.assertEqual(self.cells('2026-10-12')[0]['share_cents'],50)
        self.assertEqual(self.cells('2026-10-13'),[])
        mid=self.movement('ARRIVAL','2026-10-20T07:00')
        self.assertEqual(self.cells('2026-10-20'),[])
        self.create({**self.payload('2026-10-20'),'arrival_movement_ref':mid,'items':[{**self.item,'object_id':3}]})
        self.assertEqual(self.cells('2026-10-21')[0]['object_id'],3)

    def test_nonwork_fact_keeps_zero_share_and_independent_period_conflict(self):
        self.movement('DEPARTURE','2026-10-05T10:00')
        fid=self.fact('2026-10-06',2)
        before=self.snapshot()
        cells=self.cells('2026-10-06')
        self.assertEqual(len(cells),1)
        self.assertEqual(cells[0]['source_fact_id'],fid)
        self.assertEqual(cells[0]['share_cents'],0)
        self.assertEqual(cells[0]['status'],'CONFLICT')
        self.assertNotIn('FACT_ON_NONWORK_DAY',self.check('2026-10-06')['warnings'])
        self.assertIn('FACT_OUTSIDE_KNOWN_PERIOD',self.check('2026-10-06')['warnings'])
        self.assertEqual(before,self.snapshot())

    def test_ticket_annul_restore_matrix_and_original_ids(self):
        ticket=self.upload()
        confirmed=self.action(ticket,'confirm')[1]['item']
        self.conn.execute('UPDATE rail_tickets SET object_id=1 WHERE id=%s',(ticket['id'],))
        self.create({**self.payload(confirmed['arrival_datetime'][:10]),'arrival_movement_ref':confirmed['movement_id'],
                     'source_kind':'TICKET','source_ticket_id':ticket['id']})
        self.conn.execute('INSERT INTO luvr_months(year,month) VALUES(2026,9)')
        self.conn.execute('INSERT INTO luvr_month_employees(year,month,employee_id) VALUES(2026,9,2)')
        before=self.matrix('year=2026&month=9')
        self.assertEqual(self.action(ticket,'annul')[0],200)
        self.assertNotEqual(before,self.matrix('year=2026&month=9'))
        self.assertEqual(self.action(ticket,'restore')[0],200)
        self.assertEqual(before,self.matrix('year=2026&month=9'))

    def test_membership_filter_unformed_validation(self):
        self.conn.execute('INSERT INTO luvr_month_employees(year,month,employee_id) VALUES(2026,10,1)')
        self.assertEqual(len(self.matrix()['employees']),2)
        self.assertEqual([e['employee_id'] for e in self.matrix('year=2026&month=10&employee_id=2')['employees']],[2])
        self.assertEqual(self.matrix('year=2026&month=10&employee_id=999999')['employees'],[])
        empty=self.matrix('year=2026&month=11')
        self.assertFalse(empty['formed'])
        self.assertEqual(empty['employees'],[])
        self.assertEqual(http_request('GET','/api/production-matrix',query='year=2026&month=13')[0],422)

    def test_day_totals_are_backend_aggregates(self):
        self.conn.execute('INSERT INTO luvr_month_employees(year,month,employee_id) VALUES(2026,10,1)')
        result=self.matrix()
        self.assertEqual(len(result['day_totals']),31)
        for index,total in enumerate(result['day_totals']):
            for field in ('object_cents','cameral_cents','distributed_cents','available_cents'):
                self.assertEqual(total[field],sum(e['checks'][index][field] for e in result['employees']))

    def test_daily_report_flag_and_no_source_changes(self):
        before=self.snapshot()
        result=self.employee()
        status,calendar=http_request('GET','/api/employees/2/luvr/calendar',query='year=2026&month=10')
        self.assertEqual(status,200)
        self.assertEqual(result['luvr_days'],calendar['item']['days'])
        self.assertEqual(before,self.snapshot())
        self.conn.execute('UPDATE positions SET requires_daily_report=false WHERE id=9001')
        self.assertFalse(self.cells('2026-10-03')[0]['report_required'])
        self.assertEqual(self.cells('2026-10-03')[0]['share_cents'],100)

    def test_automatic_cameral_without_assignment_for_both_position_flags(self):
        self.movement('DEPARTURE','2026-10-12T10:00')
        self.movement('ARRIVAL','2026-10-20T07:00')
        self.assertEqual(self.cells('2026-10-21'),[])
        self.assertIn('ASSIGNMENT_UNKNOWN',self.check('2026-10-21')['warnings'])
        self.conn.execute('UPDATE positions SET requires_daily_report=false WHERE id=9001')
        before=self.snapshot()
        calendar=self.employee()['luvr_days']
        cell=self.cells('2026-10-21')[0]
        self.assertEqual((cell['kind'],cell['control_mode'],cell['share_cents']),('CAMERAL','CAMERAL',100))
        self.assertEqual(cell['basis_kind'],'POSITION_RULE')
        self.assertIsNone(cell['object_id'])
        self.assertIsNone(cell['category_id'])
        self.assertIsNone(cell['edit_target'])
        self.assertFalse(cell['report_required'])
        self.assertEqual(self.check('2026-10-21')['status'],'OK')
        self.assertEqual(self.check('2026-10-21')['object_cents'],0)
        self.assertEqual(self.check('2026-10-21')['cameral_cents'],100)
        self.assertEqual(self.cells('2026-10-13'),[])
        self.assertEqual(before,self.snapshot())
        self.assertEqual(calendar,self.employee()['luvr_days'])

    def test_automatic_cameral_fact_priority_and_nonwork_conflict(self):
        self.conn.execute('UPDATE positions SET requires_daily_report=false WHERE id=9001')
        self.fact('2026-10-05',1)
        self.fact('2026-10-05',2)
        self.fact('2026-10-07',1)
        self.conn.execute("INSERT INTO employee_luvr_day_overrides(employee_id,work_date,value) VALUES(2,'2026-10-07','OFF_SHIFT'),(2,'2026-10-03','HALF')")
        before=self.snapshot()
        # A valid explicit plan is not replaced by the automatic fallback.
        self.assertEqual(self.cells('2026-10-03')[0]['share_cents'],50)
        self.assertEqual(self.cells('2026-10-03')[0]['kind'],'OBJECT')
        facts=self.cells('2026-10-05')
        self.assertEqual([c['share_cents'] for c in facts],[50,50])
        self.assertTrue(all(c['source']=='FACT' and c['kind']=='OBJECT' for c in facts))
        self.assertEqual(self.check('2026-10-05')['cameral_cents'],0)
        self.assertTrue(all(c['kind']=='OBJECT' and c['source']=='PLAN' for c in self.cells('2026-10-06')))
        self.assertEqual(self.cells('2026-10-07')[0]['source'],'FACT')
        self.assertEqual(self.check('2026-10-07')['status'],'CONFLICT')
        self.assertEqual(before,self.snapshot())

    def test_automatic_office_cameral_needs_no_manual_event(self):
        self.conn.execute("UPDATE positions SET work_location='OFFICE',work_schedule='FIVE_TWO',requires_daily_report=false WHERE id=9001")
        result=self.employee()
        self.assertEqual(result['totals']['available_cents'],2200)
        self.assertEqual(result['totals']['cameral_cents'],2200)
        self.assertEqual(result['totals']['object_cents'],0)
        self.assertEqual(self.cells('2026-10-04'),[])
        self.assertTrue(all(c['status']=='OK' for c in result['checks']))

    def test_fact_plan_without_required_report_crosses_month_and_replaces_sets(self):
        self.conn.execute('UPDATE positions SET requires_daily_report=false WHERE id=9001')
        ids=[self.fact('2026-10-29',obj) for obj in (1,2,3)]
        self.conn.execute('INSERT INTO luvr_months(year,month) VALUES(2026,11)')
        self.conn.execute('INSERT INTO luvr_month_employees(year,month,employee_id) VALUES(2026,11,2)')
        def november(day):
            e=self.matrix('year=2026&month=11')['employees'][0]
            return [r['cells'][day] for r in e['rows'] if day in r['cells']]
        self.assertTrue(all(c['source']=='FACT' for c in self.cells('2026-10-29')))
        self.assertEqual([c['source_fact_id'] for c in self.cells('2026-10-30')],ids)
        self.assertEqual([c['share_cents'] for c in november('2026-11-01')],[33,33,34])
        self.assertTrue(all(c['source']=='PLAN' for c in november('2026-11-01')))
        self.fact('2026-11-03',2)
        self.assertEqual([c['object_id'] for c in november('2026-11-04')],[2])
        self.create({**self.payload('2026-11-05'),'items':[{**self.item,'object_id':3}]})
        self.assertEqual([c['object_id'] for c in november('2026-11-05')],[3])
        self.movement('DEPARTURE','2026-11-06T17:00')
        self.movement('ARRIVAL','2026-11-10T07:00')
        self.assertEqual(november('2026-11-07'),[])
        self.assertTrue(all(c['kind']=='CAMERAL' for c in november('2026-11-11')))
        self.conn.execute('UPDATE positions SET requires_daily_report=true WHERE id=9001')
        self.assertEqual(november('2026-11-11'),[])

    def test_grouped_row_preserves_day_sources_periods_and_independent_overrides(self):
        fid=self.fact('2026-10-05',1)
        self.write(self.request('2026-10-06','CONTROL_MODE','OPERATIONAL'))
        self.write(self.request('2026-10-07','CATEGORY',90))
        self.create(self.payload('2026-10-10'))
        before=self.snapshot()
        rows=self.employee()['rows']
        self.assertEqual(len(rows),1)
        row=rows[0]
        self.assertEqual(row['source'],'MIXED')
        self.assertEqual(row['cells']['2026-10-05']['source'],'FACT')
        self.assertEqual(row['cells']['2026-10-06']['source'],'PLAN')
        self.assertEqual(row['cells']['2026-10-06']['source_fact_id'],fid)
        self.assertEqual(row['cells']['2026-10-06']['category_id'],1)
        self.assertEqual(row['cells']['2026-10-07']['category_id'],90)
        self.assertEqual(row['cells']['2026-10-07']['control_mode'],'OPERATIONAL')
        self.assertEqual(row['cells']['2026-10-10']['control_mode'],'INSPECTION')
        self.assertEqual(row['cells']['2026-10-10']['category_id'],1)
        self.assertNotEqual(row['cells']['2026-10-09']['edit_target'],row['cells']['2026-10-10']['edit_target'])
        self.assertEqual(row['total_cents'],sum(c['share_cents'] for c in row['cells'].values()))
        self.assertEqual(before,self.snapshot())

    def test_same_day_equal_object_identity_keeps_both_fact_targets(self):
        first=self.fact('2026-10-05',1)
        second=self.conn.execute("""INSERT INTO daily_control_results
            (report_date,employee_id,object_id,po_id,category_id,source_file,source_sha256)
            VALUES('2026-10-05',2,1,1,90,'another.docx',%s) RETURNING id""",('b'*64,)).fetchone()[0]
        cells=self.cells('2026-10-05')
        self.assertEqual({c['source_fact_id'] for c in cells},{first,second})
        self.assertEqual([c['share_cents'] for c in cells],[50,50])
        self.assertEqual({c['edit_target']['fact_id'] for c in cells},{first,second})
        self.assertEqual(len(self.employee()['rows']),2)
        self.assertEqual(sum(c['share_cents'] for c in self.cells('2026-10-06')),100)

    def test_ticket_restore_reactivates_fact_based_plan_without_daily_report(self):
        self.conn.execute('UPDATE positions SET requires_daily_report=false WHERE id=9001')
        ticket=self.upload()
        self.assertEqual(self.action(ticket,'confirm')[0],200)
        fid=self.fact('2026-09-12',1)
        self.conn.execute('INSERT INTO luvr_months(year,month) VALUES(2026,9)')
        self.conn.execute('INSERT INTO luvr_month_employees(year,month,employee_id) VALUES(2026,9,2)')
        before=self.matrix('year=2026&month=9')
        cell=next(r['cells']['2026-09-13'] for r in before['employees'][0]['rows'] if '2026-09-13' in r['cells'])
        self.assertEqual((cell['source'],cell['source_fact_id'],cell['kind']),('PLAN',fid,'OBJECT'))
        facts=self.conn.execute('SELECT to_jsonb(r) FROM daily_control_results r ORDER BY id').fetchall()
        self.assertEqual(self.action(ticket,'annul')[0],200)
        self.assertNotEqual(before,self.matrix('year=2026&month=9'))
        self.assertEqual(self.action(ticket,'restore')[0],200)
        self.assertEqual(before,self.matrix('year=2026&month=9'))
        self.assertEqual(facts,self.conn.execute('SELECT to_jsonb(r) FROM daily_control_results r ORDER BY id').fetchall())

    def test_sickness_and_dismissal_use_luvr_final(self):
        self.conn.execute("INSERT INTO employee_sick_periods(employee_id,date_from,date_to) VALUES(2,'2026-10-05','2026-10-07')")
        self.conn.execute("UPDATE employees SET dismissal_date='2026-10-20' WHERE id=2")
        self.assertEqual(self.check('2026-10-06')['available_cents'],0)
        self.assertEqual(self.cells('2026-10-06'),[])
        self.assertEqual(self.check('2026-10-08')['available_cents'],100)
        self.assertEqual(self.check('2026-10-20')['available_cents'],0)

    def test_fact_edit_tokens_and_date_only_effect(self):
        self.fact('2026-10-05')
        cell=self.cells('2026-10-05')[0]
        target=cell['edit_target']
        self.assertEqual(target['scope'],'FACT')
        fields=target.pop('fields')
        status,body=http_request('PATCH','/api/employees/2/production-matrix-overrides',
            {**target,'field_name':'CONTROL_MODE','control_mode':'OPERATIONAL','version':fields['CONTROL_MODE']['version']})
        self.assertEqual(status,200,body)
        self.assertEqual(self.cells('2026-10-05')[0]['control_mode'],'OPERATIONAL')
        self.assertIsNone(self.cells('2026-10-06')[0]['control_mode'])

    def test_office_cameral_weekends_and_total_conservation(self):
        self.conn.execute("UPDATE employee_movements SET event_datetime='2026-09-01 07:00' WHERE id=%s",(self.anchor,))
        self.conn.execute("UPDATE positions SET work_location='OFFICE',work_schedule='FIVE_TWO' WHERE id=9001")
        self.create(dict(effective_from='2026-10-01',period_kind='EXPLICIT',period_start='2026-10-01',
                         period_end='2026-10-31',assignment_state='NO_OBJECT',items=[]))
        employee=self.employee()
        self.assertEqual(employee['totals']['available_cents'],2200)
        self.assertEqual(employee['totals']['cameral_cents'],2200)
        self.assertEqual(employee['totals']['object_cents'],0)
        self.assertEqual(self.cells('2026-10-04'),[])
        self.assertTrue(all(c['status']=='OK' for c in employee['checks']))
        for check in employee['checks']:
            self.assertEqual(check['object_cents']+check['cameral_cents'],check['available_cents'])


    def test_po_overlay_is_dated_and_preserves_original_assignments_and_shares(self):
        before=self.snapshot()
        initial=self.employee()
        c=next(r['cells']['2026-10-03'] for r in initial['rows'] if '2026-10-03' in r['cells'])
        target=c['edit_target'];fields=target['fields']
        payload={k:v for k,v in target.items() if k!='fields'}
        payload.update(field_name='PO',po_id=2,version=fields['PO']['version'])
        self.write(payload)
        employee=self.employee()
        prior=next(r['cells']['2026-10-02'] for r in employee['rows'] if '2026-10-02' in r['cells'])
        current=next(r['cells']['2026-10-03'] for r in employee['rows'] if '2026-10-03' in r['cells'])
        self.assertEqual(prior['po_id'],1);self.assertEqual(current['po_id'],2)
        self.assertEqual(current['po_name'],'ПО Б')
        self.assertEqual(initial['totals'],employee['totals'])
        self.assertEqual(before,self.snapshot())
        self.assertEqual(self.conn.execute('SELECT po_id FROM production_assignment_items WHERE id=%s',(self.saved['items'][0]['id'],)).fetchone()[0],1)

    def test_fact_po_overlay_does_not_rewrite_daily_fact_or_other_dates(self):
        fid=self.fact('2026-10-04')
        self.fact('2026-10-05')
        before=self.snapshot()
        e=self.employee();c=next(r['cells']['2026-10-04'] for r in e['rows'] if '2026-10-04' in r['cells'])
        payload={k:v for k,v in c['edit_target'].items() if k!='fields'}
        payload.update(field_name='PO',po_id=2,version=0)
        self.write(payload)
        changed=self.employee()
        day4=next(r['cells']['2026-10-04'] for r in changed['rows'] if '2026-10-04' in r['cells'])
        day5=next(r['cells']['2026-10-05'] for r in changed['rows'] if '2026-10-05' in r['cells'])
        self.assertEqual(day4['po_id'],2);self.assertEqual(day5['po_id'],1)
        self.assertEqual(self.conn.execute('SELECT po_id FROM daily_control_results WHERE id=%s',(fid,)).fetchone()[0],1)
        self.assertEqual(before,self.snapshot())
        self.assertEqual(e['totals'],changed['totals'])

    def test_invalid_po_and_stale_version_do_not_change_matrix(self):
        c=next(r['cells']['2026-10-03'] for r in self.employee()['rows'] if '2026-10-03' in r['cells'])
        payload={k:v for k,v in c['edit_target'].items() if k!='fields'}
        payload.update(field_name='PO',po_id=999999,version=0)
        before=self.matrix()
        self.assertEqual(http_request('PATCH','/api/employees/2/production-matrix-overrides',payload)[0],400)
        self.assertEqual(before,self.matrix())
        payload['po_id']=2;self.write(payload)
        self.assertEqual(http_request('PATCH','/api/employees/2/production-matrix-overrides',payload)[0],409)
