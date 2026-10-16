"""Round trip in the designated test schema; all rows and sequences remain unchanged."""
import unittest
from contextlib import contextmanager
from datetime import date
from unittest.mock import patch
from psycopg import sql
from app.database.db import get_connection
from app.api.construction_identity import require_test_database
from app.repositories.construction_identity import resolve
from app.repositories.daily_control import get_journal
from app.services.production_matrix import calculate_month
from app.services.deployment import build_report
from test_daily_control import http_request


class IdentityRoundTripTest(unittest.TestCase):
    def test_complete_round_trip_preserves_sources_totals_and_rollback(self):
        conn=get_connection()
        self.addCleanup(conn.close)
        require_test_database(conn)
        conn.execute('SELECT pg_advisory_xact_lock(20261013,24)')
        tables=[r[0] for r in conn.execute('SELECT tablename FROM pg_tables WHERE schemaname=current_schema() ORDER BY tablename')]
        def snapshot(names):
            return {t:conn.execute(sql.SQL('SELECT to_jsonb(r) FROM {} r ORDER BY to_jsonb(r)::text').format(sql.Identifier(t))).fetchall() for t in names}
        def sequences():
            return conn.execute('SELECT sequencename,last_value FROM pg_sequences WHERE schemaname=current_schema() ORDER BY sequencename').fetchall()
        original=snapshot(tables);original_sequences=sequences()
        @contextmanager
        def connection():
            with conn.transaction():yield conn
        mocks=[]
        try:
            for module in ('app.api.construction_identity','app.repositories.objects','app.repositories.subobjects',
                           'app.repositories.daily_control','app.repositories.production_matrix'):
                mock=patch(module+'.get_connection',connection);mock.start();mocks.append(mock)
            def convert(entity, parent):
                require_test_database(conn)
                version=resolve(conn,entity_id=entity)['version']
                status,body=http_request('PATCH',f'/api/construction-entities/{entity}/hierarchy',
                    dict(parent_entity_id=parent,version=version,confirmed=True))
                self.assertEqual(status,200,body)
                return body['item']

            candidate=conn.execute('''SELECT e.entity_id FROM construction_entity_current e
                WHERE legacy_object_id IS NOT NULL AND NOT is_archived AND NOT EXISTS
                (SELECT 1 FROM construction_entity_hierarchy h WHERE h.parent_entity_id=e.entity_id)
                ORDER BY entity_id LIMIT 1''').fetchone()
            self.assertIsNotNone(candidate,'No leaf object available for an isolated round trip')
            entity=candidate[0]
            initial=resolve(conn,entity_id=entity)
            if initial['parent_entity_id'] is not None:convert(entity,None)
            parent=conn.execute('''SELECT entity_id FROM construction_entity_current WHERE parent_entity_id IS NULL
                AND NOT is_archived AND entity_id<>%s ORDER BY entity_id LIMIT 1''',(entity,)).fetchone()[0]
            parent_entity=resolve(conn,entity_id=parent)
            oid=initial['legacy_object_id']
            # Explicit fixture IDs avoid even nontransactional nextval() changes.
            seed_tables=('positions','employees','po_types','object_categories','employee_assignments',
                         'daily_control_results','employee_movements','luvr_month_employees')
            seed=max(conn.execute(sql.SQL('SELECT COALESCE(max(id),0) FROM {}').format(sql.Identifier(t))).fetchone()[0]
                     for t in seed_tables)+1000
            require_test_database(conn)
            conn.execute("INSERT INTO positions(id,name,work_location,work_schedule,requires_daily_report) VALUES(%s,'Roundtrip tester','OBJECT','SHIFT',true)",(seed,))
            conn.execute("INSERT INTO employees(id,full_name,position_id) VALUES(%s,'Roundtrip tester',%s)",(seed,seed))
            conn.execute("INSERT INTO po_types(id,name) VALUES(%s,'Roundtrip PO 1'),(%s,'Roundtrip PO 2')",(seed,seed+1))
            conn.execute("INSERT INTO object_categories(id,name) VALUES(%s,'Roundtrip category')",(seed,))
            conn.execute('INSERT INTO employee_assignments(id,employee_id,object_id,po_id,category_id) VALUES(%s,%s,%s,%s,%s)',(seed,seed,oid,seed,seed))
            conn.execute('INSERT INTO employee_assignments(id,employee_id,entity_id,po_id,category_id) VALUES(%s,%s,%s,%s,%s)',(seed+1,seed,entity,seed+1,seed))
            conn.execute("INSERT INTO employee_movements(id,employee_id,movement_type,transport_type,event_datetime) VALUES(%s,%s,'ARRIVAL','SELF','2026-10-01 07:00')",(seed,seed))
            conn.execute('INSERT INTO luvr_months(year,month) VALUES(2026,10) ON CONFLICT DO NOTHING')
            conn.execute('INSERT INTO luvr_month_employees(id,year,month,employee_id) VALUES(%s,2026,10,%s)',(seed,seed))
            for offset,day,old_id,new_id in ((0,4,oid,None),(1,5,None,entity),(2,5,None,parent)):
                conn.execute('''INSERT INTO daily_control_results(id,report_date,employee_id,object_id,entity_id,
                    po_id,category_id,source_file,source_sha256) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                    (seed+offset,date(2026,10,day),seed,old_id,new_id,seed,seed,f'roundtrip-{offset}.docx',str(offset+1)*64))
            source_tables=[t for t in tables if t!='construction_entity_hierarchy']
            baseline=snapshot(source_tables)
            stable_keys=('entity_id','legacy_object_id','legacy_subobject_id','name','is_archived','archived_at','activity_status')
            stable={k:initial[k] for k in stable_keys}
            totals=None;report_totals={};shares={}
            for stage,target in (('before',None),('child',parent),('standalone',None)):
                with self.subTest(stage=stage):
                    if stage!='before':convert(entity,target)
                    actual=resolve(conn,entity_id=entity)
                    self.assertEqual({k:actual[k] for k in stable_keys},stable)
                    self.assertEqual(actual['parent_entity_id'],target)
                    self.assertEqual(snapshot(source_tables),baseline)
                    roots=http_request('GET','/api/objects')[1]['items']
                    children=http_request('GET','/api/subobjects',query='include_inactive=true')[1]['items']
                    self.assertEqual(sum(r['entity_id']==entity for r in roots),int(target is None))
                    self.assertEqual(sum(r['entity_id']==entity for r in children),int(target is not None))
                    matrix=calculate_month(2026,10,seed)
                    self.assertTrue(matrix['formed']);self.assertEqual(len(matrix['employees']),1)
                    if totals is None:totals=matrix['totals']
                    self.assertEqual(matrix['totals'],totals)
                    for day in (4,5):
                        d=date(2026,10,day)
                        cells=[r['cells'][str(d)] for r in matrix['employees'][0]['rows'] if str(d) in r['cells']]
                        self.assertEqual(len(cells),1 if day==4 else 2)
                        current=next(c for c in cells if c['entity_id']==entity)
                        self.assertEqual(current['parent_entity_id'],target)
                        self.assertEqual(current['object_name'],parent_entity['name'] if target else initial['name'])
                        self.assertEqual(current.get('subobject_name'),initial['name'] if target else None)
                        weights=sorted(c['share_cents'] for c in cells)
                        shares.setdefault(day,weights);self.assertEqual(weights,shares[day])
                        report=build_report(d,matrix,{})
                        report_totals.setdefault(day,report['totals']);self.assertEqual(report['totals'],report_totals[day])
                        self.assertEqual(len(report['rows']),len(cells))
                        current_row=next(r for r in report['rows'] if r['entity_id']==entity)
                        self.assertEqual(current_row['parent_entity_id'],target)
                        self.assertEqual(current_row['object_name'],parent_entity['name']+'\n'+initial['name'] if target else initial['name'])
                    journal=get_journal(date(2026,10,4),date(2026,10,5),entity_id=entity,include_subobjects=False)
                    self.assertEqual(len(journal['items']),2)
                    self.assertEqual(len({r['source_sha256'] for r in journal['items']}),2)
                    self.assertTrue(all(r['parent_entity_id']==target for r in journal['items']))
        finally:
            for mock in reversed(mocks):mock.stop()
            conn.rollback()
            require_test_database(conn)
            self.assertEqual(snapshot(tables),original,'Test rows or hierarchy survived rollback')
            self.assertEqual(sequences(),original_sequences,'A sequence changed during the test')
            conn.rollback()
