import unittest
from unittest.mock import patch
from starlette.requests import Request
from fastapi import HTTPException
from app.services import personnel_local as local
from app.access_context import read_only_request

class LocalGuards(unittest.TestCase):
 def request(self,**changes):
  headers={'host':'127.0.0.1:8001','origin':'http://127.0.0.1:8001','sec-fetch-site':'same-origin','content-type':'application/json','x-personnel-local-token':local.browser_key()}
  headers.update(changes.pop('headers',{}));scope=dict(type='http',method='POST',scheme='http',path='/api/employees/1/position-transfers',query_string=b'',server=('127.0.0.1',8001),client=('127.0.0.1',1));scope.update(changes);scope['headers']=[(k.encode(),v.encode()) for k,v in headers.items()];return Request(scope)
 def check(self,req,status=None,private=True):
  with patch.object(local,'_enabled',True),patch.object(local,'listener_is_private',return_value=private):
   if status:
    with self.assertRaises(HTTPException) as e:local.authorize(req,True)
    self.assertEqual(e.exception.status_code,status)
   else:self.assertTrue(local.is_local(local.authorize(req,True)))
 def test_explicit_process_capability(self):self.check(self.request())
 def test_disabled_preserves_session_path(self):
  with patch.object(local,'_enabled',False):self.assertIsNone(local.authorize(self.request(),True))
 def test_listener_must_be_confirmed(self):self.check(self.request(),503,False)
 def test_bad_key(self):self.check(self.request(headers={'x-personnel-local-token':'invalid'}),403)
 def test_foreign_origin(self):self.check(self.request(headers={'origin':'http://example.invalid'}),403)
 def test_cross_site(self):self.check(self.request(headers={'sec-fetch-site':'cross-site'}),403)
 def test_wrong_host(self):self.check(self.request(headers={'host':'localhost:8001'}),403)
 def test_proxy(self):self.check(self.request(headers={'x-forwarded-for':'127.0.0.1'}),403)
 def test_remote_peer(self):self.check(self.request(client=('192.0.2.1',1)),403)
 def test_wrong_server(self):self.check(self.request(server=('0.0.0.0',8001)),403)
 def test_readonly(self):
  token=read_only_request.set(True)
  try:self.check(self.request(),403)
  finally:read_only_request.reset(token)
 def test_not_json(self):self.check(self.request(headers={'content-type':'text/plain'}),415)


class NativeListenerChecks(unittest.TestCase):
 def test_current_process_loopback(self):
  with patch.object(local,'_tcp_listeners',return_value=[('127.0.0.1',8001,local.os.getpid())]):
   self.assertTrue(local.listener_is_private())
 def test_public_or_ipv6_listener_rejected(self):
  for address in ('0.0.0.0','192.0.2.1','::','::1'):
   with self.subTest(address=address),patch.object(local,'_tcp_listeners',return_value=[('127.0.0.1',8001,local.os.getpid()),(address,8001,local.os.getpid())]):
    self.assertFalse(local.listener_is_private())
 def test_foreign_pid_rejected(self):
  with patch.object(local,'_tcp_listeners',return_value=[('127.0.0.1',8001,local.os.getpid()+1)]):self.assertFalse(local.listener_is_private())
 def test_empty_or_other_port_rejected(self):
  for rows in ([],[('127.0.0.1',8002,local.os.getpid())]):
   with patch.object(local,'_tcp_listeners',return_value=rows):self.assertFalse(local.listener_is_private())
 def test_error_fails_closed(self):
  with patch.object(local,'_tcp_listeners',side_effect=OSError('Unavailable')):self.assertFalse(local.listener_is_private())
 def test_every_call_takes_fresh_snapshot(self):
  with patch.object(local,'_tcp_listeners',side_effect=[[('127.0.0.1',8001,local.os.getpid())],[('0.0.0.0',8001,local.os.getpid())]]) as query:
   self.assertTrue(local.listener_is_private());self.assertFalse(local.listener_is_private());self.assertEqual(query.call_count,2)
 def test_native_snapshot_matches_os_listener(self):
  import subprocess,json
  result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',"@(Get-NetTCPConnection -LocalPort 8001 -State Listen -ErrorAction Stop | Select-Object LocalAddress,OwningProcess) | ConvertTo-Json -Compress"],capture_output=True,text=True,check=True,timeout=10)
  expected=json.loads(result.stdout);expected=expected if isinstance(expected,list) else [expected]
  self.assertEqual(sorted(row for row in local._tcp_listeners() if row[1]==8001),sorted((row['LocalAddress'],8001,row['OwningProcess']) for row in expected))

if __name__=='__main__':unittest.main()
