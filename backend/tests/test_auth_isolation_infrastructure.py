import tempfile,unittest
from pathlib import Path
from auth_cluster_cleanup import cleanup
class IsolationInfrastructureTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.base=Path(self.tmp.name);self.run=self.base/'run';self.cluster=self.run/'cluster';self.cluster.mkdir(parents=True)
 def test_preparation_error_cleanup_without_server(self):
  r=cleanup(self.cluster,self.run,self.base,lambda:None,lambda:True)
  self.assertTrue(r['removed']);self.assertEqual(r['stop_attempts'],0)
 def test_cleanup_retries_then_removes(self):
  state={'calls':0,'stopped':False}
  def stop():
   state['calls']+=1
   if state['calls']==1:raise OSError('Simulated first stop failure')
   state['stopped']=True
  r=cleanup(self.cluster,self.run,self.base,stop,lambda:state['stopped'])
  self.assertTrue(r['removed']);self.assertEqual(r['stop_attempts'],2)
 def test_failed_cleanup_preserves_running_directory(self):
  r=cleanup(self.cluster,self.run,self.base,lambda:None,lambda:False)
  self.assertFalse(r['removed']);self.assertTrue(self.cluster.exists());self.assertIsNotNone(r['error'])
 def test_outside_path_refused(self):
  with self.assertRaises(RuntimeError):cleanup(self.base,self.run,self.base,lambda:None,lambda:True)
 def test_unique_report_paths_do_not_overwrite(self):
  import uuid
  a=self.base/uuid.uuid4().hex;b=self.base/uuid.uuid4().hex;a.mkdir();b.mkdir()
  (a/'report.json').write_text('first');(b/'report.json').write_text('second')
  self.assertEqual((a/'report.json').read_text(),'first')
