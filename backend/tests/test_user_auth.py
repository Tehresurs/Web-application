import os
if os.environ.get('AUTH_ISOLATED_WORKER') != '1':
    raise RuntimeError('Use backend/scripts/run_auth_isolated.py; legacy DB fixtures are disabled')
import asyncio,json,os,unittest,uuid
from pathlib import Path
from unittest.mock import patch
import psycopg
from psycopg import sql
from fastapi import FastAPI
from app.services.user_auth import AuthService,AuthDenied,RateLimited
from app.api import user_auth as api

SCHEMA='test_construction_identity_stage46'
DB='auth_stage2_'+uuid.uuid4().hex

def connect(db,auto=False):
    raise RuntimeError("Worker must supply restricted connection factory")
    return psycopg.connect(host=os.getenv('DB_HOST'),port=os.getenv('DB_PORT'),user=os.getenv('DB_USER'),password=os.getenv('DB_PASSWORD'),dbname=db,autocommit=auto,options='-c search_path='+SCHEMA)

class IsolatedService(AuthService):
    def connect(self):
        c=connect(DB)
        assert c.info.dbname==DB and DB.startswith('auth_stage2_')
        return c

async def request(app,path,method='GET',data=None,cookie='',csrf='',origin='http://127.0.0.1',scheme='http',host='127.0.0.1'):
    headers=[(b'host',host.encode()),(b'content-type',b'application/json'),(b'origin',origin.encode())]
    if cookie:headers.append((b'cookie',cookie.encode()))
    if csrf:headers.append((b'x-csrf-token',csrf.encode()))
    raw=json.dumps(data).encode() if data is not None else b''
    out=[]
    async def receive():return {'type':'http.request','body':raw,'more_body':False}
    async def send(m):out.append(m)
    await app({'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','scheme':scheme,'method':method,'path':path,'raw_path':path.encode(),'query_string':b'','headers':headers,'client':('127.0.0.1',1234),'server':('127.0.0.1',80)},receive,send)
    start=next(m for m in out if m['type']=='http.response.start');body=b''.join(m.get('body',b'') for m in out if m['type']=='http.response.body')
    return start['status'],dict(start['headers']),json.loads(body)

class UserAuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raise RuntimeError("Legacy fixture disabled; restricted worker supplies lifecycle")
    @classmethod
    def tearDownClass(cls):
        raise RuntimeError("Legacy fixture disabled; restricted worker supplies lifecycle")
    def setUp(self):
        with connect(DB) as c:
            c.execute('TRUNCATE auth_security_events,auth_sessions,auth_user_roles,auth_users,employees CASCADE')
            c.execute('INSERT INTO employees VALUES (100,false)')
            self.uid=c.execute("INSERT INTO auth_users(login,password_hash,is_blocked,employee_id) VALUES ('test.user',%s,false,100) RETURNING id",(self.hash,)).fetchone()[0]
            c.execute("INSERT INTO auth_user_roles SELECT %s,id FROM auth_roles WHERE code='OFFICE_MANAGER'",(self.uid,))
        self.app=FastAPI();self.app.include_router(api.router)
        self.patch=patch.object(api,'service',return_value=self.s);self.patch.start();self.addCleanup(self.patch.stop)
    def call(self,*args,**kw):return asyncio.run(request(self.app,*args,**kw))
    def token(self):return self.s.login('test.user',self.password,'127.0.0.1')
    def test_correct_wrong_unknown_and_malformed_hash(self):
        self.assertEqual(self.s.current(self.token())['employee_id'],100)
        for login,pw in [('test.user','wrong'),('missing.user','wrong')]:
            with self.assertRaises(AuthDenied):self.s.login(login,pw,'x')
        with connect(DB) as c:c.execute("UPDATE auth_users SET password_hash='malformed'")
        with self.assertRaises(AuthDenied):self.s.login('test.user',self.password,'x')
    def test_blocked_and_archived_users(self):
        t=self.token()
        with connect(DB) as c:c.execute('UPDATE auth_users SET is_blocked=true')
        with self.assertRaises(AuthDenied):self.s.current(t)
        with self.assertRaises(AuthDenied):self.token()
        with connect(DB) as c:c.execute('UPDATE auth_users SET is_blocked=false');c.execute('UPDATE employees SET is_archived=true')
        with self.assertRaises(AuthDenied):self.s.current(t)
    def test_expiry_revocation_credential_version(self):
        t=self.token()
        with connect(DB) as c:c.execute("UPDATE auth_sessions SET created_at=now()-interval '2 hours',last_seen_at=now()-interval '2 hours',expires_at=now()-interval '1 hour'")
        with self.assertRaises(AuthDenied):self.s.current(t)
        t=self.token();self.s.revoke_all(self.uid)
        with self.assertRaises(AuthDenied):self.s.current(t)
        t=self.token()
        with connect(DB) as c:c.execute('UPDATE auth_users SET credential_version=credential_version+1')
        with self.assertRaises(AuthDenied):self.s.current(t)
    def test_logout_csrf_and_cookie(self):
        status,headers,body=self.call('/api/auth/login','POST',{'login':'test.user','password':self.password})
        self.assertEqual(status,200);cookie=headers[b'set-cookie'].decode();self.assertIn('HttpOnly',cookie);self.assertIn('SameSite=strict',cookie)
        cookie=cookie.split(';')[0]
        self.assertEqual(self.call('/api/auth/logout','POST',cookie=cookie)[0],403)
        self.assertEqual(self.call('/api/auth/logout','POST',cookie=cookie,csrf=body['csrf_token'],origin='http://evil.example')[0],403)
        self.assertEqual(self.call('/api/auth/logout','POST',cookie=cookie,csrf=body['csrf_token'])[0],200)
        self.assertEqual(self.call('/api/auth/me',cookie=cookie)[0],401)
    def test_bruteforce_persistent_across_instances(self):
        for i in range(10):
            with self.assertRaises(AuthDenied):self.s.login('test.user','wrong','same-peer')
        with self.assertRaises(RateLimited):IsolatedService().login('test.user',self.password,'different-peer')
        self.assertEqual(self.call('/api/auth/login','POST',{'login':'test.user','password':self.password})[0],429)
    def test_permissions_and_role_employee_spoof(self):
        status,_,_=self.call('/api/auth/login','POST',{'login':'test.user','password':self.password,'role':'SYSTEM_TECHNICIAN','employee_id':999})
        self.assertEqual(status,400)
        t=self.token();u=self.s.current(t)
        self.assertEqual(u['roles'],['OFFICE_MANAGER']);self.assertEqual(set(u['permissions']),{'data.read','excel.export'})
        with connect(DB) as c:c.execute('DELETE FROM auth_user_roles')
        self.assertEqual(self.s.current(t)['permissions'],[])
    def test_token_storage_and_no_secret_responses_events(self):
        t=self.token()
        with connect(DB) as c:
            stored=c.execute('SELECT token_hash FROM auth_sessions').fetchone()[0];events=c.execute('SELECT details::text FROM auth_security_events').fetchall()
        self.assertNotEqual(stored,t);self.assertEqual(stored,self.s.digest(t));self.assertNotIn(t,str(events));self.assertNotIn(self.password,str(events))
        status,headers,body=self.call('/api/auth/me',cookie=api.COOKIE+'='+t)
        self.assertEqual(status,200);self.assertNotIn(self.password,str(body));self.assertNotIn(t,str(body));self.assertNotIn('password_hash',str(body));self.assertEqual(headers[b'cache-control'],b'no-store')
        status,_,body=self.call('/api/auth/login','POST',{'login':[],'password':self.password})
        self.assertEqual(status,400);self.assertNotIn(self.password,str(body))
    def test_logs_do_not_contain_credentials(self):
        import logging,io
        stream=io.StringIO();handler=logging.StreamHandler(stream);root=logging.getLogger();root.addHandler(handler)
        try:
            self.call('/api/auth/login','POST',{'login':'test.user','password':self.password})
            self.call('/api/auth/login','POST',{'login':'test.user','password':'wrong-secret-value'})
        finally:root.removeHandler(handler)
        self.assertNotIn(self.password,stream.getvalue());self.assertNotIn('wrong-secret-value',stream.getvalue());self.assertNotIn(self.hash,stream.getvalue())
    def test_unique_tokens_and_csrf_session_binding(self):
        a=self.token();b=self.token();self.assertNotEqual(a,b)
        self.s.verify_csrf(a,self.s.csrf(a))
        with self.assertRaises(AuthDenied):self.s.verify_csrf(a,self.s.csrf(b))
    def test_service_refuses_wrong_database_and_closes_connection(self):
        from unittest.mock import Mock
        c=Mock();c.execute.return_value.fetchone.return_value=('wrong','public')
        plain=AuthService(connection_factory=lambda:c)
        with self.assertRaises(RuntimeError):plain.connect()
        c.close.assert_called_once()
    def test_https_origin_no_session_and_failure_closed(self):
        self.assertEqual(self.call('/api/auth/me')[0],401)
        self.assertEqual(self.call('/api/auth/login','POST',{'login':'test.user','password':self.password},origin='null')[0],403)
        self.assertEqual(self.call('/api/auth/me',host='public.example')[0],403)
        status,headers,_=self.call('/api/auth/login','POST',{'login':'test.user','password':self.password},scheme='https',host='public.example',origin='https://public.example')
        self.assertEqual(status,200);self.assertIn('Secure',headers[b'set-cookie'].decode())
        with patch.object(api,'service',side_effect=RuntimeError('secret database error')):
            status,_,body=self.call('/api/auth/me')
            self.assertEqual(status,503);self.assertNotIn('secret',str(body));self.assertNotIn('LEADER',str(body))

if __name__=='__main__':unittest.main()
