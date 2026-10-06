"""Deterministic local previews, <=3 changed items/cycle, no provider writes."""
from datetime import timedelta
from .acquisition_store import digest
from .ads_intelligence import proposal
from .ads_runtime import persist
from .manager_intelligence import semantic_evidence
from .manager_sources import stamp

CHANNELS=['website','article','GBP','LinkedIn','Facebook / Instagram','short video','sales collateral','Apollo proof point']


def prepare(inputs,store,now,*,maximum=3):
    if type(maximum) is not int or not 0<=maximum<=3:raise ValueError('Preparation bound required')
    acq=inputs.get('acquisition-intelligence',{});old={p['record']['proposal_id']:p for p in store.rows()}
    feedback=store.feedback_latest();created=[];reused=0;considered=0
    source={r['source']:r for r in acq.get('source_health',[])}
    for row in acq.get('content_queue',[])[:10]:
        sample=row.get('search_sample',{});at=stamp(sample.get('observed_at'))
        if not at or not 0<=(now-at).total_seconds()<7*86400 or not row.get('existing_page'):continue
        considered+=1;service=row.get('service','UNKNOWN');language=row.get('language','UNKNOWN')
        pid=digest(['manager-website',row.get('id')]);title='Review '+service+' '+language+' page intent, FAQ and internal links'
        r=proposal('WEBSITE_EVIDENCE_PREVIEW',service,language,[],now,{},problem=row.get('why','Page opportunity'),change=title)
        r.update(proposal_id=pid,target_system='WEBSITE',target_object={'system':'WEBSITE','entity_type':'WEBSITE_PAGE','entity_id':row['existing_page']},
            target_url_or_record=row['existing_page'],business_problem=row.get('why','Existing search visibility needs review'),
            why_now=row.get('why_now','Dated Search Console evidence'),recommended_change=title,
            source_evidence=[{'provider':'SEARCH_CONSOLE','source_reference':row.get('target_query',row['existing_page']),
                'observed_at':at.isoformat(),'valid_until':(at+timedelta(days=7)).isoformat(),'freshness':'CURRENT','confidence':'TENTATIVE',
                'truth_class':'NATIVE_MEASURED','limitations':['Small organic sample; no causal conversion claim.']}],
            confidence='TENTATIVE',data_quality='Dated page/query evidence; editorial draft requires expertise review',
            preview_location='/v1/operator/acquisition?proposal_id='+pid,
            affected_files_or_records=[row['existing_page']],status='PREVIEW_READY',
            expected_benefit='Clearer commercial intent and qualified inquiry path; outcome UNKNOWN',
            risk='Unsupported claims, irrelevant links or broken form; owner verifies draft before exact branch/build/publication approval',
            owner_action_required='Review actual local copy/FAQ/link/creative draft; request branch/build only after repository mapping',
            rollback_reference='Preserve existing source SHA; revert reviewed change through normal deployment')
        detail={'service':service,'language':language,'page':row['existing_page'],'source_sample':sample,
            'preview_kind':'LOCAL_EDITORIAL_DRAFT','repository_branch':None,'build_status':'NOT_RUN — no website repository modification',
            'draft':{'heading':service+(' pour votre entreprise' if language=='FR' else ' for your business'),
                'copy':('Décrivez votre site, vos besoins et votre échéancier pour préparer une évaluation.' if language=='FR' else
                        'Tell us about your site, requirements and timeline so we can prepare an assessment.'),
                'cta':'Request a site assessment / Demander une évaluation',
                'faq':[{'question':'What information helps prepare an installation estimate?',
                        'answer':'Describe the site, required service and timeline. Technical scope and commercial terms require an assessment.'}],
                'links':[{'label':'Quote / Soumission','target':'Existing native FR/EN form on this page; preserve embed/callbacks'},
                         {'label':'Related service','target':'Owner selects an existing relevant service page; no invented URL'}]},
            'creative_brief':{'provider':'HOLO_OPTIONAL / SUPPORTED_IMAGE_PROVIDER','service':service,'audience':row.get('icp'),
                'hook':row.get('target_query'),'channel':'website','proof':'Owner supplied licensed project image required',
                'rights_provenance':'UNKNOWN — do not publish an unverified customer image','prompt':'Commercial '+service+' installation, no logos or unsupported product claim',
                'asset_reference':None,'status':'BRIEF_READY','intended_use':row['existing_page']},
            'repurposing':[{'channel':c,'status':'BRIEF_ONLY','hook':row.get('target_query'),
                           'proof':'Same dated query; owner project proof required before a case study','publication_allowed':False} for c in CHANNELS],
            'checks':['Preserve FR/EN embed and acknowledged-success callbacks','No duplicate service/doorway page',
                      'Validate links, accessibility and repository build before publication','No provider/customer write'],
            'migration_plan':'Create isolated website branch after exact repository mapping; render/build/test; request production approval; retain rollback SHA',
            'related_market_opportunity':row.get('id'),'related_keyword':row.get('target_query'),'performance':None}
        r['measurement_plan']={'metrics':[{'metric':'qualified inquiries from improved page','source_reference':'Immutable intake + exact page/source + CRM qualification',
            'unit':'count','baseline_value':None,'baseline_status':'UNKNOWN','baseline_sample':None,'baseline_window':None,
            'cohort_geography_language':service+' / '+language+' / exact page'}],
            'window':'28 days baseline and 28 days post-approved deployment; compare matched weekday windows',
            'minimum_usable_sample':'At least 30 relevant organic visits and 5 qualified inquiries; otherwise INSUFFICIENT_DATA',
            'guardrails':['No broken quote/acknowledgement path','No material organic visibility regression','No unsupported claims or TEST business KPI'],
            'success':'Improved observed qualified inquiry rate with usable sample and intact guardrails; association only',
            'neutral':'Usable sample with no clear movement','regression':'Guardrail breach or observed qualified inquiry decline',
            'insufficient_data':'Tiny sample, missing lineage or unmatched windows; no causal claim',
            'test_exclusion':'Exclude known diagnostic TEST inquiries; retain GA4 Testing-filter limitations',
            'attribution_limits':'No causal inference; seasonality and other marketing changes remain confounders'}
        item={'record':r,'detail':detail};prior=old.get(pid);f=feedback.get(('PROPOSAL',pid))
        if f and (f['choice']=='NEVER' or f['choice'] in {'REJECT','NOT_RELEVANT','WAIT'} and f['value'].get('semantic_evidence')==semantic_evidence(r,detail)):
            reused+=1;continue
        if prior and semantic_evidence(prior['record'],prior['detail'])==semantic_evidence(r,detail):reused+=1;continue
        if len(created)>=maximum:continue
        priority={'schema':1,'type':'optibrain.business_priority','priority_id':digest(['priority',pid]),'domain':'WEBSITE_SEO',
            'targets':[r['target_object']],'proposal_id':pid,'what':title,'why':r['business_problem'],'business_impact':r['expected_benefit'],
            'urgency':'MEDIUM','due_at':None,'confidence':'TENTATIVE','data_quality':r['data_quality'],'source_evidence':r['source_evidence'],
            'priority_reasons':['Dated query visibility','Improve existing page before duplicating service pages'],
            'dependency':'Repository branch/build and owner editorial approval','blocker':None,'actor':'OWNER','can_prepare':True,
            'owner_approval_required':True,'status':'OWNER_REVIEW','created_at':now.isoformat(),'updated_at':now.isoformat(),
            'next_action':'Read local copy/FAQ/creative preview; approve intent or request revision'}
        asset={'schema':1,'type':'optibrain.optimization_asset','asset_id':digest(['content',pid]),'asset_type':'ARTICLE_IDEA',
            'proposal_id':pid,'service':service,'icp':row.get('icp') or 'Business buyer','geography':row.get('geography','UNKNOWN'),
            'language':language,'channel':'WEBSITE','source_evidence':r['source_evidence'],'provider':'LOCAL_DETERMINISTIC',
            'brief_or_prompt_reference':r['preview_location'],'draft_or_asset_reference':r['preview_location'],
            'rights_source_status':'Owner-licensed project proof required','usage':'Editorial draft and repurposing brief; no publication',
            'illustrative':True,'performance_evidence':[],'created_at':now.isoformat()}
        persist({'proposals':[item],'priorities':[{'record':priority,'detail':{}}],'assets':[{'record':asset,'detail':detail}]},store)
        created.append(pid)
    return {'created':created,'reused':reused,'considered':considered,'maximum':maximum,'model_calls':0,'provider_writes':0}


def prepare_forms(inputs,store,now,*,maximum=3):
    """Only verified native/design evidence can prepare a shared Form proposal."""
    from .manager_forms import preview
    if type(maximum) is not int or not 0<=maximum<=3:raise ValueError('Preparation bound required')
    created=[];old={r['record']['proposal_id']:r for r in store.rows()};feedback=store.feedback_latest()
    for form in inputs.get('forms',{}).get('models',[])[:10]:
        at=stamp(form.get('observed_at'))
        if not at or not 0<=(now-at).total_seconds()<7*86400:continue
        draft=preview(form)
        if not draft:continue
        pid=digest(['manager-form',form['form_id']]);lang=form.get('language','UNKNOWN')
        ev=[{'provider':'ZOHO_FORMS','source_reference':form['form_id'],'observed_at':at.isoformat(),
             'valid_until':(at+timedelta(days=7)).isoformat(),'freshness':'CURRENT','confidence':'MODERATE',
             'truth_class':'NATIVE_MEASURED','limitations':['Local specification only; native provider draft needs separate write authority']}]
        r=proposal('FORM_REVISION_DRAFT','Quote intake',lang,ev,now,{},problem='; '.join(draft['issues']),change='Review quote Form draft and migration specification')
        r.update(proposal_id=pid,target_system='ZOHO_FORM',target_object={'system':'ZOHO_FORMS','entity_type':'FORM','entity_id':form['form_id']},
            target_url_or_record=form['form_id'],preview_location='/v1/operator/acquisition?proposal_id='+pid,
            expected_benefit='Reduce verified intake/mapping friction; abandonment and conversion benefit UNKNOWN',
            affected_files_or_records=[form['form_id']],owner_action_required='Review exact mapping/callbacks/tests/migration draft; no production replacement',
            rollback_reference=draft['rollback'])
        r['measurement_plan']['metrics'][0].update(metric='genuine acknowledged inquiries with useful service/attribution mapping',source_reference='Immutable native Form receipts + exact CRM association')
        r['measurement_plan']['guardrails']=['Preserve native form identity/acknowledgement and rollback','CRM native writer stays OFF','Exclude TEST inquiries; no unproven abandonment claim']
        detail={'form':{k:form.get(k) for k in ('form_id','language','fields','required_fields','hidden_fields','attribution_fields','callbacks')},'draft':draft}
        prior=old.get(pid);f=feedback.get(('PROPOSAL',pid))
        if f and (f['choice']=='NEVER' or f['choice'] in {'REJECT','WAIT','NOT_RELEVANT'} and f['value'].get('semantic_evidence')==semantic_evidence(r,detail)):continue
        if prior and semantic_evidence(prior['record'],prior['detail'])==semantic_evidence(r,detail):continue
        if len(created)>=maximum:break
        persist({'proposals':[{'record':r,'detail':detail}],'priorities':[],'assets':[]},store);created.append(pid)
    return {'created':created,'model_calls':0,'provider_writes':0}
