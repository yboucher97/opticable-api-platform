"""Universal owner explanations derived from the canonical proposal/priority.

Unknowns remain explicit. This projection is not a proposal store, approval or
evidence of execution. Legacy immutable revisions keep their original hashes.
"""
import ast
from copy import deepcopy
from html import escape
import json
from .acquisition_store import safe,digest
from .website_registry import site_for

OPTIONS = ['APPROVE', 'REQUEST REVISION', 'REJECT', 'DEFER']
FIELDS = {'summary','current_state','proposed_change','why_change','evidence','pros','cons','risks',
          'expected_benefit','proven_vs_assumed','confidence','do_nothing','rollback',
          'recommended_decision','owner_options','dependencies','before_after','measurement_plan',
          'measured_result','learning','technical','site','production_page','preview_page'}
TECHNICAL = {'repository','base_sha','proposal_sha','files_changed','test_results','preview_url',
             'production_impact','rollback_reference','stale_state','provider_configuration_affected','indirect_changes'}
UNKNOWN = 'UNKNOWN — evidence has not been collected.'


def validate_card(card):
    if not isinstance(card, dict) or not FIELDS <= set(card): raise ValueError('Decision Card required fields missing')
    for name in ('current_state','proposed_change','why_change','expected_benefit','do_nothing','rollback'):
        if not isinstance(card[name], str) or not card[name].strip(): raise ValueError('Decision Card explanation required: '+name)
    for name in ('evidence','pros','cons','risks','dependencies'):
        if not isinstance(card[name], list) or not card[name]: raise ValueError('Decision Card list required: '+name)
    truth = card['proven_vs_assumed']
    if not isinstance(truth, dict) or set(truth) != {'observed_fact','tested_fact','hypothesis','inference','unknown'}:
        raise ValueError('Separate observed/tested/hypothesis/inference/unknown required')
    if any(not isinstance(v,list) for v in truth.values()): raise ValueError('Truth lists required')
    if card['owner_options'] != OPTIONS: raise ValueError('All four owner options required')
    for field, values in [('confidence', {'HIGH','MEDIUM','LOW'}), ('recommended_decision', {'APPROVE','REVISE','REJECT','DEFER'})]:
        v=card[field]
        if not isinstance(v,dict) or v.get('value') not in values or not isinstance(v.get('reason'),str) or not v['reason'].strip():
            raise ValueError('Decision Card '+field+' and reason required')
    if not isinstance(card['summary'],dict) or set(card['summary']) != {'what_changed','why','main_benefit','main_downside','recommendation'}:
        raise ValueError('Short owner summary required')
    if any(not isinstance(v,str) or not v.strip() for v in card['summary'].values()):raise ValueError('Summary explanation required')
    if not isinstance(card['before_after'],list):raise ValueError('Before/after required')
    for change in card['before_after']:
        if not isinstance(change,dict) or not {'field','before','after','state'} <= set(change) or change['state'] not in {'EXACT','UNKNOWN','NO_CHANGE'}:
            raise ValueError('Exact or explicitly unknown before/after required')
        if any(not isinstance(change[k],str) or not change[k] for k in ('field','before','after')):raise ValueError('Before/after text required')
    if card['technical'] is not None and (not isinstance(card['technical'],dict) or not TECHNICAL <= set(card['technical'])):
        raise ValueError('Technical decision metadata required')
    if not isinstance(card['measurement_plan'],dict) or not {'baseline','metric','window','success_condition','guardrail','result_state'} <= set(card['measurement_plan']):
        raise ValueError('Measurement contract required, including unknown baselines')
    safe(card)
    if len(json.dumps(card,ensure_ascii=False,allow_nan=False).encode()) > 196608:raise ValueError('Decision Card bound exceeded')
    return card


def _copy_fields(source):
    """Parse literal source text without importing or executing website code."""
    try: tree=ast.parse(source)
    except (SyntaxError,TypeError): return {}
    values={}
    for node in ast.walk(tree):
        if isinstance(node,ast.If) and any(isinstance(n,ast.Constant) and n.value=='fr' for n in ast.walk(node.test)):
            for stmt in node.body:
                if isinstance(stmt,ast.Assign) and len(stmt.targets)==1 and isinstance(stmt.targets[0],ast.Name):
                    try: values.setdefault(stmt.targets[0].id,ast.literal_eval(stmt.value))
                    except (ValueError,TypeError): pass
    return values


def comparison(detail, preview):
    changes=(preview or {}).get('package',{}).get('changes') or detail.get('changes') or detail.get('before_after')
    if changes:
        result=[]
        for change in changes:
            old,new=_copy_fields(change.get('before')),_copy_fields(change.get('after'))
            if old and new:
                for field in dict.fromkeys([*old,*new]):
                    if old.get(field)!=new.get(field):
                        def text(v): return v if isinstance(v,str) else json.dumps(v,ensure_ascii=False) if v is not None else '(absent)'
                        result.append({'field':change.get('path','content')+' · '+field,'before':text(old.get(field)),
                            'after':text(new.get(field)),'state':'EXACT'})
            else: result.append({'field':change.get('path') or change.get('field','content'),
                'before':change['before'],'after':change['after'],'state':'EXACT'})
        return result
    if detail.get('no_op'):
        return [{'field':'Website source','before':'Exact base source SHA '+detail['base_sha'],
                 'after':'Same exact source SHA '+detail['base_sha']+'; preview-only containment added to generated artifact','state':'NO_CHANGE'}]
    draft=detail.get('draft')
    return [{'field':'Content / configuration','before':detail.get('current_text') or UNKNOWN,
             'after':detail.get('proposed_text') or (draft if isinstance(draft,str) else json.dumps(draft,ensure_ascii=False) if draft else UNKNOWN),
             'state':'EXACT' if detail.get('current_text') and detail.get('proposed_text') else 'UNKNOWN'}]


def decision_card(item, preview=None, *, evidence=None, measured=None):
    r=item['record'];d=item['detail'];priority=r['type']=='optibrain.business_priority'
    supplied=r.get('decision_card') or d.get('decision_card')
    if supplied: card=deepcopy(validate_card(supplied))
    else:
        plan=r.get('measurement_plan') or {};metrics=plan.get('metrics',[])
        source=evidence if evidence is not None else r.get('source_evidence',[])
        observed=[e for e in source if isinstance(e,dict) and e.get('truth_class') in {'NATIVE_MEASURED','OWNER_CONFIRMED','PROVIDER_FACT','OWNER_VERIFIED_FACT'}]
        inferred=[e for e in source if isinstance(e,dict) and e.get('truth_class') in {'INFERRED','ESTIMATED','MODEL_INFERENCE'}]
        stale=any(e.get('freshness') in {'STALE','UNKNOWN'} for e in source if isinstance(e,dict))
        confidence='LOW' if stale else {'STRONG':'HIGH','MODERATE':'MEDIUM'}.get(r.get('confidence'),'LOW')
        change=r.get('recommended_change') or r.get('what') or UNKNOWN
        why=r.get('business_problem') or r.get('why') or UNKNOWN
        benefit=r.get('expected_benefit') or r.get('business_impact') or UNKNOWN
        downside=d.get('cons') or ['Implementation/review effort and opportunity cost are not quantified.']
        decision={'value':'REVISE' if r.get('target_system')=='WEBSITE' and not d.get('no_op') else 'DEFER',
                  'reason':'Review exact copy and preserve useful technical detail; conversion lift is unmeasured.' if r.get('target_system')=='WEBSITE' and not d.get('no_op') else 'Owner must review the evidence and unresolved assumptions before execution.'}
        card={'current_state':d.get('current_state') or r.get('current_state') or ('Observed target: '+str(r.get('target_url_or_record') or r.get('target_object') or r.get('targets'))),
            'proposed_change':change,'why_change':why,'evidence':source or [UNKNOWN],
            'pros':d.get('pros') or ['Expected: '+benefit], 'cons':downside,
            'risks':[r.get('risk') or 'Execution impact and provider dependencies need verification.'],
            'expected_benefit':'EXPECTED / HYPOTHESIS — '+benefit,
            'proven_vs_assumed':{'observed_fact':observed,'tested_fact':[],'hypothesis':[benefit],
                                'inference':inferred,'unknown':[r.get('data_quality') or UNKNOWN,'Causal business improvement has not been established.']},
            'confidence':{'value':confidence,'reason':'Based on recorded evidence confidence '+r.get('confidence','UNKNOWN')+'; '+('stale/unknown source freshness limits conclusions.' if stale else 'business impact remains unmeasured.')},
            'do_nothing':'Retain the current target state. '+why+' remains unaddressed; the size of any missed benefit is unknown.',
            'rollback':r.get('rollback_reference') or 'UNKNOWN — no rollback reference has been verified; execution must wait.',
            'recommended_decision':decision,'owner_options':list(OPTIONS),
            'dependencies':[r.get('dependency') or r.get('owner_action_required') or 'Owner review of current evidence; separate execution authority.'],
            'before_after':comparison(d,preview),
            'measurement_plan':{'baseline':metrics or UNKNOWN,'metric':[m['metric'] for m in metrics] or UNKNOWN,
                'window':plan.get('window') or UNKNOWN,'success_condition':plan.get('success') or UNKNOWN,
                'guardrail':plan.get('guardrails') or [UNKNOWN], 'result_state':'MEASURED' if r.get('result') else 'NOT_EXECUTED'},
            'measured_result':r.get('result'),'learning':r.get('learning'), 'technical':None,
            'site':None,'production_page':r.get('target_url_or_record'),'preview_page':r.get('preview_location')}
    repository=(preview or {}).get('repository') or d.get('repository')
    site=site_for(repository=repository,page=card['production_page'],site_id=d.get('site_id'))
    if site: card['site']=site['site_id']
    technical=bool(repository or r.get('target_system') in {'WEBSITE','ZOHO_FORM','CRM_CONFIGURATION'} or d.get('technical_change'))
    if technical:
        p=preview or {};checks=p.get('tests',{})
        # Enum test labels are data, never credential-shaped dictionary keys.
        tests=[{'test_class':k,**deepcopy(v)} for k,v in checks.items()]
        card['technical']={'repository':repository,'base_sha':p.get('base_sha') or d.get('base_sha'),
            'proposal_sha':p.get('head_sha') or d.get('proposal_sha'), 'files_changed':p.get('package',{}).get('allowed_files') or r.get('affected_files_or_records',[]),
            'test_results':tests or 'NOT_RUN', 'preview_url':p.get('preview_url'),
            'production_impact':p.get('production_impact') or 'NOT_EXECUTED — impact must be assessed before execution',
            'rollback_reference':p.get('rollback_base') or r.get('rollback_reference'), 'stale_state':p.get('stale_state','UNKNOWN'),
            'provider_configuration_affected':d.get('provider_configuration_affected') or UNKNOWN,
            'indirect_changes':d.get('indirect_changes') or UNKNOWN}
        card['preview_page']=p.get('preview_url') or r.get('preview_location')
        if tests:
            head=p.get('head_sha')
            card['proven_vs_assumed']['tested_fact']=[t for t in tests if t.get('state')=='PASS' and head and t.get('head_sha')==head]
        if p and (p.get('proposal_revision')!=r.get('revision') or p.get('proposal_hash')!=item.get('payload_hash')):
            card['technical']['preview_revision']=p.get('proposal_revision')
            card['technical']['current_revision']=r.get('revision')
            card['proven_vs_assumed']['tested_fact']=[]
            card['proven_vs_assumed']['unknown'].append('Tests belong to a superseded preview revision; the current proposal is not verified by that binding.')
            card['confidence']={'value':'LOW','reason':'The canonical proposal and historical tested preview differ; refresh exact revision evidence before approval.'}
        if p.get('package'):
            card['technical']['provider_configuration_affected']=d.get('provider_configuration_affected') or 'No production provider configuration file is in the scoped preparation package. Preview target: '+str(p.get('preview_project'))
    if preview: card['before_after']=comparison(d,preview)
    camera=card['production_page'] and '/systemes-cameras-securite' in card['production_page']
    if camera:
        card.update(current_state='Technical scene-design wording on the French commercial camera page.',
            proposed_change='Explicit commercial camera intent, Montréal/Laval/Rive-Nord relevance, stronger quote CTA and FAQ coverage.',
            pros=['Explicit commercial intent','Clearer quote CTA','Named local service area','FAQ coverage'],
            cons=['Some technical specificity is lost','The visible copy change is subtle','Conversion improvement is not proven'],
            do_nothing='Retain the existing technical scene-design copy and CTA; no measured conversion loss from doing so is known.',
            rollback='No production change occurred. A future deployed copy change requires a guarded forward revert to the recorded base '+str((preview or {}).get('base_sha') or d.get('production_rollback_sha') or UNKNOWN)+'. Preserve measurement history.',
            measurement_plan={'baseline':'UNKNOWN — collect 28 days of consented camera-page sessions, quote starts and genuine qualified inquiries before execution.',
                'metric':['Camera-page quote-start rate','Genuine qualified commercial inquiries'],
                'window':'28 days before and 28 days after a separately approved production execution; sparse samples remain INSUFFICIENT_DATA.',
                'success_condition':'Quote-start rate improves against the observed baseline with sufficient usable samples and no lower inquiry quality; the numerical target needs owner review.',
                'guardrail':['Forms remain usable','Consent and attribution remain correct','Exclude TEST/operator events','No degradation in qualified inquiry quality'],
                'result_state':'NOT_EXECUTED'},
            recommended_decision={'value':'REVISE','reason':'Retain technical scene-design detail and sharpen the change before any production proposal.'})
    from .optimization_learning import evidence_bundle,truth_class
    from datetime import datetime,timezone
    bundle=item.get('evidence_bundle') or evidence_bundle(r,d,datetime.now(timezone.utc))
    card.update(why_optibrain_thinks_this=card['why_change'],sources_used=bundle['items'],
        counterevidence={'findings':bundle['counterevidence'],'search':[{'check':c['check'],'state':c['state']} for c in bundle['counterevidence_search']],
            'searched_sources':sorted(bundle['source_coverage']),'state':bundle['counterevidence_state']},
        evidence_bundle={'fingerprint':digest(bundle),
            'audit_record_id':item.get('audit_action_id'),'correlation':bundle['correlation'],
            'unknowns':bundle['unknowns']},previous_relevant_learning=item.get('previous_learning',[]),
        audit_record_id=item.get('audit_action_id'),
        audit_state='DURABLE' if item.get('audit_action_id') else 'LEGACY — awaiting canonical observer evidence',
        expected_result=card['expected_benefit'],result_measurement='See the frozen measurement plan and execution baseline.',
        rollback_class=d.get('rollback_capability','UNKNOWN'),
        canonical_truth=[{'evidence_id':e['evidence_id'],'classification':e['truth_class']} for e in bundle['items']])
    if measured:
        card['measured_result']=deepcopy(measured);card['learning']=measured.get('learning') or measured.get('interpretation')
        card['measurement_plan']['result_state']=measured.get('result') or measured.get('outcome','UNKNOWN')
    card['summary']={'what_changed':card['proposed_change'],'why':card['why_change'],
        'main_benefit':card['expected_benefit'],'main_downside':card['cons'][0],
        'recommendation':card['recommended_decision']['value']+' — '+card['recommended_decision']['reason']}
    return validate_card(card)


def todo_explanation(priority, card):
    event=priority.get('lifecycle',{}).get('latest_authoritative_event')
    return {'why_this_exists':priority['why'],'latest_event':event or {'state':priority['status'],'evidence':priority.get('evidence',[])},
        'action_required':priority['next_action'],'deadline':priority.get('due_at') or priority.get('deadline'),
        'if_ignored':card['do_nothing'],'confidence':card['confidence'],
        'proposal_ids':priority.get('proposal_ids',[]),'priority_id':priority['priority_id'],
        'evidence':priority.get('evidence',[]),'actionability':priority.get('actionability','UNKNOWN'),
        'decision_card_id':card.get('audit_record_id'),'audit_record_id':card.get('audit_record_id')}


def render_card(card):
    validate_card(card);h=lambda v:escape(str(v),quote=True)
    def show(v):
        if isinstance(v,dict):return '<dl>'+''.join('<dt>'+h(k.replace('_',' ').upper())+'</dt><dd>'+show(n)+'</dd>' for k,n in v.items())+'</dl>'
        if isinstance(v,list):return '<ul>'+''.join('<li>'+show(n)+'</li>' for n in v)+'</ul>' if v else '<p>None recorded.</p>'
        return '<pre style="white-space:pre-wrap">'+h('UNKNOWN' if v is None else v)+'</pre>'
    out='<section class="decision-card"><h2>Decision Card</h2>'
    for k,v in card['summary'].items():out+='<p><strong>'+h(k.replace('_',' ').upper())+':</strong> '+h(v)+'</p>'
    if card['site']:out+='<p>Site: '+h(card['site'])+' · Repository: '+h(card['technical']['repository'])+'</p>'
    out+='<p><strong>PROS</strong></p>'+show(card['pros'])+'<p><strong>CONS</strong></p>'+show(card['cons'])
    out+='<p><strong>UNCERTAINTY / CONFIDENCE</strong></p>'+show(card['confidence'])
    out+='<details><summary>Decision evidence and exact before / after</summary>'
    for k,v in card.items():
        if k not in {'summary','pros','cons','confidence'}:
            out+='<h3>'+h(k.replace('_',' ').upper())+'</h3>'
            out+=('<a href="/v1/operator/manager/audit/'+h(v)+'">'+h(v)+'</a>') if k=='audit_record_id' and v else show(v)
    return out+'</details></section>'


def concise_card(card):
    validate_card(card)
    return {k:deepcopy(card[k]) for k in ('summary','pros','cons','confidence')}


def render_concise(card):
    if not card:return '<p>Decision explanation awaits the next observer refresh; open the canonical proposal for current evidence.</p>'
    h=lambda v:escape(str(v),quote=True)
    out=''.join('<p><strong>'+h(k.replace('_',' ').upper())+':</strong> '+h(v)+'</p>' for k,v in card['summary'].items())
    for name in ('pros','cons'):out+='<p><strong>'+name.upper()+':</strong> '+h('; '.join(card[name]))+'</p>'
    return out+'<p><strong>CONFIDENCE / UNCERTAINTY:</strong> '+h(card['confidence']['value']+' — '+card['confidence']['reason'])+'</p>'
