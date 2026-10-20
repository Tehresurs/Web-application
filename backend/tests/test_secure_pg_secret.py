import unittest,secrets,tempfile
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.secure_pg_secret import store,load
class DPAPITests(unittest.TestCase):
 def test_roundtrip_and_no_plaintext(self):
  with tempfile.TemporaryDirectory() as temporary:
   directory=Path(temporary)/'private';secret=secrets.token_urlsafe(32)
   store(directory,secret)
   self.assertEqual(load(directory),secret)
   self.assertNotIn(secret.encode(),(directory/'credential.dpapi').read_bytes())
   with self.assertRaises(FileExistsError):store(directory,'must not overwrite')
 def test_tampering_rejected(self):
  with tempfile.TemporaryDirectory() as temporary:
   directory=Path(temporary)/'private';store(directory,secrets.token_urlsafe(32))
   path=directory/'credential.dpapi';raw=bytearray(path.read_bytes());raw[-1]^=1;path.write_bytes(raw)
   with self.assertRaises(RuntimeError):load(directory)
