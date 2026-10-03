#!/usr/bin/env python3
"""Native provider schema test only: synthetic IDs, hardcoded validateOnly=True.

No live option, business event registration, effect claim or policy activation.
The genuine-event exporter continues to reject every TEST/synthetic outcome.
"""
import argparse,json,os,sys
from datetime import datetime,timezone
from hashlib import sha256
from pathlib import Path

REPO=Path(__file__).resolve().parents[2]
sys.dont_write_bytecode=True
sys.path.insert(0,str(REPO/'apps/workflow-api'))
sys.path.insert(0,str(REPO/'ops/phase16_17'))
from inventory import clients
from workflow.google_oauth import GoogleOAuthManager
from workflow.automation.lifecycle_control import trusted_json
from workflow.automation.conversion_export import ROOT,SCOPE,BASE,digest

def main():
 if os.geteuid()!=0:raise ValueError('Manual root provider validation required')
 os.umask(0o077)
 p=argparse.ArgumentParser();p.add_argument('--native-audit',required=True);a=p.parse_args()
 receipt=Path(a.native_audit)
 if receipt.resolve().parent!=Path('/var/lib/optibrain/phase24-25'):
  raise ValueError('Protected native audit receipt required')
 audit=trusted_json(receipt,1048576)
 if not 0<=(datetime.now(timezone.utc)-datetime.fromisoformat(audit['at'])).total_seconds()<3600:
  raise ValueError('Fresh native configuration required')
 native=audit['native']
 for key in ('ads:actions','ads:custom_goals','ads:customer'):
  if native[key]['state']!='PROVEN':raise ValueError('Native destination/account/goal proof missing')
 goals=native['ads:custom_goals']['response'].get('results',[])
 used={x for row in goals for x in row['customConversionGoal'].get('conversionActions',[]) if row['customConversionGoal'].get('status')!='REMOVED'}
 customer=native['ads:customer']['response']['results'][0]['customer']
 if customer['id']!='6808491878' or customer['conversionTrackingSetting']['googleAdsConversionCustomer']!='customers/6808491878':
  raise ValueError('Wrong native conversion account')
 settings,_,_=clients(REPO);oauth=GoogleOAuthManager(settings.google_oauth)
 if SCOPE not in str((oauth.load_saved_credentials() or {}).get('scope','')).split():raise ValueError('Data Manager consent missing')
 import httpx
 result={'schema':1,'at':datetime.now(timezone.utc).isoformat(),'validate_only':True,'executed_events':0,'real_uploads':0,
         'test_events_ingested':0,'native_audit':str(receipt),'native_audit_sha256':sha256(receipt.read_bytes()).hexdigest(),'families':{}}
 kinds={'QUALIFIED_LEAD':('qualified_lead',0),'CONVERTED_LEAD':('estimate_accepted',123.45),'PURCHASE':('invoice_paid',123.45)}
 for category,(kind,value) in kinds.items():
  matches=[r['conversionAction'] for r in native['ads:actions']['response'].get('results',[])
           if r['conversionAction'].get('type')=='UPLOAD_CLICKS' and r['conversionAction'].get('status')=='ENABLED'
           and r['conversionAction'].get('category')==category and r['conversionAction'].get('primaryForGoal') is False]
  if len(matches)!=1:raise ValueError('One unambiguous secondary destination required')
  action=matches[0]
  if action['resourceName'] in used or action['valueSettings'].get('alwaysUseDefaultValue') is not False:
   raise ValueError('Bidding/default-value conflict')
  destination={'operatingAccount':{'accountType':'GOOGLE_ADS','accountId':customer['id']},
   'loginAccount':{'accountType':'GOOGLE_ADS','accountId':customer['id']},'productDestinationId':action['id']}
  event={'transactionId':digest({'test':'OPTIBRAIN_PROVIDER_VALIDATION_ONLY','kind':kind,'action':action['id']}),
   'eventTimestamp':datetime.now(timezone.utc).isoformat(),'eventSource':'WEB',
   'adIdentifiers':{'gclid':'OPTIBRAIN_TEST_VALIDATION_ONLY'},'consent':{'adUserData':'CONSENT_GRANTED','adPersonalization':'CONSENT_DENIED'},
   'conversionValue':value,'currency':customer['currencyCode']}
  body={'destinations':[destination],'events':[event],'validateOnly':True}
  # This testing endpoint validates and does NOT execute (Google's REST contract).
  # No flag/caller payload can turn this diagnostic into the live exporter.
  response=httpx.post(BASE+'events:ingest',json=body,headers={'Authorization':'Bearer '+oauth.access_token()},timeout=30,follow_redirects=False)
  reply=response.json()
  result['families'][kind]={'action_id':action['id'],'body_sha256':digest(body),'http_status':response.status_code,
   'response':reply,'passed':response.status_code==200 and not reply.get('fieldWarnings')}
 result['passed']=all(v['passed'] for v in result['families'].values())
 output=ROOT/'validation'/('native-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.json')
 with output.open('x') as f:json.dump(result,f,indent=2)
 print(json.dumps({'state':'NATIVE_VALIDATION_PASS' if result['passed'] else 'NATIVE_VALIDATION_ISSUE','receipt':str(output),
  'executed_events':0,'families':result['families']}))
 if not result['passed']:raise SystemExit(1)

if __name__=='__main__':main()
