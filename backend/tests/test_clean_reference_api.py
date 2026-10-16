"""Read-only reference API checks on a disposable clone and an ephemeral port."""
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import psycopg
from psycopg.rows import dict_row
from fastapi import HTTPException
from test_clean_construction_api import CleanAPI
from app.api.clean_construction import connection


class ReferenceAPI(unittest.TestCase):
    fresh = False
    setUpClass = classmethod(CleanAPI.setUpClass.__func__)
    drop_copy = classmethod(CleanAPI.drop_copy.__func__)
    stop_server = classmethod(CleanAPI.stop_server.__func__)

    def test_source_and_fields(self):
        queries = {
            '/employees?archive=all': '''SELECT e.id,e.full_name,e.position_id,p.name AS position_name,e.is_archived,e.archived_at
                FROM employees e LEFT JOIN positions p ON p.id=e.position_id ORDER BY e.full_name,e.id''',
            '/po-types': 'SELECT id,name FROM po_types ORDER BY name,id',
            '/categories': 'SELECT id,name,parent_id,sort_order,is_system FROM object_categories ORDER BY sort_order,id',
        }
        with psycopg.connect(**self.params, dbname=self.database, row_factory=dict_row) as conn:
            self.assertEqual(conn.execute('SELECT current_database() db').fetchone()['db'],self.database)
            for endpoint, query in queries.items():
                expected=conn.execute(query).fetchall()
                response=self.client.get(endpoint)
                self.assertEqual(response.status_code,200,response.text)
                # FastAPI serializes timestamps using ISO format.
                from fastapi.encoders import jsonable_encoder
                self.assertEqual(response.json()['items'],jsonable_encoder(expected))
            archived=self.client.get('/employees?archive=archived').json()['items']
            active=self.client.get('/employees').json()['items']
            self.assertTrue(all(r['is_archived'] for r in archived))
            self.assertTrue(all(not r['is_archived'] for r in active))
            self.assertEqual(len(active)+len(archived),len(self.client.get('/employees?archive=all').json()['items']))

    def test_environment_rejected(self):
        for change in ({'CONSTRUCTION_MODEL':'legacy'},{'CONSTRUCTION_MODEL':''},
                       {'APP_DB_PROFILE':'production'},{'CLEAN_START_DB_PROFILE':'production'},
                       {'CLEAN_START_DB_NAME':'ai_excel_agent'},{'CLEAN_START_DB_SCHEMA':'other'}):
            with patch.dict(os.environ,change):
                for endpoint in ('/employees','/po-types','/categories'):
                    self.assertEqual(self.client.get(endpoint).status_code,403)

    def test_actual_schema_mismatch_and_read_only(self):
        original=psycopg.connect
        def wrong_schema(**kwargs):
            kwargs['options']='-c search_path=pg_catalog'
            return original(**kwargs)
        with patch('app.api.clean_construction.psycopg.connect',side_effect=wrong_schema):
            self.assertEqual(self.client.get('/employees').status_code,403)
        class MismatchedDatabase:
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc_value, traceback):
                return False
            def execute(self, query, params=None):
                class Result:
                    @staticmethod
                    def fetchone():
                        return {'db':'unexpected_database','schema':'public'}
                return Result()
        with patch('app.api.clean_construction.psycopg.connect',return_value=MismatchedDatabase()):
            self.assertEqual(self.client.get('/employees').status_code,403)
        with connection(read_only=True,require_model=True) as conn:
            self.assertEqual(conn.execute('SHOW transaction_read_only').fetchone()['transaction_read_only'],'on')
            with self.assertRaises(psycopg.errors.ReadOnlySqlTransaction):
                with conn.transaction():
                    conn.execute("UPDATE public.po_types SET name=name WHERE false")
        for endpoint in ('/employees','/po-types','/categories'):
            self.assertEqual(self.client.post(endpoint,json={}).status_code,405)

    def test_legacy_ui_routes_unchanged(self):
        root=Path(__file__).resolve().parents[1]
        source=(root/'app/static/js/processing.js').read_text(encoding='utf-8')
        self.assertIn('fetch("/api/po-types")',source)
        self.assertIn('fetch("/api/object-categories")',source)
        self.assertIn('/api/employees/${employeeId}/assignments',source)
        self.assertNotIn('/api/clean-construction-entities',source)
        main=(root/'app/main.py').read_text(encoding='utf-8')
        self.assertIn('@app.get("/api/po-types")',main)
        self.assertIn('@app.get("/api/object-categories")',main)


if __name__=='__main__':unittest.main(verbosity=2,failfast=True)
