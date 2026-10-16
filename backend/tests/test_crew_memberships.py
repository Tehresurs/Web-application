import os
import unittest
from contextlib import contextmanager
from unittest.mock import patch
import test_luvr_directories
from test_daily_control import http_request


@unittest.skipUnless(os.getenv('DAILY_CONTROL_TEST_DB') == '1', 'Requires isolated PostgreSQL')
class CrewMembershipTests(unittest.TestCase):
    def setUp(self):
        test_luvr_directories.LuvrDirectoryTests.setUp(self)
        self.conn.execute("INSERT INTO crews(id,name) VALUES(1,'First'),(2,'Second')")
        self.conn.execute('ALTER TABLE employees ADD FOREIGN KEY(crew_id) REFERENCES crews(id) ON DELETE SET NULL')
        @contextmanager
        def connection():
            with self.conn.transaction():
                yield self.conn
        mocked = patch('app.repositories.crew_memberships.get_connection', connection)
        mocked.start()
        self.addCleanup(mocked.stop)

    def change(self, target, links, confirmed=False, **extra):
        return http_request('PATCH', '/api/crew-memberships', dict(target_crew_id=target,
            employees=[dict(employee_id=e, expected_crew_id=c) for e,c in links], confirm_transfers=confirmed, **extra))

    def links(self):
        return self.conn.execute('SELECT id,crew_id FROM employees ORDER BY id').fetchall()

    def test_add_one_and_remove(self):
        self.assertEqual(self.change(1,[(1,None)])[0],200)
        self.assertEqual(self.links(),[(1,1),(2,None)])
        self.assertEqual(self.change(None,[(1,1)])[0],200)
        self.assertEqual(self.links(),[(1,None),(2,None)])

    def test_batch_and_preserve_all_other_fields(self):
        before=self.conn.execute("SELECT to_jsonb(e)-'crew_id' FROM employees e ORDER BY id").fetchall()
        self.assertEqual(self.change(2,[(1,None),(2,None)])[0],200)
        self.assertEqual(self.links(),[(1,2),(2,2)])
        self.assertEqual(before,self.conn.execute("SELECT to_jsonb(e)-'crew_id' FROM employees e ORDER BY id").fetchall())
        employees=http_request('GET','/api/employees')[1]['items']
        self.assertEqual({e['crew_id'] for e in employees},{2})

    def test_transfer_requires_confirmation(self):
        self.change(1,[(1,None)])
        self.assertEqual(self.change(2,[(1,1)])[0],409)
        self.assertEqual(self.links()[0],(1,1))
        self.assertEqual(self.change(2,[(1,1)],True)[0],200)
        self.assertEqual(self.links()[0],(1,2))

    def test_stale_batch_does_not_partially_save(self):
        self.change(1,[(2,None)])
        self.assertEqual(self.change(2,[(1,None),(2,None)],True)[0],409)
        self.assertEqual(self.links(),[(1,None),(2,1)])
        self.assertEqual(self.change(None,[(2,None)])[0],409)

    def test_missing_employee_or_crew_rolls_back(self):
        self.assertEqual(self.change(1,[(1,None),(999,None)])[0],404)
        self.assertEqual(self.change(999,[(1,None)])[0],404)
        self.assertEqual(self.links(),[(1,None),(2,None)])

    def test_duplicates_repeat_and_narrow_payload(self):
        self.assertEqual(self.change(1,[(1,None),(1,None)])[0],400)
        self.assertEqual(self.change(1,[(1,None)],full_name='Changed')[0],422)
        self.assertEqual(self.change(1,[(1,None)])[0],200)
        self.assertEqual(self.change(1,[(1,None)])[0],409)
        self.assertEqual(self.change(1,[(1,1)])[0],200)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM employees').fetchone()[0],2)

    def test_database_error_rolls_back_entire_group(self):
        self.conn.execute('ALTER TABLE employees ADD CONSTRAINT test_reject CHECK(id<>2 OR crew_id IS NULL)')
        from app.repositories.crew_memberships import change_memberships
        with self.assertRaises(Exception):
            change_memberships(1,[dict(employee_id=i,expected_crew_id=None) for i in (1,2)])
        self.assertEqual(self.links(),[(1,None),(2,None)])

    def test_expected_state_is_required_and_strict(self):
        for body in [dict(target_crew_id=1,employees=[dict(employee_id=1)]),
                     dict(target_crew_id=True,employees=[dict(employee_id=1,expected_crew_id=None)]),
                     dict(target_crew_id=1,employees=[])]:
            self.assertEqual(http_request('PATCH','/api/crew-memberships',body)[0],422)
