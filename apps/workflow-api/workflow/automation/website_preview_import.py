"""Bounded structured handoff from the website lane; reports grant no readiness."""
from copy import deepcopy
import json
from .website_preview_model import identifier, sha, repository_name
from .manager_sources import stamp


def import_website_report(raw,preview,*,expected_proposal_id,expected_repository,now):
    if not isinstance(raw,bytes) or len(raw)>131072:raise ValueError('Website report byte bound exceeded')
    try:r=json.loads(raw)
    except (ValueError,UnicodeDecodeError):raise ValueError('Structured website report required') from None
    if not isinstance(r,dict) or r.get('schema')!=1 or r.get('production_affected') is not False:raise ValueError('Non-production report contract required')
    repo=repository_name(r.get('repository'));camera=r.get('camera',{})
    pid=identifier(camera.get('proposal_id'));revision=camera.get('source_revision')
    if pid!=expected_proposal_id or repo!=expected_repository or pid!=preview['proposal_id'] or repo!=preview['repository'] or revision!=preview['proposal_revision'] or not stamp(r.get('observed_at')):
        raise ValueError('Report proposal/revision/repository mismatch')
    base=sha(r.get('start_base_sha'));original=sha(camera.get('proposal_sha'));tested=sha(r.get('prepared_tested_head_sha'))
    if base!=preview['base_sha'] or tested!=camera.get('prepared_sha'):raise ValueError('Report SHA mismatch')
    cf=r.get('cloudflare',{});status=str(cf.get('builds_trigger_read',''))
    blocked='401' in status or '403' in status
    v=deepcopy(preview)
    v.update(head_sha=tested,original_proposal_sha=original,state='PROVIDER_BLOCKED' if blocked else 'PREPARATION_ELIGIBLE',
        preview_state='BLOCKED_AUTH' if blocked else 'NOT_COLLECTED',owner_status='PENDING',preview_url=None,
        preview_deployment_id=None,last_verified_at=None,stale_state='UNKNOWN',updated_at=now.isoformat())
    # Local evidence belongs to a historically tested SHA. It is reference
    # evidence only; fresh trusted runner/adapter reads are needed for READY.
    v['imported_evidence']={'observed_at':r['observed_at'],'historical_branch':r.get('branch'),
        'original_proposal_sha':original,'prepared_tested_sha':tested,
        'testing':[{'test_class':k.upper(),'reported_result':result} for k,result in r.get('testing',{}).items()
            if k in {'build','lint','routes','fr','en','forms','ga4','ob_attribution','links_assets','schema','responsive_accessibility','policy_tests','secret_scan','preview_http'}],
        'owner_review':camera.get('owner_review'),'local_build_state':'PASS' if r.get('pipeline',{}).get('build','').startswith('PASS') else 'NOT_RUN',
        'local_test_state':'PASS' if camera.get('tests')=='PASSED_LOCAL' else 'NOT_RUN','hosted_readiness':False}
    v['provider_reads']['cloudflare']={'state':'BLOCKED_AUTH' if blocked else 'NOT_COLLECTED',
        'attempted':1 if blocked else 0,'successful':0,'failed':1 if blocked else 0,'source_at':None,
        'observed_at':r['observed_at'],'reason':status or 'No hosted evidence collected'}
    return v
