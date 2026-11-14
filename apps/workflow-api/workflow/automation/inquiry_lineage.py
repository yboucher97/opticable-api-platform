"""Read-only exact inquiry/campaign/CRM lineage. No fuzzy identities or writes.

Capture IDs are correlation evidence, not consent or a verified paid-ad campaign.
Historical unknowns remain unknown; observations and business inventory differ.
"""
from collections import defaultdict
from datetime import datetime
from hashlib import sha256
import re


def inquiry_id(value):
    return bool(isinstance(value,str) and re.fullmatch(r'obq_[a-f0-9]{32}',value))


def build_inquiry_funnel(receipts, leads, deals=(), quotes=(), invoices=(), campaigns=()):
    issues=[];by_attempt=defaultdict(list);by_receipt={}
    for row in receipts:
        rid=row.get('provider_receipt_id');attempt=row.get('inquiry_id')
        if row.get('test_only') is not False:
            issues.append('TEST_OR_UNCLASSIFIED_RECEIPT_EXCLUDED');continue
        if not rid or not inquiry_id(attempt) or not row.get('provider_evidence'):
            issues.append('MISSING_NATIVE_RECEIPT_OR_ATTEMPT');continue
        if rid in by_receipt and by_receipt[rid]!=row:
            issues.append('CONFLICTING_RECEIPT');by_receipt[rid]=None;continue
        by_receipt[rid]=row
    for row in by_receipt.values():
        if row:by_attempt[row['inquiry_id']].append(row)
    lead_index={str(r['id']):r for r in leads if r.get('id') and r.get('test_only') is False}
    campaign_index={str(r['id']):r for r in campaigns if r.get('id') and r.get('provider') and r.get('account_id') and r.get('evidence')}
    linked=[];ambiguous=[]
    for attempt,rows in by_attempt.items():
        claims={str(r.get('crm_lead_id')) for r in rows if r.get('crm_lead_id')}
        if len(claims)!=1:
            ambiguous.append(attempt);continue
        lid=next(iter(claims));lead=lead_index.get(lid)
        # Both native records must explicitly carry the same immutable attempt.
        # A name,phone,email,visitor cookie or UTM similarity cannot satisfy this.
        if not lead or lead.get('inquiry_id')!=attempt or not lead.get('provider_evidence'):
            ambiguous.append(attempt);continue
        touch=rows[0].get('attribution',{})
        campaign=campaign_index.get(str(touch.get('campaign_id','')))
        campaign_ok=bool(campaign and touch.get('provider')==campaign['provider'] and touch.get('account_id')==campaign['account_id'])
        linked.append({'inquiry_key':sha256(('inquiry:'+attempt).encode()).hexdigest(),'inquiry_id':attempt,
                       'provider_receipt_ids':sorted(r['provider_receipt_id'] for r in rows),'crm_lead_id':lid,
                       'landing_page':touch.get('landing_page'),'source':touch.get('source') or 'UNATTRIBUTED',
                       'utm_campaign_id':touch.get('campaign_id'),'campaign_identity':'NATIVE_VERIFIED' if campaign_ok else 'CAPTURED_UNVERIFIED' if touch.get('campaign_id') else 'UNKNOWN',
                       'qualified':lead.get('qualification')=='OWNER_VERIFIED_QUALIFIED' and bool(lead.get('qualification_evidence'))})
    linked_leads={r['crm_lead_id'] for r in linked}
    exact_deals=[d for d in deals if d.get('test_only') is False and str(d.get('lead_id')) in linked_leads and d.get('provider_evidence')]
    deal_ids={str(d['id']) for d in exact_deals}
    verified_quotes=[q for q in quotes if q.get('test_only') is False and str(q.get('deal_id')) in deal_ids and q.get('provider_evidence')]
    won=[d for d in exact_deals if d.get('stage')=='Closed Won' and d.get('stage_evidence')]
    # Do not turn gross invoiced value, inventory or cash into recognized revenue.
    return {'scope':'Exact observed inquiry lineage; not complete traffic or business inventory',
            'observed_unique_inquiries':len(by_attempt),'exact_linked_leads':len(linked_leads),
            'verified_qualified_leads':len({r['crm_lead_id'] for r in linked if r['qualified']}), 'linked_quotes':len(verified_quotes),
            'linked_won_deals':len(won),'recognized_revenue':None,'roas':None,'cpql':None,
            'linked':linked,'ambiguous_or_unlinked_attempts':ambiguous,'issues':sorted(set(issues)),
            'historical_unknowns_preserved':True,'provider_writes':0}
