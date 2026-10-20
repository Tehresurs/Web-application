"""Explicit HR-only process capability; no account or session impersonation."""
import os,secrets,hmac,hashlib
from dataclasses import dataclass
from fastapi import HTTPException
from app.access_context import read_only_request

@dataclass(frozen=True)
class LocalSource:
    label:str='Локальное приложение'

_source=LocalSource()
_browser_key=secrets.token_urlsafe(32)
_sql_key=secrets.token_urlsafe(32)
_enabled=False

def _tcp_listeners():
    """Fresh IPv4 and IPv6 OWNER_PID listener snapshots from Windows IP Helper."""
    import ctypes
    import socket
    import struct
    if os.name!='nt':raise OSError('Windows TCP inspection required')
    DWORD=ctypes.c_uint32
    class Row4(ctypes.Structure):
        _fields_=[('state',DWORD),('address',DWORD),('port',DWORD),
                  ('remote_address',DWORD),('remote_port',DWORD),('pid',DWORD)]
    class Row6(ctypes.Structure):
        _fields_=[('address',ctypes.c_ubyte*16),('scope',DWORD),('port',DWORD),
                  ('remote_address',ctypes.c_ubyte*16),('remote_scope',DWORD),
                  ('remote_port',DWORD),('state',DWORD),('pid',DWORD)]
    api=ctypes.WinDLL('iphlpapi.dll').GetExtendedTcpTable
    api.argtypes=[ctypes.c_void_p,ctypes.POINTER(DWORD),ctypes.c_int,DWORD,DWORD,DWORD]
    api.restype=DWORD
    listeners=[]
    for family,row_type in ((socket.AF_INET,Row4),(socket.AF_INET6,Row6)):
        size=DWORD(0)
        code=api(None,ctypes.byref(size),False,family,3,0) # TCP_TABLE_OWNER_PID_LISTENER
        if code not in (0,122):raise ctypes.WinError(code)
        for attempt in range(3):
            if size.value<ctypes.sizeof(DWORD):raise OSError('Invalid TCP table size')
            buffer=ctypes.create_string_buffer(size.value)
            code=api(buffer,ctypes.byref(size),False,family,3,0)
            if code==122:continue # Table grew; take a new complete snapshot.
            if code:raise ctypes.WinError(code)
            count=DWORD.from_buffer_copy(buffer).value
            row_size=ctypes.sizeof(row_type)
            if size.value>len(buffer) or count>(size.value-4)//row_size:raise OSError('Incomplete TCP table')
            for index in range(count):
                row=row_type.from_buffer_copy(buffer,4+index*row_size)
                if row.state!=2:raise OSError('Unexpected non-listener TCP row')
                packed=struct.pack('=I',row.address) if family==socket.AF_INET else bytes(row.address)
                listeners.append((socket.inet_ntop(family,packed),socket.ntohs(row.port & 0xffff),row.pid))
            break
        else:raise OSError('TCP table kept changing')
    return listeners


def listener_is_private():
    try:
        rows=[row for row in _tcp_listeners() if row[1]==8001]
        return bool(rows) and all(address=='127.0.0.1' and pid==os.getpid() for address,port,pid in rows)
    except Exception:return False


def activate():
    global _enabled
    if os.environ.get('PERSONNEL_LOCAL_8001')!='1':return
    from app.database.db import get_connection
    with get_connection() as c:
        if c.execute('SELECT current_database(),current_schema()').fetchone()!=('ai_excel_agent_test','test_construction_identity_stage46'):raise RuntimeError('Wrong local HR target')
        if c.execute("SELECT to_regclass('dk_service.tx_state')").fetchone()[0]:raise RuntimeError('Signed DK cannot use legacy local HR')
        c.execute('UPDATE personnel_settings SET local_key_digest=%s WHERE id=1 AND local_enabled', (hashlib.sha256(_sql_key.encode()).hexdigest(),))
    _enabled=True

def authorize(request,write=False):
    if not _enabled:return None
    from app.api.user_auth import origin,transport
    transport(request)
    if read_only_request.get():raise HTTPException(403,'Read-only кадровый режим')
    if request.url.netloc!='127.0.0.1:8001' or request.client is None or request.client.host!='127.0.0.1' or request.scope.get('server')!=('127.0.0.1',8001):raise HTTPException(403,'Local HR endpoint rejected')
    if any(name in request.headers for name in ('forwarded','x-forwarded-for','x-forwarded-host','x-forwarded-proto')):raise HTTPException(403,'Proxy HR requests rejected')
    if not listener_is_private():raise HTTPException(503,'Private HR listener not confirmed')
    if request.headers.get('sec-fetch-site') not in ('same-origin',):raise HTTPException(403,'Same-origin browser required')
    if write:
        origin(request)
        if request.headers.get('content-type','').split(';')[0]!='application/json':raise HTTPException(415,'JSON required')
        if not hmac.compare_digest(request.headers.get('x-personnel-local-token',''),_browser_key):raise HTTPException(403,'Local HR request capability rejected')
    return _source

def is_local(value):return value is _source

def browser_key():return _browser_key

def sql_key():
    if not _enabled:raise PermissionError('Local HR disabled')
    return _sql_key
