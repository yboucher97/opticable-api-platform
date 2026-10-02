#!/usr/bin/env python3
"""Nonleasing dead-letter peek. Never creates consumers, pulls, ACKs or purges.

Cloudflare's consumer pull can enforce retention and expire old entries even
when the caller never ACKs. Historical backlog audits must use peek only.
"""
from inventory import clients,ROOT
from datetime import datetime,timezone
import json
import os

def main():
    os.umask(0o077)
    settings,_,client=clients()
    from workflow.automation.mutation_control import technical_admin_call
    base='/accounts/'+settings.cloudflare.account_id+'/queues/f3f7bddc3a8a445b9553ad8ff154f7c4'
    before=client.request(base)['data']['result']
    body={'batch_size':100}
    with technical_admin_call(client,'cloudflare','POST',base+'/messages/peek',body):
        messages=client.request(base+'/messages/peek','POST',body=body)['data']['result']
    after=client.request(base)['data']['result']
    receipt={'schema':1,'at':datetime.now(timezone.utc).isoformat(),'before':before,'peek':messages,'after':after,
        'leases':0,'consumers_created':0,'acknowledgments':0,'explicit_purges':0,'replays':0,
        'limitation':'Provider peek returns at most 100 messages and offers no cursor. Do not use pull to bypass this bound.'}
    path=ROOT/'dead-letter-peek-current.json';path.write_text(json.dumps(receipt,indent=2)+'\n')
    print('Nonleasing peek retained; no consumer, ACK, purge or replay:',path)

if __name__=='__main__':main()
