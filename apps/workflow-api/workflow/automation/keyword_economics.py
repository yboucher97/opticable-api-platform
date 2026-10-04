"""Bounded, cached Keyword Planner evidence. No provider writes or automatic purchases."""
from datetime import datetime, timedelta
from .acquisition_store import digest, normalized, safe
from .acquisition_intelligence import number, service_for, intent_for

SOURCE='windsor_keyword_planner'
URL='https://windsor.ai/'
FRESHNESS=30*86400
MAX_ROWS=12


def normalize(envelope, *, now):
    safe(envelope)
    if (envelope.get('schema')!=1 or envelope.get('provider')!='windsor_google_ads_keyword_planner'
            or envelope.get('account')!='6808491878' or envelope.get('currency')!='CAD'
            or envelope.get('location_id')!='20123'):
        raise ValueError('Keyword economics provenance is not established')
    at=datetime.fromisoformat(envelope['retrieved_at'].replace('Z','+00:00'))
    if at.utcoffset() is None or at>now:
        raise ValueError('Invalid keyword economics observation time')
    stale=(now-at).total_seconds()>FRESHNESS
    rows=[];seen=set()
    requests=envelope.get('requests',[]);replies=envelope.get('replies',[])
    if len(requests)!=2 or len(replies)!=2:
        raise ValueError('Independent FR/EN batches required')
    for request,reply in zip(requests,replies):
        options=request.get('options',{});language={'1002':'FR','1000':'EN'}.get(options.get('language'))
        if (request.get('connector')!='google_ads' or request.get('accounts')!=['680-849-1878'] or
                not language or options.get('geo_target_constants')!='20123' or
                options.get('keyword_plan_network')!='GOOGLE_SEARCH' or reply.get('status')!='done'):
            raise ValueError('Keyword economics request scope is not proven')
        raw=reply.get('data',[])
        if not isinstance(raw,list) or len(raw)>1000:
            raise ValueError('Keyword economics batch exceeds bound')
        seeds=[normalized(q) for q in options.get('keyword_seeds','').split(',') if q.strip()]
        if not 1<=len(seeds)<=6:raise ValueError('Keyword seed budget exceeded')
        # Seed terms first, then examples with economics or explicit zero. Never
        # buy/enrich the existing keyword universe merely because it exists.
        ordered=sorted(enumerate(raw),key=lambda pair:(normalized(pair[1].get('keyword','')) not in seeds,
                  pair[1].get('keyword_average_cpc') is None and pair[1].get('avg_monthly_searches')!=0,pair[0]))
        for _,r in ordered[:6]:
            if r.get('keyword_country')!='Quebec' or r.get('keyword_language')!=('French' if language=='FR' else 'English'):
                raise ValueError('Provider geography/language differs from requested scope')
            query=r.get('keyword');identity=(normalized(query or ''),language,'QUÉBEC')
            if not query or identity in seen:continue
            seen.add(identity)
            index=number(r.get('competition_index'))
            if index is not None and index>100:raise ValueError('Invalid competition index')
            micros=lambda field:number(r.get(field))/1e6 if number(r.get(field)) is not None else None
            row={'query':query,'language':language,'geography':'QUÉBEC','geography_basis':'PROVIDER REQUEST AND RESPONSE',
                 'source':SOURCE,'provider':'Google Keyword Planner via Windsor connector','provider_url':URL,
                 'retrieved_at':at.isoformat(),'observed_at':at.isoformat(),'date_from':None,'date_to':None,
                 'window':'TRAILING 12 MONTHS — EXACT EFFECTIVE MONTH BOUNDS NOT RETURNED',
                 'requested_window':{'from':request.get('date_from'),'to':request.get('date_to')},
                 'market_volume':number(r.get('avg_monthly_searches')),'competition_index':index,
                 'paid_competition':r.get('keyword_competition') or None,'low_bid':micros('top_of_page_bid_low'),
                 'high_bid':micros('top_of_page_bid_high'),'cpc':micros('keyword_average_cpc'),
                 'observed_cpc':None,'currency':'CAD','currency_proof':'Native Google Ads customer currency read',
                 'metric_basis':'PROVIDER ESTIMATE — NOT ACTUAL OPTICABLE CPC OR PROVEN ROI',
                 'confidence':'PROVIDER ESTIMATE','stale':stale,'service':service_for(query),'intent':intent_for(query),
                 'cost_class':'EXISTING WINDSOR TRIAL; EXACT CREDITS NOT EXPOSED',
                 'limitations':['Close variants can overlap; do not sum into market size.',
                                'Sparse bid/CPC data remains unknown; reported zero is preserved.',
                                'Connector access works now; trial continuity is not guaranteed.']}
            rows.append(row)
    return rows[:MAX_ROWS]


def integrate(store,envelope,*,now):
    rows=normalize(envelope,now=now)
    sid=store.snapshot(SOURCE,URL,envelope,now)
    for row in rows:
        store.record('KEYWORD',row,source=SOURCE,native_id=digest([row['query'],row['language'],row['geography']]),
                     url=URL,now=now,snapshot=sid,observed_at=row['observed_at'],confidence='PROVIDER ESTIMATE',
                     cost_class=row['cost_class'])
    stale=any(r['stale'] for r in rows)
    store.source(SOURCE,'PARTIAL' if stale else 'WORKING',now,observed_at=envelope['retrieved_at'],requests=2,
                 reason='Cached Québec FR/EN Keyword Planner estimates via working Windsor gateway; direct Google Explorer access blocked. Trial continuity remains external.',
                 cost_class='EXISTING WINDSOR TRIAL',query=digest(envelope['requests']),cache_hit=True)
    return {'state':'STALE' if stale else 'WORKING','source':SOURCE,'access':'CONNECTOR/GATEWAY — CACHED; NO AUTONOMOUS REFRESH',
            'retrieved_at':envelope['retrieved_at'],'refresh_after':(datetime.fromisoformat(envelope['retrieved_at'].replace('Z','+00:00'))+timedelta(seconds=FRESHNESS)).isoformat(),
            'records':len(rows),'volume_known':sum(r['market_volume'] is not None for r in rows),
            'cpc_known':sum(r['cpc'] is not None for r in rows),'competition_known':sum(r['paid_competition'] is not None for r in rows),
            'currency':'CAD','geography':'QUÉBEC','rows':rows,'provider_calls_this_rebuild':0,
            'direct_google_status':'PLAN LIMITED — EXPLORER; BASIC ACCESS REQUIRED',
            'metric_basis':'PROVIDER ESTIMATES; MISSING VALUES ARE UNKNOWN','trial_continuity':'NOT GUARANTEED'}
