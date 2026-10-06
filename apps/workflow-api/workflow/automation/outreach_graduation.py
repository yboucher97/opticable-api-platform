"""Non-executing sealed future operation validation. No transport or authority.

Passing a fixture validates a candidate structure only. Even a valid, approved
spec cannot send or mutate Apollo in Phase34.
"""
from .acquisition_store import digest
from .sales_intelligence import stamp

def seal(proposal,recipients,message,channel,limits):
    return digest({'proposal':proposal,'recipients':recipients,'message':message,'channel':channel,'limits':limits})

def validate_candidate(spec,*,now):
    required={'proposal','recipients','message','channel','limits','hash','approval_receipt'}
    if set(spec)!=required:raise ValueError('Exact future specification required')
    if spec['hash']!=seal(spec['proposal'],spec['recipients'],spec['message'],spec['channel'],spec['limits']):raise ValueError('Altered sealed proposal')
    if not isinstance(spec['recipients'],list) or not 1<=len(spec['recipients'])<=10:raise ValueError('Bounded exact recipients')
    limit=spec['limits'];expiry=stamp(limit.get('expires_at'))
    if not expiry or not now<expiry or limit.get('daily_cap',0) not in range(1,11) or limit.get('kill_switch') is not False:raise ValueError('Cap, expiry and kill-switch proof required')
    for r in spec['recipients']:
        if not r.get('native_person_id') or r.get('owner')!='OPTIBRAIN_FUTURE' or r.get('contact_confidence') not in {'VERIFIED_CURRENT','SUPPORTED_CURRENT'}:raise ValueError('Recipient and exclusive owner binding')
        if r.get('suppressed') is not False or r.get('collision')!='CLEAR' or r.get('recent_contact') is not False or r.get('manual_context_verified') is not True:raise ValueError('Fresh collision and suppression requirements')
    approval=spec['approval_receipt']
    if approval.get('hash')!=spec['hash'] or not approval.get('approved_by') or not stamp(approval.get('approved_at')):raise ValueError('Exact approval receipt required')
    return {'structure_valid':True,'execution_authorized':False,'provider_writes':0,
            'idempotency_key':digest([spec['hash'],'FUTURE_OPERATION']),
            'unknown_effect':'HOLD — NO RETRY UNTIL READ-AFTER-WRITE RECONCILIATION'}

def execution_allowed(*args,**kwargs):return False
