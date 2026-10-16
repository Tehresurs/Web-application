import os
import unittest
from unittest.mock import patch
import test_production_matrix as fixtures
from rail_fixture import coupon_pdf
from test_daily_control import http_request
from app.repositories.directory_errors import DirectoryConflict


@unittest.skipUnless(os.getenv('DAILY_CONTROL_TEST_DB')=='1','Requires isolated PostgreSQL')
class RailProductionAssignmentTests(unittest.TestCase):
    for name in ('movement','payload','create','history','fact','snapshot','upload','action','request','write','read','matrix'):
        locals()[name]=getattr(fixtures.ProductionMatrixTests,name)

    def setUp(self):
        fixtures.ProductionMatrixTests.setUp(self)
        self.conn.execute('INSERT INTO luvr_months(year,month) VALUES(2026,9)')
        self.conn.execute('INSERT INTO luvr_month_employees(year,month,employee_id) VALUES(2026,9,2)')

    def object(self,ticket,obj):
        return http_request('PATCH',f"/api/rail-tickets/{ticket['id']}/object",{'object_id':obj})

    def linked(self,ticket):
        return http_request('GET','/api/employees/2/production-assignments',query='date_from=2026-09-01&date_to=2026-09-30')[1]['item']['history']

    def cells(self,day='2026-09-12',employee=2):
        matrix=self.matrix(f'year=2026&month=9&employee_id={employee}')
        return [r['cells'][day] for r in matrix['employees'][0]['rows'] if day in r['cells']]

    def test_confirm_object_creates_plan_and_fact_replaces_it(self):
        ticket=self.upload()
        self.assertEqual(self.object(ticket,1)[0],200)
        self.assertEqual(self.action(ticket,'confirm')[0],200)
        rows=[r for r in self.linked(ticket) if r['source_ticket_id']==ticket['id']]
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['items'][0]['object_id'],1)
        self.assertIsNone(rows[0]['items'][0]['po_id'])
        self.assertIsNone(rows[0]['items'][0]['subobject_id'])
        self.assertEqual(self.cells()[0]['source'],'PLAN')
        self.assertEqual(self.cells()[0]['share_cents'],100)
        self.assertEqual(self.cells('2026-09-10'),[])
        self.fact('2026-09-14',2)
        self.assertEqual(self.cells('2026-09-14')[0]['source'],'FACT')
        self.assertEqual(self.cells('2026-09-15')[0]['object_id'],2)

    def test_archived_object_blocks_new_ticket_plan_but_keeps_existing(self):
        from app.database.migrate_object_archive import apply_migration
        apply_migration(self.conn)
        ticket=self.upload()
        self.object(ticket,1)
        count_before=self.conn.execute('SELECT count(*) FROM production_assignment_changes').fetchone()[0]
        self.conn.execute('UPDATE construction_objects SET is_archived=true WHERE id=1')
        self.assertEqual(self.action(ticket,'confirm')[0],409)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM production_assignment_changes').fetchone()[0],count_before)
        self.assertEqual(self.object(ticket,1)[0],200)  # Unchanged stored reference.
        self.conn.execute('UPDATE construction_objects SET is_archived=false WHERE id=1')
        self.assertEqual(self.action(ticket,'confirm')[0],200)
        before=self.matrix('year=2026&month=9')
        self.conn.execute('UPDATE construction_objects SET is_archived=true WHERE id=1')
        self.assertEqual(self.matrix('year=2026&month=9'),before)
        self.assertEqual(self.action(ticket,'annul')[0],200)
        self.assertEqual(self.action(ticket,'restore')[0],200)
        self.assertEqual(self.matrix('year=2026&month=9'),before)

    def test_ticket_cannot_select_archived_object(self):
        from app.database.migrate_object_archive import apply_migration
        apply_migration(self.conn)
        ticket=self.upload()
        self.conn.execute('UPDATE construction_objects SET is_archived=true WHERE id=1')
        self.assertEqual(self.object(ticket,1)[0],409)
        self.assertIsNone(self.conn.execute('SELECT object_id FROM rail_tickets WHERE id=%s',(ticket['id'],)).fetchone()[0])

    def test_new_employee_can_confirm_existing_ticket_with_object(self):
        ticket=self.upload(coupon_pdf(full_name='НОВЫЙ ИВАН ИВАНОВИЧ'))
        self.assertEqual(self.object(ticket,1)[0],200)
        status,employee=http_request('POST','/api/employees',{'full_name':'Новый Иван Иванович','position_id':9001})
        self.assertEqual(status,200,employee)
        self.conn.execute('INSERT INTO luvr_month_employees(year,month,employee_id) VALUES(2026,9,%s)',(employee['id'],))
        self.assertEqual(self.action(ticket,'confirm')[0],200)
        self.assertEqual(self.cells(employee=employee['id'])[0]['object_id'],1)

    def test_select_object_after_confirm_and_repeat_are_idempotent(self):
        ticket=self.upload()
        self.assertEqual(self.action(ticket,'confirm')[0],200)
        self.assertEqual(self.cells(),[])
        self.assertEqual(self.object(ticket,1)[0],200)
        before=self.matrix('year=2026&month=9')
        history=self.linked(ticket)
        for _ in range(2):
            self.assertEqual(self.object(ticket,1)[0],200)
            self.assertEqual(self.action(ticket,'confirm')[0],200)
        self.assertEqual(history,self.linked(ticket))
        self.assertEqual(before,self.matrix('year=2026&month=9'))

    def test_multiple_objects_survive_replacement_with_history(self):
        ticket=self.upload();self.object(ticket,1);confirmed=self.action(ticket,'confirm')[1]['item']
        initial=next(c for c in self.linked(ticket) if c['source_ticket_id']==ticket['id'])
        body={**self.payload('2026-09-11'),'arrival_movement_ref':confirmed['movement_id'],'source_kind':'TICKET',
              'source_ticket_id':ticket['id'],'items':[self.item,{**self.item,'object_id':2}],'version':initial['version']}
        self.assertEqual(http_request('PATCH',f"/api/production-assignments/{initial['id']}",body)[0],200)
        self.assertEqual(self.object(ticket,3)[0],200)
        current=next(c for c in self.linked(ticket) if c['id']==initial['id'])
        self.assertEqual({i['object_id'] for i in current['items']},{2,3})
        self.assertEqual({i['object_id'] for i in current['correction_history'][-1]['items']},{1,2})
        self.assertEqual({c['object_id'] for c in self.cells()},{2,3})
        self.assertEqual(sum(c['share_cents'] for c in self.cells()),100)

    def test_annul_restore_preserves_history_and_plan(self):
        ticket=self.upload();self.object(ticket,1);self.action(ticket,'confirm')
        before=self.matrix('year=2026&month=9')
        stored=self.conn.execute('SELECT to_jsonb(c) FROM production_assignment_changes c ORDER BY id').fetchall()
        self.assertEqual(self.action(ticket,'annul')[0],200)
        self.assertEqual(self.cells(),[])
        self.assertEqual(stored,self.conn.execute('SELECT to_jsonb(c) FROM production_assignment_changes c ORDER BY id').fetchall())
        self.assertEqual(self.action(ticket,'restore')[0],200)
        self.assertEqual(before,self.matrix('year=2026&month=9'))

    def test_departure_new_arrival_without_object_does_not_reuse_old_plan(self):
        ticket=self.upload();self.object(ticket,1);self.action(ticket,'confirm')
        self.movement('DEPARTURE','2026-09-15T17:00')
        second=self.upload(coupon_pdf(departure_datetime='19.09.2026 23:04',arrival_datetime='20.09.2026 07:29'))
        self.assertEqual(self.action(second,'confirm')[0],200)
        self.assertEqual(self.cells('2026-09-16'),[])
        self.assertEqual(self.cells('2026-09-21'),[])
        self.object(second,2)
        self.assertEqual(self.cells('2026-09-21')[0]['object_id'],2)

    def test_assignment_failure_rolls_back_confirmation(self):
        ticket=self.upload();self.object(ticket,1)
        before=self.conn.execute('SELECT count(*) FROM employee_movements').fetchone()[0]
        with patch('app.repositories.rail_production_assignments.save',side_effect=DirectoryConflict('test failure')):
            self.assertEqual(self.action(ticket,'confirm')[0],409)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM employee_movements').fetchone()[0],before)
        self.assertEqual(http_request('GET',f"/api/rail-tickets/{ticket['id']}")[1]['item']['status'],'PARSED')

    def test_clear_and_reselect_does_not_bring_back_removed_object(self):
        ticket=self.upload();self.object(ticket,1);self.action(ticket,'confirm')
        self.assertEqual(self.object(ticket,None)[0],200)
        self.assertEqual(self.cells(),[])
        self.assertEqual(self.object(ticket,2)[0],200)
        self.assertEqual([c['object_id'] for c in self.cells()],[2])

    def test_independent_multi_object_assignment_is_not_silently_replaced(self):
        ticket=self.upload();confirmed=self.action(ticket,'confirm')[1]['item']
        self.create({**self.payload('2026-09-11'),'arrival_movement_ref':confirmed['movement_id'],
                     'items':[self.item,{**self.item,'object_id':2}]})
        self.assertEqual(self.object(ticket,1)[0],200)
        before=self.linked(ticket)
        self.assertEqual(self.object(ticket,3)[0],409)
        self.assertEqual(before,self.linked(ticket))
        self.assertEqual({c['object_id'] for c in self.cells()},{1,2})
        self.assertEqual(http_request('GET',f"/api/rail-tickets/{ticket['id']}")[1]['item']['object_id'],1)
