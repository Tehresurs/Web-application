"""Isolated stage 3 factory. Never imported/installed by app.main."""
from starlette.responses import JSONResponse
from starlette.requests import Request
from starlette.exceptions import HTTPException
from starlette.routing import Match,Mount
from starlette.concurrency import run_in_threadpool
from app.auth_policies import routes,identity,policies
from app.api.user_auth import COOKIE,transport,origin
from app.services.user_auth import AuthDenied
from app.access_context import read_only_request

class ProtectedApp:
    def __init__(self,app,auth_service):
        self.app=app;self.auth=auth_service
        self.policy={(p['method'],p['path']):p for p in policies()}
    async def __call__(self,scope,receive,send):
        if scope['type']=='lifespan':return await self.app(scope,receive,send)
        if scope['type']=='websocket':return await send({'type':'websocket.close','code':1008})
        if scope['type']!='http':return
        async def error(status,message):
            return await JSONResponse({'detail':message},status_code=status,headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})(scope,receive,send)
        method=scope['method'];chosen=None;policy=None
        for r in routes(self.app):
            match,_=r.matches(scope)
            if match==Match.FULL:
                chosen=r
                policy=self.policy.get(('MOUNT' if isinstance(r,Mount) else method,r.path))
                if policy and policy['handler']!=identity(r):policy=None
                break
        # Even a newly registered public-looking route has no authority without a policy.
        public=policy and policy['permission']=='PUBLIC'
        request=Request(scope,receive)
        if not public:
            try:
                transport(request)
                token=request.cookies.get(COOKIE)
                user=await run_in_threadpool(self.auth.current,token)
            except HTTPException:return await error(403,'HTTPS required')
            except AuthDenied:return await error(401,'Authentication required')
            except Exception:return await error(503,'Authentication unavailable')
            if not policy or policy['permission']=='DENY':return await error(403,'Action not permitted')
            permission=policy['permission']
            if permission!='SESSION' and permission not in user['permissions']:return await error(403,'Permission denied')
            if policy.get('allowed_roles') and not set(user['roles']).intersection(policy['allowed_roles']):return await error(403,'Role not permitted for workflow')
            if policy['csrf']:
                try:
                    origin(request)
                    self.auth.verify_csrf(token,request.headers.get('x-csrf-token'))
                except Exception:return await error(403,'CSRF rejected')
            if policy.get('payload_guard'):
                from app.auth_policies import validate_payload
                try:
                    body=bytearray()
                    async for chunk in request.stream():
                        body.extend(chunk)
                        if len(body)>11*1024*1024:return await error(413,'Policy payload limit exceeded')
                    payload=bytes(body)
                    async def replay():return {'type':'http.request','body':payload,'more_body':False}
                    await validate_payload(policy['payload_guard'],Request(scope,replay))
                    receive=replay
                except Exception:return await error(403,'Workflow branch requires separate authority')
            scope.setdefault('state',{})['auth_user']=user
            if scope['path']=='/api/production-matrix/capabilities':
                # Old single-user LEADER capability is not authoritative in this entry.
                return await JSONResponse({'status':'ok','item':{'roles':user['roles'],'can_manage_dk':False,'single_user':False}},headers={'Cache-Control':'no-store'})(scope,receive,send)
        readonly=policy and policy['permission'] in ('data.read','excel.export')
        ctx=read_only_request.set(bool(readonly))
        async def guarded_send(message):
            if message['type']=='http.response.start':
                message=dict(message)
                message['headers']=[(k,v) for k,v in message.get('headers',[]) if k.lower() not in (b'cache-control',b'x-frame-options',b'x-content-type-options')]+[(b'cache-control',b'no-store'),(b'x-frame-options',b'DENY'),(b'x-content-type-options',b'nosniff')]
            await send(message)
        try:return await self.app(scope,receive,guarded_send)
        finally:read_only_request.reset(ctx)

def create_protected_app(app=None,auth_service=None):
    if app is None:
        from app.main import app
    if auth_service is None:
        from app.api.user_auth import service
        auth_service=service()
    return ProtectedApp(app,auth_service)
