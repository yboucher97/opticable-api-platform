#!/usr/bin/python3
"""Manual read-only evidence reduction and zero-credit company-domain probe.

No generic provider request interface; never writes provider state. Reuses the
complete discovery inventory rather than repeating production lifecycle tests.
"""
from datetime import datetime,timezone
from pathlib import Path
from collections import Counter
import json
import os
import sys
import httpx

REPO=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO/'apps/workflow-api'))
from workflow.automation.sales_intelligence import build_sales,permit_signals,tender_signals,domain,key,live


def save(path,value):
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as stream:json.dump(value,stream,sort_keys=True,indent=2)


def main():
    if os.geteuid()!=0:raise ValueError('Manual root evidence reduction required')
    root=Path('/var/lib/optibrain/phase26-27');out=Path('/var/lib/optibrain/sales-intelligence')
    owner=Path('/home/optibrain/phase26-27-evidence')
    first=json.loads((root/'apollo-discovery-first.json').read_text())
    full=json.loads((root/'apollo-discovery-complete.json').read_text())
    f=first['entries'];c=full['entries']
    apollo={'schema':1,'at':full['at'],'contacts_complete':True,'contacts':full['apollo_contacts'],
            'accounts':f['accounts']['data']['accounts'],'sequences':f['sequences']['data']['emailer_campaigns'],
            'messages':c['delivered']['data']['emailer_messages']+f['messages']['data']['emailer_messages'],
            'replies':c['replied']['data']['emailer_messages'],'stages':f['contact_stages']['data']['contact_stages'],
            'labels':f['labels']['data'],'provider_mutations':0,'credit_consuming_calls':0}
    crm={k:v.get('data',[]) for k,v in full['crm'].items()}
    now=datetime.now(timezone.utc)
    permits=json.loads((owner/'montreal-permits.json').read_text())['result']['records']
    releases=json.loads((owner/'seao-week.json').read_text())['releases']
    signals=tender_signals(releases,now=now)
    # Primary-domain evidence is independent of fuzzy company-name matching.
    exact_domains={'ocds-ec9k95-20172194':('ville.mont-royal.qc.ca','https://www.ville.mont-royal.qc.ca'),
                   'ocds-ec9k95-20168879':('cmaisonneuve.qc.ca','https://www.cmaisonneuve.qc.ca/environnement/approvisionnement/')}
    for s in signals:
        if s['record_id'] in exact_domains:
            s['domain'],s['company_identity_source']=exact_domains[s['record_id']]
            s['identity_unresolved']=False
    probe=root/'additive-apollo-probe.json'
    if probe.exists():results=json.loads(probe.read_text())
    else:
        sys.path.insert(0,'/opt/opticable-api-platform/ops/phase16_17')
        from inventory import clients
        settings,_,_=clients()
        with httpx.Client(base_url='https://api.apollo.io/api/v1',headers={'x-api-key':settings.apollo.api_key},timeout=30,follow_redirects=False) as client:
            before=client.get('/users/api_profile');before.raise_for_status();before=before.json()
            entries=[]
            for host,_ in exact_domains.values():
                response=client.post('/mixed_people/api_search',json={'q_organization_domains_list':[host],'page':1,'per_page':5})
                entries.append({'domain':host,'http_status':response.status_code,'data':response.json()})
            after=client.get('/users/api_profile');after.raise_for_status();after=after.json()
        credit={k:after[k]-v for k,v in before.items() if ('credits_used' in k) and type(v) in (int,float) and type(after.get(k)) in (int,float)}
        results={'at':now.isoformat(),'read_only':True,'provider_mutations':0,'credit_usage_delta':credit,'entries':entries}
        save(probe,results)
    if any(v!=0 for v in results['credit_usage_delta'].values()):raise ValueError('Unexpected credit change; investigate before further enrichment')
    evidence=[]
    for r in results['entries']:
        people=r.get('data',{}).get('people',[]) if r['http_status']==200 else []
        current=[p for p in people if domain(p.get('organization',{}).get('primary_domain'))==r['domain']]
        evidence.append({'domain':r['domain'],'http_status':r['http_status'],'total_matches':r.get('data',{}).get('total_entries'),
                         'sampled':len(people),'current_employer_proven':len(current),
                         'verified_email_returned':sum(bool(p.get('email')) for p in current),
                         'paid_enrichment_used':False,'clay_used':False})
        for s in signals:
            if s.get('domain')==r['domain']:
                s['apollo_research']=evidence[-1]
                s['who']='Owner reviews procurement; Apollo current-employer candidates require role validation'
    sales=build_sales(apollo,crm,[*signals,*permit_signals(permits,now=now)],now=now)
    for name,value in [('apollo.json',apollo),('crm.json',{'schema':1,'at':full['at'],'crm':{k:crm[k] for k in ('Leads','Contacts','Accounts')}}),('public-triggers.json',{'schema':1,'at':now.isoformat(),'signals':signals}),
                       ('permits.json',{'schema':1,'at':now.isoformat(),'records':permits})]:
        if not (out/name).exists():save(out/name,value)
    save(root/'shadow-live-validation.json',sales)
    from zoneinfo import ZoneInfo
    sent=c['daily-sent']['data']['emailer_messages']
    days=Counter(str(datetime.fromisoformat(r['completed_at'].replace('Z','+00:00')).astimezone(ZoneInfo('America/Toronto')).date()) for r in sent if r.get('completed_at'))
    seq=[]
    config={}
    for r in apollo['sequences']:
        detail=c['sequence-'+r['id']]['data']
        config[r['id']]={'active':r['active'],'archived':r['archived'],'schedule':r['emailer_schedule_id'],
                         'max_emails_per_day':r['max_emails_per_day'],'steps':detail['emailer_steps'],
                         'touches':detail['emailer_touches'],'templates':detail['emailer_templates']}
        seq.append({k:r.get(k) for k in ('id','name','active','archived','creation_type','max_emails_per_day','num_steps',
                  'unique_scheduled','unique_delivered','unique_bounced','unique_replied','unique_unsubscribed','unique_demoed')})
    save(root/'apollo-production-config-before.json',config)
    summary={'at':now.isoformat(),'contacts':sales['contacts'],'accounts':len(apollo['accounts']),'sequences':seq,
             'active_contacts':sales['active_contacts'],'suppressed_contacts':sales['suppressed_contacts'],
             'unsubscribed_contacts':sum(r.get('email_unsubscribed') is True for r in apollo['contacts']),
             'exact_crm_contact_overlap':sales['exact_crm_contact_overlap'],
             'replied_messages':len(apollo['replies']),'provider_classified_willing_to_meet':sum(r.get('reply_class')=='willing_to_meet' for r in apollo['replies']),
             'bounded_completed_messages_by_toronto_day':dict(days),'daily_prospect_creation':'UNKNOWN — no complete creation-date history query',
             'saved_searches':'UNAVAILABLE HTTP404','labels_visible':len(apollo['labels']),
             'tasks_total':f['tasks']['data'].get('pagination',{}).get('total_entries'),
             'public_tenders':len(signals),'permit_signals':len(permit_signals(permits,now=now)),
             'additive_company_overlap':[{ 'source_record':s['record_id'],'apollo_matches':len(s['apollo_matches']),'crm_matches':len(s['crm_matches']),'identity_known':s['identity_known']} for s in sales['prospects'] if s['source']=='seao'],
             'apollo_lookup':evidence,'new_sales_rows':dict(Counter(r['kind'] for r in sales['rows'])),
             'provider_writes':0,'credits_used':0,'clay_status':'DEFERRED — installed plugin, no callable tool/key in this session',
             'crm_non_test_counts':{k:sum(live(r) for r in rows) for k,rows in crm.items()},
             'promotion_to_crm':'OFF — owner/reply/meeting review; no raw bulk imports'}
    save(root/'discovery-summary.json',summary)
    print(json.dumps(summary))


if __name__=='__main__':main()
