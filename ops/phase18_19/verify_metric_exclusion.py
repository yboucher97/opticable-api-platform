#!/usr/bin/env python3
"""Bounded GET-only native reporting audit; never installs/repairs configuration.

Independent of the TEST Lab lock. Run after TEST Deals have been closed. Only
aggregate counts are printed; per-record IDs/configuration remain root-only.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[2]
ROOT = Path('/var/lib/optibrain/phase18-19')
PRIOR = Path('/var/lib/optibrain/phase16-17')
MODULES = {'Leads', 'Contacts', 'Accounts', 'Deals', 'Service_Locations', 'Services', 'Tasks', 'Cases', 'Installations'}
TITLES = {'Leads': 'Last_Name', 'Contacts': 'Last_Name', 'Accounts': 'Account_Name', 'Deals': 'Deal_Name',
          'Service_Locations': 'Name', 'Services': 'Name', 'Tasks': 'Subject', 'Cases': 'Subject', 'Installations': 'Name'}


def excludes_test(expression):
    """Prove all accepting branches reject OptiBrain_Test=True, not substring presence."""
    if not isinstance(expression, dict):return False
    field = expression.get('field') or {}
    if (isinstance(field, dict) and field.get('api_name') == 'OptiBrain_Test'
            and ((expression.get('comparator') == 'not_equal' and expression.get('value') is True)
                 or (expression.get('comparator') == 'equal' and expression.get('value') is False))):
        return True
    children = expression.get('group')
    if not isinstance(children, list) or not children:return False
    operator = str(expression.get('group_operator') or '').lower()
    if operator == 'and':return any(excludes_test(child) for child in children)
    if operator == 'or':return all(excludes_test(child) for child in children)
    return False


def main():
    if os.geteuid() != 0:raise ValueError('Manual root GET-only verification required')
    os.umask(0o077)
    sys.path.insert(0, str(REPO / 'ops/phase16_17'))
    from inventory import clients
    _, client, _ = clients(REPO)
    reads = 0
    def get(path, query=None):
        nonlocal reads
        reads += 1
        if reads > 130:raise ValueError('Metric verification provider-read bound reached')
        response = client.request('zohoapis', 'GET', path, query=query or {})
        if response.get('status') not in {200, 204} or response.get('ok') is not True:
            raise ValueError('Native metric verification read unavailable')
        # CRM uses 204 for a legitimate empty operating view. Exact report or
        # record reads still fail their required-single-row checks below.
        if response['status'] == 204:
            if response.get('data') not in (None, '', {}):
                raise ValueError('Empty native view returned contradictory content')
            return {}
        return response.get('data') or {}

    original_reports = json.loads((PRIOR / 'metric-reports-verified.json').read_text())
    original_views = json.loads((PRIOR / 'metric-views-verified.json').read_text())
    if len(original_reports) != 37 or set(original_views) != MODULES:
        raise ValueError('Authoritative expected reporting set changed; classify before proceeding')
    registry = json.loads((ROOT / 'ownership.json').read_text())
    if registry.get('schema') != 1 or not registry.get('run'):
        raise ValueError('Deterministic Phase18/19 TEST registry required')
    owned = {identity: row for identity, row in registry.get('records', {}).items()
             if row.get('ownership') == 'TEST_ONLY' and row.get('run') == registry['run'] and row.get('module') in MODULES}
    evidence = {'schema': 1, 'at': datetime.now(timezone.utc).isoformat(), 'run': registry['run'],
                'provider_writes': 0, 'reports': [], 'views': {}, 'test_records': [], 'issues': []}
    for previous in original_reports:
        rows = get('/crm/v8/Reports/' + previous['id']).get('Reports') or []
        if len(rows) != 1 or rows[0].get('module', {}).get('api_name') != previous['module']:
            raise ValueError('Exact native report identity/module changed')
        row = rows[0]
        excluded = excludes_test(row.get('filters'))
        evidence['reports'].append({'id': row['id'], 'module': previous['module'],
                                   'guarantees_test_exclusion': excluded, 'filters': row.get('filters')})
        if not excluded:evidence['issues'].append('REPORT_EXCLUSION_MISSING:' + row['id'])
    for module, previous in original_views.items():
        rows = get('/crm/v8/settings/custom_views/' + previous['id'], {'module': module}).get('custom_views') or []
        if len(rows) != 1:raise ValueError('Exact native operating view unavailable')
        view = rows[0]
        excluded = excludes_test(view.get('criteria'))
        identities, leak = [], []
        complete = False
        for page in range(1, 4):
            result = get('/crm/v8/' + module, {'cvid': previous['id'], 'fields': 'id,OptiBrain_Test', 'per_page': 200, 'page': page})
            rows = result.get('data') or []
            for row in rows:
                identity = str(row['id']); identities.append(identity)
                if row.get('OptiBrain_Test') is True or identity in owned:leak.append(identity)
            if not result.get('info', {}).get('more_records'):
                complete = True;break
        evidence['views'][module] = {'id': view['id'], 'criteria': view.get('criteria'),
            'guarantees_test_exclusion': excluded, 'records_returned': len(identities),
            'test_records_returned': len(leak), 'complete': complete}
        if not excluded or leak or not complete:evidence['issues'].append('LIVE_VIEW_EXCLUSION_ISSUE:' + module)
    active_deals, value = 0, 0
    for identity, lineage in owned.items():
        module = lineage['module']
        fields = ['id', 'OptiBrain_Test', TITLES[module]] + (['Stage', 'Amount'] if module == 'Deals' else [])
        if module in {'Leads', 'Contacts'}:fields.append('First_Name')
        rows = get('/crm/v8/' + module + '/' + identity, {'fields': ','.join(fields)}).get('data') or []
        if len(rows) != 1:raise ValueError('Exact TEST artifact unavailable for metric proof')
        row = rows[0]
        marked = row.get('OptiBrain_Test') is True
        title = str(row.get(TITLES[module]) or '')
        if module in {'Leads', 'Contacts'}:title = str(row.get('First_Name') or '') + ' ' + title
        visible = 'OPTIBRAIN TEST' in title.upper()
        result = {'id': identity, 'module': module, 'native_test_boolean': marked, 'visible_test_marker': visible}
        if not marked or not visible:evidence['issues'].append('TEST_ARTIFACT_MARKER_MISSING:' + identity)
        if module == 'Deals':
            closed = row.get('Stage') == 'Closed Lost'; zero = row.get('Amount') == 0
            result.update(closed_lost=closed, amount_zero=zero)
            active_deals += int(not closed)
            if not zero:value += 1
            if not closed or not zero:evidence['issues'].append('TEST_FORECAST_EXCLUSION_ISSUE:' + identity)
        evidence['test_records'].append(result)
    evidence.update(provider_reads=reads, reports_verified=len(evidence['reports']),
        views_verified=len(evidence['views']), new_and_borrowed_test_records_verified=len(owned),
        synthetic_in_live_views=sum(row['test_records_returned'] for row in evidence['views'].values()),
        active_test_pipeline=active_deals, nonzero_test_deals=value,
        historical_hidden_report_limitations_retained=len(json.loads((PRIOR / 'report-read-limitations.json').read_text())),
        status='PASS' if not evidence['issues'] else 'ISSUE')
    output = ROOT / 'metric-exclusion-current.json'
    output.write_text(json.dumps(evidence, sort_keys=True, ensure_ascii=False, indent=2) + '\n')
    os.chmod(output, 0o600)
    print(json.dumps({key: evidence[key] for key in ['status', 'provider_reads', 'provider_writes', 'reports_verified',
        'views_verified', 'new_and_borrowed_test_records_verified', 'synthetic_in_live_views', 'active_test_pipeline',
        'nonzero_test_deals', 'historical_hidden_report_limitations_retained']}, sort_keys=True))
    if evidence['issues']:raise SystemExit('Native TEST metric exclusion needs bounded review; no configuration was changed')


if __name__ == '__main__':main()
