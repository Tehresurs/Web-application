"""Standalone adapter/SQL checks on a disposable clean-start database copy."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.repositories import clean_construction_identity as adapter
from test_clean_start_categories_sql import CategoryChecks, MIGRATIONS


class AdapterTests(unittest.TestCase):
    fresh = False
    drop_copy = classmethod(CategoryChecks.drop_copy.__func__)

    @classmethod
    def setUpClass(cls):
        CategoryChecks.setUpClass.__func__(cls)
        cls.env = patch.dict(os.environ, {'CONSTRUCTION_MODEL':'clean_start', 'APP_DB_PROFILE':'test',
            'CLEAN_START_DB_PROFILE':'test','CLEAN_START_DB_SCHEMA':'public','CLEAN_START_DB_NAME':cls.database})
        cls.env.start()
        cls.addClassCleanup(cls.env.stop)
        with psycopg.connect(**cls.params, dbname=cls.database, autocommit=True) as c:
            c.execute("SELECT set_config('app.allow_clean_start_migration','yes',false)")
            c.execute("SELECT set_config('app.stage4129_rehearsal_database',%s,false)",(cls.database,))
            before = c.execute('SELECT * FROM construction_entities ORDER BY entity_id').fetchall()
            correction = (MIGRATIONS/'024_clean_start_archive_correction.sql').read_text(encoding='utf-8')
            c.execute(correction)
            c.execute(correction)
            assert c.execute('SELECT * FROM construction_entities ORDER BY entity_id').fetchall() == before

    def setUp(self):
        self.c = psycopg.connect(**self.params, dbname=self.database)
        self.addCleanup(self.c.close)
        self.addCleanup(self.c.rollback)
        self.root=self.insert('Adapter root')
        self.child=self.insert('Adapter child',self.root)

    def insert(self,name,parent=None):
        return self.c.execute('INSERT INTO construction_entities(name,parent_entity_id) VALUES(%s,%s) RETURNING entity_id',(name,parent)).fetchone()[0]

    def archive(self,eid):
        self.c.execute('UPDATE construction_entities SET is_archived=true,archived_at=clock_timestamp() WHERE entity_id=%s',(eid,))

    def test_model_and_environment(self):
        adapter.validate(self.c)
        for config in ({'CONSTRUCTION_MODEL':'legacy'},{'CONSTRUCTION_MODEL':''},
                       {'APP_DB_PROFILE':'production'},{'CLEAN_START_DB_PROFILE':'production'},
                       {'CLEAN_START_DB_NAME':'ai_excel_agent'}, {'CLEAN_START_DB_SCHEMA':'other'},
                       {'CLEAN_START_DB_NAME':'ai_excel_agent_stage41210_20261014_1634'}):
            with patch.dict(os.environ,config):
                with self.assertRaises(adapter.ModelUnavailable):adapter.resolve(self.c,self.root)

    def test_actual_schema_and_contract(self):
        self.c.execute('SET LOCAL search_path=pg_catalog')
        with self.assertRaises(adapter.ModelUnavailable):adapter.validate(self.c)
        self.c.execute('SET LOCAL search_path=public')
        self.c.execute('ALTER VIEW construction_entity_current RENAME COLUMN category_id TO missing_category')
        with self.assertRaises(adapter.ModelUnavailable):adapter.validate(self.c)

    def test_read_and_availability(self):
        item=adapter.resolve(self.c,self.child)
        self.assertEqual(item['parent']['entity_id'],self.root)
        self.assertTrue(item['available'])
        self.assertEqual(len(adapter.directory(self.c)),2)
        with self.assertRaises(ValueError):adapter.require_available(self.c,self.child,as_parent=True)
        with self.assertRaises(LookupError):adapter.resolve(self.c,9223372036854775807)
        self.archive(self.root)
        self.assertTrue(adapter.resolve(self.c,self.child)['effectively_archived'])
        with self.assertRaises(ValueError):adapter.require_available(self.c,self.child)

    def test_existing_child_under_archived_parent(self):
        self.archive(self.child)
        self.archive(self.root)
        self.c.execute("UPDATE construction_entities SET name='Renamed',activity_status='SUSPENDED' WHERE entity_id=%s",(self.child,))
        self.c.execute('UPDATE construction_entities SET is_archived=false,archived_at=NULL WHERE entity_id=%s',(self.child,))
        item=adapter.resolve(self.c,self.child)
        self.assertFalse(item['is_archived'])
        self.assertTrue(item['effectively_archived'])
        self.assertFalse(item['available'])
        destination=self.insert('Available destination')
        self.c.execute('UPDATE construction_entities SET parent_entity_id=%s WHERE entity_id=%s',(destination,self.child))
        self.assertTrue(adapter.require_available(self.c,self.child)['available'])
        self.assertEqual(adapter.resolve(self.c,self.child)['name'],'Renamed')
        self.archive(destination)
        self.c.execute('UPDATE construction_entities SET parent_entity_id=NULL WHERE entity_id=%s',(self.child,))
        self.assertIsNone(adapter.resolve(self.c,self.child)['parent'])

    def test_new_invalid_links_rejected_atomically(self):
        self.archive(self.root)
        target=self.insert('Movable root')
        before=adapter.resolve(self.c,target)
        for query,args in [
            ('INSERT INTO construction_entities(name,parent_entity_id) VALUES(%s,%s)',('New invalid child',self.root)),
            ('UPDATE construction_entities SET parent_entity_id=%s WHERE entity_id=%s',(self.root,target)),
            ('UPDATE construction_entities SET parent_entity_id=%s WHERE entity_id=%s',(self.child,target)),
            ('UPDATE construction_entities SET parent_entity_id=%s WHERE entity_id=%s',(target,target)),
        ]:
            with self.assertRaises(psycopg.errors.CheckViolation):
                with self.c.transaction():self.c.execute(query,args)
        self.assertEqual(adapter.resolve(self.c,target),before)


if __name__=='__main__':unittest.main(verbosity=2,failfast=True)
