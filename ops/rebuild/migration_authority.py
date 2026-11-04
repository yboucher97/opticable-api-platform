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

def main():
 a=argparse.ArgumentParser();a.add_argument('mode',choices=('issue','template'));a.add_argument('--owner-message',type=Path);a.add_argument('--owner-reference');a.add_argument('--decisions',type=Path);a.add_argument('--package-sha256');args=a.parse_args();require(os.geteuid()==0 and os.uname().nodename=='vps-f8e9b20e','NEW_root_only');p=load_profile('/etc/optibrain/migration/profile.json')
 if args.mode=='template':
  print(json.dumps({'warning':'NOT-AUTHORIZED-TEMPLATE; each decision defaults false','package_sha256':profile_binding(p),'execution_id':p['execution_id'],'decisions':{scope:{'approved':False,'conditional_rollback_approved':False,'conditional_OLD_queue_resume_approved':False} for scope in SCOPES}},indent=2));return
 require(args.owner_message and args.decisions and args.owner_reference and args.package_sha256,'all_actual_owner_inputs_required');out=issue(p,args.owner_message,args.owner_reference,args.decisions,args.package_sha256)
 # Preserve prior decisions and the actual authorization message, including declined scopes.
 root=Path('/recovery/migration-preparation/autonomous-20261101/executor/owner-authorizations');root.mkdir(mode=0o700,exist_ok=True)
 old=Path('/etc/optibrain/migration/owner-approvals.json')
 if old.exists():atomic_json(root/(file_hash(old)+'.previous.json'),json.loads(old.read_text()))
 evidence=root/(out['owner_authorization_sha256']+'.txt')
 if not evidence.exists():evidence.write_bytes(args.owner_message.read_bytes());evidence.chmod(0o600)
 atomic_json(old,out);c=Control('/var/lib/optibrain-rebuild/actions.db',p['execution_id']);changes={}
 from migration_adapters import TIMED_SCOPES
 if all(out['scopes'][s]['approved'] for s in TIMED_SCOPES):changes['forms_hold_started_epoch']=out['issued_epoch'];changes['maintenance_clock_basis']='Conservative approved-window start; never later than subsequent Forms UI hold'
 c.transition({**changes,'owner_approval_reference':args.owner_reference,'owner_approval_sha256':file_hash(old),'owner_decisions':{s:v['approved'] for s,v in out['scopes'].items()}},'actual_owner_decisions_recorded')
 print(json.dumps({'status':'RECORDED','approved_scopes':[s for s,v in out['scopes'].items() if v['approved']],'declined_scopes':[s for s,v in out['scopes'].items() if not v['approved']],'expires_epoch':out['expires_epoch'],'production_operations':0}))
if __name__=='__main__':main()
