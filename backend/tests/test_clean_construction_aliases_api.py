"""Entity-alias API checks on a disposable copy of an approved clean-start DB."""
import os
from pathlib import Path
import socket
import sys
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
import uuid
from unittest.mock import patch

import psycopg
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI

ROOT = Path(__file__).resolve().parents[1]
sys_path = str(ROOT)
if sys_path not in sys.path:
    sys.path.insert(0, sys_path)

from app.api.clean_construction import router


SOURCE_DATABASE = 'ai_excel_agent_stage4151_20261019_86bf41ed'


class APIClient:
    def __init__(self, base_url):
        self.base_url = base_url

    def request(self, method, path, payload=None):
        import json

        request = urllib.request.Request(
            self.base_url + path,
            method=method,
            data=None if payload is None else json.dumps(payload).encode(),
            headers={'Content-Type': 'application/json'},
        )
        try:
            response = urllib.request.urlopen(request, timeout=10)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.code, json.loads(response.read().decode())


class CleanConstructionAliasAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        load_dotenv(ROOT / '.env')
        cls.params = {
            'host': os.environ['DB_HOST'],
            'port': os.environ['DB_PORT'],
            'user': os.environ['DB_USER'],
            'password': os.environ['DB_PASSWORD'],
        }
        cls.database = 'ai_excel_agent_test_categories_' + uuid.uuid4().hex[:12]
        with psycopg.connect(**cls.params, dbname=SOURCE_DATABASE, autocommit=True) as admin:
            actual = admin.execute('SELECT current_database(),current_schema()').fetchone()
            if actual != (SOURCE_DATABASE, 'public'):
                raise AssertionError(f'Unexpected clean-start source: {actual!r}')
            if admin.execute(
                "SELECT to_regclass('public.construction_entity_aliases')"
            ).fetchone()[0] is None:
                raise AssertionError('The clean-start source has no construction_entity_aliases')
            admin.execute(
                psycopg.sql.SQL('CREATE DATABASE {} TEMPLATE {}').format(
                    psycopg.sql.Identifier(cls.database),
                    psycopg.sql.Identifier(SOURCE_DATABASE),
                )
            )
        cls.addClassCleanup(cls.drop_copy)

        env = {
            'APP_DB_PROFILE': 'test',
            'CLEAN_START_DB_PROFILE': 'test',
            'CLEAN_START_DB_NAME': cls.database,
            'CLEAN_START_DB_SCHEMA': 'public',
            'CONSTRUCTION_MODEL': 'clean_start',
        }
        env.update({
            'CLEAN_START_DB_' + key.upper(): str(value)
            for key, value in cls.params.items()
        })
        cls.env = patch.dict(os.environ, env)
        cls.env.start()
        cls.addClassCleanup(cls.env.stop)

        app = FastAPI()
        app.include_router(router)
        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        cls.port = sock.getsockname()[1]
        if cls.port in (8000, 8001):
            sock.close()
            raise AssertionError('The alias test server must not use port 8000 or 8001')
        cls.server = uvicorn.Server(uvicorn.Config(app, log_level='error'))
        cls.thread = threading.Thread(
            target=cls.server.run, kwargs={'sockets': [sock]}, daemon=True
        )
        cls.thread.start()
        cls.addClassCleanup(cls.stop_server)
        for _ in range(100):
            if cls.server.started:
                break
            time.sleep(0.05)
        if not cls.server.started:
            raise AssertionError('The isolated clean-start test server did not start')
        cls.client = APIClient(
            f'http://127.0.0.1:{cls.port}/api/clean-construction-entities'
        )

    @classmethod
    def drop_copy(cls):
        if not getattr(cls, 'database', '').startswith('ai_excel_agent_test_categories_'):
            raise AssertionError('Refusing to drop a database outside the test-copy allowlist')
        with psycopg.connect(**cls.params, dbname=SOURCE_DATABASE, autocommit=True) as admin:
            admin.execute(
                psycopg.sql.SQL('DROP DATABASE {}').format(
                    psycopg.sql.Identifier(cls.database)
                )
            )

    @classmethod
    def stop_server(cls):
        cls.server.should_exit = True
        cls.thread.join(10)

    def create_entity(self, name, parent_entity_id=None):
        status, response = self.client.request('POST', '', {
            'name': name,
            'parent_entity_id': parent_entity_id,
        })
        self.assertEqual(status, 201, response)
        return response['item']

    def create_alias(self, entity_id, source_value):
        return self.client.request('POST', '/aliases', {
            'entity_id': entity_id,
            'source_value': source_value,
        })

    def test_alias_crud_uses_entity_ids(self):
        entity = self.create_entity('Alias CRUD ' + uuid.uuid4().hex)
        status, created = self.create_alias(entity['entity_id'], 'Alt name ' + uuid.uuid4().hex)
        self.assertEqual(status, 201, created)
        alias = created['item']
        self.assertEqual(alias['entity_id'], entity['entity_id'])
        self.assertTrue({'alias_id', 'entity_id', 'source_value', 'normalized_source_value'} <= alias.keys())
        self.assertFalse({'object_id', 'subobject_id', 'legacy_object_id'} & alias.keys())

        status, listed = self.client.request('GET', '/aliases')
        self.assertEqual(status, 200)
        self.assertIn(alias, listed['items'])
        status, scoped = self.client.request('GET', f'/aliases?entity_id={entity["entity_id"]}')
        self.assertEqual(status, 200)
        self.assertEqual(scoped['items'], [alias])

        new_name = 'Renamed alias ' + uuid.uuid4().hex
        status, updated = self.client.request(
            'PATCH', f'/aliases/{alias["alias_id"]}',
            {'entity_id': entity['entity_id'], 'source_value': new_name},
        )
        self.assertEqual(status, 200, updated)
        self.assertEqual(updated['item']['normalized_source_value'], new_name.lower())

        status, deleted = self.client.request('DELETE', f'/aliases/{alias["alias_id"]}')
        self.assertEqual(status, 200, deleted)
        self.assertTrue(deleted['deleted'])
        self.assertEqual(
            self.client.request('GET', f'/aliases?entity_id={entity["entity_id"]}')[1]['items'],
            [],
        )
        self.assertEqual(self.client.request('DELETE', '/aliases/9223372036854775807')[0], 404)

    def test_exact_search_alias_search_and_unknown_name(self):
        entity = self.create_entity('Exact search ' + uuid.uuid4().hex)
        alias_name = 'Alternative ' + uuid.uuid4().hex
        status, _ = self.create_alias(entity['entity_id'], alias_name)
        self.assertEqual(status, 201)

        exact = self.client.request('GET', '/match?name=' + urllib.parse.quote(entity['name']))[1]['match']
        self.assertEqual((exact['status'], exact['match_source']), ('found', 'name'))
        self.assertEqual(exact['entity_id'], entity['entity_id'])
        alias = self.client.request('GET', '/match?name=' + urllib.parse.quote(alias_name))[1]['match']
        self.assertEqual((alias['status'], alias['match_source']), ('found', 'alias'))
        self.assertEqual(alias['entity_id'], entity['entity_id'])
        normalized_alias = self.client.request(
            'GET', '/match?name=' + urllib.parse.quote(alias_name.upper())
        )[1]['match']
        self.assertEqual(normalized_alias['entity_id'], entity['entity_id'])
        missing = self.client.request(
            'GET', '/match?name=' + urllib.parse.quote('unknown ' + uuid.uuid4().hex)
        )[1]['match']
        self.assertEqual(missing, {'status': 'not_found'})

    def test_ambiguity_is_reported_without_choosing(self):
        canonical = 'Ambiguous name ' + uuid.uuid4().hex
        first = self.create_entity(canonical)
        second = self.create_entity('Other entity ' + uuid.uuid4().hex)
        status, _ = self.create_alias(second['entity_id'], canonical)
        self.assertEqual(status, 201)

        result = self.client.request(
            'GET', '/match?name=' + urllib.parse.quote(canonical)
        )[1]
        self.assertEqual(result['match']['status'], 'ambiguous')
        self.assertNotIn('entity_id', result['match'])
        self.assertEqual(
            {candidate['entity_id'] for candidate in result['candidates']},
            {first['entity_id'], second['entity_id']},
        )

    def test_duplicate_normalized_alias_and_invalid_entity(self):
        first = self.create_entity('Duplicate target A ' + uuid.uuid4().hex)
        second = self.create_entity('Duplicate target B ' + uuid.uuid4().hex)
        name = 'Duplicate alias ' + uuid.uuid4().hex
        self.assertEqual(self.create_alias(first['entity_id'], name)[0], 201)
        self.assertEqual(self.create_alias(second['entity_id'], '  ' + name.upper() + '  ')[0], 409)
        self.assertEqual(
            self.create_alias(9223372036854775807, 'Missing target ' + uuid.uuid4().hex)[0],
            404,
        )
        self.assertEqual(self.create_alias(first['entity_id'], '   ')[0], 422)
        self.assertEqual(
            self.client.request('PATCH', '/aliases/9223372036854775807', {
                'entity_id': first['entity_id'],
                'source_value': 'Missing alias',
            })[0],
            404,
        )

        with psycopg.connect(**self.params, dbname=self.database) as conn:
            with self.assertRaises(psycopg.errors.ForeignKeyViolation):
                with conn.transaction():
                    conn.execute(
                        '''INSERT INTO construction_entity_aliases(entity_id,source_value)
                           VALUES (%s,%s)''',
                        (9223372036854775807, 'direct FK check ' + uuid.uuid4().hex),
                    )

    def test_alias_survives_object_subobject_round_trip(self):
        parent = self.create_entity('Alias parent ' + uuid.uuid4().hex)
        child = self.create_entity(
            'Alias child ' + uuid.uuid4().hex, parent['entity_id']
        )
        alias_name = 'Persistent alias ' + uuid.uuid4().hex
        status, created = self.create_alias(child['entity_id'], alias_name)
        self.assertEqual(status, 201, created)
        alias_id = created['item']['alias_id']

        status, standalone = self.client.request(
            'PATCH', f'/{child["entity_id"]}/hierarchy',
            {'version': child['version'], 'parent_entity_id': None, 'confirmed': True},
        )
        self.assertEqual(status, 200, standalone)
        status, promoted = self.client.request(
            'PATCH', f'/{child["entity_id"]}/hierarchy',
            {'version': standalone['item']['version'],
             'parent_entity_id': parent['entity_id'], 'confirmed': True},
        )
        self.assertEqual(status, 200, promoted)

        status, aliases = self.client.request(
            'GET', f'/aliases?entity_id={child["entity_id"]}'
        )
        self.assertEqual(status, 200)
        self.assertEqual([row['alias_id'] for row in aliases['items']], [alias_id])
        matched = self.client.request(
            'GET', '/match?name=' + urllib.parse.quote(alias_name)
        )[1]['match']
        self.assertEqual(matched['entity_id'], child['entity_id'])
        self.assertEqual(matched['match_source'], 'alias')

    def test_wrong_profile_refused_and_legacy_routes_unchanged(self):
        for environment in (
            {'APP_DB_PROFILE': 'production'},
            {'CLEAN_START_DB_NAME': 'ai_excel_agent'},
            {'CLEAN_START_DB_SCHEMA': 'other'},
        ):
            with patch.dict(os.environ, environment):
                self.assertEqual(self.client.request('GET', '/aliases')[0], 403)
                self.assertEqual(self.client.request('GET', '/match?name=anything')[0], 403)
        source = (ROOT / 'app/main.py').read_text(encoding='utf-8')
        self.assertIn('app.include_router(known_values_router)', source)
        self.assertIn('app.include_router(clean_construction_router)', source)
        known_values = (ROOT / 'app/api/known_values.py').read_text(encoding='utf-8')
        self.assertIn('@router.get("/value-aliases"', known_values)
        self.assertIn('@router.post("/value-aliases"', known_values)


if __name__ == '__main__':
    unittest.main(verbosity=2, failfast=True)
