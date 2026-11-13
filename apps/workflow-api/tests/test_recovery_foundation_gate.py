import ast
import importlib.util
from pathlib import Path
import unittest
import tempfile
import hashlib
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('foundation_release_gate',ROOT/'deploy/manual-guarded-release.py')
gate=importlib.util.module_from_spec(spec);spec.loader.exec_module(gate)


class FoundationGateTests(unittest.TestCase):
    def test_new_bridge_remains_blocked_without_private_passive_policy(self):
        with patch.object(gate,'read_private',side_effect=RuntimeError('policy absent')):
            with self.assertRaises(RuntimeError):gate.recovery_validator()

    def test_bridge_does_not_relax_main_ci_or_exact_recovery_requirements(self):
        ci={'head_sha':'a'*40,'conclusion':'success','name':'Validate API Platform',
            'repository':{'full_name':'yboucher97/opticable-api-platform'},'head_branch':'release/production-integration-v2-20261113','event':'pull_request'}
        with self.assertRaises(RuntimeError):gate.validate_ci(ci,'a'*40)
        with self.assertRaises(RuntimeError):gate.validate_release_recovery({},'b'*40,'a'*40)

    def test_bridge_verifies_capsule_before_importing_validator(self):
        source=(ROOT/'deploy/manual-guarded-release.py').read_text();tree=ast.parse(source)
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='recovery_validator')
        code=ast.get_source_segment(source,node)
        self.assertLess(code.index('module.verify_runtime'),code.index('from workflow.automation.release_recovery'))
        self.assertNotIn('module.activate()',code)

    def test_rollback_accepts_only_exact_candidate_files_and_link(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);env=root/'env';manifest=root/'manifest';venv=root/'candidate-venv';venv.mkdir()
            env.write_bytes(b'exact-environment');manifest.write_bytes(b'exact-manifest');live=root/'live';live.symlink_to(venv)
            expected={'candidate_sha':'a'*40,'env_sha256':hashlib.sha256(env.read_bytes()).hexdigest(),
                'manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest(),'venv':str(venv)}
            def command(*args):return 'a'*40 if args[-2:]==('rev-parse','HEAD') else ''
            with patch.object(gate,'run',command):gate.require_rollback_state(expected,env=env,manifest=manifest,live=live)
            env.write_bytes(b'NEWER_CREDENTIAL_CONFIGURATION')
            with patch.object(gate,'run',command),self.assertRaises(RuntimeError):
                gate.require_rollback_state(expected,env=env,manifest=manifest,live=live)
            self.assertEqual(env.read_bytes(),b'NEWER_CREDENTIAL_CONFIGURATION')

    def test_unknown_source_and_incomplete_checkpoint_stop_before_rollback(self):
        with self.assertRaises(RuntimeError):gate.require_rollback_state(None)
        with patch.object(gate,'run',return_value='newer-source'),self.assertRaises(RuntimeError):
            gate.require_rollback_state({'candidate_sha':'a'*40})
