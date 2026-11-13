"""Real isolated Git/files/SQLite/process exercises; no live provider or service."""
from copy import deepcopy
from datetime import timedelta
import hashlib
import io
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from test_operational_recovery import NOW, grant
from workflow.automation.acquisition_store import digest
from workflow.automation.operational_recovery import DevelopmentScope, RecoveryCoordinator
from workflow.automation.release_recovery import (
    RecoverySupervisor, ExistingR2Reader, verify_checkpoint, validate_contract, contract_digest, file_sha, REPOSITORY)
from workflow.automation.release_recovery import build_recovery_capsule, verify_recovery_capsule

GOOD = b'import json,sqlite3,sys\nwith sqlite3.connect(sys.argv[1]) as db: n=db.execute("SELECT COUNT(*) FROM business_history").fetchone()[0]\nprint(json.dumps({"status":"ok","rows":n,"version":"good"}))\n'
BROKEN = b'def deliberately_broken(\n'
HEALTHY = GOOD.replace(b'"good"', b'"candidate"')


class ReleaseFixture:
    def __init__(self, root, candidate=BROKEN):
        self.root = root;grant(root)
        self.scope = DevelopmentScope(root);self.repo = root / 'source';self.repo.mkdir()
        self.git('init', '-q');self.git('config', 'user.name', 'OptiBrain fixture')
        self.git('config', 'user.email', 'fixture@localhost')
        (self.repo / 'service.py').write_bytes(GOOD)
        self.git('add', 'service.py');self.git('commit', '-qm', 'known good fixture')
        self.good = self.git('rev-parse', 'HEAD')
        (self.repo / 'service.py').write_bytes(candidate)
        self.git('add', 'service.py');self.git('commit', '-qm', 'candidate fixture')
        self.candidate = self.git('rev-parse', 'HEAD');self.candidate_code = candidate
        (root / 'release').mkdir();(root / 'release/service.py').write_bytes(GOOD)
        (root / 'release/service.py').chmod(0o644)
        self.database = root / 'state.sqlite'
        with sqlite3.connect(self.database) as db:
            db.execute('CREATE TABLE business_history(id PRIMARY KEY,value)')
            db.execute('INSERT INTO business_history VALUES(1,"before-deployment")')
        # Real consistent SQLite backup and isolated archive restoration below.
        snapshot = root / 'snapshot.sqlite'
        with sqlite3.connect(self.database) as source, sqlite3.connect(snapshot) as dest:source.backup(dest)
        self.archive = root / 'fixture.tar.gz'
        with tarfile.open(self.archive, 'w:gz') as archive:
            data = tarfile.TarInfo('service.py');data.size = len(GOOD);archive.addfile(data, io.BytesIO(GOOD))
            archive.add(snapshot, arcname='snapshot.sqlite')
        # Header-shaped deterministic fixture bytes, never represented as real AGE encryption.
        self.cipher = b'age-encryption.org/v1\nFIXTURE_NOT_REAL_ENCRYPTION\n' + self.archive.read_bytes()
        self.expected = dict(repository=REPOSITORY, last_good_sha=self.good, generation='20261112T195422Z',
            archive_sha256=file_sha(self.archive), ciphertext_sha256=hashlib.sha256(self.cipher).hexdigest(),
            remote_bytes=len(self.cipher), r2_bucket='optibrain-recovery-prod', r2_object_key='fixture/20261112T195422Z.age')
        self.closed = False;self.restore_calls = 0;self.insert_newer_business_row = True
        self.receipt = self.verify()
        # Actually exercise old code against additive/newer state before approval.
        with sqlite3.connect(self.database) as db:
            db.execute('ALTER TABLE business_history ADD COLUMN newer_field TEXT')
        compatibility = subprocess.run([sys.executable, '-I', '-B', str(root / 'release/service.py'), str(self.database)],
                                       capture_output=True, timeout=5)
        assert compatibility.returncode == 0
        self.contract = dict(schema=1, repository=REPOSITORY, environment='isolated-development',
            last_good_sha=self.good, candidate_sha=self.candidate, checkpoint_receipt_sha256=digest(self.receipt),
            database_restore_allowed=False, security_changes_allowed=False,
            compatibility_evidence=dict(kind='last_good_reads_current_schema', passed=True,
                last_good_sha=self.good, candidate_sha=self.candidate,
                evidence_sha256=hashlib.sha256(compatibility.stdout).hexdigest()),
            targets=[dict(path='service.py', mode=0o644, before_sha256=hashlib.sha256(GOOD).hexdigest(),
                          candidate_sha256=hashlib.sha256(candidate).hexdigest())])
        self.approve()

    def git(self, *args, binary=False):
        out = subprocess.check_output(['git', '-C', str(self.repo), '-c', 'core.hooksPath=/dev/null', *args], stderr=subprocess.DEVNULL)
        return out if binary else out.decode().strip()

    def git_file(self, commit, path):
        return self.git('show', commit + ':' + path, binary=True)

    def github(self, repo, sha):
        return dict(sha=sha, repository=repo, authenticated_read=True)

    def remote(self, bucket, key):
        return dict(authenticated=True, bucket=bucket, key=key, content_length=len(self.cipher),
                    chunks=[self.cipher[i:i+127] for i in range(0, len(self.cipher), 127)], close=self.close)

    def close(self):self.closed = True

    def restore(self, archive, expected_hash):
        self.restore_calls += 1
        assert file_sha(archive) == expected_hash
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'isolated.sqlite'
            with tarfile.open(archive) as saved:
                assert saved.extractfile('service.py').read() == GOOD
                target.write_bytes(saved.extractfile('snapshot.sqlite').read())
            with sqlite3.connect(target.as_uri() + '?mode=ro', uri=True) as db:
                assert db.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
                assert db.execute('SELECT COUNT(*) FROM business_history').fetchone()[0] == 1
        return dict(result='PASS', source_commit=self.good, source_extraction='PASS',
                    databases_restored=1, generation=self.expected['generation'])

    def verify(self, **overrides):
        args = dict(github_read=self.github, r2_read=self.remote, isolated_restore=self.restore, now=NOW)
        args.update(overrides)
        return verify_checkpoint(self.expected, self.archive, **args)

    def approve(self, **values):
        self.contract['configuration_checkpoint_sha256'] = digest([
            {k: t[k] for k in ('path', 'mode', 'before_sha256')} for t in self.contract['targets']])
        self.expected_digest = contract_digest(self.contract)
        self.contract['approval'] = dict(approved=True, authority='OWNER_ISOLATED_EXPERIMENT',
            contract_sha256=self.expected_digest, rollback_playbook='EXACT_CODE_CONFIG_ONCE_V1', maximum_rollbacks=1,
            starts_at=(NOW - timedelta(seconds=1)).isoformat(), expires_at=(NOW + timedelta(minutes=30)).isoformat(), **values)

    def health(self):
        code = (self.root / 'release/service.py').read_bytes()
        source = self.good if code == GOOD else self.candidate if code == self.candidate_code else 'UNKNOWN'
        if source == self.candidate and self.insert_newer_business_row:
            with sqlite3.connect(self.database) as db:
                db.execute('INSERT OR IGNORE INTO business_history(id,value) VALUES(2,"newer-live-record")')
        result = subprocess.run([sys.executable, '-I', '-B', 'service.py', str(self.database)], cwd=self.root / 'release',
                                env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'}, capture_output=True, timeout=5)
        try:body = json.loads(result.stdout)
        except ValueError:body = {}
        return dict(healthy=result.returncode == 0 and body.get('status') == 'ok', source_sha=source)

    def data_health(self):
        with sqlite3.connect(self.database.as_uri() + '?mode=ro', uri=True) as db:
            integrity = db.execute('PRAGMA quick_check').fetchone()[0]
            rows = db.execute('SELECT id,value FROM business_history ORDER BY id').fetchall()
        return dict(healthy=integrity == 'ok' and (1, 'before-deployment') in rows,
                    evidence_sha256=digest([integrity, rows]), database_restore_performed=False)

    def supervisor(self, **overrides):
        args = dict(expected_digest=self.expected_digest, git_file=self.git_file, probe=self.health,
                    data_probe=self.data_health, now=NOW)
        args.update(overrides)
        return RecoverySupervisor(self.scope, self.contract, self.receipt, **args)

    def business_rows(self):
        with sqlite3.connect(self.database) as db:return db.execute('SELECT id,value FROM business_history ORDER BY id').fetchall()


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.fixture = ReleaseFixture(Path(t.name))

    def test_complete_ciphertext_and_real_isolated_sqlite_restore_are_required(self):
        f = self.fixture
        self.assertTrue(f.closed);self.assertEqual(f.restore_calls, 1)
        self.assertTrue(f.receipt['authenticated_complete_readback'])
        self.assertEqual(f.receipt['isolated_restore'], 'PASS')
        self.assertFalse(f.receipt['offline_private_age_decryption'])

    def test_upload_acknowledgement_alone_is_not_recoverability(self):
        with self.assertRaises(ValueError):self.fixture.verify(r2_read=lambda *args: {'authenticated': False})

    def test_stalled_or_over_budget_backup_readback_is_closed_and_refused(self):
        f=self.fixture;closed=Mock()
        def remote(bucket,key):
            return dict(authenticated=True,bucket=bucket,key=key,content_length=len(f.cipher),
                        chunks=[b'',b'',b'',b''],close=closed)
        with self.assertRaises(ValueError):f.verify(r2_read=remote)
        closed.assert_called_once()
        with patch('workflow.automation.release_recovery.time.monotonic',side_effect=[0,181]):
            with self.assertRaisesRegex(ValueError,'budget'):f.verify()

    def test_wrong_github_commit_or_repository_refused(self):
        with self.assertRaises(ValueError):self.fixture.verify(github_read=lambda *args: dict(sha='a'*40, repository=REPOSITORY, authenticated_read=True))

    def test_truncated_and_modified_remote_object_refused(self):
        f = self.fixture
        for body in (f.cipher[:-1], b'X' + f.cipher[1:]):
            def remote(bucket, key):
                return dict(authenticated=True, bucket=bucket, key=key, content_length=len(f.cipher), chunks=[body])
            with self.assertRaises(ValueError):f.verify(r2_read=remote)

    def test_local_archive_change_refused_before_remote_call(self):
        f = self.fixture;f.archive.write_bytes(f.archive.read_bytes() + b'changed');remote = Mock()
        with self.assertRaises(ValueError):f.verify(r2_read=remote)
        remote.assert_not_called()

    def test_failed_or_wrong_source_restore_refused(self):
        for value in [dict(result='FAIL'), dict(result='PASS', source_commit='a'*40, source_extraction='PASS', databases_restored=1, generation='20261112T195422Z')]:
            with self.assertRaises(ValueError):self.fixture.verify(isolated_restore=lambda *args: value)

    def test_stream_closed_even_when_identity_or_authentication_rejected(self):
        close = Mock()
        with self.assertRaises(ValueError):self.fixture.verify(r2_read=lambda *args: dict(authenticated=False, close=close))
        close.assert_called_once()

    def test_future_or_stale_checkpoint_not_released(self):
        f = self.fixture
        for at in (NOW - timedelta(days=2), NOW + timedelta(seconds=1)):
            receipt = deepcopy(f.receipt);receipt['verified_at'] = at.isoformat()
            f.contract['checkpoint_receipt_sha256'] = digest(receipt);f.approve()
            with self.assertRaises(ValueError):validate_contract(f.contract, receipt, expected_digest=f.expected_digest, now=NOW)

    def test_protected_database_security_and_traversal_paths_refused(self):
        f = self.fixture
        for path in ['state.sqlite', 'history.db-wal', '../service.py', '/etc/config.conf', '.git/config',
                     '.github/workflows/deploy.yml', 'config/mutation-control.json', 'oauth.json', 'service.env', 'business_autonomy.py']:
            f.contract['targets'][0]['path'] = path;f.approve()
            with self.assertRaises(ValueError):validate_contract(f.contract, f.receipt, expected_digest=f.expected_digest, now=NOW)

    def test_exact_approval_expiry_and_one_rollback_are_required(self):
        f = self.fixture
        for key, value in [('approved', False), ('maximum_rollbacks', 2), ('maximum_rollbacks', True),
                           ('expires_at', NOW.isoformat()), ('contract_sha256', 'a'*64)]:
            f.approve();f.contract['approval'][key] = value
            with self.assertRaises(ValueError):f.supervisor()

    def test_newer_data_compatibility_evidence_is_required(self):
        f = self.fixture;f.contract.pop('compatibility_evidence');f.approve()
        with self.assertRaises(ValueError):f.supervisor()

    def test_relevant_configuration_checkpoint_is_required(self):
        f = self.fixture;f.contract['configuration_checkpoint_sha256'] = 'a' * 64
        f.expected_digest = contract_digest(f.contract)
        f.contract['approval']['contract_sha256'] = f.expected_digest
        with self.assertRaisesRegex(ValueError, 'checkpoint'):f.supervisor()

    def test_supervisor_and_release_guard_cannot_rollback_their_own_controls(self):
        f = self.fixture
        for path in ['deploy/manual-guarded-release.py',
                     'apps/workflow-api/workflow/automation/operational_recovery.py',
                     'apps/workflow-api/workflow/automation/release_recovery.py',
                     'apps/workflow-api/workflow/automation/defect_development.py',
                     'apps/workflow-api/workflow/automation/repair_catalog.py',
                     'ops/phase14/production_repair_catalog.json']:
            f.contract['targets'][0]['path'] = path;f.approve()
            with self.assertRaises(ValueError):f.supervisor()

    def test_existing_sigv4_client_is_reused_with_exact_complete_object_get(self):
        client = Mock();client.meta = SimpleNamespace(endpoint_url='https://' + 'a'*32 + '.r2.cloudflarestorage.com',
            config=SimpleNamespace(signature_version='s3v4'))
        client.head_object.return_value = {'ETag': 'fixture-etag'}
        body = Mock();body.iter_chunks.return_value = [b'fixture']
        client.get_object.return_value = {'Body': body, 'ContentLength': 7}
        result = ExistingR2Reader(client)('optibrain-recovery-prod', 'exact-object')
        self.assertEqual(list(result['chunks']), [b'fixture']);result['close']()
        client.get_object.assert_called_once_with(Bucket='optibrain-recovery-prod', Key='exact-object', IfMatch='fixture-etag')
        body.close.assert_called_once()
        client.meta.endpoint_url = 'https://unrelated.invalid'
        with self.assertRaises(ValueError):ExistingR2Reader(client)


class ProtectedCapsuleTests(unittest.TestCase):
    def test_existing_supervisor_runs_from_pinned_capsule_and_tampering_is_rejected(self):
        source=Path(__file__).resolve().parents[3]
        sha=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()
        with tempfile.TemporaryDirectory() as t:
            target=Path(t)/'protected-runtime';receipt=build_recovery_capsule(source,target,source_sha=sha)
            manifest=verify_recovery_capsule(target,expected_digest=receipt['manifest_sha256'])
            self.assertFalse(manifest['main_api_included']);self.assertFalse((target/'workflow/api.py').exists())
            result=subprocess.run([sys.executable,'-I','-B','-c',
                "import sys;sys.path.insert(0,sys.argv[1]);from workflow.automation.release_recovery import RecoverySupervisor;assert 'workflow.api' not in sys.modules;print('independent')",str(target)],
                capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            executable=target/'workflow/automation/release_recovery.py';executable.chmod(0o600)
            executable.write_text('raise RuntimeError("candidate tamper")\n');executable.chmod(0o444)
            with self.assertRaises(ValueError):verify_recovery_capsule(target,expected_digest=receipt['manifest_sha256'])


class ReleaseGateContractTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.fixture = ReleaseFixture(Path(t.name))
        root = Path(__file__).resolve().parents[3]
        spec = importlib.util.spec_from_file_location('guard_recovery_test', root/'deploy/manual-guarded-release.py')
        self.guard = importlib.util.module_from_spec(spec);spec.loader.exec_module(self.guard)

    def test_future_guard_requires_the_contract_even_when_other_release_checks_pass(self):
        with self.assertRaisesRegex(RuntimeError, 'contract_missing'):
            self.guard.validate_release_recovery({}, self.fixture.good, self.fixture.candidate)

    def test_guard_loads_only_private_external_receipts_bound_to_exact_release(self):
        f = self.fixture;f.contract['environment'] = 'production';f.approve()
        f.contract['approval']['authority'] = 'OWNER_EXACT_PRODUCTION_CHANGE'
        auth = dict(recovery_contract_file='/var/lib/optibrain/releases/recovery/fixture-contract.json',
            recovery_verification_file='/var/lib/optibrain/releases/recovery/fixture-recovery.json',
            recovery_contract_sha256=f.expected_digest, backup_sha256=f.expected['archive_sha256'])
        with patch.object(self.guard, 'read_private', side_effect=[f.contract, f.receipt]), \
                patch.object(self.guard, 'recovery_validator', return_value=validate_contract), \
                patch.object(self.guard, 'datetime', SimpleNamespace(now=lambda zone: NOW)):
            value = self.guard.validate_release_recovery(auth, f.good, f.candidate)
        self.assertEqual(value['last_good_sha'], f.good);self.assertFalse(value['database_restore_allowed'])
        auth['recovery_contract_file'] = '/home/ubuntu/candidate-owned.json'
        with self.assertRaisesRegex(RuntimeError, 'untrusted_recovery_reference'):
            self.guard.validate_release_recovery(auth, f.good, f.candidate)

    def test_guard_rejects_wrong_source_or_archive_before_code_changes(self):
        f = self.fixture
        auth = dict(recovery_contract_file='/var/lib/optibrain/releases/recovery/contract.json',
            recovery_verification_file='/var/lib/optibrain/releases/recovery/receipt.json',
            recovery_contract_sha256=f.expected_digest, backup_sha256='a'*64)
        with patch.object(self.guard, 'read_private', side_effect=[f.contract, f.receipt]):
            with self.assertRaisesRegex(RuntimeError, 'source_binding'):
                self.guard.validate_release_recovery(auth, f.good, f.candidate)


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.fixture = ReleaseFixture(Path(t.name))

    def test_broken_candidate_rolled_back_using_real_git_and_process_probe(self):
        f = self.fixture;s = f.supervisor();result = s.deploy(now=NOW)
        self.assertEqual(result['state'], 'ROLLED_BACK')
        self.assertEqual((f.root / 'release/service.py').read_bytes(), GOOD)
        self.assertEqual(f.business_rows(), [(1, 'before-deployment'), (2, 'newer-live-record')])
        self.assertFalse(result['database_restored']);self.assertTrue(f.health()['healthy'])
        self.assertEqual((f.root / 'release/service.py').stat().st_mode & 0o777, 0o644)
        self.assertTrue(s.audit.verify_integrity(s.action_id))

    def test_completed_rollback_cannot_reapply_bad_candidate(self):
        f = self.fixture;s = f.supervisor();s.deploy(now=NOW)
        self.assertEqual(s.deploy(now=NOW + timedelta(seconds=1))['state'], 'ALREADY_FINAL')
        self.assertEqual((f.root / 'release/service.py').read_bytes(), GOOD)

    def test_healthy_candidate_is_verified_without_rollback(self):
        with tempfile.TemporaryDirectory() as t:
            f = ReleaseFixture(Path(t), candidate=HEALTHY);s = f.supervisor()
            self.assertEqual(s.deploy(now=NOW)['state'], 'CANDIDATE_VERIFIED')
            self.assertEqual(s.check_deployment(now=NOW + timedelta(seconds=1))['state'], 'HEALTHY')

    def test_later_health_failure_is_independently_detected_and_rolled_back_once(self):
        with tempfile.TemporaryDirectory() as t:
            f = ReleaseFixture(Path(t), candidate=HEALTHY);s = f.supervisor()
            s.deploy(now=NOW)
            original = s.probe
            s.probe = lambda: dict(healthy=False, source_sha=f.candidate) if (f.root/'release/service.py').read_bytes()==HEALTHY else original()
            self.assertEqual(s.check_deployment(now=NOW + timedelta(seconds=2))['state'], 'ROLLED_BACK')
            self.assertEqual(s.check_deployment(now=NOW + timedelta(seconds=3))['state'], 'ALREADY_FINAL')
            self.assertEqual((f.root / 'release/service.py').read_bytes(), GOOD)
            self.assertEqual(len(f.business_rows()), 2)

    def test_prechange_or_newer_unknown_code_edit_is_preserved(self):
        f = self.fixture;(f.root / 'release/service.py').write_bytes(b'newer-unreviewed-code')
        with self.assertRaises(ValueError):f.supervisor().deploy(now=NOW)
        self.assertEqual((f.root / 'release/service.py').read_bytes(), b'newer-unreviewed-code')

    def test_candidate_cannot_forge_healthy_version_without_matching_hash(self):
        f = self.fixture;s = f.supervisor(probe=lambda: dict(healthy=True, source_sha=f.candidate))
        self.assertEqual(s.deploy(now=NOW)['state'], 'REJECTED')

    def test_unknown_edit_during_health_blocks_rollback_without_overwriting(self):
        f = self.fixture;original = f.health
        def probe():
            if (f.root / 'release/service.py').read_bytes() == BROKEN:
                (f.root / 'release/service.py').write_bytes(b'unrelated-newer-edit')
                return dict(healthy=False, source_sha=f.candidate)
            return original()
        s = f.supervisor(probe=probe)
        self.assertEqual(s.deploy(now=NOW)['state'], 'ROLLBACK_BLOCKED')
        self.assertEqual((f.root / 'release/service.py').read_bytes(), b'unrelated-newer-edit')
        with s.audit.connect(readonly=True) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM action_envelopes WHERE action_id LIKE 'incident:%'").fetchone()[0], 1)

    def test_failed_rollback_health_creates_incident_and_stops(self):
        f = self.fixture;calls = 0
        def probe():
            nonlocal calls
            calls += 1
            return f.health() if calls == 1 else dict(healthy=False, source_sha=f.good)
        s = f.supervisor(probe=probe)
        self.assertEqual(s.deploy(now=NOW)['state'], 'ROLLBACK_FAILED')
        self.assertEqual(s.recover_interrupted(now=NOW + timedelta(seconds=2))['state'], 'ALREADY_FINAL')

    def test_failed_rollback_blocks_a_different_repair_in_same_journal(self):
        from test_operational_recovery import observed
        f = self.fixture;calls = []
        def probe():
            calls.append(1)
            return f.health() if len(calls) == 1 else dict(healthy=False, source_sha=f.good)
        s = f.supervisor(probe=probe)
        self.assertEqual(s.deploy(now=NOW)['state'], 'ROLLBACK_FAILED')
        c = RecoveryCoordinator(f.scope, now=NOW)
        result = c.repair(observed(), {'expected': {'healthy': True}}, now=NOW)
        self.assertEqual(result['state'], 'RECOVERY_HOLD')
        self.assertFalse((f.root/'derived/status.json').exists())

    def test_http_health_without_independent_data_verification_cannot_pass(self):
        f = self.fixture
        with self.assertRaises(ValueError):f.supervisor(data_probe=None)
        s = f.supervisor(data_probe=lambda: {'healthy': True})
        self.assertEqual(s.deploy(now=NOW)['state'], 'REJECTED')

    def test_candidate_cannot_change_code_during_a_successful_probe(self):
        with tempfile.TemporaryDirectory() as t:
            f = ReleaseFixture(Path(t), candidate=HEALTHY)
            def probe():
                value = f.health()
                if value['source_sha'] == f.candidate:
                    (f.root/'release/service.py').write_bytes(b'unknown-edit-after-probe')
                return value
            s = f.supervisor(probe=probe)
            self.assertEqual(s.deploy(now=NOW)['state'], 'ROLLBACK_BLOCKED')
            self.assertEqual((f.root/'release/service.py').read_bytes(), b'unknown-edit-after-probe')

    def test_rollback_does_not_hide_corrupt_business_data_behind_healthy_code(self):
        f = self.fixture;health = f.health
        def probe():
            value = health()
            if value['source_sha'] == f.candidate:
                with sqlite3.connect(f.database) as db:
                    db.execute("UPDATE business_history SET value='candidate-corruption' WHERE id=1")
            return value
        s = f.supervisor(probe=probe)
        self.assertEqual(s.deploy(now=NOW)['state'], 'ROLLBACK_FAILED')
        self.assertEqual((f.root/'release/service.py').read_bytes(), GOOD)
        self.assertEqual(f.business_rows()[0], (1, 'candidate-corruption'))
        self.assertFalse(f.data_health()['healthy'])
        # Evidence is preserved; recovery must escalate, never overwrite the DB.
        self.assertEqual(s.recover_interrupted(now=NOW)['state'], 'ALREADY_FINAL')

    def test_interrupted_candidate_recovers_without_replaying_deployment(self):
        f = self.fixture;s = f.supervisor();original = s._write
        def crash(name, data):
            original(name, data)
            raise KeyboardInterrupt('fixture process loss')
        s._write = crash
        with self.assertRaises(KeyboardInterrupt):s.deploy(now=NOW)
        restarted = f.supervisor()
        self.assertEqual(restarted.recover_interrupted(now=NOW + timedelta(seconds=1))['state'], 'ROLLED_BACK')
        self.assertEqual((f.root / 'release/service.py').read_bytes(), GOOD)

    def test_fresh_supervisor_process_recovers_without_main_application_import(self):
        f = self.fixture;s = f.supervisor();write = s._write
        def crash(name, data):
            write(name, data)
            raise KeyboardInterrupt('deployment process exited')
        s._write = crash
        with self.assertRaises(KeyboardInterrupt):s.deploy(now=NOW)
        payload = f.root/'resume.json'
        payload.write_text(json.dumps(dict(contract=f.contract, receipt=f.receipt, expected_digest=f.expected_digest)))
        app = Path(__file__).resolve().parents[1]
        code = '''import sys,json,subprocess,sqlite3,hashlib
from pathlib import Path
from datetime import datetime
sys.path.insert(0,sys.argv[1])
from workflow.automation.operational_recovery import DevelopmentScope
from workflow.automation.release_recovery import RecoverySupervisor
from workflow.automation.acquisition_store import digest
root=Path(sys.argv[2]);v=json.loads((root/'resume.json').read_text());c=v['contract']
def blob(sha,name):return subprocess.check_output(['git','-C',str(root/'source'),'show',sha+':'+name])
def health():
 data=(root/'release/service.py').read_bytes()
 sha=c['last_good_sha'] if hashlib.sha256(data).hexdigest()==c['targets'][0]['before_sha256'] else c['candidate_sha']
 r=subprocess.run([sys.executable,'-I','-B',str(root/'release/service.py'),str(root/'state.sqlite')],capture_output=True,timeout=5)
 return dict(healthy=r.returncode==0,source_sha=sha)
def integrity():
 with sqlite3.connect((root/'state.sqlite').as_uri()+'?mode=ro',uri=True) as db:
  ok=db.execute('PRAGMA quick_check').fetchone()[0]=='ok'
  rows=db.execute('SELECT id,value FROM business_history ORDER BY id').fetchall()
 return dict(healthy=ok and (1,'before-deployment') in rows,evidence_sha256=digest(rows),database_restore_performed=False)
s=RecoverySupervisor(DevelopmentScope(root),c,v['receipt'],expected_digest=v['expected_digest'],git_file=blob,probe=health,data_probe=integrity,now=datetime.fromisoformat(sys.argv[3]))
result=s.recover_interrupted(now=datetime.fromisoformat(sys.argv[3]))
assert 'workflow.api' not in sys.modules
print(json.dumps(dict(result=result,main_application_imported=False,data=integrity())))
'''
        process = subprocess.run([sys.executable, '-I', '-B', '-c', code, str(app), str(f.root), NOW.isoformat()],
            env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'}, capture_output=True, text=True, timeout=20)
        self.assertEqual(process.returncode, 0, process.stderr)
        result = json.loads(process.stdout)
        self.assertEqual(result['result']['state'], 'ROLLED_BACK')
        self.assertFalse(result['main_application_imported']);self.assertTrue(result['data']['healthy'])
        self.assertEqual((f.root/'release/service.py').read_bytes(), GOOD)

    def test_production_execution_and_postapproval_contract_mutation_refused(self):
        f = self.fixture;f.contract['environment'] = 'production';f.approve()
        f.contract['approval']['authority'] = 'OWNER_EXACT_PRODUCTION_CHANGE'
        with self.assertRaises(ValueError):f.supervisor()
        f.contract['environment'] = 'isolated-development';f.approve();s = f.supervisor()
        f.contract['database_restore_allowed'] = True
        with self.assertRaises(ValueError):s.deploy(now=NOW)

    def test_approved_modes_are_atomic_and_health_rejects_mode_drift(self):
        f=self.fixture;s=f.supervisor()
        (f.root/'release/service.py').chmod(0o600)
        self.assertEqual(s.deploy(now=NOW)['state'],'REJECTED')
        with tempfile.TemporaryDirectory() as t:
            from unittest.mock import patch
            f=ReleaseFixture(Path(t));s=f.supervisor()
            import os
            original=os.fsync
            with patch('workflow.automation.operational_recovery.os.fsync',wraps=original) as sync:
                self.assertEqual(s.deploy(now=NOW)['state'],'ROLLED_BACK')
            self.assertGreaterEqual(sync.call_count,4)
            self.assertEqual((f.root/'release/service.py').stat().st_mode&0o777,0o644)

    def test_hard_process_exit_during_rollback_resumes_without_data_restore(self):
        f=self.fixture
        # Reuse the existing fixture in a child, preserving actual Git/SQLite
        # state. Abrupt exit after the fsynced preimage models interrupted power.
        payload=f.root/'crash.json';payload.write_text(json.dumps(dict(contract=f.contract,receipt=f.receipt,
            expected_digest=f.expected_digest,expected=f.expected,good=f.good,candidate=f.candidate)))
        app=Path(__file__).resolve().parents[1];tests=Path(__file__).resolve().parent
        code='''import sys,pathlib,json,os
sys.path[:0]=[sys.argv[1],sys.argv[2]]
from test_release_recovery import ReleaseFixture,BROKEN,NOW
from workflow.automation.operational_recovery import DevelopmentScope
root=pathlib.Path(sys.argv[3]);v=json.loads((root/'crash.json').read_text())
f=ReleaseFixture.__new__(ReleaseFixture);f.root=root;f.repo=root/'source';f.database=root/'state.sqlite';f.scope=DevelopmentScope(root)
for k in ['contract','receipt','expected_digest','expected','good','candidate']:setattr(f,k,v[k])
f.candidate_code=BROKEN;f.insert_newer_business_row=True
s=f.supervisor();write=s._write
def crash(name,data):
 write(name,data)
 if data!=BROKEN:os._exit(23)
s._write=crash;s.deploy(now=NOW)
'''
        r=subprocess.run([sys.executable,'-I','-B','-c',code,str(app),str(tests),str(f.root)],
            env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'},capture_output=True,text=True,timeout=20)
        self.assertEqual(r.returncode,23,r.stderr)
        s=f.supervisor();self.assertEqual(s.recover_interrupted(now=NOW+timedelta(seconds=1))['state'],'ROLLED_BACK')
        self.assertEqual(len(f.business_rows()),2);self.assertEqual((f.root/'release/service.py').read_bytes(),GOOD)

    def test_symlink_target_and_concurrent_supervisor_refused(self):
        f = self.fixture;p = f.root / 'release/service.py';p.unlink();p.symlink_to(f.repo / 'service.py')
        with self.assertRaises(ValueError):f.supervisor().deploy(now=NOW)
        p.unlink();p.write_bytes(GOOD)
        with f.scope.lock():
            with self.assertRaises(BlockingIOError):f.supervisor().deploy(now=NOW)


if __name__ == '__main__':unittest.main()
