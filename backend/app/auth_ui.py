"""Opt-in session UI. Never installed by app.main or the live launcher."""
import json
from pathlib import Path
from starlette.responses import HTMLResponse, Response, RedirectResponse
from starlette.concurrency import run_in_threadpool
from app.auth_protected import create_protected_app
from app.services.user_auth import AuthDenied
from app.api.user_auth import COOKIE, transport
from starlette.requests import Request

BASE=Path(__file__).parent
class AuthUI:
    def __init__(self,app,service):
        self.protected=create_protected_app(app,service);self.service=service
    async def __call__(self,scope,receive,send):
        if scope['type']!='http':return await self.protected(scope,receive,send)
        path=scope['path'];method=scope['method']
        headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY','Referrer-Policy':'same-origin'}
        # Exact allowlist only. No public static mount or wildcard route.
        if method=='GET' and path=='/login':
            return await HTMLResponse((BASE/'templates/auth_login.html').read_text(encoding='utf-8'),headers=headers)(scope,receive,send)
        if method=='GET' and path in ('/auth-ui.js','/auth-ui.css'):
            suffix='js' if path.endswith('.js') else 'css'
            return await Response((BASE/('static/'+suffix)/('auth_ui.'+suffix)).read_bytes(),media_type='text/javascript' if suffix=='js' else 'text/css',headers=headers)(scope,receive,send)
        if method=='GET' and path=='/':
            try:
                request=Request(scope,receive);transport(request)
                user=await run_in_threadpool(self.service.current,request.cookies.get(COOKIE))
            except AuthDenied:return await RedirectResponse('/login',303,headers=headers)(scope,receive,send)
            except Exception:return await Response('Authentication unavailable',503,headers=headers)(scope,receive,send)
            messages=[]
            async def capture(message):messages.append(message)
            await self.protected(scope,receive,capture)
            start=next(m for m in messages if m['type']=='http.response.start')
            if start['status']!=200:
                for m in messages:await send(m)
                return
            body=b''.join(m.get('body',b'') for m in messages if m['type']=='http.response.body')
            # Bootstrap executes before existing scripts; credentials are never serialized.
            bootstrap=b'<link rel="stylesheet" href="/auth-ui.css"><script src="/auth-ui.js"></script>'
            body=body.replace(b'</head>',bootstrap+b'</head>',1).replace(b'<body>',b'<body class="auth-loading">',1)
            start['headers']=[(k,v) for k,v in start['headers'] if k.lower()!=b'content-length']+[(b'content-length',str(len(body)).encode())]
            await send(start);return await send({'type':'http.response.body','body':body})
        return await self.protected(scope,receive,send)

def create_auth_ui(app=None,service=None):
    if app is None:
        from app.main import app
    if service is None:
        from app.api.user_auth import service as factory
        service=factory()
    return AuthUI(app,service)
