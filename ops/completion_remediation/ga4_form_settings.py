#!/usr/bin/env python3
"""Manual owner-authorized telemetry setting; no Ads or business mutation path."""
from datetime import datetime,timezone
from pathlib import Path
import json,os,sys
import httpx
REPO=Path(__file__).resolve().parents[2]
sys.dont_write_bytecode=True
sys.path.insert(0,str(REPO/'ops/phase16_17'))
from inventory import clients
URL='https://analyticsadmin.googleapis.com/v1alpha/properties/530093120/dataStreams/14233342137/enhancedMeasurementSettings'

def main():
    if os.geteuid()!=0 or sys.argv[1:] not in ([],['--apply']):raise ValueError('Manual root inspection or --apply only')
    os.umask(0o077)
    settings,_,_=clients(REPO)
    from workflow.google_oauth import GoogleOAuthManager
    with httpx.Client(headers={'Authorization':'Bearer '+GoogleOAuthManager(settings.google_oauth).access_token()},timeout=8,follow_redirects=False) as client:
        r=client.get(URL);r.raise_for_status();before=r.json()
        receipt={'at':datetime.now(timezone.utc).isoformat(),'before':before,'mutation_attempted':False}
        if sys.argv[1:]==['--apply'] and before.get('formInteractionsEnabled') is True:
            # Exact field mask only. No wildcard, retries, conversion actions,
            # monetary value, identities, campaign or property-selection inputs.
            receipt['mutation_attempted']=True
            try:
                response=client.patch(URL,params={'updateMask':'form_interactions_enabled'},json={'formInteractionsEnabled':False})
                receipt['status']=response.status_code
            except httpx.HTTPError:receipt['status']='ACK UNKNOWN; GET RECONCILIATION ONLY'
            r=client.get(URL);r.raise_for_status();after=r.json();receipt['after']=after
            receipt['verified']=after.get('formInteractionsEnabled',False) is False and {k:v for k,v in after.items() if k!='formInteractionsEnabled'}=={k:v for k,v in before.items() if k!='formInteractionsEnabled'}
            if not receipt['verified']:raise ValueError('Telemetry setting requires reconciliation; no retry')
        path=Path('/var/lib/optibrain/completion-remediation-1-2/ga4-form-settings-'+('applied' if sys.argv[1:] else 'before')+'.json')
        path.write_text(json.dumps(receipt,indent=2))
        print(json.dumps({'receipt':str(path),'automatic_forms_before':before.get('formInteractionsEnabled'),
            'mutation_attempted':receipt['mutation_attempted'],'verified':receipt.get('verified')}))

if __name__=='__main__':main()
