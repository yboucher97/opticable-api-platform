"""The captured shutdown policy must not fail or initialize lifecycle work."""
from copy import deepcopy
import importlib.util
import io
import json
from pathlib import Path
import sys
from contextlib import redirect_stdout
from unittest.mock import patch
import unittest

from workflow.automation import lifecycle_control as lc

ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('pr133_launcher',ROOT/'ops/phase16_17/lifecycle_runner.py')
launcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(launcher)


class ClosedLifecycleTests(unittest.TestCase):
    def setUp(self):
        # Exact schema/body emitted by the installed --stop at 15:01:36.911 UTC.
        self.closed={'schema':1,'test_writes_enabled':False,
                     'allowed_actions':['crm.task.create'],'real_canary_allowed':False}

    def scoped(self):
        return {**self.closed,'schema':2,'lifecycle':{
            'enabled':False,'test_run':'original-run','test_scopes':[],'real_scopes':[],
            'activated_at':'original-cutoff','approved_sources':['ai_website'],
            'expires_at':'original-expiry','source_hashes':{},'phase16_checkpoint_sha256':'original'}}

    def test_original_transport_still_rejects_the_captured_off_policy(self):
        # Do not weaken the transport gate to make a stopped service healthy.
        with patch.object(lc,'trusted_json',return_value=self.closed):
            with self.assertRaisesRegex(ValueError,'Lifecycle requires strict scoped mutation policy'):
                lc.read_policy()

    def test_closed_once_and_dry_run_skip_all_lifecycle_initialization(self):
        for value in (self.closed,self.scoped()):
            for mode in ('--once','--dry-run'):
                with self.subTest(schema=value['schema'],mode=mode):
                    before=deepcopy(value);output=io.StringIO()
                    def trusted(path):
                        if path==launcher.POLICY:return b'{}'
                        if path==launcher.CONTROL:return json.dumps(value).encode()
                        raise AssertionError('Unexpected filesystem read')
                    # Any workflow/provider import after the OFF check fails.
                    with patch.object(launcher.os,'geteuid',return_value=0), \
                         patch.object(launcher,'trusted',side_effect=trusted), \
                         patch.object(launcher,'verify',return_value=ROOT) as verify, \
                         patch.object(sys,'argv',['launcher',mode]), \
                         patch('builtins.__import__',side_effect=AssertionError('No lifecycle/provider import')), \
                         redirect_stdout(output):
                        launcher.main()
                    verify.assert_called_once_with({})
                    self.assertEqual(json.loads(output.getvalue()),{
                        'state':'DISABLED','eligible_leads':0,'effects_this_cycle':0,'provider_reads':0})
                    self.assertEqual(value,before)

    def test_enabled_ambiguous_or_malformed_policy_is_not_closed(self):
        values=[None,[],{}, {**self.closed,'extra':True}, {**self.closed,'schema':True},
                {**self.closed,'schema':3}, {**self.closed,'test_writes_enabled':0},
                {**self.closed,'test_writes_enabled':True}, {**self.closed,'real_canary_allowed':True},
                {**self.closed,'allowed_actions':['crm.lead.create']}, {**self.closed,'lifecycle':{}}]
        for key,bad in (('enabled',True),('enabled',0),('real_scopes',['crm.lead.intake']),
                        ('test_scopes',['crm.internal.task'])):
            value=self.scoped();value['lifecycle'][key]=bad;values.append(value)
        value=self.scoped();del value['lifecycle']['expires_at'];values.append(value)
        for value in values:
            with self.subTest(value=value):self.assertFalse(launcher.authority_closed(value))

    def test_runtime_and_policy_read_failures_are_not_hidden(self):
        for error in (ValueError('Pinned root source changed'),ValueError('Untrusted runtime file')):
            with self.subTest(error=str(error)), \
                 patch.object(launcher.os,'geteuid',return_value=0), \
                 patch.object(sys,'argv',['launcher','--once']), \
                 patch.object(launcher,'trusted',side_effect=error):
                with self.assertRaisesRegex(ValueError,str(error)):launcher.main()

    def test_malformed_json_remains_a_failure(self):
        with patch.object(launcher.os,'geteuid',return_value=0), \
             patch.object(sys,'argv',['launcher','--once']), \
             patch.object(launcher,'verify',return_value=ROOT), \
             patch.object(launcher,'trusted',side_effect=[b'{}',b'{invalid']):
            with self.assertRaises(json.JSONDecodeError):launcher.main()
