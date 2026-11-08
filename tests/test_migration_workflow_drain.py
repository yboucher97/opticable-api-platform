"""Exact terminal-history exceptions, never a blanket error bypass."""
import copy,json,sys,tempfile,time,unittest,os
from pathlib import Path
from unittest.mock import patch
from datetime import datetime,timezone
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'ops/rebuild'))
import migration_adapters as m
from common import atomic_json,digest,file_hash,RebuildError
class DrainTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.path='/accounts/fixture/workflows/fixture/instances';self.detail={'status':'errored','end':'2026-11-01T12:00:00Z','error':{'name':'FixtureError','message':'fixture only'},'params':{'event_id':'FIXTURE'}};self.ident='failed-fixture';self.active={};self.errors=[];self.p={'runtime':{'workflow_instances_path':self.path},'scopes':{'source_freeze_final_sync':{}}}
 def tearDown(self):self.tmp.cleanup()
 def edge(self,path,params=None):
  if params:return self.errors if params['status']=='errored' else self.active.get(params['status'],[])
  if path==self.path+'/'+self.ident:return self.detail
  raise AssertionError('unreviewed endpoint')
 def approve(self):
  proof=self.root/'evidence.json';atomic_json(proof,{'items':[{'id':self.ident,'detail':self.detail}]});os.utime(proof,(time.time()-2,time.time()-2));atomic_json(self.root/'migration-offhost.json',{'status':'PASS','full_R2_readback':'PASS','at':datetime.now(timezone.utc).isoformat()});self.p['scopes']['source_freeze_final_sync']['retained_errored_workflows']={'instances':{self.ident:digest(self.detail)},'evidence_file':str(proof),'evidence_sha256':file_hash(proof)};self.errors=[{'id':self.ident,'status':'errored'}]
 def verify(self):
  with patch.object(m,'CONTROL',self.root):return m.verify_workflow_drain(self.p,self.edge)
 def test_empty_drain_unchanged(self):self.assertEqual(self.verify()['preserved_terminal_failures'],0)
 def test_error_without_exact_owner_binding_blocks(self):
  self.errors=[{'id':self.ident}]
  with self.assertRaises(RebuildError):self.verify()
 def test_exact_approved_sealed_terminal_failure_preserved_without_write(self):
  self.approve();before=copy.deepcopy(self.detail);self.assertEqual(self.verify()['preserved_terminal_failures'],1);self.assertEqual(self.detail,before)
 def test_active_states_always_block(self):
  self.approve()
  for state in ('queued','running','paused','waitingForPause','waiting','rollingBack'):
   self.active={state:[{'id':'still-active'}]}
   with self.assertRaises(RebuildError):self.verify()
 def test_new_error_outside_approved_set_blocks(self):
  self.approve();self.errors.append({'id':'unapproved-new-failure'})
  with self.assertRaises(RebuildError):self.verify()
 def test_changed_failure_snapshot_blocks(self):
  self.approve();self.detail['params']['event_id']='CHANGED'
  with self.assertRaises(RebuildError):self.verify()
 def test_unsealed_evidence_blocks(self):
  self.approve();atomic_json(self.root/'migration-offhost.json',{'status':'BLOCKED','full_R2_readback':'NOT_RUN'})
  with self.assertRaises(RebuildError):self.verify()
 def test_changed_local_evidence_blocks(self):
  self.approve();Path(self.p['scopes']['source_freeze_final_sync']['retained_errored_workflows']['evidence_file']).write_text('{}')
  with self.assertRaises(RebuildError):self.verify()
 def test_malformed_provider_list_fails_closed(self):
  self.active={'running':{}}
  with self.assertRaises(RebuildError):self.verify()
if __name__=='__main__':unittest.main()
