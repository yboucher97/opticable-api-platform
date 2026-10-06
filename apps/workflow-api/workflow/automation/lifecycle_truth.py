"""Deterministic commercial facts -> current state -> owner action.

No provider calls, text inference, persistent derived truth or send authority.
Contexts are exact commercial objects, never fuzzy company identities.
"""
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo


EVENTS = set('INQUIRY_RECEIVED QUALIFICATION_NEEDED QUALIFIED QUOTE_REQUESTED ESTIMATE_EXISTS '
             'QUOTE_DRAFTED QUOTE_READY QUOTE_SENT QUOTE_SENT_RECORDED CUSTOMER_REPLIED '
             'REVISION_REQUESTED QUOTE_REVISED QUOTE_ACCEPTED QUOTE_DECLINED QUOTE_EXPIRED '
             'FOLLOWUP_DUE FOLLOWUP_SENT RESPONSE_SENT WORK_SCHEDULED WORK_IN_PROGRESS '
             'WORK_COMPLETED INVOICE_CREATED INVOICED PAID DORMANT REACTIVATION_CANDIDATE '
             'DELIVERABLE_PROMISED DELIVERABLE_COMPLETED TENDER_OPEN TENDER_SUBMITTED '
             'WAITING_PROVIDER WAITING_NATURAL_EVENT OWNER_DEFERRED'.split())
CORRECTION_REASONS = set('MISSING_EVENT BAD_SOURCE_PRECEDENCE STALE_CACHE FAILED_IDENTITY_LINK '
                         'MISSING_REPLY_DETECTION DERIVED_ACTION_PERSISTED OWNER_CURRENT_STATE'.split())
PROGRESSION = {'QUOTE_SENT': 3, 'QUOTE_SENT_RECORDED': 3, 'QUOTE_ACCEPTED': 4,
               'WORK_SCHEDULED': 5, 'WORK_IN_PROGRESS': 6, 'WORK_COMPLETED': 7,
               'INVOICE_CREATED': 8, 'INVOICED': 8, 'PAID': 9}
PREPARATION = {'INQUIRY_RECEIVED', 'QUALIFICATION_NEEDED', 'QUALIFIED', 'QUOTE_REQUESTED',
               'ESTIMATE_EXISTS', 'QUOTE_DRAFTED', 'QUOTE_READY', 'QUOTE_REVISED'}
RESPONSE_EVENTS = {'CUSTOMER_REPLIED', 'REVISION_REQUESTED', 'QUOTE_ACCEPTED', 'QUOTE_DECLINED'}


def stamp(value):
    try:
        at = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return at.astimezone(timezone.utc) if at.tzinfo else None
    except (ValueError, TypeError):
        return None


def context_key(context):
    if not isinstance(context, dict) or set(context) != {'system', 'entity_type', 'entity_id'}:
        raise ValueError('Exact commercial context required')
    if any(not isinstance(v, str) or not v or len(v) > 200 for v in context.values()):
        raise ValueError('Bounded commercial context required')
    return ':'.join(context[k] for k in ('system', 'entity_type', 'entity_id'))


def authority(event):
    """Authority is fact-specific, not a global provider ranking."""
    kind, source = event.get('event_type'), event.get('source')
    if event.get('truth_class') == 'OWNER_VERIFIED_FACT' and source == 'OWNER':
        return 4
    if event.get('truth_class') not in {'PROVIDER_FACT', 'PUBLIC_SOURCE_FACT'}:
        return 0  # Tasks, priorities, proposals and refreshed projections are not facts.
    if source == 'BOOKS' and kind in PREPARATION | set(PROGRESSION) | {'QUOTE_DECLINED', 'QUOTE_EXPIRED'}:
        if kind == 'QUOTE_SENT' and event.get('proof') != 'BOOKS_SYSTEM_EMAIL_HISTORY':
            return 0
        return 3
    if source in {'MAIL', 'APOLLO'} and kind in RESPONSE_EVENTS | {'QUOTE_SENT', 'FOLLOWUP_SENT', 'RESPONSE_SENT', 'INQUIRY_RECEIVED', 'DELIVERABLE_PROMISED', 'DELIVERABLE_COMPLETED'}:
        return 3 if event.get('proof') in {'EXACT_THREAD', 'EXACT_OBJECT', 'PROVIDER_MESSAGE'} else 0
    if source == 'CRM' and kind in PREPARATION | {'QUOTE_ACCEPTED','QUOTE_DECLINED','CUSTOMER_REPLIED','REVISION_REQUESTED',
            'WORK_SCHEDULED','WORK_IN_PROGRESS','WORK_COMPLETED','DELIVERABLE_PROMISED','DELIVERABLE_COMPLETED',
            'WAITING_PROVIDER','WAITING_NATURAL_EVENT','OWNER_DEFERRED','DORMANT','REACTIVATION_CANDIDATE','FOLLOWUP_DUE'}:
        return 3
    if source == 'FORMS' and kind == 'INQUIRY_RECEIVED':
        return 3
    if source == 'PUBLIC' and kind in {'TENDER_OPEN', 'TENDER_SUBMITTED'}:
        return 3
    return 0


def valid_event(event):
    try:
        context_key(event['context'])
        return (event['event_type'] in EVENTS and bool(event.get('event_id')) and
                event.get('identity_confidence') in {'EXACT', 'VERIFIED'} and
                event.get('confidence') in {'HIGH', 'MODERATE'} and authority(event) > 0)
    except (KeyError, TypeError, ValueError):
        return False


def derive(events, *, context, now, coverage=None, followup=None, owner=None):
    """Latest authoritative business event wins within an exact object.

    event_at is occurrence time; source_at is version/status time; observed_at
    is collection time. Unknown occurrence time never becomes collection time.
    A status observation can suppress preparation but cannot prove actual send.
    """
    key = context_key(context)
    if now.tzinfo is None:
        raise ValueError('Aware lifecycle clock required')
    coverage = coverage or {}
    facts = [e for e in events if valid_event(e) and context_key(e['context']) == key and
             ((stamp(e.get('event_at')) or stamp(e.get('source_at'))) or PROGRESSION.get(e['event_type'],0)>=4) and
             ((stamp(e.get('event_at')) or stamp(e.get('source_at'))) or datetime.min.replace(tzinfo=timezone.utc)) <= now]
    facts.sort(key=lambda e: (stamp(e.get('event_at')) or stamp(e.get('source_at')) or datetime.min.replace(tzinfo=timezone.utc),
                              authority(e), stamp(e.get('source_at')) or datetime.min.replace(tzinfo=timezone.utc),
                              PROGRESSION.get(e['event_type'], 0), str(e['event_id'])))
    current = None;stage_event=None
    milestone = 0
    for event in facts:
        kind = event['event_type']
        if kind == 'FOLLOWUP_DUE':
            followup = {**(event.get('detail') or {}), 'authoritative': True, 'context_key': key,
                        'assigned_at': event.get('event_at') or event.get('source_at')}
            continue
        # Re-observed drafts do not reopen sent/accepted/invoiced work. An
        # explicit revision request opens a revision cycle for this object.
        if current and current['event_type'] in {'QUOTE_DECLINED','QUOTE_EXPIRED'} and kind in PREPARATION:
            continue  # reactivation is a separate, explicit business context
        if kind == 'REVISION_REQUESTED' and milestone <= 4:
            milestone = 0;stage_event=None
        elif kind in PREPARATION and milestone >= 3:
            continue
        elif kind in PROGRESSION and PROGRESSION[kind] < milestone:
            continue
        elif kind in {'QUOTE_ACCEPTED','QUOTE_DECLINED','FOLLOWUP_SENT','FOLLOWUP_DUE'} and milestone >= 5:
            continue
        elif kind == 'QUOTE_SENT_RECORDED' and current and current['event_type'] in {'QUOTE_SENT', 'CUSTOMER_REPLIED', 'RESPONSE_SENT', 'FOLLOWUP_SENT', 'REVISION_REQUESTED'}:
            continue
        current = event
        if kind in PROGRESSION:stage_event=event
        milestone = max(milestone, PROGRESSION.get(kind, 0))
    result = {'schema': 1, 'context': context, 'source_facts': list(dict.fromkeys(e['event_id'] for e in facts)),
              'current_state': 'UNKNOWN', 'next_action': 'VERIFY_CURRENT_STATE',
              'actionability': 'VERIFY_FIRST', 'reason_code': 'VERIFY_CURRENT_STATE',
              'waiting_reason': None, 'followup_due_state': 'UNKNOWN',
              'response_status': 'UNKNOWN', 'confidence': 'INSUFFICIENT',
              'latest_authoritative_event': current, 'last_event_at': current.get('event_at') if current and current.get('time_basis')!='ASSERTION_AT' else None,
              'source_health': coverage, 'truth_class': 'DERIVED_DETERMINISTICALLY',
              'execution_authorized': False, 'deadline': None}
    result['commercial_stage']=stage_event['event_type'] if stage_event else None
    def action(state, next_action, gate, reason, waiting=None):
        result.update(current_state=state, next_action=next_action, actionability=gate,
                      reason_code=reason, waiting_reason=waiting)
    if not current:
        return result
    latest_time = stamp(current.get('event_at')) or stamp(current.get('source_at'))
    # Fresh collection can support confidence in the same fact without ever
    # making its occurrence newer or reviving an older preparation event.
    observations = [stamp(e.get('observed_at')) for e in facts if
                    e['event_type'] == current['event_type'] and authority(e) == authority(current) and
                    (stamp(e.get('event_at')) or stamp(e.get('source_at'))) == latest_time]
    observed = max((at for at in observations if at and at <= now), default=None)
    result['evidence_observed_at'] = observed.isoformat() if observed else None
    competing = {e['event_type'] for e in facts if
                 (stamp(e.get('event_at')) or stamp(e.get('source_at'))) == latest_time and authority(e) == authority(current)}
    if {'QUOTE_ACCEPTED','QUOTE_DECLINED'} <= competing:
        result.update(current_state='UNKNOWN',next_action='VERIFY_CURRENT_STATE',actionability='VERIFY_FIRST',
                      reason_code='CONFLICTING_AUTHORITATIVE_EVENTS',confidence='INSUFFICIENT')
        return result
    kind = current['event_type']
    result['confidence'] = current['confidence']
    if not stamp(current.get('event_at')) and not stamp(current.get('source_at')):
        result['confidence'] = 'MODERATE'  # exact current existence, chronology unknown
    data = current.get('detail') or {}
    if kind=='QUOTE_SENT' and current.get('time_basis')=='ASSERTION_AT':
        replies=[e for e in facts if e['event_type'] in {'CUSTOMER_REPLIED','REVISION_REQUESTED'} and stamp(e.get('event_at'))]
        real_sends=[e for e in facts if e['event_type'] in {'QUOTE_SENT','RESPONSE_SENT','FOLLOWUP_SENT'} and e.get('time_basis')!='ASSERTION_AT' and stamp(e.get('event_at'))]
        latest_send=max((stamp(e['event_at']) for e in real_sends),default=None)
        pending=[e for e in replies if not latest_send or stamp(e['event_at'])>latest_send]
        if pending:
            result.update(current_state='SENT_WITH_REPLY_ORDER_UNKNOWN',next_action='VERIFY_RESPONSE_STATUS',
                          actionability='VERIFY_FIRST',reason_code='VERIFY_REPLY_STATUS',confidence='MODERATE',
                          response_status='REPLY_OBSERVED_ORDER_UNKNOWN',latest_reply_event=pending[-1])
            return result
    reply_health = coverage.get('response', {})
    through = stamp(reply_health.get('through_at'))
    # A bounded search_complete flag alone is not complete inbound AND outbound
    # history. It must cover this exact thread/object through the decision time.
    complete = (reply_health.get('completeness') == 'COMPLETE' and through is not None and
                through >= now and reply_health.get('context_key') == key)
    result['response_status'] = 'NO_LATER_RESPONSE_OBSERVED' if complete else 'UNKNOWN'
    if kind in {'INQUIRY_RECEIVED', 'QUALIFICATION_NEEDED'}:
        action('QUALIFICATION_NEEDED' if complete else 'INQUIRY_RESPONSE_UNKNOWN', 'QUALIFY_INQUIRY' if complete else 'VERIFY_RESPONSE_STATUS',
               'ACTIONABLE_NOW' if complete else 'VERIFY_FIRST',
               'NEW_INBOUND_REQUIRES_REPLY' if complete else 'VERIFY_REPLY_STATUS')
    elif kind=='QUALIFIED':
        action('QUALIFIED','VERIFY_NEXT_COMMERCIAL_STEP','VERIFY_FIRST','QUALIFIED_NEXT_STEP_UNKNOWN')
    elif kind in {'QUOTE_REQUESTED', 'QUOTE_DRAFTED', 'QUOTE_REVISED', 'QUOTE_READY'}:
        next_action={'QUOTE_REQUESTED':'PREPARE_QUOTE','QUOTE_DRAFTED':'FINISH_QUOTE',
                     'QUOTE_REVISED':'REVIEW_REVISED_QUOTE','QUOTE_READY':'REVIEW_READY_QUOTE'}[kind]
        action(kind,next_action,'ACTIONABLE_NOW','QUOTE_DRAFT_INCOMPLETE' if kind in {'QUOTE_REQUESTED','QUOTE_DRAFTED'} else 'QUOTE_READY_FOR_REVIEW')
        if data.get('completion_state')=='UNKNOWN':
            action(kind,'VERIFY_QUOTE_STATE','VERIFY_FIRST','VERIFY_QUOTE_COMPLETENESS')
    elif kind in {'QUOTE_SENT', 'FOLLOWUP_SENT', 'RESPONSE_SENT'}:
        state = result['commercial_stage'] if milestone>=5 else 'WAITING_CUSTOMER' if complete else 'SENT_RESPONSE_UNKNOWN'
        action(state, 'NO_ACTION', 'WAITING', 'FOLLOWUP_POLICY_UNKNOWN', 'FOLLOWUP_POLICY_UNKNOWN')
        policy = {} if milestone>=5 else followup or {}
        due = stamp(policy.get('due_at'))
        anchor = stamp(current.get('event_at')) if current.get('time_basis') != 'ASSERTION_AT' else None
        if policy.get('authoritative') is True and policy.get('context_key') == key:
            # A superseded task due date does not survive a newer outbound.
            created = stamp(policy.get('assigned_at'))
            if due and anchor and due >= anchor and created and created >= anchor:
                result['deadline'] = due.isoformat()
            elif anchor and isinstance(policy.get('delay_days'), int) and policy['delay_days'] >= 0 and policy.get('rule_id'):
                due = anchor + timedelta(days=policy['delay_days'])
                result['deadline'] = due.isoformat()
            else:
                due = None
        else:
            due = None
        if due:
            result['followup_due_state'] = 'FUTURE' if due > now else 'DUE'
            if due > now:
                action(state, 'NO_ACTION', 'WAITING', 'FOLLOWUP_NOT_DUE', 'FOLLOWUP_NOT_DUE')
            elif complete:
                action('FOLLOWUP_DUE', 'FOLLOW_UP', 'ACTIONABLE_NOW', 'QUOTE_FOLLOWUP_DUE')
            else:
                action(state, 'VERIFY_RESPONSE_STATUS', 'VERIFY_FIRST', 'VERIFY_REPLY_STATUS')
        else:
            result['followup_due_state'] = 'POLICY_UNKNOWN'
    elif kind in {'CUSTOMER_REPLIED', 'REVISION_REQUESTED'}:
        result['response_status'] = 'REPLY_OBSERVED'
        intent = 'REVISION' if kind == 'REVISION_REQUESTED' else data.get('reply_kind', 'OTHER')
        if milestone>=5:
            action('POST_DELIVERY_REPLY', 'PROCESS_REPLY' if complete else 'VERIFY_RESPONSE_STATUS',
                   'ACTIONABLE_NOW' if complete else 'VERIFY_FIRST', 'NEW_INBOUND_REQUIRES_REPLY' if complete else 'VERIFY_REPLY_STATUS')
        elif intent == 'REVISION' and data.get('intent_confidence', current['confidence']) == 'HIGH' and complete:
            action('REVISION_REQUESTED', 'REVISE_QUOTE', 'ACTIONABLE_NOW', 'CUSTOMER_REVISION_REQUESTED')
        else:
            action('CUSTOMER_REPLIED', 'PROCESS_REPLY' if complete else 'VERIFY_RESPONSE_STATUS',
                   'ACTIONABLE_NOW' if complete else 'VERIFY_FIRST',
                   'NEW_INBOUND_REQUIRES_REPLY' if complete else 'VERIFY_REPLY_STATUS')
    elif kind == 'QUOTE_SENT_RECORDED':
        action('SENT_RECORDED_DELIVERY_UNKNOWN', 'VERIFY_DELIVERY_STATUS', 'VERIFY_FIRST', 'VERIFY_QUOTE_DELIVERY')
    elif kind == 'QUOTE_ACCEPTED':
        downstream = coverage.get('downstream',{})
        downstream_at = stamp(downstream.get('through_at'))
        known = downstream.get('completeness')=='COMPLETE' and downstream.get('context_key')==key and downstream_at and downstream_at>=now
        action('ACCEPTED_WORK', 'REVIEW_ACCEPTED_WORK' if known else 'VERIFY_ACCEPTED_WORK_STATUS',
               'ACTIONABLE_NOW' if known else 'VERIFY_FIRST', 'ACCEPTED_WORK_HANDOFF' if known else 'VERIFY_WORK_PROGRESSION')
    elif kind in {'INVOICE_CREATED', 'INVOICED', 'PAID', 'WORK_COMPLETED', 'QUOTE_DECLINED', 'QUOTE_EXPIRED', 'TENDER_SUBMITTED', 'DELIVERABLE_COMPLETED', 'DORMANT'}:
        action(kind, 'NO_ACTION', 'NO_ACTION', 'DOWNSTREAM_STATE' if kind in {'INVOICE_CREATED','INVOICED', 'PAID', 'WORK_COMPLETED'} else kind)
    elif kind in {'WORK_SCHEDULED', 'WORK_IN_PROGRESS'}:
        action(kind, 'NO_ACTION', 'WAITING', 'WAITING_SCHEDULED_WORK', 'WAITING_SCHEDULED_WORK')
    elif kind in {'WAITING_PROVIDER', 'WAITING_NATURAL_EVENT', 'OWNER_DEFERRED'}:
        action(kind, 'NO_ACTION', 'WAITING', kind, kind)
    elif kind == 'DELIVERABLE_PROMISED':
        due = stamp(data.get('due_at')); result['deadline'] = due.isoformat() if due else None
        result['deadline_precision']=data.get('due_precision','UNKNOWN')
        # The promise is real, its continued non-completion may be unknown.
        action(kind, 'VERIFY_DELIVERABLE_STATUS', 'VERIFY_FIRST', 'PROMISED_DELIVERABLE_OUTSTANDING')
        future_day = due and due.astimezone(ZoneInfo('America/Toronto')).date() > now.astimezone(ZoneInfo('America/Toronto')).date()
        if due and due > now and (data.get('due_precision') != 'DAY' or future_day):
            action(kind, 'NO_ACTION', 'WAITING', 'PROMISE_NOT_DUE', 'PROMISE_NOT_DUE')
        not_before=stamp(data.get('not_before'))
        if not_before and not_before>now:
            action(kind,'NO_ACTION','WAITING','COMMITMENT_NOT_YET_DUE','COMMITMENT_NOT_YET_DUE')
    elif kind == 'TENDER_OPEN':
        due = stamp(data.get('deadline')); result['deadline'] = due.isoformat() if due else None
        if due and due <= now:
            action('TENDER_CLOSED', 'NO_ACTION', 'NO_ACTION', 'DEADLINE_PASSED')
        elif due and due - now <= timedelta(days=2):
            action('TENDER_OPEN', 'VERIFY_ELIGIBILITY_AND_SUBMISSION', 'VERIFY_FIRST', 'TENDER_DEADLINE')
        else:
            action('TENDER_OPEN', 'REVIEW_TENDER_FIT', 'OPTIONAL', 'TENDER_RESEARCH')
    elif kind == 'ESTIMATE_EXISTS':
        action(kind, 'VERIFY_QUOTE_STATE', 'VERIFY_FIRST', 'VERIFY_QUOTE_STATE')
    if owner in {'APOLLO_CLAUDE', 'CLAUDE_APOLLO'} and result['next_action'] in {'FOLLOW_UP', 'PROCESS_REPLY', 'QUALIFY_INQUIRY'}:
        action(result['current_state'], 'REVIEW_WITH_CONVERSATION_OWNER', 'VERIFY_FIRST', 'APOLLO_OWNERSHIP_CHECK')
    return result


def eligible_today(row, now):
    gate = row.get('actionability', 'VERIFY_FIRST')
    if row.get('status') in {'SUPERSEDED', 'COMPLETED_BY_EVIDENCE', 'WAIT', 'NEVER', 'REJECTED'}:
        return False
    if row.get('readiness') != 'CURRENT' or row.get('dependency') or row.get('blocker'):
        return False
    if gate == 'ACTIONABLE_NOW':
        return True
    due = stamp(row.get('due_at') or row.get('deadline'))
    return gate == 'VERIFY_FIRST' and bool(due and due - now <= timedelta(days=2))


def reply_draft_obsolete(state):
    event=state.get('latest_authoritative_event') or {}
    return state.get('actionability') in {'WAITING','NO_ACTION'} or event.get('event_type') in {
        'RESPONSE_SENT','FOLLOWUP_SENT','QUOTE_SENT','DELIVERABLE_PROMISED','DELIVERABLE_COMPLETED',
        'QUOTE_ACCEPTED','QUOTE_DECLINED','WORK_SCHEDULED','WORK_IN_PROGRESS','WORK_COMPLETED','INVOICE_CREATED','INVOICED','PAID'}


def priority_order(row, now):
    """Actionability/deadline dominate importance; unknown value isn't money."""
    due = stamp(row.get('due_at') or row.get('deadline'))
    imminent = bool(due and due - now <= timedelta(days=2))
    confidence = {'HIGH': 0, 'MODERATE': 1, 'TENTATIVE': 2}.get(row.get('confidence'), 3)
    factors = row.get('factors') or {}
    value = factors.get('verified_business_value')
    value = value if type(value) in {int,float} and 0 <= value < 1e12 else 0
    risk = {'HIGH':0,'MEDIUM':1,'LOW':2}.get(factors.get('customer_risk'),3)
    recurring = factors.get('recurring_potential') == 'SUPPORTED'
    effort = factors.get('verified_effort_minutes')
    effort = effort if type(effort) in {int,float} and 0 <= effort < 1e6 else 1e6
    observed = stamp((row.get('lifecycle') or {}).get('evidence_observed_at'))
    freshness = -observed.timestamp() if observed and observed <= now else float('inf')
    return (not eligible_today(row, now), not imminent,
            not (imminent and row.get('reason_code')=='TENDER_DEADLINE'),
            due or datetime.max.replace(tzinfo=timezone.utc),
            {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2}.get(row.get('urgency'), 3), confidence,freshness,risk,-value,not recurring,effort,
            str(row.get('priority_id', '')))
