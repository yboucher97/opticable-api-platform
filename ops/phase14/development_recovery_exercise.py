#!/usr/bin/env python3
"""Reproducible offline recovery/real-diagnostic-defect exercise; never installed.

Uses the regression fixtures deliberately. R2 transport/encryption in the small
rollback fixture is simulated and labelled; actual production recovery proofs
are maintained independently by the existing backup/upload/restore services.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'apps/workflow-api'), str(ROOT/'apps/workflow-api/tests')]
from workflow.automation.operational_recovery import DevelopmentScope
from workflow.automation.defect_development import prepare_defect
import test_release_recovery as release_fixture
from test_operational_recovery import grant

REGRESSION = b'''from datetime import datetime,timedelta,timezone
from pathlib import Path
import tempfile,sqlite3,unittest
from workflow.automation.store import AutomationStore
from workflow.automation.readiness import build_readiness
class RetainedQueueRegression(unittest.TestCase):
 def test_claimed_work_is_not_historical_only(self):
  now=datetime(2026,11,12,tzinfo=timezone.utc)
  with tempfile.TemporaryDirectory() as temporary:
   root=Path(temporary);store=AutomationStore(root/'automation.db')
   with sqlite3.connect(store.db_path) as db:
    for identity,status in [('old','failed'),('current','claimed')]:
     db.execute('INSERT INTO automation_runs(run_id,workflow_id,event_id,correlation_id,status,created_at) VALUES(?,?,?,?,?,?)',(identity,'fixture','fixture','fixture',status,(now-timedelta(days=2)).isoformat()))
   rows=build_readiness(store,{},api_version='fixture',auth_configured=True,runtime_path=root/'missing.json',now=now)['signals']
   queue=next(row for row in rows if row['name']=='Queue')
   self.assertEqual(queue['classification'],'CURRENT OR UNCLASSIFIED')
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--base-source', type=Path, required=True)
    parser.add_argument('--github-identity', type=Path, required=True)
    args = parser.parse_args()
    if os.geteuid() == 0:raise ValueError('Run as unprivileged development owner')
    DevelopmentScope(args.workspace)
    args.workspace.mkdir(mode=0o700, exist_ok=False)
    now = datetime.now(timezone.utc)
    release_fixture.NOW = now
    rollback_root = args.workspace/'rollback';rollback_root.mkdir(mode=0o700)
    fixture = release_fixture.ReleaseFixture(rollback_root);grant(rollback_root, now)
    supervisor = fixture.supervisor()
    outcome = supervisor.deploy(now=now)
    assert outcome['state'] == 'ROLLED_BACK'
    assert fixture.health()['healthy'] and len(fixture.business_rows()) == 2
    assert (rollback_root/'release/service.py').read_bytes() == release_fixture.GOOD
    identity = json.loads(args.github_identity.read_text())
    def verified_github(repo, sha):
        assert sha == identity['sha'] and identity['authenticated_native_read'] is True
        return dict(repository=repo, sha=sha, tree_sha=identity['tree'], authenticated_read=True)
    defect_root = args.workspace/'diagnostic-defect';defect_root.mkdir(mode=0o700);grant(defect_root, now)
    diagnostic = 'apps/workflow-api/workflow/automation/readiness.py'
    prepared = prepare_defect(args.base_source, DevelopmentScope(defect_root),
        {diagnostic: (ROOT/diagnostic).read_bytes()}, REGRESSION,
        source_sha=identity['sha'], github_read=verified_github, now=now)
    report = dict(at=now.isoformat(), environment='isolated-development', production_writes=0,
        rollback=dict(outcome, known_good_commit=fixture.good, broken_commit=fixture.candidate,
            final_code_sha256=hashlib.sha256((rollback_root/'release/service.py').read_bytes()).hexdigest(),
            known_good_code_sha256=hashlib.sha256(release_fixture.GOOD).hexdigest(),
            health_verified=True, business_rows_before=1, business_rows_after=2,
            database_restore_performed=False, r2_transport='SIMULATED_FIXTURE_NOT_LIVE_R2',
            encryption='HEADER_SHAPED_FIXTURE_NOT_REAL_AGE',
            journal_integrity=supervisor.audit.verify_integrity(supervisor.action_id)),
        real_diagnostic_defect=dict(prepared, github_identity_evidence=str(args.github_identity),
            defect='claimed work incorrectly classified as historical-only',
            publication='Draft request only; existing issue98/recovery work must be deduplicated before publication'))
    (args.workspace/'result.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':main()
