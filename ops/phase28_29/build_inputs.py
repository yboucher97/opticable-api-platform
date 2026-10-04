#!/usr/bin/env python3
"""Reuse trusted existing evidence; build a private, reproducible acquisition lab."""
import json,os,sys
from datetime import datetime,timezone
from pathlib import Path
REPO=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO/'apps/workflow-api'))
ROOT=Path('/var/lib/optibrain/acquisition-intelligence')
EVIDENCE=Path('/home/optibrain/phase28-29-evidence')

def main():
    if os.geteuid()!=0:raise ValueError('Private source reuse requires manual root')
    os.umask(0o077);now=datetime.now(timezone.utc)
    from workflow.automation.sales_intelligence import permit_signals
    from workflow.automation.acquisition_store import AcquisitionStore
    from workflow.automation.acquisition_ingest import ingest
    load=lambda p:json.loads(Path(p).read_text())
    native=load(sorted(ROOT.glob('google-20*.json'))[-1])
    native['reads']={k:{**v,'observed_at':native['at']} for k,v in native['reads'].items()}
    enabled=sorted(ROOT.glob('google-after-enable-*.json'))
    if enabled:
        newest=load(enabled[-1]);native['reads'].update({k:{**v,'observed_at':newest['at']} for k,v in newest['reads'].items()});native['at']=newest['at']
    if (ROOT/'google-current.json').exists():native=load(ROOT/'google-current.json')
    broker=lambda name:load(EVIDENCE/name).get('structuredContent',{}).get('data',[])
    permits=load('/var/lib/optibrain/sales-intelligence/permits.json')
    seao=load('/var/lib/optibrain/sales-intelligence/public-triggers.json')
    seao_ids={r['record_id'] for r in seao['signals']};week=load('/home/optibrain/phase26-27-evidence/seao-week.json')
    seao_raw=[r for r in week.get('releases',[]) if r.get('ocid') in seao_ids]
    modified=lambda name:datetime.fromtimestamp((EVIDENCE/name).stat().st_mtime,timezone.utc).isoformat()
    x={'schema':1,'at':now.isoformat(),'broker_at':modified('windsor-searchconsole.json'),
       'gbp_at':modified('windsor-gbp-daily.json'),'public_business_at':modified('oqlf-business.json'),
       'competitors_at':load(EVIDENCE/'competitor-pages.json')['at'],'providers_checked_at':modified('provider-discovery.json'),
       'date_from':native['reads']['gsc_queries'].get('date_from','2026-09-01'),'date_to':native['reads']['gsc_queries'].get('date_to','2026-10-01'),
       'broker_period':{'date_from':'2026-09-01','date_to':'2026-10-01'},
       'apollo':load('/var/lib/optibrain/sales-intelligence/apollo.json'),
       'crm':load('/var/lib/optibrain/sales-intelligence/crm.json')['crm'],'crm_at':load('/var/lib/optibrain/sales-intelligence/crm.json')['at'],
       'google':native,'gsc':broker('windsor-searchconsole.json'),'gbp':broker('windsor-gbp-daily.json'),
       'public_business':load(EVIDENCE/'oqlf-business.json')['result']['records'],
       'signals':permit_signals(permits['records'],now=now)+seao['signals'],'raw_permits':permits['records'],'seao_raw':seao_raw,
       'permits_at':permits['at'],'seao_at':seao.get('at'),
       'competitors':load(EVIDENCE/'competitor-pages.json')['pages'],
       'social':{name:{'at':modified('windsor-'+name+'.json'),'date_from':'2026-07-01','date_to':'2026-10-01',
                        'rows':broker('windsor-'+name+'.json')} for name in ('facebook_organic','instagram','linkedin_organic')}}
    # Re-assembling one source must preserve the separately collected Phase29 evidence.
    if (ROOT/'inputs.json').exists():
        prior=load(ROOT/'inputs.json')
        for name in ('website','market_research','verified_outcomes'):
            if name in prior:x[name]=prior[name]
    # Runtime hydrates these existing identity caches independently. Do not store
    # a second full Apollo workspace beside multi-megabyte website snapshots.
    payload=json.dumps({k:v for k,v in x.items() if k not in {'apollo','crm'}},ensure_ascii=False,separators=(',',':'))
    if len(payload.encode())>16777216:raise ValueError('Bounded research assembly exceeds 16 MiB')
    (ROOT/'inputs.json').write_text(payload);(ROOT/'inputs.json').chmod(0o600)
    store=AcquisitionStore(ROOT/'lab.sqlite');view=ingest(store,x,now=now)
    (ROOT/'phase28-lab.json').write_text(json.dumps(view,ensure_ascii=False));(ROOT/'phase28-lab.json').chmod(0o600)
    print(json.dumps({k:view[k] for k in ('counts','snapshots','facts','identity_conflicts','crm_promotions','provider_writes')},ensure_ascii=False))

if __name__=='__main__':main()
