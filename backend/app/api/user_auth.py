"""Opt-in stage 2 endpoints. Existing API permissions remain untouched."""
from functools import lru_cache
from fastapi import APIRouter,Request,HTTPException
from fastapi.responses import JSONResponse
from app.services.user_auth import AuthService,AuthDenied,RateLimited

router=APIRouter(prefix='/api/auth',tags=['User sessions'])
COOKIE='tehresurs_session'
@lru_cache(maxsize=1)
def service():return AuthService()

def local(request):
    return request.url.hostname in ('127.0.0.1','localhost') and request.client is not None and request.client.host in ('127.0.0.1','::1')
def transport(request):
    if request.url.scheme!='https' and not local(request):raise HTTPException(403,'HTTPS required')
def origin(request):
    transport(request)
    value=request.headers.get('origin')
    expected=f'{request.url.scheme}://{request.url.netloc}'
    if not value or value!=expected:raise HTTPException(403,'Origin rejected')

def reply(data,status=200):return JSONResponse(data,status_code=status,headers={'Cache-Control':'no-store','Pragma':'no-cache','X-Content-Type-Options':'nosniff'})

async def credentials(request):
    # Manual parsing avoids framework validation echoing passwords in 422 responses.
    if request.headers.get('content-type','').split(';')[0]!='application/json':raise HTTPException(415,'JSON required')
    body=bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body)>8192:raise HTTPException(413,'Request too large')
    import json
    try:
        d=json.loads(body)
        if not isinstance(d,dict) or set(d)!={'login','password'}:raise ValueError()
        if not isinstance(d['login'],str) or not isinstance(d['password'],str):raise ValueError()
        if not 3<=len(d['login'])<=254 or not 1<=len(d['password'])<=1024:raise ValueError()
        return d
    except (ValueError,TypeError):raise HTTPException(400,'Invalid credentials payload') from None

@router.post('/login')
async def login(request:Request):
    origin(request);d=await credentials(request)
    from starlette.concurrency import run_in_threadpool
    try:
        s=service();token=await run_in_threadpool(s.login,d['login'],d['password'],request.client.host)
    except RateLimited:return reply({'detail':'Try again later'},429)
    except AuthDenied:return reply({'detail':'Invalid credentials'},401)
    except Exception:return reply({'detail':'Authentication unavailable'},503)
    r=reply({'authenticated':True,'csrf_token':s.csrf(token)})
    r.set_cookie(COOKIE,token,max_age=28800,httponly=True,secure=request.url.scheme=='https',samesite='strict',path='/')
    return r

@router.get('/me')
def me(request:Request):
    transport(request)
    try:
        s=service();token=request.cookies.get(COOKIE);u=s.current(token)
        u.pop('session_id',None)
        return reply({'user':u,'csrf_token':s.csrf(token)})
    except AuthDenied:return reply({'detail':'Authentication required'},401)
    except Exception:return reply({'detail':'Authentication unavailable'},503)

def require_session_csrf(request:Request):
    origin(request)
    try:
        s=service();token=request.cookies.get(COOKIE);u=s.current(token)
        s.verify_csrf(token,request.headers.get('x-csrf-token'))
        return u
    except AuthDenied:raise HTTPException(403,'Session or CSRF rejected') from None
    except Exception:raise HTTPException(503,'Authentication unavailable') from None

@router.post('/logout')
def logout(request:Request):
    require_session_csrf(request)
    try:service().logout(request.cookies.get(COOKIE))
    except AuthDenied:return reply({'detail':'Authentication required'},401)
    except Exception:return reply({'detail':'Authentication unavailable'},503)
    r=reply({'authenticated':False});r.delete_cookie(COOKIE,path='/',secure=request.url.scheme=='https',httponly=True,samesite='strict');return r
