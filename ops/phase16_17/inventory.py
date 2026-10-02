#!/usr/bin/env python3
"""Manual bounded GET-only live model inventory; secret values stay in memory."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path('/var/lib/optibrain/phase16-17')
CODE = Path('/opt/opticable-api-platform')

def clients(code=None):
    if os.geteuid()!=0:raise ValueError('Manual root session required')
    pid=subprocess.check_output(['systemctl','show','opticable-workflow-api','-p','MainPID','--value'],text=True).strip()
    if not pid.isdigit() or pid=='0':raise ValueError('API process unavailable')
    for entry in Path('/proc/'+pid+'/environ').read_bytes().split(b'\0'):
        if b'=' in entry:
            key,value=entry.split(b'=',1);os.environ[key.decode()]=value.decode()
    sys.path.insert(0,str((Path(code) if code else CODE)/'apps/workflow-api'))
    from workflow.config import load_settings
    from workflow.zoho_gateway import ZohoGatewayClient
    from workflow.zoho_oauth import ZohoOAuthManager
    from workflow.cloudflare_api import CloudflareApiClient
    settings=load_settings()
    return settings,ZohoGatewayClient(settings.zoho_gateway,ZohoOAuthManager(settings.zoho_oauth)),CloudflareApiClient(settings.cloudflare)

def main():
    os.umask(0o077)
    settings,zoho,cloudflare=clients()
    from workflow.automation.crm_inventory import project
    entries={};count=0
    def get(name,service,path,query=None,kind=None):
        nonlocal count
        count+=1
        if count>70:raise ValueError('Inventory bound exceeded')
        try:
            response=zoho.request(service,'GET',path,query=query or {})
            data=response['data']
            entries[name]=dict(http_status=response['status'],data=project(data,kind) if kind and isinstance(data,dict) else data)
            return data
        except Exception as exc:
            response=getattr(exc,'response',None)
            entries[name]=dict(error_type=type(exc).__name__,http_status=getattr(response,'status_code',None))
            return None
    data=get('crm_modules','zohoapis','/crm/v8/settings/modules',kind='modules')
    if not isinstance(data,dict) or not data.get('modules'):raise ValueError('Canonical module read failed')
    chosen={'Leads','Contacts','Accounts','Deals','Tasks','Cases','Service_Locations','Services',
            'Installations','Installation_X_Services','Quotes','Invoices','Sales_Orders','Purchase_Orders'}
    chosen|={m['api_name'] for m in data['modules'] if m['api_name'].startswith('CustomModule500')}
    for module in sorted(chosen):
        get(module+':fields','zohoapis','/crm/v8/settings/fields',{'module':module},'fields')
        if module not in {'Quotes','Invoices','Sales_Orders','Purchase_Orders','Installation_X_Services'}:
            get(module+':layouts','zohoapis','/crm/v8/settings/layouts',{'module':module},'layouts')
            get(module+':related_lists','zohoapis','/crm/v8/settings/related_lists',{'module':module},'related_lists')
    get('crm_users','zohoapis','/crm/v8/users',{'type':'ActiveUsers'})
    get('crm_conversion_mapping','zohoapis','/crm/v8/settings/conversion_mapping',{'module':'Leads'})
    get('books_organizations','zohoapis','/books/v3/organizations')
    for name in ('estimates','invoices','items'):
        get('books_'+name,'zohoapis','/books/v3/'+name,{'organization_id':'802337532','per_page':20})
    get('sign_templates','sign','/templates')
    get('sign_account','sign','/account')
    get('mail_accounts','mail','/api/accounts')
    get('workdrive_user','zohoapis','/workdrive/api/v1/users/me')
    result=dict(schema=1,at=datetime.now(timezone.utc).isoformat(),provider_reads=count,
                provider_writes=0,entries=entries)
    output=ROOT/'model-inventory.json'
    with output.open('x') as stream:json.dump(result,stream,indent=2);stream.write('\n')
    queues=cloudflare.request('/accounts/'+settings.cloudflare.account_id+'/queues')['data']
    (ROOT/'queue-inventory.json').write_text(json.dumps(queues,indent=2)+'\n')
    summary={name:{k:v for k,v in entry.items() if k!='data'} for name,entry in entries.items()}
    print(json.dumps(dict(saved=str(output),reads=count,writes=0,results=summary),sort_keys=True))

if __name__=='__main__':
    try:main()
    except Exception as exc:raise SystemExit('Inventory stopped: '+type(exc).__name__)
