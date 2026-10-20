"""Windows process counters for an explicitly owned temporary PostgreSQL tree."""
import ctypes
from ctypes import wintypes as w
class Entry(ctypes.Structure):
 _fields_=[('size',w.DWORD),('usage',w.DWORD),('pid',w.DWORD),('heap',ctypes.c_size_t),('module',w.DWORD),('threads',w.DWORD),('parent',w.DWORD),('priority',w.LONG),('flags',w.DWORD),('exe',w.WCHAR*260)]
class Counters(ctypes.Structure):
 _fields_=[('cb',w.DWORD),('faults',w.DWORD)]+[(name,ctypes.c_size_t) for name in ['peak_rss','rss','peak_paged','paged','peak_nonpaged','nonpaged','pagefile','peak_pagefile','private']]
k=ctypes.WinDLL('kernel32',use_last_error=True);p=ctypes.WinDLL('psapi',use_last_error=True)
k.CreateToolhelp32Snapshot.argtypes=[w.DWORD,w.DWORD];k.CreateToolhelp32Snapshot.restype=w.HANDLE
k.Process32FirstW.argtypes=[w.HANDLE,ctypes.POINTER(Entry)];k.Process32FirstW.restype=w.BOOL
k.Process32NextW.argtypes=[w.HANDLE,ctypes.POINTER(Entry)];k.Process32NextW.restype=w.BOOL
k.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];k.OpenProcess.restype=w.HANDLE
k.CloseHandle.argtypes=[w.HANDLE];k.CloseHandle.restype=w.BOOL
p.GetProcessMemoryInfo.argtypes=[w.HANDLE,ctypes.POINTER(Counters),w.DWORD];p.GetProcessMemoryInfo.restype=w.BOOL

def sample(root):
 h=k.CreateToolhelp32Snapshot(2,0)
 if h==ctypes.c_void_p(-1).value:raise RuntimeError('Process snapshot unavailable')
 rows=[];e=Entry();e.size=ctypes.sizeof(e)
 try:
  valid=k.Process32FirstW(h,ctypes.byref(e))
  while valid:
   rows.append((e.pid,e.parent,e.exe.lower()));valid=k.Process32NextW(h,ctypes.byref(e))
 finally:k.CloseHandle(h)
 ids={root}
 for _ in range(len(rows)):
  added={pid for pid,parent,exe in rows if parent in ids and exe=='postgres.exe'}-ids
  if not added:break
  ids.update(added)
 rss=private=measured=0
 for pid in ids:
  handle=k.OpenProcess(0x410,False,pid)
  if not handle:continue
  try:
   c=Counters();c.cb=ctypes.sizeof(c)
   if p.GetProcessMemoryInfo(handle,ctypes.byref(c),c.cb):rss+=c.rss;private+=c.private;measured+=1
  finally:k.CloseHandle(handle)
 return dict(rss_sum_bytes=rss,private_sum_bytes=private,processes=measured)
