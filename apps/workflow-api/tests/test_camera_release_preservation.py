"""The preview adapter release preserves original internal and closed customer authority."""
from copy import deepcopy
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('camera_stage',ROOT/'ops/first_hosted_camera_preview/stage_runtime.py')
stage=importlib.util.module_from_spec(spec);spec.loader.exec_module(stage)

class PreservationTests(unittest.TestCase):
    def fixture(self):
        return {'internal_policy':{'lifecycle':{'enabled':True,'real_scopes':['original'], 'test_scopes':[],
            'activated_at':'original-cutoff','expires_at':'original-expiry','source_hashes':{'a.py':'old'}},'real_canary_allowed':False},
            'customer_policy':{'external_enabled':False,'test_enabled':False,'test_scopes':[],
                'activated_at':'closed-cutoff','expires_at':'closed-expiry','real_scopes':['retained']},
            'internal_activation':{'release_sha':'old','scopes':['original'],'run':'original-run','activated_at':'original-cutoff'}}
    def helper(self):
        def require(value,reason):
            if not value:raise ValueError(reason)
        return SimpleNamespace(INTERNAL_SCOPES={'original'},INTERNAL_SOURCES={'a.py'},require=require,
            trusted=lambda p:b'reviewed',digest=lambda p:'new-pin')
    def test_only_reviewed_source_pins_and_release_identity_change(self):
        prior=self.fixture();before=deepcopy(prior)
        i,c,a=stage.preserved(prior,Path('/immutable/new/source'),self.helper())
        self.assertEqual(prior,before);self.assertEqual(c,before['customer_policy'])
        i['lifecycle']['source_hashes']=before['internal_policy']['lifecycle']['source_hashes'];a['release_sha']='old'
        self.assertEqual(i,before['internal_policy']);self.assertEqual(a,before['internal_activation'])
    def test_closed_changed_or_test_authority_is_never_implicitly_enabled(self):
        for kind in ['closed','extra','test','customer']:
            with self.subTest(kind=kind):
                p=self.fixture()
                if kind=='closed':p['internal_policy']['lifecycle']['enabled']=False
                if kind=='extra':p['internal_policy']['lifecycle']['real_scopes'].append('new')
                if kind=='test':p['internal_policy']['lifecycle']['test_scopes']=['TEST']
                if kind=='customer':p['customer_policy']['external_enabled']=True
                with self.assertRaises(ValueError):stage.preserved(p,Path('/immutable/new/source'),self.helper())
