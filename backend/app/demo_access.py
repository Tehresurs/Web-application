"""Separate, fail-closed, authenticated READ_ONLY entrance to the 8001 app.

No forwarding to the unrestricted HTTP port. Credentials/role headers supplied
by clients or proxies are never interpreted as user roles.
"""
import base64
import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets
from threading import Lock
import time
from starlette.responses import JSONResponse, Response
from app.access_context import read_only_request

ITERATIONS=800_000
SAFE_EXACT=frozenset(('/', '/api/object-categories','/api/po-types','/api/objects',
 '/api/positions','/api/employees','/api/crews','/api/subobjects','/api/value-aliases',
 '/api/construction-entities','/api/construction-entities/environment',
 '/api/daily-control-results','/api/daily-control-results/absence-rules',
 '/api/production-matrix','/api/production-matrix/capabilities',
 '/api/luvr/month','/api/luvr/month/settings','/api/luvr/month/header-snapshot',
 '/api/deployment/report','/api/deployment/analysis','/api/vou/settings','/api/vou/reports'))
SAFE_PATTERNS=tuple(re.compile(p) for p in (
 r'/api/employees/[1-9][0-9]*/(?:assignments|absences|production-assignments|production-matrix-overrides)',
 r'/api/employees/[1-9][0-9]*/luvr/(?:movements|sick-periods|duration-exceptions|day-overrides|calendar|calendar/day)',
 r'/api/(?:subobjects|value-aliases|rail-tickets)/[1-9][0-9]*',
 r'/api/daily-control-results/(?:facts|review-assignments)/[1-9][0-9]*',
 r'/api/vou/reports/[0-9a-f]{32}(?:/file)?',
))


def allowed_read(path):
    if any(part in path for part in ('..','%',chr(92),'//',chr(0))):return False
    path=path.rstrip('/') or '/'
    if path in SAFE_EXACT or path=='/api/rail-tickets':return True
    if any(p.fullmatch(path) for p in SAFE_PATTERNS):return True
    return path.startswith('/static/') and bool(re.fullmatch(r'/static/[A-Za-z0-9_/.-]+\.(?:js|css|png|svg|ico|jpg|jpeg|woff2?)',path))


def make_user(password):
    if len(password)<16:raise ValueError('Use at least 16 password characters')
    salt=secrets.token_bytes(24)
    return dict(role='READ_ONLY',salt=salt.hex(),iterations=ITERATIONS,
                password_hash=hashlib.pbkdf2_hmac('sha256',password.encode(),salt,ITERATIONS).hex())


class Users:
    def __init__(self,path):
        self.path=Path(path);self.lock=Lock();self.cache={};self.failures={};self.key=secrets.token_bytes(32)
    def verify(self,header,peer):
        now=time.monotonic()
        try:
            if len(header)>4096 or not header.startswith('Basic '):return None
            username,password=base64.b64decode(header[6:],validate=True).decode('utf-8').split(':',1)
            username=username.strip().casefold()
            raw=self.path.read_bytes();users=json.loads(raw)['users']
            user=users.get(username)
            signature=hmac.digest(self.key,raw+header.encode(),'sha256')
            with self.lock:
                if self.cache.get(signature,0)>now:return username
                fails=[t for t in self.failures.get(peer,[]) if t>now-900]
                if len(fails)>=20:return None
            valid=False
            if user and user.get('role')=='READ_ONLY' and 600_000<=user['iterations']<=2_000_000:
                actual=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(user['salt']),user['iterations']).hex()
                valid=hmac.compare_digest(actual,user['password_hash'])
            with self.lock:
                if valid:
                    self.cache={k:v for k,v in self.cache.items() if v>now}
                    if len(self.cache)>256:self.cache.clear()
                    self.cache[signature]=now+60
                    self.failures.pop(peer,None)
                else:self.failures[peer]=fails+[now]
            return username if valid else None
        except (OSError,ValueError,KeyError,TypeError):return None


class DemoAccess:
    def __init__(self,app,users_path,hosts):
        self.app=app;self.users=Users(users_path);self.hosts=frozenset(hosts)
        if not self.hosts:raise ValueError('Demo host allowlist is required')
    async def __call__(self,scope,receive,send):
        if scope['type']=='lifespan':return await self.app(scope,receive,send)
        if scope['type']=='websocket':return await send({'type':'websocket.close','code':1008})
        if scope['type']!='http':return
        headers={k.lower():v for k,v in scope.get('headers',[])}
        host=headers.get(b'host',b'').decode('latin1').split(':',1)[0].lower()
        if host not in self.hosts:
            return await Response('Host not allowed',400)(scope,receive,send)
        from starlette.concurrency import run_in_threadpool
        peer=(scope.get('client') or ('unknown',))[0]
        username=await run_in_threadpool(self.users.verify,headers.get(b'authorization',b'').decode('latin1'),peer)
        common={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff',
                'X-Frame-Options':'DENY','Referrer-Policy':'no-referrer'}
        if not username:
            return await JSONResponse({'detail':'Требуется учётная запись просмотра'},401,
                headers={**common,'WWW-Authenticate':'Basic realm="Tehresurs viewer", charset="UTF-8"'})(scope,receive,send)
        method=scope['method'];path=scope['path']
        if method not in ('GET','HEAD') or (path not in ('/api/demo/me','/favicon.ico') and not allowed_read(path)):
            return await JSONResponse({'detail':'Доступ только для просмотра. Действие запрещено.'},403,headers=common)(scope,receive,send)
        if path=='/favicon.ico':return await Response(status_code=204,headers=common)(scope,receive,send)
        if path=='/api/demo/me':
            return await JSONResponse({'role':'READ_ONLY','username':username,'can_write':False},headers=common)(scope,receive,send)
        token=read_only_request.set(True)
        start=None;chunks=[]
        async def wrapped(message):
            nonlocal start
            if message['type']=='http.response.start':
                message=dict(message);items=list(message.get('headers',[]))
                items=[(k,v) for k,v in items if k.lower() not in (b'cache-control',b'x-frame-options')]
                items.extend((k.lower().encode(),v.encode()) for k,v in common.items())
                items.append((b'content-security-policy',b"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"))
                message['headers']=items
                if path=='/' and method=='GET':start=message;return
            if start is not None and message['type']=='http.response.body':
                chunks.append(message.get('body',b''))
                if message.get('more_body'):return
                body=b''.join(chunks)
                injection=b'<script>window.TEHRESURS_READ_ONLY=true;</script><script src="/static/js/demo_viewer.js?v=1"></script><link rel="stylesheet" href="/static/css/demo_viewer.css?v=1">'
                body=body.replace(b'<head>',b'<head>'+injection,1)
                start['headers']=[(k,v) for k,v in start['headers'] if k.lower()!=b'content-length']+[(b'content-length',str(len(body)).encode())]
                await send(start);await send({'type':'http.response.body','body':body});return
            await send(message)
        try:await self.app(scope,receive,wrapped)
        finally:read_only_request.reset(token)
