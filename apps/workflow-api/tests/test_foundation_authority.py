from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[3]

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value

authority=load('foundation_authority','ops/phase15/recovery_authority.py')
runtime=load('foundation_runtime','ops/phase14/runtime_snapshot.py')
release=load('foundation_release','deploy/manual-guarded-release.py')
NOW=datetime(2026,10,4,tzinfo=timezone.utc)

class RecoveryAuthorityTests(unittest.TestCase):
    def test_enabled_archive_preserves_destinations_but_cannot_restore_authority(self):
        archived={'schema':1,'enabled':True,'release_sha':'a'*40,'source_sha256':'b'*64,
                  'eligible_after':NOW.isoformat(),'expires_at':(NOW+timedelta(days=1)).isoformat(),
                  'validated_families':{'qualified_lead':{'passed':True,'mode':'PROVIDER_VALIDATION_ONLY'}},
                  'destinations':{kind:{'account_id':'6808491878','action_id':str(i),'status':'ENABLED',
                                       'currency_code':'CAD','value_basis':'NO_VALUE',
                                       'local_enabled':True,'allowed_event_keys':['event-1']}
                                  for i,kind in enumerate(('qualified_lead','estimate_accepted','invoice_paid'))}}
        before=deepcopy(archived);restored=authority.reset_conversion_authority(archived)
        self.assertEqual(before,archived)
        self.assertEqual(restored['validated_families'],archived['validated_families'])
        self.assertFalse(restored['enabled']);self.assertIsNone(restored['release_sha']);self.assertIsNone(restored['expires_at'])
        self.assertEqual(authority.verify_conversion_disabled(restored)['configured_destinations'],3)
        for kind,d in restored['destinations'].items():
            self.assertEqual(d['action_id'],archived['destinations'][kind]['action_id'])
            self.assertFalse(d['local_enabled']);self.assertEqual(d['allowed_event_keys'],[])
        self.assertEqual(authority.reset_conversion_authority(restored),restored)
        self.assertEqual(runtime.authority_summary(restored,'conversion',NOW)['authority'],'NOT AUTHORIZED')
    def test_empty_and_corrupt_archives_fail_closed(self):
        self.assertFalse(authority.reset_conversion_authority()['enabled'])
        for value in ({}, {'schema':1,'destinations':[]}, {'schema':1,'destinations':{'x':True}}):
            with self.subTest(value=value),self.assertRaises(ValueError):authority.reset_conversion_authority(value)
        for value in ({'schema':1,'enabled':True,'destinations':{}},
                      {'schema':1,'enabled':False,'destinations':{'x':{'local_enabled':True,'allowed_event_keys':[]}}}):
            with self.assertRaises(ValueError):authority.verify_conversion_disabled(value)
    def test_active_disabled_expired_and_missing_window_are_distinct(self):
        policy={'activated_at':(NOW-timedelta(days=1)).isoformat(),
                'expires_at':(NOW+timedelta(days=1)).isoformat(),'real_scopes':['a','b'],'enabled':True}
        self.assertEqual(runtime.authority_summary({'lifecycle':policy},'internal',NOW)['operation_state'],'ACTIVE')
        self.assertEqual(runtime.authority_summary({'lifecycle':{**policy,'enabled':False}},'internal',NOW)['operation_state'],'DISABLED')
        self.assertEqual(runtime.authority_summary({'lifecycle':{**policy,'expires_at':NOW.isoformat()}},'internal',NOW)['operation_state'],'EXPIRED')
        self.assertEqual(runtime.authority_summary({'lifecycle':{**policy,'expires_at':None}},'internal',NOW)['authority'],'NOT AUTHORIZED')
        customer={**policy,'external_enabled':True}
        self.assertEqual(runtime.authority_summary(customer,'customer',NOW)['configured'],2)
        self.assertEqual(runtime.authority_summary(customer,'customer',NOW)['authority'],'AUTHORIZED')

class ReadOnlyReleaseTests(unittest.TestCase):
    def test_same_sha_checks_pins_without_authority_or_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);app=root/'apps/workflow-api';app.mkdir(parents=True)
            p=app/'fixture.py';p.write_text('known source\n')
            manifest=root/'manifest.json';manifest.write_text(json.dumps({'candidate_sha':'a'*40,
                             'source_hashes':{'fixture.py':hashlib.sha256(p.read_bytes()).hexdigest()}}))
            before={x:x.read_bytes() for x in root.rglob('*') if x.is_file()}
            calls=[]
            def read(*args,**kwargs):
                calls.append(args);return 'a'*40 if args[-2:]==('rev-parse','HEAD') else ''
            with patch.object(release,'PROD',root),patch.object(release,'MANIFEST',manifest),\
                 patch.object(release.os,'geteuid',return_value=0),patch.object(release,'run',side_effect=read),\
                 patch.object(release,'health',return_value=True),patch.object(release,'candidate_version',return_value='1.21.0'),\
                 patch.object(release,'verify_closed') as guard,patch.object(release,'atomic') as write,\
                 patch.object(release,'read_private') as grants:
                result=release.verify_current('a'*40)
                guard.assert_not_called();write.assert_not_called();grants.assert_not_called()
                with self.assertRaisesRegex(RuntimeError,'requires_current_sha'):release.verify_current('b'*40)
            self.assertTrue(result['read_only']);self.assertEqual(result['authority_changes'],0)
            self.assertEqual(before,{x:x.read_bytes() for x in root.rglob('*') if x.is_file()})
            self.assertTrue(all('fetch' not in args and 'restart' not in args and 'reset' not in args for args in calls))
    def test_changing_release_still_stops_at_closed_writer_guard(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(release,'ROOT',Path(tmp)),\
             patch.object(release.os,'geteuid',return_value=0),patch.object(release.os,'open',return_value=1),\
             patch.object(release.fcntl,'flock'),patch.object(release,'verify_closed',side_effect=RuntimeError('scoped_lifecycle_writers_enabled')),\
             patch.object(release,'run') as calls:
            with self.assertRaisesRegex(RuntimeError,'scoped_lifecycle'):release.main('b'*40)
            calls.assert_not_called()

if __name__=='__main__':unittest.main()
