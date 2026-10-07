#!/usr/bin/env python3
"""Owner entry point. Restore stops at a reviewable report, before traffic cutover."""
import argparse
import json
import os
from pathlib import Path
import sys

from common import REPO, RebuildError, atomic_json, now, private_file, require, trusted_manifest


def load(path, protected=False):
    if protected:private_file(path)
    return json.loads(Path(path).read_text())


def status(report):
    print('OPTIBRAIN REBUILD')
    for name in ('OS','SOURCE','DATABASES','MANAGER','AUDIT','KNOWLEDGE','SECRETS','SYSTEMD','PROXY','BACKUPS'):
        check=report.get('checks',{}).get(name,{})
        value=check.get('status','NOT RUN')
        if name=='DATABASES' and value=='PASS':
            value=str(check['evidence']['passed'])+'/'+str(check['evidence']['expected'])+' PASS'
        print(name+': '+value)
    for name,value in report.get('checks',{}).get('PROVIDERS',{}).items():print(name+': '+value['status'])
    knowledge=report.get('checks',{}).get('KNOWLEDGE',{})
    print('DECISION CARDS: '+knowledge.get('status','NOT RUN'))
    print('PRIORITIES: '+knowledge.get('status','NOT RUN'))
    print('LEARNING: '+knowledge.get('status','NOT RUN'))
    print('AUTHORITY: '+report.get('authority','UNKNOWN'))
    print('READY FOR OWNER CUTOVER: '+('YES' if report.get('ready_for_owner_cutover') else 'NO'))
    for name,check in report.get('checks',{}).items():
        if isinstance(check,dict) and check.get('blocker'):print('BLOCKER '+name+': '+check['blocker'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    inspect=sub.add_parser('inspect');inspect.add_argument('--output',type=Path,required=True)
    catalog=sub.add_parser('catalog');catalog.add_argument('--archive',type=Path,required=True)
    catalog.add_argument('--upload-state',type=Path,default=Path('/var/lib/optibrain/phase2a/state.json'))
    catalog.add_argument('--workspace',type=Path,default=Path('/dev/shm'));catalog.add_argument('--output',type=Path,required=True)
    for name in ('plan','restore','verify','final-sync'):
        p=sub.add_parser(name);p.add_argument('--manifest',type=Path,default=REPO/'docs/rebuild/current-host-manifest.json')
        p.add_argument('--catalog',type=Path,required=True);p.add_argument('--generation',default='latest-verified')
        p.add_argument('--archive',type=Path);p.add_argument('--data-root',default='/var/lib/optibrain-data')
        p.add_argument('--migration',action='store_true');p.add_argument('--freeze-receipt',type=Path)
        if name=='plan':p.add_argument('--output',type=Path)
    p=sub.add_parser('providers');p.add_argument('--manifest',type=Path,required=True)
    p=sub.add_parser('baseline');p.add_argument('--output',type=Path,required=True);p.add_argument('--manager-ms',type=float)
    p=sub.add_parser('compare');p.add_argument('--before',type=Path,required=True);p.add_argument('--after',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p=sub.add_parser('migration-plan');p.add_argument('--old-host',required=True);p.add_argument('--new-host',required=True)
    p.add_argument('--dns-state',type=Path,required=True);p.add_argument('--recovery',required=True);p.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();os.umask(0o077)
    if args.command=='inspect':
        from inventory import collect
        print(json.dumps(collect(args.output)));return 0
    if args.command=='catalog':
        from recovery import build_catalog
        private_file(args.archive);private_file(args.upload_state)
        value=build_catalog(args.archive,load(args.upload_state),args.workspace);atomic_json(args.output,value)
        print(json.dumps({'generation':value['generations'][0]['generation'],'database_count':len(value['generations'][0]['databases']),'output':str(args.output)}));return 0
    if args.command=='providers':
        from providers import probe_all
        print(json.dumps(probe_all(manifest=load(args.manifest))));return 0
    if args.command=='baseline':
        from performance import baseline
        atomic_json(args.output,baseline(args.manager_ms));print(json.dumps({'output':str(args.output)}));return 0
    if args.command=='compare':
        from performance import compare
        atomic_json(args.output,compare(load(args.before),load(args.after)));return 0
    if args.command=='migration-plan':
        from migration import rollback_manifest
        atomic_json(args.output,rollback_manifest(args.old_host,args.new_host,load(args.dns_state),args.recovery));return 0
    from engine import Engine, restore_plan
    if args.command!='plan':trusted_manifest(args.manifest)
    manifest=load(args.manifest);catalog=load(args.catalog,protected=args.command!='plan')
    if args.command=='plan':
        value=restore_plan(manifest,catalog,args.generation,args.data_root)
        if args.output:atomic_json(args.output,value)
        print(json.dumps(value,indent=2));return 0
    require(args.archive is not None,'selected_plaintext_archive_required')
    engine=Engine(manifest,catalog,args.archive,pin=args.generation,data_root=args.data_root,migration=args.migration)
    if args.command=='verify':
        report=engine.verify()
    elif args.command=='final-sync':
        from migration import final_sync
        require(args.freeze_receipt is not None,'source_freeze_receipt_required');report=final_sync(engine,args.freeze_receipt)
    else:report=engine.run()
    status(report);return 0 if report['ready_for_owner_cutover'] else 1


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as exc:
        blocker=str(exc) if isinstance(exc,RebuildError) else type(exc).__name__
        print('OPTIBRAIN REBUILD STOPPED: '+blocker,file=sys.stderr)
        print(json.dumps({'schema':1,'type':'optibrain.rebuild.error','at':now(),'blocker':blocker,
            'ready_for_owner_cutover':False,'authority':'UNKNOWN','dns_changes':0,'production_migration':0}))
        print('READY FOR OWNER CUTOVER: NO',file=sys.stderr);raise SystemExit(1)
