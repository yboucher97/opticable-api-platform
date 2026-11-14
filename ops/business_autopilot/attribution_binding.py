"""Development-only native Leads field contract and exact-ID mapping. No client.

Produces an exact local lineage record, never writes CRM or treats UTM text as
verified campaign attribution. Native Inquiry_ID is a business identifier, not a
spare browser-attempt field. Legacy IDs and first-touch values are immutable.
"""
import re


def proposal(receipt, lead, fields):
    attempt=receipt.get('inquiry_id')
    if not isinstance(attempt,str) or not re.fullmatch(r'obq_[a-f0-9]{32}',attempt):
        raise ValueError('Exact consented attempt ID required')
    if receipt.get('test_only') or lead.get('test_only') or not receipt.get('provider_receipt_id') or not receipt.get('acknowledgement_evidence'):
        raise ValueError('Native non-test receipt and acknowledgement evidence required')
    if not receipt.get('crm_lead_id') or receipt['crm_lead_id']!=lead.get('id') or not lead.get('provider_evidence'):
        raise ValueError('Explicit native lead relationship and readback required')
    field=next((f for f in fields if f.get('api_name')=='Inquiry_ID'),None)
    if not field or field.get('data_type')!='text' or field.get('length',0)<len(attempt):
        raise ValueError('Current native Inquiry_ID text contract required')
    existing=lead.get('Inquiry_ID')
    if existing and (not isinstance(existing,str) or existing.startswith('obq_') and existing!=attempt):
        raise ValueError('Conflicting native attempt identity; no overwrite')
    return {'module':'Leads','record_id':lead['id'],'fields':{},
            'local_lineage':{'attempt_id':attempt,'provider_receipt_id':receipt['provider_receipt_id'],'crm_lead_id':lead['id'],
                'business_inquiry_id':existing,'acknowledgement_evidence':receipt['acknowledgement_evidence'],'provider_evidence':lead['provider_evidence']},
            'precondition':{'Inquiry_ID':existing},'first_touch_unchanged':True,'state':'LOCAL_LINEAGE_ONLY_NO_CRM_WRITE',
            'native_schema_change_required':False,'execution_authorized':False,'provider_writes':0,
            'required_approval':'Exact coordinated parser/capture/lineage release; this adapter never modifies CRM'}


def verify_readback(plan, record):
    expected=plan['precondition']['Inquiry_ID']
    return bool(record.get('id')==plan['record_id'] and record.get('Inquiry_ID')==expected)


def record_verified_link(database, receipt, readback, fields, now):
    """Existing immutable journal; one semantic link per native receipt, no grant."""
    from workflow.automation.action_evidence import ActionEvidence
    from workflow.automation.acquisition_store import digest
    plan=proposal(receipt,readback,fields);link=plan['local_lineage']
    if not verify_readback(plan,readback):raise ValueError('Native readback changed')
    aid='inquiry-lineage:'+digest(receipt['provider_receipt_id']);audit=ActionEvidence(database)
    with audit.connect() as db:
        db.execute('BEGIN IMMEDIATE');ActionEvidence.setup(db)
        prior=db.execute("SELECT evidence_json FROM action_evidence WHERE action_id=? AND kind='business_inquiry_lineage' ORDER BY event_id LIMIT 1",(aid,)).fetchone()
        if prior:
            import json
            saved=json.loads(prior[0])
            if any(saved['lineage'][k]!=link[k] for k in ('attempt_id','provider_receipt_id','crm_lead_id','business_inquiry_id')):
                raise ValueError('Native receipt lineage conflict; owner investigation required')
            return saved
        value={'lineage':link,'state':'VERIFIED_LOCAL_LINK','at':now.isoformat(),'provider_writes':0,'execution_authorized':False}
        ActionEvidence.append(db,aid,'business_inquiry_lineage',value,now)
        return value
