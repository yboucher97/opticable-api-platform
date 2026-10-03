"""Pure operational plans over native CRM records and observed Books state.

These functions do not call a provider, grant mutation authority, choose a date,
assign a technician, or change money. The root runner must independently check
lineage, protected records, owner transitions and exact effect claims before
executing a plan. Existing durable Services retain their original Deal link.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import re
import unicodedata
from zoneinfo import ZoneInfo

from .lifecycle import SERVICES, SITE_FIELDS, aware
from .lifecycle_control import digest

TIMEZONE = ZoneInfo('America/Toronto')
NATIVE_INSTALLATION_STATES = frozenset({
    'Requested', 'Scheduled', 'In Progress', 'Completed', 'Failed',
    'Revisit Required', 'Cancelled',
})
# Native Service_Type deliberately models several kinds as Other. Reuse of
# those kinds requires an exact business label; Other alone is insufficient.
SERVICE_TYPES = {**SERVICES, 'Telephony': 'VoIP Installation', 'Intercom': 'Other',
                 'AI Loss Prevention': 'Other'}
SUPPRESSED_SERVICES = frozenset({'Cancelled', 'Suspended'})


def _human(reason, **context):
    return {'decision': 'HUMAN', 'reason': reason, 'external_sends': False,
            'financial_writes': False, **context}


def _id(value):
    if isinstance(value, dict):
        value = value.get('id')
    value = str(value or '')
    return value if re.fullmatch(r'[0-9]{1,30}', value) else ''


def _fold(value):
    value = unicodedata.normalize('NFKD', str(value or '').casefold())
    return ''.join(c for c in value if not unicodedata.combining(c))


def _tokens(value):
    return re.findall(r'[a-z0-9]+', _fold(value))


def _street(value):
    words = _tokens(value)
    # Normalize explicit street-designator tokens only, never edit a street
    # name or discard a civic-number suffix, direction, unit or building.
    equivalents = {'street': 'st', 'avenue': 'ave', 'av': 'ave', 'road': 'rd',
                    'boulevard': 'blvd', 'boul': 'blvd', 'drive': 'dr',
                    'court': 'ct', 'crescent': 'cres', 'rue': 'rue',
                    'chemin': 'ch', 'route': 'rte'}
    positions = {len(words) - 1}
    if words and words[-1] in {'n', 's', 'e', 'w', 'north', 'south', 'east', 'west'}:
        positions.add(len(words) - 2)
    for position in positions:
        if position >= 1:
            words[position] = equivalents.get(words[position], words[position])
    return tuple(words)


def _unit(value):
    value = _fold(value).strip()
    value = re.sub(r'^(?:unit|suite|ste|apt|apartment|appartement|app)\.?\s+', '', value)
    value = re.sub(r'^#\s*', '', value)
    # Hyphen and slash carry identity; a whitespace/punctuation tokenizer
    # must not silently merge unit 2-A with 2A or unit 5/12 with 512.
    pieces = re.findall(r'[a-z]+|\d+|[-/]', value)
    return tuple(str(int(piece)) if piece.isdigit() else piece for piece in pieces)


def normalized_site_key(address):
    """Exact Canadian components with conservative abbreviation normalization.

    A spelling difference is not a match. Unit prefixes are normalized only in
    the dedicated unit component; a missing unit is never inferred.
    """
    parts = {key: str(address.get(key, address.get(field, '')) or '').strip()
             for key, field in SITE_FIELDS.items()}
    province = {'qc': 'qc', 'quebec': 'qc', 'on': 'on', 'ontario': 'on'}.get(_fold(parts['province']))
    country = {'ca': 'ca', 'canada': 'ca'}.get(_fold(parts['country']))
    postal = re.sub(r'\s', '', parts['postal_code']).upper()
    street = _street(parts['street'])
    if (not province or not country or not re.fullmatch(r'[A-Z]\d[A-Z]\d[A-Z]\d', postal)
            or not street or not re.search(r'\d', street[0]) or not parts['city']):
        return None
    unit = _unit(parts['unit'])
    return street, unit, tuple(_tokens(parts['city'])), province, postal, country


def operational_site_match(sites, account_id, address):
    """Reuse an exact site, or hold plausible same-building spelling collisions."""
    account_id = _id(account_id)
    key = normalized_site_key(address)
    if not account_id or key is None:
        return _human('Complete Account and structured Canadian address required')
    existing = [row for row in sites if _id(row.get('Linked_Account')) == account_id]
    keys = [(row, normalized_site_key(row)) for row in existing]
    if any(other is None for _, other in keys):
        return _human('Existing Account site lacks a complete address; reconcile before creating')
    matches = [row for row, other in keys if other == key]
    if len(matches) > 1:
        return _human('More than one Service Location has this address')
    if matches:
        return {'decision': 'REUSE', 'record': matches[0], 'key': key}
    for row, other in keys:
        # Same civic token, same unit/postal can be a typo or differing street
        # wording; preserve distinct sites and request a human choice.
        civic = re.match(r'\d+', other[0][0])
        target_civic = re.match(r'\d+', key[0][0])
        same_building = civic and target_civic and civic.group() == target_civic.group() and other[4:] == key[4:]
        if same_building and (not other[1] or not key[1] or ''.join(other[1]).replace('-', '').replace('/', '') == ''.join(key[1]).replace('-', '').replace('/', '')):
            return _human('Possible street spelling collision; choose the site in CRM',
                          candidate_id=_id(row))
    return {'decision': 'CREATE', 'record': None, 'key': key}


def _service_label(row):
    label = str(row.get('_verified_service_label') or '').strip()
    if label in SERVICE_TYPES:
        return label
    # Explicit native business-name prefix, as emitted by the existing runner.
    name = str(row.get('Name') or '').strip()
    matches = [label for label in SERVICE_TYPES
               if name == label or name.startswith(label + ' — ')]
    return matches[0] if len(matches) == 1 else None


def durable_service_plan(service_types, site_id, services):
    """Reuse an installed system at this Site across visits and later Deals.

    _verified_service_label is optional caller-supplied root lineage evidence,
    never a writable CRM field. Distinct systems of the same kind need a human
    selection; no fuzzy name match or automatic destructive merge is allowed.
    """
    site_id = _id(site_id)
    requested = [value.strip() for value in str(service_types or '').split(',') if value.strip()]
    if (not site_id or not requested or len(set(requested)) != len(requested)
            or any(value not in SERVICE_TYPES for value in requested)):
        return _human('Accepted scope needs a supported, unique service-kind mapping')
    existing = [row for row in services if _id(row.get('Linked_Service_Location')) == site_id]
    result = []
    for label in requested:
        native_type = SERVICE_TYPES[label]
        candidates = [row for row in existing if row.get('Service_Type') == native_type]
        if native_type == 'Other':
            if any(_service_label(row) is None for row in candidates):
                return _human('Existing Other Service has ambiguous business identity')
            candidates = [row for row in candidates if _service_label(row) == label]
        if len(candidates) > 1:
            return _human('Multiple durable Services match; select the system in CRM')
        if candidates and candidates[0].get('Service_Stage') in SUPPRESSED_SERVICES:
            return _human('Matching Service is cancelled or suspended; owner review required')
        result.append({'decision': 'REUSE' if candidates else 'CREATE', 'label': label,
                       'type': native_type, 'record': candidates[0] if candidates else None})
    return {'decision': 'PREPARE_INTERNAL', 'site_id': site_id, 'services': result,
            'external_sends': False, 'financial_writes': False}


def accepted_work_plan(*, estimate, deal, account, contact, site, services,
                       protected_ids=frozenset()):
    """Plan accepted work without inventing scope or replacing native links."""
    account_id, deal_id, site_id, contact_id = map(_id, (account, deal, site, contact))
    ids = {account_id, deal_id, site_id, contact_id}
    if not all(ids) or ids & set(map(str, protected_ids)):
        return _human('Accepted work has missing or protected business lineage')
    if (estimate.get('status') != 'accepted' or not _id(estimate.get('transaction_id'))
            or _id(estimate.get('account_id')) != account_id
            or _id(estimate.get('deal_id')) != deal_id or _id(estimate.get('site_id')) != site_id
            or _id(deal.get('Account_Name')) != account_id
            or _id(deal.get('Contact_Name')) != contact_id
            or _id(deal.get('Service_Location')) != site_id
            or _id(contact.get('Account_Name')) != account_id
            or _id(site.get('Linked_Account')) != account_id):
        return _human('Accepted Estimate/Account/Contact/Deal/Site relationships disagree')
    if deal.get('Stage') in {'Closed Lost', 'Closed Lost to Competition', 'Estimate Rejected'}:
        return _human('Owner closed or rejected the Deal; do not restart operations')
    planned = durable_service_plan(deal.get('Service_Types'), site_id, services)
    if planned['decision'] == 'HUMAN':
        return planned
    if any(_id(row['record']) in set(map(str, protected_ids)) for row in planned['services'] if row['record']):
        return _human('Matching Service belongs to the protected historical baseline')
    return {**planned, 'account_id': account_id, 'contact_id': contact_id, 'deal_id': deal_id,
            'estimate_id': str(estimate.get('transaction_id') or ''),
            'workdrive': ['Account', 'General', 'Service Location', 'Contracts'],
            'contract': 'PREPARE_ONLY', 'installation': 'UNSCHEDULED',
            'attention': 'SCHEDULE INSTALLATION', 'preserve_existing_service_deal': True}


def installation_context(installation, *, services, sites, accounts, deals, contacts,
                         links=(), deal_id=None, protected_ids=frozenset()):
    """Derive native Installation context through its Service and join records.

    Existing durable Services may have an older Linked_Deal; caller-supplied
    deal_id must come from immutable installation lineage, not a UI guess.
    """
    installation_id = _id(installation)
    primary = _id(installation.get('Linked_Service'))
    service_ids = {primary} if primary else set()
    service_ids |= {_id(link.get('Linked_Service')) for link in links
                    if _id(link.get('Linked_Installation')) == installation_id}
    if not installation_id or not service_ids or '' in service_ids:
        return _human('Installation requires explicit native Service relationships')
    selected = [row for row in services if _id(row) in service_ids]
    if len(selected) != len(service_ids) or {_id(row) for row in selected} != service_ids:
        return _human('Linked Service is missing or ambiguous')
    site_ids = {_id(row.get('Linked_Service_Location')) for row in selected}
    if len(site_ids) != 1 or '' in site_ids:
        return _human('Installation Services span missing or multiple Service Locations')
    site_id = next(iter(site_ids))
    site_matches = [row for row in sites if _id(row) == site_id]
    if len(site_matches) != 1:
        return _human('Installation Service Location unavailable or ambiguous')
    site = site_matches[0]
    account_id = _id(site.get('Linked_Account'))
    account_matches = [row for row in accounts if _id(row) == account_id]
    if len(account_matches) != 1:
        return _human('Installation Account unavailable or ambiguous')
    if deal_id is None:
        deal_ids = {_id(row.get('Linked_Deal')) for row in selected}
        if len(deal_ids) != 1 or '' in deal_ids:
            return _human('Installation Deal needs immutable linkage for existing Services')
        deal_id = next(iter(deal_ids))
    deal_id = _id(deal_id)
    deal_matches = [row for row in deals if _id(row) == deal_id]
    if len(deal_matches) != 1:
        return _human('Installation Deal unavailable or ambiguous')
    deal = deal_matches[0]
    contact_id = _id(deal.get('Contact_Name'))
    contact_matches = [row for row in contacts if _id(row) == contact_id]
    if (not contact_id or len(contact_matches) != 1
            or _id(contact_matches[0].get('Account_Name')) != account_id
            or _id(deal.get('Account_Name')) != account_id
            or _id(deal.get('Service_Location')) != site_id):
        return _human('Installation Account/Deal/Contact/Site association disagrees')
    ids = {installation_id, site_id, account_id, contact_id, deal_id, *service_ids}
    if ids & set(map(str, protected_ids)):
        return _human('Installation includes protected historical business lineage')
    return {'decision': 'PREPARE_INTERNAL', 'installation_id': installation_id,
            'account_id': account_id, 'deal_id': deal_id, 'contact_id': contact_id,
            'site_id': site_id, 'service_ids': sorted(service_ids),
            'context': {'account': account_matches[0].get('Account_Name'),
                        'deal': deal.get('Deal_Name'), 'site': site.get('Name'),
                        'contact': contact_matches[0].get('Full_Name') or contact_matches[0].get('Last_Name'),
                        'services': [row.get('Name') for row in selected],
                        'workdrive_url': site.get('Service_Location_Workdrive_Folder_URL')},
            'external_sends': False, 'financial_writes': False}


def installation_progress_plan(installation, context, *, services=(), owner_trigger=False,
                               completed_at=None, mutable_service_ids=frozenset(), now=None):
    """Observe human progress, activate only authorized Services after completion."""
    if context.get('decision') != 'PREPARE_INTERNAL' or _id(installation) != context.get('installation_id'):
        return _human('Validated Installation context required')
    status = installation.get('Installation_Status')
    if status not in NATIVE_INSTALLATION_STATES:
        return _human('Unsupported Installation status; use an existing CRM transition')
    plan = {'decision': 'OBSERVE', 'installation_id': _id(installation), 'status': status,
            'patches': [], 'external_sends': False, 'financial_writes': False}
    if status in {'Failed', 'Revisit Required'}:
        reason = str(installation.get('Instructions_Notes') or '').strip()
        if not reason:
            return _human('Blocked or return visit requires a reason in Instructions Notes',
                          attention='INSTALLATION BLOCKED — ADD REASON')
        return {**plan, 'attention': 'RETURN VISIT NEEDED' if status == 'Revisit Required' else 'INSTALLATION BLOCKED',
                'reason': reason, 'activate_services': False}
    if status == 'Cancelled':
        return {**plan, 'attention': 'INSTALLATION CANCELLED', 'activate_services': False}
    if status == 'Requested':
        return {**plan, 'attention': 'SCHEDULE INSTALLATION', 'activate_services': False}
    if status in {'Scheduled', 'In Progress'}:
        if not installation.get('Scheduled_Date'):
            return _human('Human schedule date/time required; do not choose it automatically')
        try:
            scheduled = aware(installation['Scheduled_Date'])
        except (ValueError, TypeError):
            return _human('Schedule needs explicit timezone/date/time')
        return {**plan, 'attention': 'INSTALLATION IN PROGRESS' if status == 'In Progress' else 'INSTALLATION SCHEDULED',
                'scheduled_local': scheduled.astimezone(TIMEZONE).isoformat(), 'activate_services': False,
                'access_attention': not bool(str(installation.get('Instructions_Notes') or '').strip())}
    if not owner_trigger:
        return _human('Completion requires an independently verified human CRM transition')
    if not str(installation.get('Completion_Notes') or '').strip():
        return _human('Completion evidence required in Completion Notes')
    try:
        at = aware(completed_at)
    except (ValueError, TypeError):
        return _human('Verified human completion timestamp required')
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        return _human('Current observation time needs a timezone')
    if at > current + timedelta(minutes=5):
        return _human('Completion timestamp is in the future')
    selected = [row for row in services if _id(row) in set(context['service_ids'])]
    if len(selected) != len(context['service_ids']) or {_id(row) for row in selected} != set(context['service_ids']):
        return _human('Complete linked Service inventory required before activation')
    mutable = set(map(str, mutable_service_ids))
    day = at.astimezone(TIMEZONE).date().isoformat()
    preserved = []
    for row in selected:
        if row.get('Service_Stage') in SUPPRESSED_SERVICES:
            return _human('Owner suppressed a linked Service; completion must not reactivate it')
        patch = {'OptiBrain_Last_Service_On': day}
        if row.get('Service_Stage') != 'Active':
            patch['Service_Stage'] = 'Active'
        if not row.get('OptiBrain_Installed_On'):
            patch['OptiBrain_Installed_On'] = day
        patch = {key: value for key, value in patch.items() if row.get(key) != value}
        if patch and _id(row) not in mutable:
            if row.get('Service_Stage') != 'Active':
                return _human('Service activation lacks mutable record lineage')
            # An existing Active system can receive another visit without
            # changing its historical metadata or original commercial link.
            # This visit's date/evidence stays in the root Installation context.
            preserved.append(_id(row))
            continue
        if patch:
            plan['patches'].append({'module': 'Services', 'id': _id(row),
                                    'scope': 'crm.service.activate', 'patch': patch})
    return {**plan, 'activate_services': True, 'completed_at': at.isoformat(),
            'preserved_reference_service_ids': preserved,
            'completion_evidence': {'notes': str(installation['Completion_Notes']),
                                    'proof_url': installation.get('Completion_Proof_Link')},
            'attention': 'CREATE / SEND INVOICE', 'contract_send': 'HUMAN',
            'post_sale': 'SUPPORT / WARRANTY CONTEXT READY',
            'effect_key': digest({'installation': _id(installation), 'human_completed_at': at.isoformat()})}


def return_visit_plan(installation, context, *, transition_id, known_visits=None, owner_trigger=False):
    """Preserve original visit and durable Services; new visit stays unscheduled."""
    if (not owner_trigger or context.get('decision') != 'PREPARE_INTERNAL'
            or _id(installation) != context.get('installation_id')
            or installation.get('Installation_Status') != 'Revisit Required'
            or not str(installation.get('Instructions_Notes') or '').strip()
            or not re.fullmatch(r'[A-Za-z0-9:_-]{1,200}', str(transition_id or ''))):
        return _human('Return visit requires reason and verified stable human transition identity')
    key = digest({'kind': 'return_visit', 'installation': _id(installation), 'transition': transition_id})
    old = (known_visits or {}).get(key)
    if old:
        if (old.get('parent_installation_id') != _id(installation)
                or set(old.get('service_ids') or []) != set(context['service_ids'])
                or old.get('deal_id') != context['deal_id'] or not _id(old.get('installation_id'))):
            return _human('Existing return-visit evidence conflicts; reconcile without retry')
        return {'decision': 'REUSE', 'effect_key': key, 'record_id': old['installation_id'],
                'preserve_original': True, 'service_ids': context['service_ids']}
    return {'decision': 'PREPARE_INTERNAL', 'effect_key': key, 'parent_installation_id': _id(installation),
            'deal_id': context['deal_id'], 'service_ids': context['service_ids'],
            'row': {'Name': ('Return visit — ' + str(installation.get('Name') or 'Installation'))[:120],
                    'Linked_Service': {'id': context['service_ids'][0]}, 'Installation_Status': 'Requested',
                    'Instructions_Notes': str(installation['Instructions_Notes'])[:4000]},
            'preserve_original': True, 'create_services': False, 'attention': 'SCHEDULE RETURN VISIT',
            'external_sends': False, 'financial_writes': False}


def invoice_progress_plan(native, books, *, deals, sites, services, now=None,
                          service_ids=None, protected_ids=frozenset()):
    """Read native Finance/Books relationships and derive internal billing state."""
    transaction = _id(native.get('Invoice_ID'))
    account_id = _id(native.get('Account_Name'))
    deal_id = _id(native.get('Potential_Name') or native.get('PotentialName'))
    if (not transaction or transaction != _id(books.get('invoice_id')) or not account_id or not deal_id
            or books.get('zcrm_potential_id') and _id(books['zcrm_potential_id']) != deal_id
            or books.get('zcrm_account_id') and _id(books['zcrm_account_id']) != account_id):
        return _human('Native Finance Invoice/Books/Account/Deal relationships disagree')
    selected = [row for row in deals if _id(row) == deal_id]
    if len(selected) != 1 or _id(selected[0].get('Account_Name')) != account_id:
        return _human('Invoice must belong to one native Account/Deal')
    deal = selected[0]
    if deal.get('Service_Location') and not _id(deal['Service_Location']):
        return _human('Present Deal Service Location lookup is malformed')
    linked = [row for row in services if _id(row.get('Linked_Deal')) == deal_id]
    if service_ids is not None:
        requested = set(map(str, service_ids))
        linked = [row for row in services if _id(row) in requested]
        if len(linked) != len(requested) or {_id(row) for row in linked} != requested:
            return _human('Invoice Service linkage evidence is incomplete')
    site_ids = {_id(row.get('Linked_Service_Location')) for row in linked}
    if _id(deal.get('Service_Location')):
        site_ids.add(_id(deal['Service_Location']))
    if len(site_ids) != 1 or '' in site_ids:
        return _human('Invoice requires one unambiguous Service Location')
    site_id = next(iter(site_ids))
    matched = [row for row in sites if _id(row) == site_id]
    if len(matched) != 1 or _id(matched[0].get('Linked_Account')) != account_id:
        return _human('Invoice site does not belong to the native Account')
    if {account_id, deal_id, site_id, *[_id(row) for row in linked]} & set(map(str, protected_ids)):
        return _human('Protected Finance context is read-only; no automatic lifecycle progression')
    try:
        total, balance = Decimal(str(books['total'])), Decimal(str(books['balance']))
        if not total.is_finite() or not balance.is_finite() or min(total, balance) < 0 or balance > total:
            raise ValueError('Invalid amount')
    except (KeyError, InvalidOperation, ValueError):
        return _human('Books amount/balance is unavailable or inconsistent')
    status = str(books.get('status') or '').lower()
    if status not in {'draft', 'sent', 'viewed', 'paid', 'void', 'partially_paid', 'partial_paid', 'unpaid', 'overdue'} or status == 'paid' and balance != 0:
        return _human('Books payment status and balance disagree')
    attention, financial_state = 'INVOICE OBSERVED', 'OPEN'
    if status in {'void', 'draft'}:
        attention, financial_state = 'REVIEW INVOICE', status.upper()
    elif status == 'paid':
        attention, financial_state = 'PAYMENT OBSERVED — PAID', 'SATISFIED'
    elif balance > 0:
        due = books.get('due_date')
        if not due:
            return _human('Unpaid Invoice due date required for billing attention')
        try:
            due_date = datetime.strptime(str(due), '%Y-%m-%d').date()
        except ValueError:
            return _human('Invoice due date is invalid')
        current = (now or datetime.now(timezone.utc)).astimezone(TIMEZONE).date()
        attention = 'INVOICE OVERDUE' if due_date < current else 'INVOICE PAYMENT ATTENTION'
        financial_state = 'PARTIAL' if balance < total else 'UNPAID'
    else:
        attention, financial_state = 'REVIEW ZERO BALANCE PAYMENT STATE', 'UNCONFIRMED'
    return {'decision': 'OBSERVE', 'transaction_id': transaction, 'number': books.get('invoice_number'),
            'account_id': account_id, 'deal_id': deal_id, 'site_id': site_id,
            'service_ids': [_id(row) for row in linked], 'status': status,
            'amount': str(total), 'balance': str(balance), 'due_date': books.get('due_date'),
            'attention': attention, 'financial_state': financial_state,
            'clear_billing_attention': financial_state == 'SATISFIED',
            'external_sends': False, 'financial_writes': False}


def support_case_plan(issue, context, *, source_event_id, existing_cases=(),
                      protected_ids=frozenset()):
    """Prepare a native Case and root site/service/visit context, with no triage AI."""
    if (context.get('decision') != 'PREPARE_INTERNAL'
            or not re.fullmatch(r'[A-Za-z0-9:_-]{1,200}', str(source_event_id or ''))):
        return _human('Support intake needs a stable source and validated site/service context')
    required = {context.get(key) for key in ('account_id', 'contact_id', 'deal_id', 'site_id')}
    required |= set(context.get('service_ids') or [])
    if any(not _id(value) for value in required) or required & set(map(str, protected_ids)):
        return _human('Support business lineage missing or protected')
    subject = str(issue.get('subject') or '').strip()
    description = str(issue.get('description') or '').strip()
    if not subject or not description:
        return _human('Support issue subject and description required')
    # No keyword-based emergency decision or automatic priority assignment.
    if issue.get('emergency') is not False:
        return _human('Human must determine whether this support request is an emergency')
    key = digest({'kind': 'support_case', 'source': source_event_id})
    matches = [row for row in existing_cases if row.get('_source_effect_key') == key]
    if len(matches) > 1:
        return _human('Multiple Cases claim this support intake; reconcile before continuing')
    if matches:
        row = matches[0]
        if (not _id(row) or _id(row) in set(map(str, protected_ids))
                or _id(row.get('Account_Name')) != context['account_id']
                or _id(row.get('Related_To')) != context['contact_id']
                or _id(row.get('Deal_Name')) != context['deal_id']):
            return _human('Existing Case has different customer relationships')
        return {'decision': 'REUSE', 'effect_key': key, 'record_id': _id(row)}
    business = context.get('context') or {}
    text = (description + '\n\nService location: ' + str(business.get('site') or '')
            + '\nServices: ' + ', '.join(str(value) for value in business.get('services') or [])
            + '\nNext action: human review of customer support request.')[:4000]
    return {'decision': 'PREPARE_INTERNAL', 'effect_key': key,
            'row': {'Subject': subject[:120], 'Status': 'New', 'Case_Origin': 'Web',
                    'Account_Name': {'id': context['account_id']},
                    'Related_To': {'id': context['contact_id']},
                    'Deal_Name': {'id': context['deal_id']}, 'Description': text},
            'support_context': {key: context.get(key) for key in (
                'account_id', 'contact_id', 'deal_id', 'site_id', 'service_ids', 'installation_id')},
            'attention': 'SUPPORT CASE — HUMAN REVIEW', 'external_sends': False,
            'financial_writes': False}
