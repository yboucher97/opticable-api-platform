#!/usr/bin/env python3
"""GET-only proof for exact retained version-review conflicts, without run redrive.

Original failed runs/events remain immutable evidence. Only a root display
resolution receipt is added after every copied-store observation reuses an
already committed review and emits no new event. Never executes a workflow.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime,timezone
from types import SimpleNamespace


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--commit',action='store_true');args=parser.parse_args()
    if os.geteuid()!=0:raise PermissionError('Manual root required')
    os.umask(0o077)
    prod=Path('/opt/opticable-api-platform/apps/workflow-api')
    pid=subprocess.check_output(['systemctl','show','opticable-workflow-api','-p','MainPID','--value'],text=True).strip()
    for value in Path('/proc/'+pid+'/environ').read_bytes().split(b'\0'):
        if b'=' in value:
            key,data=value.split(b'=',1);os.environ[key.decode()]=data.decode()
    sys.path.insert(0,str(prod))
    from workflow.config import load_settings
    from workflow.zoho_gateway import ZohoGatewayClient
    from workflow.zoho_oauth import ZohoOAuthManager
    from workflow.automation.store import AutomationStore
    from workflow.automation.events import EventLedger
    from workflow.automation.providers.crm_leads import register_crm_lead_actions
    from workflow.automation.provider_usage import ProviderUsage
    settings=load_settings();client=ZohoGatewayClient(settings.zoho_gateway,ZohoOAuthManager(settings.zoho_oauth))
    with tempfile.TemporaryDirectory(prefix='phase14-review-proof-') as tmp:
        source=sqlite3.connect(settings.automation.db_path.as_uri()+'?mode=ro',uri=True)
        destination=sqlite3.connect(Path(tmp)/'copy.db');source.backup(destination);source.close();destination.close()
        store=AutomationStore(Path(tmp)/'copy.db');ledger=EventLedger(store)
        with store._connect() as db:
            rows=db.execute("SELECT DISTINCT r.run_id,r.event_id FROM automation_runs r JOIN automation_run_steps s ON s.run_id=r.run_id "
                "WHERE r.status='failed' AND r.workflow_id='opticable.crm.lead-observe' AND s.action='crm.lead.observe' AND s.error='EventConflict'").fetchall()
            before=db.execute('SELECT COUNT(*) FROM automation_events').fetchone()[0]
        if not 1<=len(rows)<=20:raise ValueError('Exact read-observer conflict bound requires manual inspection')
        actions={};engine=SimpleNamespace(register_action=lambda name,fn,**kwargs:actions.update({name:fn}))
        register_crm_lead_actions(engine,client,store)
        with ProviderUsage(None,'manual:read-observer-reconciliation') as usage:
            for row in rows:
                envelope=ledger.inspect(row['event_id'])['envelope']
                outcome=actions['crm.lead.observe']({'event':envelope},None)
                if not outcome.get('review_event_ids'):raise ValueError('Existing version review not proven')
        with store._connect() as db:after=db.execute('SELECT COUNT(*) FROM automation_events').fetchone()[0]
        if before!=after or usage.summary['calls']['crm_write'] or usage.summary['calls']['mail_mutation']:
            raise ValueError('Read-only existing-review proof incomplete')
        value={'schema':1,'at':datetime.now(timezone.utc).isoformat(),'producer_sha256':hashlib.sha256((prod/'workflow/automation/providers/crm_leads.py').read_bytes()).hexdigest(),
               'run_ids':[row['run_id'] for row in rows],'provider_mutations':0,'new_events':0,'provider_usage':usage.summary,
               'reason':'Same provider record versions have existing immutable reviews; historical schema/time-dependent decisions are not rewritten'}
        if args.commit:
            directory=Path('/var/lib/optibrain/phase14/observer-reconciliation');directory.mkdir(mode=0o700,parents=True,exist_ok=True)
            fd,name=tempfile.mkstemp(prefix='.review-resolution-',dir=directory)
            with os.fdopen(fd,'w') as stream:json.dump(value,stream,sort_keys=True);stream.write('\n');stream.flush();os.fsync(stream.fileno())
            os.replace(name,directory/'lead-review-resolution.json')
        print(json.dumps({'reconciled_read_only_runs':len(rows),'new_events':0,'provider_mutations':0,'commit':args.commit,'calls':usage.summary['calls']}))


if __name__=='__main__':main()
