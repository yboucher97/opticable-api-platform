"""Manual staging helper checks; all authority/provider operations are fakes."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import Mock, patch

SPEC = importlib.util.spec_from_file_location('stage_runtime', Path(__file__).with_name('stage_runtime.py'))
stage = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(stage)
SHA = 'a'*40


class StagingChecks(unittest.TestCase):
    def test_exact_head_denies_wrong_sha_or_tracked_changes(self):
        with patch.object(stage, 'command', side_effect=[SHA+'\n', 'changed.py\n']):
            with self.assertRaisesRegex(ValueError, 'tracked source'): stage.exact_head(SHA)
        with patch.object(stage, 'command', return_value='b'*40):
            with self.assertRaisesRegex(ValueError, 'HEAD differs'): stage.exact_head(SHA)
        with self.assertRaisesRegex(ValueError, 'Exact release SHA'): stage.exact_head('main')

    def test_enabled_timer_or_running_service_blocks_staging(self):
        for response in ('ActiveState=active\nSubState=waiting\nUnitFileState=disabled\nLoadState=loaded\n',
                         'ActiveState=inactive\nSubState=dead\nUnitFileState=enabled\nLoadState=loaded\n'):
            with self.subTest(response=response), patch.object(stage, 'command', return_value=response):
                with self.assertRaises(ValueError): stage.idle_units()

    def test_archive_symlink_is_rejected_before_materialization(self):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode='w') as archive:
            item = tarfile.TarInfo('unsafe'); item.type = tarfile.SYMTYPE; item.linkname = '/etc/passwd'
            archive.addfile(item)
        with patch.object(stage, 'command', return_value=stream.getvalue()):
            with self.assertRaisesRegex(ValueError, 'links/devices'): stage.archive_files(SHA)

    def test_all_python_and_requirements_are_pinned(self):
        files = {'nested/helper.py': b'pass', 'apps/a/requirements.txt': b'pkg==1',
                 'apps/a/requirements-dev.txt': b'pytest', 'docs/history.md': b'history'}
        self.assertEqual(set(stage.pinned_files(files)), set(files)-{'docs/history.md'})

    def test_stop_keeps_customer_and_internal_kills_distinct(self):
        with patch.object(stage, 'trusted', return_value=b'checked'), patch.object(stage, 'command') as command:
            result = stage.stop('customer')
            self.assertEqual(result['families'], ['customer'])
            self.assertEqual(command.call_count, 1)
            self.assertIn(str(stage.LAUNCHERS['customer']), command.call_args.args[0])
            self.assertNotIn(str(stage.LAUNCHERS['internal']), command.call_args.args[0])


class ActivationChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.source = self.root/SHA/'source'
        app = self.source/'apps/workflow-api/workflow'; app.mkdir(parents=True)
        (app/'api.py').write_text('API_VERSION="1.14.0"\n')
        self.now = datetime.now(timezone.utc)
        old = {'enabled': True, 'test_run': 'real-internal-20261002-v1', 'test_scopes': [],
            'real_scopes': sorted(stage.ORIGINAL_SCOPES), 'activated_at': '2026-10-02T22:09:41+00:00',
            'expires_at': (self.now+timedelta(days=20)).isoformat(), 'approved_sources': ['ai_website'],
            'source_hashes': dict.fromkeys(stage.INTERNAL_SOURCES, 'old-hash'),
            'phase16_checkpoint_sha256': stage.digest(b'checkpoint')}
        self.snapshot = {'internal_policy': {'schema': 2, 'test_writes_enabled': False,
            'allowed_actions': ['crm.task.create'], 'real_canary_allowed': False, 'lifecycle': old},
            'internal_activation': {'family': 'REAL_LEAD_INTERNAL_AUTOMATION_V1', 'run': old['test_run'],
                'activated_at': old['activated_at'], 'approved_sources': old['approved_sources'],
                'scopes': old['real_scopes'], 'release_sha': 'b'*40},
            'customer_policy': {'test_run': 'controlled-test-run'}}
        self.phase18 = {'phase18': 'PASS', 'safety_critical_failures': 0, 'passed_families': sorted(stage.CUSTOMER_SCOPES)}
        self.phase19 = {'phase19_test': 'PASS', 'scenario_results': dict.fromkeys('ABCD', 'PASS'),
            'replay_get_only': True, **dict.fromkeys(('new_verified_provider_effects', 'financial_writes', 'customer_sends',
                'payment_mutations', 'duplicate_sites', 'duplicate_services', 'duplicate_folders', 'duplicate_installations', 'duplicate_tasks'), 0)}
        self.validation = {'passed': True, 'tests': 1108, 'failures': 0, 'errors': 0, 'skipped': 0,
            'blocked_network_attempts': 0, 'workflow_source_hashes': {'apps/workflow-api/workflow/api.py': stage.digest(b'checkpoint')}}
        self.send_state = {'schema': 1, 'effects': {'previous-test': {'mode': 'TEST_ONLY', 'family': 'customer.quote.reminder', 'state': 'verified'}}, 'holds': {}}
        self.release = {'sha': SHA, 'state': 'deployed', 'api_version': '1.14.0', 'writers_enabled': False, 'tests': {'passed': True}}
        self.paths = {stage.SNAPSHOT: self.snapshot, stage.INTERNAL/'activation.json': self.snapshot['internal_activation'],
            stage.INTERNAL/'phase16-checkpoint.json': {'phase16': 'PASS', 'safety_critical_failures': 0},
            stage.CUSTOMER/'phase18-checkpoint.json': self.phase18, stage.PHASE19: self.phase19,
            stage.VALIDATION: self.validation, stage.CUSTOMER/'state.json': self.send_state, stage.RECEIPT: self.release}
        self.patches = [patch.object(stage, 'load', side_effect=lambda path: deepcopy(self.paths[path])),
                        patch.object(stage, 'trusted', return_value=b'checkpoint')]
        for item in self.patches: item.start(); self.addCleanup(item.stop)

    def test_valid_native_gates_preserve_original_authority_and_send_state(self):
        values = stage.activation_inputs(self.source, self.now)
        self.assertEqual(values[0], self.snapshot)
        self.assertEqual(values[4], self.send_state)

    def test_missing_scope_expired_snapshot_or_case_scope_cannot_arm(self):
        original = deepcopy(self.snapshot)
        for mutation in ('missing', 'expired', 'case'):
            with self.subTest(mutation=mutation):
                self.snapshot.clear(); self.snapshot.update(deepcopy(original))
                old = self.snapshot['internal_policy']['lifecycle']
                if mutation == 'missing': old['real_scopes'].remove('crm.site.prepare')
                elif mutation == 'case': old['real_scopes'].append('crm.case.prepare')
                else: old['expires_at'] = (self.now-timedelta(seconds=1)).isoformat()
                with self.assertRaises(ValueError): stage.activation_inputs(self.source, self.now)

    def test_unproven_family_replay_effect_or_changed_workflow_denies(self):
        original = deepcopy(self.phase18), deepcopy(self.phase19), deepcopy(self.validation)
        for mutation in ('family', 'replay', 'source', 'network'):
            with self.subTest(mutation=mutation):
                for current, saved in zip((self.phase18, self.phase19, self.validation), original):
                    current.clear(); current.update(deepcopy(saved))
                if mutation == 'family': self.phase18['passed_families'].pop()
                elif mutation == 'replay': self.phase19['new_verified_provider_effects'] = 1
                elif mutation == 'source': self.validation['workflow_source_hashes']['apps/workflow-api/workflow/api.py'] = 'wrong'
                else: self.validation['blocked_network_attempts'] = 1
                with self.assertRaises(ValueError): stage.activation_inputs(self.source, self.now)

    def activate(self, fail=False):
        written = []; response = io.StringIO(json.dumps({'status': 'ok', 'version': '1.14.0'})); response.status = 200
        def atomic(path, value, **kwargs):
            written.append((path, deepcopy(value), kwargs))
            if fail and path == stage.CUSTOMER_POLICY and value['external_enabled']: raise OSError('Injected config write failure')
        with patch.object(stage, 'EVIDENCE', self.root), patch.object(stage, 'CUSTOMER', self.root/'customer'), \
             patch.object(stage, 'exact_head'), patch.object(stage, 'closed'), patch.object(stage, 'idle_units'), \
             patch.object(stage, 'manifest_matches', return_value=(self.source, {})), \
             patch.object(stage, 'activation_inputs', return_value=(deepcopy(self.snapshot), self.phase18, self.phase19, self.validation, self.send_state)), \
             patch.object(stage.urllib.request, 'urlopen', return_value=response), patch.object(stage, 'atomic', side_effect=atomic), \
             patch.object(stage.grp, 'getgrnam', return_value=Mock(gr_gid=99)):
            if fail:
                with self.assertRaises(OSError): stage.activate(SHA)
                result = None
            else: result = stage.activate(SHA)
        return result, written

    def test_activation_preserves_cutoff_expiry_adds_only_proven_scope_and_never_starts_timer(self):
        result, written = self.activate()
        internal = next(value for path, value, _ in written if path == stage.INTERNAL_POLICY)
        customer = next(value for path, value, _ in written if path == stage.CUSTOMER_POLICY)
        self.assertEqual(set(internal['lifecycle']['real_scopes']), stage.ORIGINAL_SCOPES|{'crm.service.activate'})
        for key in ('test_run', 'activated_at', 'expires_at', 'approved_sources'):
            self.assertEqual(internal['lifecycle'][key], self.snapshot['internal_policy']['lifecycle'][key])
        self.assertNotIn('crm.case.prepare', internal['lifecycle']['real_scopes'])
        self.assertEqual(set(customer['real_scopes']), stage.CUSTOMER_SCOPES)
        self.assertFalse(customer['test_enabled']); self.assertEqual(customer['per_family_limit'], 10)
        self.assertEqual(timestamp(customer['expires_at'])-timestamp(customer['activated_at']), timedelta(days=30))
        self.assertEqual(result['timers_started'], 0); self.assertEqual(len(result['dry_run_commands']), 2)
        self.assertFalse(any(path.name in ('state.json', 'ownership.json') for path, _, _ in written))

    def test_partial_policy_failure_closes_both_without_overwriting_final_activation_receipt(self):
        _, written = self.activate(fail=True)
        final = {path: value for path, value, _ in written}
        self.assertFalse(final[stage.INTERNAL_POLICY]['lifecycle']['enabled'])
        self.assertFalse(final[stage.CUSTOMER_POLICY]['external_enabled'])
        self.assertFalse(any(path.name == 'runtime-activation-'+SHA+'.json' for path in final))


timestamp = stage.timestamp
if __name__ == '__main__': unittest.main()
