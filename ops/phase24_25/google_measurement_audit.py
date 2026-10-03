#!/usr/bin/env python3
"""Manual native configuration audit. Ads POST is a fixed SELECT, never a mutate.

No configurable URL/query/body; saved grant must refresh before any reads. Native
provider errors stay private and cannot be interpreted as empty configuration.
"""
import json,os,sys
from datetime import datetime,timezone
from pathlib import Path
REPO=Path(__file__).resolve().parents[2]
sys.dont_write_bytecode=True
sys.path.insert(0,str(REPO/'ops/phase16_17'))
from inventory import clients

def main():
 if os.geteuid()!=0:raise ValueError('Manual root audit required')
 os.umask(0o077)
 from workflow.google_oauth import GoogleOAuthManager
 from workflow.google_api import GoogleApiClient
 import httpx
 settings,_,_=clients(REPO);oauth=GoogleOAuthManager(settings.google_oauth)
 token=oauth.access_token() # Fail here once; never repeat seven rejected refreshes.
 scopes=str((oauth.load_saved_credentials() or {}).get('scope','')).split()
 result={'schema':1,'at':datetime.now(timezone.utc).isoformat(),'read_only':True,'configuration_mutations':0,'granted_scopes':scopes,'native':{}}
 google=GoogleApiClient(oauth)
 reads=[('analytics_admin_v1beta','accountSummaries')]
 for pid in ('530093120','530619880'):
  reads.extend(('analytics_admin_v1beta','properties/'+pid+suffix) for suffix in ('','/dataStreams','/keyEvents','/dataFilters'))
 reads.append(('tagmanager','accounts'))
 for service,path in reads:
  try:result['native'][service+':'+path]={'state':'PROVEN','response':google.request(service,'GET',path)}
  except Exception as exc:result['native'][service+':'+path]={'state':'UNAVAILABLE','error_class':type(exc).__name__}
 if 'https://www.googleapis.com/auth/adwords' in scopes:
  queries={
   'actions':'SELECT conversion_action.id, conversion_action.name, conversion_action.status, conversion_action.type, conversion_action.primary_for_goal, conversion_action.counting_type, conversion_action.category, conversion_action.value_settings.default_value, conversion_action.value_settings.default_currency_code, conversion_action.value_settings.always_use_default_value FROM conversion_action',
   'custom_goals':'SELECT custom_conversion_goal.id, custom_conversion_goal.name, custom_conversion_goal.status, custom_conversion_goal.conversion_actions FROM custom_conversion_goal',
   'customer':'SELECT customer.id, customer.descriptive_name, customer.currency_code, customer.time_zone, customer.conversion_tracking_setting.google_ads_conversion_customer, customer.conversion_tracking_setting.accepted_customer_data_terms, customer.conversion_tracking_setting.enhanced_conversions_for_leads_enabled FROM customer'}
  for name,query in queries.items():
   response=httpx.post('https://googleads.googleapis.com/v25/customers/6808491878/googleAds:search',
    json={'query':query},headers={'Authorization':'Bearer '+token},timeout=30,follow_redirects=False)
   result['native']['ads:'+name]={'state':'PROVEN' if response.status_code==200 else 'UNAVAILABLE','http_status':response.status_code,
    'response':response.json() if response.status_code==200 else {'error_class':'Native read rejected'}}
 stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ');path=Path('/var/lib/optibrain/phase24-25')/('google-native-'+stamp+'.json')
 with path.open('x') as f:json.dump(result,f,indent=2)
 print(json.dumps({'state':'READ_AUDIT_COMPLETE','receipt':str(path),'native_reads':len(result['native']),
  'proven':sum(v['state']=='PROVEN' for v in result['native'].values()),'mutations':0,'scope_names':scopes}))

if __name__=='__main__':main()
