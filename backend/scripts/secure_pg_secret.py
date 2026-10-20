"""Windows-user DPAPI storage preparation. No application/configuration integration."""
import ctypes,os,subprocess
from ctypes import wintypes
from pathlib import Path
class Blob(ctypes.Structure):
    _fields_=[('cbData',wintypes.DWORD),('pbData',ctypes.POINTER(ctypes.c_ubyte))]

def transform(value,decrypt=False):
    if os.name!='nt':raise RuntimeError('Windows DPAPI required')
    raw=ctypes.create_string_buffer(value);source=Blob(len(value),ctypes.cast(raw,ctypes.POINTER(ctypes.c_ubyte)));output=Blob()
    crypt=ctypes.WinDLL('crypt32',use_last_error=True)
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.LocalFree.argtypes=[ctypes.c_void_p];kernel.LocalFree.restype=ctypes.c_void_p
    try:
        if decrypt:ok=crypt.CryptUnprotectData(ctypes.byref(source),None,None,None,None,1,ctypes.byref(output))
        else:ok=crypt.CryptProtectData(ctypes.byref(source),'Tehresurs PostgreSQL',None,None,None,1,ctypes.byref(output))
        if not ok:raise RuntimeError('DPAPI operation rejected')
        return ctypes.string_at(output.pbData,output.cbData)
    finally:
        ctypes.memset(raw,0,len(raw))
        if output.pbData:
            ctypes.memset(output.pbData,0,output.cbData);kernel.LocalFree(output.pbData)

def store(directory,password):
    directory=Path(directory).resolve();directory.mkdir(parents=False,exist_ok=False)
    username=ctypes.create_unicode_buffer(257);size=wintypes.DWORD(len(username))
    if not ctypes.windll.advapi32.GetUserNameW(username,ctypes.byref(size)):raise RuntimeError('Windows identity unavailable')
    exe=Path(os.environ['SYSTEMROOT'])/'System32/icacls.exe'
    subprocess.run([str(exe),str(directory),'/inheritance:r','/grant:r',username.value+':(OI)(CI)F'],check=True,capture_output=True)
    (directory/'credential.dpapi').write_bytes(transform(password.encode('utf-8')))

def load(directory):return transform((Path(directory)/'credential.dpapi').read_bytes(),decrypt=True).decode('utf-8')

if __name__=='__main__':
    import argparse,sys,getpass,warnings,hmac
    parser=argparse.ArgumentParser();parser.add_argument('--store',action='store_true');args=parser.parse_args()
    if not args.store:print('Preparation only. No secret read or saved.');raise SystemExit(0)
    if not sys.stdin.isatty() or not sys.stdout.isatty():raise SystemExit('Private interactive console required')
    try:
        warnings.simplefilter('error',getpass.GetPassWarning)
        secret=getpass.getpass('New application role password: ');repeat=getpass.getpass('Repeat: ')
        if not secret or not hmac.compare_digest(secret.encode(),repeat.encode()):raise ValueError()
        store(Path(__file__).resolve().parents[2]/'.private_pg_8001',secret)
        print('Encrypted local secret saved; no database/configuration changed.')
    except Exception:raise SystemExit('Secret not saved; inspect only filesystem metadata')
