"""Source-aware optimization and reusable outcomes; no provider calls or policy edits."""
from copy import deepcopy
from datetime import timedelta
import json
from .acquisition_store import digest
from .action_evidence import redact, stamp

TRUTH_CLASSES = {'OBSERVED','TESTED','MEASURED_RESULT','INFERENCE','HYPOTHESIS','UNKNOWN'}
EVIDENCE_CLASSES = {'DIRECT','SUPPORTING','CONTEXT','COUNTEREVIDENCE','UNKNOWN'}
STRENGTHS = {'DETERMINISTIC','STRONGLY_SUPPORTED','WEAKLY_SUPPORTED','UNKNOWN'}
RESULTS = {'POSITIVE','NEGATIVE','MIXED','INCONCLUSIVE','NOT_MEASURABLE'}
SCOPES = {'SITE-SPECIFIC','SERVICE-SPECIFIC','AUDIENCE-SPECIFIC','CHANNEL-SPECIFIC','GENERALIZABLE'}
PROTECTED_LEARNING = {'authority_policies','financial_safeguards','destructive_action_policy',
    'approval_boundaries','security_controls','rollback_requirements'}
FUTURE_ACTIONS = {'email_classification','email_move','attachment_extraction','document_classification',
    'crm_association','project_association','file_move','financial_match','contract_classification','todo_creation','owner_correction','undo'}


def truth_class(value):
    return {'NATIVE_MEASURED':'OBSERVED','PROVIDER_FACT':'OBSERVED','OWNER_CONFIRMED':'OBSERVED',
        'OWNER_VERIFIED_FACT':'OBSERVED','USER_CONFIRMED':'OBSERVED','TESTED_FACT':'TESTED',
        'MEASURED_RESULT':'MEASURED_RESULT','INFERRED':'INFERENCE','MODEL_INFERENCE':'INFERENCE',
        'DERIVED_DETERMINISTIC':'INFERENCE','DERIVED_DETERMINISTICALLY':'INFERENCE',
        'ESTIMATED':'HYPOTHESIS','ESTIMATE':'HYPOTHESIS'}.get(value,value if value in TRUTH_CLASSES else 'UNKNOWN')


def evidence_item(original, now, *, relationship='Recorded proposal evidence', evidence_class=None):
    source=str(original.get('source') or original.get('provider') or 'UNKNOWN')
    reference=str(original.get('source_reference') or original.get('reference') or 'UNKNOWN')
    source_at=original.get('source_at') or original.get('effective_at') or original.get('observed_at')
    observed_at=original.get('observed_at')
    at=stamp(source_at);until=stamp(original.get('valid_until'))
    freshness='UNKNOWN' if not at or at>now else 'STALE' if until and until<now or (now-at)>timedelta(days=7) else original.get('freshness','CURRENT')
    classification=evidence_class or original.get('evidence_class') or ('CONTEXT' if 'competitor' in source.lower() else 'DIRECT')
    return {'evidence_id':digest([source,reference,source_at,original]),'source':source,'source_reference':reference,
        'source_at':source_at,'observed_at':observed_at,'freshness':freshness,
        'completeness':original.get('completeness','UNKNOWN'),'relationship':relationship,
        'evidence_class':classification,'truth_class':truth_class(original.get('truth_class')),
        'limitations':original.get('limitations',[]),'value':deepcopy(original.get('value')),
        'lineage':deepcopy(original.get('lineage',{}))}


def correlate(nodes, *, maximum=200):
    """Bounded adjacent joins using namespace-specific native IDs only.

    Aggregate query/page relationships cannot establish session or revenue causality.
    Same email, company, amount, or date alone never establishes acquisition lineage.
    """
    if len(nodes)>maximum:raise ValueError('Correlation node bound exceeded')
    order=['SEARCH_QUERY','LANDING_PAGE','CAMPAIGN','SESSION','FORM','LEAD','DEAL','ESTIMATE','INVOICE','REVENUE']
    joins={('SEARCH_QUERY','LANDING_PAGE'):'page_url',('LANDING_PAGE','CAMPAIGN'):'landing_page',
        ('CAMPAIGN','SESSION'):'click_id',('SESSION','FORM'):'session_id',('FORM','LEAD'):'submission_id',
        ('LEAD','DEAL'):'lead_id',('DEAL','ESTIMATE'):'deal_id',('ESTIMATE','INVOICE'):'estimate_id',
        ('INVOICE','REVENUE'):'invoice_id'}
    edges=[]
    for left_kind,right_kind in zip(order,order[1:]):
        field=joins[(left_kind,right_kind)]
        for left in [n for n in nodes if n.get('kind')==left_kind]:
            for right in [n for n in nodes if n.get('kind')==right_kind]:
                key=(left.get('keys') or {}).get(field)
                if key is None or key=='' or key!=(right.get('keys') or {}).get(field):continue
                exact=field not in {'page_url','landing_page'} and left.get('evidence_ref') and right.get('evidence_ref')
                if field=='click_id':exact=exact and left.get('click_id_type')=='gclid' and right.get('click_id_type')=='gclid'
                strength='DETERMINISTIC' if exact else 'WEAKLY_SUPPORTED'
                edges.append({'left':left['id'],'right':right['id'],'relationship_strength':strength,
                    'join_rule':field,'evidence_refs':[left.get('evidence_ref'),right.get('evidence_ref')],
                    'causal_claim_allowed':False})
                if len(edges)>500:raise ValueError('Correlation edge bound exceeded')
    # A connected path is required; counting unrelated deterministic edges is insufficient.
    adjacency={}
    for edge in edges:
        if edge['relationship_strength']=='DETERMINISTIC':adjacency.setdefault(edge['left'],[]).append(edge['right'])
    starts=[n['id'] for n in nodes if n.get('kind') in {'SEARCH_QUERY','CAMPAIGN'}]
    revenues={n['id'] for n in nodes if n.get('kind')=='REVENUE' and n.get('measured') is True}
    connected=set(starts);pending=list(starts)
    while pending:
        for child in adjacency.get(pending.pop(),[]):
            if child not in connected:connected.add(child);pending.append(child)
    attributed=bool(revenues & connected)
    return {'edges':edges,'attribution_confidence':'DETERMINISTIC' if attributed else 'UNKNOWN',
        'revenue_lineage_verified':attributed,'causal_claim_allowed':False,
        'limitations':['Native IDs support lineage; correlation alone cannot prove a change caused an outcome.',
            'Aggregate search/page data cannot identify an individual visitor.','Missing links remain UNKNOWN.']}


def evidence_bundle(record, detail, now, *, additional=(), coverage=None):
    originals=[*record.get('source_evidence',[]),*additional]
    if len(originals)>200:raise ValueError('Evidence bundle bound exceeded')
    items=[evidence_item(e,now,relationship=e.get('relationship') or 'Recorded evidence for '+str(record.get('proposal_id') or 'priority')) for e in originals]
    # Review counterevidence in the recorded source payload, keeping absent checks explicit.
    counters=[]
    for original,item in zip(originals,items):
        if original.get('evidence_class')=='COUNTEREVIDENCE' or original.get('counterevidence'):
            item['evidence_class']='COUNTEREVIDENCE';counters.append({'evidence_ref':item['evidence_id'],'finding':original.get('counterevidence') or original.get('relationship')})
        for limitation in original.get('limitations',[]):
            counters.append({'evidence_ref':item['evidence_id'],'finding':limitation,'classification':'MEASUREMENT_LIMITATION'})
    coverage=coverage or {e['source']:{'state':'REVIEWED','reference':e['source_reference']} for e in items}
    checks=['Existing target performance','Qualified inquiry quality and customer conversations','Seasonality and traffic mix',
        'Concurrent campaigns/changes','Tracking completeness and small samples','Relevant previous outcomes']
    searched=[{'check':check,'state':'SEARCHED_RECORDED_EVIDENCE','sources':sorted(coverage),
        'finding':'See sourced counterevidence; absent source facts remain UNKNOWN'} for check in checks]
    bundle={'schema':1,'proposal_id':record.get('proposal_id'),'revision':record.get('revision',1),
        'items':items,'source_coverage':coverage,'counterevidence':counters,'counterevidence_search':searched,
        'correlation':correlate(detail.get('correlation_nodes',[])),
        'unknowns':['No causal revenue attribution without a connected source-to-business lineage.',
            'Competitor behavior supplies context and does not prove effectiveness.'],
        'counterevidence_state':'FOUND' if counters else 'NONE_FOUND_IN_REVIEWED_EVIDENCE'}
    return validate_bundle(redact(bundle))


def validate_bundle(bundle, *, material=False):
    if not isinstance(bundle,dict) or not {'items','source_coverage','counterevidence','counterevidence_search','correlation','unknowns'}<=set(bundle):
        raise ValueError('Canonical evidence bundle required')
    if not bundle['counterevidence_search']:raise ValueError('Active counterevidence search required')
    if material and not any(e.get('evidence_class') in {'DIRECT','SUPPORTING'} and stamp(e.get('source_at')) for e in bundle['items']):
        raise ValueError('Material optimization requires dated relevant evidence')
    for item in bundle['items']:
        if not {'source','source_at','observed_at','freshness','completeness','relationship','evidence_class','truth_class','evidence_id'}<=set(item) or item['evidence_class'] not in EVIDENCE_CLASSES or item['truth_class'] not in TRUTH_CLASSES:
            raise ValueError('Source provenance and evidence classification required')
    for edge in bundle['correlation']['edges']:
        if edge['relationship_strength'] not in STRENGTHS:raise ValueError('Explicit correlation strength required')
        if edge['relationship_strength']=='DETERMINISTIC' and not all(edge.get('evidence_refs',[])):raise ValueError('Deterministic relationship requires provider evidence')
    for source,review in bundle['source_coverage'].items():
        if review.get('available_relevant') and review.get('state')!='REVIEWED':raise ValueError('Relevant available source must be reviewed: '+source)
    return bundle


def validate_measurement_plan(plan):
    required={'primary_metric','secondary_metrics','guardrails','window','minimum_evidence','attribution_limits'}
    if not isinstance(plan,dict) or not required<=set(plan) or not all(plan.get(k) for k in ('primary_metric','guardrails','window','minimum_evidence','attribution_limits')):
        raise ValueError('Primary/secondary metrics, guardrails, window, minimum evidence and attribution limits required')
    return plan


def validate_baseline(baseline, now):
    fields={'proposal_id','production_version','entity','captured_at','items','traffic_mix','business_outcomes','tracking_completeness'}
    if not isinstance(baseline,dict) or not fields<=set(baseline) or not baseline['production_version'] or not baseline['entity'] or not baseline['items']:
        raise ValueError('Pre-execution baseline and exact production version required')
    at=stamp(baseline['captured_at'])
    if not at or at>now:raise ValueError('Baseline must precede execution')
    for item in baseline['items']:
        if not {'source','source_at','observed_at','metric','value','evidence_ref'}<=set(item) or not item['evidence_ref'] or not stamp(item['source_at']) or stamp(item['source_at'])>now:
            raise ValueError('Dated inspectable baseline evidence required')
    return baseline


def classify_result(before, after, *, sufficient, complete, guardrail_breach=False, higher_is_better=True, measurable=True):
    if not measurable:return 'NOT_MEASURABLE'
    if not sufficient or not complete or before is None or after is None:return 'INCONCLUSIVE'
    if guardrail_breach:return 'MIXED' if (after>before)==higher_is_better and after!=before else 'NEGATIVE'
    if after==before:return 'INCONCLUSIVE'
    return 'POSITIVE' if (after>before)==higher_is_better else 'NEGATIVE'


def learning_confidence(factors):
    required={'sample_size','duration','data_completeness','tracking_coverage','seasonality',
              'traffic_source_changes','simultaneous_changes','repeatability','business_relevance'}
    if not required<=set(factors):raise ValueError('Learning confidence factors required')
    if any(factors[k] in (None,'UNKNOWN','INSUFFICIENT') for k in required):return {'value':'LOW','reason':'Unknown or insufficient confidence factors','factors':factors}
    return {'value':'HIGH' if all(factors[k]=='ADEQUATE' for k in required) else 'MEDIUM',
            'reason':'Recorded sample, coverage, confounding and repeatability assessment','factors':factors}


def validate_learning(value, action):
    required={'proposal_id','execution_action_id','site','service','language','audience','channel','change_class','baseline',
        'after_evidence','result','confidence','confounders','limitations','lesson','reuse_eligible','scope'}
    if not isinstance(value,dict) or not required<=set(value) or value['result'] not in RESULTS or value['scope'] not in SCOPES:
        raise ValueError('Canonical Learning Record required')
    if not action or action['status']!='SUCCEEDED' or action['readback']['state']!='VERIFIED' or value['execution_action_id']!=action['action_id'] or value['proposal_id']!=action['proposal_id']:
        raise ValueError('Verified executed action required; previews and approvals are not outcomes')
    if action['exact_versions'].get('environment')!='production':raise ValueError('Production execution evidence required')
    if value['baseline']!=action['baseline']:raise ValueError('Learning baseline must be the frozen execution baseline')
    if not value['after_evidence'] or not value['limitations'] or not value['lesson']:raise ValueError('After evidence, limitations and reproducible lesson required')
    for item in value['after_evidence']:
        if not item.get('evidence_ref') or not stamp(item.get('source_at')) or stamp(item['source_at'])<stamp(action['completed_at']):raise ValueError('Dated post-execution outcome evidence required')
    for field in ('site','service','language','audience','channel','change_class'):
        if not isinstance(value[field],str) or not value[field]:raise ValueError('Explicit learning context required')
    if type(value['reuse_eligible']) is not bool:raise ValueError('Explicit reuse eligibility required')
    confidence=value['confidence'];assessed=learning_confidence(confidence.get('factors',{}))
    if confidence.get('value')!=assessed['value']:raise ValueError('Learning confidence must agree with recorded factors')
    if value['result'] not in {'INCONCLUSIVE','NOT_MEASURABLE'}:
        comparison=value.get('comparison',{})
        if not {'before','after','sufficient','complete','guardrail_breach','higher_is_better'}<=set(comparison):
            raise ValueError('Measured result requires explicit comparison and evidence sufficiency')
        if classify_result(**comparison)!=value['result']:raise ValueError('Result must match observed comparison and limitations')
        metric=value.get('measurement_metric')
        if not metric or not any(i.get('metric')==metric and i.get('value')==comparison['before'] for i in value['baseline']['items']):
            raise ValueError('Comparison before value must match dated frozen baseline evidence')
        if not any(i.get('metric')==metric and i.get('value')==comparison['after'] for i in value['after_evidence']):
            raise ValueError('Comparison after value must match dated outcome evidence')
    if confidence.get('value') not in {'HIGH','MEDIUM','LOW'} or not confidence.get('reason'):raise ValueError('Learning confidence and rationale required')
    if value['result'] in {'INCONCLUSIVE','NOT_MEASURABLE'} and value['reuse_eligible']:raise ValueError('Unmeasured outcomes cannot support expected benefit')
    if value['scope']=='GENERALIZABLE' and not value.get('transfer_evidence'):raise ValueError('Cross-context transfer requires supporting evidence')
    if any(k in PROTECTED_LEARNING for k in value.get('recommended_policy_changes',{})):raise ValueError('Learning cannot alter protected safety policies')
    return redact(value)


def relevant_learning(records, context, *, limit=10):
    matches=[]
    for row in records:
        value=row['value']
        if not value.get('execution_action_id'):continue  # Legacy text is not invented outcome evidence.
        if any(value.get(k)!=context.get(k) for k in ('site','service','language','audience','channel','change_class')):continue
        matches.append({**row,'evidence_class':'COUNTEREVIDENCE' if value['result'] in {'NEGATIVE','MIXED'} else
            'SUPPORTING' if value.get('reuse_eligible') else 'CONTEXT'})
    return matches[:limit]


def future_intelligence_contract(kind, value):
    """Validate future evidence payloads without implementing intake, moves or Books writes."""
    if kind not in FUTURE_ACTIONS:raise ValueError('Unsupported future intelligence action')
    required={'reason','confidence','evidence_refs','owner_correction','undo_state'}
    if kind in {'email_classification','email_move','attachment_extraction'}:
        required|={'message_id','thread_id','sender','classification','original_labels','new_labels','attachments','attachment_hashes','destination','business_entities'}
    if kind in {'file_move','undo'}:
        required|={'original_location','destination','before_hash','after_hash','document_type','business_entities','rollback_procedure'}
    if kind=='financial_match':
        required|={'document_observed','books_candidate','bank_candidate','amount_date_reference','client_vendor','project','match_class'}
        if value.get('match_class') not in {'DETERMINISTIC','HIGH_CONFIDENCE','POSSIBLE','UNKNOWN'} or value.get('books_mutation') is not False:raise ValueError('Read-only classified financial evidence required')
    if not required<=set(value):raise ValueError('Future module evidence contract incomplete')
    if kind in {'file_move','undo'} and (not value['before_hash'] or value['before_hash']!=value['after_hash']):raise ValueError('Move must preserve verified content hash')
    return redact(value)
