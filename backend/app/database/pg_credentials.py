"""Opt-in DPAPI credentials for the fixed Tehresurs database. Test-copy implementation."""
import ctypes
import json
import os
import subprocess
from dataclasses import dataclass,field
from functools import lru_cache
from pathlib import Path

class CredentialError(RuntimeError):pass
@dataclass(frozen=True)
class Credential:
    role:str
    database:str
    schema:str
    port:int
    password:str=field(repr=False)

class Blob(ctypes.Structure):
    _fields_=[('size',ctypes.c_uint32),('data',ctypes.POINTER(ctypes.c_ubyte))]

def _file_stamp(filename):
    path=Path(filename)
    if os.name!='nt' or not path.is_absolute() or not path.is_file():raise ValueError()
    for item in (path,*path.parents):
        if getattr(item.lstat(),'st_file_attributes',0)&0x400:raise ValueError()
    class BasicInfo(ctypes.Structure):
        _fields_=[('created',ctypes.c_int64),('accessed',ctypes.c_int64),('written',ctypes.c_int64),('changed',ctypes.c_int64),('attributes',ctypes.c_uint32)]
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateFileW.argtypes=[ctypes.c_wchar_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p];kernel.CreateFileW.restype=ctypes.c_void_p
    kernel.GetFileInformationByHandleEx.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p,ctypes.c_uint32];kernel.GetFileInformationByHandleEx.restype=ctypes.c_int
    kernel.CloseHandle.argtypes=[ctypes.c_void_p];kernel.CloseHandle.restype=ctypes.c_int
    handle=kernel.CreateFileW(str(path),0x80,7,None,3,0x00200000,None)
    if handle==ctypes.c_void_p(-1).value:raise ValueError()
    try:
        info=BasicInfo()
        if not kernel.GetFileInformationByHandleEx(handle,0,ctypes.byref(info),ctypes.sizeof(info)):raise ValueError()
        if info.attributes&0x400:raise ValueError()
        details=path.stat()
        return (details.st_dev,details.st_ino,details.st_size,info.written,info.changed)
    finally:kernel.CloseHandle(handle)

@lru_cache(maxsize=1)
def _read_protected_file(filename,stamp=None):
    try:
        if os.name!='nt':raise ValueError()
        path=Path(filename)
        if not path.is_absolute() or not path.is_file():raise ValueError()
        for item in (path,*path.parents):
            if getattr(item.lstat(),'st_file_attributes',0)&0x400:raise ValueError()
        # Run once per process/path. Only ACL metadata/path, never a credential, enters PowerShell.
        literal=str(path).replace("'","''")
        command="$ErrorActionPreference='Stop'; $a=Get-Acl -LiteralPath '"+literal+"'; $sid=[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value; if ($a.GetOwner([System.Security.Principal.SecurityIdentifier]).Value -ne $sid) { exit 2 }; foreach($r in $a.GetAccessRules($true,$true,[System.Security.Principal.SecurityIdentifier])) { if ($r.AccessControlType -eq 'Allow' -and $r.IdentityReference.Value -notin @($sid,'S-1-5-18','S-1-5-32-544')) { exit 3 } }; exit 0"
        result=subprocess.run([str(Path(os.environ['SYSTEMROOT'])/'System32/WindowsPowerShell/v1.0/powershell.exe'),'-NoProfile','-NonInteractive','-Command',command],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10,creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:raise ValueError()
        encrypted=path.read_bytes()
        if not 32<=len(encrypted)<=65536:raise ValueError()
        buffer=ctypes.create_string_buffer(encrypted);source=Blob(len(encrypted),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_ubyte)));output=Blob()
        crypt=ctypes.WinDLL('crypt32',use_last_error=True);kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        crypt.CryptUnprotectData.argtypes=[ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_uint32,ctypes.POINTER(Blob)];crypt.CryptUnprotectData.restype=ctypes.c_int
        kernel.LocalFree.argtypes=[ctypes.c_void_p];kernel.LocalFree.restype=ctypes.c_void_p
        try:
            if not crypt.CryptUnprotectData(ctypes.byref(source),None,None,None,None,1,ctypes.byref(output)):raise ValueError()
            data=json.loads(ctypes.string_at(output.data,output.size).decode('utf-8'))
        finally:
            if output.data:
                ctypes.memset(output.data,0,output.size);kernel.LocalFree(output.data)
        if set(data)!={'role','database','schema','port','password'}:raise ValueError()
        if data['role']!='tehresurs_app' or data['database']!='ai_excel_agent_test' or data['schema']!='test_construction_identity_stage46':raise ValueError()
        if type(data['port']) is not int or not 1024<=data['port']<=65535:raise ValueError()
        if not isinstance(data['password'],str) or not 32<=len(data['password'])<=1024:raise ValueError()
        return Credential(data['role'],data['database'],data['schema'],data['port'],data['password'])
    except Exception:
        raise CredentialError('Protected PostgreSQL credential unavailable or invalid') from None

def connection_credentials():
    """Never fall back when DPAPI was selected, including an empty/missing path."""
    path=os.getenv('DB_CREDENTIAL_FILE')
    if path is None and os.getenv('DB_USER')!='tehresurs_app':
        return os.getenv('DB_USER'),os.getenv('DB_PASSWORD')
    try:
        if not path or os.getenv('DB_PASSWORD'):raise ValueError()
        value=_read_protected_file(path,_file_stamp(path))
        if (os.getenv('DB_USER'),os.getenv('DB_NAME'),os.getenv('DB_SCHEMA'))!=(value.role,value.database,value.schema):raise ValueError()
        if os.getenv('DB_HOST') not in ('127.0.0.1','::1') or int(os.getenv('DB_PORT','0'))!=value.port:raise ValueError()
        return value.role,value.password
    except Exception:
        raise CredentialError('Protected PostgreSQL credential/configuration rejected') from None
