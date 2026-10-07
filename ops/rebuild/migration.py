"""Prepared cutover/rollback records and target-only final generation sync."""
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import sqlite3

from common import RebuildError, atomic_json, database_snapshot, digest, now, path_at, private_file, quote_ident, require
from recovery import select_generation

IMMUTABLE_TABLES={'action_envelopes','action_evidence','lifecycle_intents','lifecycle_evidence',
                  'optimization_records','manager_feedback','manager_learning','manager_events',
                  'website_preview_observations','automation_audit','automation_event_history',
                  'intake_events','feedback_events','form_receipts','connector_receipts',
                  'service_events','manager_receipts','optimization_reviews'}


def rollback_manifest(old_host,new_host,dns,recovery):
    require(bool(old_host) and bool(new_host) and old_host!=new_host,'distinct_hosts_required')
    require(dns.get('record_id') and dns.get('old_content') and dns.get('ttl') is not None
            and type(dns.get('proxied')) is bool,'complete_dns_before_state_required')
    return {'schema':1,'at':now(),'old_host':old_host,'new_host':new_host,'dns_before':dns,
        'dns_proposed':{**dns,'content':new_host},'recovery':recovery,'owner_approval':None,
        'cutover_ready':False,'operations':['Freeze source writers and observers with reviewed existing stop helpers',
            'Capture final VERIFIED recovery and export its exact snapshot catalog',
            'Restore final generation on replacement; compare immutable history; verify privately',
            'Owner reviews report and approves exact old/new record, source, recovery and rollback',
            'Switch only approved DNS/origin target; validate public health, Access denial and owner login',
            'Keep writers OFF during initial monitoring; keep old host frozen and intact'],
        'rollback':['Freeze both hosts and reconcile any post-cutover inbound events/provider effects',
            'Restore exact previous DNS content/TTL/proxy state',
            'Verify public version/auth and owner route on old host',
            'Keep new state for reconciliation; never overwrite the old DB with stale state'],
        'divergence_risk':'New inbound receipts after cutover require a verified new-host backup and reconciliation before switching back; writers OFF does not prevent new intake',
        'old_host_retention':{'recommended_days':14,'minimum_review_days':7,'automatic_termination':False},
        'dns_mutations_performed':0,'production_migration':0}


def assert_immutable_superset(old_path,new_path):
    def rows(path):
        output={}
        with sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True) as db:
            names={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table in sorted(names & IMMUTABLE_TABLES):
                output[table]={digest([{'blob_hex':v.hex()} if isinstance(v,bytes) else v for v in row])
                               for row in db.execute('SELECT * FROM '+quote_ident(table))}
        return output
    old=rows(old_path);new=rows(new_path)
    require(all(table in new and value <= new[table] for table,value in old.items()),'final_sync_lost_immutable_history')
    return {'tables_checked':len(old),'rows_retained':sum(map(len,old.values()))}


def validate_freeze(receipt,row):
    try: at=datetime.fromisoformat(receipt['frozen_at'].replace('Z','+00:00'))
    except Exception: raise RebuildError('invalid_source_freeze_receipt')
    current=datetime.now(timezone.utc)
    require(at.tzinfo is not None and timedelta(seconds=-60)<=current-at<=timedelta(hours=1),'source_freeze_receipt_stale')
    require(receipt.get('writers_off') is True and receipt.get('observers_off') is True and receipt.get('intake_off') is True
            and receipt.get('recovery_generation')==row['generation'] and receipt.get('source_sha')==row['source_sha']
            and receipt.get('old_host'),'source_freeze_not_verified')
    generation=datetime.strptime(row['generation'],'%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc)
    require(generation>=at-timedelta(seconds=1),'recovery_predates_source_freeze')
    return True


def final_sync(engine,freeze):
    """Target-only, serialized generation switch. Both generations are retained."""
    private_file(freeze);receipt=json.loads(Path(freeze).read_text())
    with engine.locked(final_sync=True) as state:
        saved=json.loads(state.read_text());previous=saved['generation']
        require(bool(previous),'initial_restore_required_before_final_sync')
        require(receipt.get('old_host')!=engine.host.run(['hostname','-f']),'final_sync_must_target_replacement')
        if previous==engine.row['generation']:
            # Completed sync reruns validate the target; they never apply a delta
            # twice or need a new source freeze for a readback-only verification.
            require(saved.get('previous_generation'),'final_sync_receipt_missing')
            return engine.apply(state)
        require(engine.row['generation']>previous,'final_sync_requires_newer_generation')
        validate_freeze(receipt,engine.row)
        old=engine.data/'generations'/previous
        try:
            with engine.operation('final_sync_preflight',{'previous_generation':previous},
                    {'generation':engine.row['generation'],'source_frozen':True}) as result:
                engine.safety()
                staged,manifest=engine.stage()
                old_receipt=json.loads((old/'verified.json').read_text())
                require(set(old_receipt['databases'])<=set(engine.row['databases']),'final_sync_missing_previous_store')
                histories=[]
                for name in engine.row['databases']:
                    if (old/name).is_file():histories.append(assert_immutable_superset(old/name,staged/name))
                require(engine.host.run(['git','-c','safe.directory=/opt/opticable-api-platform','-C',
                        '/opt/opticable-api-platform','rev-parse','HEAD'])==engine.row['source_sha'],
                        'source_changed_during_migration_rebuild_review_required')
                saved.update(pending_generation=engine.row['generation'],previous_generation=previous,completed=False)
                atomic_json(state,saved)
                result.update(immutable_history=histories,source_freeze='VERIFIED',previous_generation=previous,
                              freeze_receipt_sha256=digest(receipt))
            # A crash after any unmount is recoverable: a target may be bound to
            # old, bound to new, or empty. Anything else is refused. No deletes.
            from recovery import STATE_ROOTS
            with engine.operation('final_sync_switch',{'generation':previous},{'generation':engine.row['generation']}) as result:
                switched=[]
                for canonical in STATE_ROOTS:
                    target=path_at(engine.root,canonical);source=path_at(old,'/state'+canonical)
                    replacement=path_at(staged,'/state'+canonical)
                    if engine.host.same_mount(replacement,target):continue
                    if engine.host.same_mount(source,target):
                        engine.host.run(['umount',target]);switched.append(canonical)
                    else:
                        require(not os.path.ismount(target) and not any(target.iterdir()),
                                'old_mount_identity_mismatch')
                result.update(old_generation_retained=previous,services='STOPPED',unmounted=switched,data_deletions=0)
            return engine.apply(state)
        except BaseException as exc:
            # Even a preflight failure contains the replacement, retaining both
            # staged data and the interrupted-switch receipt for a safe rerun.
            engine.failure(exc)
            raise
