"""Read-only recurring business lifecycle; Books alone runs recurring billing.

Plans are display/internal attention only. They never change Service status,
money, contracts or schedules, and confer no provider-write authority.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from zoneinfo import ZoneInfo

TORONTO = ZoneInfo('America/Toronto')


def identity(value):
    if isinstance(value, dict): value = value.get('id')
    value = str(value or '')
    return value if re.fullmatch(r'[0-9]{1,30}', value) else ''


def synthetic(row):
    return row.get('OptiBrain_Test') is True or row.get('test_only') is True or any(
        'OPTIBRAIN TEST' in str(row.get(k, '')).upper() for k in ('Name', 'Account_Name', 'Deal_Name', 'Last_Name', 'customer_name', 'contact_name', 'recurrence_name'))


def day(value):
    return date.fromisoformat(str(value)) if value else None


def money(value):
    try: result = Decimal(str(value))
    except InvalidOperation as exc: raise ValueError('Malformed monetary observation') from exc
    if not result.is_finite() or result < 0 or result > Decimal('1000000000'):
        raise ValueError('Invalid monetary observation')
    return result


def index(rows, key='id'):
    result = {}
    for row in rows:
        value = identity(row.get(key))
        if not value or value in result: raise ValueError('Incomplete or duplicate native identity')
        result[value] = row
    return result


def bind_profile(profile, customer, services, sites, finance_invoices, generated, *, reviewed=None):
    """Independent native customer/Account plus exact Deal or reviewed linkage.

    A Books shipping address/location_id is not a CRM Site ID. Names, amount and
    number of Services under an Account never establish a billing relationship.
    """
    pid = identity(profile.get('recurring_invoice_id')); cid = identity(profile.get('customer_id'))
    account = identity(customer.get('zcrm_account_id'))
    human = lambda reason: {'decision': 'HUMAN', 'reason': reason, 'profile_id': pid, 'account_id': account}
    if not pid or not cid or identity(customer.get('contact_id')) != cid or not account:
        return human('Native Books customer → CRM Account linkage is missing')
    generated_ids = {identity(r.get('invoice_id')) for r in generated}
    if '' in generated_ids: return human('Generated invoice history has an invalid ID')
    linked = [r for r in finance_invoices if identity(r.get('Invoice_ID')) in generated_ids]
    if any(identity(r.get('Account_Name')) != account for r in linked):
        return human('Native Invoice Account disagrees with Books customer; no association made')
    deals = {identity(r.get('Potential_Name')) for r in linked if identity(r.get('Potential_Name'))}
    direct = identity(profile.get('zcrm_potential_id'))
    if direct: deals.add(direct)
    if len(deals) > 1: return human('Recurring profile generated invoices span multiple Deals')
    candidates = [s for s in services if deals and identity(s.get('Linked_Deal')) in deals]
    if reviewed:
        required = {'profile_id', 'customer_id', 'account_id', 'site_id', 'service_id', 'reviewed_at', 'reviewed_by', 'proof'}
        if not required <= set(reviewed) or not reviewed['proof'] or not reviewed['reviewed_by']:
            return human('Incomplete owner-reviewed linkage receipt')
        at = datetime.fromisoformat(reviewed['reviewed_at'])
        if at.tzinfo is None: return human('Reviewed linkage timestamp must be explicit')
        if [reviewed['profile_id'], reviewed['customer_id'], reviewed['account_id']] != [pid, cid, account]:
            return human('Reviewed linkage conflicts with current native financial identity')
        candidates = [s for s in services if identity(s.get('id')) == reviewed['service_id']]
    if len(candidates) != 1: return human('Select the recurring Service; native transaction linkage is insufficient')
    service = candidates[0]; site = sites.get(identity(service.get('Linked_Service_Location')))
    if not site or identity(site.get('Linked_Account')) != account:
        return human('Service/Site Account disagrees with recurring customer')
    if reviewed and identity(site.get('id')) != reviewed['site_id']:
        return human('Reviewed Site differs from native Service location')
    if reviewed and deals and identity(service.get('Linked_Deal')) not in deals:
        return human('Reviewed Service conflicts with native recurring Deal evidence')
    return {'decision': 'LINKED', 'profile_id': pid, 'customer_id': cid, 'account_id': account,
            'site_id': identity(site['id']), 'service_id': identity(service['id']),
            'deal_id': identity(service.get('Linked_Deal')), 'proof': 'REVIEWED_NATIVE_IDENTITIES' if reviewed else 'NATIVE_INVOICE_DEAL_SERVICE'}


def attention(service_id, kind, anchor, reason, action):
    key = hashlib.sha256(json.dumps([service_id, kind, str(anchor)], separators=(',', ':')).encode()).hexdigest()
    return {'key': key, 'kind': kind, 'anchor': str(anchor or ''), 'identity': service_id,
            'module': 'Services', 'why': reason, 'next_action': action, 'priority': 'MEDIUM', 'test_only': False}


def project_service(service, site, profile, invoices, *, now, cases=(), context=None):
    if now.tzinfo is None: raise ValueError('Aware lifecycle clock required')
    today = now.astimezone(TORONTO).date(); sid = identity(service.get('id'))
    if not sid or not site or identity(site.get('id')) != identity(service.get('Linked_Service_Location')):
        raise ValueError('Native Service/Site relationship required')
    context = context or {}; stage = service.get('Service_Stage') or 'UNKNOWN'
    health = 'ENDED' if stage == 'Cancelled' else 'PAUSED / HUMAN REVIEW' if stage == 'Suspended' else 'ACTIVE' if stage == 'Active' else 'ATTENTION'
    recurring = service.get('Contract_Type') == 'Recurring Service' or bool(profile)
    rows = []; billing = 'UNLINKED'; overdue = []; account = identity(site.get('Linked_Account'))
    def add(kind, anchor, reason, action):
        row = attention(sid, kind, anchor, reason, action);row['context'] = service.get('Name') or 'Service';rows.append(row)
    if profile:
        pid = identity(profile.get('recurring_invoice_id')); cid = identity(profile.get('customer_id'))
        ids = set()
        for invoice in invoices:
            iid = identity(invoice.get('invoice_id'))
            if not iid or iid in ids or identity(invoice.get('customer_id')) != cid or identity(invoice.get('recurring_invoice_id')) != pid:
                raise ValueError('Generated Invoice profile/customer association is inconsistent')
            ids.add(iid)
            due = day(invoice.get('due_date')); balance = money(invoice.get('balance', 0))
            if balance and due and due < today and invoice.get('status') not in {'void', 'draft'}: overdue.append(iid)
        billing = 'OVERDUE' if overdue else 'PAID' if invoices and all(r.get('status') == 'paid' and money(r.get('balance', 0)) == 0 for r in invoices) else 'OBSERVED'
        if overdue:
            add('RECURRING_BILLING', '|'.join(sorted(overdue)), 'Recurring Invoice overdue; technical Service status is unchanged', 'Review Invoice in Zoho Finance')
            if health == 'ACTIVE': health = 'ATTENTION'
        if len(overdue) >= 2:
            add('RETENTION', 'billing', 'Multiple distinct recurring Invoices are overdue', 'Review billing and Service context; no automatic cancellation')
        if profile.get('status') == 'stopped' and stage == 'Active':
            add('BILLING_PROFILE_STOPPED', pid, 'Books recurring profile stopped while Service remains Active', 'Owner reviews billing and Service separately')
        ending = day(profile.get('end_date'))
        if ending and 0 <= (ending - today).days <= 90 and health != 'ENDED':
            add('BILLING_END_REVIEW', ending, 'Recurring billing profile approaches its end date; this is not legal contract expiry', 'Review recurring billing/contract in Books and CRM')
    elif recurring:
        add('MISSING_BILLING_LINK', sid, 'Recurring Service has no independently verified Books profile linkage', 'Review Service and native Finance relationship')
    # Owner-recorded cancellation suppresses future lifecycle attention, never Books.
    if health == 'ENDED':
        rows = [r for r in rows if r['kind'] in {'RECURRING_BILLING', 'BILLING_PROFILE_STOPPED'}]
        if profile and profile.get('status') == 'active': add('ENDED_BILLING_REVIEW', sid, 'Service ended while Books billing remains active', 'Owner decides billing cancellation in Books')
    elif health != 'PAUSED / HUMAN REVIEW':
        renewal = day(service.get('OptiBrain_Renewal_On'))
        if renewal and (renewal - today).days <= 90 and recurring:
            remaining = (renewal - today).days; window = 30 if remaining <= 30 else 60 if remaining <= 60 else 90
            add('RENEWAL', renewal, f'Renewal / contract review within {window} days' if remaining >= 0 else 'Recorded renewal review overdue', 'Review contract; legal/financial renewal remains human')
            if remaining <= 0: add('RETENTION', renewal, 'Renewal review date passed without an updated recorded date', 'Review renewal status with owner')
        maintenance = day(service.get('OptiBrain_Maintenance_Due')); last = day(service.get('OptiBrain_Last_Service_On'))
        if maintenance and maintenance <= today and (not last or last < maintenance):
            add('MAINTENANCE', maintenance, 'Explicit recorded maintenance is due', 'Prepare maintenance; scheduling remains human')
        started = day(service.get('OptiBrain_Installed_On'))
        if recurring and started and started < today:
            anchor = date(today.year, started.month, min(started.day, 28) if started.month == 2 and started.day == 29 else started.day)
            if anchor <= today and today.year > started.year and not context.get('price_review_completed_for_year') == today.year:
                add('PRICE_REVIEW', anchor, 'Annual internal price review due; no price change authorized', 'Review current Books recurring amount and Service context')
        open_cases = [r for r in cases if not synthetic(r) and identity(r.get('Account_Name') or r.get('Related_To')) == account and r.get('Status') not in {'Closed', 'Resolved'}]
        if len(open_cases) >= 2: add('RETENTION', 'support', 'Multiple open support Cases for this Account; site-specific cause requires review', 'Review Case/site/Service context')
        if stage == 'Active' and started and not open_cases and not overdue and not context.get('delivery_problem') and not context.get('review_requested_recently'):
            add('REVIEW_ELIGIBLE', started, 'Completed active Service; no known open Case/billing/delivery suppression', 'Owner reviews eligibility and prepares review request; automatic send OFF')
        if recurring and context.get('cancellation_request') is True:
            health = 'ENDING';add('RETENTION', 'cancellation-request', 'Explicit cancellation request awaits owner decision', 'Owner reviews end decision; billing remains Books-owned')
    for r in rows:r['test_only'] = synthetic(service) or synthetic(site)
    return {'id': sid, 'account_id': account, 'site_id': identity(site['id']), 'deal_id': identity(service.get('Linked_Deal')),
            'name': service.get('Name') or 'Service', 'service_stage': stage, 'health': health, 'recurring': recurring,
            'billing_state': billing, 'profile_id': identity(profile.get('recurring_invoice_id')) if profile else None,
            'billing_frequency': profile.get('recurrence_frequency') if profile else None,
            'repeat_every': profile.get('repeat_every') if profile else None,
            'next_billing_date': profile.get('next_invoice_date') if profile else None,
            'observed_amount': str(money(profile['total'])) if profile and profile.get('total') is not None else None,
            'currency': profile.get('currency_code') if profile else None,
            'started_on': service.get('OptiBrain_Installed_On'), 'attention': rows, 'test_only': synthetic(service) or synthetic(site),
            'financial_writes': False, 'external_sends': False, 'service_mutations': False}


def build_recurring(snapshot, *, now, reviewed_links=None):
    services = index(snapshot['services']);sites = index(snapshot['sites']);accounts = index(snapshot['accounts'])
    profiles = index(snapshot['profiles'], 'recurring_invoice_id');customers = index(snapshot['customers'], 'contact_id')
    reviewed_links = reviewed_links or {};rows = [];attention_rows = {};unlinked = []
    linked = {}
    for pid, profile in profiles.items():
        customer = customers.get(identity(profile.get('customer_id')), {})
        if synthetic(profile) or synthetic(customer): continue
        anomalies = [r for r in snapshot.get('profile_exceptions', []) if r.get('profile_id') == pid]
        if anomalies:
            unlinked.append({'profile_id': pid, 'account_id': identity(customer.get('zcrm_account_id')),
                'decision': 'HUMAN', 'reason': anomalies[0]['reason']})
            continue
        relation = bind_profile(profile, customer, list(services.values()), sites, snapshot['finance_invoices'], snapshot['generated'].get(pid, []), reviewed=reviewed_links.get(pid))
        if relation['account_id'] in accounts and synthetic(accounts[relation['account_id']]): continue
        if relation['decision'] != 'LINKED': unlinked.append(relation);continue
        sid = relation['service_id']
        if synthetic(services[sid]) or synthetic(sites[relation['site_id']]): continue
        if sid in linked: raise ValueError('Multiple billing profiles require explicit Service scope review')
        linked[sid] = (profile, relation)
    for sid, service in services.items():
        site = sites.get(identity(service.get('Linked_Service_Location')))
        if not site or synthetic(service) or synthetic(site) or synthetic(accounts.get(identity(site.get('Linked_Account')), {})): continue
        pair = linked.get(sid);profile = pair[0] if pair else None
        invoices = snapshot['generated'].get(identity(profile.get('recurring_invoice_id')), []) if profile else []
        row = project_service(service, site, profile, invoices, now=now, cases=snapshot.get('cases', []))
        rows.append(row)
        for a in row['attention']:attention_rows[a['key']] = a
    # One concise missing-link card per Account, not one card per billing profile.
    for account in sorted({r['account_id'] for r in unlinked}):
        a = attention(account, 'MISSING_RECURRING_LINK', account, 'Books recurring profiles lack deterministic Service/Site linkage', 'Review recurring Service association; no protected data repair')
        a.update(module='Accounts', identity=account, context=accounts.get(account, {}).get('Account_Name') or 'Recurring customer');attention_rows[a['key']] = a
    # Contextual opportunities are internal, per Site, never messages or new Deals.
    for site in sites.values():
        if synthetic(site): continue
        active = [s for s in rows if s['site_id'] == identity(site['id']) and s['service_stage'] == 'Active']
        native = [services[s['id']] for s in active]
        types = {str(s.get('Service_Type') or '') for s in native}
        if 'Cabling Installation' in types and 'Wifi Installation' not in types:
            a = attention(identity(site['id']), 'OPPORTUNITY', 'managed-wifi', 'Known cabling Service; no recorded WiFi Service at this Site', 'Owner decides whether Managed WiFi is relevant')
            a.update(module='Service_Locations', context=site.get('Name') or 'Service Location');attention_rows[a['key']] = a
    return {'schema': 1, 'scope': 'live', 'read_only': True, 'at': now.isoformat(), 'state': 'READY', 'rows': rows,
            'attention': list(attention_rows.values()), 'recurring_services': sum(r['recurring'] for r in rows),
            'books_profiles': len(profiles), 'profiles_linked': len(linked), 'unlinked': unlinked,
            'financial_writes': 0, 'customer_sends': 0, 'crm_writes': 0, 'billing_engine': 'ZOHO_BOOKS'}


def render_recurring(value):
    from html import escape
    h = lambda v: escape(str(v if v is not None else 'Unknown'), quote=True)
    rows = ''.join('<article><h2>'+h(r['name'])+'</h2><p>'+h(r['health'])+' · Billing '+h(r['billing_state'])+'</p>'+
        '<p>Amount '+h(r['observed_amount'])+' '+h(r['currency'])+' · Next billing '+h(r['next_billing_date'])+'</p></article>' for r in value['rows'] if r['recurring'] and not r['test_only'])
    cards = ''.join('<li>'+h(a['context'])+': '+h(a['why'])+' — '+h(a['next_action'])+'</li>' for a in value['attention'] if not a.get('test_only'))
    return '<!doctype html><html lang="en"><meta charset="utf-8"><title>Recurring Services</title><h1>Recurring Services</h1><p>Books owns recurring billing. Prices, renewals and scheduling remain human.</p><p>Observed '+h(value.get('observed_at',value['at']))+' · '+str(value['books_profiles'])+' Books profiles · '+str(value['profiles_linked'])+' verified Service links.</p><ul>'+cards+'</ul>'+rows+'</html>'
