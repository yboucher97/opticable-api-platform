from datetime import timedelta
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from workflow.automation.acquisition_store import digest
from workflow.automation.action_evidence import ActionEvidence
from workflow.automation.operational_recovery import DevelopmentScope, recovery_holds
from workflow.automation.readiness_refresh import ARGV,RELEASE,SERVICE,SIGNALS,ReadinessRefreshAdapter,run_exact
from test_operational_recovery import NOW,grant


class RefreshTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);grant(self.root);self.scope=DevelopmentScope(self.root)
        self.audit=ActionEvidence(self.root/'existing-journal.sqlite')
        with self.audit.connect() as db:self.audit.setup(db)
        self.target=self.root/'status.json';self.before=b'{"old":true}\n';self.target.write_bytes(self.before)
        self.policy={'enabled':True,'authority':'ROOT_REVIEWED_READINESS_ADAPTER_V1','source_sha':RELEASE}
        self.permit={'approved':True,'authority':'OWNER_EXACT_READINESS_REFRESH','operation_id':'fixture-refresh-001',
            'service':SERVICE,'playbook_id':'refresh-local-readiness','argv':list(ARGV),'maximum_attempts':1,
            'execution_timeout_seconds':45,'cooldown_seconds':900,'policy_sha256':digest(self.policy),
            'source_sha':RELEASE,'starts_at':NOW.isoformat(),'expires_at':(NOW+timedelta(hours=1)).isoformat(),
            'configuration_checkpoint_sha256':'a'*64,'sampler_identity_sha256':'b'*64}
        self.evidence={k:True for k in ('root_policy_verified','root_grant_verified','runtime_pin_verified','45_flags_off','76_settings_unchanged','no_inflight_business_effects','no_recovery_hold','audit_integrity_verified','sampler_idle','observations_stale','configuration_checkpoint_verified')}
        self.evidence.update(source_sha=RELEASE,observed_at=NOW.isoformat(),configuration_checkpoint_sha256='a'*64,
            sampler_identity_sha256='b'*64,sampler_invocation_id='existing-timer-id',resource_observed_at=(NOW-timedelta(hours=2)).isoformat())
        self.calls=0

    def command(self,argv, *, bad=False, racing=False):
        self.assertEqual(tuple(argv),ARGV);self.calls+=1
        # A real isolated process persists output; no production sampler/systemd call.
        value={'captured_at':NOW.isoformat(),'deployment_sha':RELEASE,'provider_calls':0,'mutations':0,
            'resource_observed_at':self.evidence['resource_observed_at'],
            'signals':[{'name':name,'state':'ACTION REQUIRED' if name=='Off-host backup' else 'OK'} for name in sorted(SIGNALS)]}
        if bad:value['resource_observed_at']=NOW.isoformat()
        subprocess.run([sys.executable,'-I','-B','-c','import pathlib,sys;pathlib.Path(sys.argv[1]).write_text(sys.argv[2])',str(self.target),json.dumps(value)],check=True)
        self.evidence['observations_stale']=False
        if racing:self.evidence['sampler_invocation_id']='timer-started-during-attempt'
        return {'sampled_at':NOW.isoformat(),'signals':len(SIGNALS)}

    def adapter(self,command=None):
        return ReadinessRefreshAdapter(self.scope,self.audit,target=self.target,policy=self.policy,grant=self.permit,
            evidence=lambda:dict(self.evidence),command=command or self.command,clock=lambda:NOW)

    def test_actual_fixture_write_verified_without_fabricating_source_or_clearing_problems(self):
        result=self.adapter().execute(self.permit['operation_id']);self.assertEqual(result['state'],'VERIFIED')
        data=json.loads(self.target.read_text());self.assertEqual(data['resource_observed_at'],self.evidence['resource_observed_at'])
        self.assertEqual(next(v['state'] for v in data['signals'] if v['name']=='Off-host backup'),'ACTION REQUIRED')
        self.assertEqual(result['database_restores'],0)
        with self.audit.connect() as db:
            with self.assertRaises(Exception):db.execute('DELETE FROM action_envelopes')

    def test_duplicate_operation_and_cooldown_never_execute_again(self):
        adapter=self.adapter();adapter.execute(self.permit['operation_id']);self.evidence['observations_stale']=True
        self.assertEqual(adapter.execute(self.permit['operation_id'])['state'],'ALREADY_FINAL')
        self.permit['operation_id']='fixture-refresh-002'
        self.assertEqual(adapter.execute(self.permit['operation_id'])['state'],'COOLDOWN');self.assertEqual(self.calls,1)

    def test_bad_output_archived_and_only_prior_derived_snapshot_restored(self):
        result=self.adapter(lambda argv:self.command(argv,bad=True)).execute(self.permit['operation_id'])
        self.assertEqual(result['state'],'FAILED');self.assertTrue(result['prior_derived_snapshot_restored'])
        self.assertEqual(self.target.read_bytes(),self.before);self.assertTrue(recovery_holds(self.audit))

    def test_timer_race_preserves_newer_output_and_stops(self):
        result=self.adapter(lambda argv:self.command(argv,racing=True)).execute(self.permit['operation_id'])
        self.assertTrue(result['ambiguous']);self.assertFalse(result['prior_derived_snapshot_restored'])
        self.assertNotEqual(self.target.read_bytes(),self.before);self.assertTrue(recovery_holds(self.audit))

    def test_timeout_is_ambiguous_and_blocks_repeat(self):
        def failed(argv):raise TimeoutError('fixture')
        adapter=self.adapter(failed);result=adapter.execute(self.permit['operation_id'])
        self.assertTrue(result['ambiguous']);self.assertEqual(adapter.execute(self.permit['operation_id'])['state'],'ALREADY_FINAL')

    def test_disabled_expired_wrong_release_action_and_evidence_refused_before_effect(self):
        from copy import deepcopy
        original=deepcopy(self.permit)
        for key,value in [('approved',False),('source_sha','f'*40),('argv',['systemctl','restart','api']),('maximum_attempts',2),('expires_at',NOW.isoformat()),('operation_id','another-operation')]:
            self.permit.clear();self.permit.update(original);self.permit[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):self.adapter().execute('fixture-refresh-001')
        self.permit.clear();self.permit.update(original);self.evidence['45_flags_off']=False
        with self.assertRaises(ValueError):self.adapter().execute('fixture-refresh-001')
        self.assertEqual(self.calls,0);self.assertEqual(self.target.read_bytes(),self.before)

    def test_real_command_boundary_rejects_every_other_operation(self):
        for argv in [('/usr/bin/systemctl','restart','api'),(*ARGV,'--extra'),('/bin/sh','-c','true')]:
            with self.subTest(argv=argv),self.assertRaises(ValueError):run_exact(argv)

    def test_lost_audit_completion_holds_different_operation_after_cooldown(self):
        from unittest.mock import patch
        adapter=self.adapter()
        with patch.object(self.audit,'finish',side_effect=OSError('isolated journal interruption')):
            with self.assertRaises(OSError):adapter.execute(self.permit['operation_id'])
        later=NOW+timedelta(seconds=1000);self.evidence.update(observations_stale=True,observed_at=later.isoformat())
        self.permit['operation_id']='fixture-refresh-after-interruption';adapter.clock=lambda:later
        self.assertEqual(adapter.execute(self.permit['operation_id'])['state'],'AMBIGUOUS_PRIOR_OPERATION_HOLD')
        self.assertEqual(self.calls,1)

    def test_future_entrypoint_has_no_unprivileged_or_arbitrary_target_route(self):
        import importlib.util
        root=Path(__file__).resolve().parents[3];path=root/'ops/phase14/readiness_refresh_entrypoint.py'
        child=subprocess.run([sys.executable,'-I','-B',str(path),'--operation-id','fixture-operation'],capture_output=True)
        self.assertNotEqual(child.returncode,0)
        spec=importlib.util.spec_from_file_location('future_readiness_entrypoint',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        for name in ('../../etc/secret','evidence/other.before','evidence/readiness-refresh:xyz.before'):
            with self.assertRaises(ValueError):module.RootScope().write(name,b'x')
