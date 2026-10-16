"""Run directly: python tests/test_clean_construction_api.py (real isolated HTTP port)."""
import os
from pathlib import Path
import socket
import sys
import threading
import time
import unittest
import subprocess
from unittest.mock import patch

import urllib.request
import urllib.error
import psycopg
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.api.clean_construction import router
from test_clean_start_categories_sql import CategoryChecks


class Client:
    def __init__(self, base_url, **kwargs):
        self.base_url = base_url

    def request(self, method, path, json=None):
        import json as codec
        req = urllib.request.Request(self.base_url + path, method=method,
            data=None if json is None else codec.dumps(json).encode(),
            headers={'Content-Type': 'application/json'})
        try:
            response = urllib.request.urlopen(req, timeout=10)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            status, body = response.code, response.read().decode()
        class Result:
            status_code = status
            text = body
            def json(self):
                return codec.loads(body)
        return Result()

    def get(self, path): return self.request('GET', path)
    def post(self, path, **kwargs): return self.request('POST', path, **kwargs)
    def patch(self, path, **kwargs): return self.request('PATCH', path, **kwargs)
    def delete(self, path): return self.request('DELETE', path)
    def close(self): pass


class CleanAPI(unittest.TestCase):
    fresh = False
    drop_copy = classmethod(CategoryChecks.drop_copy.__func__)

    @classmethod
    def setUpClass(cls):
        CategoryChecks.setUpClass.__func__(cls)
        config = {'APP_DB_PROFILE': 'test', 'CLEAN_START_DB_PROFILE': 'test', 'CONSTRUCTION_MODEL': 'clean_start',
                  'CLEAN_START_DB_NAME': cls.database, 'CLEAN_START_DB_SCHEMA': 'public'}
        config.update({'CLEAN_START_DB_' + key.upper(): str(value) for key, value in cls.params.items()})
        cls.env = patch.dict(os.environ, config)
        cls.env.start()
        cls.addClassCleanup(cls.env.stop)
        app = FastAPI()
        app.include_router(router)
        app.mount('/static', StaticFiles(directory=Path(__file__).resolve().parents[1] / 'app/static'))
        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
        assert port not in (8000, 8001)
        cls.server = uvicorn.Server(uvicorn.Config(app, log_level='error'))
        cls.thread = threading.Thread(target=cls.server.run, kwargs={'sockets': [sock]}, daemon=True)
        cls.thread.start()
        cls.addClassCleanup(cls.stop_server)
        for _ in range(100):
            if cls.server.started:
                break
            time.sleep(.05)
        assert cls.server.started
        print('Isolated HTTP port:', port)
        cls.port = port
        cls.client = Client(base_url=f'http://127.0.0.1:{port}/api/clean-construction-entities', timeout=10)
        cls.addClassCleanup(cls.client.close)

    @classmethod
    def stop_server(cls):
        cls.server.should_exit = True
        cls.thread.join(10)

    def create(self, name, **fields):
        response = self.client.post('', json={'name': name, **fields})
        self.assertEqual(response.status_code, 201, response.text)
        item = response.json()['item']
        self.assertFalse({'id', 'object_id', 'subobject_id', 'legacy_object_id'} & item.keys())
        return item

    def test_lifecycle(self):
        with psycopg.connect(**self.params, dbname=self.database) as c:
            category = c.execute("INSERT INTO object_categories(name) VALUES ('API category') RETURNING id").fetchone()[0]
        root = self.create('API root', category_id=category)
        child = self.create('API child', parent_entity_id=root['entity_id'], category_id=category)
        eid = child['entity_id']
        def change(method, suffix, **payload):
            nonlocal child
            response = self.client.request(method, f'/{eid}{suffix}', json={'version': child['version'], **payload})
            self.assertEqual(response.status_code, 200, response.text)
            child = response.json()['item']
            self.assertEqual(child['entity_id'], eid)
            self.assertEqual(child['category_id'], category)
        change('PATCH', '', name='API renamed', activity_status='SUSPENDED')
        change('PATCH', '/hierarchy', parent_entity_id=None, confirmed=True)
        self.assertIn(eid, [i['entity_id'] for i in self.client.get('?kind=objects').json()['items']])
        change('PATCH', '/hierarchy', parent_entity_id=root['entity_id'], confirmed=True)
        self.assertNotIn(eid, [i['entity_id'] for i in self.client.get('?kind=objects').json()['items']])
        self.assertEqual(self.client.get(f'?parent_entity_id={root["entity_id"]}').json()['items'][0]['entity_id'], eid)
        change('POST', '/archive')
        self.assertTrue(child['is_archived'])
        change('POST', '/restore')
        self.assertFalse(child['is_archived'])
        self.assertEqual(self.client.get(f'/{eid}').json()['item']['name'], 'API renamed')
        with psycopg.connect(**self.params, dbname=self.database) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM construction_objects').fetchone()[0], 0)
            self.assertEqual(c.execute('SELECT count(*) FROM construction_subobjects').fetchone()[0], 0)

    def test_structural_errors_atomic(self):
        root = self.create('Constraints root')
        child = self.create('Constraints child', parent_entity_id=root['entity_id'])
        for entity, parent in [(root, root['entity_id']), (root, child['entity_id']), (child, child['entity_id']), (child, 9223372036854775807)]:
            before = self.client.get(f'/{entity["entity_id"]}').json()
            result = self.client.patch(f'/{entity["entity_id"]}/hierarchy', json={
                'parent_entity_id': parent, 'version': entity['version'], 'confirmed': True})
            self.assertEqual(result.status_code, 409, result.text)
            self.assertEqual(self.client.get(f'/{entity["entity_id"]}').json(), before)
        self.assertEqual(self.client.post('', json={'name': 'grandchild', 'parent_entity_id': child['entity_id']}).status_code, 409)
        self.assertEqual(self.client.post('', json={'name': root['name']}).status_code, 409)
        self.assertEqual(self.client.patch(f'/{child["entity_id"]}', json={'name':'stale','version':999}).status_code, 409)

    def test_archive_parent_and_parents_list(self):
        root = self.create('Archived parent')
        other = self.create('Parent candidate')
        self.assertEqual(self.client.post(f'/{root["entity_id"]}/archive', json={'version':root['version']}).status_code, 200)
        self.assertEqual(self.client.post('', json={'name':'blocked child','parent_entity_id':root['entity_id']}).status_code,409)
        candidates = self.client.get(f'?parents_for={other["entity_id"]}').json()['items']
        self.assertTrue(all(i['parent_entity_id'] is None and not i['is_archived'] and i['entity_id'] != other['entity_id'] for i in candidates))

    def test_validation_and_missing(self):
        for payload in ({'name':''}, {'name':'valid','activity_status':'INVALID'}, {'name':'valid','object_id':1}):
            self.assertEqual(self.client.post('', json=payload).status_code,422)
        self.assertEqual(self.client.post('', json={'name':'bad category','category_id':9223372036854775807}).status_code,409)
        self.assertEqual(self.client.get('/9223372036854775807').status_code,404)
        self.assertEqual(self.client.delete('/1').status_code,405)

    def test_category_changes(self):
        with psycopg.connect(**self.params, dbname=self.database) as c:
            before = c.execute('SELECT * FROM object_categories ORDER BY id').fetchall()
            category = before[0][0]
        item = self.create('Category changes')
        eid = item['entity_id']
        result = self.client.patch(f'/{eid}', json={'version':item['version'], 'category_id':category})
        self.assertEqual(result.status_code,200,result.text)
        item = result.json()['item']
        self.assertEqual(item['category_id'],category)
        failed = self.client.patch(f'/{eid}', json={'version':item['version'], 'category_id':9223372036854775807})
        self.assertEqual(failed.status_code,409)
        self.assertEqual(self.client.get(f'/{eid}').json()['item'],item)
        result = self.client.patch(f'/{eid}', json={'version':item['version'], 'category_id':None})
        self.assertEqual(result.status_code,200)
        self.assertIsNone(result.json()['item']['category_id'])
        with psycopg.connect(**self.params, dbname=self.database) as c:
            self.assertEqual(c.execute('SELECT * FROM object_categories ORDER BY id').fetchall(),before)

    def test_environment_guards(self):
        for config in ({'APP_DB_PROFILE':'production'}, {'CLEAN_START_DB_PROFILE':'production'},
                       {'CLEAN_START_DB_NAME':'ai_excel_agent'}, {'CLEAN_START_DB_SCHEMA':'wrong'}):
            with patch.dict(os.environ,config):
                self.assertEqual(self.client.post('',json={'name':'must not write'}).status_code,403)
                self.assertEqual(self.client.get('/workspace').status_code,403)
        env = self.client.get('/environment').json()['item']
        self.assertEqual((env['database'],env['schema']), (self.database,'public'))

    def test_workspace_browser(self):
        page = self.client.get('/workspace')
        self.assertEqual(page.status_code,200)
        self.assertNotIn('/static/js/processing.js',page.text)
        self.assertIn('clean_construction_workspace.js',page.text)
        result = subprocess.run(['node', str(Path(__file__).parent / 'browser/clean_construction.cjs'),
            f'http://127.0.0.1:{self.port}'], capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode,0,result.stdout + result.stderr)
        self.assertIn('Browser lifecycle passed', result.stdout)


if __name__ == '__main__':
    unittest.main(verbosity=2, failfast=True)
