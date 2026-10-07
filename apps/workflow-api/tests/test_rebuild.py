"""Replacement-host contracts with private fixtures and fake OS/provider ports."""
from copy import deepcopy
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'ops/rebuild'))
from common import Audit, RebuildError, atomic_json, database_snapshot, file_hash, path_at
from engine import Engine, Host, BASE_PACKAGES, package_plan, restore_plan, reviewed_bytes, validate_rebuild_manifest
from recovery import STATE_ROOTS, classify, selected, select_generation, stage_archive, manifest_from_archive, validate_manifest
from verification import check_secrets, knowledge_check, ready, validate_stale_suppression
from migration import assert_immutable_superset, final_sync, rollback_manifest, validate_freeze
from performance import compare


class FakeHost(Host):
    def __init__(self,root):super().__init__(root);self.calls=[];self.installed=set(BASE_PACKAGES);self.mounts={}
    def ids(self):
        names=['root','optibrain','opticable-workflow-api','opticable-password-pdf','opticable-omada-site','siteandpassword']
        return dict.fromkeys(names,os.getuid()),dict.fromkeys(names,os.getgid())
    def chown(self,path,uid,gid):pass
    def ensure_users(self):return self.ids()
    def same_mount(self,source,target):return self.mounts.get(str(target))==str(source)
    def run(self,args,**kwargs):
        args=list(map(str,args));self.calls.append(args)
        if args[0]=='dpkg-query':return '\n'.join(sorted(self.installed))
        if args[:2]==['apt-get','install']:self.installed.update(args[5:]);return ''
        if args[:2]==['systemctl','list-unit-files']:
            return '\n'.join(p.name+' static -' for p in (self.root/'etc/systemd/system').glob('*.service'))
        if args[:2]==['mount','--bind']:
            source,target=map(Path,args[2:]);shutil.copytree(source,target,dirs_exist_ok=True);self.mounts[str(target)]=str(source);return ''
        if args[0]=='umount':
            target=Path(args[1]);self.mounts.pop(str(target))
            for item in target.iterdir():
                if item.is_dir():shutil.rmtree(item)
                else:item.unlink()
            return ''
        if args[:2]==['systemctl','is-active']:return 'active'
        if args[:2]==['systemctl','is-enabled']:return 'enabled'
        if args[:2]==['git','-c'] and args[-2:]==['rev-parse','HEAD']:return 'a'*40
        if args[0]=='hostname':return 'replacement.example'
        if args[:2]==['timedatectl','show']:return 'America/Toronto'
        return ''


def make_archive(directory, *, generation='20261007T030438Z', learning=0, corrupt=False):
    root=Path(directory)/('input-'+generation);root.mkdir()
    db=root/'database/automation.db';db.parent.mkdir()
    if corrupt:db.write_bytes(b'not SQLite')
    else:
        with sqlite3.connect(db) as con:
            con.executescript('CREATE TABLE manager_learning(id TEXT PRIMARY KEY,value TEXT);CREATE TABLE pending(id TEXT PRIMARY KEY,state TEXT);')
            con.execute("INSERT INTO pending VALUES('stale-job','queued')")
            for i in range(learning):con.execute('INSERT INTO manager_learning VALUES(?,?)',(str(i),'measured lesson'))
    config=root/'system/etc/opticable-workflow-api.env';config.parent.mkdir(parents=True)
    config.write_text('SITE_WORKFLOW_API_KEY=fixture_only\n')
    files=[]
    for p in (db,config):files.append({'path':str(p.relative_to(root)),'size':p.stat().st_size,'sha256':file_hash(p)})
    manifest={'backup_format_version':'1','timestamp':generation,'production_git_sha':'a'*40,'application_version':'1.34.1',
        'files':files,'sqlite_databases':[{'backup_path':'database/automation.db','integrity':'ok'}],
        'source_metadata':[{'source_path':'/etc/opticable-workflow-api.env','backup_path':'system/etc/opticable-workflow-api.env/.',
                            'owner':'root','group':'root','type':'file','mode':'0600'}]}
    for canonical in STATE_ROOTS:
        backup='state'+canonical
        (root/backup).mkdir(parents=True,exist_ok=True)
        manifest['source_metadata'].append({'source_path':canonical,'backup_path':backup+'/.',
            'owner':'root','group':'root','type':'directory','mode':'0700'})
    (root/'manifest.json').write_text(json.dumps(manifest))
    archive=Path(directory)/(generation+'.tar.gz')
    with tarfile.open(archive,'w:gz') as tar:tar.add(root,arcname='generation-'+generation)
    row={'generation':generation,'source_sha':'a'*40,'api_version':'1.34.1','backup_format_version':'1',
         'verification_status':'download_hash_verified','plaintext_sha256':file_hash(archive),'ciphertext_sha256':'b'*64,
         'databases':['database/automation.db'],'expected_knowledge':{'database/automation.db':database_snapshot(db)} if not corrupt else {'database/automation.db':{}},
         'verified_at':datetime.now(timezone.utc).isoformat()}
    return archive,row


class RebuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='rebuild-contract-');self.directory=Path(self.tmp.name)
        self.manifest=json.loads((ROOT/'docs/rebuild/current-host-manifest.json').read_text())
        self.manifest['source_production_sha']='a'*40
        self.archive,self.row=make_archive(self.directory)
        self.catalog={'catalog_version':1,'generations':[self.row]}
        self.target=self.directory/'target';(self.target/'etc').mkdir(parents=True)
        (self.target/'etc/os-release').write_text('ID=ubuntu\nVERSION_ID="24.04"\n')
        (self.target/'usr/bin').mkdir(parents=True)
        self.host=FakeHost(self.target)
        self.engine=Engine(self.manifest,self.catalog,self.archive,host=self.host)
        self.engine.control.mkdir(parents=True)
        self.engine.audit=Audit(self.engine.control/'actions.db')
    def tearDown(self):self.tmp.cleanup()
    def assert_blocked(self,function,code):
        with self.assertRaisesRegex(RebuildError,code):function()

    def test_manifest_current_complete_and_hash_pinned(self):self.assertTrue(validate_rebuild_manifest(self.manifest))
    def test_canonical_audit_works_before_third_party_packages_exist(self):
        code="import sys;sys.path.insert(0,sys.argv[1]);from common import Audit;from pathlib import Path;a=Audit(Path(sys.argv[2]));\nwith a.step('stdlib_bootstrap','fixture',{'fresh':True},{'reviewed':True}) as result:result.update(verified=True)"
        result=subprocess.run(['/usr/bin/python3','-I','-S','-B','-c',code,str(ROOT/'ops/rebuild'),str(self.directory/'stdlib-audit.db')],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
    def test_manifest_missing_inventory_rejected(self):
        del self.manifest['secret_paths'];self.assert_blocked(lambda:validate_rebuild_manifest(self.manifest),'incomplete')
    def test_manifest_cannot_grant_authority(self):
        self.manifest['authority_expected_restore_state']['customer']='ON';self.assert_blocked(lambda:validate_rebuild_manifest(self.manifest),'unsafe_manifest')
    def test_reviewed_unit_hash_mismatch(self):
        self.manifest['bootstrap']['reviewed_files'][0]['sha256']='0'*64;self.assert_blocked(lambda:validate_rebuild_manifest(self.manifest),'hash_mismatch')
    def test_unreviewed_package_plan_rejected(self):
        self.manifest['bootstrap']['packages'].append('docker.io');self.assert_blocked(lambda:validate_rebuild_manifest(self.manifest),'unreviewed_package')
    def test_replacement_backup_adapter_uses_only_generation_root_manifest(self):
        row=next(r for r in self.manifest['bootstrap']['reviewed_files'] if r['source']=='ops/backup/optibrain-backup.sh')
        self.assertIn(b'-mindepth 2 -maxdepth 2 -type f -name manifest.json',reviewed_bytes(row))
        row['installed_sha256']='0'*64;self.assert_blocked(lambda:reviewed_bytes(row),'installed_definition_hash_mismatch')
    def test_package_plan_missing_only(self):self.assertEqual(package_plan(BASE_PACKAGES[:-1]),[BASE_PACKAGES[-1]])
    def test_package_plan_idempotent(self):self.assertEqual(package_plan(BASE_PACKAGES),[])
    def test_latest_verified_ignores_newest_unverified(self):
        bad=deepcopy(self.row);bad.update(generation='20261008T030438Z',verification_status='prepared')
        self.catalog['generations'].append(bad);self.assertEqual(select_generation(self.catalog),self.row)
    def test_latest_compatible_exact_sha(self):self.assertEqual(select_generation(self.catalog,source_sha='a'*40),self.row)
    def test_wrong_generation_blocked(self):self.assert_blocked(lambda:select_generation(self.catalog,'20261009T030438Z'),'no_verified')
    def test_incompatible_generation_blocked(self):self.assert_blocked(lambda:select_generation(self.catalog,source_sha='c'*40),'no_verified')
    def test_duplicate_generation_blocked(self):
        self.catalog['generations'].append(deepcopy(self.row));self.assert_blocked(lambda:select_generation(self.catalog),'duplicate')
    def test_plan_has_zero_host_writes(self):
        before=list(self.target.rglob('*'));plan=restore_plan(self.manifest,self.catalog)
        self.assertEqual(before,list(self.target.rglob('*')));self.assertEqual(plan['writes_performed'],0);self.assertFalse(self.host.calls)
    def test_optional_data_volume_plan(self):self.assertEqual(restore_plan(self.manifest,self.catalog,data_root='/srv/optibrain-data')['data_root'],'/srv/optibrain-data')
    def test_unsafe_data_volume_rejected(self):self.assert_blocked(lambda:restore_plan(self.manifest,self.catalog,data_root='/srv/../etc'),'unsafe_data_root')
    def test_existing_production_refused_before_any_adapter(self):
        (self.target/'etc/optibrain').mkdir()
        with patch('engine.os.geteuid',return_value=0):self.assert_blocked(self.engine.guard,'existing_production_host')
        self.assertEqual(self.host.calls,[])
    def test_existing_production_marker_does_not_bypass_refusal(self):
        (self.target/'etc/optibrain').mkdir();(self.target/'etc/optibrain-rebuild-target').write_text('marker')
        with patch('engine.os.geteuid',return_value=0):self.assert_blocked(self.engine.guard,'existing_production_host')
    def test_directory_symlink_rejected(self):
        (self.target/'escape').symlink_to(self.directory);self.assert_blocked(lambda:path_at(self.target,'/escape/a'),'symlink')
    def test_directory_traversal_rejected(self):self.assert_blocked(lambda:path_at(self.target,'/../../etc'),'unsafe_destination')
    def test_managed_file_rerun_preserves_bytes(self):
        self.assertTrue(self.engine.write('/etc/fixture','safe',0o640));stamp=(self.target/'etc/fixture').stat().st_mtime_ns
        self.assertFalse(self.engine.write('/etc/fixture','safe',0o640));self.assertEqual((self.target/'etc/fixture').stat().st_mtime_ns,stamp)
    def test_changed_permissions_stop_rerun(self):
        self.engine.write('/etc/fixture','safe',0o640);(self.target/'etc/fixture').chmod(0o666)
        self.assert_blocked(lambda:self.engine.write('/etc/fixture','safe',0o640),'permissions_changed')
    def test_directory_modes_match_service_contract(self):
        self.engine.users_directories();self.assertEqual((self.target/'var/lib/opticable-api-platform/shared').stat().st_mode&0o7777,0o2770)
        self.assertEqual((self.target/'var/lib/optibrain').stat().st_mode&0o7777,0o700)
    def test_safe_restore_masks_all_business_and_retired_units(self):
        self.engine.safety();self.assertEqual(validate_stale_suppression(self.engine)['authority'],'SAFE/OFF')
    def test_safety_idempotent(self):
        self.engine.safety();self.engine.safety();self.assertEqual(self.engine.verify_safety(),'SAFE/OFF')
    def test_authority_tampering_blocked(self):
        self.engine.safety();p=self.target/'etc/optibrain/mutation-control.json';v=json.loads(p.read_text());v['lifecycle']['enabled']=True;p.write_text(json.dumps(v))
        self.assert_blocked(self.engine.verify_safety,'authority_not_safe')
    def test_stale_timer_unmask_blocked(self):
        self.engine.safety();p=self.target/'etc/systemd/system/opticable-customer-communications.timer';p.unlink();p.write_text('[Timer]\n')
        self.assert_blocked(lambda:validate_stale_suppression(self.engine),'timer_unmasked')
    def test_database_restore_dynamic_count_and_exact_hashes(self):
        m,s=stage_archive(self.archive,self.row,self.directory/'stage');self.assertEqual(s,self.row['expected_knowledge']);self.assertEqual(len(s),1)
    def test_database_integrity_failure_stops(self):
        archive,row=make_archive(self.directory,generation='20261008T030438Z',corrupt=True)
        with self.assertRaises(sqlite3.DatabaseError):stage_archive(archive,row,self.directory/'stage')
    def test_database_foreign_keys_failure_stops(self):
        p=self.directory/'bad-fk.db'
        with sqlite3.connect(p) as db:db.executescript('CREATE TABLE p(id PRIMARY KEY);CREATE TABLE c(id, p REFERENCES p(id));INSERT INTO c VALUES(1,999);')
        self.assert_blocked(lambda:database_snapshot(p),'foreign_keys_failed')
    def test_archive_hash_mismatch_stops_before_staging(self):
        self.row['plaintext_sha256']='0'*64;destination=self.directory/'stage'
        self.assert_blocked(lambda:stage_archive(self.archive,self.row,destination),'archive_hash_mismatch');self.assertFalse(destination.exists())
    def test_manifest_wrong_generation_stops(self):
        m=manifest_from_archive(self.archive);self.row['generation']='20261008T030438Z'
        self.assert_blocked(lambda:validate_manifest(m,self.row),'wrong_recovery')
    def test_database_count_mismatch_stops(self):
        self.row['databases'].append('other.db');self.assert_blocked(lambda:validate_manifest(manifest_from_archive(self.archive),self.row),'inventory_mismatch')
    def test_traversal_archive_member_stops(self):
        p=self.directory/'evil.tar.gz'
        with tarfile.open(p,'w:gz') as tar:
            member=tarfile.TarInfo('../escape');member.size=1;tar.addfile(member,io.BytesIO(b'x'))
        self.assert_blocked(lambda:manifest_from_archive(p),'unsafe_archive')
    def test_link_archive_member_stops(self):
        p=self.directory/'evil.tar.gz'
        with tarfile.open(p,'w:gz') as tar:
            member=tarfile.TarInfo('link');member.type=tarfile.SYMTYPE;member.linkname='/etc/passwd';tar.addfile(member)
        self.assert_blocked(lambda:manifest_from_archive(p),'duplicate_or_link')
    def test_learning_zero_is_honest(self):
        stage_archive(self.archive,self.row,self.directory/'stage');v=knowledge_check(self.row['expected_knowledge'],self.row['expected_knowledge']);self.assertEqual(v['learning']['count'],0)
    def test_future_nonzero_learning_preserved_without_count_constant(self):
        a,r=make_archive(self.directory,generation='20261008T030438Z',learning=3)
        m,s=stage_archive(a,r,self.directory/'stage');self.assertEqual(knowledge_check(s,r['expected_knowledge'])['learning']['count'],3)
    def test_learning_loss_blocked(self):
        a,r=make_archive(self.directory,generation='20261008T030438Z',learning=1)
        self.assert_blocked(lambda:assert_immutable_superset(self.directory/'input-20261008T030438Z/database/automation.db',self.directory/'input-20261007T030438Z/database/automation.db'),'lost_immutable')
    def test_final_delta_preserves_immutable_learning(self):
        a,r=make_archive(self.directory,generation='20261008T030438Z',learning=2)
        self.assertEqual(assert_immutable_superset(self.directory/'input-20261007T030438Z/database/automation.db',self.directory/'input-20261008T030438Z/database/automation.db')['tables_checked'],1)
    def test_promotion_readback_permissions_and_safe_rerun(self):
        self.engine.safety();self.engine.users_directories();staged,manifest=self.engine.stage()
        self.engine.promote(staged,manifest);self.engine.promote(staged,manifest)
        self.assertEqual(database_snapshot(self.target/'var/lib/opticable-workflow-api/output/automation/automation.db'),self.row['expected_knowledge']['database/automation.db'])
        self.assertEqual((self.target/'etc/opticable-workflow-api.env').stat().st_mode&0o777,0o600)
        self.assertEqual(len(self.host.mounts),len(STATE_ROOTS));self.assertEqual(self.engine.verify_safety(),'SAFE/OFF')
    def test_component_bootstrap_rerun_does_not_reapply_restore(self):
        state=self.engine.control/'state.json';atomic_json(state,{'completed':False,'generation':None})
        success={'ready_for_owner_cutover':True,'authority':'SAFE/OFF'}
        with patch.object(self.engine,'install_node'),patch.object(self.engine,'source_runtime'),patch.object(self.engine,'rebind'),patch.object(self.engine,'proxy_firewall'),patch('verification.verify_host',return_value=success),patch.object(self.engine,'stage',wraps=self.engine.stage) as stage:
            self.assertTrue(self.engine.apply(state)['ready_for_owner_cutover'])
            self.assertTrue(self.engine.apply(state)['ready_for_owner_cutover']);self.assertEqual(stage.call_count,1)
        self.assertTrue(json.loads(state.read_text())['completed'])
    def test_failed_completed_verify_clears_marker_and_contains_services(self):
        state=self.engine.control/'state.json';atomic_json(state,{'completed':True,'generation':self.row['generation']})
        with patch('verification.verify_host',return_value={'ready_for_owner_cutover':False}):self.engine.apply(state)
        self.assertFalse(json.loads(state.read_text())['completed']);self.assertEqual(self.engine.verify_safety(),'SAFE/OFF')
    def test_final_sync_resumes_after_partial_unmount_and_preserves_old_state(self):
        self.engine.safety();self.engine.users_directories();old,manifest=self.engine.stage();self.engine.promote(old,manifest)
        generation=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        archive,row=make_archive(self.directory,generation=generation,learning=2)
        candidate=Engine(self.manifest,{'catalog_version':1,'generations':[row]},archive,host=self.host)
        candidate.audit=self.engine.audit
        state=candidate.control/'state.json';atomic_json(state,{'generation':self.row['generation'],'completed':False})
        freeze=self.directory/'freeze.json';atomic_json(freeze,{'frozen_at':(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(),'writers_off':True,'observers_off':True,'intake_off':True,'old_host':'old.example','recovery_generation':generation,'source_sha':'a'*40})
        @contextmanager
        def locked(**kwargs):yield state
        real_run=self.host.run;count=[0]
        def interrupted(args,**kwargs):
            if args[0]=='umount':
                count[0]+=1
                if count[0]==2:raise RebuildError('fixture_interruption')
            return real_run(args,**kwargs)
        with patch('migration.private_file'),patch.object(candidate,'locked',locked),patch.object(self.host,'run',side_effect=interrupted):
            self.assert_blocked(lambda:final_sync(candidate,freeze),'fixture_interruption')
        self.assertEqual(json.loads(state.read_text())['pending_generation'],generation)
        with patch('migration.private_file'),patch.object(candidate,'locked',locked),patch.object(candidate,'apply',return_value={'ready_for_owner_cutover':False}) as apply:
            final_sync(candidate,freeze);apply.assert_called_once()
        self.assertTrue((old/'database/automation.db').is_file());self.assertFalse(self.host.mounts)
        self.assertEqual(self.engine.verify_safety(),'SAFE/OFF')
    def test_scheduled_job_is_preserved_without_execution(self):
        stage_archive(self.archive,self.row,self.directory/'stage');self.engine.safety()
        with sqlite3.connect(self.directory/'stage/database/automation.db') as db:self.assertEqual(db.execute('SELECT state FROM pending').fetchone()[0],'queued')
        self.assertFalse(any('stale-job' in c for c in self.host.calls))
    def test_secret_missing_blocks_readiness(self):self.assert_blocked(lambda:check_secrets(self.engine),'missing_or_unsafe')
    def test_provider_failure_cannot_be_ready(self):
        names=['OS','SOURCE','DATABASES','KNOWLEDGE','AUDIT','MANAGER','SYSTEMD','PROXY','FIREWALL','SSH','AUTHORITY','STORAGE','SECRETS','BACKUPS']
        checks={n:{'status':'PASS'} for n in names};checks['PROVIDERS']={'GITHUB':{'status':'BLOCKED'}}
        self.assertFalse(ready(checks,['GITHUB']))
    def test_backup_not_run_blocks_cutover(self):
        checks={n:{'status':'PASS'} for n in ['OS','SOURCE','DATABASES','KNOWLEDGE','AUDIT','MANAGER','SYSTEMD','PROXY','FIREWALL','SSH','AUTHORITY','STORAGE','SECRETS']}
        checks['PROVIDERS']={};self.assertFalse(ready(checks,[]))
    def test_rollback_requires_exact_dns_before_state(self):self.assert_blocked(lambda:rollback_manifest('old','new',{},'generation'),'complete_dns')
    def test_rollback_keeps_old_host_and_freezes_both(self):
        value=rollback_manifest('148.113.249.7','192.0.2.20',{'record_id':'r','old_content':'148.113.249.7','ttl':1,'proxied':True},self.row['generation'])
        self.assertFalse(value['old_host_retention']['automatic_termination']);self.assertEqual(value['dns_mutations_performed'],0)
    def test_caches_and_worktrees_not_canonical_restore(self):
        self.assertFalse(selected('/var/lib/opticable-omada-site/ms-playwright/a'));self.assertEqual(classify('/run/readiness'),'REGENERABLE')
        self.assertFalse(selected('/home/optibrain/worktrees/old/source.py'));self.assertTrue(selected('/var/lib/optibrain/lifecycle/immutable-evidence.json'))
    def test_secret_authorizations_and_host_keys_never_restored(self):
        for p in ['/etc/optibrain/manual-release-authorization.json','/etc/optibrain/authorize-persistent-codex-development','/etc/ssh/ssh_host_ed25519_key']:
            self.assertFalse(selected(p))
    def test_historical_authorization_evidence_retained(self):
        self.assertTrue(selected('/var/lib/optibrain/lifecycle/immutable-authorization.json'))
    def test_conversion_native_configuration_retained_but_grants_cleared(self):
        value={'schema':1,'enabled':True,'release_sha':'a'*40,'destinations':{'ads':{'local_enabled':True,'allowed_event_keys':['event'],'native_id':'123'}},'validated_families':{'ads':'recorded'}}
        reset=self.engine.closed_conversion(value)
        self.assertEqual(reset['destinations']['ads']['native_id'],'123');self.assertFalse(reset['enabled'])
        self.assertFalse(reset['destinations']['ads']['local_enabled']);self.assertEqual(reset['destinations']['ads']['allowed_event_keys'],[])
    def test_systemd_install_exact_hash_and_rerun(self):
        self.engine.safety();self.engine.install_definitions();self.engine.install_definitions()
        self.assertTrue((self.target/'etc/systemd/system/opticable-workflow-api.service.rebuild-disabled').is_file())
        self.assertTrue((self.target/'etc/systemd/system/opticable-customer-communications.timer').is_symlink())
    def test_app_and_backup_boot_require_durable_mounts(self):
        self.engine.safety();self.engine.install_definitions()
        for name in ('opticable-workflow-api','optibrain-backup','optibrain-phase2a-upload'):
            value=(self.target/'etc/systemd/system'/(name+'.service.d/98-rebuild-data.conf')).read_text()
            self.assertTrue(all(path in value for path in STATE_ROOTS));self.assertIn('RequiresMountsFor=',value)
    def test_universal_action_evidence_hash_chain(self):
        self.engine.safety()
        with self.engine.audit.store.connect(readonly=True) as db:ids=[r[0] for r in db.execute('SELECT action_id FROM action_envelopes')]
        self.assertTrue(ids);self.assertTrue(all(self.engine.audit.store.verify_integrity(aid) for aid in ids))
    def test_failed_operation_records_structured_audit_and_preserves_error(self):
        with self.assertRaisesRegex(RebuildError,'fixture_blocker'):
            with self.engine.operation('fixture_failure',{'value':'before'},{'value':'proposed'}):raise RebuildError('fixture_blocker')
        with self.engine.audit.store.connect(readonly=True) as db:
            aid=db.execute('SELECT action_id FROM action_envelopes').fetchone()[0]
            plan=self.engine.audit.store.current(db,aid)
        self.assertEqual(plan['status'],'FAILED');self.assertEqual(plan['final_result']['safe_details'],'fixture_blocker')
        self.assertTrue(self.engine.audit.store.verify_integrity(aid))
    def test_audit_chain_corruption_rejected(self):
        self.engine.safety();path=self.engine.control/'actions.db'
        with sqlite3.connect(path) as db:
            db.execute('DROP TRIGGER action_evidence_immutable_update');db.execute("UPDATE action_evidence SET event_hash='broken' WHERE event_id=1")
        self.assert_blocked(lambda:database_snapshot(path),'audit_chain_failed')
    def test_final_freeze_expired_blocks(self):
        receipt={'frozen_at':(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()}
        self.assert_blocked(lambda:validate_freeze(receipt,self.row),'freeze_receipt_stale')
    def test_final_freeze_requires_intake_off(self):
        receipt={'frozen_at':datetime.now(timezone.utc).isoformat(),'writers_off':True,'observers_off':True,
                 'old_host':'old','recovery_generation':self.row['generation'],'source_sha':self.row['source_sha']}
        self.assert_blocked(lambda:validate_freeze(receipt,self.row),'source_freeze_not_verified')
    def test_performance_comparison_uses_numbers(self):
        before={'api_latency_ms':{'median':10},'manager_render_ms':100,'disk_bytes':{'free':1000},'memory_bytes':{'MemAvailable':1000}}
        after=deepcopy(before);after['api_latency_ms']['median']=5
        self.assertEqual(compare(before,after)['measurements']['api_median_ms']['assessment'],'BETTER')


if __name__=='__main__':unittest.main()
