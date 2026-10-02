#!/usr/bin/env python3
"""Validate supplied recovery milestones; no service/provider actions or proof claim."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path

MILESTONES=('incident_start','replacement_ready','verified_restore','contained_boot',
            'provider_reads_ready','dns_cutover_start','authenticated_owner_ready')


def measure(values):
    if not isinstance(values,dict) or not values or set(values)-set(MILESTONES):raise ValueError('Unknown or empty milestone set')
    if 'incident_start' not in values:raise ValueError('Incident start required')
    parsed={}
    previous=None
    for name in MILESTONES:
        if name not in values:continue
        stamp=datetime.fromisoformat(values[name].replace('Z','+00:00'))
        if stamp.utcoffset() is None:raise ValueError('Offset-aware recorded timestamps required')
        stamp=stamp.astimezone(timezone.utc)
        if previous is not None and stamp<previous:raise ValueError('Milestones run backwards')
        parsed[name]=stamp;previous=stamp
    elapsed={name:round((stamp-parsed['incident_start']).total_seconds(),3) for name,stamp in parsed.items()}
    complete=set(parsed)==set(MILESTONES)
    return dict(schema=1,status='COMPLETE RECORDED TIMELINE' if complete else 'PARTIAL RECORDED TIMELINE',
                independently_proven=False,milestones_utc={k:v.isoformat() for k,v in parsed.items()},
                elapsed_seconds=elapsed,rto_seconds=elapsed.get('authenticated_owner_ready') if complete else None)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--input',type=Path,required=True);parser.add_argument('--output',type=Path)
    args=parser.parse_args();value=measure(json.loads(args.input.read_text()))
    text=json.dumps(value,indent=2)+'\n'
    if args.output:args.output.write_text(text)
    else:print(text,end='')


if __name__=='__main__':main()
