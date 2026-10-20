import asyncio
import base64
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from app.demo_access import DemoAccess,make_user,allowed_read
from app.access_context import read_only_request
from app.services.matrix_dk import role


async def request(app,path='/',method='GET',authorization=None,extra=()):
    target,_,query=path.partition('?')
    headers=[(b'host',b'localhost'),*extra]
    if authorization:headers.append((b'authorization',authorization.encode()))
    scope=dict(type='http',asgi={'version':'3.0'},http_version='1.1',method=method,
      scheme='http',path=target,raw_path=target.encode(),query_string=query.encode(),root_path='',
      server=('127.0.0.1',18001),client=('127.0.0.1',12345),headers=headers)
    messages=[]
    async def receive():return {'type':'http.request','body':b'','more_body':False}
    async def send(message):messages.append(message)
    await app(scope,receive,send)
    start=next(m for m in messages if m['type']=='http.response.start')
    body=b''.join(m.get('body',b'') for m in messages if m['type']=='http.response.body')
    return start['status'],dict(start['headers']),body


class DemoAccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.user=make_user('long-test-password-for-demo')
        cls.authorization='Basic '+base64.b64encode(b'viewer@example.test:long-test-password-for-demo').decode()
    def setUp(self):
        temp=TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.path=Path(temp.name)/'users.json';self.save({'viewer@example.test':self.user})
        self.calls=[]
        async def target(scope,receive,send):
            from starlette.responses import JSONResponse,HTMLResponse
            self.calls.append((scope['path'],read_only_request.get(),role()))
            response=HTMLResponse('<html><head></head><body>demo</body></html>') if scope['path']=='/' else JSONResponse({'read_only':read_only_request.get()})
            await response(scope,receive,send)
        self.app=DemoAccess(target,self.path,{'localhost'})
    def save(self,users):self.path.write_text(json.dumps({'users':users}),encoding='utf-8')
    def call(self,*args,**kwargs):return asyncio.run(request(self.app,*args,**kwargs))
    def test_anonymous_and_spoofed_headers_never_reach_application(self):
        for path in ['/','/api/employees','/static/js/processing.js']:
            status,headers,_=self.call(path,extra=[(b'x-role',b'LEADER'),(b'cf-access-authenticated-user-email',b'viewer@example.test')])
            self.assertEqual(status,401);self.assertIn(b'www-authenticate',headers)
        self.assertEqual(self.calls,[])
    def test_all_non_read_methods_blocked_even_with_valid_credentials(self):
        for method in ['POST','PUT','PATCH','DELETE','OPTIONS','TRACE','CONNECT']:
            for path in ['/api/employees','/api/rail-tickets/1/confirm','/api/vou/reports','/api/luvr/month/form','/api/process-folder']:
                self.assertEqual(self.call(path,method,self.authorization)[0],403,(method,path))
        self.assertEqual(self.calls,[])
    def test_unsafe_and_future_get_endpoints_blocked(self):
        for path in ['/api/select-folder','/api/check-folder','/api/luvr/month/export','/api/deployment/report/export',
                     '/api/clean-construction-entities/workspace','/docs','/openapi.json','/api/future-write-route',
                     '/static/../.env','/static/secret.py']:
            self.assertEqual(self.call(path,authorization=self.authorization)[0],403,path)
        self.assertEqual(self.calls,[])
    def test_viewer_context_is_applied_and_reset_without_affecting_local_role(self):
        original=role()
        self.assertEqual(self.call('/api/production-matrix',authorization=self.authorization)[0],200)
        self.assertEqual(self.calls[0][1:],(True,'READ_ONLY'))
        self.assertFalse(read_only_request.get());self.assertEqual(role(),original)
    def test_root_has_protected_ui_and_no_store_headers(self):
        status,headers,body=self.call(authorization=self.authorization)
        self.assertEqual(status,200);self.assertIn(b'demo_viewer.js',body)
        self.assertEqual(headers[b'cache-control'],b'no-store')
        self.assertIn(b"frame-ancestors 'none'",headers[b'content-security-policy'])
    def test_account_revocation_immediately_invalidates_cached_password(self):
        self.assertEqual(self.call('/api/employees',authorization=self.authorization)[0],200)
        self.save({})
        self.assertEqual(self.call('/api/employees',authorization=self.authorization)[0],401)
    def test_role_headers_do_not_grant_write(self):
        self.assertEqual(self.call('/api/employees','POST',self.authorization,[(b'x-role',b'LEADER')])[0],403)
    def test_missing_or_malformed_user_store_fails_closed(self):
        self.path.write_text('broken',encoding='utf-8')
        self.assertEqual(self.call('/api/employees',authorization=self.authorization)[0],401)
    def test_other_hosts_rejected(self):
        self.assertEqual(self.call(authorization=self.authorization,extra=[(b'host',b'evil.test')])[0],400)
    def test_read_filters_and_saved_file_download_allowed(self):
        for path in ['/api/deployment/analysis','/api/employees/1/luvr/calendar','/api/rail-tickets/1',
                     '/api/vou/reports/'+'1'*32+'/file']:
            self.assertTrue(allowed_read(path),path)
    def test_password_minimum_and_role_are_fixed(self):
        with self.assertRaises(ValueError):make_user('short')
        self.assertEqual(self.user['role'],'READ_ONLY')

    def test_history_lock_is_preserved_for_local_and_omitted_for_viewer(self):
        from unittest.mock import Mock
        from app.repositories.luvr_history import _employee
        cursor=Mock();cursor.fetchone.return_value=(1,)
        _employee(cursor,1)
        self.assertIn('FOR KEY SHARE',cursor.execute.call_args.args[0])
        token=read_only_request.set(True)
        try:_employee(cursor,1)
        finally:read_only_request.reset(token)
        self.assertNotIn('FOR KEY SHARE',cursor.execute.call_args.args[0])
