"""Fixed, bounded Google acquisition READS; no mutation/upload destinations."""
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
import json
import httpx
from time import monotonic
from zoneinfo import ZoneInfo

ADS = 'https://googleads.googleapis.com/v25/customers/6808491878/'
SITE = quote('sc-domain:opticable.ca', safe='')


class GoogleAcquisitionReader:
    def __init__(self, token, *, transport=None, limit=14):
        if not token:raise ValueError('Google credential unavailable')
        self.http=httpx.Client(headers={'Authorization':'Bearer '+token},timeout=httpx.Timeout(8,connect=3),
                               transport=transport,follow_redirects=False)
        self.limit=min(limit,14);self.calls=0;self.started=monotonic()

    def read(self, kind, *, now):
        # Neither URL nor query is caller supplied. All POST bodies are provider
        # reporting SELECTs / report requests. Generic Google remains GET-only.
        today=now.astimezone(ZoneInfo('America/Toronto')).date()
        end=(today-timedelta(days=2)).isoformat();start=(today-timedelta(days=33)).isoformat()
        span="segments.date BETWEEN '"+start+"' AND '"+end+"'"
        queries={
            'ads_customer':'SELECT customer.id, customer.currency_code, customer.time_zone FROM customer',
            'ads_campaigns':'SELECT campaign.id, campaign.name, campaign.status, campaign.advertising_channel_type, metrics.impressions, metrics.clicks, metrics.cost_micros, metrics.conversions FROM campaign WHERE '+span+' LIMIT 300',
            'ads_keywords':'SELECT campaign.id, ad_group.id, ad_group_criterion.criterion_id, ad_group_criterion.keyword.text, ad_group_criterion.keyword.match_type, ad_group_criterion.status, ad_group_criterion.negative, ad_group_criterion.quality_info.quality_score, metrics.impressions, metrics.clicks, metrics.cost_micros, metrics.average_cpc FROM keyword_view WHERE '+span+' LIMIT 500',
            'ads_search_terms':'SELECT campaign.id, ad_group.id, search_term_view.search_term, search_term_view.status, metrics.impressions, metrics.clicks, metrics.cost_micros FROM search_term_view WHERE '+span+' LIMIT 500',
            'ads_geo_constants':"SELECT geo_target_constant.resource_name, geo_target_constant.name, geo_target_constant.canonical_name, geo_target_constant.country_code, geo_target_constant.target_type FROM geo_target_constant WHERE geo_target_constant.country_code = 'CA' AND geo_target_constant.name IN ('Canada', 'Quebec', 'Montréal', 'Montreal', 'Laval') LIMIT 25",
            'ads_languages':"SELECT language_constant.resource_name, language_constant.name, language_constant.code FROM language_constant WHERE language_constant.code IN ('fr','en')",
        }
        body=None;method='POST'
        if kind in queries:url=ADS+'googleAds:search';body={'query':queries[kind]}
        elif kind=='gsc_sites':method='GET';url='https://www.googleapis.com/webmasters/v3/sites'
        elif kind=='gsc_sitemaps':method='GET';url='https://www.googleapis.com/webmasters/v3/sites/'+SITE+'/sitemaps'
        elif kind.startswith('gsc_') and kind[4:] in ('queries','daily','devices','countries'):
            dimensions={'queries':['query','page','country'],'daily':['date'],'devices':['device'],'countries':['country']}[kind[4:]]
            url='https://www.googleapis.com/webmasters/v3/sites/'+SITE+'/searchAnalytics/query'
            body={'startDate':start,'endDate':end,'dimensions':dimensions,'rowLimit':1000,'dataState':'final'}
        elif kind=='ga4_collection':
            start=(today-timedelta(days=90)).isoformat();end=(today-timedelta(days=1)).isoformat()
            url='https://analyticsdata.googleapis.com/v1beta/properties/530093120:runReport'
            body={'dateRanges':[{'startDate':start,'endDate':end}],
                  'dimensions':[{'name':x} for x in ('date','eventName','hostName')],
                  'metrics':[{'name':'eventCount'}], 'limit':'500',
                  'orderBys':[{'dimension':{'dimensionName':'date'},'desc':True}],
                  'dimensionFilter':{'filter':{'fieldName':'hostName','inListFilter':{'values':['opticable.ca','www.opticable.ca','ai.opticable.ca']}}}}
        elif kind in ('ga4_main','ga4_other'):
            pid='530093120' if kind=='ga4_main' else '530619880'
            url='https://analyticsdata.googleapis.com/v1beta/properties/'+pid+':runReport'
            body={'dateRanges':[{'startDate':start,'endDate':end}],
                  'dimensions':[{'name':x} for x in ('landingPage','sessionSourceMedium','deviceCategory')],
                  'metrics':[{'name':x} for x in ('sessions','activeUsers','engagedSessions')],'limit':'500'}
        elif kind in ('market_keywords_fr','market_keywords_en'):
            # Language/Quebec resource IDs independently read from native
            # constants before this bounded research operation was added.
            fr=kind.endswith('_fr')
            seeds=('câblage structuré','câblage réseau','installation cat6','fibre optique entreprise','installation wifi commercial','wifi entrepôt','caméra surveillance commerciale','contrôle accès entreprise','intercom immeuble','alarme commerciale','wifi chantier','caméra chantier','téléphonie ip entreprise','réseau géré','support réseau entreprise','prévention pertes intelligence artificielle','liaison sans fil point à point') if fr else ('structured cabling','network cabling','cat6 installation','commercial fiber installation','commercial wifi installation','warehouse wifi','commercial security cameras','access control installation','commercial intercom','commercial alarm installation','construction wifi','construction cameras','business ip telephony','managed network','network support','ai loss prevention','point to point wireless')
            url=ADS.rstrip('/')+':generateKeywordHistoricalMetrics'
            body={'keywords':list(seeds),'language':'languageConstants/1002' if fr else 'languageConstants/1000',
                  'geoTargetConstants':['geoTargetConstants/20123'],'keywordPlanNetwork':'GOOGLE_SEARCH',
                  'historicalMetricsOptions':{'includeAverageCpc':True}}
        elif kind in ('gsc_inspect_wifi_fr','gsc_inspect_wifi_en'):
            path='/fr/services/installation-wifi-commercial/' if kind.endswith('_fr') else '/en/services/commercial-wifi-installation/'
            url='https://searchconsole.googleapis.com/v1/urlInspection/index:inspect'
            body={'inspectionUrl':'https://opticable.ca'+path,'siteUrl':'sc-domain:opticable.ca','languageCode':'en-US'}
        else:raise ValueError('Only fixed acquisition reads are allowed')
        if self.calls>=self.limit or monotonic()-self.started>=40:raise ValueError('Google acquisition read budget exhausted')
        self.calls+=1
        try:
            with self.http.stream(method,url,json=body) as response:
                payload=b''
                for chunk in response.iter_bytes():
                    payload+=chunk
                    if len(payload)>2097152:raise ValueError('Google acquisition response exceeds bound')
                status=response.status_code
            if status!=200:
                return {'state': 'AUTH EXPIRED' if status==401 else 'RATE LIMITED' if status==429 else 'BLOCKED',
                        'http_status':status,'error':'Fixed native read rejected','date_from':start,'date_to':end}
            return {'state':'WORKING','http_status':status,'data':json.loads(payload),
                    'date_from':start,'date_to':end,'observed_at':now.isoformat(),'partial':kind in ('gsc_queries','ads_keywords','ads_search_terms')}
        except httpx.HTTPError:return {'state':'PARTIAL','error':'Native read unavailable'}

    def close(self):self.http.close()
