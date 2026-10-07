"""Bounded owner projections of shared stores. No provider or model calls."""
from collections import Counter
from datetime import datetime,timedelta,timezone
from html import escape
from zoneinfo import ZoneInfo
from .acquisition_store import digest
from .manager_sources import registry,evidence_health,stamp,health_state
from .lifecycle_projection import collect_states,reconcile_priority
from .lifecycle_truth import eligible_today,priority_order,context_key,reply_draft_obsolete
from .decision_card import decision_card,render_card,todo_explanation

TZ=ZoneInfo('America/Toronto')
DOMAIN={'GOOGLE_ADS':'ads','WEBSITE':'website','SEO':'seo','ZOHO_FORM':'form','CONTENT':'content',
        'IMAGE_CREATIVE':'content','OUTREACH':'outreach','SALES_PROCESS':'sales','GBP':'marketing'}
CLOSED={'REJECTED','NEVER','NOT_RELEVANT','WAIT','SUCCESS','NEUTRAL','REGRESSION'}


def semantic_evidence(record,detail):
    def stable(v):
        if isinstance(v,dict):return {k:stable(n) for k,n in v.items() if k not in {'at','observed_at','valid_until','created_at','updated_at','revision','prepared_at','last_verified_at'}}
        if isinstance(v,list):return [stable(n) for n in v]
        return v
    return digest(stable([record.get('source_evidence'),record.get('recommended_change'),detail]))


def proposals(store,sources,now):
    feedback=store.feedback_latest();output=[]
    for item in store.rows():
        r=item['record'];status=item['effective_status'];f=feedback.get(('PROPOSAL',r['proposal_id']))
        website=None
        if r['target_system']=='WEBSITE':
            from .website_preview_runtime import manager_projection
            website=manager_projection(item,store.preview(r['proposal_id'],now),now)
        evidence=evidence_health(r['source_evidence'],sources,now)
        signature=semantic_evidence(r,item['detail'])
        if f and (f['version']==item['payload_hash'] or f['choice']=='NEVER' or
                  f['choice'] in {'REJECT','NOT_RELEVANT','WAIT'} and f['value'].get('semantic_evidence')==signature):
            status={'APPROVE':'APPROVED','REJECT':'REJECTED','REQUEST_REVISION':'RESEARCHING'}.get(f['choice'],f['choice'])
        stale=any(e['freshness'] in {'STALE','UNKNOWN'} for e in evidence)
        confidence='INSUFFICIENT' if stale else r['confidence']
        output.append({'proposal_id':r['proposal_id'],'revision':r['revision'],'payload_hash':item['payload_hash'],
            'domain':'customer' if r['proposal_type']=='CUSTOMER_EXPANSION' else DOMAIN.get(r['target_system'],'operations'),
            'type':r['proposal_type'],'target_object':r['target_object'],'title':r['recommended_change'],'why':r['business_problem'],'why_now':r['why_now'],
            'expected_benefit':r['expected_benefit'],'risk':r['risk'],'confidence':confidence,'original_confidence':r['confidence'],
            'status':status,'readiness':'NEEDS_REFRESH' if stale else status,'evidence':evidence,
            'preview':r.get('preview_location'),'owner_action':r['owner_action_required'],
            'measurement_plan':{'metrics':[m['metric'] for m in (r.get('measurement_plan') or {}).get('metrics',[])],
                'window':(r.get('measurement_plan') or {}).get('window'),'detail':'/v1/operator/acquisition?proposal_id='+r['proposal_id']},'cost':item['detail'].get('budget') or {'value':None,'basis':'UNKNOWN'},
            'authority_class':r['authority_class'],'execution_authorized':False,
            'execution_reference':r.get('execution_reference'),'result':r.get('result'),'learning':r.get('learning'),
            'feedback':{'choice':f['choice'],'at':f['at'],'reason':f['value'].get('reason'),'category':f['value'].get('category'),
                        'conditions':f['value'].get('reconsideration_conditions')} if f else None,
            'approval':'OWNER_INTENT_ONLY' if status=='APPROVED' else None})
        if website:
            output[-1]['website_preview']=website
            if website.get('repository'):
                output[-1].update(status=website['state'],readiness=website['state'],
                    preview=website['verified_url'] or r.get('preview_location'),
                    approval='EXACT_PREVIEW_OWNER_INTENT' if website['approval_bound'] else None)
        from .learning_runtime import context
        item={**item,'evidence_bundle':store.evidence_bundle(r['proposal_id'],r['revision']),
              'previous_learning':store.relevant_learning(context(item))}
        output[-1]['decision_card']=decision_card(item,store.preview(r['proposal_id'],now) if r['target_system']=='WEBSITE' else None,
            evidence=evidence,measured=store.latest_learning(r['proposal_id'],r['revision']))
    return output


def authority_health(inputs,now):
    signals={s['name']:s for s in inputs.get('status',{}).get('signals',[])};output=[]
    for key,name in [('internal','Internal automation'),('customer_communication','Customer communication')]:
        s=signals.get(name,{});expires=stamp(s.get('expires_at'))
        state='EXPIRED' if expires and expires<=now else 'ACTIVE' if s.get('enabled') is True else 'DISABLED' if s else 'UNKNOWN'
        output.append({'authority':key,'state':state,'scopes':s.get('configured'),'expires_at':s.get('expires_at'),
            'review_by':'2026-10-25','automatic_renewal':False,'truth_class':'DERIVED_DETERMINISTICALLY'})
    for key in ('ads','outreach','financial_write','publication'):
        output.append({'authority':key,'state':'ABSENT','scopes':0,'expires_at':None,'automatic_renewal':False,'truth_class':'USER_CONFIRMED'})
    output.extend([{'authority':'conversion_export','state':'DISABLED','scopes':0,'automatic_renewal':False},
                   {'authority':'english_automation','state':'DISABLED','scopes':0,'automatic_renewal':False},
                   {'authority':'persistent_development_worker','state':'DISABLED','scopes':0,'automatic_renewal':False}])
    return output


def priorities(store,proposal_rows,sources,now,*,active_ids=None,crosswalk=None,lifecycle_states=None):
    by={p['proposal_id']:p for p in proposal_rows};feedback=store.feedback_latest();groups={};crosswalk=crosswalk or {}
    for item in store.rows('optibrain.business_priority'):
        r=item['record'];pid=r['priority_id'];p=by.get(r.get('proposal_id'));status=p['status'] if p else r['status']
        website_action=None
        if p and p.get('website_preview',{}).get('repository'):
            from .website_preview_runtime import priority_action
            website_action=priority_action(p['website_preview'])
            if item['detail'].get('website_preview_priority') and not website_action:continue
        if r['domain']=='MANAGER' and active_ids is not None and pid not in active_ids:continue
        f=feedback.get(('PRIORITY',pid))
        if f and (f['version']==item['payload_hash'] or f['choice']=='NEVER'):
            if f['choice'] not in {'HIGHER','LOWER'}:status=f['choice']
        if status in CLOSED:continue
        evidence=p['evidence'] if p else evidence_health(r['source_evidence'],sources,now)
        fresh=bool(evidence) and all(e['freshness']=='CURRENT' for e in evidence)
        target=r['targets'][0]
        target_key=':'.join(str(target[k]) for k in ('system','entity_type','entity_id'))
        canonical=crosswalk.get(target_key,target_key)
        # Only unify exact resolved identity for business attention. Campaign,
        # website and system decisions retain their independent action identity.
        family='BUSINESS_ATTENTION' if target['entity_type'] in {'CONVERSATION','SALES_REPLY','LEAD','PROSPECT','TRIGGER','CUSTOMER_EXPANSION','OUTREACH_PROPOSAL'} else r['domain']
        key=digest([canonical,family]);urgency=r['urgency']
        if f and f['version']==item['payload_hash']:
            if f['choice']=='HIGHER':urgency='HIGH'
            if f['choice']=='LOWER':urgency='LOW'
        v={**{k:v for k,v in r.items() if k not in {'source_evidence','data_quality','created_at','updated_at','priority_reasons','type','schema'}},'status':status,'priority_id':pid,'payload_hash':item['payload_hash'],
            'evidence':evidence,'confidence':r['confidence'] if fresh else 'INSUFFICIENT',
            'readiness':'CURRENT' if fresh else 'NEEDS_REFRESH','urgency':urgency,'canonical_target':canonical,
            'priority_ids':[pid],'proposal_ids':[r['proposal_id']] if r.get('proposal_id') else [],
            'factors':{'business_impact':r['business_impact'],'deadline':r.get('due_at'),'urgency':urgency,
                'confidence':r['confidence'] if fresh else 'INSUFFICIENT','risk':p['risk'] if p else 'UNKNOWN',
                'revenue_potential':'UNKNOWN','recurring_potential':'UNKNOWN','cost':p['cost'] if p else 'UNKNOWN',
                'effort':'UNKNOWN','service_fit':'Evidence-dependent','geography':'Evidence-dependent',
                'dependency':r.get('dependency'),'reasons':r['priority_reasons']},
            'execution_authorized':False,'preview':p.get('preview') if p else None}
        if website_action and target.get('system')=='WEBSITE' and target.get('entity_type') in {'WEBSITE_PAGE','LANDING_PAGE'}:
            v.update(what=website_action+' · '+p['title'],next_action=website_action,
                preview=p['website_preview']['verified_url'],website_preview=p['website_preview'],
                actionability='VERIFY_FIRST' if website_action in {'PROVIDER ACCESS REQUIRED','STALE PREVIEW'} else 'ACTIONABLE_NOW',
                reason_code='WEBSITE_PREVIEW_OWNER_REVIEW')
        v=reconcile_priority(v,lifecycle_states or {})
        if website_action=='READY FOR PRODUCTION EXECUTOR':
            v.update(actionability='WAITING',reason_code='SEPARATE_PRODUCTION_AUTHORITY_REQUIRED')
        v['decision_card']=p['decision_card'] if p else decision_card(item,evidence=evidence)
        v['todo_explanation']=todo_explanation(v,v['decision_card'])
        # Exact commercial-object state prevents separate projects at one
        # Account from collapsing into the same action.
        if v.get('lifecycle'):key=digest([v['lifecycle']['context'],family])
        if key in groups:
            g=groups[key];g['priority_ids'].append(pid);g['proposal_ids']+=v['proposal_ids']
            seen={digest(e) for e in g['evidence']};g['evidence'] += [e for e in evidence if digest(e) not in seen]
            if priority_order(v,now)<priority_order(g,now):
                v['priority_ids']=g['priority_ids'];v['proposal_ids']=g['proposal_ids'];groups[key]=v
        else:groups[key]=v
    return sorted(groups.values(),key=lambda r:priority_order(r,now))


def build_manager(inputs,store,now,*,active_ids=None,crosswalk=None):
    inputs={**inputs,'website-repositories':store.repository_states()}
    sources=registry(inputs,now);ps=proposals(store,sources,now)
    states=collect_states(inputs,now,store)
    for p in ps:
        if p['type']=='SALES_REPLY':
            state=states.get(context_key(p['target_object']))
            if state and reply_draft_obsolete(state):
                p['status']='SUPERSEDED';p['readiness']='SUPERSEDED';p['lifecycle']=state
    priorities_all=priorities(store,ps,sources,now,active_ids=active_ids,crosswalk=crosswalk,lifecycle_states=states)
    today=[r for r in priorities_all if eligible_today(r,now)][:5]
    sales=inputs.get('sales-conversations',{});acq=inputs.get('acquisition-intelligence',{});trigger=inputs.get('trigger-intelligence',{})
    business=inputs.get('business',{});snapshot=business.get('snapshot',{});finance={};customers=[]
    if snapshot:
        try:
            from .business_intelligence import build_business
            b=build_business(snapshot,now=now);finance={'observed_at':b['observed_at'],'sales':{k:v for k,v in b['sales'].items() if k!='deals'},
                'financial':b['financial'],'basis':b['basis'],'profitability':{'state':'UNKNOWN','reason':b['profitability']['reason']},
                'lineage':b['attribution']['coverage'],'recurring':b['recurring']}
            customers=b['customer_value'][:10]
        except (ValueError,TypeError,KeyError):finance={'state':'UNKNOWN','profitability':{'state':'UNKNOWN'}}
    conversations=sales.get('conversations',[])
    attention=[c for c in conversations if c.get('urgency') in {'HOT','HIGH'} and c.get('next_best_action')!='SUPPRESS'
               and states.get('OUTREACH:CONVERSATION:'+c['conversation_id'],{}).get('actionability') in {'ACTIONABLE_NOW','VERIFY_FIRST'}]
    domains=Counter(p['domain'] for p in ps);statuses=Counter(p['readiness'] for p in ps)
    events=store.events();nowday=now.astimezone(TZ).date().isoformat()
    changed=[e for e in events if stamp(e['recorded_at']) and now-stamp(e['recorded_at'])<=timedelta(days=1) and e['value'].get('change_type')!='INITIAL_OBSERVATION']
    universe=trigger.get('prospect_universe',{})
    sections={
        'sales':{'attention_count':len(attention) if conversations else None,'coverage':sales.get('coverage',{}),'gaps':sales.get('coverage_gaps',{}),
            'ownership':'CLAUDE_APOLLO unchanged; manual activity completeness UNKNOWN','detail':'/v1/operator/sales',
            'attention':[{'conversation_id':c['conversation_id'],'company':c.get('company'),'person':c.get('person_name'),
                'classification':c.get('reply_class'),'urgency':c.get('urgency'),'draft_ready':bool(c.get('draft')),
                'lifecycle':states.get('OUTREACH:CONVERSATION:'+c['conversation_id'],{})} for c in attention[:5]]},
        'acquisition':{'funnel':universe.get('funnel',{}),'coverage':universe.get('enrichment_metrics',{}),'signals':trigger.get('trigger_count'),
            'current_trigger_prospects':universe.get('current_trigger_prospects'),'historical_organizations':universe.get('historical_organizations'),
            'repeat_buyers':universe.get('repeat_buyers'),'detail':'/v1/operator/acquisition'},
        'customers':{'count':len(snapshot['accounts']) if 'accounts' in snapshot else None,'recent_value':customers,
            'expansion_proposals':domains['customer'],'need':'Only evidence-backed opportunities; existing customers retain relationship context'},
        'recurring':{k:inputs.get('recurring',{}).get(k) for k in ('books_profiles','profiles_linked','unlinked','recurring_services','state')},
        'finance':finance or {'state':'UNKNOWN','profitability':{'state':'UNKNOWN'}},
        'marketing':{'content_opportunities':acq.get('content_queue_count'),'hooks':len(store.rows('optibrain.optimization_asset')),
            'detail':'/v1/operator/marketing','publication':'OWNER APPROVAL REQUIRED'},
        'website_seo':{'content_queue':[{k:r.get(k) for k in ('id','service','language','title','target_query','existing_page','why','evidence_confidence')} for r in acq.get('content_queue',[])[:5]],'technical':acq.get('technical_seo',{}),'detail':'/v1/operator/acquisition',
            'preview_preparation':'Evidence-backed copy/FAQ/links/creative briefs; branch/build path when repository adapter available'},
        'ads':{'proposal_count':sum(p['domain']=='ads' for p in ps),'health':inputs.get('ads-intelligence',{}).get('source_health',{}),
            'detail':'/v1/operator/acquisition','mutation_authority':'ABSENT','pilot':'FR commercial camera; proposed CAD420/28 days, maximum CAD500; owner decision pending'},
        'system':{'signals':inputs.get('status',{}).get('signals',[]),'detail':'/v1/operator/system-health'},
        'owner_actions':{'upcoming':[a for a in authority_health(inputs,now) if a.get('expires_at')],
            'optional':[{'action':'GBP native read scope','trigger':'Only when native profile verification is desired'}],
            'deferred':[{'action':'Google Basic','trigger':'Native fresh Planner economics required for later quantitative optimization'},
                        {'action':'AI vendor hosting/legal proof','trigger':'Before approving provider-specific public AI claims'}],
            'waiting_natural_event':['Genuine consented paid click/outcome evidence; conversion exports remain OFF']} }
    completeness={'sales':'GREEN' if conversations else 'PARTIAL','acquisition':'PARTIAL','customers':'GREEN' if snapshot else 'PARTIAL',
        'recurring':'PARTIAL','finance':'PARTIAL','ads':'GREEN — WAITING NATURAL DATA','website_seo':'GREEN' if acq else 'PARTIAL',
        'content':'GREEN' if domains['content'] else 'PARTIAL','holo':'GREEN — INTENTIONALLY OPTIONAL','profitability':'BLOCKED'}
    activity=store.activity(now);counts=store.counts()
    assets=store.rows('optibrain.optimization_asset')
    content=[{'content_asset_id':a['record']['asset_id'],'type':a['record']['asset_type'],
        'service':a['record']['service'],'audience':a['record']['icp'],'channel':a['record']['channel'],
        'geography':a['record']['geography'],'hook':a['detail'].get('hook') or a['detail'].get('related_keyword') or a['record']['brief_or_prompt_reference'],
        'problem':a['detail'].get('problem','See linked proposal'),'proof':a['record']['rights_source_status'],
        'source_evidence':evidence_health(a['record']['source_evidence'],sources,now),
        'related_keyword':a['detail'].get('related_keyword'),'related_market_opportunity':a['detail'].get('related_market_opportunity'),
        'related_sales_question':a['detail'].get('sales_question'),'status':'DRAFT / BRIEF','preview':a['record']['draft_or_asset_reference'],
        'uses':a['record']['usage'],'performance':a['record']['performance_evidence']} for a in assets]
    sections['content']={'items':content[:20],'total':len(content),'publication':'OWNER APPROVAL REQUIRED','hook_library':'Shared Optimization Assets; no second queue'}
    from .website_registry import websites
    sections['websites']={'sites':websites(store,ps,now)}
    brief={'day':nowday,'what_changed':[{'event_id':e['id'],'title':e['value'].get('title')} for e in changed[:5]],
        'sales_attention':sections['sales']['attention'],'acquisition':sections['acquisition']['funnel'],
        'customer_actions':domains['customer'],'marketing_seo_ads':dict(domains),
        'proposals_ready':sum(p['readiness'] in {'PREVIEW_READY','OWNER_REVIEW','PROPOSED'} and p['status'] not in CLOSED for p in ps),
        'system_blockers':[{'source':s['source_id'],'state':s['data_health'],'reason':s['reason']} for s in sources if s['required'] and s['data_health'] in {'BLOCKED','STALE','AUTH_EXPIRED','PROVIDER_ERROR'}][:5],
        'top_priorities':[{'id':p['priority_id'],'what':p['what'],'why':p['why'],
            'current_state':p.get('current_state'),'actionability':p['actionability'],'reason_code':p['reason_code'],
            'latest_authoritative_event':p.get('lifecycle',{}).get('latest_authoritative_event'),
            'last_event_at':p.get('lifecycle',{}).get('last_event_at'),'confidence':p['confidence']} for p in today],
        'empty_day':'No newly changed evidence recorded; retained current decisions remain available.' if not changed else None}
    from .action_evidence import ActionEvidence
    audit_timeline=ActionEvidence(store.path).timeline(limit=40)
    return {'audit_timeline':audit_timeline,'learning_records':store.learning_records(limit=20),'schema':1,'type':'optibrain.manager','scope':'live','read_only':True,'at':now.isoformat(),
        'provider_writes':0,'execution_authorized':False,'persistent_worker':'OFF','today':today,'commercial_states':states,
        'sections':sections,'proposals':ps,'priority_count':len(priorities_all),'priorities':priorities_all,
        'proposal_counts':{'total':len(ps),'by_domain':dict(domains),'by_status':dict(statuses)},'sources':sources,
        'authority':authority_health(inputs,now),'events':events,'activity':activity,'brief':brief,
        'data_completeness':completeness,'manager_records':counts,'efficiency':{'runtime_model_calls':0,'new_provider_reads':0,
            'policy':'Reuse bounded provider caches; incremental semantic hashes; <=3 preparations/cycle; no persistent model worker',
            'provider_cost':'Observed credits only; unmetered invoices/costs UNKNOWN','usage':store.usage(now),
            'apollo_last_observed_credits':trigger.get('apollo_research_credits'),'apollo_last_observed_reads':trigger.get('apollo_research_calls')},
        'safety':{'protected':123,'new_financial_authority':0,'new_ads_authority':0,'new_outreach_authority':0,
            'conversion_exports':'OFF','English_real_automation':'DISABLED','Apollo_Claude':'UNCHANGED'},
        'navigation':{'business':'/v1/operator/business','sales':'/v1/operator/sales','acquisition':'/v1/operator/acquisition',
            'recurring':'/v1/operator/recurring','marketing':'/v1/operator/marketing','system':'/v1/operator/system-health'}}


def render_manager(view,*,query='',domain='',status=''):
    h=lambda x:escape(str(x),quote=True)
    def short(v,depth=0):
        if v is None:return '<span>UNKNOWN</span>'
        if isinstance(v,dict):
            if depth>3:return '<span>'+h(str(v)[:200])+'</span>'
            return '<dl>'+''.join('<dt><strong>'+h(k.replace('_',' ').title())+'</strong></dt><dd>'+short(n,depth+1)+'</dd>' for k,n in list(v.items())[:22])+'</dl>'
        if isinstance(v,list):
            if not v:return '<span>No observed items</span>'
            return '<ul>'+''.join('<li>'+short(n,depth+1)+'</li>' for n in v[:12])+'</ul>'
        return h(str(v)[:700])
    def card(title,body):return '<section><h2>'+h(title)+'</h2>'+body+'</section>'
    out="<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>OptiBrain Business Manager</title><style>body{font:16px system-ui;background:#f4f6f8;color:#173342;max-width:1200px;margin:auto;padding:24px}section,article{background:white;padding:20px;border-radius:8px;margin:14px 0}nav a{margin-right:16px}small{color:#556}button,input,select,textarea{font:inherit;padding:6px}td,th{padding:8px;text-align:left;border-bottom:1px solid #ddd}table{width:100%}details{margin:12px 0}</style><h1>OptiBrain Business Manager</h1><nav>"
    out+=''.join('<a href="'+h(url)+'">'+h(name.title())+'</a>' for name,url in view['navigation'].items())+'</nav><p>'+h(view['at'])+' · Owner review and preparation</p>'
    out+="<form method='get'><label>Find company, person, service, proposal or page <input name='q' maxlength='100' value='"+h(query)+"'></label> <label>Domain <input name='domain' value='"+h(domain)+"'></label> <label>Status <input name='status' value='"+h(status)+"'></label> <button>Filter</button></form>"
    out+=card('Today',''.join('<article><strong>'+h(p['what'])+'</strong><p>'+h(p['why'])+'</p><p>'+h(p['next_action'])+'</p><small>'+h(p['confidence'])+' · '+h(p.get('current_state','Owner review'))+' · '+h(p.get('actionability'))+' · '+h(p.get('reason_code'))+'</small></article>' for p in view['today']) or '<p>No current action due. Waiting and prepared work remain available below.</p>')
    out+=card('Morning brief',short(view['brief']['what_changed'])+'<p>'+short(view['brief'].get('empty_day') or '')+'</p>')
    for name,section in view['sections'].items():
        out+=card(name.replace('_',' ').title(),short(section))
    rows=[p for p in view['proposals'] if (not query or query.casefold() in str(p).casefold()) and (not domain or p['domain']==domain) and (not status or status in {p['status'],p['readiness']})]
    body='<p>'+h(view['proposal_counts'])+'</p>'
    for p in rows[:50]:
        url='/v1/operator/acquisition?proposal_id='+p['proposal_id']
        body+='<article><h3><a href="'+h(url)+'">'+h(p['title'])+'</a></h3><p>'+h(p['domain'])+' · '+h(p['status'])+' · '+h(p['readiness'])+' · confidence '+h(p['confidence'])+'</p><p>'+h(p['why'])+'</p><p>Benefit: '+h(p['expected_benefit'])+' · Cost: '+h(p['cost'])+'</p><p>Risk: '+h(p['risk'])+'</p><details><summary>Why this?</summary>'+short(p['evidence'])+'</details><p>'+h(p['owner_action'])+'</p>'
        body+=render_card(p['decision_card'])
        if p.get('website_preview'):
            body+='<details><summary>Website preparation / preview / review</summary>'+short(p['website_preview'])+'</details>'
        body+="<form method='post' action='/v1/operator/manager/feedback'><input type='hidden' name='kind' value='PROPOSAL'><input type='hidden' name='target' value='"+h(p['proposal_id'])+"'><input type='hidden' name='version' value='"+h(p['payload_hash'])+"'><label>Decision <select name='choice'>"+''.join('<option value="'+value+'">'+label+'</option>' for value,label in [('APPROVE','APPROVE'),('REQUEST_REVISION','REQUEST REVISION'),('REJECT','REJECT'),('WAIT','DEFER'),('NOT_RELEVANT','NOT RELEVANT'),('NEVER','NEVER')])+"</select></label><label> Reason <input name='reason' maxlength='1000'></label><label> Reconsider when <input name='conditions' maxlength='1000'></label><button>Record owner intent</button></form><small>Approval records intent. Provider execution still requires separate authority.</small></article>"
    out+=card('Optimization proposals',body)
    body=''
    for p in view['priorities'][:30]:
        body+=render_card(p['decision_card'])+'<details><summary>Why this todo exists</summary>'+short(p['todo_explanation'])+'</details>'
        body+='<article><strong>'+h(p['what'])+'</strong><p>'+h(p['status'])+' · '+h(p.get('current_state','Owner review'))+' · '+h(p['actionability'])+'</p><p>'+h(p['next_action'])+'</p><details><summary>Why / evidence / factors</summary>'+short(p.get('lifecycle'))+short(p['factors'])+short(p['evidence'])+'</details>'
        body+="<form method='post' action='/v1/operator/manager/feedback'><input type='hidden' name='kind' value='PRIORITY'><input type='hidden' name='target' value='"+h(p['priority_id'])+"'><input type='hidden' name='version' value='"+h(p['payload_hash'])+"'><select name='choice'>"+''.join('<option>'+c+'</option>' for c in ('HIGHER','LOWER','WAIT','NOT_RELEVANT','NEVER'))+"</select><button>Save preference</button></form></article>"
    out+=card('Business priorities',body)
    out+=card('Source health','<table><tr><th>Source</th><th>Auth</th><th>Data</th><th>Observed</th><th>Reason</th></tr>'+''.join('<tr>'+''.join('<td>'+h(s[k])+'</td>' for k in ('provider','authentication_health','data_health','observed_at','reason'))+'</tr>' for s in view['sources'])+'</table>')
    out+=card('Authority health',short(view['authority']))+card('What OptiBrain actually did',short(view['activity']))
    out+=card('Action audit timeline',short(view.get('audit_timeline',[])))
    out+=card('Business event feed',''.join('<p>'+h(e['value'].get('title'))+' · '+h(e['observed_at'])+' · '+h(e['value']['classification'])+'</p>' for e in view['events'][:30]))
    out+=card('Completeness / efficiency',short(view['data_completeness'])+short(view['efficiency']))
    return out+'</html>'
