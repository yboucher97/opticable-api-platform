#!/usr/bin/env python3
"""Manual Phase19 provider TEST proof, after durable Phase18 PASS only.

Reuses the isolated Phase18 TEST policy/registry and exact journal/R2 fences.
Financial events are explicit TEST status-equivalent fixtures; this tool never
creates an Estimate, Invoice, payment, or customer communication. Replay mode
performs GET verification only and cannot rewind intermediate CRM transitions.
"""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parents[2]
ROOT = Path('/var/lib/optibrain/phase18-19')
MARKER = 'OPTIBRAIN TEST — PHASE 18'
TORONTO = ZoneInfo('America/Toronto')


def imports():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from live_lab import lab, activate, CONTROL
    instance = lab()
    from workflow.automation import operational_lifecycle as operations
    from workflow.automation.lifecycle import site_fields
    from workflow.automation.lifecycle_control import trusted_json
    from test_lab import atomic
    checkpoint = trusted_json(Path('/var/lib/optibrain/customer-communications/phase18-checkpoint.json'))
    if checkpoint.get('phase18') != 'PASS' or checkpoint.get('safety_critical_failures') != 0:
        raise ValueError('Phase18 critical gates must pass before Phase19 provider TEST work')
    if not instance.state.get('parents'):
        raise ValueError('Phase18 independently owned TEST parents are required')
    return instance, activate, CONTROL, operations, site_fields, atomic


def create(instance, key, module, row):
    key = 'phase19-' + key
    old = instance.state['operations'].get(key)
    if old:
        if old.get('state') != 'verified':
            raise ValueError('Existing Phase19 create attempt requires independent reconciliation')
        actual = instance.crm(module, old['provider_id'])
        entry = instance.ownership['records'].get(actual['id'], {})
        if entry.get('module') != module or entry.get('run') != instance.state['run']:
            raise ValueError('Existing Phase19 effect has conflicting TEST ownership')
        return actual
    return instance.create(key, module, row)


def update(instance, key, module, identity, patch, scope=None):
    key = 'phase19-' + key
    old = instance.state['operations'].get(key)
    if old:
        if old.get('state') != 'verified':
            raise ValueError('Existing Phase19 update attempt requires independent reconciliation')
        with instance.journal.connect() as db:
            source = db.execute('SELECT envelope FROM lifecycle_intents WHERE action_id=?',
                                (old['action_id'],)).fetchone()
        if not source:
            raise ValueError('Existing Phase19 update lost immutable intent')
        operation = json.loads(source[0])
        if (operation['path'] != '/crm/v8/' + module + '/' + identity
                or operation['body']['data'] != [{'id': identity, **patch}]):
            raise ValueError('Existing Phase19 update intent changed')
        # Later native status changes are authoritative; never replay the old
        # Scheduled/Failed/etc. patch over a completed or rescheduled visit.
        return instance.crm(module, identity)
    return instance.update(key, module, identity, patch, scope=scope)


def task(instance, key, deal_id, contact_id, label, description, due):
    return create(instance, key, 'Tasks', {'Subject': MARKER + ' — ' + label,
        'What_Id': {'id': deal_id}, '$se_module': 'Deals', 'Who_Id': {'id': contact_id},
        'Status': 'Not Started', 'Due_Date': due, 'Description': MARKER + ' — ' + description,
        'Send_Notification_Email': False, 'OptiBrain_Test': True})


def deal(instance, key, parents, site_id, label, due):
    return create(instance, key, 'Deals', {'Deal_Name': MARKER + ' — Phase19 ' + label,
        'Account_Name': {'id': parents['account_id']}, 'Contact_Name': {'id': parents['contact_id']},
        'Service_Location': {'id': site_id}, 'Stage': 'Contracts In Progress',
        'Closing_Date': due, 'Amount': 0, 'Service_Types': 'Structured Cabling',
        'OptiBrain_Test': True, 'Description': MARKER + ' — TEST accepted-status equivalent; no Finance transaction.'})


def context(instance, operations, visit, scenario, parents):
    rows = [instance.crm('Services', value) for value in scenario['service_ids']]
    result = operations.installation_context(visit, services=rows,
        sites=[instance.crm('Service_Locations', scenario['site_id'])],
        accounts=[instance.crm('Accounts', parents['account_id'])],
        deals=[instance.crm('Deals', scenario['deal_id'])],
        contacts=[instance.crm('Contacts', parents['contact_id'])],
        links=instance.lists('Installation_X_Services', 'id,Linked_Installation,Linked_Service'),
        deal_id=scenario['deal_id'])
    if result['decision'] != 'PREPARE_INTERNAL':
        raise ValueError('Operational TEST native association is incomplete: ' + result['reason'])
    if set(result['service_ids']) != set(scenario['service_ids']):
        raise ValueError('Operational TEST Service association changed')
    return result, rows


def visit(instance, key, scenario, label):
    record = create(instance, key, 'Installations', {'Name': MARKER + ' — Phase19 ' + label,
        'Linked_Service': {'id': scenario['service_ids'][0]}, 'Installation_Status': 'Requested',
        'Instructions_Notes': MARKER + ' — Human scheduling required; use TEST main entrance.',
        'OptiBrain_Test': True})
    for service_id in scenario['service_ids']:
        create(instance, key + '-link-' + service_id, 'Installation_X_Services',
            {'Name': MARKER + ' — Phase19 Service visit', 'Linked_Installation': {'id': record['id']},
             'Linked_Service': {'id': service_id}})
    return record


def completion(instance, operations, scenario, record, parents, fixture, *, mutable=False, key):
    record = update(instance, key + '-schedule', 'Installations', record['id'],
        {'Installation_Status': 'Scheduled', 'Scheduled_Date': fixture['scheduled_at'],
         'Assigned_To': 'Opticable TEST technician',
         'Instructions_Notes': MARKER + ' — TEST human-selected date/technician, main entrance.'}, scope='crm.test.transition')
    record = update(instance, key + '-in-progress', 'Installations', record['id'],
                    {'Installation_Status': 'In Progress'}, scope='crm.test.transition')
    record = update(instance, key + '-complete', 'Installations', record['id'],
        {'Installation_Status': 'Completed', 'Completion_Notes': MARKER + ' — TEST completion: scope checked, cabling test evidence recorded.'},
        scope='crm.test.transition')
    proof, rows = context(instance, operations, record, scenario, parents)
    planned = operations.installation_progress_plan(record, proof, services=rows,
        owner_trigger=True, completed_at=fixture['completed_at'],
        mutable_service_ids=set(scenario['service_ids']) if mutable else set(),
        now=datetime.now(timezone.utc))
    if planned['decision'] != 'OBSERVE' or planned.get('activate_services') is not True:
        raise ValueError('Operational TEST completion cannot safely progress')
    for change in planned['patches']:
        update(instance, key + '-service-' + change['id'], 'Services', change['id'],
               change['patch'], scope='crm.test.transition')
    billing = task(instance, key + '-billing', scenario['deal_id'], parents['contact_id'],
        'Create / send TEST Invoice', 'Work complete; human Finance Invoice creation; no automatic financial action.', fixture['due_date'])
    scenario.setdefault('completion', {})[record['id']] = planned
    scenario.setdefault('billing_task_ids', []).append(billing['id'])
    scenario['billing_task_ids'] = sorted(set(scenario['billing_task_ids']))
    instance.save()
    return record, proof


def accepted_fixture(instance, operations, scenario, parents):
    native_deal = instance.crm('Deals', scenario['deal_id'])
    result = operations.accepted_work_plan(
        estimate={'transaction_id': '9900018190001', 'status': 'accepted',
                  'account_id': parents['account_id'], 'deal_id': scenario['deal_id'], 'site_id': scenario['site_id']},
        deal=native_deal, account=instance.crm('Accounts', parents['account_id']),
        contact=instance.crm('Contacts', parents['contact_id']), site=instance.crm('Service_Locations', scenario['site_id']),
        services=instance.lists('Services', 'id,Name,Linked_Deal,Linked_Service_Location,Service_Type,Service_Stage,OptiBrain_Test'))
    if result['decision'] != 'PREPARE_INTERNAL':
        raise ValueError('TEST accepted-status fixture cannot be planned safely')
    return {'source_kind': 'TEST_ONLY_STATUS_EQUIVALENT', 'actual_finance_transaction_created': False, 'plan': result}


def scenario_a(instance, operations, site_fields, atomic, fixture):
    p = instance.state['parents']; scenarios = instance.state.setdefault('operational_scenarios', {})
    if scenarios.get('A', {}).get('complete'):return
    scenario = scenarios.setdefault('A', {'scenario': 'NEW_SITE_ONE_SERVICE', 'service_ids': []})
    address = {'street': '195 TEST PHASE 19 Avenue', 'unit': 'Suite 19', 'city': 'Montréal',
               'province': 'QC', 'postal_code': 'H1A 1A1', 'country': 'Canada'}
    sites = instance.lists('Service_Locations', 'id,Name,Linked_Account,' + ','.join(site_fields(address)))
    match = operations.operational_site_match(sites, p['account_id'], address)
    if match['decision'] == 'HUMAN':raise ValueError('New TEST site needs reconciliation')
    if match['decision'] == 'REUSE':
        site = match['record']
        if site['id'] not in instance.ownership['records']:raise ValueError('TEST site reuse lacks run ownership')
    else:
        site = create(instance, 'a-site', 'Service_Locations', {'Name': MARKER + ' — Phase19 Site A',
            'Linked_Account': {'id': p['account_id']}, 'Primary_Contact': {'id': p['contact_id']},
            'OptiBrain_Test': True, **site_fields(address)})
    scenario['site_id'] = site['id']; instance.save()
    opportunity = deal(instance, 'a-deal', p, site['id'], 'A accepted cabling', fixture['due_date'])
    scenario['deal_id'] = opportunity['id']; instance.save()
    scenario['accepted'] = accepted_fixture(instance, operations, scenario, p)
    service_plan = scenario['accepted']['plan']['services'][0]
    if service_plan['decision'] == 'REUSE':
        service = service_plan['record']
        if service['id'] not in instance.ownership['records']:raise ValueError('Durable TEST Service lacks lineage')
    else:
        service = create(instance, 'a-service', 'Services', {'Name': MARKER + ' — Phase19 Structured Cabling',
            'Linked_Service_Location': {'id': site['id']}, 'Linked_Deal': {'id': opportunity['id']},
            'Service_Type': 'Cabling Installation', 'Service_Stage': 'Ready for Scheduling', 'OptiBrain_Test': True})
    scenario['service_ids'] = [service['id']]; instance.save()
    # Reuse the existing Account/General trees; make only the needed Site and Contracts.
    folder = instance.folder('phase19-a-site-folder', MARKER + ' — Phase19 Site A', p['workdrive']['account'])
    contracts = instance.folder('phase19-a-contracts', 'Contracts', folder['id'])
    scenario['workdrive'] = {'site': folder['id'], 'contracts': contracts['id']}
    update(instance, 'a-folder-link', 'Service_Locations', site['id'],
        {'Service_Location_Workdrive_Folder_ID': folder['id'],
         'Service_Location_Workdrive_Folder_URL': 'https://workdrive.zoho.com/folder/' + folder['id']})
    scenario['contract'] = {'state': 'PREPARE_ONLY', 'external_send': False,
        'account_id': p['account_id'], 'contact_id': p['contact_id'], 'deal_id': opportunity['id'],
        'site_id': site['id'], 'service_ids': scenario['service_ids'], 'folder_id': contracts['id']}
    atomic(ROOT / 'phase19-a-contract-context.json', scenario['contract'])
    record = visit(instance, 'a-installation', scenario, 'A cabling visit')
    scenario['installation_id'] = record['id']; instance.save()
    scheduling = task(instance, 'a-scheduling-task', opportunity['id'], p['contact_id'],
        'Schedule TEST installation A', 'Human scheduling and site access decision required.', fixture['due_date'])
    completion(instance, operations, scenario, record, p, fixture, mutable=True, key='a')
    update(instance, 'a-scheduling-complete', 'Tasks', scheduling['id'], {'Status': 'Completed'})
    scenario['complete'] = True; instance.save()


def scenario_b(instance, operations, fixture):
    p = instance.state['parents']; scenarios = instance.state.setdefault('operational_scenarios', {})
    if scenarios.get('B', {}).get('complete'):return
    scenario = scenarios.setdefault('B', {'scenario': 'EXISTING_SITE_DURABLE_SERVICE_ADDITIONAL_WORK',
        'site_id': p['site_id'], 'service_ids': [p['service_id']]})
    service = instance.crm('Services', p['service_id'])
    if service.get('Service_Stage') != 'Active':raise ValueError('Expected existing TEST Active Service for additional work')
    scenario.setdefault('service_before', {key: service.get(key) for key in ('id', 'Linked_Deal', 'Service_Stage',
        'Modified_Time', 'OptiBrain_Installed_On', 'OptiBrain_Last_Service_On')})
    opportunity = deal(instance, 'b-deal', p, p['site_id'], 'B existing Service expansion', fixture['due_date'])
    scenario['deal_id'] = opportunity['id']; instance.save()
    scenario['accepted'] = accepted_fixture(instance, operations, scenario, p)
    planned = scenario['accepted']['plan']['services']
    if len(planned) != 1 or planned[0]['decision'] != 'REUSE' or planned[0]['record']['id'] != p['service_id']:
        raise ValueError('Additional accepted work must reuse existing durable TEST Service')
    record = visit(instance, 'b-installation', scenario, 'B additional work visit')
    scenario['installation_id'] = record['id']; instance.save()
    completion(instance, operations, scenario, record, p, fixture, mutable=False, key='b')
    actual = instance.crm('Services', p['service_id'])
    if any(actual.get(key) != value for key, value in scenario['service_before'].items()):
        raise ValueError('Durable TEST Service was changed instead of reused read-only')
    scenario['complete'] = True; instance.save()


def scenario_c(instance, operations, fixture):
    p = instance.state['parents']; scenarios = instance.state.setdefault('operational_scenarios', {})
    if scenarios.get('C', {}).get('complete'):return
    scenario = scenarios.setdefault('C', {'scenario': 'BLOCKED_RETURN_VISIT_COMPLETION',
        'site_id': p['site_id'], 'service_ids': [p['service_id']]})
    opportunity = deal(instance, 'c-deal', p, p['site_id'], 'C blocked/return work', fixture['due_date'])
    scenario['deal_id'] = opportunity['id']; instance.save()
    scenario['accepted'] = accepted_fixture(instance, operations, scenario, p)
    original = visit(instance, 'c-original-installation', scenario, 'C original blocked visit')
    scenario['installation_id'] = original['id']; instance.save()
    original = update(instance, 'c-schedule', 'Installations', original['id'],
        {'Installation_Status': 'Scheduled', 'Scheduled_Date': fixture['scheduled_at'],
         'Assigned_To': 'Opticable TEST technician'}, scope='crm.test.transition')
    original = update(instance, 'c-blocked', 'Installations', original['id'],
        {'Installation_Status': 'Failed', 'Instructions_Notes': MARKER + ' — No site access; customer unavailable.'}, scope='crm.test.transition')
    proof, rows = context(instance, operations, original, scenario, p)
    blocked = operations.installation_progress_plan(original, proof, services=rows)
    if blocked['decision'] != 'OBSERVE' or blocked.get('activate_services') is not False:
        raise ValueError('Blocked TEST visit incorrectly activates Service')
    original = update(instance, 'c-revisit-required', 'Installations', original['id'],
        {'Installation_Status': 'Revisit Required', 'Instructions_Notes': MARKER + ' — Site access restored; return visit required.'}, scope='crm.test.transition')
    returned = operations.return_visit_plan(original, proof, transition_id='phase19-test-revisit-c-v1', owner_trigger=True)
    if returned['decision'] != 'PREPARE_INTERNAL' or returned['create_services'] is not False:
        raise ValueError('Return visit TEST plan must preserve Service')
    child = create(instance, 'c-return-installation', 'Installations',
        {**returned['row'], 'Name': MARKER + ' — Phase19 C return visit', 'OptiBrain_Test': True})
    for service_id in scenario['service_ids']:
        create(instance, 'c-return-link-' + service_id, 'Installation_X_Services',
            {'Name': MARKER + ' — Phase19 return visit Service', 'Linked_Installation': {'id': child['id']},
             'Linked_Service': {'id': service_id}})
    known = {returned['effect_key']: {'installation_id': child['id'], 'parent_installation_id': original['id'],
        'deal_id': scenario['deal_id'], 'service_ids': scenario['service_ids']}}
    replay = operations.return_visit_plan(original, proof, transition_id='phase19-test-revisit-c-v1',
                                          owner_trigger=True, known_visits=known)
    if replay['decision'] != 'REUSE' or replay['record_id'] != child['id']:
        raise ValueError('Return visit TEST replay did not reuse native visit')
    scenario.update(return_installation_id=child['id'], blocked=blocked, return_visits=known); instance.save()
    completion(instance, operations, scenario, child, p, fixture, mutable=False, key='c-return')
    if instance.crm('Installations', original['id']).get('Installation_Status') != 'Revisit Required':
        raise ValueError('Return visit overwrote original blocked visit history')
    issue = {'subject': 'TEST completed Service support', 'description': MARKER + ' — Synthetic support request after completion.', 'emergency': False}
    completed_context, _ = context(instance, operations, instance.crm('Installations', child['id']), scenario, p)
    planned = operations.support_case_plan(issue, completed_context, source_event_id='phase19-test-support-c-v1')
    if planned['decision'] != 'PREPARE_INTERNAL':raise ValueError('TEST support Case context is incomplete')
    case = create(instance, 'c-support-case', 'Cases', {**planned['row'],
        'Subject': MARKER + ' — Phase19 support Case', 'OptiBrain_Test': True})
    planned['support_context']['case_id'] = case['id']
    atomic = __import__('test_lab').atomic
    atomic(ROOT / 'phase19-support-case-context.json', planned)
    scenario.update(case_id=case['id'], support_context=planned['support_context'], complete=True); instance.save()


def scenario_d(instance, operations, fixture, atomic):
    p = instance.state['parents']; scenarios = instance.state.setdefault('operational_scenarios', {})
    if scenarios.get('D', {}).get('complete'):return
    base = scenarios['A']; native_deal = instance.crm('Deals', base['deal_id'])
    site = instance.crm('Service_Locations', base['site_id']); services = [instance.crm('Services', value) for value in base['service_ids']]
    native = {'Invoice_ID': '9900018190002', 'Account_Name': {'id': p['account_id']}, 'Potential_Name': {'id': base['deal_id']}}
    books = {'invoice_id': '9900018190002', 'invoice_number': 'TEST_ONLY_SIMULATED_PHASE19',
             'status': 'sent', 'total': 100, 'balance': 100, 'due_date': fixture['due_date']}
    observations = []
    for status, balance in [('sent', 100), ('partially_paid', 40), ('paid', 0)]:
        result = operations.invoice_progress_plan(native, {**books, 'status': status, 'balance': balance},
            deals=[native_deal], sites=[site], services=services, now=datetime.now(timezone.utc))
        if result['decision'] != 'OBSERVE' or result['financial_writes'] is not False:
            raise ValueError('TEST Invoice/payment fixture cannot be safely observed')
        observations.append(result)
    if observations[-1]['clear_billing_attention'] is not True:
        raise ValueError('TEST paid observation did not clear internal billing attention')
    payment_task = task(instance, 'd-payment-observation', base['deal_id'], p['contact_id'],
        'Observe TEST payment fixture', 'TEST_ONLY simulated Books payment state; no payment mutation.', fixture['due_date'])
    update(instance, 'd-payment-observation-complete', 'Tasks', payment_task['id'], {'Status': 'Completed'})
    # Native production Finance/Books inspection remains strictly GET-only.
    records = json.loads(Path('/var/lib/optibrain/phase16-17/finance-native-records.json').read_text())
    cached = records['CustomModule5001']['data']['data'][0]
    actual = instance.crm('CustomModule5001', cached['id'])
    books_id = str(actual.get('Invoice_ID') or '')
    if not books_id.isdigit():raise ValueError('Native Finance Invoice ID unavailable')
    book_invoice = instance.get('zohoapis', '/books/v3/invoices/' + books_id,
                                {'organization_id': '802337532'})['invoice']
    if str(book_invoice.get('invoice_id')) != books_id:raise ValueError('Native Finance/Books Invoice ID disagrees')
    customer = instance.get('zohoapis', '/books/v3/contacts/' + str(book_invoice['customer_id']),
                            {'organization_id': '802337532'})['contact']
    native_account = str((actual.get('Account_Name') or {}).get('id') or '')
    if native_account and str(customer.get('zcrm_account_id')) != native_account:
        raise ValueError('Read-only native Invoice Account/Books customer relationship disagrees')
    evidence = {'native_invoice_id_match': True, 'native_account_books_customer_match': bool(native_account),
        'native_deal_link_present': bool((actual.get('Potential_Name') or {}).get('id')),
        'observed_status': book_invoice.get('status'), 'observed_balance': book_invoice.get('balance'),
        'detail_field_names': sorted(book_invoice), 'provider_writes': 0,
        'relationship_limitation': 'Historical native Invoice without Deal linkage remains human; never repaired automatically.'}
    atomic(ROOT / 'phase19-native-finance-readonly.json', evidence)
    scenarios['D'] = {'scenario': 'COMPLETION_INVOICE_PAYMENT_OBSERVATION',
        'source_kind': 'TEST_ONLY_STATUS_EQUIVALENT', 'invoice_payment_progression': observations,
        'native_finance_readonly': evidence, 'actual_finance_transactions_created': 0,
        'payment_mutations': 0, 'complete': True}
    instance.save()


def verify(instance, operations, *, replay=False):
    scenarios = instance.state.get('operational_scenarios', {})
    if set(scenarios) != {'A', 'B', 'C', 'D'} or not all(row.get('complete') for row in scenarios.values()):
        raise ValueError('All Phase19 TEST scenarios must be complete')
    p = instance.state['parents']; identities = {module: [] for module in ('Deals', 'Service_Locations', 'Services', 'Installations', 'Tasks', 'Cases')}
    for key, scenario in scenarios.items():
        if key == 'D':continue
        record = instance.crm('Installations', scenario.get('return_installation_id', scenario['installation_id']))
        if record.get('Installation_Status') != 'Completed' or record.get('OptiBrain_Test') is not True:
            raise ValueError('Operational TEST final visit must be completed and excluded from real metrics')
        context(instance, operations, record, scenario, p)
    for key, value in instance.state['operations'].items():
        if key.startswith('phase19-') and value.get('state') != 'verified':
            raise ValueError('Phase19 TEST effect outcome is not independently verified')
        if key.startswith('phase19-') and value.get('provider_id'):
            entry = instance.ownership['records'].get(value['provider_id'], {})
            if entry.get('module') in identities:
                identities[entry['module']].append(value['provider_id'])
    for module in identities:
        identities[module] = sorted(set(identities[module]))
    for module, ids in identities.items():
        for identity in ids:
            row = instance.crm(module, identity)
            if row.get('OptiBrain_Test') is not True:raise ValueError('Operational TEST boolean missing: ' + module)
            if module == 'Deals' and (row.get('Amount') != 0 or row.get('Stage') != 'Closed Lost'):
                raise ValueError('Operational TEST Deal can contaminate forecasts')
    # Re-run matching over real provider reads; exact same native entities must be reused.
    a = scenarios['A']; site = instance.crm('Service_Locations', a['site_id'])
    sites = instance.lists('Service_Locations', 'id,Linked_Account,' + ','.join(__import__('workflow.automation.lifecycle', fromlist=['SITE_FIELDS']).SITE_FIELDS.values()))
    if (operations.operational_site_match(sites, p['account_id'], site).get('record') or {}).get('id') != a['site_id']:
        raise ValueError('Operational TEST site replay did not reuse exact site')
    services = instance.lists('Services', 'id,Name,Linked_Deal,Linked_Service_Location,Service_Type,Service_Stage')
    for key in ['A', 'B', 'C']:
        result = operations.durable_service_plan('Structured Cabling', scenarios[key]['site_id'], services)
        if result['decision'] != 'PREPARE_INTERNAL' or result['services'][0]['record']['id'] != scenarios[key]['service_ids'][0]:
            raise ValueError('Operational TEST replay duplicated durable Service')
    original = instance.crm('Installations', scenarios['C']['installation_id'])
    if original.get('Installation_Status') != 'Revisit Required':raise ValueError('Original return-visit history was overwritten')
    borrowed = instance.crm('Services', p['service_id'])
    if any(borrowed.get(key) != value for key, value in scenarios['B']['service_before'].items()):
        raise ValueError('Existing durable TEST Service was mutated')
    return {'phase19_test': 'PASS', 'scenario_results': {key: 'PASS' for key in scenarios},
        'new_owned_records': {module: len(values) for module, values in identities.items()},
        'identities': identities, 'intentional_visits': 4, 'new_services': 1,
        'durable_service_reuse': True, 'original_return_visit_history_preserved': True,
        'duplicate_sites': 0, 'duplicate_services': 0, 'duplicate_installations': 0,
        'duplicate_folders': 0, 'duplicate_tasks': 0, 'customer_sends': 0,
        'financial_writes': 0, 'payment_mutations': 0, 'status_fixtures_explicitly_test_only': True,
        'replay_get_only': replay, 'test_metric_exclusion': 'BOOLEAN TRUE; ALL TEST DEALS CLOSED LOST / AMOUNT 0',
        'human_trigger_test_basis': 'CONTROLLED TEST API STATUS EQUIVALENT; REAL REQUIRES OWNER CRM UI EVIDENCE',
        'at': datetime.now(timezone.utc).isoformat()}


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in {'run', 'replay'}:
        raise ValueError('Explicit run or replay required')
    instance, activate, control, operations, site_fields, atomic = imports()
    mode = sys.argv[1]
    before = sum(value.get('state') == 'verified' for key, value in instance.state['operations'].items() if key.startswith('phase19-'))
    if mode == 'run':
        activate(instance)
        try:
            if 'operational_fixture' not in instance.state:
                now = datetime.now(timezone.utc).replace(microsecond=0)
                schedule = (now - timedelta(days=1)).astimezone(TORONTO).replace(hour=10, minute=0, second=0)
                instance.state['operational_fixture'] = {'completed_at': now.isoformat(), 'scheduled_at': schedule.isoformat(),
                    'due_date': now.astimezone(TORONTO).date().isoformat(), 'mode': 'TEST_ONLY_ACCELERATED'}
                instance.save()
            fixture = instance.state['operational_fixture']
            scenario_a(instance, operations, site_fields, atomic, fixture)
            scenario_b(instance, operations, fixture)
            scenario_c(instance, operations, fixture)
            scenario_d(instance, operations, fixture, atomic)
            for key, scenario in instance.state['operational_scenarios'].items():
                if scenario.get('deal_id'):
                    update(instance, key.lower() + '-close-deal', 'Deals', scenario['deal_id'], {'Stage': 'Closed Lost', 'Amount': 0})
            receipt = verify(instance, operations)
        finally:
            atomic(control, {'schema': 1, 'test_writes_enabled': False, 'allowed_actions': ['crm.task.create'],
                             'real_canary_allowed': False})
    else:
        receipt = verify(instance, operations, replay=True)
    after = sum(value.get('state') == 'verified' for key, value in instance.state['operations'].items() if key.startswith('phase19-'))
    receipt['new_verified_provider_effects'] = after - before
    if mode == 'replay' and after != before:raise ValueError('Replay changed provider effect count')
    atomic(ROOT / ('phase19-operations-' + mode + '.json'), receipt)
    print(json.dumps({key: value for key, value in receipt.items() if key != 'identities'}, sort_keys=True))


if __name__ == '__main__':
    main()
