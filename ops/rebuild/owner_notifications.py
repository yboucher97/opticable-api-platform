#!/usr/bin/env python3
"""Owner-only migration operator alerts, explicitly authorized 2026-11-01.

Separate from customer communication/runtime authority. Fixed mailbox and HTTPS
origin, no CC/BCC, attachments or arbitrary body/recipients. One durable intent
per incident; ambiguous delivery is GET-only reconciled, never resent.
"""
import argparse
from dataclasses import replace
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time
import httpx
from common import atomic_json,digest,env_file,file_hash,private_file,require,trusted_manifest
from durable_migration import Control,load_profile,profile_binding,timestamp

OWNER='yboucher@opticable.ca'
ACCOUNT='1083319000000008002'
BASE='https://mail.zoho.com'
MAX_ALERT_INCIDENTS=16
KINDS={'TEST','BLOCKED','CRITICAL','ROLLBACK','SUCCESS'}
AUTHORITY_REFERENCE='owner-request:2026-11-01:AUTONOMOUS-MIGRATION:DURABLE-RECOVERY-NOTIFICATIONS:section-4'


def body_for(kind,run_id,state,report_ref):
    require(kind in KINDS,'invalid_alert_category')
    require(re.fullmatch(r'[A-Za-z0-9_-]{1,100}',run_id) is not None,'invalid_run_id')
    stage=state.get('current_stage','PREPARED')
    require(stage in {'PREPARED','APPROVED','FORMS_HELD','CAPTURED','INTAKE_RELEASED','WORKER_HELD','CRM_VERIFIED','QUEUE_HELD','SOURCE_FROZEN','RECOVERY_VERIFIED','TARGET_SYNCHRONIZED','PRIVATE_VERIFIED','CUTOVER','INTAKE_VERIFIED','COMPLETE'},'invalid_stage')
    authority=state.get('authority','OLD');require(authority in {'OLD','NEW'},'invalid_authority')
    reference='/home/optibrain/optibrain-migration-progress-20261101.txt'
    require(report_ref==reference,'fixed_report_reference_required')
    detail={'BLOCKED':'Execution stopped at an approval or safety boundary. Consult the durable current-stage report for exact live intake and authority; no uncertain effect is retried.', 'CRITICAL':'A monitored migration safety condition requires attention. Check the disk/hold/authority evidence in the current report; uncertain effects are contained, never blindly retried.', 'ROLLBACK':'A rollback or containment checkpoint was recorded. NEW data is retained; consult the exact verified authority in the report.', 'SUCCESS':'Consult the independently verified completion evidence and final authority in the report.'}.get(kind,'')
    extra=('What happened: '+detail+'\n' if detail else '')
    return ('OptiBrain migration '+kind+'\n'+extra+'Execution: '+run_id+'\nStage: '+stage+
      '\nAuthoritative server recorded: '+authority+
      '\nPreserved: existing databases, learning, audit history, backups and prior checkpoints.\n'+
      ('This is the single authorized owner-only technical delivery test. No maintenance is started.\n' if kind=='TEST' else '')+
      'Production availability and automatic recovery: consult the current independently checked report; this email does not assert unverified health.\n'+
      'Owner next action: '+('No action for this test.' if kind=='TEST' else 'Review the exact blocker and separately bound approval scopes in the report.')+
      '\nReport: '+reference+'\nNo customer communications or business execution authority is enabled.\n')


class Mail:
    def __init__(self):
        sys.path.insert(0,'/opt/opticable-api-platform/apps/workflow-api')
        from workflow.config import load_settings
        from workflow.zoho_oauth import ZohoOAuthManager
        os.environ.update(env_file('/etc/opticable-workflow-api.env'))
        s=load_settings();self.tmp=tempfile.TemporaryDirectory(prefix='migration-owner-mail-',dir=('/run/optibrain-migration-watchdog' if Path('/run/optibrain-migration-watchdog').is_dir() else '/run/optibrain-migration'))
        root=Path(self.tmp.name);credentials=root/'credentials.json';shutil.copyfile(s.zoho_oauth.credentials_path,credentials);credentials.chmod(0o600)
        cache=root/'access-cache.json'
        if s.zoho_oauth.access_cache_path and s.zoho_oauth.access_cache_path.exists():
            shutil.copyfile(s.zoho_oauth.access_cache_path,cache);cache.chmod(0o600)
        self.oauth=ZohoOAuthManager(replace(s.zoho_oauth,credentials_path=credentials,access_cache_path=cache))

    def request(self,method,path,*,params=None,body=None):
        require(path.startswith('/api/accounts/'+ACCOUNT) and not any(c in path for c in ['\\','\r','\n','..','?','#']),'mail_path_forbidden')
        require(method=='GET' or method=='POST' and path=='/api/accounts/'+ACCOUNT+'/messages','mail_method_forbidden')
        if method=='POST':
            require(set(body)=={'fromAddress','toAddress','subject','content','mailFormat'} and body['fromAddress']==OWNER and body['toAddress']==OWNER and body['mailFormat']=='plaintext','owner_only_mail_required')
        with httpx.Client(timeout=30,follow_redirects=False) as client:
            r=client.request(method,BASE+path,params=params,json=body,headers={'Authorization':'Zoho-oauthtoken '+self.oauth.access_token()})
        require(r.status_code==200,'mail_provider_http_failure')
        value=r.json();require(int(value.get('status',{}).get('code',0))==200,'mail_provider_failure')
        return value.get('data')


def addresses(value):
    return set(re.findall(r'[A-Za-z0-9_.+\-]+@[A-Za-z0-9.\-]+',str(value).lower()))


def delivery(mail,subject,earliest_epoch):
    folders=mail.request('GET','/api/accounts/'+ACCOUNT+'/folders')
    inbox={str(f['folderId']) for f in folders if (str(f.get('folderId')),str(f.get('folderName','')).lower()) in {('1083319000000008014','inbox'),('1083319000000633001','optibrain')}}
    require('1083319000000008014' in inbox,'owner_inbox_identity_unverified')
    rows=mail.request('GET','/api/accounts/'+ACCOUNT+'/messages/search',params={
        'searchKey':'subject:'+subject.split()[-1], 'receivedTime':int((time.time()+60)*1000),
        'start':1,'limit':100,'includeto':'true'})
    for row in rows:
        if row.get('subject')!=subject or str(row.get('folderId')) not in inbox:continue
        folder=str(row['folderId']);mid=str(row['messageId'])
        details=mail.request('GET','/api/accounts/'+ACCOUNT+'/folders/'+folder+'/messages/'+mid+'/details')
        require(details['subject']==subject and addresses(details.get('fromAddress'))=={OWNER} and addresses(details.get('toAddress'))=={OWNER},'delivered_owner_identity_mismatch')
        require(not addresses(details.get('ccAddress')) and not addresses(details.get('bccAddress')),'unexpected_mail_recipient')
        received=int(details.get('receivedTime') or details.get('receivedtime') or 0)/1000
        require(received>=earliest_epoch-10,'delivered_message_too_old')
        return {'state':'DELIVERED','account_id':ACCOUNT,'recipient':OWNER,'received_folder_id':folder,'delivery_folder':'Inbox' if folder=='1083319000000008014' else 'OptiBrain (existing owner mail filter)',
                'message_id':mid,'subject':subject,'delivered_at':datetime.fromtimestamp(received,timezone.utc).isoformat(),
                'verified_at':timestamp().isoformat(),'evidence':'Authenticated GET search + exact received owner-folder message details; excludes Sent, drafts and outgoing copies'}
    return None


AUTHORIZATION_ROOT=Path('/recovery/migration-preparation/autonomous-20261101/executor/owner-authorizations')


def check_alert_budget(control,profile,incident=None):
    """One explicit, audited renewal; preserve every old incident and the 16-slot guard."""
    with control.connect() as db:
        rows={r[0]:json.loads(r[1]) for r in db.execute(
            'SELECT incident,state_json FROM migration_alerts WHERE execution_id=?',(control.run_id,))}
    projected=len(rows)+int(incident is not None and incident not in rows)
    plan=profile.get('runtime',{}).get('owner_notification_renewal')
    if not plan:
        require(projected<=MAX_ALERT_INCIDENTS,'owner_alert_run_limit_reached')
        return
    require(plan.get('additional_incident_limit')==MAX_ALERT_INCIDENTS,'notification_budget_limit_changed')
    baseline=plan.get('baseline_incident_hashes',{})
    require(len(baseline)==MAX_ALERT_INCIDENTS and all(
        name in rows and rows[name].get('state') in ('DELIVERED','NOT_SENT_CANONICAL_GUARD_REFUSED')
        and digest(rows[name])==checksum for name,checksum in baseline.items()),'notification_history_changed')
    path=Path(plan['approval_file']);private_file(path);approval=json.loads(path.read_text())
    require(approval.get('approved') is True and approval.get('execution_id')==control.run_id
        and approval.get('package_sha256')==profile_binding(profile)
        and approval.get('plan_sha256')==digest(plan),'exact_notification_renewal_required')
    require(approval.get('issued_epoch',float('inf'))<=time.time()<approval.get('expires_epoch',0)
        <=datetime.fromisoformat(plan['expires_utc']).timestamp(),'notification_renewal_expired')
    owner=Path(approval['owner_authorization_file']);private_file(owner)
    require(owner.resolve().parent==AUTHORIZATION_ROOT.resolve()
        and file_hash(owner)==approval.get('owner_authorization_sha256')
        and approval.get('owner_authorization_reference'),'actual_notification_owner_artifact_required')
    action=control.audit.store.get(approval.get('action_id',''))
    require(action and action['status']=='SUCCEEDED'
        and action['trigger']==approval['owner_authorization_reference']
        and action['authority_class']=='OWNER_ONLY_MIGRATION_NOTIFICATION_RENEWAL'
        and action['exact_versions'].get('package_sha256')==profile_binding(profile)
        and action['after_state'].get('receipt_sha256')==file_hash(path),'notification_renewal_not_audited')
    require(projected<=2*MAX_ALERT_INCIDENTS
        and projected-len(baseline)<=MAX_ALERT_INCIDENTS,'owner_alert_renewal_limit_reached')


def notify(control,profile,policy_path,kind,incident,*,mail_factory=Mail,delays=(0,2,4,8,12,20)):
    private_file(policy_path);policy=json.loads(Path(policy_path).read_text())
    require(policy['recipient']==OWNER and policy['account_id']==ACCOUNT and policy['authority_reference']==AUTHORITY_REFERENCE,'owner_channel_not_authorized')
    require(time.time()<policy['expires_epoch'],'owner_channel_authority_expired')
    require(policy['code_sha256']==file_hash(__file__),'notification_code_changed')
    require(profile['execution_id']==control.run_id,'notification_run_mismatch')
    require(re.fullmatch('[A-Za-z0-9:_-]{1,140}',incident) is not None,'invalid_incident')
    state=control.state() or {};body=body_for(kind,control.run_id,state,policy['report_reference'])
    if kind!='TEST':
        try:
            health=json.loads(Path('/var/lib/optibrain-rebuild/migration-health.json').read_text())
            fresh_health=0<=time.time()-health['checked_epoch']<180
            src=health.get('source',{});dst=health.get('target',{})
            available=(src.get('API',{}).get('status')=='ok' and all(v=='active' for v in src.get('services',{}).values())) if state.get('authority')=='OLD' else dst.get('API',{}).get('ok') is True
            body+='Verified production available: '+str(bool(available))+'; health evidence current: '+str(fresh_health)+'; source free bytes: '+str(int(src.get('root_free_bytes',0)))+'\n'
        except Exception:body+='Current production availability: UNKNOWN; timed maintenance remains blocked.\n'
        body+='Automatic recovery: bounded local restart and stage-specific approved compensation; ambiguous effects remain contained.\n'
    subject='OPTIBRAIN MIGRATION '+kind+' '+control.run_id+'-'+digest(incident)[:12]
    check_alert_budget(control,profile,incident)
    row,fresh=control.alert_intent(incident,digest(body))
    if row.get('state')=='DELIVERED':return row
    if fresh:require(row['body_sha256']==digest(body),'alert_incident_body_changed_do_not_resend')
    mail=mail_factory()
    if fresh:
        check_alert_budget(control,profile)
        # Explicit current owner instruction authorizes only this fixed technical channel.
        aid='migration-owner-alert:'+control.run_id+':'+incident
        action=control.audit.envelope(aid,'migration.owner_notification',{'type':'MAIL','identity':OWNER},timestamp(),
            initiator='OWNER',trigger=AUTHORITY_REFERENCE,before_state={'incident':incident,'mail_send_attempts':0},
            proposed_state={'recipient':OWNER,'account_id':ACCOUNT,'body_sha256':digest(body),'subject':subject},
            reason='Explicit owner-authorized technical migration alert',business_rationale='Notify owner without customer execution authority',
            authority_class='OWNER_ONLY_MIGRATION_NOTIFICATION',automatic_rule=AUTHORITY_REFERENCE,
            mutation=True,approval_required=True,rollback_capability='IRREVERSIBLE',irreversible=True,
            consequence='One technical email delivered to the owner mailbox',compensating_action='Retain audit; owner may archive email; never delete or resend automatically',
            exact_versions={'notification_code_sha256':file_hash(__file__),'profile_sha256':digest(profile)})
        control.audit.store.plan(action,timestamp())
        control.audit.store.approve(aid,'OWNER_EXPLICIT_REQUEST:'+AUTHORITY_REFERENCE,timestamp(),binding=control.canonical.approval_binding(action),expires_at=datetime.fromtimestamp(policy['expires_epoch'],timezone.utc).isoformat())
        control.audit.store.start(aid,timestamp(),authority_check=lambda:require(policy['recipient']==OWNER,'owner_only'))
        try:
            account=mail.request('GET','/api/accounts/'+ACCOUNT)
            if isinstance(account,list): account=next((x for x in account if str(x.get('accountId'))==ACCOUNT),{})
            require(str(account.get('accountId'))==ACCOUNT and account.get('primaryEmailAddress')==OWNER,'owner_mail_account_changed')
            ack=mail.request('POST','/api/accounts/'+ACCOUNT+'/messages',body={'fromAddress':OWNER,'toAddress':OWNER,'subject':subject,'content':body,'mailFormat':'plaintext'})
            row.update(acknowledgement_id=str((ack or {}).get('messageId','')),subject=subject,send_epoch=time.time())
            control.save_alert(incident,row)
        except Exception as e:
            row.update(state='UNKNOWN',error=type(e).__name__,subject=subject);control.save_alert(incident,row)
            control.audit.store.finish(aid,timestamp(),provider_success=False,failure={'stage':'OWNER_MAIL_SEND','error_class':type(e).__name__,'provider_status':None,'safe_details':'Owner alert outcome uncertain','partial_effects':'UNKNOWN; no automatic resend','recovery_action':'GET-only owner mailbox reconciliation'})
            raise
    for delay in delays:
        if delay:time.sleep(delay)
        result=delivery(mail,subject,datetime.fromisoformat(row['at']).timestamp())
        if result:
            result.update(incident=incident,body_sha256=row['body_sha256']);control.save_alert(incident,result)
            aid='migration-owner-alert:'+control.run_id+':'+incident
            action=control.audit.store.get(aid)
            if action and action['status']=='STARTED':control.audit.store.finish(aid,timestamp(),provider_success=True,actual_after=result,verified=True)
            if kind=='TEST':control.transition({'notification_test':result},'owner_delivery_test_passed')
            clear_verified_notification_failure(control,result)
            return result
    row.update(state='UNKNOWN',subject=subject,error='InboxDeliveryNotVerified');control.save_alert(incident,row)
    return row


def clear_verified_notification_failure(control,result):
    if not (control.state() or {}).get('notification_failure') or result.get('state')!='DELIVERED':return
    try:fresh=0<=time.time()-datetime.fromisoformat(result['verified_at']).timestamp()<180
    except (KeyError,ValueError):return
    if not fresh:return
    with control.connect() as db:
        rows=[json.loads(r[0]) for r in db.execute('SELECT state_json FROM migration_alerts WHERE execution_id=?',(control.run_id,))]
    # A later successful message cannot resolve an earlier uncertain send.
    if all(r.get('state') in ('DELIVERED','NOT_SENT_CANONICAL_GUARD_REFUSED') for r in rows):
        control.transition({'notification_failure':None,'notification_recovery_evidence':{'received_message_id':result.get('message_id'),'verified_at':result['verified_at'],'all_uncertain_alerts_reconciled':True}},'notification_failure_resolved_by_received_readback')

def main():
    a=argparse.ArgumentParser();a.add_argument('kind',choices=sorted(KINDS));a.add_argument('incident')
    a.add_argument('--profile',required=True);a.add_argument('--policy',default='/etc/optibrain/migration/owner-notification-policy.json')
    a.add_argument('--database',default='/var/lib/optibrain-rebuild/actions.db');args=a.parse_args()
    require(os.geteuid()==0 and os.uname().nodename=='vps-f8e9b20e','replacement_root_only')
    p=load_profile(args.profile);c=Control(args.database,p['execution_id']);print(json.dumps(notify(c,p,args.policy,args.kind,args.incident)))

if __name__=='__main__':main()
