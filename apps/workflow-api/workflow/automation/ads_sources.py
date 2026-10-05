"""Fixed, bounded reporting-only Ads inventory. No mutate/upload transport."""
from datetime import timedelta
from time import monotonic
from zoneinfo import ZoneInfo
import json
import httpx

ACCOUNT = '6808491878'
ENDPOINT = 'https://googleads.googleapis.com/v25/customers/'+ACCOUNT+'/googleAds:search'


def queries(now):
    end = now.astimezone(ZoneInfo('America/Toronto')).date()-timedelta(days=1)
    start = end-timedelta(days=89)
    span = f"segments.date BETWEEN '{start}' AND '{end}'"
    metric = 'metrics.impressions, metrics.clicks, metrics.cost_micros, metrics.ctr, metrics.average_cpc, metrics.conversions, metrics.conversions_value'
    return {
        'customer': 'SELECT customer.id, customer.descriptive_name, customer.currency_code, customer.time_zone, customer.conversion_tracking_setting.google_ads_conversion_customer FROM customer',
        'campaigns': 'SELECT campaign.id, campaign.name, campaign.status, campaign.advertising_channel_type, campaign.bidding_strategy_type, campaign.campaign_budget, campaign.network_settings.target_google_search, campaign.network_settings.target_search_network, campaign.network_settings.target_content_network, campaign.geo_target_type_setting.positive_geo_target_type, campaign.geo_target_type_setting.negative_geo_target_type FROM campaign LIMIT 1000',
        'budgets': 'SELECT campaign_budget.id, campaign_budget.name, campaign_budget.amount_micros, campaign_budget.status, campaign_budget.explicitly_shared FROM campaign_budget LIMIT 1000',
        'criteria': 'SELECT campaign.id, campaign_criterion.criterion_id, campaign_criterion.type, campaign_criterion.negative, campaign_criterion.status, campaign_criterion.location.geo_target_constant, campaign_criterion.language.language_constant, campaign_criterion.keyword.text, campaign_criterion.keyword.match_type FROM campaign_criterion LIMIT 2000',
        'ad_groups': 'SELECT campaign.id, ad_group.id, ad_group.name, ad_group.status, ad_group.type, ad_group.cpc_bid_micros FROM ad_group LIMIT 1000',
        'keywords': 'SELECT campaign.id, ad_group.id, ad_group_criterion.criterion_id, ad_group_criterion.status, ad_group_criterion.negative, ad_group_criterion.keyword.text, ad_group_criterion.keyword.match_type, ad_group_criterion.cpc_bid_micros FROM ad_group_criterion WHERE ad_group_criterion.type = KEYWORD LIMIT 2000',
        'ads': 'SELECT campaign.id, ad_group.id, ad_group_ad.status, ad_group_ad.ad.id, ad_group_ad.ad.type, ad_group_ad.ad.final_urls, ad_group_ad.ad.responsive_search_ad.headlines, ad_group_ad.ad.responsive_search_ad.descriptions, ad_group_ad.ad.expanded_text_ad.headline_part1, ad_group_ad.ad.expanded_text_ad.headline_part2, ad_group_ad.ad.expanded_text_ad.description FROM ad_group_ad LIMIT 1000',
        'assets': 'SELECT asset.id, asset.name, asset.type, asset.final_urls, asset.text_asset.text, asset.sitelink_asset.link_text, asset.sitelink_asset.description1, asset.callout_asset.callout_text FROM asset LIMIT 1000',
        'campaign_assets': 'SELECT campaign.id, campaign_asset.asset, campaign_asset.field_type, campaign_asset.status FROM campaign_asset LIMIT 1000',
        'negative_lists': 'SELECT shared_set.id, shared_set.name, shared_set.type, shared_set.status FROM shared_set LIMIT 1000',
        'shared_negatives': 'SELECT shared_set.id, shared_criterion.criterion_id, shared_criterion.keyword.text, shared_criterion.keyword.match_type FROM shared_criterion LIMIT 2000',
        'campaign_negative_lists': 'SELECT campaign.id, campaign_shared_set.shared_set, campaign_shared_set.status FROM campaign_shared_set LIMIT 1000',
        'conversion_actions': 'SELECT conversion_action.id, conversion_action.name, conversion_action.status, conversion_action.type, conversion_action.primary_for_goal, conversion_action.category, conversion_action.counting_type, conversion_action.value_settings.default_value, conversion_action.value_settings.default_currency_code FROM conversion_action LIMIT 1000',
        'customer_goals': 'SELECT customer_conversion_goal.category, customer_conversion_goal.origin, customer_conversion_goal.biddable FROM customer_conversion_goal LIMIT 1000',
        'campaign_goals': 'SELECT campaign.id, campaign_conversion_goal.category, campaign_conversion_goal.origin, campaign_conversion_goal.biddable FROM campaign_conversion_goal LIMIT 1000',
        'goal_config': 'SELECT campaign.id, conversion_goal_campaign_config.goal_config_level, conversion_goal_campaign_config.custom_conversion_goal FROM conversion_goal_campaign_config LIMIT 1000',
        'custom_goals': 'SELECT custom_conversion_goal.id, custom_conversion_goal.name, custom_conversion_goal.status, custom_conversion_goal.conversion_actions FROM custom_conversion_goal LIMIT 1000',
        'conversion_metrics_90d': 'SELECT segments.conversion_action, segments.conversion_action_name, metrics.conversions, metrics.all_conversions, metrics.conversions_value, metrics.all_conversions_value FROM customer WHERE '+span+' LIMIT 1000',
        'conversion_metrics_history': "SELECT segments.conversion_action, segments.conversion_action_name, metrics.conversions, metrics.all_conversions, metrics.conversions_value, metrics.all_conversions_value FROM customer WHERE segments.date BETWEEN '2024-01-01' AND '"+str(end)+"' LIMIT 1000",
        'performance_90d': 'SELECT campaign.id, campaign.name, campaign.status, '+metric+' FROM campaign WHERE '+span+' LIMIT 1000',
        'search_terms_90d': 'SELECT campaign.id, ad_group.id, search_term_view.search_term, search_term_view.status, '+metric+' FROM search_term_view WHERE '+span+' LIMIT 2000',
        'performance_history': "SELECT campaign.id, campaign.name, campaign.status, "+metric+f" FROM campaign WHERE segments.date BETWEEN '2024-01-01' AND '{end}' LIMIT 1000",
        'search_terms_history': "SELECT campaign.id, ad_group.id, search_term_view.search_term, search_term_view.status, "+metric+f" FROM search_term_view WHERE segments.date BETWEEN '2024-01-01' AND '{end}' LIMIT 2000",
        'geo_names': "SELECT geo_target_constant.resource_name, geo_target_constant.name, geo_target_constant.canonical_name, geo_target_constant.country_code, geo_target_constant.target_type FROM geo_target_constant WHERE geo_target_constant.country_code = 'CA' AND geo_target_constant.name IN ('Canada','Quebec','Laval','Montreal','Montréal','Terrebonne','Blainville','Boisbriand','Mascouche','Saint-Eustache','Saint-Jérôme','Saint-Jerome') LIMIT 100",
        'languages': "SELECT language_constant.resource_name, language_constant.name, language_constant.code FROM language_constant WHERE language_constant.code IN ('fr','en') LIMIT 100",
    }, str(start), str(end)


class AdsInventoryReader:
    def __init__(self, token, *, transport=None, max_calls=25):
        if not token: raise ValueError('Google OAuth unavailable')
        self.http = httpx.Client(headers={'Authorization':'Bearer '+token}, transport=transport,
                                 timeout=httpx.Timeout(12, connect=3), follow_redirects=False)
        self.calls = 0; self.limit = min(max_calls,25); self.started = monotonic()

    def read(self, kind, *, now):
        fixed, start, end = queries(now)
        if kind not in fixed: raise ValueError('Only fixed Ads reporting SELECTs allowed')
        if self.calls >= self.limit or monotonic()-self.started > 180:
            raise ValueError('Ads reporting budget exhausted')
        self.calls += 1
        try:
            with self.http.stream('POST', ENDPOINT, json={'query':fixed[kind]}) as response:
                data=b''
                for chunk in response.iter_bytes():
                    data+=chunk
                    if len(data)>2097152: raise ValueError('Ads read exceeds 2 MiB bound')
                payload=json.loads(data); status=response.status_code
            if status!=200:
                # Preserve precise provider error codes, never echo credentials/messages.
                codes=[e.get('errorCode',{}) for d in payload.get('error',{}).get('details',[]) for e in d.get('errors',[])]
                return {'state':'AUTHORIZATION_FAILURE' if status==403 else 'TOKEN_FAILURE' if status==401 else 'RATE_LIMIT' if status==429 else 'API_LIMITATION',
                        'http_status':status,'error_codes':codes,'observed_at':now.isoformat(),'provider_writes':0}
            return {'state':'WORKING','data':payload,'observed_at':now.isoformat(),
                    'date_from':'2024-01-01' if kind.endswith('history') else start,
                    'date_to':end,'complete':not bool(payload.get('nextPageToken')) and len(payload.get('results',[]))<int(fixed[kind].rsplit('LIMIT ',1)[-1]) if 'LIMIT ' in fixed[kind] else not bool(payload.get('nextPageToken')),
                    'provider_writes':0}
        except (httpx.HTTPError, json.JSONDecodeError):
            return {'state':'TRANSIENT_PROVIDER_FAILURE','provider_writes':0}

    def close(self): self.http.close()
