import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('passive_observer',ROOT/'ops/phase14/passive_recovery_observer.py')
observer=importlib.util.module_from_spec(spec);spec.loader.exec_module(observer)


class PassiveTests(unittest.TestCase):
    def test_api_unavailable_keeps_supervisor_passive_and_preserves_other_health(self):
        observation={'observed_at':'2026-11-13T22:00:00+00:00','source_sha':'a'*40,
            'source_matches_registration':True,'services':{'api':{'healthy':False},'pdf':{'healthy':True}},'simulation':True}
        result=observer.evaluate(observation)
        self.assertEqual(result['state'],'ACTION_REQUIRED')
        self.assertEqual(result['unhealthy_services'],['api'])
        for key in ('production_repairs_enabled','rollback_enabled','restart_enabled'):
            self.assertIs(result[key],False)
        self.assertEqual(result['database_restores'],0)

    def test_healthy_observation_does_not_authorize_repairs(self):
        value={'observed_at':'2026-11-13T22:00:00+00:00','source_sha':'a'*40,'source_matches_registration':True,'services':{'api':{'healthy':True}}}
        self.assertEqual(observer.evaluate(value)['state'],'VERIFIED')
        value['source_matches_registration']=False
        self.assertEqual(observer.evaluate(value)['state'],'ACTION_REQUIRED')

    def test_inventory_content_and_ownership_are_checked_before_runtime_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'a.py').write_text('value=1\n');(root/'a.py').chmod(0o444)
            manifest={'main_api_included':False,'source_sha':'a'*40,'files':{'a.py':observer.hashlib.sha256((root/'a.py').read_bytes()).hexdigest()}}
            (root/'manifest.json').write_text(json.dumps(manifest));(root/'manifest.json').chmod(0o444)
            dependencies={'files':{}}
            (root/'dependencies.json').write_text(json.dumps(dependencies));(root/'dependencies.json').chmod(0o444)
            (root/'passive_child.py').write_text('pass\n');(root/'passive_child.py').chmod(0o444)
            policy={'manifest_sha256':observer.canonical(manifest),'runtime_source_sha':'a'*40,'dependencies_sha256':observer.canonical(dependencies),'passive_child_sha256':observer.hashlib.sha256((root/'passive_child.py').read_bytes()).hexdigest()}
            # Production path ownership is independently tested by the root installation preflight.
            with patch.object(observer,'trusted',lambda *a,**k:None):
                observer.verify_runtime(root,policy)
                (root/'a.py').chmod(0o644);(root/'a.py').write_text('value=2\n');(root/'a.py').chmod(0o444)
                with self.assertRaises(ValueError):observer.verify_runtime(root,policy)

    def test_only_passive_cli_operation_exists(self):
        import subprocess,sys
        for action in ('repair','restart','rollback','deploy'):
            child=subprocess.run([sys.executable,'-I','-B',str(ROOT/'ops/phase14/passive_recovery_observer.py'),action],capture_output=True)
            self.assertNotEqual(child.returncode,0)

    def test_no_live_api_or_repair_runner_is_imported(self):
        import ast
        tree=ast.parse((ROOT/'ops/phase14/passive_recovery_observer.py').read_text())
        self.assertFalse(any(isinstance(n,ast.ImportFrom) and (n.module or '').endswith('.api') for n in ast.walk(tree)))
        child=(ROOT/'ops/phase14/passive_recovery_child.py').read_text()
        for method in ('.deploy(','.restart(','.rollback('):self.assertNotIn(method,child)
