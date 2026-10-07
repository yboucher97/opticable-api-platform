"""Bridge the existing scoped effect journal to the universal action contract."""
from datetime import datetime, timedelta, timezone
from .action_evidence import ActionEvidence, envelope, approval_binding
from .acquisition_store import digest


def prepare_effect(journal, effect, *, scope='EXISTING_EXACT_SCOPE', before=None, source=None):
    now=datetime.now(timezone.utc);audit=ActionEvidence(journal.path)
    if audit.get(effect.action_id):return audit
    payload=effect.payload;method=payload.get('method');path=payload.get('path','UNKNOWN');service=payload.get('service','UNKNOWN')
    irreversible=service=='mail' or path.endswith('/actions/convert')
    updating=method in {'PUT','PATCH','DELETE'}
    if before is None and not updating:before={'exists':False,'basis':'New effect; exact existing deduplication/claim boundary'}
    reversible=updating and before is not None and method!='DELETE'
    plan=envelope(effect.action_id,scope,{'type':service,'identity':path},now,
        mutation=True,initiator='EXISTING_ROOT_SCOPED_RUNNER',trigger=digest(source or {'request_key':effect.request_key}),
        provider=service,source_system='EXISTING_LIFECYCLE',before_state=before,proposed_state=payload.get('body'),
        provider_request=payload,exact_versions={'payload_hash':effect.payload_hash,'request_key':effect.request_key,
            'before_version':(before or {}).get('Modified_Time'),'source_hash':digest(source or {})},
        reason='Existing exact scoped action; independent root authority and off-host claim remain required',
        business_rationale='Execute only the eligible source/ownership condition in the previously authorized scope',
        evidence_refs=[{'source_hash':digest(source or {}),'scope':scope}],decision_rules=['Existing root policy','Fresh immutable source','Exact off-host claim'],
        authority_class=scope,automatic_rule='Validated existing root scope and exact source/ownership conditions',
        rollback_capability='IRREVERSIBLE' if irreversible else 'REVERSIBLE_WITH_LIMITATIONS' if reversible else 'COMPENSATING_ACTION_ONLY' if not updating else 'UNKNOWN',
        irreversible=irreversible,approval_required=irreversible,
        rollback_target=before if reversible else None,
        rollback_procedure='Owner-reviewed conditional restoration of captured values; preserve newer provider changes and history' if reversible else None,
        consequence='Sent communication/conversion may be externally consumed and cannot be undone' if irreversible else 'Provider object may exist or affect related workflow',
        compensating_action='Owner reviews correction/follow-up or marks derived object inactive; no automatic deletion or resend')
    audit.plan(plan,now)
    if irreversible:
        # The pre-existing exact root effect authorization remains a delegated
        # approval boundary. Record that provenance; never claim a new human click.
        audit.approve(effect.action_id,'EXISTING_ROOT_DELEGATED_SCOPE',now,binding=approval_binding(plan),
            expires_at=(now+timedelta(minutes=2)).isoformat())
    return audit


def start_effect(journal, effect, scope, client):
    audit=ActionEvidence(journal.path);plan=audit.get(effect.action_id)
    if not plan:
        before=None
        if effect.payload.get('method') in {'PUT','PATCH','DELETE'}:
            response=client.request(effect.payload['service'],'GET',effect.payload['path'])
            data=response.get('data',response);before=(data.get('data') or [data])[0] if isinstance(data,dict) else data
        audit=prepare_effect(journal,effect,scope=scope,before=before)
    # Existing journal preparation cannot arm a second execution/replay.
    if audit.get(effect.action_id)['status']=='STARTED':return
    audit.start(effect.action_id,datetime.now(timezone.utc),authority_check=lambda:None)


def effect_event(journal, effect, kind, value):
    audit=ActionEvidence(journal.path);plan=audit.get(effect.action_id)
    if not plan:return
    now=datetime.now(timezone.utc)
    if kind in {'verified','customer_verified'} and plan['status']=='STARTED':
        audit.finish(effect.action_id,now,provider_success=True,actual_after=value,verified=True,response={'acknowledged':True})
    elif kind in {'exception','customer_exception'} and plan['status']=='STARTED':
        audit.finish(effect.action_id,now,provider_success=False,failure={'stage':'PROVIDER_EXECUTION_OR_READBACK',
            'error_class':value.get('type','ProviderUncertain'),'provider_status':value.get('status'),
            'safe_details':value,'partial_effects':'UNKNOWN','recovery_action':'Read-only reconciliation; no automatic retry'})
    else:
        audit.event(effect.action_id,'TECHNICAL_AUDIT',kind,value,now)
