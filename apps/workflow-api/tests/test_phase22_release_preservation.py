from copy import deepcopy
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('stage22',ROOT/'ops/phase22_23/stage_runtime.py');stage=importlib.util.module_from_spec(spec);spec.loader.exec_module(stage)

class ReleasePreservationTests(unittest.TestCase):
 def fixture(self):
  internal={'lifecycle':{'enabled':True,'real_scopes':['internal'], 'test_scopes':[], 'activated_at':'original-cutoff', 'expires_at':'original-expiry','source_hashes':{'a.py':'old'}},'real_canary_allowed':False}
  customer={'external_enabled':True,'test_enabled':False,'real_scopes':['customer'],'test_scopes':[], 'activated_at':'original-customer-cutoff','expires_at':'original-customer-expiry','source_hashes':{'b.py':'old'},'per_family_limit':10}
  return {'internal_policy':internal,'customer_policy':customer,'internal_activation':{'release_sha':'old-sha','scopes':['internal'],'run':'original-run','activated_at':'original-cutoff'}}
 def helper(self):
  def require(value,reason):
   if not value:raise ValueError(reason)
  return SimpleNamespace(INTERNAL_SCOPES={'internal'},CUSTOMER_SCOPES={'customer'},INTERNAL_SOURCES={'a.py'},CUSTOMER_SOURCES={'b.py'},require=require,trusted=lambda p:b'new-code',digest=lambda b:'new-pin')
 def test_release_does_not_renew_expand_or_reset_authority(self):
  prior=self.fixture();saved=deepcopy(prior);i,c,a=stage.preserved(prior,Path('/immutable/new-sha/source'),self.helper())
  self.assertEqual(prior,saved)
  i['lifecycle']['source_hashes']=saved['internal_policy']['lifecycle']['source_hashes'];c['source_hashes']=saved['customer_policy']['source_hashes'];a['release_sha']='old-sha'
  self.assertEqual(i,saved['internal_policy']);self.assertEqual(c,saved['customer_policy']);self.assertEqual(a,saved['internal_activation'])
 def test_partial_or_changed_scope_authority_refused(self):
  for key in ('internal_policy','customer_policy'):
   with self.subTest(key=key):
    p=self.fixture();scope=p[key]['lifecycle'] if key=='internal_policy' else p[key];scope['real_scopes'].append('broad')
    with self.assertRaises(ValueError):stage.preserved(p,Path('/immutable/new/source'),self.helper())
 def test_inactive_or_test_authority_never_reenabled(self):
  for key in ('enabled','test_enabled'):
   with self.subTest(key=key):
    p=self.fixture()
    if key=='enabled':p['internal_policy']['lifecycle']['enabled']=False
    else:p['customer_policy']['test_enabled']=True
    with self.assertRaises(ValueError):stage.preserved(p,Path('/immutable/new/source'),self.helper())
