from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parents[1] / 'apps/workflow-api'))
from workflow.automation.acquisition_store import AcquisitionStore
from workflow.automation.action_evidence import ActionEvidence
import storage
import lifecycle

NOW = datetime(2026, 11, 14, 21, tzinfo=timezone.utc)


class Fixture:
    def __init__(self, base):
        self.root = Path(base); self.database = self.root / 'existing.db'
        self.policy = {**storage.POLICY, 'allowlisted_roots': [str(self.root / p) for p in ('artifacts', 'temporary', 'disposable-previews')]}
        for p in self.policy['allowlisted_roots']: Path(p).mkdir(mode=0o700)
        self.store = AcquisitionStore(self.database)
        with self.store.connect(): pass
        with ActionEvidence(self.database).connect() as db: ActionEvidence.setup(db)
        self.counter = 0

    def add(self, days=31, path=None, **extra):
        self.counter += 1; path = path or f'campaigns/service/en/social/draft/post-{self.counter}.txt'
        root = self.root / {'temporary_test': 'temporary', 'private_staging': 'disposable-previews'}.get(extra.get('lifecycle_class'), 'artifacts')
        data = f'original disposable text {self.counter}'.encode(); relative = f'item-{self.counter}.txt'
        p = root / relative; p.write_bytes(data); p.chmod(0o600)
        at = NOW - timedelta(days=days); os.utime(p, (at.timestamp(), at.timestamp()))
        item = {'path': relative, 'local_root': str(root), 'logical_path': path,
                'sha256': sha256(data).hexdigest(), 'bytes': len(data), 'status': 'DRAFT_ONLY', **extra}
        self.store.record('CONTENT_ASSET', item, source=storage.SOURCE, native_id=item['sha256'], url='https://opticable.ca/', now=at)
        return item, p

    def connect(self):
        return sqlite3.connect(self.database)

    def plan(self, now=NOW):
        with self.connect() as db: return lifecycle.plan(db, self.root, now, os.getuid(), self.policy)

    def budget(self, now=NOW, free=60 * storage.GIB):
        with self.connect() as db: return storage.admission(db, self.root, now, self.policy, free_bytes=free)

    def decision(self, item, choice='APPROVE'):
        with ActionEvidence(self.database).connect() as db:
            ActionEvidence.append(db, 'review:' + item['sha256'], 'business_review_decision',
                                  {'id': item['sha256'], 'choice': choice, 'at': NOW.isoformat()}, NOW)


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.f = Fixture(self.tmp.name)

    def test_thirty_day_boundary_uses_latest_file_and_metadata_interaction(self):
        a, p = self.f.add(days=30)
        self.assertEqual(self.f.plan()['eligible_files'], 1)
        os.utime(p, (NOW.timestamp(), NOW.timestamp()))
        self.assertEqual(self.f.plan()['eligible_files'], 0)

    def test_every_protected_record_excluded(self):
        for key in storage.POLICY['protected'] + ['business_private','published','legal_hold','incident_hold','test_hold']:
            self.f.add(**{key: True})
        for choice in ('APPROVE','REJECT','REQUEST_REVISION','COMMENT'):
            a, _ = self.f.add(); self.f.decision(a, choice)
        self.f.add(path='business-work/quote-review/client.txt')
        self.f.add(path='archives/audit.json')
        self.f.add(path='analytics/performance.json')
        self.assertEqual(self.f.plan()['eligible_files'], 0)
        self.assertTrue(all(r['action'] == 'KEEP' for r in self.f.plan()['rows']))

    def test_expired_approval_is_still_a_permanent_hold(self):
        a, _ = self.f.add(days=365); self.f.decision(a)
        self.assertEqual(self.f.plan(NOW + timedelta(days=365))['eligible_files'], 0)

    def test_revision_request_is_pending_and_refreshes_interaction_without_disposal(self):
        a, _ = self.f.add(days=40); self.f.decision(a, 'REQUEST_REVISION')
        self.assertEqual(self.f.budget()['active_pending_items'], 1)
        self.assertIn(storage.semantic(a), self.f.budget()['pending_semantics'])
        self.assertEqual(self.f.plan()['eligible_files'], 0)

    def test_seven_day_temp_and_fourteen_day_staging_need_explicit_release(self):
        for kind, days in (('temporary_test', 7), ('private_staging', 14)):
            for offset in (-1, 0):
                self.f.add(days=days+offset, lifecycle_class=kind, disposable=True, in_use=False, evidence_required=False)
            self.f.add(days=50, lifecycle_class=kind)
        self.assertEqual(self.f.plan()['eligible_files'], 2)

    def test_unresolved_action_or_test_reference_is_a_hold(self):
        a, _ = self.f.add()
        with ActionEvidence(self.f.database).connect() as db:
            ActionEvidence.append(db, 'incident:unresolved', 'new_incident_kind', {'required_file': a['path']}, NOW)
        self.assertEqual(self.f.plan()['eligible_files'], 0)

    def test_unknown_unregistered_file_is_never_a_candidate(self):
        (self.f.root / 'temporary' / 'old-unknown').write_bytes(b'keep')
        self.assertEqual(self.f.plan()['eligible_files'], 0)

    def test_symlink_leaf_and_parent_never_followed(self):
        a, p = self.f.add(); p.unlink(); p.symlink_to('/etc/passwd')
        self.assertEqual(self.f.plan()['rows'][0]['action'], 'MANUAL_REVIEW')
        with self.assertRaises(OSError):
            with lifecycle.directory(p, {0, os.getuid()}): pass

    def test_hardlinks_and_modified_bytes_are_excluded(self):
        a, p = self.f.add(); os.link(p, p.with_suffix('.link'))
        b, q = self.f.add(); q.write_bytes(b'altered')
        self.assertEqual(self.f.plan()['eligible_files'], 0)

    def test_path_escape_and_wrong_registry_root_rejected(self):
        a, _ = self.f.add()
        for fields in ({'path':'../escape'}, {'path':'/etc/passwd'}, {'local_root':'/var/backups/optibrain'}, {'path':'.quarantine/file'}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                lifecycle.allowed({**a, **fields}, self.f.policy, self.f.root)

    def test_wrong_file_owner_excluded(self):
        self.f.add()
        with self.f.connect() as db:
            self.assertEqual(lifecycle.plan(db, self.f.root, NOW, 123456, self.f.policy)['eligible_files'], 0)

    def test_daily_toronto_and_rolling_168_hour_caps(self):
        for i in range(2): self.f.add(days=0)
        self.assertIn('daily_marketing_cap', self.f.budget()['pause_reasons'])
        for i in range(8): self.f.add(days=2)
        self.assertIn('rolling_seven_day_cap', self.f.budget(NOW + timedelta(days=1))['pause_reasons'])
        self.assertEqual(self.f.budget(NOW + timedelta(days=8))['marketing_slots'], 2)

    def test_pending_limit_and_expiry_are_distinct_from_file_deletion(self):
        for i in range(30): self.f.add(days=1)
        self.assertIn('pending_review_cap', self.f.budget()['pause_reasons'])
        b = self.f.budget(NOW + timedelta(days=31))
        self.assertEqual(b['active_pending_items'], 0)
        self.assertEqual(len(b['pending_semantics']), 30)
        self.assertTrue(all(p.is_file() for p in (self.f.root / 'artifacts').iterdir()))

    def test_minimum_free_disk_has_early_pause_margin(self):
        for free in (25, 34, 35): self.assertTrue(self.f.budget(free=free*storage.GIB)['disk_paused'])
        self.assertFalse(self.f.budget(free=36*storage.GIB)['disk_paused'])

    def test_disposable_limit_counts_preview_and_quarantine(self):
        preview = self.f.root / 'website-preview'; preview.mkdir()
        with (preview / 'sparse').open('wb') as f: f.truncate(1800 * 1024**2)
        self.assertIn('disposable_pause_margin', self.f.budget()['pause_reasons'])

    def test_reservation_survives_interruption_and_completion_does_not_double_charge(self):
        with ActionEvidence(self.f.database).connect() as db:
            aid, v = storage.reserve(db, 'exact-key', self.f.budget(), NOW)
        self.assertEqual(self.f.budget()['marketing_slots'], 0)
        with ActionEvidence(self.f.database).connect() as db: storage.complete(db, aid, v, [], NOW)
        self.assertEqual(self.f.budget()['marketing_slots'], 2)

    def test_duplicate_semantics_ignore_dates_weeks_and_slot_numbers(self):
        a = {'logical_path':'campaigns/2026-W47/camera/fr/facebook/draft/day-1.txt'}
        b = {'logical_path':'campaigns/2026-W48/camera/fr/facebook/draft/day-7.txt'}
        self.assertEqual(storage.semantic(a), storage.semantic(b))
        self.assertNotEqual(storage.semantic(a), storage.semantic({**b, 'logical_path': b['logical_path'].replace('/fr/', '/en/')}))

    def test_selection_blocks_optional_and_duplicate_but_keeps_business(self):
        a, _ = self.f.add(days=1)
        b = self.f.budget(); b.update(optional_paused=True, marketing_slots=0)
        files = {a['logical_path']: b'changed draft', 'planning/2026-11-14/next.json': b'new useful analysis',
                 'business-work/response/client.txt': b'prepare lead follow-up'}
        selected, _ = storage.select(files, [], {'storage_budget': b})
        self.assertNotIn(a['logical_path'], selected)
        self.assertIn('business-work/response/client.txt', selected)
        self.assertIn('planning/2026-11-14/next.json', selected)

    def test_feedback_revision_consumes_same_marketing_budget(self):
        a, _ = self.f.add(days=10); self.f.decision(a, 'REQUEST_REVISION')
        item = {'logical_path': a['logical_path'], 'revision_of': a['sha256']}
        ctx = {'storage_budget': self.f.budget(), 'feedback':[{'asset_sha256': a['sha256'], 'choice':'REQUEST_REVISION'}]}
        selected, _ = storage.select({a['logical_path']: b'improved'}, [item], ctx)
        self.assertEqual(len(selected), 1)
        ctx['storage_budget']['marketing_slots'] = 0
        self.assertEqual(storage.select({a['logical_path']: b'improved'}, [item], ctx)[0], {})

    def test_no_admission_no_files_and_full_disk_selects_nothing(self):
        with self.assertRaises(ValueError): storage.select({'x':b'x'}, [], {})
        self.assertEqual(storage.select({'business-work/a': b'x'}, [], {'storage_budget':self.f.budget(free=24*storage.GIB)})[0], {})

    def test_no_approval_means_no_quarantine_or_delete(self):
        self.f.add(); q = self.f.root / 'q'
        with patch('lifecycle.os.geteuid', return_value=0):
            result = lifecycle.execute(self.f.database, self.f.root, NOW, os.getuid(), self.f.policy,
                                       approval_path=self.f.root/'absent.json', quarantine=q)
        self.assertEqual(result['state'], 'APPROVAL_REQUIRED'); self.assertFalse(q.exists())

    def test_dry_run_does_not_modify_database_or_files(self):
        self.f.add(); before = sha256(self.f.database.read_bytes()).hexdigest()
        self.assertEqual(self.f.plan()['eligible_files'], 1)
        self.assertEqual(before, sha256(self.f.database.read_bytes()).hexdigest())
        self.assertEqual(self.f.plan()['immediate_free_space_savings'], 0)

    def test_existing_monitor_emits_pause_and_error_through_existing_alerts(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location('candidate_resource_monitor', HERE/'resource_manager.py')
        monitor=importlib.util.module_from_spec(spec);spec.loader.exec_module(monitor)
        sample={'available':60*storage.GIB,'mem_available':10*storage.GIB,'inode_free_fraction':1,'databases':[],
            'backup_age_hours':1,'healthy':True,'queues':{'status':'measured','queues':{}},
            'business_storage':{'optional_paused':True,'pause_reasons':['pending_review_cap']}}
        alerts=monitor.assess(sample,None,None)
        self.assertTrue(any(x['key']=='business_storage' and 'pending_review_cap' in x['reason'] for x in alerts))
        sample['business_storage']={'state':'ERROR'}
        self.assertTrue(any(x['key']=='business_storage' for x in monitor.assess(sample,None,None)))


def root_integration():
    """Actual root custody/rename/unlink tests on synthetic isolated data only."""
    assert os.geteuid() == 0
    with tempfile.TemporaryDirectory(prefix='optibrain-lifecycle-synthetic-') as base:
        f = Fixture(base); a, p = f.add(); q = f.root / 'quarantine'; auth = f.root / 'approval.json'
        auth.write_text(json.dumps({'schema':1,'actor':'owner:opticable','approved_at':NOW.isoformat(),
            'policy_sha256':storage.digest(f.policy),'cleanup_code_sha256':lifecycle.code_digest(),
            'quarantine_enabled':True,'permanent_deletion_enabled':True})); auth.chmod(0o600)
        (f.root / 'fixture-policy.json').write_text(json.dumps(f.policy))
        def execute(now=NOW): return lifecycle.execute(f.database, f.root, now, 0, f.policy, approval_path=auth, quarantine=q)
        def fresh(now=NOW):
            import subprocess
            return json.loads(subprocess.check_output([sys.executable, '-I', '-B', str(Path(__file__).resolve()),
                '--root-reconcile', str(f.root), now.isoformat()], text=True))
        # Crash AFTER rename, BEFORE QUARANTINED receipt. Intent is committed.
        real = lifecycle.no_replace
        def crash(*args): real(*args); raise RuntimeError('synthetic interruption after rename')
        with patch('lifecycle.no_replace', side_effect=crash):
            try: execute(); raise AssertionError('fault not injected')
            except RuntimeError: pass
        assert not p.exists() and len(list(q.iterdir())) == 1
        assert fresh()['quarantined'] == 1
        assert execute(NOW + timedelta(days=6, hours=23))['deleted'] == 0
        # Crash AFTER unlink, BEFORE deletion receipt. DELETE_INTENT persists.
        real_event = lifecycle.event
        def event_crash(db, aid, v, now):
            if v['state'] == 'DELETED': raise RuntimeError('synthetic interruption after unlink')
            return real_event(db, aid, v, now)
        with patch('lifecycle.event', side_effect=event_crash):
            try: execute(NOW + timedelta(days=7)); raise AssertionError('fault not injected')
            except RuntimeError: pass
        assert not list(q.iterdir())
        assert fresh(NOW + timedelta(days=7))['deleted'] == 1
        assert fresh(NOW + timedelta(days=8))['deleted'] == 0
        # Fresh process sees final receipt; audit trigger rejects receipt removal.
        with f.connect() as db:
            state = lifecycle.latest(db, storage.operation_id(a)); assert state['state'] == 'DELETED'
            try: db.execute('DELETE FROM action_evidence'); raise AssertionError('receipt mutation permitted')
            except sqlite3.IntegrityError: pass
        # Interaction arriving during quarantine blocks final deletion forever.
        a, p = f.add(); assert execute()['quarantined'] == 1; f.decision(a, 'COMMENT')
        assert execute(NOW + timedelta(days=30))['deleted'] == 0
        # Wrong policy/code approval cannot authorize even a rename.
        a, p = f.add(); value = json.loads(auth.read_text()); value['cleanup_code_sha256'] = '0'*64; auth.write_text(json.dumps(value))
        assert execute()['state'] == 'APPROVAL_REQUIRED' and p.exists()
        # Actual installed recovery function, redirected to an isolated runtime.
        import admin_storage
        import tarfile
        runtime=f.root/'rollback-runtime';runtime.mkdir(); monitor=f.root/'monitor.py'
        ledger=f.root/'rollback-ledger';ledger.mkdir();(runtime/'engine.py').write_bytes(b'original-engine')
        (runtime/'manifest.json').write_bytes(b'original-manifest');monitor.write_bytes(b'original-monitor')
        hook=f.root/'fixture-hook';hook.write_bytes(b'original-hook')
        old={p.name:admin_storage.digest(p) for p in runtime.iterdir()}
        archive=ledger/'pre-storage-runtime.tar.gz'
        with tarfile.open(archive,'w:gz') as tar:
            for p in runtime.iterdir():tar.add(p,arcname='runtime/'+p.name)
            tar.add(monitor,arcname='resource_manager.py');tar.add(hook,arcname='business-artifacts.conf')
        admin_storage.save(ledger/'checkpoint.json',{'archive_sha256':admin_storage.digest(archive),
            'runtime':old,'monitor_sha256':admin_storage.digest(monitor)})
        (runtime/'engine.py').write_bytes(b'new-engine');(runtime/'storage.py').write_bytes(b'new-storage')
        (runtime/'lifecycle.py').write_bytes(b'new-lifecycle');monitor.write_bytes(b'new-monitor')
        marker=f.root/'newer-business-data';marker.write_bytes(b'preserve-newer-business-data')
        admin_storage.restore(ledger,runtime,monitor,f.root/'policy.json')
        assert all(admin_storage.digest(runtime/name)==h for name,h in old.items())
        assert not (runtime/'storage.py').exists() and not (runtime/'lifecycle.py').exists()
        assert marker.read_bytes()==b'preserve-newer-business-data' and monitor.read_bytes()==b'original-monitor'
    print(json.dumps({'root_isolated_lifecycle':'PASS','crash_after_rename':'PASS','crash_after_unlink':'PASS',
        'quarantine_seven_days':'PASS','late_comment_hold':'PASS','duplicate_deletion':'PASS',
        'immutable_receipts':'PASS','changed_approval':'PASS','actual_isolated_rollback':'PASS','production_files_deleted':0}))


if __name__ == '__main__':
    if sys.argv[1:] == ['--root-integration']: root_integration()
    elif len(sys.argv) == 4 and sys.argv[1] == '--root-reconcile':
        root = Path(sys.argv[2]); policy = json.loads((root / 'fixture-policy.json').read_text())
        print(json.dumps(lifecycle.execute(root / 'existing.db', root, storage.timestamp(sys.argv[3]), 0, policy,
            approval_path=root / 'approval.json', quarantine=root / 'quarantine')))
    else: unittest.main()
