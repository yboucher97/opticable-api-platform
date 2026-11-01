#!/usr/bin/env python3
"""Read-only window attestation. No queue hold, freeze, deployment or provider write."""
import json,os,subprocess,sys,time
from pathlib import Path
from common import atomic_json,file_hash,require
from durable_migration import load_profile,profile_binding,Control
from migration_adapters import Live,CONTROL,ART

def verify_window():
 require(os.geteuid()==0 and os.uname().nodename=='vps-f8e9b20e','NEW_only')
 p=load_profile('/etc/optibrain/migration/profile.json');live=Live(p);proofs={}
 source=live.source('status');require(source['persistent_fence_installed'],'OLD_fence_not_installed');proofs['source']=source
 preflight=live.source('preflight');require(preflight['status']=='PASS' and preflight['owner_allowlist_preserved'] and preflight['google_binding_preserved'],'source_identity_or_capacity_failed');proofs['identity']=preflight
 source_providers=live.source('providers');require(source_providers['all_required_pass'],'OLD_provider_not_healthy');proofs['source_providers']=source_providers
 sys.path.insert(0,'/opt/optibrain-rebuild-toolchain/migration-20261027/ops/rebuild')
 from providers import probe_all
 manifest=json.loads((CONTROL/'manifest.json').read_text());target=probe_all(manifest=manifest);require(all(target.get(k,{}).get('status')=='PASS' for k in manifest['bootstrap']['required_providers']),'NEW_provider_not_healthy');proofs['target_providers']=target
 owner=Path('/recovery/migration-preparation/cutover-readiness-20261011/owner-access-verified.json');v=json.loads(owner.read_text());require(v.get('status')=='PASS' and v.get('real_owner_identity_verified') is True,'real_owner_identity_proof_missing');proofs['owner_proof_sha256']=file_hash(owner)
 import importlib.util
 spec=importlib.util.spec_from_file_location('reviewed_final_identity',ART/'final_identity_check.py');identity=importlib.util.module_from_spec(spec);spec.loader.exec_module(identity)
 pins=json.loads((ART/'final-identity-pins.json').read_text());require(v['subject_sha256']==pins['owner_receipt_subject_sha256'],'owner_subject_binding_changed')
 target_pins=dict(pins);registration=json.loads(Path(identity.REGISTRATION).read_text())
 candidate=registration['candidate_sha'];require(candidate in (p['production_sha'],p['scopes']['new_only_intake_release']['candidate_sha']),'target_release_not_reviewed');target_pins['source_sha']=candidate
 proofs['target_identity']=identity.check_values(registration,json.loads(Path(identity.GOOGLE).read_text()),target_pins)
 from owner_notifications import Mail,delivery
 result=delivery(Mail(),'OPTIBRAIN MIGRATION TEST optibrain-20261101-durable-01-9eda4cb69192',1793547390)
 require(result and result.get('state')=='DELIVERED','owner_delivery_no_longer_provable');proofs['notification_delivery']=result
 control=live.c.state() or {};require(control.get('notification_test',{}).get('state')=='DELIVERED','notification_test_not_persisted')
 offhost=json.loads((CONTROL/'migration-offhost.json').read_text());require(offhost.get('status')=='PASS' and offhost.get('full_R2_readback')=='PASS','encrypted_control_readback_missing');proofs['offhost']=offhost
 fixture=Path(p['runtime']['fixture_evidence']);v=json.loads(fixture.read_text());require(v.get('status')=='PASS' and v.get('code_sha256')==p['code_sha256'] and v.get('full_chain') and v.get('persistent_fence') and v.get('conditional_rollback'),'fixture_code_or_safety_evidence_missing');proofs['fixture_sha256']=file_hash(fixture)
 require(subprocess.check_output(['systemctl','is-active','optibrain-migration-watchdog.timer'],text=True).strip()=='active','watchdog_not_active')
 output={'status':'PASS','package_sha256':profile_binding(p),'verified_epoch':time.time(),'owner_access':True,'providers':True,'identity':True,'recovery':True,'rollback':True,'reboot_fence':True,'proofs':proofs,'production_mutations':0}
 atomic_json('/var/lib/optibrain-rebuild/window-verification.json',output);return output
if __name__=='__main__':
 try:r=verify_window();print(json.dumps({'status':r['status'],'package_sha256':r['package_sha256'],'verified_epoch':r['verified_epoch'],'production_mutations':0}))
 except Exception as e:print(json.dumps({'status':'BLOCKED','error':str(e)}));raise SystemExit(1)
