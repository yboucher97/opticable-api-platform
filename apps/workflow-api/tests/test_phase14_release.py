import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('phase14_release',Path(__file__).resolve().parents[3]/'deploy/manual-guarded-release.py')
release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)


class ReleaseTests(unittest.TestCase):
    def test_ci_requires_repository_main_event_exact_head_and_success(self):
        good=dict(head_sha='a'*40,conclusion='success',name='Validate API Platform',repository={'full_name':release.REPO},head_branch='main',event='push')
        release.validate_ci(good,'a'*40)
        for key,value in [('head_sha','b'*40),('conclusion','failure'),('repository',{'full_name':'foreign/repo'}),('head_branch','candidate'),('event','pull_request')]:
            with self.subTest(key=key),self.assertRaises(RuntimeError):release.validate_ci({**good,key:value},'a'*40)
    def test_version_and_source_pins_are_extracted_as_data_and_keep_writers_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);app=root/'apps/workflow-api/workflow';app.mkdir(parents=True)
            (app/'api.py').write_text('API_VERSION="1.12.0"\nraise RuntimeError("must never execute")\n')
            (app/'phase7_registration.py').write_text('_PINNED_SOURCES=frozenset({"workflow/api.py"})\n')
            manifest=root/'manifest.json';env=root/'environment';env.write_text('OPTIBRAIN_PHASE7_RELEASE_SHA='+('b'*40)+'\n')
            value={'candidate_sha':'b'*40,'business_actions_enabled':True,'create_approval_id':'f'*32,'create_request_hash':'f'*64,'crm_approval_id':'f'*32,'outbound_approval_id':'f'*32}
            with patch.object(release,'PROD',root),patch.object(release,'MANIFEST',manifest),patch.object(release,'ENV',env):
                release.pin_manifest('a'*40,value)
            saved=json.loads(manifest.read_text())
            self.assertEqual(saved['api_version'],'1.12.0');self.assertFalse(saved['business_actions_enabled'])
            self.assertIsNone(saved['create_approval_id']);self.assertIsNone(saved['outbound_approval_id'])
            self.assertEqual(saved['source_hashes']['workflow/api.py'],release.sha(app/'api.py'))
    def test_receipt_has_schema_tests_migration_services_timers_safety_and_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name in ('automation.db','phase9-form-receipts.db','phase9-intake.db','phase10-service-events.db','phase12-autonomy.db'):
                with sqlite3.connect(root/name) as db:db.execute('CREATE TABLE fixture(value)')
            auth={'ci_run_id':1,'validation':{'passed':True,'tests':840},'backup_archive':'fixture.tar.gz','backup_sha256':'f'*64}
            with patch.object(release,'run',return_value='active'),patch.object(release,'candidate_version',return_value='1.12.0'):
                value=release.runtime_receipt('a'*40,'b'*40,auth,db_root=root)
            self.assertEqual(value['schema'],1);self.assertEqual(value['type'],'optibrain.release')
            self.assertEqual(value['migration_state']['active_databases'],5);self.assertEqual(len(value['timer_health']),5)
            self.assertEqual(value['rollback']['sha'],'b'*40);self.assertFalse(value['safety_flags']['real_canary_allowed'])
            self.assertEqual(value['tests']['tests'],840)
            with patch.object(release,'run',return_value='inactive'):
                with self.assertRaisesRegex(RuntimeError,'regression'):release.runtime_receipt('a'*40,'b'*40,auth,db_root=root)


if __name__=='__main__':unittest.main()
