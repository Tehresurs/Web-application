"""Existing API lifecycle, designated test schema, all row changes rolled back."""
import os
import sys
from pathlib import Path
from contextlib import contextmanager
import unittest
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.database.db import get_connection
from app.repositories.construction_identity import resolve
from test_daily_control import http_request


class CatalogActions(unittest.TestCase):
    def test_entity_lifecycle_and_legacy_contract(self):
        with patch.dict(os.environ,{'APP_DB_PROFILE':'test','DB_NAME':'ai_excel_agent_test',
            'DB_SCHEMA':'test_construction_identity_stage46','APP_TEST_ALLOWED_DB_SCHEMAS':'test_construction_identity_stage46'}):
            conn=get_connection()
            self.addCleanup(conn.close)
            self.addCleanup(conn.rollback)
            self.assertEqual(conn.execute('SELECT current_database(),current_schema()').fetchone(),
                             ('ai_excel_agent_test','test_construction_identity_stage46'))
            conn.execute('SELECT pg_advisory_xact_lock(20261013,24)')
            history=conn.execute('SELECT to_jsonb(r) FROM daily_control_results r ORDER BY id').fetchall()
            @contextmanager
            def connection():
                with conn.transaction():yield conn
            from contextlib import ExitStack
            with ExitStack() as stack:
                for module in ('app.repositories.objects','app.repositories.subobjects','app.api.construction_identity','app.repositories.object_archive'):
                    stack.enter_context(patch(module+'.get_connection',connection))
                def request(method,path,payload=None,entity=False):
                    status,body=http_request(method,path,payload,query='id_type=entity' if entity else '')
                    self.assertEqual(status,200,body)
                    return body.get('item',body.get('object',body))
                name='Entity actions '+uuid4().hex
                root=request('POST','/api/objects',{'name':name})
                parent=request('POST','/api/objects',{'name':name+' parent'})
                eid=conn.execute('SELECT id FROM construction_entities WHERE legacy_object_id=%s',(root['id'],)).fetchone()[0]
                pid=conn.execute('SELECT id FROM construction_entities WHERE legacy_object_id=%s',(parent['id'],)).fetchone()[0]
                initial=resolve(conn,entity_id=eid)
                def move(target,id=eid):
                    return request('PATCH',f'/api/construction-entities/{id}/hierarchy',
                        {'parent_entity_id':target,'version':resolve(conn,entity_id=id)['version'],'confirmed':True})
                request('PATCH',f'/api/objects/{eid}',{'name':name+' edit'},True)
                move(pid)
                rows=http_request('GET','/api/subobjects',query='include_inactive=true')[1]['items']
                self.assertIsNone(next(r for r in rows if r['entity_id']==eid)['id'])
                request('PATCH',f'/api/subobjects/{eid}',{'name':name+' child edit','is_active':True},True)
                self.assertTrue(request('POST',f'/api/subobjects/{eid}/archive',entity=True)['is_archived'])
                self.assertFalse(request('POST',f'/api/subobjects/{eid}/restore',entity=True)['is_archived'])
                move(None)
                # Also cover a former legacy child displayed as an object with id=null.
                child=request('POST','/api/subobjects',{'name':name+' native child','parent_entity_id':pid})
                cid=child['entity_id']
                move(None,cid)
                result=request('PATCH',f'/api/objects/{cid}',{'name':name+' promoted child'},True)
                self.assertIsNone(result['id'])
                request('POST',f'/api/objects/{cid}/archive',entity=True)
                request('POST',f'/api/objects/{cid}/restore',entity=True)
                move(pid,cid)
                old=request('PATCH',f'/api/objects/{root["id"]}',{'name':name+' legacy edit'})
                self.assertEqual(old['id'],root['id'])
                after=resolve(conn,entity_id=eid)
                for key in ('entity_id','legacy_object_id','legacy_subobject_id'):
                    self.assertEqual(after[key],initial[key])
                self.assertEqual(conn.execute('SELECT to_jsonb(r) FROM daily_control_results r ORDER BY id').fetchall(),history)


if __name__=='__main__':unittest.main(verbosity=2)
