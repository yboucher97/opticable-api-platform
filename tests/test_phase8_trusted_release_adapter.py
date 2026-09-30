"""Focused one-shot staging and source-bound recovery checks; no live mutation."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
from unittest import TestCase, mock
from types import SimpleNamespace
import io
import json

from test_phase8_static_release_gates import fixtures, gates, iso

PATH = Path(__file__).resolve().parents[1] / "ops/phase8/trusted_release_adapter.py"
spec = importlib.util.spec_from_file_location("phase8_trusted_adapter", PATH)
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)
GateError = adapter.gates.GateError


def snapshots():
    now = datetime.now(timezone.utc)
    authority, first = fixtures()
    _, third = fixtures("prepromotion")
    authority["issued_at"] = iso(now - timedelta(minutes=5))
    authority["expires_at"] = iso(now + timedelta(minutes=30))
    packets = [deepcopy(first), deepcopy(first), third]
    for index, packet in enumerate(packets):
        packet["observed_at"] = iso(now - timedelta(seconds=6 - index * 2))
        for key in ("baseline_backup", "candidate_backup"):
            if packet[key] is not None:
                packet[key]["created_at"] = iso(now - timedelta(minutes=20))
                packet[key]["restore_at"] = iso(now - timedelta(minutes=10))
    return authority, packets


class Collector:
    def __init__(self, packets):
        self.packets = packets
        self.calls = []

    def observe(self, authority, stage):
        self.calls.append(stage)
        return deepcopy(self.packets.pop(0))


class Executor:
    def __init__(self, authority, fail=False):
        self.authority = authority
        self.fail = fail
        self.claimed = False
        self.stage_calls = 0

    def claim_once(self, release_id, candidate):
        assert release_id == self.authority["release_id"] and candidate == gates.CANDIDATE
        if self.claimed:
            return False
        self.claimed = True
        return True

    def stage_exact(self, candidate, baseline, release_id):
        self.stage_calls += 1
        if self.fail:
            raise RuntimeError("ambiguous_stage_result")
        return {"candidate": candidate, "baseline": baseline,
                "release_id": release_id, "result": "STAGED"}


class AdapterTest(TestCase):
    def test_ordered_exact_stage_and_no_permission(self):
        authority, packets = snapshots()
        collector = Collector(packets)
        executor = Executor(authority)
        with mock.patch.object(adapter, "require_installed_identity"), \
             mock.patch.object(adapter.gates, "verify_installed_artifacts"), \
             mock.patch.object(adapter.gates, "read_root_private", return_value=authority):
            result = adapter.GuardedStagingAdapter(collector, executor).stage_once()
        self.assertEqual(result["result"], "STAGED_VERIFIED")
        self.assertFalse(result["main_promotion_authorized"])
        self.assertEqual(executor.stage_calls, 1)
        self.assertEqual(collector.calls, ["prestage_identity", "baseline_recovery",
                                           "prepromotion_identity"])

    def test_bad_recovery_blocks_before_stage(self):
        authority, packets = snapshots()
        packets[1]["baseline_backup"]["offhost_sha256"] = "b" * 64
        executor = Executor(authority)
        with mock.patch.object(adapter, "require_installed_identity"), \
             mock.patch.object(adapter.gates, "verify_installed_artifacts"), \
             mock.patch.object(adapter.gates, "read_root_private", return_value=authority):
            with self.assertRaises(GateError):
                adapter.GuardedStagingAdapter(Collector(packets), executor).stage_once()
        self.assertEqual(executor.stage_calls, 0)

    def test_bad_poststage_recovery_is_terminal(self):
        authority, packets = snapshots()
        packets[2]["candidate_backup"]["restore_isolated"] = False
        executor = Executor(authority)
        with mock.patch.object(adapter, "require_installed_identity"), \
             mock.patch.object(adapter.gates, "verify_installed_artifacts"), \
             mock.patch.object(adapter.gates, "read_root_private", return_value=authority):
            subject = adapter.GuardedStagingAdapter(Collector(packets), executor)
            with self.assertRaisesRegex(GateError, "candidate_recovery_unproven"):
                subject.stage_once()
            with self.assertRaisesRegex(GateError, "staging_attempt_already_recorded"):
                subject.stage_once()
        self.assertEqual(executor.stage_calls, 1)

    def test_ambiguous_result_blocks_retry_even_new_adapter(self):
        authority, packets = snapshots()
        executor = Executor(authority, fail=True)
        with mock.patch.object(adapter, "require_installed_identity"), \
             mock.patch.object(adapter.gates, "verify_installed_artifacts"), \
             mock.patch.object(adapter.gates, "read_root_private", return_value=authority):
            subject = adapter.GuardedStagingAdapter(Collector(deepcopy(packets)), executor)
            with self.assertRaisesRegex(RuntimeError, "ambiguous_stage_result"):
                subject.stage_once()
            with self.assertRaisesRegex(GateError, "staging_attempt_already_recorded"):
                subject.stage_once()
            second = adapter.GuardedStagingAdapter(Collector(deepcopy(packets)), executor)
            with self.assertRaisesRegex(GateError, "staging_attempt_already_recorded"):
                second.stage_once()
        self.assertEqual(executor.stage_calls, 1)

    def test_remote_ref_must_be_unique_and_exact(self):
        value = gates.CANDIDATE + "\trefs/heads/" + gates.BRANCH
        self.assertEqual(adapter.exact_ref(value, "refs/heads/" + gates.BRANCH), gates.CANDIDATE)
        for wrong in (value + "\n" + value, gates.BASELINE + "\trefs/heads/main", ""):
            with self.assertRaises(GateError):
                adapter.exact_ref(wrong, "refs/heads/" + gates.BRANCH)

    def test_branch_copy_cannot_stage(self):
        authority, packets = snapshots()
        executor = Executor(authority)
        with self.assertRaisesRegex(GateError, "branch_adapter_cannot_stage"):
            adapter.GuardedStagingAdapter(Collector(packets), executor).stage_once()
        self.assertEqual(executor.stage_calls, 0)

    def test_backup_sources_must_match_archive_bytes(self):
        now = datetime.now(timezone.utc)
        generation = "20260930T003000Z"
        release_id = "phase8-20260930-abcdefgh"
        raw = b"offline archive bytes"
        digest = __import__("hashlib").sha256(raw).hexdigest()
        manifest = {"generation": generation, "manifest_production_sha": gates.BASELINE,
                    "created_at": iso(now - timedelta(minutes=20)), "preserve_existing": True,
                    "retention_hold": True, "capacity_verified": True}
        offhost = {"generation": generation, "source_sha256": digest,
                   "verification_status": "download_hash_verified"}
        restore = {"generation": generation, "archive_sha256": digest,
                   "restored_at": iso(now - timedelta(minutes=10)), "result": "PASS",
                   "isolated": True, "journal_dedupe_result": "PASS"}
        def read_json(path):
            return {"baseline-backup.json": manifest, "baseline-offhost.json": offhost,
                    "baseline-restore.json": restore}[path.name]
        member = SimpleNamespace(name="generation-" + generation + "/manifest.json",
                                 size=100, isfile=lambda: True)
        fake_tar = mock.MagicMock()
        fake_tar.__enter__.return_value = fake_tar
        fake_tar.getmembers.return_value = [member]
        embedded = json.dumps({"production_git_sha": gates.BASELINE,
                               "timestamp": generation}).encode()
        fake_tar.extractfile.side_effect = lambda member: io.BytesIO(embedded)
        with mock.patch.object(adapter, "private_json", side_effect=read_json), \
             mock.patch.object(adapter, "protected_sha", return_value=digest), \
             mock.patch.object(adapter.tarfile, "open", return_value=fake_tar), \
             mock.patch.object(adapter, "protected_bytes", return_value=(digest + "  /var/backups/optibrain/optibrain-backup-" + generation + ".tar.gz\n").encode()):
            value = adapter.backup_from_sources(release_id, "baseline", gates.BASELINE, now)
            self.assertEqual(value["archive_sha256"], digest)
            offhost["source_sha256"] = "b" * 64
            with self.assertRaisesRegex(GateError, "baseline_source_mismatch"):
                adapter.backup_from_sources(release_id, "baseline", gates.BASELINE, now)
