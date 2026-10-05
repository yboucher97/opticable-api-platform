"""Unprivileged offline replay of current public evidence; no provider calls."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'apps/workflow-api'))
from workflow.automation.prospect_universe import ProspectStore,build_universe,owner_projection
from workflow.automation.trigger_runtime import build_queue,projection
from workflow.automation.trigger_sources import quebec_permits,local_date
from workflow.automation.coverage_sources import primary_seeds,PRIMARY,private_triggers


def main(p):
    now=datetime.now(timezone.utc)
    private=json.loads((p/'private-runtime-input.json').read_text());data=json.loads((p/'quebec-permits.geojson').read_text())
    metadata=json.loads((p/'quebec-resource.json').read_text())['result'];file=p/'quebec-permits.geojson'
    observed=datetime.fromtimestamp(file.stat().st_mtime,tz=timezone.utc).isoformat()
    latest=max(f['properties'].get('DATE_DELIVRANCE','') for f in data['features'])
    qrows=quebec_permits(data,now=now,verified_at=observed,published_at=local_date(latest))
    seeds=[];cache={'quebec_permit':{'records':qrows,'signature':[metadata['url'],metadata.get('last_modified')],
        'attempted_at':observed,'observed_at':observed,'source_records':len(data['features']),
        'source_effective_at':local_date(latest),'raw_sha256':hashlib.sha256(file.read_bytes()).hexdigest(),'state':'WORKING'}}
    for kind,name in [('montoni','montoni-distribution.html'),('lovo','lovo-expansion.html'),('saq_gc','saq-gc.html')]:
        f=p/name;at=datetime.fromtimestamp(f.stat().st_mtime,tz=timezone.utc)
        rows=primary_seeds(kind,f.read_bytes(),now=at);seeds.extend(rows)
        cache[kind]={'seeds':rows,'state':'WORKING','attempted_at':at.isoformat(),'observed_at':at.isoformat()}
    (p/'candidate-coverage-sources.json').write_text(json.dumps(cache,ensure_ascii=False,indent=2))
    crm={**private['identities']['crm'],'Deals':private['business']['snapshot'].get('deals',[]),
        'Services':private['business']['snapshot'].get('services',[]),'Service_Locations':private['business']['snapshot'].get('sites',[]),'_identity_complete':True}
    with tempfile.TemporaryDirectory() as tmp:
        store=ProspectStore(Path(tmp)/'db');store.capture_baseline(json.loads((p/'phase30-baseline-triggers.json').read_text()),now=now)
        queue=build_queue(store,[*private['stored'],*qrows,*private_triggers(seeds,now=now)],private['apollo'],crm,now=now,crm_at=private['identities']['at'],feedback={},source_health=[])
        view=build_universe(store,queue,private['apollo'],crm,now=now,crm_at=private['identities']['at'],seeds=seeds,research=private['role_cache'])
        compact=owner_projection(view);queue['prospect_universe']=compact
        result={k:view[k] for k in view if k not in ['records','trigger_audits']}
        result['projection_bytes']=len(json.dumps(projection(queue),ensure_ascii=False,indent=2).encode())
        result['at']=now.isoformat();result['source_fixture_separation']='CURRENT PUBLIC EVIDENCE — OFFLINE REPLAY, NOT SALES EFFECT'
        (p/'candidate-universe-proof.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
        (p/'candidate-trigger-retention-audit.json').write_text(json.dumps(view['trigger_audits'],ensure_ascii=False,indent=2))
        (p/'candidate-prospect-sample.json').write_text(json.dumps([{k:x[k] for k in ['prospect_id','canonical_name','identity_status','domain','geography_class','prospecting_status','pools','contact_coverage','CRM_state','Apollo_state','suppression_state','repeat_buyer_count','current_trigger_count','historical_trigger_count','why_opticable']} for x in view['records'] if x['entity_kind']=='ORGANIZATION'],ensure_ascii=False,indent=2))
        print(json.dumps({k:result[k] for k in ['funnel','pool_counts','identity_counts','contact_counts','baseline_review','historical_organizations','repeat_buyers','icp_only_prospects','no_current_trigger_prospects','why_not_ready','unresolved_projects','projection_bytes']},ensure_ascii=False,indent=2))


if __name__=='__main__':main(Path(sys.argv[1]))
