#!/usr/bin/env python3
"""Manual, fixed-property read-only collection evidence. No conversion upload."""
import json,os,sys
from pathlib import Path
from datetime import datetime,timezone
import httpx
REPO=Path(__file__).resolve().parents[2]
sys.dont_write_bytecode=True
sys.path.insert(0,str(REPO/'ops/phase16_17'))
from inventory import clients

def main():
 if os.geteuid()!=0:raise ValueError('Manual root only')
 os.umask(0o077);s,_,_=clients(REPO)
 from workflow.google_oauth import GoogleOAuthManager
 token=GoogleOAuthManager(s.google_oauth).access_token()
 rows={}
 with httpx.Client(headers={'Authorization':'Bearer '+token},timeout=12) as c:
  base='https://analyticsdata.googleapis.com/v1beta/properties/530093120'
  for key,path,body in [
   ('realtime',':runRealtimeReport',{'dimensions':[{'name':'eventName'}],'metrics':[{'name':'eventCount'}],'limit':'100'}),
   ('realtime_pages',':runRealtimeReport',{'dimensions':[{'name':'unifiedScreenName'}],'metrics':[{'name':'screenPageViews'}],'limit':'20'}),
   ('today',':runReport',{'dateRanges':[{'startDate':'today','endDate':'today'}],'dimensions':[{'name':'eventName'},{'name':'hostName'}],'metrics':[{'name':'eventCount'}],'limit':'100'})]:
   r=c.post(base+path,json=body);rows[key]={'status':r.status_code,**r.json()}
 receipt={'at':datetime.now(timezone.utc).isoformat(),'property':'530093120','reads':rows,'provider_writes':0}
 path=Path('/var/lib/optibrain/completion-remediation-1-2/ga4-collection-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.json')
 path.write_text(json.dumps(receipt,indent=2));print(json.dumps({'receipt':str(path),'results':rows}))

if __name__=='__main__':main()
