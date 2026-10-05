"""Phase33 completion contracts. Pure preparation; no provider client/writer."""
from .acquisition_store import digest
from math import isfinite

GOALS = {
    'goal_config_level':'CAMPAIGN', 'custom_conversion_goal':None,
    'initial_biddable_goals':[],
    'initial_strategy':'MAXIMIZE_CLICKS, never conversion-based bidding',
    'account_defaults':'Do not inherit; set every returned campaign category/origin biddable=false before activation',
    'native_form_success':{'action_id':'7582574548','target':'SECONDARY / OBSERVATION ONLY',
        'current':'HIDDEN GA4 import; enable secondary only after separately approved TEST exclusion and import review',
        'counting_proposal':'ONE_PER_CLICK; diagnostic GA4 event remains ONCE_PER_EVENT', 'value_proposal':0},
    'legacy_merci':{'action_id':'7567646545','disposition':'REMOVE FROM BIDDING; SECONDARY ONLY pending retirement',
        'reason':'WEBPAGE_CODELESS page visit is not a submission acknowledgement'},
    'offline':{'qualified_lead':'7795448568','estimate_accepted':'7795962128','invoice_paid':'7796070369',
        'target':'SECONDARY, never in a custom goal; exports OFF / NOT AUTHORIZED',
        'later_bidding':'Only one separately approved meaningful funnel stage; qualified_lead first after genuine evidence'},
    'double_counting':'Never sum acknowledgement, Lead, qualification, accepted Estimate and paid Invoice as unique customers or revenue',
}

def complete_preview(detail):
    """Complete every existing FR/EN camera/cabling variant without arming it."""
    camera=detail['service']=='Security cameras';total=420 if camera else 280;cap=500 if camera else 350
    detail['locations'].update({'include_resource_ids':['geoTargetConstants/1002604','geoTargetConstants/1002579'],
        'resource_ids':'Montréal and Laval city constants; re-read status/country/type before paused creation',
        'negative_geo_target_type':'PRESENCE','optional_owner_review':[],
        'excluded_expansion':'No Canada/Québec-wide, Québec City, Rive-Nord, radius or location-of-interest target in the initial spec'})
    detail['ad_schedule']={'initial':'ALL_DAYS_ALL_HOURS','phone':'No unsupported business-hours promise or call-only conversion goal',
        'reason':'Form is available continuously; no commercial-hour conversion evidence supports restricting low volume',
        'timezone':'America/Toronto'}
    detail['device_policy']='All devices, no bid adjustments; historical tiny/PMax-mixed data is not a reliable device-effect estimate'
    detail['language_resource_id']='languageConstants/1002' if detail['language']=='FR' else 'languageConstants/1000'
    detail['negative_preview']={
        'ACCOUNT_LEVEL_CANDIDATE':['emploi','jobs','salaire','salary','career','formation','cours','do it yourself','diy'],
        'CAMPAIGN_LEVEL':['pour maison','pour la maison','home security','for home','para casa'] if camera else ['cable ethernet achat','buy ethernet cable'],
        'AD_GROUP_LEVEL':[],
        'REVIEW_ONLY':['Exact historical product-shopping searches, eufy/tapo/dekco; preserve explicit commercial installation/compatibility exceptions',
            'free/gratuit, brand names, wireless, construction, residential mixed-use: never blanket-negate a valid commercial quote'],
        'execution':'NONE; future approved initial negatives are campaign-level only, no account-wide mutation',
        'match_type':'PHRASE for explicit irrelevant intent; EXACT for individually reviewed product-only searches',
    }
    detail['conversion_goal_proposal']=GOALS
    detail['test_isolation']={'GA4_filters':'Internal and Developer Exclude/Testing remain unchanged; Testing labels, not exclusion',
        'owner_QA':'Use existing Tag Assistant/debug session and device-local legacy GTM/Ads request blocking; no new native submission required here',
        'business_KPIs':'Immutable TEST ownership and additive reviewed test classification excluded from natural Leads/outcomes',
        'ads_import':'Keep generate_lead HIDDEN during initial pilot unless independently proven TEST exclusion is separately approved',
        'consent':'Analytics acceptance never grants ad_storage, ad_user_data or ad_personalization; all remain denied',
        'ordinary_traffic':'No broad filter activation, no changed real visitor consent, no synthetic click IDs in production'}
    detail['budget'].update({'preferred_mode':'CAMPAIGN_TOTAL_BUDGET',
        'period':'CUSTOM_PERIOD','total_amount_micros':total*1000000,'explicitly_shared':False,
        'amount_micros':None,'flight_days':28,'hard_ceiling_CAD':cap,
        'pacing_equivalent_daily':total/28,'daily_overdelivery_risk':None,
        'daily_limit':'Total-budget flights have no daily spend cap. CAD15/10 is an average pacing comparison only.',
        'not_enforced':'No campaign exists. Future exact paused creation must validate native total-budget availability and read back the cap and dates. Do not silently fall back to daily budgeting.',
        'source':'https://support.google.com/google-ads/answer/10486938',
        'alternative':'DAILY only by separately sealed owner decision plus proven spend monitor/pause authority; polling alone cannot guarantee a strict total cap'})
    detail['spend_guard']={'planned_total_CAD':total,'owner_maximum_CAD':cap,'warn_CAD':round(total*.75,2),
        'pause_CAD':round(total*.9,2),'read_interval_minutes':15,'maximum_read_age_minutes':15,
        'unknown_spend':'NO ACTIVATE / HOLD; if already active, exact campaign PAUSE under separately graduated pause-only authority and alert owner',
        'failure_to_pause':'UNKNOWN EFFECT HOLD; alert owner for immediate native pause; no retry-create or claim of enforcement',
        'hard_backstop':'Native nonshared total budget and exact 28-day end; monitor is an early stop, not the hard cap',
        'daily_option':'Require a validated maximum delayed/unreported charge bound plus reserved headroom; absent proof deny activation',
        'installed':'NONE — design only; future pilot activation requires implemented/proven monitor, stop and native budget readback'}
    detail['stop_conditions']={'immediate':['Privacy/consent or PII breach','Wrong final URL/form or broken intake/success listener',
        'Unauthorised goal/network/location/budget/spec change','Spend state unknown/stale; pause transport/kill switch unhealthy',
        'Campaign total cap/date mismatch or unapproved serving'],
        'bounded_reviews':['At 30 reported relevant clicks or day7/14 review: >30% irrelevant intent among at least20 reported search-term clicks -> pause/revise exact negatives',
        'Reported CPC > approved risk ceiling after at least10 clicks -> hold and inspect strategy/auction before any higher bid',
        'At least3 confirmed out-of-target clicks or >10% outside target among20 location-report clicks -> pause/review presence settings',
        'No qualified inquiries after30 relevant clicks -> owner review, not statistical rejection; stop at spend/end bounds'],
        'limits':'Search-term/location reporting is incomplete/delayed. Safety failures stop immediately; performance decisions need valid denominators.'}
    detail['measurement_window']={'days':28,'review_days':[7,14,28],'minimum_intent_sample_relevant_clicks':30,
        'promising':'At least3 genuine independently qualified campaign-linked inquiries within cap, no guardrail breach; directional only',
        'insufficient_data':'Sparse clicks, only TEST/debug, missing click/consent/outcome linkage or incomplete denominators',
        'CPA_ROAS_margin':'UNKNOWN until genuine qualified outcomes, deterministic revenue and cost lineage exist'}
    detail['rollback']={'operation':'Pause exact newly created campaign; retain all evidence; no remove/delete or old campaign revival',
        'website':'Exact reviewed website rollback reference; landing copy remains preview unless separately approved',
        'authority':'Separate campaign-specific pause-only scope; owner native pause is fallback'}
    detail['graduation']={'current':'READ / ANALYZE / PREPARE ONLY',
        'approval_binds':['proposal_id','revision','core_and_detail_sha256','account6808491878','operationCREATE_PAUSED',
            'exact canonical spec','budget/date/geo/network/goal fingerprint','approved_by/time','expiry','nonce'],
        'idempotency':'Durable exact operation key plus existing off-host effect claim; one winner. Never repeat create after lost acknowledgement.',
        'read_after_write':'Reconcile native resource IDs/statusPAUSED, budget/dates/goals/network/language/geo/ads/keywords against sealed spec before success',
        'unknown_effect':'HOLD, read/reconcile exact operation; no retry with new name/key',
        'kill_switch':'Root Ads stop, global stop, expiry and protected boundary checked before transport',
        'approval_effect':'Local REVIEWED and fixture APPROVED confer no execution. Future CREATE_PAUSED adds no activation or goal mutation authority.',
        'next_stage':'Separate owner activation, native total-budget and monitor proof, then measurement/learning; no unrestricted edit-any-object API'}
    detail['future_outcomes']={k:None for k in ('impressions','clicks','search_terms','CPC','form_success','Lead','qualified_lead',
        'Estimate','estimate_accepted','invoice_paid','spend','CPA','ROAS','margin','learning')}
    if detail['launch_state']!='LANDING PAGE REVIEW REQUIRED':
        detail['launch_state']='PREVIEW COMPLETE — future exact approval, paused creation and activation graduation required'
    detail['launch_dependencies']=['Separate exact CREATE_PAUSED approval; no current writer',
        'Read back native total budget/dates/goals and implement/prove bounded monitor+pause before activation',
        'Preserve TEST isolation, analytics-only consent and manual English triage; no export activation',
        'Use existing live camera/cabling page; optional copy preview needs separate owner approval']
    return detail

def check_seal(detail,expected_hash):
    """Pure prerequisite fixture/helper. Successful check grants no authority."""
    return {'state':'MATCH' if digest(detail)==expected_hash else 'DENY_ALTERED_SPEC','execution_authorized':False,'provider_writes':0}

def spend_decision(spend,*,age_minutes,guard):
    if spend is None or not isinstance(age_minutes,(int,float)) or isinstance(age_minutes,bool) or not isfinite(age_minutes) or age_minutes<0 or age_minutes>guard['maximum_read_age_minutes']:
        state='HOLD_UNKNOWN_SPEND'
    elif not isinstance(spend,(int,float)) or isinstance(spend,bool) or not isfinite(spend) or spend<0:state='HOLD_INVALID_SPEND'
    elif spend>=guard['pause_CAD']:state='PAUSE_REQUIRED'
    elif spend>=guard['warn_CAD']:state='OWNER_WARNING'
    else:state='OBSERVE'
    return {'state':state,'execution_authorized':False,'provider_writes':0}
