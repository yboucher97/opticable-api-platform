from copy import deepcopy
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('post37_stage',Path(__file__).resolve().parents[3]/'ops/post37_remediation/stage_runtime.py')
stage=importlib.util.module_from_spec(spec);spec.loader.exec_module(stage)

class ReleasePreservationTests(unittest.TestCase):
    def setUp(self):
        def require(ok,reason):
            if not ok:raise ValueError(reason)
        self.helper=SimpleNamespace(require=require,INTERNAL_SCOPES={'i'},CUSTOMER_SCOPES={'c'},INTERNAL_SOURCES={'i.py'},CUSTOMER_SOURCES={'c.py'},trusted=lambda p:p.read_bytes(),digest=lambda b:__import__('hashlib').sha256(b).hexdigest())
        self.prior={'internal_policy':{'lifecycle':{'enabled':True,'real_scopes':['i'],'test_scopes':[],'source_hashes':{'i.py':'old'},'expires_at':'original-expiry','activated_at':'original-cutoff'}},
            'customer_policy':{'external_enabled':True,'test_enabled':False,'real_scopes':['c'],'test_scopes':[],'source_hashes':{'c.py':'old'},'activated_at':'original-cutoff','expires_at':'original-expiry'},
            'internal_activation':{'release_sha':'old','activated_at':'original-cutoff','scopes':['i']},
            'internal_effects':{'claim':{'state':'succeeded'}},'customer_effects':{'send':{'state':'succeeded'}}}
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.source=Path(self.tmp.name)/('a'*40)/'source';files=self.source/'apps/workflow-api/workflow';files.mkdir(parents=True)
        for name in ('i.py','c.py'):(files/name).write_text('reviewed source')
    def test_only_source_pins_and_release_identity_change(self):
        before=deepcopy(self.prior);internal,customer,activation=stage.preserved(self.prior,self.source,self.helper)
        self.assertEqual(self.prior,before)
        for policy,key in ((internal['lifecycle'],'internal_policy'),(customer,'customer_policy')):
            old=before[key]['lifecycle'] if key=='internal_policy' else before[key]
            self.assertEqual({k:v for k,v in policy.items() if k!='source_hashes'},{k:v for k,v in old.items() if k!='source_hashes'})
        self.assertEqual(activation,{**before['internal_activation'],'release_sha':'a'*40})
    def test_expansion_or_test_authority_cannot_resume(self):
        for kind in ('internal','customer','test'):
            with self.subTest(kind=kind):
                v=deepcopy(self.prior)
                if kind=='internal':v['internal_policy']['lifecycle']['real_scopes'].append('new')
                elif kind=='customer':v['customer_policy']['real_scopes'].append('new')
                else:v['customer_policy']['test_enabled']=True
                with self.assertRaises(ValueError):stage.preserved(v,self.source,self.helper)
