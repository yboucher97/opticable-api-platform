#!/usr/bin/env python3
"""Record actual owner decisions; never generate consent or auto-approve scopes.
Operator supplies the verbatim authorization artifact and independent decisions.
No production operation occurs here. Exact immutable package is checked again.
"""
import argparse,json,os,time
from datetime import datetime
from pathlib import Path
from common import atomic_json,digest,file_hash,private_file,require
from durable_migration import Control,load_profile,profile_binding,SCOPES

def issue(p,owner_message,reference,decisions,expected,now=None):
 epoch=time.time() if now is None else now
 require(expected==profile_binding(p),'owner_reviewed_package_changed');private_file(owner_message);private_file(decisions)
 text=Path(owner_message).read_text();require(len(text)>20 and reference and 'NOT-AUTHORIZED-TEMPLATE' not in text,'actual_owner_authorization_artifact_required')
 d=json.loads(Path(decisions).read_text());require(set(d)==set(SCOPES),'eight_independent_decisions_required')
 deadlines=[]
 for scope,value in d.items():
  if value.get('approved') is True and p['scopes'][scope].get('approval_expiry_utc'):
   end=datetime.fromisoformat(p['scopes'][scope]['approval_expiry_utc']);require(end.tzinfo is not None and end.timestamp()>epoch,'reviewed_scope_document_expired:'+scope);deadlines.append(end.timestamp())
 until=min([epoch+3600,*deadlines])
 out={'execution_id':p['execution_id'],'profile_sha256':expected,'owner_authorization_reference':reference,'owner_authorization_sha256':file_hash(owner_message),'issued_epoch':epoch,'expires_epoch':until,'scopes':{}}
 for scope in SCOPES:
  v=d[scope];require(isinstance(v.get('approved'),bool),'explicit_yes_or_no_required:'+scope)
  out['scopes'][scope]={'approved':v['approved'],'binding_sha256':digest(p['scopes'][scope]),'issued_epoch':epoch,'expires_epoch':until,'owner_authorization_reference':reference,'owner_authorization_sha256':file_hash(owner_message),'conditional_rollback_approved':v.get('conditional_rollback_approved') is True,'conditional_OLD_queue_resume_approved':v.get('conditional_OLD_queue_resume_approved') is True}
 return out


def window_changes(p,control,out,prior_snapshot):
 # One root execution/notification ledger; only stage evidence and action IDs
 # receive a fresh namespace after a proved closed pre-NEW attempt.
 state=control.state() or {}
 require(not any(state.get(k) for k in ('forms_hold_started_epoch','hold_started_epoch')),'previous_maintenance_window_not_closed')
 done=state.get('completed_stages',[])
 require(not any(x in done for x in ('INTAKE_RELEASED','CUTOVER','COMPLETE')),'NEW_boundary_forbids_window_rearm')
 require(state.get('authority','OLD')=='OLD','OLD_not_authoritative_for_window_rearm')
 require(out['owner_authorization_reference']!=state.get('owner_approval_reference'),'fresh_window_owner_authorization_reference_required')
 if any(x in done for x in ('QUEUE_HELD','SOURCE_FROZEN','CAPTURED','TARGET_SYNCHRONIZED')):
  closed=state.get('maintenance_closeout',{});path=Path(closed.get('path',''))
  private_file(path);require(file_hash(path)==closed.get('sha256'),'closed_window_proof_changed')
  proof=json.loads(path.read_text());source=proof.get('source',{})
  require(state.get('status')=='ROLLED_BACK' and proof.get('status')=='CLOSED_VERIFIED_PRE_NEW_ROLLBACK'
   and source.get('fenced') is False and source.get('state',{}).get('event')=='ROLLED_BACK'
   and not source.get('state',{}).get('new_data_observed')
   and proof.get('NEW_never_released') is True and proof.get('Worker_original') is True
   and proof.get('DNS',{}).get('content')==p['source']['ip']
   and not proof.get('queue',{}).get('settings',{}).get('delivery_paused',False)
   and set(proof.get('forms',{}))=={'FR','EN'}
   and all(v.get('http_status')==200 and v.get('live_form_elements',0)>0 and v.get('maintenance_message_present') is False for v in proof['forms'].values()),
   'closed_pre_NEW_rollback_not_independently_verified')
 require(out['scopes']['source_freeze_final_sync'].get('conditional_rollback_approved') is True
  and out['scopes']['safe_queue_observer_resume'].get('conditional_OLD_queue_resume_approved') is True,'conditional_rollback_permissions_required')
 window=digest({'execution_id':p['execution_id'],'issued_epoch':out['issued_epoch'],'owner_sha256':out['owner_authorization_sha256']})[:24]
 require(window!=state.get('maintenance_window_id'),'same_window_cannot_be_reissued')
 return {'maintenance_window_id':window,'previous_window_state':str(prior_snapshot),
  'owner_approval_reference':out['owner_authorization_reference'],'owner_authorization_sha256':out['owner_authorization_sha256'],
  'profile_sha256':profile_binding(p),'status':'APPROVED','current_stage':'APPROVED',
  'completed_stages':['PREPARED','APPROVED'],'next_resumable_stage':'FORMS_HELD',
  'last_output_sha256':None,'blocker':None,'rollback_decision':None,'rollback_observed':None,
  'forms_hold_started_epoch':out['issued_epoch'],'hold_started_epoch':None,
  'maintenance_clock_basis':'Original actual receipt issue of this independently authorized window; prior window verified closed',
  'evidence':[str(prior_snapshot)],'authority':'OLD'}

def main():
 a=argparse.ArgumentParser();a.add_argument('mode',choices=('issue','template'));a.add_argument('--owner-message',type=Path);a.add_argument('--owner-reference');a.add_argument('--decisions',type=Path);a.add_argument('--package-sha256');args=a.parse_args();require(os.geteuid()==0 and os.uname().nodename=='vps-f8e9b20e','NEW_root_only');p=load_profile('/etc/optibrain/migration/profile.json')
 if args.mode=='template':
  print(json.dumps({'warning':'NOT-AUTHORIZED-TEMPLATE; each decision defaults false','package_sha256':profile_binding(p),'execution_id':p['execution_id'],'decisions':{scope:{'approved':False,'conditional_rollback_approved':False,'conditional_OLD_queue_resume_approved':False} for scope in SCOPES}},indent=2));return
 require(args.owner_message and args.decisions and args.owner_reference and args.package_sha256,'all_actual_owner_inputs_required');out=issue(p,args.owner_message,args.owner_reference,args.decisions,args.package_sha256)
 c=Control('/var/lib/optibrain-rebuild/actions.db',p['execution_id']);changes={}
 from migration_adapters import TIMED_SCOPES
 if all(out['scopes'][s]['approved'] for s in TIMED_SCOPES):
  require(not any((c.state() or {}).get(k) for k in ('forms_hold_started_epoch','hold_started_epoch')),'previous_maintenance_window_not_closed')
  if p.get('runtime',{}).get('windowed_maintenance_evidence'):
   snapshot=Path('/recovery/migration-preparation/autonomous-20261101/executor/owner-authorizations')/('prior-window-'+digest(c.state())+'.json')
   changes=window_changes(p,c,out,snapshot)
   atomic_json(snapshot,c.state())
  else:
   changes['forms_hold_started_epoch']=out['issued_epoch'];changes['maintenance_clock_basis']='Conservative approved-window start; never later than subsequent Forms UI hold'
 # Preserve prior decisions and the actual authorization message, including declined scopes.
 root=Path('/recovery/migration-preparation/autonomous-20261101/executor/owner-authorizations');root.mkdir(mode=0o700,exist_ok=True)
 old=Path('/etc/optibrain/migration/owner-approvals.json')
 if old.exists():atomic_json(root/(file_hash(old)+'.previous.json'),json.loads(old.read_text()))
 evidence=root/(out['owner_authorization_sha256']+'.txt')
 if not evidence.exists():evidence.write_bytes(args.owner_message.read_bytes());evidence.chmod(0o600)
 atomic_json(old,out)
 c.transition({**changes,'owner_approval_reference':args.owner_reference,'owner_approval_sha256':file_hash(old),'owner_decisions':{s:v['approved'] for s,v in out['scopes'].items()}},'actual_owner_decisions_recorded')
 print(json.dumps({'status':'RECORDED','approved_scopes':[s for s,v in out['scopes'].items() if v['approved']],'declined_scopes':[s for s,v in out['scopes'].items() if not v['approved']],'expires_epoch':out['expires_epoch'],'production_operations':0}))
if __name__=='__main__':main()
