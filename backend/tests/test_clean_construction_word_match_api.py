"""Read-only clean-start Word object matching on a disposable DB copy."""
import os
from pathlib import Path
import socket
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
import uuid
from unittest.mock import patch

import psycopg
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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


class TestCleanConstructionWordMatchAPI(unittest.TestCase):
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
            actual = admin.execute(
                'SELECT current_database(),current_schema()'
            ).fetchone()
            if actual != (SOURCE_DATABASE, 'public'):
                raise AssertionError(f'Unexpected clean-start source: {actual!r}')
            if admin.execute(
                "SELECT to_regclass('public.construction_entity_aliases')"
            ).fetchone()[0] is None:
                raise AssertionError('The clean-start source has no entity aliases table')
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
            raise AssertionError('The test server must not use port 8000 or 8001')
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

    def match(self, name):
        status, response = self.client.request(
            'POST', '/word-report-match', {'object_name': name}
        )
        self.assertEqual(status, 200, response)
        self.assertEqual(response['status'], 'ok')
        return response['match']

    def test_exact_alias_similar_unknown_and_raw_input(self):
        name = 'Word exact ' + uuid.uuid4().hex
        entity = self.create_entity(name)
        exact = self.match('  ' + name.upper() + '  ')
        self.assertEqual((exact['status'], exact['match_source']), ('found', 'exact'))
        self.assertEqual(exact['entity_id'], entity['entity_id'])
        self.assertEqual(exact['raw_name'], '  ' + name.upper() + '  ')
        self.assertEqual(exact['entity']['kind'], 'object')

        alias_name = 'Word alias ' + uuid.uuid4().hex
        status, created = self.client.request('POST', '/aliases', {
            'entity_id': entity['entity_id'],
            'source_value': alias_name,
        })
        self.assertEqual(status, 201, created)
        alias = self.match(alias_name.upper())
        self.assertEqual((alias['status'], alias['match_source']), ('found', 'alias'))
        self.assertEqual(alias['entity_id'], entity['entity_id'])

        similar = self.match(name[:-1])
        self.assertEqual((similar['status'], similar['reason']), ('needs_review', 'similar'))
        self.assertIsNone(similar['entity_id'])
        self.assertIn(entity['entity_id'], [item['entity_id'] for item in similar['candidates']])

        unknown_name = 'unrelated report name ' + uuid.uuid4().hex
        unknown = self.match(unknown_name)
        self.assertEqual((unknown['status'], unknown['reason']), ('needs_review', 'unknown'))
        self.assertEqual(unknown['raw_name'], unknown_name)
        self.assertEqual(unknown['candidates'], [])

    def test_subobject_alias_survives_hierarchy_transformations(self):
        parent = self.create_entity('Word parent ' + uuid.uuid4().hex)
        child = self.create_entity('Word child ' + uuid.uuid4().hex, parent['entity_id'])
        alias_name = 'Word child alias ' + uuid.uuid4().hex
        status, _ = self.client.request('POST', '/aliases', {
            'entity_id': child['entity_id'],
            'source_value': alias_name,
        })
        self.assertEqual(status, 201)

        match = self.match(alias_name)
        self.assertEqual((match['entity_id'], match['entity']['kind']), (
            child['entity_id'], 'subobject'
        ))
        self.assertEqual(match['entity']['parent_entity_id'], parent['entity_id'])

        status, detached = self.client.request(
            'PATCH', f'/{child["entity_id"]}/hierarchy', {
                'parent_entity_id': None,
                'version': child['version'],
                'confirmed': True,
            }
        )
        self.assertEqual(status, 200, detached)
        standalone = self.match(alias_name)
        self.assertEqual((standalone['entity_id'], standalone['entity']['kind']), (
            child['entity_id'], 'object'
        ))

        status, reattached = self.client.request(
            'PATCH', f'/{child["entity_id"]}/hierarchy', {
                'parent_entity_id': parent['entity_id'],
                'version': detached['item']['version'],
                'confirmed': True,
            }
        )
        self.assertEqual(status, 200, reattached)
        restored = self.match(alias_name)
        self.assertEqual((restored['entity_id'], restored['entity']['kind']), (
            child['entity_id'], 'subobject'
        ))

    def test_ambiguous_names_are_never_selected(self):
        parent1 = self.create_entity('Word branch one ' + uuid.uuid4().hex)
        parent2 = self.create_entity('Word branch two ' + uuid.uuid4().hex)
        repeated_name = 'Repeated report name ' + uuid.uuid4().hex
        first = self.create_entity(repeated_name, parent1['entity_id'])
        second = self.create_entity(repeated_name, parent2['entity_id'])
        result = self.match(repeated_name)
        self.assertEqual((result['status'], result['reason']), ('needs_review', 'ambiguous'))
        self.assertIsNone(result['entity_id'])
        self.assertEqual(
            {item['entity_id'] for item in result['candidates']},
            {first['entity_id'], second['entity_id']},
        )

        other = self.create_entity('Word alias collision target ' + uuid.uuid4().hex)
        status, created = self.client.request('POST', '/aliases', {
            'entity_id': other['entity_id'],
            'source_value': first['name'],
        })
        self.assertEqual(status, 201, created)
        collision = self.match(first['name'])
        self.assertEqual(collision['reason'], 'ambiguous')
        self.assertIsNone(collision['entity_id'])

    def test_archived_entities_require_review_and_expose_candidates(self):
        entity = self.create_entity('Word archived ' + uuid.uuid4().hex)
        status, archived = self.client.request(
            'POST', f'/{entity["entity_id"]}/archive', {
                'version': entity['version'],
            }
        )
        self.assertEqual(status, 200, archived)
        result = self.match(entity['name'])
        self.assertEqual(
            (result['status'], result['reason']),
            ('needs_review', 'unavailable_exact_match'),
        )
        self.assertIsNone(result['entity_id'])
        self.assertFalse(result['candidates'][0]['available'])
        self.assertTrue(result['candidates'][0]['is_archived'])

    def test_archived_parent_makes_child_unavailable_for_auto_match(self):
        parent = self.create_entity('Word archived parent ' + uuid.uuid4().hex)
        child = self.create_entity('Word child of archived parent ' + uuid.uuid4().hex,
                                   parent['entity_id'])
        status, archived = self.client.request(
            'POST', f'/{parent["entity_id"]}/archive', {
                'version': parent['version'],
            }
        )
        self.assertEqual(status, 200, archived)
        result = self.match(child['name'])
        self.assertEqual(result['reason'], 'unavailable_exact_match')
        self.assertFalse(result['candidates'][0]['available'])
        self.assertTrue(result['candidates'][0]['effectively_archived'])

    def test_wrong_profile_database_schema_and_connection_are_rejected(self):
        cases = (
            ({'CONSTRUCTION_MODEL': 'legacy'}, 403),
            ({'CLEAN_START_DB_PROFILE': 'production'}, 403),
            ({'CLEAN_START_DB_NAME': 'ai_excel_agent'}, 403),
            ({'CLEAN_START_DB_SCHEMA': 'private'}, 403),
        )
        for overrides, expected_status in cases:
            with self.subTest(overrides=overrides), patch.dict(os.environ, overrides):
                status, _ = self.client.request(
                    'POST', '/word-report-match', {'object_name': 'not important'}
                )
                self.assertEqual(status, expected_status)

        with patch('app.api.clean_construction.psycopg.connect',
                   side_effect=psycopg.OperationalError('simulated connection failure')):
            status, response = self.client.request(
                'POST', '/word-report-match', {'object_name': 'not important'}
            )
        self.assertEqual(status, 503, response)

    def test_word_parser_and_legacy_matcher_remain_separate(self):
        parser_source = (ROOT / 'app' / 'parsers' / 'word_parser.py').read_text(
            encoding='utf-8'
        )
        self.assertIn('object_match = match_object(object_name)', parser_source)
        self.assertNotIn('clean_construction_matcher', parser_source)
