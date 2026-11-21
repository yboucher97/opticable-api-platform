#!/usr/bin/env python3
"""Run a fixed, offline, development-only work catalogue and emit its ledger view."""
import argparse
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'apps/workflow-api'))
from workflow.automation.autonomy_pilot import Pilot, Task, allowance, cgroup_proof, current, digest
from workflow.automation.operational_recovery import DevelopmentScope
from workflow.automation.recurring_lifecycle import money
from workflow.automation.revenue_brief import quote_scenarios

TASKS = (
    Task('owner-gated-model-review', 100, lane='model'),
    Task('cash-and-recorded-payment-reconciliation', 90),
    Task('quote-inventory-and-exclusive-scenarios', 80, ('cash-and-recorded-payment-reconciliation',)),
    Task('backup-activation-gate', 70),
    Task('persistent-activation', 50, ('backup-activation-gate',), lane='protected'),
)


def cash(data):
    overdue = data['overdue']
    posted = data['posted_mtd']
    return {'overdue_count': len(overdue), 'overdue_cad': format(sum((money(r['balance']) for r in overdue), Decimal()), '.2f'),
            'recorded_mtd_cad': format(sum((money(r['amount']) for r in posted), Decimal()), '.2f'),
            'recorded_mtd_count': len(posted), 'settlement': 'UNVERIFIED', 'source_at': data['books_at']}


def cents(value):
    dollars, point, fraction = value.partition('.')
    if not dollars.isdecimal() or point and (not fraction.isdecimal() or len(fraction) > 2):
        raise ValueError('Expected exact nonnegative CAD amount')
    return int(dollars) * 100 + int(fraction.ljust(2, '0') or '0')


def check_cash(data, out):
    observed = data['overdue']
    posted = data['posted_mtd']
    tests = [
        current(data['books_at'], datetime.now(timezone.utc), 180),
        len({r['id'] for r in observed}) == len(observed) == out['overdue_count'],
        all(r['currency'] == 'CAD' and r['status'] == 'overdue' and cents(r['balance']) > 0 for r in observed),
        sum(cents(r['balance']) for r in observed) == cents(out['overdue_cad']),
        len({r['id'] for r in posted}) == len(posted) == out['recorded_mtd_count'],
        all(r['status'] in {'paid', 'success'} for r in posted),
        current(data['payment_at'], datetime.now(timezone.utc), 180),
        sum(cents(r['amount']) for r in posted) == cents(out['recorded_mtd_cad']),
        out['settlement'] == 'UNVERIFIED' and out['source_at'] == data['books_at'],
    ]
    return {'passed': all(tests), 'check': 'native IDs, exact integer cents and posted-status checks'}


def quotes(data):
    inventory = data['quotes']
    return {'count': len(inventory), 'counts_by_status': dict(Counter(row['status'] for row in inventory)),
            'scenarios': quote_scenarios(inventory, data['scenarios']),
            'source_at': data['quotes_at']}


def check_quotes(data, out):
    rows = {row['id']: row for row in data['quotes']}
    valid = len(rows) == len(data['quotes']) == out['count'] and current(
        out['source_at'], datetime.now(timezone.utc), 180)
    valid &= out['source_at'] == data['quotes_at'] and sum(out['counts_by_status'].values()) == len(rows)
    proposed = data['scenarios']
    observed = out['scenarios']
    if len(observed) != len(proposed):
        return {'passed': False, 'check': 'scenario inventory length'}
    for case, result in zip(proposed, observed):
        ids = case['estimate_ids']
        amount = result['gross_quote_value']
        valid &= result['estimate_ids'] == ids and result['conditional_on_award'] is True
        valid &= result['exclusive_group'] == case.get('exclusive_group')
        expected = None
        if ids and len(ids) == len(set(ids)) and all(
                rid in rows and rows[rid]['review'] and rows[rid]['current_source']
                and rows[rid]['status'] not in {'invoiced', 'expired', 'declined', 'rejected'}
                and rows[rid]['currency'] == case['currency'] for rid in ids):
            expected = sum(cents(rows[rid]['total']) for rid in ids)
        valid &= expected == (cents(amount) if amount is not None else None)
    noveco = [s for s in observed if s['exclusive_group'] == 'Noveco office core']
    valid &= len(noveco) == 2 and len(set(noveco[0]['estimate_ids']) ^ set(noveco[1]['estimate_ids'])) == 2
    return {'passed': bool(valid), 'check': 'unique native quote IDs, independent integer cents and exclusive membership'}


def recovery(data):
    pre = data['backup_preflight']
    proof = data['restore']
    return {'generation': proof['generation'], 'local_restore': proof['result'],
            'encrypted_remote_readback': pre['state']['verification_status'], 'databases': proof['databases_restored'],
            'offline_custody_verified': pre['state']['offline_restore_verified'],
            'activation': 'BLOCKED' if pre['state']['offline_restore_verified'] is not True else 'APPROVAL_REQUIRED'}


def check_recovery(data, out):
    pre = data['backup_preflight']
    proof = data['restore']
    verified = (proof['source_sha256'] == pre['state']['source_sha256']
                and proof['generation'] == pre['state']['generation'] == out['generation']
                and proof['files_verified'] == pre['files']
                and proof['databases_restored'] == len(pre['sqlite_inventory']) == out['databases']
                and proof['source_extraction'] == out['local_restore'] == 'PASS'
                and 'no services started' in proof['scope']
                and pre['encrypted_local_rehash'] == 'PASS'
                and out['encrypted_remote_readback'] == 'download_hash_verified'
                and out['offline_custody_verified'] is False and out['activation'] == 'BLOCKED')
    return {'passed': verified, 'check': 'exact generation and independently measured archive, database and ciphertext receipts'}


def assert_network_denied():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM):
            pass
    except OSError as error:
        if error.errno in {1, 13, 97}:
            return
        raise
    raise ValueError('Independent INET denial required')


def refresh_resources(sample, path):
    def pressure(kind):
        values = Path('/proc/pressure', kind).read_text().splitlines()[0].split()
        return float(next(v.split('=')[1] for v in values if v.startswith('avg10=')))

    ram = Path('/proc/meminfo').read_text().splitlines()
    units = list(sample['maintenance'])
    try:
        output = subprocess.check_output(
            ['/usr/bin/systemctl', 'show', *units, '-p', 'Id', '-p', 'ActiveState', '-p', 'Result'], text=True, timeout=3)
        states = [dict(line.split('=', 1) for line in part.splitlines()) for part in output.strip().split('\n\n')]
        maintenance = {s['Id'].removesuffix('.service'): s['ActiveState'] for s in states}
        results = {s['Id'].removesuffix('.service'): s['Result'] for s in states}
    except (subprocess.SubprocessError, KeyError, ValueError):
        maintenance, results = {}, {}
    return {**sample, 'filesystem_bytes': {'free': shutil.disk_usage(path).free}, 'load': list(os.getloadavg()),
            'memory_kib': {'MemAvailable': int(next(s.split()[1] for s in ram if s.startswith('MemAvailable:')))},
            'psi_some_avg10_pct': {k: pressure(k) for k in ('cpu', 'memory', 'io')}, 'maintenance': maintenance, 'maintenance_results': results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace', type=Path)
    parser.add_argument('--source', required=True)
    parser.add_argument('--paused', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    git = ['/usr/bin/git', '--no-optional-locks', '-C', str(ROOT)]
    if subprocess.check_output([*git, 'rev-parse', 'HEAD'], text=True, timeout=5).strip() != args.source:
        raise ValueError('Source commit mismatch')
    if subprocess.check_output([*git, 'status', '--porcelain'], text=True, timeout=5).strip():
        raise ValueError('Pilot requires a clean exact-source checkout')
    controls = cgroup_proof()
    assert_network_denied()
    scope = DevelopmentScope(args.workspace)
    scope.verify(datetime.now(timezone.utc))
    path = scope.path('input.json')
    if path.stat().st_size > 1024 * 1024:
        raise ValueError('Input bound exceeded')
    data = json.loads(path.read_bytes())
    sample = json.loads(scope.path('admission.json').read_bytes())
    plan = Pilot(scope, TASKS, goal='Issue 174: verify current cash evidence and non-production continuation',
                 source=args.source, input_hash=digest(data))
    actions = {t.name: f for t, f in zip(TASKS[1:4], (cash, quotes, recovery))}
    checks = {t.name: f for t, f in zip(TASKS[1:4], (check_cash, check_quotes, check_recovery))}
    result = plan.run(lambda: refresh_resources(sample, scope.root),
                      {name: lambda f=f: f(data) for name, f in actions.items()},
                      {name: lambda out, f=f: f(data, out) for name, f in checks.items()},
                      paused=args.paused)
    result['resource_enforcement'] = controls | {'inet_socket_denied': True}
    status, retry_at = allowance(data['allowance'], datetime.now(timezone.utc), windows=(10080,))
    result['included_usage_window'] = {'assessment': status, 'next_eligible_observation': retry_at.isoformat() if retry_at else None}
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
