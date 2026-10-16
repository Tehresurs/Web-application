"""Clean-start Word-report parsing against a disposable database copy."""
import json
import os
from io import BytesIO
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
from docx import Document
from dotenv import load_dotenv
from fastapi import FastAPI

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api.clean_construction import router
from app.parsers.word_parser import looks_like_full_name

SOURCE_DATABASE = 'ai_excel_agent_stage4151_20261019_86bf41ed'


class APIClient:
    def __init__(self, base_url):
        self.base_url = base_url

    def request(self, method, path, payload=None, content_type='application/json'):
        if payload is None:
            body = None
        elif isinstance(payload, bytes):
            body = payload
        else:
            body = json.dumps(payload).encode()
        request = urllib.request.Request(
            self.base_url + path,
            method=method,
            data=body,
            headers={'Content-Type': content_type},
        )
        try:
            response = urllib.request.urlopen(request, timeout=15)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.code, json.loads(response.read().decode())

    def upload_docx(self, content, filename='report.docx'):
        boundary = '----WordReport' + uuid.uuid4().hex
        body = (
            f'--{boundary}\r\n'
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            'Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document\r\n\r\n'
        ).encode() + content + f'\r\n--{boundary}--\r\n'.encode()
        return self.request(
            'POST',
            '/word-report/parse',
            body,
            f'multipart/form-data; boundary={boundary}',
        )

    def get_text(self, path):
        request = urllib.request.Request(self.base_url + path, method='GET')
        try:
            response = urllib.request.urlopen(request, timeout=15)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.code, response.read().decode()


def make_report_docx(object_name, employee_name, general_contractor,
                     subcontractor='—'):
    document = Document()
    table = document.add_table(rows=0, cols=4)
    rows = (
        ('Дата', '14.10.2026', 'Направление контроля', 'Качество'),
        ('Объект', object_name, '', ''),
        ('Генподрядчик', general_contractor, '', ''),
        ('Субподрядчик', subcontractor, '', ''),
        (employee_name, '', '', ''),
        ('Подпись', '', '', ''),
    )
    for row_values in rows:
        cells = table.add_row().cells
        for cell, value in zip(cells, row_values):
            cell.text = value
    output = BytesIO()
    document.save(output)
    return output.getvalue()


class TestCleanWordReportAPI(unittest.TestCase):
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
                "SELECT to_regclass('public.daily_control_results')"
            ).fetchone()[0] is None:
                raise AssertionError('Clean-start source has no daily_control_results table')
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

        with psycopg.connect(**cls.params, dbname=cls.database) as conn:
            employees = conn.execute(
                '''SELECT full_name FROM public.employees
                   WHERE NOT is_archived ORDER BY id'''
            ).fetchall()
            cls.employee_name = next(
                (row[0] for row in employees if looks_like_full_name(row[0])),
                None,
            )
            organization = conn.execute(
                'SELECT name FROM public.po_types ORDER BY name,id LIMIT 1'
            ).fetchone()
            cls.general_contractor = organization[0] if organization else None
        if not cls.employee_name:
            raise AssertionError('No active employee with a parser-valid full name in test DB')
        if not cls.general_contractor:
            raise AssertionError('No organization is available in the clean-start test DB')

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

    def counts(self):
        with psycopg.connect(**self.params, dbname=self.database) as conn:
            return {
                table: conn.execute(f'SELECT count(*) FROM public.{table}').fetchone()[0]
                for table in (
                    'construction_entities',
                    'construction_entity_aliases',
                    'daily_control_results',
                )
            }

    def parse(self, object_name, employee_name=None, subcontractor='—',
              filename='report.docx'):
        return self.client.upload_docx(
            make_report_docx(
                object_name,
                employee_name or self.employee_name,
                self.general_contractor,
                subcontractor,
            ),
            filename,
        )

    def test_exact_subobject_report_uses_entity_id_and_writes_nothing(self):
        parent = self.create_entity('Word report parent ' + uuid.uuid4().hex)
        child = self.create_entity(
            'Word report subobject ' + uuid.uuid4().hex,
            parent['entity_id'],
        )
        before = self.counts()
        status, result = self.parse(
            child['name'],
            subcontractor=self.general_contractor,
        )
        self.assertEqual(status, 200, result)
        report = result['intermediate_report']
        self.assertEqual(report['status'], 'ready')
        self.assertEqual(report['entity_id'], child['entity_id'])
        self.assertEqual(report['current_hierarchy']['parent_entity_id'], parent['entity_id'])
        self.assertEqual(report['business_data']['object_match']['status'], 'exact')
        self.assertEqual(report['full_name'], self.employee_name)
        self.assertEqual(report['employee_id'] > 0, True)
        self.assertEqual(report['report_date'], '2026-10-14')
        self.assertEqual(report['business_data']['inspector']['source']['row'], 4)
        self.assertEqual(
            report['business_data']['general_contractor_match']['status'],
            'exact',
        )
        self.assertEqual(report['subcontractor'], self.general_contractor)
        self.assertEqual(
            report['business_data']['subcontractor_match']['status'],
            'exact',
        )
        self.assertEqual(result['errors'], [])
        self.assertEqual(result['persistence'], {
            'daily_facts_written': False,
            'aliases_written': False,
        })
        self.assertEqual(self.counts(), before)

    def test_alias_match_is_explicit_and_resolves_the_same_entity(self):
        entity = self.create_entity('Word alias report target ' + uuid.uuid4().hex)
        alias = 'Word report alternative ' + uuid.uuid4().hex
        status, response = self.client.request('POST', '/aliases', {
            'entity_id': entity['entity_id'],
            'source_value': alias,
        })
        self.assertEqual(status, 201, response)
        before = self.counts()
        status, result = self.parse(alias)
        self.assertEqual(status, 200, result)
        report = result['intermediate_report']
        self.assertEqual(report['entity_id'], entity['entity_id'])
        self.assertEqual(report['object_name'], alias)
        self.assertEqual(report['business_data']['object_match']['status'], 'alias')
        self.assertEqual(report['status'], 'ready')
        self.assertEqual(self.counts(), before)

    def test_unknown_object_and_typo_in_engineer_name_need_review(self):
        employee_words = self.employee_name.split()
        typo = employee_words[0][:-1] + ('я' if employee_words[0][-1].lower() != 'я' else 'а')
        typo_name = ' '.join([typo, *employee_words[1:]])
        unknown = 'Unknown Word entity ' + uuid.uuid4().hex
        status, result = self.parse(unknown, employee_name=typo_name)
        self.assertEqual(status, 200, result)
        report = result['intermediate_report']
        self.assertEqual(report['status'], 'needs_review')
        self.assertIsNone(report['entity_id'])
        self.assertEqual(report['object_name'], unknown)
        self.assertEqual(report['business_data']['object_match']['status'], 'unknown')
        self.assertEqual(report['business_data']['employee_match']['status'], 'similar')
        self.assertIsNone(report['employee_id'])
        self.assertTrue(any(
            error['field'] == 'employee' and error['requires_approval']
            for error in report['errors']
        ))

    def test_similar_and_ambiguous_objects_are_not_auto_selected(self):
        similar_entity = self.create_entity(
            'Word near match ' + uuid.uuid4().hex
        )
        similar_status, similar_result = self.parse(similar_entity['name'][:-1])
        self.assertEqual(similar_status, 200, similar_result)
        similar_report = similar_result['intermediate_report']
        self.assertEqual(similar_report['business_data']['object_match']['status'],
                         'similar')
        self.assertIsNone(similar_report['entity_id'])
        self.assertIn(
            similar_entity['entity_id'],
            [
                item['entity_id']
                for item in similar_report['business_data']['object_match']['candidates']
            ],
        )

        canonical = self.create_entity('Word collision ' + uuid.uuid4().hex)
        alias_target = self.create_entity('Word alias target ' + uuid.uuid4().hex)
        status, response = self.client.request('POST', '/aliases', {
            'entity_id': alias_target['entity_id'],
            'source_value': canonical['name'],
        })
        self.assertEqual(status, 201, response)
        ambiguous_status, ambiguous_result = self.parse(canonical['name'])
        self.assertEqual(ambiguous_status, 200, ambiguous_result)
        ambiguous_report = ambiguous_result['intermediate_report']
        self.assertEqual(
            ambiguous_report['business_data']['object_match']['status'],
            'ambiguous',
        )
        self.assertIsNone(ambiguous_report['entity_id'])
        self.assertEqual(
            {
                candidate['entity_id']
                for candidate in ambiguous_report['business_data']['object_match']['candidates']
            },
            {canonical['entity_id'], alias_target['entity_id']},
        )

    def test_invalid_inspector_name_uses_penultimate_left_cell_rule(self):
        status, result = self.parse('Missing object ' + uuid.uuid4().hex,
                                    employee_name='Фамилия Имя')
        self.assertEqual(status, 200, result)
        report = result['intermediate_report']
        inspector = report['business_data']['inspector']
        self.assertEqual(inspector['status'], 'invalid_name')
        self.assertEqual(inspector['source']['row'], 4)
        self.assertEqual(inspector['source']['cell'], 0)
        self.assertEqual(report['full_name'], 'Фамилия Имя')
        self.assertIsNone(report['employee_id'])
        self.assertEqual(report['status'], 'error')

    def test_upload_validation_and_bad_docx(self):
        status, response = self.client.upload_docx(b'not a document', 'bad.docx')
        self.assertEqual(status, 422, response)
        status, response = self.client.upload_docx(b'x', 'report.pdf')
        self.assertEqual(status, 415, response)
        status, response = self.client.upload_docx(b'')
        self.assertEqual(status, 400, response)

    def test_clean_start_profile_is_required_for_upload(self):
        content = make_report_docx(
            'object', self.employee_name, self.general_contractor
        )
        with patch.dict(os.environ, {'CLEAN_START_DB_NAME': 'ai_excel_agent'}):
            status, _ = self.client.upload_docx(content)
        self.assertEqual(status, 403)

    def test_parse_manual_correction_and_confirmation_is_non_persistent(self):
        entity = self.create_entity('Confirm report object ' + uuid.uuid4().hex)
        employee_words = self.employee_name.split()
        misspelled_name = ' '.join(
            [employee_words[0][:-1] + 'я', *employee_words[1:]]
        )
        original_object = 'Unmatched object from Word ' + uuid.uuid4().hex
        original_contractor = 'Unmatched contractor from Word ' + uuid.uuid4().hex
        source_content = make_report_docx(
            original_object,
            misspelled_name,
            original_contractor,
        )
        before = self.counts()
        status, parsed = self.client.upload_docx(source_content)
        self.assertEqual(status, 200, parsed)
        report = parsed['intermediate_report']
        self.assertEqual(report['entity_id'], None)
        self.assertIsNone(report['employee_id'])
        self.assertEqual(report['business_data']['object_match']['status'], 'unknown')
        self.assertEqual(report['business_data']['employee_match']['status'], 'similar')
        with psycopg.connect(**self.params, dbname=self.database) as conn:
            employee_id = conn.execute(
                'SELECT id FROM public.employees WHERE full_name=%s AND NOT is_archived',
                (self.employee_name,),
            ).fetchone()[0]
            general_contractor_id = conn.execute(
                'SELECT id FROM public.po_types WHERE name=%s',
                (self.general_contractor,),
            ).fetchone()[0]
        payload = {
            'confirmed': True,
            'report_date': report['report_date'],
            'source_full_name': misspelled_name,
            'employee_id': employee_id,
            'source_object_name': report['object_name'],
            'entity_id': entity['entity_id'],
            'source_general_contractor': report['general_contractor'],
            'general_contractor_id': general_contractor_id,
            'source_subcontractor': report['subcontractor'],
            'subcontractor_required': False,
            'subcontractor_id': None,
        }
        status, confirmed = self.client.request(
            'POST', '/word-report/confirm', payload
        )
        self.assertEqual(status, 200, confirmed)
        result = confirmed['confirmed_report']
        self.assertEqual(result['status'], 'confirmed_pending_save')
        self.assertEqual(result['construction_entity']['entity_id'], entity['entity_id'])
        self.assertEqual(result['construction_entity']['source_value'], original_object)
        self.assertEqual(result['employee']['employee_id'], employee_id)
        self.assertEqual(result['employee']['source_value'], misspelled_name)
        self.assertEqual(result['general_contractor']['source_value'], original_contractor)
        self.assertEqual(result['persistence'], {
            'daily_facts_written': False,
            'aliases_written': False,
            'other_records_written': False,
        })
        self.assertEqual(self.counts(), before)

    def test_confirmation_requires_acknowledgement_and_valid_live_references(self):
        entity = self.create_entity('Confirm validation entity ' + uuid.uuid4().hex)
        payload = {
            'confirmed': False,
            'report_date': '2026-10-14',
            'employee_id': 1,
            'entity_id': entity['entity_id'],
            'general_contractor_id': 1,
            'subcontractor_required': False,
        }
        status, response = self.client.request(
            'POST', '/word-report/confirm', payload
        )
        self.assertEqual(status, 409, response)

        with psycopg.connect(**self.params, dbname=self.database) as conn:
            employee_id = conn.execute(
                'SELECT id FROM public.employees WHERE NOT is_archived ORDER BY id LIMIT 1'
            ).fetchone()[0]
            organization_id = conn.execute(
                'SELECT id FROM public.po_types ORDER BY id LIMIT 1'
            ).fetchone()[0]
        payload.update({
            'confirmed': True,
            'employee_id': employee_id,
            'general_contractor_id': organization_id,
        })
        payload['entity_id'] = 9223372036854775807
        status, response = self.client.request(
            'POST', '/word-report/confirm', payload
        )
        self.assertEqual(status, 409, response)
        payload['entity_id'] = entity['entity_id']
        payload['source_subcontractor'] = 'Subcontractor from Word'
        status, response = self.client.request(
            'POST', '/word-report/confirm', payload
        )
        self.assertEqual(status, 422, response)
        payload['subcontractor_required'] = True
        status, response = self.client.request(
            'POST', '/word-report/confirm', payload
        )
        self.assertEqual(status, 422, response)

    def test_separate_clean_review_workspace_renders_only_its_own_controller(self):
        status, html = self.client.get_text('/word-report/workspace')
        self.assertEqual(status, 200)
        self.assertIn('Согласование Word-отчёта', html)
        self.assertIn('clean_word_review.js', html)
        self.assertNotIn('processing.js', html)

    def test_review_dictionaries_are_read_from_one_clean_start_endpoint(self):
        status, result = self.client.request(
            'GET', '/word-report/dictionaries'
        )
        self.assertEqual(status, 200, result)
        dictionaries = result['dictionaries']
        self.assertIn(self.employee_name, [item['full_name'] for item in dictionaries['employees']])
        self.assertIn(self.general_contractor, [item['name'] for item in dictionaries['organizations']])
        self.assertTrue(all(
            entity['is_active'] and not entity['is_archived']
            for entity in dictionaries['entities']
        ))
        self.assertTrue(all(
            {'entity_id', 'name', 'parent_entity_id'} <= entity.keys()
            for entity in dictionaries['entities']
        ))
        self.assertFalse(any(
            {'object_id', 'subobject_id', 'legacy_object_id'} & entity.keys()
            for entity in dictionaries['entities']
        ))
