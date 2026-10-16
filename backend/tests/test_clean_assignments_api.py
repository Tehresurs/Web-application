"""Clean-start employee assignment API integration checks on an isolated clone."""
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import psycopg
import test_clean_construction_api as clean_api

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class CleanAssignmentsAPI(unittest.TestCase):
    fresh = False
    drop_copy = classmethod(clean_api.CleanAPI.drop_copy.__func__)
    setUpClass = classmethod(clean_api.CleanAPI.setUpClass.__func__)
    stop_server = classmethod(clean_api.CleanAPI.stop_server.__func__)

    def create_entity(self, name, parent_entity_id=None):
        response = self.client.post('', json={'name': name, 'parent_entity_id': parent_entity_id})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()['item']

    def test_entity_only_assignment_crud_and_hierarchy_roundtrip(self):
        employees = self.client.get('/employees?archive=all').json()['items']
        po_types = self.client.get('/po-types').json()['items']
        categories = self.client.get('/categories').json()['items']
        self.assertTrue(employees)
        self.assertGreaterEqual(len(po_types), 2)
        self.assertGreaterEqual(len(categories), 1)
        employee_id = employees[0]['id']
        root = self.create_entity('Assignment parent')
        child = self.create_entity('Assignment child', root['entity_id'])
        route = f'/employees/{employee_id}/assignments'

        created = self.client.post(route, json={
            'entity_id': child['entity_id'], 'po_id': po_types[0]['id'], 'category_id': categories[0]['id']
        })
        self.assertEqual(created.status_code, 201, created.text)
        item = created.json()['item']
        assignment_id = item['id']
        self.assertEqual(item['entity_id'], child['entity_id'])
        self.assertEqual(item['parent_entity_id'], root['entity_id'])
        self.assertEqual(item['object_name'], child['name'])
        self.assertFalse({'object_id', 'subobject_id', 'legacy_object_id', 'legacy_subobject_id'} & item.keys())

        read = self.client.get(route)
        self.assertEqual(read.status_code, 200, read.text)
        self.assertEqual(read.json()['objects_count'], 1)
        self.assertEqual(read.json()['items'][0]['id'], assignment_id)

        duplicate = self.client.post(route, json={
            'entity_id': child['entity_id'], 'po_id': po_types[0]['id'], 'category_id': categories[0]['id']
        })
        self.assertEqual(duplicate.status_code, 400)

        edited = self.client.patch(f'{route}/{assignment_id}', json={
            'entity_id': child['entity_id'], 'po_id': po_types[1]['id'], 'category_id': categories[0]['id']
        })
        self.assertEqual(edited.status_code, 200, edited.text)
        self.assertEqual(edited.json()['item']['po_id'], po_types[1]['id'])

        standalone = self.client.patch(f'/{child["entity_id"]}/hierarchy', json={
            'version': child['version'], 'parent_entity_id': None, 'confirmed': True
        })
        self.assertEqual(standalone.status_code, 200, standalone.text)
        child = standalone.json()['item']
        self.assertEqual(self.client.get(route).json()['items'][0]['entity_id'], child['entity_id'])
        self.assertIsNone(self.client.get(route).json()['items'][0]['parent_entity_id'])

        promoted = self.client.patch(f'/{child["entity_id"]}/hierarchy', json={
            'version': child['version'], 'parent_entity_id': root['entity_id'], 'confirmed': True
        })
        self.assertEqual(promoted.status_code, 200, promoted.text)
        self.assertEqual(self.client.get(route).json()['items'][0]['parent_entity_id'], root['entity_id'])
        with psycopg.connect(**self.params, dbname=self.database) as conn:
            stored = conn.execute(
                'SELECT entity_id,object_id FROM public.employee_assignments WHERE id=%s', (assignment_id,)
            ).fetchone()
            self.assertEqual(stored, (child['entity_id'], None))

        deleted = self.client.delete(f'{route}/{assignment_id}')
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertTrue(deleted.json()['deleted'])
        self.assertEqual(self.client.get(route).json()['items'], [])
        self.assertEqual(self.client.get(route).json()['objects_count'], 0)

    def test_reject_invalid_references_and_legacy_ids(self):
        employees = self.client.get('/employees?archive=all').json()['items']
        po = self.client.get('/po-types').json()['items'][0]['id']
        category = self.client.get('/categories').json()['items'][0]['id']
        entity = self.create_entity('Assignment validation')
        route = f'/employees/{employees[0]["id"]}/assignments'
        valid = {'entity_id': entity['entity_id'], 'po_id': po, 'category_id': category}

        self.assertEqual(self.client.post('/employees/9223372036854775807/assignments', json=valid).status_code, 400)
        self.assertEqual(self.client.post(route, json={**valid, 'po_id': 9223372036854775807}).status_code, 400)
        self.assertEqual(self.client.post(route, json={**valid, 'category_id': 9223372036854775807}).status_code, 400)
        self.assertEqual(self.client.post(route, json={**valid, 'entity_id': 9223372036854775807}).status_code, 400)
        self.assertEqual(self.client.post(route, json={**valid, 'object_id': 1}).status_code, 422)
        self.assertEqual(self.client.post(route, json={**valid, 'period_start': '2026-10-01'}).status_code, 422)

        archived = self.client.post(f'/{entity["entity_id"]}/archive', json={'version': entity['version']})
        self.assertEqual(archived.status_code, 200, archived.text)
        rejected = self.client.post(route, json=valid)
        self.assertEqual(rejected.status_code, 400, rejected.text)
        self.assertEqual(self.client.get(route).json()['items'], [])

    def test_rejects_a_mixed_database_source_before_write(self):
        employees = self.client.get('/employees?archive=all').json()['items']
        po = self.client.get('/po-types').json()['items'][0]['id']
        category = self.client.get('/categories').json()['items'][0]['id']
        entity = self.create_entity('Assignment source guard')
        other_database = 'ai_excel_agent_test_categories_0123456789ab'
        original_connect = __import__('psycopg').connect

        def redirect_to_current_isolated_database(**kwargs):
            kwargs['dbname'] = self.database
            return original_connect(**kwargs)

        route = f'/employees/{employees[0]["id"]}/assignments'
        with patch.dict(os.environ, {'CLEAN_START_DB_NAME': other_database}):
            with patch('app.api.clean_construction.psycopg.connect',
                       side_effect=redirect_to_current_isolated_database):
                response = self.client.post(route, json={
                    'entity_id': entity['entity_id'], 'po_id': po, 'category_id': category
                })
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(self.client.get(route).json()['items'], [])

    def test_clean_start_browser_assignment_flow(self):
        result = subprocess.run(
            ['node', str(Path(__file__).parent / 'browser/clean_assignments.cjs'),
             f'http://127.0.0.1:{self.port}'],
            capture_output=True, text=True, timeout=90,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Clean-start assignment flow passed', result.stdout)


if __name__ == '__main__':
    unittest.main(verbosity=2, failfast=True)
