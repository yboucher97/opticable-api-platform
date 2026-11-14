"""Development-only native Leads field contract and exact-ID mapping. No client.

Produces a reviewable payload, never writes CRM or treats UTM text as verified
campaign attribution. Legacy IDs and first-touch values are immutable here.
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
    if not field or field.get('data_type')!='text' or field.get('read_only') or field.get('field_read_only') or field.get('length',0)<len(attempt) or not field.get('operation_type',{}).get('api_update'):
        raise ValueError('Current writable native Inquiry_ID text contract required')
    existing=lead.get('Inquiry_ID')
    if existing and existing!=attempt:raise ValueError('Existing legacy/conflicting inquiry identity preserved; no overwrite')
    return {'module':'Leads','record_id':lead['id'],'fields':{} if existing==attempt else {'Inquiry_ID':attempt},
            'precondition':{'Inquiry_ID':existing},'first_touch_unchanged':True,'state':'REVIEW_ONLY_NO_TRANSPORT',
            'native_schema_change_required':False,'execution_authorized':False,'provider_writes':0,
            'required_approval':'Exact coordinated parser/capture/mapping release and separately gated CRM operation'}


def verify_readback(plan, record):
    expected=plan['fields'].get('Inquiry_ID',plan['precondition']['Inquiry_ID'])
    return bool(record.get('id')==plan['record_id'] and record.get('Inquiry_ID')==expected)
