"""Offline reduction of current public reads and private native cache identities.

No provider calls. Output includes a candidate source cache for reviewed staging,
not authority. Run unprivileged with bounded local evidence files.
"""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import sys
import tempfile

REPO=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO/'apps/workflow-api'))
from workflow.automation.trigger_sources import seao,expansion,permits
from workflow.automation.trigger_runtime import build_queue,projection
from workflow.automation.trigger_store import TriggerStore


def load(path):return json.loads(path.read_text())
def checked(path):return datetime.fromtimestamp(path.stat().st_mtime,tz=timezone.utc).isoformat()


def main(root):
    now=datetime.now(timezone.utc);private=load(root/'private-current-identities.json')
    catalog=load(root/'seao-catalog.json')['result']['resources']
    resource=next(r for r in catalog if r['name']=='mensuel_20260901_20260930.json')
    path=root/resource['name'];data=load(path)
    selected=seao(data['releases'],now=now,verified_at=checked(path),published_at='2026-09-30T23:59:00-04:00',source_url=resource['url'])
    selected=sorted(selected,key=lambda r:r['source_version_at'],reverse=True)[:120]
    raw=root/'tricorbraun.html';company=expansion(raw.read_bytes(),now=datetime.fromisoformat(checked(raw)))
    cached=private['permits'];local=permits(cached['records'],provider='montreal_permit',now=now,verified_at=cached['at'])
    source_cache={'seao':{'attempted_at':checked(path),'observed_at':checked(path),'records':selected,
        'state':'WORKING','coverage':'PARTIAL — OFFICIAL BATCH EXPORT','reason':'Official export coverage through September30; current addenda must be verified before bidding',
        'resource_signature':[resource['url'],resource.get('last_modified')],'source_url':resource['url'],
        'published_at':data.get('publishedDate'),'source_effective_at':'2026-09-30T23:59:00-04:00','raw_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
        'source_records':len(data['releases']),'selected_records':len(selected)},
        'company_announcement':{'attempted_at':checked(raw),'observed_at':checked(raw),'state':'WORKING','coverage':'PARTIAL — ONE PRIMARY ANNOUNCEMENT',
        'records':[company],'reason':'Visible primary announcement verified; mismatched embedded NewsArticle metadata rejected'}}
    (root/'candidate-trigger-sources.json').write_text(json.dumps(source_cache,indent=2,ensure_ascii=False))
    identities=private['identities'];snapshot=private['business']['snapshot']
    crm={**identities['crm'],'Deals':snapshot.get('deals',[]),'Services':snapshot.get('services',[]),'Service_Locations':snapshot.get('sites',[]),'_identity_complete':True}
    with tempfile.TemporaryDirectory() as tmp:
        store=TriggerStore(Path(tmp)/'isolated.db')
        queue=build_queue(store,[*local,*selected,company],private['apollo'],crm,now=now,crm_at=identities['at'],feedback={},source_health=[])
        second=build_queue(store,[*local,*selected,company],private['apollo'],crm,now=now,crm_at=identities['at'],feedback={},source_health=[])
        summary={k:queue[k] for k in ('counts','identity_counts','collision_counts','trigger_count','version_count','foreign_excluded','expired_excluded')}
        summary.update(at=now.isoformat(),public_source_records={'seao_releases':len(data['releases']),'montréal_permits':len(cached['records']),'company_announcements':1},
            replay_updates=second['updates'],version_count_after_replay=second['version_count'],provider_calls=0,provider_writes=0,crm_promotions=0,
            apollo_contacts_reused=len(private['apollo']['contacts']),crm_records_reused={k:len(v) for k,v in identities['crm'].items()},
            current_sample=[{k:r.get(k) for k in ('company_name','title','status','source_version','source_effective_at','closing_date','geography_class','priority_class','company_resolution_status','evidence_confidence','source_url','recommended_next_action')}|{'collision':r['collision']['classification']} for r in queue['rows'][:8]])
        (root/'current-public-shadow-proof.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
        print(json.dumps(summary,ensure_ascii=False))
    return summary


if __name__=='__main__':main(Path(sys.argv[1]))
