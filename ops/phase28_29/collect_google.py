#!/usr/bin/env python3
"""Manual bounded native measurement collection; credentials never enter evidence."""
from datetime import datetime, timezone
import json, os, sys
from pathlib import Path
REPO=Path(__file__).resolve().parents[2]
sys.dont_write_bytecode=True
sys.path.insert(0,str(REPO/'ops/phase16_17'))
from inventory import clients

def main():
    if os.geteuid()!=0:raise ValueError('Manual root collection required')
    os.umask(0o077);settings,_,_=clients(REPO)
    from workflow.google_oauth import GoogleOAuthManager
    from workflow.automation.acquisition_sources import GoogleAcquisitionReader
    now=datetime.now(timezone.utc)
    kinds=('gsc_sites','gsc_sitemaps','gsc_queries','gsc_daily','gsc_devices','gsc_countries',
           'ga4_main','ga4_other','ga4_collection','ads_customer','ads_campaigns','ads_keywords','ads_search_terms','ads_geo_constants')
    rows={};reader=None
    try:
        token=GoogleOAuthManager(settings.google_oauth).access_token()
        reader=GoogleAcquisitionReader(token)
        for kind in kinds:rows[kind]=reader.read(kind,now=now)
    except Exception as exc:rows['collection']={'state':'PARTIAL','error_class':type(exc).__name__}
    finally:
        if reader:reader.close()
    result={'schema':1,'at':now.isoformat(),'read_only':True,'provider_mutations':0,'reads':rows}
    root=Path('/var/lib/optibrain/acquisition-intelligence');root.mkdir(parents=True,exist_ok=True,mode=0o700)
    receipt=root/('google-'+now.strftime('%Y%m%dT%H%M%SZ')+'.json')
    receipt.write_text(json.dumps(result,indent=2));os.chmod(receipt,0o600)
    print(json.dumps({'receipt':str(receipt),'reads':len(rows),'states':{k:v['state'] for k,v in rows.items()},'mutations':0}))

if __name__=='__main__':main()
