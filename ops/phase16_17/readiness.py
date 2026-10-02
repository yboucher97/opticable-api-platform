#!/usr/bin/env python3
"""Root-only non-leasing queue peek and bounded provider readiness reads."""
from inventory import ROOT, clients
from datetime import datetime, timezone
import json
import os

def main():
    os.umask(0o077)
    settings, zoho, cloudflare = clients()
    from workflow.automation.mutation_control import technical_admin_call
    output = {'at': datetime.now(timezone.utc).isoformat(), 'results': {}}
    def read(name, service, path, query=None, headers=None):
        try:
            response = zoho.request(service, 'GET', path, query=query or {}, headers=headers or {})
            output['results'][name] = response
        except Exception as exc:
            response = getattr(exc, 'response', None)
            output['results'][name] = {'error_type': type(exc).__name__, 'status': getattr(response, 'status_code', None)}
            if response is not None:
                try: output['results'][name]['data'] = response.json()
                except ValueError: pass
    read('workdrive_user', 'zohoapis', '/workdrive/api/v1/users/me', headers={'Accept': 'application/vnd.api+json'})
    read('sign_installation_template', 'sign', '/templates/325018000000115116')
    read('sign_general_template', 'sign', '/templates/325018000000115001')
    read('crm_conversion_options', 'zohoapis', '/crm/v8/Leads/5062683000007880001/__conversion_options')
    for module in ('Leads', 'Contacts', 'Accounts', 'Deals', 'Services', 'Service_Locations'):
        read(module+':custom_views', 'zohoapis', '/crm/v8/settings/custom_views', {'module': module})
    inventory = json.loads((ROOT/'model-inventory.json').read_text())['entries']
    for name, singular, key in (('estimates', 'estimate', 'estimate_id'), ('invoices', 'invoice', 'invoice_id')):
        rows = inventory['books_'+name].get('data', {}).get(name, [])
        if rows: read('books_'+singular+'_detail', 'zohoapis', '/books/v3/'+name+'/'+rows[0][key], {'organization_id':'802337532'})
    path = '/accounts/'+settings.cloudflare.account_id+'/queues/f3f7bddc3a8a445b9553ad8ff154f7c4/messages/peek'
    body = {'batch_size': 100}
    try:
        with technical_admin_call(cloudflare, 'cloudflare', 'POST', path, body):
            result = cloudflare.request(path, method='POST', body=body)
        output['results']['dead_letter_peek'] = result
    except Exception as exc:
        response = getattr(exc, 'response', None)
        output['results']['dead_letter_peek'] = {'error_type':type(exc).__name__, 'status':getattr(response,'status_code', None)}
    path = ROOT/'readiness.json'
    with path.open('x') as stream: json.dump(output, stream, indent=2); stream.write('\n')
    summary = {key:{k:v for k,v in value.items() if k in {'status','error_type','ok'}} for key,value in output['results'].items()}
    peek = output['results'].get('dead_letter_peek', {}).get('data', {})
    if isinstance(peek, dict): summary['peek_count'] = len(peek.get('result', {}).get('messages', [])) if isinstance(peek.get('result'),dict) else None
    print(json.dumps({'saved':str(path), 'summary':summary}, sort_keys=True))

if __name__ == '__main__':
    try: main()
    except Exception as exc: raise SystemExit('Readiness stopped: '+type(exc).__name__)
