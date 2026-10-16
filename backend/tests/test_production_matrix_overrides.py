import os
import unittest
from contextlib import contextmanager
from unittest.mock import patch
import psycopg
import test_production_assignments
from test_daily_control import http_request
from app.database.migrate_production_matrix_overrides import apply_migration


@unittest.skipUnless(os.getenv('DAILY_CONTROL_TEST_DB') == '1','Requires isolated PostgreSQL')
class MatrixOverrideTests(unittest.TestCase):
    movement = test_production_assignments.ProductionAssignmentTests.movement
    payload = test_production_assignments.ProductionAssignmentTests.payload
    create = test_production_assignments.ProductionAssignmentTests.create
    history = test_production_assignments.ProductionAssignmentTests.history
    fact = test_production_assignments.ProductionAssignmentTests.fact
    snapshot = test_production_assignments.ProductionAssignmentTests.snapshot
    upload = test_production_assignments.ProductionAssignmentTests.upload
    action = test_production_assignments.ProductionAssignmentTests.action

    def setUp(self):
        test_production_assignments.ProductionAssignmentTests.setUp(self)
        apply_migration(self.conn)
        @contextmanager
        def connection():
            with self.conn.transaction():yield self.conn
        mock = patch('app.repositories.production_matrix_overrides.get_connection',connection)
        mock.start();self.addCleanup(mock.stop)
        self.conn.execute("INSERT INTO object_categories(id,name) VALUES(90,'Category 90'),(91,'Category 91')")
        self.saved = self.create()

    def request(self,day='2026-10-03',field='CONTROL_MODE',value='OPERATIONAL',**extra):
        period = next(p for p in self.history()['periods'] if p['effective_from']<=day and (not p['effective_to'] or day<=p['effective_to']))
        data = dict(effective_from=day,scope='PLAN',field_name=field,
                    period_key=period['period_key'],basis_revision=period['basis_revision'],version=0)
        if period['basis_kind']=='FACTS':data['fact_id']=period['items'][0]['id']
        else:data['assignment_item_id']=self.saved['items'][0]['id']
        data['category_id' if field=='CATEGORY' else 'control_mode']=value
        data.update(extra)
        if data['scope']=='FACT':
            data['basis_revision']=next(r['basis_revision'] for r in self.read()['intervals']
                if r.get('scope')=='FACT' and r.get('fact_id')==data['fact_id'])
        return data

    def write(self,payload):
        status,body=http_request('PATCH','/api/employees/2/production-matrix-overrides',payload)
        self.assertEqual(status,200,body)
        return body['item']

    def read(self,start='2026-10-01',end='2026-10-31'):
        status,body=http_request('GET','/api/employees/2/production-matrix-overrides',query=f'date_from={start}&date_to={end}')
        self.assertEqual(status,200,body)
        return body['item']

    def at(self,day):
        return [r for r in self.read()['intervals'] if r['effective_from']<=day<=r['effective_to']][0]

    def test_independent_fields_and_sequential_changes(self):
        self.write(self.request())
        self.write(self.request('2026-10-05','CATEGORY',90))
        self.write(self.request('2026-10-07','CONTROL_MODE','INSPECTION'))
        self.write(self.request('2026-10-09','CATEGORY',91))
        for day,category,mode in [('02',1,'INSPECTION'),('03',1,'OPERATIONAL'),('05',90,'OPERATIONAL'),
                                 ('07',90,'INSPECTION'),('09',91,'INSPECTION')]:
            row=self.at('2026-10-'+day)
            self.assertEqual((row['category_id'],row['control_mode']),(category,mode))
        self.assertEqual(self.conn.execute('SELECT count(*) FROM production_matrix_overrides').fetchone()[0],4)

    def test_prior_month_change_is_inherited(self):
        self.write(self.request())
        rows=self.read('2026-11-01','2026-11-30')['intervals']
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['control_mode'],'OPERATIONAL')

    def test_new_assignment_same_object_does_not_inherit(self):
        self.write(self.request())
        new=self.create(self.payload('2026-10-10'))
        self.assertNotEqual(new['items'][0]['id'],self.saved['items'][0]['id'])
        self.assertEqual(self.at('2026-10-10')['control_mode'],'INSPECTION')
        stale=self.request('2026-10-11')
        self.assertEqual(http_request('PATCH','/api/employees/2/production-matrix-overrides',stale)[0],409)

    def test_new_fact_ends_plan_and_fact_override_is_day_only(self):
        self.write(self.request())
        fid=self.fact('2026-10-10')
        before=self.snapshot()
        self.write(self.request('2026-10-10','CATEGORY',90,scope='FACT'))
        self.write(self.request('2026-10-10',scope='FACT'))
        self.assertEqual(self.at('2026-10-10')['category_id'],90)
        self.assertEqual(self.at('2026-10-10')['control_mode'],'OPERATIONAL')
        self.assertEqual(self.at('2026-10-11')['category_id'],1)
        self.assertIsNone(self.at('2026-10-11')['control_mode'])
        self.assertEqual(before,self.snapshot())
        self.assertEqual(http_request('PATCH','/api/employees/2/production-matrix-overrides',self.request('2026-10-11',scope='FACT'))[0],409)
        self.assertEqual(self.at('2026-10-10')['fact_id'],fid)

    def test_plan_from_fact_stops_at_next_fact(self):
        self.fact('2026-10-05')
        self.write(self.request('2026-10-06'))
        self.fact('2026-10-10',2)
        self.assertEqual(self.at('2026-10-09')['control_mode'],'OPERATIONAL')
        self.assertIsNone(self.at('2026-10-10')['control_mode'])
        self.assertIsNone(self.at('2026-10-11')['control_mode'])

    def test_fields_of_two_fact_objects_do_not_mix(self):
        first=self.fact('2026-10-05',1)
        second=self.fact('2026-10-05',2)
        self.write(self.request('2026-10-06',fact_id=first))
        self.write(self.request('2026-10-06','CATEGORY',90,fact_id=second))
        rows={r['fact_id']:r for r in self.read()['intervals'] if r['effective_from']<='2026-10-07'<=r['effective_to']}
        self.assertEqual((rows[first]['control_mode'],rows[first]['category_id']),('OPERATIONAL',1))
        self.assertEqual((rows[second]['control_mode'],rows[second]['category_id']),(None,90))

    def test_departure_new_arrival_and_cameral_stop_inheritance(self):
        self.write(self.request())
        self.create({**self.payload('2026-10-07'),'assignment_state':'NO_OBJECT','items':[]})
        self.assertEqual(self.at('2026-10-07')['control_mode'],'CAMERAL')
        self.assertIsNone(self.at('2026-10-07')['category_id'])
        self.assertFalse(self.at('2026-10-07')['editable'])
        self.assertEqual(http_request('PATCH','/api/employees/2/production-matrix-overrides',self.request('2026-10-08'))[0],409)
        self.movement('DEPARTURE','2026-10-12T17:00')
        anchor=self.movement('ARRIVAL','2026-10-20T07:00')
        self.create({**self.payload('2026-10-20'),'arrival_movement_ref':anchor})
        self.assertEqual(self.at('2026-10-20')['control_mode'],'INSPECTION')
        self.assertFalse(any(r['effective_from']<='2026-10-15'<=r['effective_to'] for r in self.read()['intervals']))

    def test_delete_returns_previous_then_initial_and_guards_versions(self):
        first=self.write(self.request())
        later=self.write(self.request('2026-10-07','CONTROL_MODE','INSPECTION'))
        route=f"/api/production-matrix-overrides/{later['id']}"
        self.assertEqual(http_request('DELETE',route,query='version=2')[0],409)
        self.assertEqual(http_request('DELETE',route,query='version=1')[0],200)
        self.assertEqual(self.at('2026-10-08')['control_mode'],'OPERATIONAL')
        self.assertEqual(http_request('PATCH','/api/employees/2/production-matrix-overrides',self.request('2026-10-07','CONTROL_MODE','INSPECTION'))[0],409)
        self.assertEqual(http_request('DELETE',f"/api/production-matrix-overrides/{first['id']}",query='version=1')[0],200)
        self.assertEqual(self.at('2026-10-08')['control_mode'],'INSPECTION')

    def test_upsert_and_stale_version(self):
        original=self.write(self.request())
        edited=self.write(self.request(value='INSPECTION',version=1))
        self.assertEqual(edited['id'],original['id'])
        self.assertEqual(edited['version'],2)
        self.assertEqual(http_request('PATCH','/api/employees/2/production-matrix-overrides',self.request(version=1))[0],409)
        self.assertEqual(http_request('PATCH','/api/employees/2/production-matrix-overrides',self.request('2026-10-08',version=2))[0],409)

    def test_invalid_fields_sources_and_values(self):
        for extra in ({'object_id':2},{'control_mode':'CAMERAL'},{'category_id':90},{'employee_id':1},
                      {'po_id':2},{'share':0.5},{'version':-1},{'version':True}):
            self.assertEqual(http_request('PATCH','/api/employees/2/production-matrix-overrides',self.request(**extra))[0],422)
        for extra in ({'assignment_item_id':99999},{'period_key':'wrong'},{'basis_revision':'wrong'}):
            self.assertEqual(http_request('PATCH','/api/employees/2/production-matrix-overrides',self.request(**extra))[0],409)
        self.assertEqual(http_request('PATCH','/api/employees/1/production-matrix-overrides',self.request())[0],409)
        self.assertEqual(http_request('PATCH','/api/employees/2/production-matrix-overrides',self.request(field='CATEGORY',value=99999))[0],400)

    def test_source_correction_preserves_inactive_override_history(self):
        override=self.write(self.request())
        status,body=http_request('PATCH',f"/api/production-assignments/{self.saved['id']}",
            {**self.payload(),'version':1,'items':[{**self.item,'object_id':2}]})
        self.assertEqual(status,200,body)
        history=self.read()['history'][0]
        self.assertFalse(history['applicable'])
        self.assertIsNone(history['assignment_item_id'])
        self.assertEqual(history['assignment_item_ref'],override['assignment_item_ref'])
        self.assertEqual(self.at('2026-10-04')['control_mode'],'INSPECTION')

    def test_migration_repeat_and_db_checks(self):
        saved=self.write(self.request())
        before=self.snapshot()
        apply_migration(self.conn)
        self.assertEqual(before,self.snapshot())
        self.assertEqual(self.read()['history'][0]['id'],saved['id'])
        for statement in ("UPDATE production_matrix_overrides SET control_mode='CAMERAL'",
                          'UPDATE production_matrix_overrides SET category_id=90',
                          'UPDATE production_matrix_overrides SET fact_id=999999'):
            with self.assertRaises(psycopg.IntegrityError), self.conn.transaction():
                self.conn.execute(statement)

    def test_sibling_fact_keeps_fact_override_but_rebases_plan(self):
        fid=self.fact('2026-10-05')
        self.write(self.request('2026-10-05','CATEGORY',90,scope='FACT'))
        self.write(self.request('2026-10-06'))
        self.fact('2026-10-05',2)
        rows=self.read()
        fact=next(r for r in rows['intervals'] if r.get('scope')=='FACT' and r['fact_id']==fid)
        self.assertEqual(fact['category_id'],90)
        self.assertFalse(next(r for r in rows['history'] if r['scope']=='PLAN')['applicable'])

    def test_ticket_annul_restore_reactivates_same_override(self):
        ticket=self.upload()
        confirmed=self.action(ticket,'confirm')[1]['item']
        self.conn.execute('UPDATE rail_tickets SET object_id=1 WHERE id=%s',(ticket['id'],))
        day=confirmed['arrival_datetime'][:10]
        saved=self.create({**self.payload(day),'arrival_movement_ref':confirmed['movement_id'],
                           'source_kind':'TICKET','source_ticket_id':ticket['id']})
        period=self.history('2026-09-01','2026-09-30')['periods'][0]
        self.write(dict(effective_from=day,scope='PLAN',field_name='CONTROL_MODE',control_mode='OPERATIONAL',
            assignment_item_id=saved['items'][0]['id'],period_key=period['period_key'],basis_revision=period['basis_revision'],version=0))
        before=self.read('2026-09-01','2026-09-30')
        self.assertEqual(self.action(ticket,'annul')[0],200)
        self.assertFalse(self.read('2026-09-01','2026-09-30')['history'][0]['applicable'])
        self.assertEqual(self.action(ticket,'restore')[0],200)
        self.assertEqual(before,self.read('2026-09-01','2026-09-30'))

    def test_concurrent_creation_has_one_winner(self):
        from concurrent.futures import ThreadPoolExecutor
        from psycopg import sql
        from app.database.db import get_connection
        payload=self.request()
        schema=self.conn.execute('SELECT current_schema()').fetchone()[0]
        self.assertTrue(schema.startswith('test_'))
        def cleanup():
            with get_connection() as conn:
                conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
        self.addCleanup(cleanup)
        self.conn.commit()
        @contextmanager
        def connection():
            with get_connection() as conn:
                conn.execute(sql.SQL('SET LOCAL search_path TO {}').format(sql.Identifier(schema)))
                conn.execute("SET LOCAL lock_timeout='5s'")
                yield conn
        def write():
            return http_request('PATCH','/api/employees/2/production-matrix-overrides',payload)[0]
        with patch('app.repositories.production_matrix_overrides.get_connection',connection):
            with ThreadPoolExecutor(max_workers=2) as pool:
                self.assertEqual(sorted(pool.map(lambda _:write(),range(2))),[200,409])
        with connection() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM production_matrix_overrides').fetchone()[0],1)
