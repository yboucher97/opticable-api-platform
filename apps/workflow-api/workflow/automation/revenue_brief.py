"""Private CLI projection of existing OptiBrain observations. No network or writes."""

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import re
import sys

from .business_intelligence import business_day
from .measurement import populations
from .recurring_lifecycle import TORONTO, identity, index, money, synthetic

CRM = {'Leads': 'leads', 'Deals': 'deals', 'Tasks': 'tasks', 'Contacts': 'contacts'}
OPEN_QUOTES = {'sent', 'viewed', 'accepted', 'signed', 'partially_invoiced', 'pending_signature'}
DRAFT_QUOTES = {'draft', 'approved', 'pending_approval'}
TERMINAL_CRM = {'closed won', 'closed lost', 'completed', 'cancelled', 'converted', 'junk lead'}
SOURCE_MAX_AGE = timedelta(hours=3)
REVIEW_MAX_AGE = timedelta(hours=30)


def timestamp(value):
    try:
        at = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return at if at.tzinfo is not None else None


def fresh(value, now, max_age):
    at = timestamp(value)
    return at is not None and timedelta(0) <= now - at <= max_age


def text_id(row):
    name = ' '.join(str(row.get(k) or '').strip() for k in ('First_Name', 'Last_Name')).strip()
    return str(row.get('Full_Name') or row.get('Deal_Name') or row.get('Subject') or name or row['id'])


def message_identity(requested_id, details):
    """The body endpoint may round numeric IDs. Only exact metadata proves identity."""
    if not isinstance(requested_id, str) or not identity(requested_id):
        raise ValueError('Exact string request identity required')
    if not isinstance(details.get('messageId'), str) or details['messageId'] != requested_id:
        raise ValueError('Message metadata identity disagrees with request')
    return requested_id


def quote_scenarios(quote_queue, scenarios):
    """Compute mutually exclusive scenarios from exact version-matched records."""
    quotes = {row['id']: row for row in quote_queue}
    output = []
    for scenario in scenarios:
        ids = scenario['estimate_ids']
        selected = [quotes.get(rid) for rid in ids]
        valid = bool(ids) and len(ids) == len(set(ids)) and all(
            row and row['current_source'] and row['review']
            and row['status'] in OPEN_QUOTES | DRAFT_QUOTES
            and row.get('currency') == scenario['currency'] and row['total'] is not None
            for row in selected
        )
        output.append({'label': scenario['label'], 'exclusive_group': scenario.get('exclusive_group'),
                       'estimate_ids': ids, 'currency': scenario['currency'],
                       'gross_quote_value': str(sum((money(r['total']) for r in selected), Decimal())) if valid else None,
                       'conditional_on_award': True})
    return output


def quote_groups(quotes):
    """Unknown alternatives are never added. This is face value, never revenue."""
    groups = defaultdict(list)
    for row in quotes:
        if row['status'] in OPEN_QUOTES | DRAFT_QUOTES and row['customer_id'] and row['currency']:
            groups[row['customer_id'], row['currency']].append(row)
    return [{'customer_id': cid, 'currency': currency,
             'estimate_ids': sorted(r['id'] for r in rows),
             'largest_single_quote': (str(max(money(r['total']) for r in rows if r['total'] is not None))
                                      if any(r['total'] is not None for r in rows) else None),
             'combined_conversion_value': None,
             'reason': 'No additive or alternative scopes inferred from customer, dates or amounts'}
            for (cid, currency), rows in sorted(groups.items())]


def draft_queue(drafts):
    """Same source/intent reuses one internal draft; language variants are alternatives."""
    seen = set(); result = []
    for row in drafts:
        ids = sorted(set(row.get('source_ids', [])))
        if not ids or any(not isinstance(rid, str) or not identity(rid) for rid in ids):
            raise ValueError('Draft requires exact source identities')
        key = sha256(json.dumps([row['kind'], ids], separators=(',', ':')).encode()).hexdigest()
        if key in seen:
            continue
        seen.add(key)
        result.append({**row, 'id': key, 'approval_scope': 'EXACT_RECIPIENT_SUBJECT_BODY_AND_SOURCE_VERSION',
                       'content_sha256': sha256(json.dumps(row, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
                       'sent': False, 'provider_draft_created': False})
    return result


def current_drafts(drafts, live, sources):
    """Drop old financial proposals as soon as status/version/source changes."""
    financial = {**live['invoices'], **live['estimates']}
    ready = []
    for row in drafts:
        versions = row.get('source_versions', {})
        if any(rid not in financial or financial[rid].get('last_modified_time') != version
               for rid, version in versions.items()):
            continue
        if row.get('kind') == 'collection':
            if not versions or not sources.get('books_invoices', {}).get('current'):
                continue
            if any(rid not in live['invoices'] or live['invoices'][rid].get('status') != 'overdue'
                   or money(live['invoices'][rid].get('balance', '0')) <= 0 for rid in versions):
                continue
        ready.append(row)
    return draft_queue(ready)


def classify_crm(snapshot, crm, proofs, *, today):
    """CRM states are review labels. Exact source links establish real work."""
    merged = dict(snapshot)
    for module, name in CRM.items():
        if module in crm:
            values = index(crm[module])
            original = index(snapshot.get(name, []))
            merged[name] = [{**original.get(rid, {}), **row} for rid, row in values.items()]
    live, _ = populations(merged)
    candidates = {module: index(merged.get(name, [])) for module, name in CRM.items()}
    excluded = {module: set(candidates[module]) - set(live[name])
                for module, name in CRM.items() if name in live}
    excluded['Accounts'] = set(index(merged.get('accounts', []))) - set(live['accounts'])
    contact_proofs = {}
    for customer in live['customers'].values():
        account_id = identity(customer.get('zcrm_account_id'))
        if not account_id:
            continue
        for person in customer.get('contact_persons', []):
            if not isinstance(person, dict):
                continue
            contact_id = identity(person.get('zcrm_contact_id'))
            contact = live['contacts'].get(contact_id, {})
            if identity(contact.get('Account_Name')) == account_id:
                contact_proofs[contact_id] = (
                    f"Books customer {customer['contact_id']} links the same native CRM Contact and Account {account_id}"
                )

    exact_contacts = defaultdict(list)
    for rid, row in candidates['Contacts'].items():
        account, email = identity(row.get('Account_Name')), str(row.get('Email') or '').strip().casefold()
        if rid not in excluded['Contacts'] and account and re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
            name = ' '.join(text_id(row).casefold().split())
            exact_contacts[account, email, name].append(rid)
    repeated_contacts = {rid: sorted(set(group) - {rid})
                         for group in exact_contacts.values() if len(group) > 1 for rid in group}
    lead_keys = defaultdict(list)
    for rid, row in candidates['Leads'].items():
        email = str(row.get('Email') or '').strip().casefold()
        name = ' '.join(text_id(row).casefold().split())
        company = ' '.join(str(row.get('Company') or '').casefold().split())
        if rid not in excluded['Leads'] and email and name and company:
            lead_keys[email, name, company].append(rid)
    duplicate_leads = {rid: sorted(set(group) - {rid})
                       for group in lead_keys.values() if len(group) > 1 for rid in group}
    result = {}
    for module, values in candidates.items():
        records = []
        for rid, row in sorted(values.items()):
            proof = proofs.get(module, {}).get(rid) or (contact_proofs.get(rid) if module == 'Contacts' else None)
            modified = timestamp(row.get('Modified_Time') or row.get('Created_Time'))
            stage = row.get('Stage') or row.get('Status') or row.get('Lead_Status')
            what_module = row.get('$se_module')
            what = identity(row.get('What_Id'))
            who = identity(row.get('Who_Id'))
            task_test = module == 'Tasks' and (what in excluded.get(what_module, ())
                                               or who in excluded['Contacts'])
            duplicates = (repeated_contacts if module == 'Contacts' else duplicate_leads if module == 'Leads' else {})
            age = (today - modified.astimezone(TORONTO).date()).days if modified else None
            if synthetic(row) or task_test or rid in excluded.get(module, ()):
                state = 'TEST'
                reason = 'Explicit synthetic marker' if synthetic(row) else 'Exact test lineage'
            elif rid in duplicates:
                state, reason = 'DUPLICATE', 'Same normalized identity and exact email/account or company; review canonical record without modifying history'
            elif (module != 'Contacts' and isinstance(stage, str) and stage.casefold() not in TERMINAL_CRM
                  and age is not None and age > 90 and not proof):
                state, reason = 'STALE', 'CRM open activity older than 90 days; reverify using customer evidence'
            elif proof:
                state, reason = 'REAL', proof
            else:
                state, reason = 'NEEDS VERIFICATION', 'Independent exact evidence missing'
            result_fields = {'id': rid, 'label': text_id(row), 'stage': stage, 'classification': state,
                             'evidence': reason, 'duplicate_with': duplicates.get(rid, []),
                             'crm_age_days': age, 'stale_crm': age is not None and age > 90,
                             'converted': bool(row.get('$converted') or row.get('$converted_detail') or row.get('Converted_Account')),
                             'revenue_recognition': 'NOT_ESTABLISHED_BY_CRM_CLASSIFICATION',
                             'include_in_real_pipeline': module in {'Leads', 'Deals'} and state == 'REAL'
                             and not (row.get('$converted') or row.get('$converted_detail') or row.get('Converted_Account'))
                             and isinstance(stage, str) and stage.casefold() not in TERMINAL_CRM}
            records.append(result_fields)
        result[module] = {'counts': dict(Counter(r['classification'] for r in records)), 'records': records}
    return result


def receipt_inquiries(receipts, excluded=()):
    """Use the existing receipt's test/quarantine projection and exact identity."""
    inquiries = []
    for receipt in receipts:
        if receipt['test_only'] or receipt['quarantined'] or receipt['provider_message_id'] in excluded:
            continue
        evidence = json.loads(receipt['evidence_json'])
        fields = evidence.get('fields', {})
        company, service = fields.get('company'), fields.get('service')
        if not company or not service or synthetic({'Company': company, 'Full_Name': fields.get('name')}):
            continue
        timeline = fields.get('timeline')
        urgent = str(timeline or '').casefold() in {'immédiat', 'immediately', 'immediate'}
        questions = ("Confirm the address, desired install date, and site access. "
                     "Request a floor plan or a brief scope description without credentials.")
        if re.search(r'wi.?fi|intercom', service, re.I):
            questions += " Confirm existing internet, network equipment, and intercom or camera models."
        if re.search(r'cabl|câbl|fib[er]', service, re.I):
            questions += " Confirm endpoints, path length, conduit, and working hours."
        inquiries.append({'id': receipt['event_id'], 'message_id': receipt['provider_message_id'],
                          'received_at': receipt['occurred_at'], 'customer': company, 'service': service,
                          'timeline': timeline, 'urgent': urgent, 'status': 'RECEIPT_REQUIRES_QUALIFICATION',
                          'next_action': questions, 'evidence': 'Existing Zoho Forms receipt ledger'})
    inquiries.sort(key=lambda r: (r['urgent'], r['received_at']), reverse=True)
    return inquiries


def brief(observation, review, receipts, *, now):
    if now.tzinfo is None:
        raise ValueError('Report clock requires a UTC offset')
    now = now.astimezone(TORONTO)
    snapshot = observation['snapshot']
    modules = observation.get('collection', snapshot.get('collection', {})).get('modules', {})
    source = {k: {'state': v.get('state'), 'at': v.get('source_at'),
                  'current': v.get('state') == 'COMPLETE' and fresh(v.get('source_at'), now, SOURCE_MAX_AGE)}
              for k, v in modules.items()}
    review_current = fresh(review.get('observed_at'), now, REVIEW_MAX_AGE)
    reviewed = review if review_current else {}
    live, _ = populations(snapshot)
    invoices = []
    for rid, row in live['invoices'].items():
        if row.get('status') != 'overdue' or not row.get('balance') or money(row['balance']) == 0:
            continue
        detail = reviewed.get('invoices', {}).get(rid, {})
        if not row.get('last_modified_time') or detail.get('version') != row.get('last_modified_time'):
            detail = {}
        invoices.append({'id': rid, 'number': row.get('invoice_number'), 'customer': row.get('customer_name'),
                         'customer_id': row.get('customer_id'), 'source_version': row.get('last_modified_time'),
                         'balance': str(money(row['balance'])), 'currency': row.get('currency_code'),
                         'due': row.get('due_date'), 'last_reminder': row.get('last_reminder_sent_date'),
                         'days_overdue': (now.date() - business_day(row['due_date'])).days if row.get('due_date') else None,
                         'source_current': source.get('books_invoices', {}).get('current', False),
                         'verification': detail.get('verification'), 'next_action': detail.get('next_action')})
    invoices.sort(key=lambda row: (row['currency'] or '', -money(row['balance']), row['number'] or row['id']))
    overdue_totals = defaultdict(Decimal)
    for row in invoices:
        if row['currency'] and row['source_current']:
            overdue_totals[row['currency']] += money(row['balance'])

    quote_queue = []
    for rid, row in live['estimates'].items():
        detail = reviewed.get('estimates', {}).get(rid, {})
        if not row.get('last_modified_time') or detail.get('version') != row.get('last_modified_time'):
            detail = {}
        status = row.get('status')
        quote_queue.append({'id': rid, 'number': row.get('estimate_number'), 'date': row.get('date'),
                            'customer_id': row.get('customer_id'), 'source_version': row.get('last_modified_time'),
                            'customer': row.get('customer_name'), 'status': status,
                            'expiry': row.get('expiry_date'), 'currency': row.get('currency_code'),
                            'total': str(money(row['total'])) if row.get('total') is not None else None,
                            'current_source': source.get('books_estimate_index', {}).get('current', False),
                            'stale': bool(row.get('date') and (now.date() - business_day(row['date'])).days > 90),
                            'review': {k: v for k, v in detail.items() if k != 'version'}})
    quote_queue.sort(key=lambda row: (row['date'] or '', row['number'] or row['id']), reverse=True)

    payments = {}
    if source.get('payments', {}).get('current') and snapshot.get('base_currency'):
        for period, start in [('today', now.date()), ('month_to_date', now.date().replace(day=1))]:
            posted = [r for r in live['payments'].values()
                      if (r.get('payment_status') or r.get('status')) in {'paid', 'success'}
                      and r.get('date') and start <= business_day(r['date']) <= now.date()]
            amounts = [r.get('bcy_amount') for r in posted]
            refunds = [r.get('bcy_refunded_amount') for r in posted]
            payments[period] = {'count': len(posted), 'currency': snapshot['base_currency'],
                                'gross': str(sum(map(money, amounts), Decimal())) if None not in amounts else None,
                                'refunds': str(sum(map(money, refunds), Decimal())) if None not in refunds else None}

    current_receipts = [r for r in receipt_inquiries(receipts, review.get('excluded_inquiry_message_ids', []))
                        if fresh(r['received_at'], now, timedelta(days=14))]
    manual_inquiries = reviewed.get('inquiries', [])
    known_messages = {r.get('message_id') for r in manual_inquiries} - {None}
    sources_complete = all(source.get(k, {}).get('current') for k in ('leads', 'deals', 'contacts', 'accounts'))
    crm_snapshot = snapshot if source.get('customers', {}).get('current') else {**snapshot, 'customers': []}
    crm_review = classify_crm(crm_snapshot, reviewed.get('crm', {}) if sources_complete else {},
                              reviewed.get('crm_proofs', {}) if sources_complete else {}, today=now.date())
    cash_actions = reviewed.get('top_actions') or [
        f"Verify payment and correspondence for {r['number'] or r['id']} ({r['currency']} {r['balance']}) before approval."
        for r in invoices if r['source_current']
    ][:5]
    return {
        'schema': 1, 'date': now.date().isoformat(), 'generated_at': now.isoformat(), 'timezone': str(TORONTO),
        'sources': source, 'review_at': review.get('observed_at'), 'review_current': review_current,
        'top_actions': cash_actions[:5],
        'overdue_invoices': invoices,
        'overdue_by_currency': {currency: str(amount) for currency, amount in overdue_totals.items()},
        'quote_inventory': quote_queue, 'quote_count_by_status': dict(Counter(r['status'] for r in quote_queue)),
        'quote_groups': quote_groups(quote_queue),
        'active_estimates': [r for r in quote_queue if r['status'] in OPEN_QUOTES | DRAFT_QUOTES],
        'new_inquiries': manual_inquiries + [r for r in current_receipts if r['message_id'] not in known_messages],
        'jobs_awaiting_acceptance_or_scheduling': reviewed.get('jobs', []),
        'recurring_opportunities': reviewed.get('recurring', []),
        'missing_information': reviewed.get('blockers', []) + ([] if review_current else
            ['Current Mail, Calendar, Projects and owner review evidence required for cross-source recommendations']),
        'completed_work': reviewed.get('completed', []) + ['Built private daily projection from the existing observer'],
        'approval_decisions': reviewed.get('approvals', []),
        'followup_drafts': current_drafts(reviewed.get('drafts', []), live, source),
        'execution_authority': False, 'marketing_artifacts_created': 0,
        'outcomes': {'books_recorded_payments': payments, 'bank_settlement': 'UNVERIFIED',
                     'quote_projections': reviewed.get('projections', []), 'new_cash_recovered_by_optibrain': None},
        'crm': crm_review, 'crm_source_current': sources_complete,
        'crm_tasks_coverage': 'REVIEWED' if sources_complete and 'Tasks' in reviewed.get('crm', {}) else 'UNAVAILABLE',
    }


def markdown(report):
    sections = [
        ('Top five cash actions', report['top_actions']),
        ('Verified overdue invoices', [
            f"{r['number'] or r['id']} | {r['customer']} | {r['currency']} {r['balance']} | due {r['due']} | "
            f"{r['next_action'] or 'Review payment and correspondence'}"
            + ('' if r['source_current'] else ' | older Books observation')
            + ('' if r['verification'] else ' | payments/credits detail needs review')
            for r in report['overdue_invoices']]),
        ('Active estimates', [
            f"{r['number'] or r['id']} | {r['customer']} | {r['currency']} {r['total']} | {r['status']} | "
            f"{r['review'].get('next_action', 'Verify current scope and customer response')}"
            + ('' if r['current_source'] else ' | older Books observation')
            for r in report['active_estimates'] if r['review']] or [
                f"{len(report['active_estimates'])} Books records to triage. See the JSON for status and source age."]),
        ('New inquiries', [f"{r['customer']} | {r['service']} | {r.get('next_action', r['status'])}"
                           for r in report['new_inquiries']]),
        ('Jobs awaiting acceptance or scheduling', report['jobs_awaiting_acceptance_or_scheduling']),
        ('Recurring opportunities', report['recurring_opportunities']),
        ('Missing information', report['missing_information']),
        ('Completed internal work', report['completed_work']),
        ('Owner approvals', report['approval_decisions']),
        ('Real outcomes and quote projections', [
            *[f"{period.replace('_', ' ')} | {v['count']} recorded Books payments | {v['currency']} {v['gross']} gross"
              f" | refunds {v['refunds']}" for period, v in report['outcomes']['books_recorded_payments'].items()],
            'Bank settlement and OptiBrain-attributed recovery remain unverified.',
            *report['outcomes']['quote_projections']]),
    ]
    lines = [f"# Daily revenue brief — {report['date']}", '',
             f"Generated {report['generated_at']} ({report['timezone']})",
             f"Cross-source review {'current' if report['review_current'] else 'due for refresh'}.",
             'Books inventory, record IDs and source coverage are in the JSON brief.']
    for name, items in sections:
        lines.extend(['', f'## {name}', ''])
        lines.extend(f'- {item}' for item in (items or ['No current verified entries in this view.']))
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, help='Existing business observation JSON; defaults to stdin')
    parser.add_argument('--review', type=Path, help='Private version-matched review evidence JSON')
    forms = parser.add_mutually_exclusive_group()
    forms.add_argument('--forms-db', type=Path, help='Existing receipt ledger, opened in SQLite read-only mode')
    forms.add_argument('--forms-json', type=Path, help='Export of the same read-only receipt projection')
    parser.add_argument('--format', choices=('json', 'md'), default='md')
    args = parser.parse_args()
    observation = json.loads(args.snapshot.read_text()) if args.snapshot else json.load(sys.stdin)
    review = json.loads(args.review.read_text()) if args.review else {}
    receipts = json.loads(args.forms_json.read_text()) if args.forms_json else []
    if args.forms_db:
        from .phase9_form_receipts import FormReceiptLedger
        receipts = FormReceiptLedger(args.forms_db).list(read_only=True)
    output = brief(observation, review, receipts, now=datetime.now(timezone.utc))
    sys.stdout.write(markdown(output) if args.format == 'md' else json.dumps(output, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
