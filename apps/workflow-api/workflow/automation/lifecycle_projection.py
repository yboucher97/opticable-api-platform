"""Bounded adapters for existing cached observations and exact relationships."""
from .acquisition_store import digest
from .lifecycle_truth import context_key, derive, stamp, valid_event
import re


def ref(system, kind, identifier):
    return {'system': system, 'entity_type': kind, 'entity_id': str(identifier)}


def fact(context, kind, source, event_at, source_at, observed_at, native_id, **extra):
    return {'context': context, 'event_type': kind, 'source': source, 'event_at': event_at,
            'source_at': source_at, 'observed_at': observed_at,
            'source_reference':str(native_id),
            'event_id': digest([context, kind, source, native_id, event_at, source_at]),
            'identity_confidence': 'EXACT', 'confidence': 'HIGH',
            'truth_class': 'PROVIDER_FACT', **extra}


def conversation_facts(c):
    context = ref('OUTREACH', 'CONVERSATION', c['conversation_id'])
    evidence = c.get('source_evidence') or {}
    events = []
    for message in evidence.get('message_refs', []):
        if message.get('match') != 'EXACT_REFERENCES_AND_SENDER':
            continue
        events.append(fact(context, 'CUSTOMER_REPLIED', 'MAIL', message.get('at'), None,
                           evidence.get('mail_at'), message['id'], proof='EXACT_THREAD',
                           detail={'reply_kind': 'QUESTION' if c.get('reply_class') == 'ASKING_QUESTION' else 'OTHER',
                                   'intent_confidence': c.get('confidence', 'INSUFFICIENT')}))
    # Only explicitly linked messages can complete a reply. A latest account
    # send or Apollo reply flag is not a response to this inbound message.
    for event in c.get('business_events', []):
        if valid_event(event) and event['context'] == context:
            events.append(event)
    return events


def conversation_state(c, now):
    if c.get('suppression') or c.get('reply_class') in {'NOT_NOW', 'NOT_INTERESTED', 'UNSUBSCRIBE', 'BOUNCE', 'WRONG_PERSON', 'LEFT_COMPANY'}:
        return {'current_state': 'SUPPRESSED' if c.get('suppression') else 'OWNER_DEFERRED',
                'next_action': 'NO_ACTION', 'actionability': 'NO_ACTION', 'reason_code': 'CONTACT_DEFERRED_OR_SUPPRESSED',
                'confidence': c.get('confidence', 'INSUFFICIENT'), 'latest_authoritative_event': None,
                'last_event_at': c.get('last_reply_at'), 'response_status': 'UNKNOWN',
                'waiting_reason': 'CONTACT_DEFERRED_OR_SUPPRESSED', 'followup_due_state': 'POLICY_UNKNOWN',
                'source_health': c.get('lifecycle_coverage', {}), 'execution_authorized': False}
    return derive(conversation_facts(c), context=ref('OUTREACH', 'CONVERSATION', c['conversation_id']),
                  now=now, coverage=c.get('lifecycle_coverage'), followup=c.get('followup_policy'),
                  owner=c.get('current_owner'))


def collect_states(inputs, now, store=None,*,record_facts=False):
    """No new reads. Source health and negative conclusions remain scoped."""
    contexts = {}; events = []; aliases = {}; coverage = {}; policies = {}; owners = {};labels={}
    snapshot = inputs.get('business', {}).get('snapshot', {})
    observed = snapshot.get('observed_at')
    modules = snapshot.get('collection', {}).get('modules', {})
    def add(event):
        key = context_key(event['context']); contexts[key] = event['context']; events.append(event)
    def alias(left, right):
        # Only unambiguous native object relations; no account-wide folding.
        aliases.setdefault(context_key(left), set()).add(context_key(right))
    estimates = snapshot.get('books_estimate_index', {})
    estimates = list(estimates.values()) if isinstance(estimates, dict) else estimates
    for e in estimates[:1000]:
        if not e.get('estimate_id'):
            continue
        context = ref('BOOKS', 'ESTIMATE', e['estimate_id']); key = context_key(context)
        labels[key]=e.get('estimate_number') or e['estimate_id']
        coverage[key] = {'books': modules.get('books_estimate_index', {'completeness': 'UNKNOWN'})}
        status = e.get('status')
        kind = {'draft': 'QUOTE_DRAFTED', 'sent': 'QUOTE_SENT_RECORDED', 'accepted': 'QUOTE_ACCEPTED',
                'declined': 'QUOTE_DECLINED', 'expired': 'QUOTE_EXPIRED'}.get(status, 'ESTIMATE_EXISTS')
        add(fact(context, kind, 'BOOKS', e.get('status_event_at'), e.get('last_modified_time') or e.get('created_time'),
                 observed, e['estimate_id'], detail={'status': status,**({'completion_state':'UNKNOWN'} if status=='draft' else {})}))
        # The existing finance adapter's structured native history proof is
        # reused when retained; sent_at alone without proof isn't sufficient.
        proof = e.get('native_sent_evidence') or {}
        if proof.get('decision') == 'OBSERVE' and str(proof.get('estimate_id')) == str(e['estimate_id']):
            add(fact(context, 'QUOTE_SENT', 'BOOKS', proof.get('sent_at'), None, observed,
                     proof.get('comment_id'), proof='BOOKS_SYSTEM_EMAIL_HISTORY'))
        for invoice in e.get('invoice_ids', []):
            identifier = invoice.get('invoice_id') if isinstance(invoice, dict) else invoice
            if identifier:
                alias(ref('BOOKS', 'INVOICE', identifier), context)
        if e.get('zcrm_potential_id'):
            alias(ref('CRM','DEAL',e['zcrm_potential_id']),context)
    for i in snapshot.get('books_invoices', [])[:1000]:
        if not i.get('invoice_id'):
            continue
        context = ref('BOOKS', 'INVOICE', i['invoice_id'])
        if i.get('estimate_id'):
            alias(context, ref('BOOKS', 'ESTIMATE', i['estimate_id']))
        if i.get('status') == 'void':continue
        add(fact(context, 'PAID' if i.get('status') == 'paid' else 'INVOICE_CREATED' if i.get('status')=='draft' else 'INVOICED', 'BOOKS',
                 i.get('status_event_at'), i.get('last_modified_time') or i.get('created_time'), observed,
                 i['invoice_id']))
    stages={'Closed Won':'QUOTE_ACCEPTED','Closed Lost':'QUOTE_DECLINED','Work Scheduled':'WORK_SCHEDULED',
            'Work In Progress':'WORK_IN_PROGRESS','Work Completed':'WORK_COMPLETED'}
    for deal in snapshot.get('deals',[])[:500]:
        kind=stages.get(deal.get('Stage'))
        if kind and deal.get('id'):
            add(fact(ref('CRM','DEAL',deal['id']),kind,'CRM',deal.get('stage_event_at'),deal.get('Modified_Time'),observed,deal['id']))
    for lead in snapshot.get('leads', [])[:500]:
        if not lead.get('id') or lead.get('Lead_Status') in {'Converted', 'Lost', 'Lost Lead', 'Not Qualified', 'Junk Lead'} or lead.get('$converted'):
            continue
        add(fact(ref('CRM', 'LEAD', lead['id']), 'INQUIRY_RECEIVED', 'CRM', lead.get('Created_Time'), None,
                 observed, lead['id']))
    for t in inputs.get('trigger-intelligence',{}).get('rows',[])[:300]:
        native=re.fullmatch(r'ocds-ec9k95-([0-9]+)',str(t.get('source_record_id','')))
        if not native or t.get('source_provider')!='seao' or t.get('status')!='OPEN':continue
        context=ref('PUBLIC','TENDER',native[1]);labels[context_key(context)]=t.get('company_name') or native[1]
        add(fact(context,'TENDER_OPEN','PUBLIC',t.get('publish_date'),t.get('source_version_at'),
                 t.get('last_verified_at'),t['source_record_id'],truth_class='PUBLIC_SOURCE_FACT',
                 detail={'deadline':t.get('closing_date'),'eligibility':'UNKNOWN','submission_status':'UNKNOWN'}))
        for system in ('OPTIBRAIN','ACQUISITION'):
            alias(ref(system,'TRIGGER',t['key']),context)
    for c in inputs.get('sales-conversations', {}).get('conversations', [])[:150]:
        context = ref('OUTREACH', 'CONVERSATION', c['conversation_id']); key = context_key(context)
        labels[key]=c.get('company') or c.get('person_name') or c['conversation_id']
        contexts[key] = context
        coverage[key] = c.get('lifecycle_coverage', {'mail': {'completeness': 'PARTIAL'}, 'apollo': {'completeness': 'PARTIAL'}})
        owners[key] = c.get('current_owner'); policies[key] = c.get('followup_policy')
        events.extend(conversation_facts(c))
        # A conversation may have several projects. Never join them via Account.
        refs = c.get('commercial_contexts', [])
        if len(refs) == 1:
            alias(context, refs[0])
        for kind in ('SALES_REPLY', 'CUSTOMER_EXPANSION'):
            alias(ref('OUTREACH', kind, c['conversation_id']), context)
    for event in inputs.get('business_events', [])[:4000]:
        if valid_event(event):
            add(event)
    if store:
        if record_facts:
            for event in events:
                if valid_event(event):store.record_business_fact(event,now)
        for event in store.business_facts():
            add(event)
    # Optional retained, exact-scoped coverage/policy metadata. Absence stays
    # unknown; a globally complete mailbox flag cannot clear another context.
    for key,value in list(inputs.get('lifecycle_coverage',{}).items())[:4000]:
        if key in contexts:coverage[key]=value
    for key,value in list(inputs.get('followup_policies',{}).items())[:4000]:
        if key in contexts:policies[key]=value
    # A revision only aliases to its predecessor with an explicit native
    # relationship; two estimates for one customer remain independent.
    for e in estimates[:1000]:
        if e.get('supersedes_estimate_id'):
            alias(ref('BOOKS', 'ESTIMATE', e['estimate_id']), ref('BOOKS', 'ESTIMATE', e['supersedes_estimate_id']))
    resolved = {k: next(iter(v)) for k, v in aliases.items() if len(v) == 1}
    def canonical(key):
        seen = set()
        while key in resolved and key not in seen:
            seen.add(key); key = resolved[key]
        return key
    grouped = {}
    for e in events:
        key = canonical(context_key(e['context']))
        context = contexts.get(key)
        if context is None:
            context = dict(zip(('system', 'entity_type', 'entity_id'), key.split(':', 2)))
            contexts[key] = context
        grouped.setdefault(key, []).append({**e, 'source_context':e['context'], 'context': context})
    states = {};canonical_states={}
    for key, context in list(contexts.items()):
        can = canonical(key)
        contexts.setdefault(can,dict(zip(('system','entity_type','entity_id'),can.split(':',2))))
        if can not in canonical_states:
            facts=grouped.get(can,[])
            preliminary=derive(facts,context=contexts[can],now=now)
            latest=preliminary.get('latest_authoritative_event') or {}
            active=context_key(latest.get('source_context') or contexts[can])
            health=dict(coverage.get(active,{}))
            for field in ('response','downstream'):
                scoped=health.get(field,{})
                if scoped.get('context_key')==active and canonical(active)==can:
                    health[field]={**scoped,'context_key':can,'source_context_key':active}
            policy=policies.get(active)
            if policy and policy.get('context_key')==active and canonical(active)==can:
                policy={**policy,'context_key':can,'source_context_key':active}
            state=derive(facts,context=contexts[can],now=now,coverage=health,followup=policy,owner=owners.get(active))
            state['context_label']=labels.get(active) or labels.get(can) or context['entity_id']
            canonical_states[can]=state
        state=canonical_states[can]
        states[key] = state
        states[can] = state
    for alias_key in resolved:
        can=canonical(alias_key)
        if can in states:states.setdefault(alias_key,states[can])
    return states


def reconcile_priority(row, states):
    """Projection-only invalidation; immutable historical rows stay intact."""
    target = (row.get('targets') or [None])[0]
    state = states.get(context_key(target)) if target else None
    result = dict(row)
    commercial = target and target.get('entity_type') in {'ESTIMATE', 'INVOICE', 'DEAL', 'CONVERSATION', 'SALES_REPLY', 'LEAD'}
    if state:
        result.update(lifecycle=state, current_state=state['current_state'], next_action=state['next_action'],
                      actionability=state['actionability'], reason_code=state['reason_code'],
                      deadline=state.get('deadline'), due_at=state.get('deadline'), confidence=state['confidence'])
        if state['actionability'] in {'WAITING', 'NO_ACTION'}:
            result['status'] = 'SUPERSEDED'
            result['invalidation_reason'] = 'COMPLETED_OR_NO_LONGER_ACTIONABLE_BY_EVIDENCE'
        elif result.get('status')=='SUPERSEDED':
            result['status']='CURRENT_DERIVED_ACTION';result['preview']=None
        # Verification is the current task; stale send/preparation wording must
        # not survive as a top action's title.
        result['original_recommendation']={'what':row.get('what'),'next_action':row.get('next_action')}
        result['recommendation_state']='SUPERSEDED_BY_EVIDENCE' if state.get('latest_authoritative_event') else 'UNVERIFIED'
        result['what'] = state['next_action'].replace('_', ' ').title() + ' · ' + state.get('context_label',str(target['entity_id']))
        result['why'] = state['reason_code']
        if str(result.get('dependency','')).startswith('Fresh conversation/contact/suppression/manual owner context'):
            result['dependency'] = None  # verification itself is the current action
    elif commercial:
        result.update(current_state='UNKNOWN', actionability='VERIFY_FIRST', reason_code='VERIFY_CURRENT_STATE',
                      next_action='Verify current business state', confidence='INSUFFICIENT')
    else:
        # Independent optimization/research domains retain their own semantics.
        result.setdefault('actionability', 'BLOCKED' if result.get('dependency') or result.get('blocker') else
                          'ACTIONABLE_NOW' if target and target.get('entity_type')=='BUSINESS_PRIORITY' and row.get('domain')=='MANAGER' else 'OPTIONAL')
        result.setdefault('reason_code', 'OWNER_REVIEW_REQUIRED')
    return result
