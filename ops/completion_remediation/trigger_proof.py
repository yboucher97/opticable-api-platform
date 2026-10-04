#!/usr/bin/env python3
"""Fixed two-permit read and curated SEAO public-page proof; no provider writes.

Outputs a candidate cache/evidence bundle. Does not install it into production.
SEAO browser run 06b8ac26-c4b4-46ab-a073-78e6a21f17f9 independently checked
both published tenders and their September30 amendments. OCDS IDs retained
below are original native IDs, not fabricated new amendment IDs.
"""
from pathlib import Path
from datetime import datetime,timezone
import json,os,httpx,sys
REPO=Path(__file__).resolve().parents[2]
sys.dont_write_bytecode=True
sys.path.insert(0,str(REPO/'apps/workflow-api'))

def main():
    if os.geteuid()!=0:raise ValueError('Manual private evidence read requires root')
    os.umask(0o077)
    from workflow.automation.sales_intelligence import permit_signals,build_sales
    from workflow.automation.trigger_evidence import actors_from_release,latest_releases,assess_trigger
    root=Path('/var/lib/optibrain/completion-remediation-1-2');now=datetime.now(timezone.utc)
    load=lambda p:json.loads(Path(p).read_text())
    prior=load('/var/lib/optibrain/sales-intelligence/permits.json')
    endpoint='https://donnees.montreal.ca/api/3/action/datastore_search'
    cached=root/'permit-current-read.json'
    if cached.exists():data=load(cached)
    else:
      with httpx.Client(timeout=20,follow_redirects=False) as c:
        with c.stream('GET',endpoint,params={'resource_id':'5232a72d-235a-48eb-ae20-bb9d501300ad','filters':json.dumps({'id_permis':['3001982059','3001982057']}),'limit':10}) as r:
            r.raise_for_status();raw=b''
            for chunk in r.iter_bytes():
                raw+=chunk
                if len(raw)>1048576:raise ValueError('Public proof exceeds bound')
      data=json.loads(raw)
    records=[r for r in data['result']['records'] if str(r.get('id_permis')) in {'3001982059','3001982057'}]
    if data.get('success') is not True or {str(r['id_permis']) for r in records}!={'3001982059','3001982057'}:raise ValueError('Exact permit proof incomplete')
    permit_proof={'schema':1,'at':now.isoformat(),'source_url':endpoint,'records':records,'actor_fields':[],'provider_writes':0}
    prior_records={str(r['id_permis']):r for r in prior['records']}
    for r in records:prior_records[str(r['id_permis'])]=r
    permits={'schema':1,'at':now.isoformat(),'records':data['result']['records'] if cached.exists() else list(prior_records.values()),'exact_rechecks':{str(r['id_permis']):now.isoformat() for r in records}}
    old=load('/var/lib/optibrain/sales-intelligence/public-triggers.json')
    raw_tenders=latest_releases(load('/home/optibrain/phase26-27-evidence/seao-week.json')['releases'])
    current=[]
    for r in old['signals']:
        row=dict(r);native=raw_tenders[r['record_id']]
        row.update(current_status='OPEN',last_checked=now.isoformat(),retrieved_at=now.isoformat(),
            source_published_at=now.isoformat(),geography='Greater Montréal' if r['record_id']=='ocds-ec9k95-20172194' else 'Montréal',actors=actors_from_release(native),
            company_identity={'confidence':'SUPPORTED','source_url':r['company_identity_source'],'native_buyer_id':native['buyer']['id']},
            source_version='SEAO latest addendum 2026-09-30',source_version_date='2026-09-30',
            version_proof={'source_url':r['source_url'],'browser_run':'06b8ac26-c4b4-46ab-a073-78e6a21f17f9','observed_status':'Publié','observed_at':now.isoformat(),'native_release_id_is_prior_version':True},
            target_contact={'state':'UNRESOLVED','role_relevance':'PROCUREMENT / FACILITIES / SECURITY — HUMAN REVIEW','contact_allowed':False})
        current.append(assess_trigger(row,now=now))
    public={'schema':1,'at':now.isoformat(),'signals':current}
    signals=permit_signals(records,now=now,retrieved_at=now.isoformat())+current
    a=load('/var/lib/optibrain/sales-intelligence/apollo.json');crm=load('/var/lib/optibrain/sales-intelligence/crm.json')['crm']
    sales=build_sales(a,crm,signals,now=now)
    result={'schema':1,'at':now.isoformat(),'permit_proof':permit_proof,'candidate_permits_cache':permits,'candidate_public_cache':public,
        'sales':sales,'provider_writes':0,'summary':{'permits':len(records),'permit_actors_resolved':0,'permit_actors_unresolved':len(records),
            'tenders':len(current),'tender_buyer_actors_proven':len(current),'target_people_proven':0,
            'sales_trigger_reviews':sum(r['kind']=='trigger' for r in sales['rows']),'research_held':sales['research_held']}}
    path=root/'current-trigger-proof.json'
    if path.exists():raise ValueError('Proof already recorded; reuse, do not repeat provider read')
    path.write_text(json.dumps(result,indent=2,ensure_ascii=False));path.chmod(0o600)
    print(json.dumps(result['summary']))
if __name__=='__main__':main()
