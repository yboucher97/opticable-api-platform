"""Read existing evidence/feedback and publish completion receipts locally only."""
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import sqlite3


def context(database, artifacts, marketing=None, receipts=None):
    from content_variations import feedback_rule
    assets={};history=[];feedback=[]
    with sqlite3.connect(Path(database).resolve().as_uri()+'?mode=ro',uri=True) as db:
        for (raw,) in db.execute("SELECT normalized_value FROM acquisition_facts WHERE source='platform:business_autopilot' ORDER BY retrieved_at,id LIMIT 3000"):
            value=json.loads(raw);h=value.get('sha256');assets[h]=value
            p=Path(artifacts)/value.get('path','')
            if not value.get('business_private') and value.get('path','').endswith('.txt') and p.resolve().is_relative_to(Path(artifacts).resolve()) and p.is_file() and p.stat().st_size<20000:
                text=p.read_text()
                if sha256(text.encode()).hexdigest()==h:history.append(text)
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='action_evidence'").fetchone():
            for event_id,raw in db.execute("SELECT event_id,evidence_json FROM action_evidence WHERE kind='business_review_decision' ORDER BY event_id LIMIT 1000"):
                v=json.loads(raw);asset=assets.get(v.get('id'))
                if not asset or v.get('actor')!='owner:opticable-review':continue
                parts=Path(asset['logical_path']).parts
                feedback.append({'event_id':event_id,'asset_sha256':v['id'],'service':asset.get('service') or (parts[3] if len(parts)>4 else 'all'),
                                 'language':asset.get('language') or next((x for x in parts if x in ('fr','en')),'bilingual'),
                                 'choice':v['choice'],'rule':feedback_rule(v.get('reason','')),'at':v['at']})
    value={'artifact_hashes':sorted(h for h in assets if h),'prior_texts':history[-60:],'feedback':feedback,
           'completion_dates':sorted({v['logical_path'].split('/')[2] for v in assets.values() if v.get('logical_path','').startswith('business-work/completion/')}),
           'external_outcomes':'Only existing verified production execution and measurement evidence may establish business lift; none inferred from editorial approval.'}
    if marketing and Path(marketing).is_file():
        m=json.loads(Path(marketing).read_text());groups=m.get('groups',[])
        value['crm_inventory']={'observed_at':m.get('observed_at'),'source':'existing /run/optibrain-readiness/marketing.json',
            'leads':sum(g.get('leads',0) for g in groups),'deals':sum(g.get('deals',0) for g in groups),
            'quotes':sum(g.get('estimates',0) for g in groups),'accepted_quotes':sum(g.get('accepted_estimates',0) for g in groups),
            'unattributed_leads':sum(g.get('leads',0) for g in groups if g.get('source')=='UNATTRIBUTED'),
            'qualification_label_count':sum(g.get('qualified_leads',0) for g in groups),
            'won_deals':None,'recognized_revenue':None,'quality':'Current visible inventory; not new outcomes in analytics period; qualification coverage unverified'}
    if receipts and Path(receipts).is_file():
        with sqlite3.connect(Path(receipts).resolve().as_uri()+'?mode=ro',uri=True) as db:
            value['receipt_inventory']=[{'test_only':r[0],'count':r[1],'first':r[2],'last':r[3]} for r in db.execute('select test_only,count(*),min(occurred_at),max(occurred_at) from form_receipts group by test_only')]
            value['receipt_inquiry_ids']=db.execute("select count(*) from form_receipts where json_extract(evidence_json,'$.attribution.inquiry_id') is not null").fetchone()[0]
    return value


def funnel(native, ctx):
    from engine import rows
    source=next((s for s in native['snapshots'] if s['source']=='platform:ga4:530093120'),None)
    metrics=rows(source['data']) if source else []
    traffic={'sessions':sum(r.get('sessions',0) for r in metrics) if source else None,'key_events':sum(r.get('keyEvents',0) for r in metrics) if source else None,'unique_inquiries':None,'scope':'GA4 property530093120; events are not unique or qualified leads'}
    return {'schema':1,'traffic_period':native['collection']['period'],'traffic_observed_at':native['collection']['at'],
        'traffic':traffic,
        'inquiries':{'retained_receipts':ctx.get('receipt_inventory',[]),'with_attempt_ids':ctx.get('receipt_inquiry_ids'),
                     'complete_period_inquiry_total':None,'limitation':'Native notification inventory is not complete acquisition coverage; no inferred identity join.'},
        'business_inventory':ctx.get('crm_inventory',{}),'qualified_leads':None,'recognized_revenue':None,'campaign_roas':None,
        'mapping':{'keys':['provider_receipt_id','obq inquiry_id','native CRM lead ID','explicit deal ID','explicit quote/invoice IDs'],
                   'forbidden':['Similar names','Shared email alone','Visitor cookie alone','UTM campaign label treated as verified Ads campaign','Historical attribution overwrite'],
                   'remaining_gate':'Inquiry_ID already exists in native Leads metadata; validate exact mapping and separately approve coordinated parser/capture release. Legacy IDs remain unchanged; no retroactive attribution.'},
        'production_changes':False,'provider_calls':0}
