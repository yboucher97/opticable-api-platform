#!/usr/bin/env python3
"""Replay an explicit evidence audit in an isolated copy of the existing journal.

Never opens a provider, changes a source cache, or rewrites an overnight report.
The audit supplies exact object references and annotated source facts; business
state and ranking use the same contract as Manager and Sales.
"""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'apps/workflow-api'))
from workflow.automation.lifecycle_projection import collect_states, reconcile_priority
from workflow.automation.lifecycle_truth import context_key, eligible_today, priority_order
from workflow.automation.manager_store import ManagerStore
from workflow.automation.manager_intelligence import build_manager


def read(path):
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError('Bounded local artifact required')
    return json.loads(path.read_text())


def replay(directory, audit):
    now = datetime.fromisoformat(audit['as_of'])
    inputs = {p.stem: read(p) for p in directory.glob('*.json') if p.stem in
              {'business', 'manager', 'sales-conversations', 'sales-intelligence', 'trigger-intelligence', 'status'}}
    snapshot = inputs.setdefault('business', {}).setdefault('snapshot', {})
    before = collect_states(inputs, now)
    snapshot.setdefault('books_estimate_index', {}).update(audit.get('supplemental_estimates', {}))
    inputs['business_events'] = audit['events']
    inputs['lifecycle_coverage'] = audit.get('coverage', {})
    with TemporaryDirectory(prefix='lifecycle-replay-') as tmp:
        store = ManagerStore(Path(tmp) / 'phase12-autonomy.db')
        for row in read(directory / 'optimization_records.json'):
            record = json.loads(row['record']) if isinstance(row['record'], str) else row['record']
            detail = json.loads(row['detail']) if isinstance(row['detail'], str) else row['detail']
            store.record(record, detail, revision=row['revision'])
        states = collect_states(inputs, now, store, record_facts=True)
        manager = build_manager(inputs, store, now, active_ids=inputs.get('manager', {}).get('active_priority_ids'),
                                crosswalk=inputs.get('manager', {}).get('crosswalk', {}))
        contexts = []; ranked = []
        for row in audit['contexts']:
            key = context_key(row['context']); state = states.get(key, {})
            reviewed = reconcile_priority({'targets': [row['context']], 'priority_id': key,
                         'what': row['label'], 'next_action': row.get('before_action'), 'readiness': 'CURRENT',
                         'status': 'OWNER_REVIEW', 'urgency': row.get('urgency', 'MEDIUM')}, {key: state} if state else {})
            contexts.append({**row, 'before_cached_state': before.get(key), 'after': state,
                             'eligible_today': eligible_today(reviewed, now)})
            if eligible_today(reviewed, now):
                ranked.append({**reviewed, 'label': row['label']})
        ranked.sort(key=lambda r: priority_order(r, now))
        priorities = manager['priorities']
        summary = {'as_of': audit['as_of'], 'read_only': True, 'provider_reads': 0, 'provider_writes': 0,
                   'contexts': contexts, 'corrected_top_actions': ranked[:5],
                   'canonical_priority_audit': [{'priority_id': p['priority_id'], 'targets': p['targets'],
                        'current_state': p.get('current_state'), 'next_action': p['next_action'],
                        'actionability': p['actionability'], 'reason_code': p['reason_code'], 'status': p['status']}
                       for p in priorities],
                   'manager_today_count': len(manager['today']), 'manager_projection_bytes': len(json.dumps(manager).encode()),
                   'manager_today':[{k:r.get(k) for k in ('what','targets','domain','next_action','reason_code','actionability','due_at')} for r in manager['today']],
                   'retained_priority_count': len(store.rows('optibrain.business_priority')),
                   'retained_proposal_count': len(store.rows()),
                   'limitations': audit['limitations']}
        return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--audit', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = replay(args.directory, read(args.audit))
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'contexts': len(result['contexts']), 'corrected_actions': len(result['corrected_top_actions']),
                      'retained_priorities': result['retained_priority_count'], 'manager_bytes': result['manager_projection_bytes'],
                      'provider_writes': 0}))
