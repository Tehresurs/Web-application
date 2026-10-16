import unittest
from copy import deepcopy
from unittest.mock import patch
from app.services.production_assignments import canonical_movements,project
from app.services.production_matrix_overrides import resolve
from app.repositories.rail_tickets import _guard_confirmed_trip
from app.repositories.directory_errors import DirectoryConflict

class DuplicateGuardTests(unittest.TestCase):
    def data(self):
        station1='Origin';station2='Destination'
        old=dict(id=107,employee_id=11,movement_type='ARRIVAL',transport_type='RAIL',
                 event_datetime='2026-10-12T15:34:00',departure_station=station1,arrival_station=station2)
        confirmed={**old,'id':123}
        return dict(id=11,work_location='OBJECT',work_schedule='SHIFT',dismissal_date=None,
                    movements=[old,confirmed],tickets=[dict(id=261,status='CONFIRMED',movement_id=123)],changes=[],
                    facts=[dict(id=563,report_date='2026-10-13',employee_id=11,object_id=57,po_id=5,category_id=1)])
    def test_exact_legacy_duplicate_prefers_confirmed_without_mutating_history(self):
        data=self.data();before=deepcopy(data)
        self.assertEqual([m['id'] for m in canonical_movements(data)],[123])
        result=project(data,'2026-10-01','2026-10-31')
        self.assertFalse(result['warnings'])
        self.assertTrue(any(p['basis_kind']=='FACTS' for p in result['periods']))
        self.assertEqual(data,before)
    def test_distinct_movements_are_not_merged_and_ids_explain_ambiguity(self):
        data=self.data();data['movements'][0]['departure_station']='Other'
        self.assertEqual(len(canonical_movements(data)),2)
        issues=project(data,'2026-10-01','2026-10-31')['warnings']
        issue=next(w for w in issues if w['code']=='AMBIGUOUS_MOVEMENTS')
        self.assertEqual(issue['movement_ids'],[107,123])
    def test_unconfirmed_arrival_remains_unconfirmed(self):
        data=self.data();data['tickets']=[];data['movements']=data['movements'][:1]
        self.assertIn('ARRIVAL_UNCONFIRMED',[w['code'] for w in project(data,'2026-10-01','2026-10-31')['warnings']])
    def test_duplicate_trip_is_rejected_even_for_another_file(self):
        class Cursor:
            def execute(self,*args):pass
            def fetchall(self):return [dict(id=261,departure_station=' Origin ',arrival_station='DESTINATION')]
        ticket=dict(id=999,departure_station='Origin',arrival_station='Destination',departure_datetime='2026-10-12T09:33',arrival_datetime='2026-10-12T15:34')
        with self.assertRaises(DirectoryConflict):_guard_confirmed_trip(Cursor(),ticket,11)

class TicketReuseTests(unittest.TestCase):
    def test_confirmation_reuses_unlinked_movement_and_rejects_second_file(self):
        import os
        from contextlib import contextmanager
        from hashlib import sha256
        from datetime import timedelta
        from app.database.db import get_connection
        from app.repositories.rail_tickets import confirm_ticket
        with patch.dict(os.environ,APP_DB_PROFILE='test',DB_NAME='ai_excel_agent_test',DB_SCHEMA='test_construction_identity_stage46'):
            conn=get_connection()
            try:
                self.assertEqual(conn.execute('select current_database(),current_schema()').fetchone(),('ai_excel_agent_test','test_construction_identity_stage46'))
                conn.execute('SELECT pg_advisory_xact_lock(20261007,1601)')
                # Build a new isolated event; never depend on editable user history.
                eid,name=conn.execute('SELECT id,full_name FROM employees WHERE NOT is_archived ORDER BY id LIMIT 1').fetchone()
                stamp='2039-01-05 10:00:00'
                origin='Test origin';destination='Test destination'
                # Route parser is patched only for this synthetic fixture.
                mid=conn.execute("INSERT INTO employee_movements(employee_id,movement_type,transport_type,event_datetime,departure_station,arrival_station) VALUES(%s,'ARRIVAL','RAIL',%s,%s,%s) RETURNING id",(eid,stamp,origin,destination)).fetchone()[0]
                def ticket(label):
                    return conn.execute("INSERT INTO rail_tickets(file_hash,source_filename,full_name,departure_station,departure_datetime,arrival_station,arrival_datetime,status,parse_errors,movement_type) VALUES(%s,%s,%s,%s,'2039-01-04 10:00',%s,%s,'PARSED','[]','ARRIVAL') RETURNING id",(sha256(label.encode()).hexdigest(),label,name,origin,destination,stamp)).fetchone()[0]
                a=ticket('rollback-duplicate-a.pdf');b=ticket('rollback-duplicate-b.pdf')
                @contextmanager
                def connection():yield conn
                with patch('app.repositories.rail_tickets.get_connection',connection),patch('app.repositories.rail_tickets.sync_production_assignment'),patch('app.repositories.rail_tickets.luvr_route',return_value=(True,'ARRIVAL')):
                    first=confirm_ticket(a,eid)
                    self.assertEqual(first['movement_id'],mid)
                    again=confirm_ticket(a,eid)
                    self.assertEqual(again['movement_id'],mid)
                    with self.assertRaises(DirectoryConflict):confirm_ticket(b,eid)
                self.assertEqual(conn.execute('SELECT count(*) FROM employee_movements WHERE employee_id=%s AND event_datetime=%s',(eid,stamp)).fetchone()[0],1)
            finally:
                conn.rollback();conn.close()
