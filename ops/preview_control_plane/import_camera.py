#!/usr/bin/env python3
"""Explicit local import of the retained camera evidence; never a provider call."""
from copy import deepcopy
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'apps/workflow-api'))
from workflow.automation.acquisition_store import digest
from workflow.automation.manager_store import ManagerStore
from workflow.automation.website_preview_model import RepositoryState, new_preview, preview_ready
from workflow.automation.website_preview_import import import_website_report

PID = '49d2893d1498325eb5ae8f5a7304d1e3d199d03afcb4c6d0383dd7ed6ab32c17'
REPO = 'yboucher97/opticable-website'
REPORT = 'apps/workflow-api/tests/fixtures/website-preview/camera-website-report.json'
REPORT_HASH = '4dc475170ffd10ffaf35b102972f5a2e06ecbe71f930ef1ef0ce979c86e0cc51'
PROPOSAL_SHA = 'a0650b92007f197d68c252363362e2066f9db063'


def import_camera(store, raw, now, expected_hash):
    if hashlib.sha256(raw).hexdigest() != REPORT_HASH:
        raise ValueError('Reviewed historical camera report required')
    item = store.website_proposal(PID)
    existing = store.preview(PID, now)
    if existing and item['detail'].get('camera_report_sha256') == REPORT_HASH:
        return {'state': 'EXACT_REPLAY', 'provider_writes': 0, 'preview_ready': preview_ready(existing, now)}
    r = item['record']; report = json.loads(raw)
    if item['payload_hash'] != expected_hash or r['revision'] != 2 or r['target_object']['system'] != 'WEBSITE' or r['target_object']['entity_type'] not in {'LANDING_PAGE','WEBSITE_PAGE'} or report['camera']['proposal_sha'] != PROPOSAL_SHA:
        raise ValueError('Exact reviewed current camera revision required')
    repo = RepositoryState('github:'+REPO, 'GITHUB', REPO, 'main', 'main',
        last_analyzed_sha=report['prepared_tested_head_sha'], health_state='NOT_COLLECTED',
        source_at=report['observed_at'])
    # This package is a reference, not executable preparation input. A later
    # preparation must supply reviewed file scope and exact replacements.
    package = {'proposal_id':PID,'proposal_revision':r['revision'],'proposal_hash':item['payload_hash'],
        'repository':REPO,'base_sha':report['start_base_sha'],
        'required_tests':['BUILD','LINT','ROUTES','FR','EN','FORMS','GA4','ATTRIBUTION','LINKS','SCHEMA','ACCESSIBILITY','RESPONSIVE','SECRET_SCAN'],
        'evidence_refs':[REPORT], 'semantic_hash':digest(['HISTORICAL_CAMERA_REFERENCE',REPORT_HASH]),
        'reference_only':True}
    value = import_website_report(raw,new_preview(package,repo,now,'commercial-camera'),
        expected_proposal_id=PID,expected_repository=REPO,now=now)
    value['imported_evidence']['source_proposal_revision'] = r['revision']
    value['imported_evidence']['source_proposal_hash'] = item['payload_hash']
    updated = deepcopy(r); updated.update(revision=3,status='PROPOSED',updated_at=now.isoformat())
    for field in ('approved_at','approved_by','execution_reference','result','learning'):
        updated[field]=None
    detail = {**item['detail'],'repository':REPO,'camera_report_sha256':REPORT_HASH,
              'repository_mapping_evidence':REPORT,'historical_source_revision':2}
    # Consecutive immutable revision preserves the original two revisions and
    # invalidates any prior owner intent. No provider record is changed.
    store.record(updated,detail)
    current = store.website_proposal(PID)
    package.update(proposal_revision=3,proposal_hash=current['payload_hash'])
    value.update(proposal_revision=3,proposal_hash=current['payload_hash'],package=package)
    store.save_preview(value)
    store.repository_state(repo,now)
    return {'state':'IMPORTED_HISTORICAL_EVIDENCE','proposal_id':PID,'proposal_revision':3,
        'source_proposal_revision':2,'original_proposal_sha':value['original_proposal_sha'],
        'head_sha':value['head_sha'],'hosted_preview':value['preview_state'],
        'local_build_evidence':value['imported_evidence']['local_build_state'],
        'local_test_evidence':value['imported_evidence']['local_test_state'],
        'preview_ready':preview_ready(value,now),'provider_writes':0,'execution_authorized':False}


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--database',type=Path,required=True)
    parser.add_argument('--expected-proposal-hash',required=True)
    args=parser.parse_args()
    if not args.database.is_file():raise SystemExit('Existing canonical journal required')
    print(json.dumps(import_camera(ManagerStore(args.database),(ROOT/REPORT).read_bytes(),
        datetime.now(timezone.utc),args.expected_proposal_hash),sort_keys=True))
