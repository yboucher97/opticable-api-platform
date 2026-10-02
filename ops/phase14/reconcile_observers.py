#!/usr/bin/env python3
"""Explicit local observer reconciliation after complete GET-only readback.

Retain the saved delta cursor and immutable watch history. No watch creation,
renewal, credential replacement, business transport or event replay is performed.
Default is a read-only probe; --commit requires a root manual session.
"""
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--commit',action='store_true')
    args=parser.parse_args()
    if os.geteuid()!=0:raise PermissionError('Manual root session required')
    root=Path('/opt/opticable-api-platform')
    pid=subprocess.check_output(['systemctl','show','opticable-workflow-api','-p','MainPID','--value'],text=True).strip()
    for value in Path('/proc/'+pid+'/environ').read_bytes().split(b'\0'):
        if b'=' in value:
            key,val=value.split(b'=',1);os.environ[key.decode()]=val.decode()
    sys.path.insert(0,str(root/'apps/workflow-api'))
    from workflow.config import load_settings
    from workflow.zoho_gateway import ZohoGatewayClient
    from workflow.zoho_oauth import ZohoOAuthManager
    from workflow.automation.crm_delta import CrmLeadDeltaAdapter
    from workflow.automation.store import AutomationStore
    from workflow.automation.desired_journal import DesiredJournal,resource_key
    from workflow.automation.desired_state import DesiredStateDocument
    from workflow.automation.reconcilers.zoho_notification import ZohoCrmNotificationReconciler
    import yaml
    settings=load_settings();client=ZohoGatewayClient(settings.zoho_gateway,ZohoOAuthManager(settings.zoho_oauth))
    store=AutomationStore(settings.automation.db_path);journal=DesiredJournal(store)
    with store._connect() as db:
        cp=dict(db.execute("SELECT * FROM automation_sync_checkpoints WHERE provider='zoho_crm' AND stream='Leads' AND mode='incremental'").fetchone())
    page=CrmLeadDeltaAdapter(client,cp['source_account']).fetch(cp['cursor'],None,mode='incremental',limit=100)
    doc=DesiredStateDocument.model_validate(json.loads((root/'apps/workflow-api/config/automation/desired-state/zoho-crm-notification.template.json').read_text()))
    resource=doc.resources[0];adapter=ZohoCrmNotificationReconciler(client);adapter.bind_journal(journal)
    current=adapter.read(resource);desired=adapter.plan(resource).desired
    if not current or any(current[k]!=desired[k] for k in desired if k!='expiry'):
        raise ValueError('Native binding or provider options differ; no local reconciliation allowed')
    expiry=datetime.fromisoformat(current['expiry'])
    if not datetime.now(timezone.utc)<expiry:raise ValueError('Provider channel expired')
    if journal.unresolved(resource_key(resource)):raise ValueError('Unresolved watch intent must be reconciled separately')
    result={'schema':1,'at':datetime.now(timezone.utc).isoformat(),'commit':args.commit,
            'delta_probe_items':page.fetched_items,'delta_cursor_preserved':True,
            'checkpoint_revision_before':cp['revision'],'checkpoint_status_before':cp['status'],
            'configured_expiry':os.environ['OPTIBRAIN_PHASE5_CRM_CHANNEL_EXPIRY'],
            'provider_expiry':current['expiry'],'provider_mutations':0,'credentials_rotated':False}
    if args.commit:
        control=json.loads(Path('/etc/optibrain/mutation-control.json').read_text())
        if control.get('test_writes_enabled') is not False or control.get('real_canary_allowed') is not False:
            raise ValueError('Universal writes must remain disabled')
        evidence=Path('/var/lib/optibrain/phase14/observer-reconciliation')
        evidence.mkdir(parents=True,mode=0o700,exist_ok=True)
        env=Path('/etc/opticable-workflow-api.env');web=Path(os.environ['OPTIBRAIN_WEBHOOK_CONFIG'])
        old_env=env.read_text();old_web=web.read_text()
        for path,text in [(env,old_env),(web,old_web)]:
            before=evidence/(path.name+'.before')
            if not before.exists():before.write_text(text);before.chmod(0o600)
        rows=old_env.splitlines();key='OPTIBRAIN_PHASE5_CRM_CHANNEL_EXPIRY'
        indexes=[i for i,line in enumerate(rows) if line.startswith(key+'=')]
        if len(indexes)!=1:raise ValueError('Expiry configuration ambiguous')
        rows[indexes[0]]=key+'='+current['expiry']
        updated='\n'.join(rows)+'\n'
        config=yaml.safe_load(old_web)
        config['phase5-crm-leads']['expires_at']=current['expiry']
        try:
            temp=env.with_name('.phase14-env.tmp');temp.write_text(updated);temp.chmod(env.stat().st_mode & 0o777);os.replace(temp,env)
            web.write_text(json.dumps(config,indent=2)+'\n')
            os.environ[key]=current['expiry']
            # Add a new observation under the reconciled binding; never edit old evidence.
            adapter.remember(resource,current)
            journal.record('native_status',resource_key(resource),{'status':'verified','local_configuration_reconciled':True},'phase14-manual-readback')
            with store._connect() as db:
                db.execute('BEGIN IMMEDIATE')
                changed=db.execute("UPDATE automation_sync_checkpoints SET status='idle',failures=0,last_error=NULL,next_attempt_at=0,revision=revision+1,updated_at=? WHERE provider=? AND source_account=? AND stream=? AND mode=? AND revision=? AND status='failed' AND last_error='authentication_failed' AND lease_token IS NULL",
                    (datetime.now(timezone.utc).isoformat(),cp['provider'],cp['source_account'],cp['stream'],cp['mode'],cp['revision'])).rowcount
                if cp['status']=='failed' and changed!=1:raise ValueError('Checkpoint changed; retry only a fresh probe')
                db.execute('INSERT INTO automation_audit(at,category,action,actor,target,success,metadata_json) VALUES(?,?,?,?,?,?,?)',
                    (datetime.now(timezone.utc).isoformat(),'delta_sync','authentication_reconciled','phase14-manual-readback','Leads',1,
                     json.dumps({'prior_revision':cp['revision'],'cursor_preserved':True,'probe_items':page.fetched_items,'provider_mutations':0})))
            subprocess.run(['systemctl','restart','opticable-workflow-api.service'],check=True,timeout=30)
        except Exception:
            env.write_text(old_env);web.write_text(old_web)
            subprocess.run(['systemctl','restart','opticable-workflow-api.service'],check=True,timeout=30)
            raise
        result['configuration_hash']=hashlib.sha256(updated.encode()).hexdigest()
        (evidence/'receipt.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))


if __name__=='__main__':main()
