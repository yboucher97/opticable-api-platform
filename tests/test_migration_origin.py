"""File and transport failures are fixtures; never exposes deployed listeners."""
import copy,json,os,sys,tempfile,unittest,types
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'ops/rebuild'))
import migration_origin as m
from common import atomic_json,file_hash,RebuildError
class OriginTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.source=self.root/'source';self.dest=self.root/'destination';self.source.mkdir();self.dest.mkdir();rows={}
  for n in m.NAMES:
   p=self.source/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('FIXTURE '+n);rows[n]={'bytes':p.stat().st_size,'sha256':file_hash(p)}
  manifest=self.root/'manifest.json';atomic_json(manifest,rows);config=self.root/'production.caddy';config.write_text(m.HOST+' {\n}\n');private=self.root/'Caddyfile';private.write_text('http://127.0.0.1:8080 {\n}\n')
  self.scope={'tls_source':str(self.source),'tls_manifest':str(manifest),'tls_manifest_sha256':file_hash(manifest),'production_config':str(config),'production_config_sha256':file_hash(config),'current_config':str(private),'before_config_sha256':file_hash(private)}
 def tearDown(self):self.tmp.cleanup()
 def test_exact_retained_seven_files(self):self.assertEqual(set(m.material(self.scope,self.dest)),m.NAMES)
 def test_each_changed_TLS_member_blocks(self):
  for n in m.NAMES:
   p=self.source/n;saved=p.read_bytes();p.write_text('CHANGED')
   with self.assertRaises(RebuildError):m.material(self.scope,self.dest)
   p.write_bytes(saved)
 def test_extra_manifest_file_blocks(self):
  p=Path(self.scope['tls_manifest']);v=json.loads(p.read_text());v['other.key']={};atomic_json(p,v);self.scope['tls_manifest_sha256']=file_hash(p)
  with self.assertRaises(RebuildError):m.material(self.scope,self.dest)
 def test_missing_required_member_blocks(self):
  p=self.source/m.CERT;p.unlink()
  with self.assertRaises(FileNotFoundError):m.material(self.scope,self.dest)
 def test_conflicting_destination_preserved(self):
  d=self.dest/m.CERT;d.parent.mkdir(parents=True);d.write_text('NEWER TLS STATE')
  with self.assertRaises(RebuildError):m.material(self.scope,self.dest)
  self.assertEqual(d.read_text(),'NEWER TLS STATE')
 def test_matching_destination_is_allowed(self):
  d=self.dest/m.CERT;d.parent.mkdir(parents=True);d.write_bytes((self.source/m.CERT).read_bytes());m.material(self.scope,self.dest)
 def test_destination_symlink_blocks(self):
  (self.dest/'certificates').symlink_to(self.source/'certificates',target_is_directory=True)
  with self.assertRaises(RebuildError):m.material(self.scope,self.dest)
 def test_source_symlink_blocks(self):
  p=self.source/m.CERT;saved=p.read_bytes();p.unlink();alternate=self.root/'cert';alternate.write_bytes(saved);p.symlink_to(alternate)
  with self.assertRaises(RebuildError):m.material(self.scope,self.dest)
 def test_private_config_drift_blocks(self):
  Path(self.scope['current_config']).write_text('MATERIAL CHANGE')
  with self.assertRaises(RebuildError):m.material(self.scope,self.dest)
 def test_unreviewed_config_blocks(self):
  Path(self.scope['production_config']).write_text('other.host {}')
  with self.assertRaises(RebuildError):m.material(self.scope,self.dest)
 def live(self):
  case=self
  class Live:
   p={'scopes':{'dns_cutover':{'origin':case.scope}}};root=case.root/'evidence'
   def approval(self,s):return {'approved':True,'fixture_only':True}
   def source(self,v):return {'fenced':True}
   def edge(self,p):return {'settings':{'delivery_paused':True}}
   def private_api(self):return {'all45_off':True}
   def run_origin(self,a):self.commands.append(a)
   def origin_headers(self):return {'X-API-Key':'FIXTURE_ONLY'}
  x=Live();x.root.mkdir();x.commands=[];return x
 def enable_fixture(self,live,readback):
  real=Path
  with patch.object(m,'Path',side_effect=lambda p: self.dest if str(p)=='/var/lib/caddy/.local/share/caddy' else real(p)),patch.object(m,'probe',side_effect=readback),patch.object(m.os,'geteuid',return_value=0),patch.object(m.os,'uname',return_value=types.SimpleNamespace(nodename='vps-f8e9b20e')),patch.object(m.os,'chown'),patch.object(m.pwd,'getpwnam',return_value=types.SimpleNamespace(pw_uid=0,pw_gid=0)):
   return m.enable(live)
 def test_success_installs_and_proves_origin_before_DNS(self):
  x=self.live();self.enable_fixture(x,lambda h:{'hold':{'http':200}});self.assertTrue((x.root/'origin-verified.json').exists());self.assertEqual(Path(self.scope['current_config']).read_bytes(),Path(self.scope['production_config']).read_bytes());self.assertTrue(all((self.dest/n).exists() for n in m.NAMES))
 def test_failed_TLS_readback_restores_only_private_proxy(self):
  x=self.live();before=Path(self.scope['current_config']).read_bytes()
  with self.assertRaises(TimeoutError):self.enable_fixture(x,lambda h:(_ for _ in ()).throw(TimeoutError()))
  self.assertEqual(Path(self.scope['current_config']).read_bytes(),before);r=json.loads((x.root/'origin-failure.json').read_text());self.assertTrue(r['private_proxy_restored']);self.assertFalse(r['DNS_transport_started']);self.assertTrue(r['OLD_fence_and_NEW_data_preserved'])
 def test_unheld_queue_blocks_before_copy_or_reload(self):
  x=self.live();x.edge=lambda p:{'settings':{'delivery_paused':False}}
  with self.assertRaises(RebuildError):self.enable_fixture(x,lambda h:{})
  self.assertEqual(x.commands,[]);self.assertFalse((x.root/'origin-activation.json').exists())
 def test_expired_approval_blocks_before_copy(self):
  x=self.live();x.approval=lambda s:(_ for _ in ()).throw(RebuildError('expired'))
  with self.assertRaises(RebuildError):self.enable_fixture(x,lambda h:{})
  self.assertEqual(x.commands,[])
 def test_existing_intent_is_reconcile_only(self):
  x=self.live();atomic_json(x.root/'origin-activation.json',{'state':'ATTEMPTED'})
  with self.assertRaises(RebuildError):self.enable_fixture(x,lambda h:{})
  self.assertFalse((x.root/'origin-verified.json').exists())
 def test_adapter_never_sends_DNS_after_origin_failure(self):
  from migration_adapters import Live
  x=type('FixtureLive',(),{})();x.p={'scopes':{'dns_cutover':{'after':{}}}};called=[];x.edge_write=lambda *a:called.append(a)
  with patch.object(m,'enable',side_effect=TimeoutError()):
   with self.assertRaises(TimeoutError):Live.effect(x,'CUTOVER',{},{} )
  self.assertEqual(called,[])
if __name__=='__main__':unittest.main()
