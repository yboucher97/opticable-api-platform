"""Read-only acquisition/Finance lineage. No analytics or advertising transport.

Invoice value is observed gross invoiced value, not recognized revenue or cash.
Missing relationships stay unattributed; an Account never supplies a guessed Deal.
"""
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from html import escape
import re
from .recurring_lifecycle import identity, index, money, synthetic, bind_profile


def label(value, fallback='UNATTRIBUTED'):
    value = str(value or '').strip()
    # Raw URL, names, email, click IDs and query strings never enter reports.
    if not value or '@' in value or re.search(r'https?://|[?&=]|\+?\d[\d .()-]{7,}', value):
        return fallback
    return re.sub(r'[<>\r\n]', '', value)[:120]


def acquisition(record):
    return {'source': label(record.get('First_Source') or record.get('Lead_Source')),
            'medium': label(record.get('First_Medium'), 'Not recorded'),
            'campaign': label(record.get('First_Campaign'), 'Not recorded'),
            'last_source': label(record.get('Last_Source')),
            'last_campaign': label(record.get('Last_Campaign'), 'Not recorded')}


def outcome(kind, record_id):
    if kind not in {'qualified_lead', 'estimate_sent', 'estimate_accepted', 'customer_won', 'invoice_observed'} or not identity(record_id):
        raise ValueError('Canonical outcome identity required')
    return {'kind': kind, 'key': sha256(('opticable:v1:'+kind+':'+record_id).encode()).hexdigest(),
            'record_id': record_id, 'provider': 'google_ads', 'version': 1, 'external_upload': False}


def conversion_plan(record, kind, *, destination=None, consent=None):
    """An internal readiness plan, never an upload payload or permission."""
    event = outcome(kind, identity(record.get('id')))
    reasons = []
    if synthetic(record): reasons.append('TEST_ONLY')
    if not destination or destination.get('verified') is not True or not destination.get('conversion_action'):
        reasons.append('Provider destination unverified')
    if not consent or consent.get('ad_user_data') != 'GRANTED' or not consent.get('recorded_at'):
        reasons.append('Advertising consent unproven; contact/analytics consent is insufficient')
    if not any(record.get(k) for k in ('Google_GCLID', 'Google_GBRAID', 'Google_WBRAID')):
        reasons.append('No supported Google click evidence')
    try:
        at = datetime.fromisoformat(str(record.get('Outcome_Time','')).replace('Z','+00:00'))
        if at.tzinfo is None:raise ValueError('Offset required')
    except ValueError:reasons.append('Outcome timing unproven; Lead creation is not qualification time')
    # Even a fully supported plan needs a separately reviewed destination and
    # scoped transport family. This module cannot turn reporting into a send.
    return {**event, 'readiness': 'EXCLUDED' if synthetic(record) else 'PARTIAL' if reasons else 'READY_FOR_REVIEW',
            'reasons': reasons, 'contains_pii': False}


def build_marketing(snapshot, *, recurring_links=None):
    from .measurement import populations
    from .finance_links import resolve_finance
    link_rows=populations(snapshot)[0]
    collections = {k: index(snapshot.get(k, [])) for k in
        ('accounts', 'contacts', 'leads', 'deals', 'sites', 'services', 'finance_estimates', 'finance_invoices')}
    accounts, contacts, leads, deals = (collections[k] for k in ('accounts', 'contacts', 'leads', 'deals'))
    excluded = {k: {i for i, r in rows.items() if synthetic(r)} for k, rows in collections.items()}
    # Propagate TEST lineage before any business count, financial value or plan.
    for cid, row in contacts.items():
        if identity(row.get('Account_Name')) in excluded['accounts']: excluded['contacts'].add(cid)
    for lid, row in leads.items():
        detail = row.get('$converted_detail') or {}
        if identity(detail.get('account')) in excluded['accounts'] or identity(detail.get('contact')) in excluded['contacts']:
            excluded['leads'].add(lid)
    for did, row in deals.items():
        if identity(row.get('Account_Name')) in excluded['accounts'] or identity(row.get('Contact_Name')) in excluded['contacts']:
            excluded['deals'].add(did)
    for lid, row in leads.items():
        detail = row.get('$converted_detail') or {}
        did = identity(detail.get('deal'))
        if lid in excluded['leads'] and did:excluded['deals'].add(did)
        if did in excluded['deals']:excluded['leads'].add(lid)
    for sid, row in collections['sites'].items():
        if identity(row.get('Linked_Account')) in excluded['accounts']: excluded['sites'].add(sid)
    for sid, row in collections['services'].items():
        if identity(row.get('Linked_Service_Location')) in excluded['sites'] or identity(row.get('Linked_Deal')) in excluded['deals']:
            excluded['services'].add(sid)
    customers = index(snapshot.get('customers', []), 'contact_id')
    test_customers = {i for i, r in customers.items() if synthetic(r) or identity(r.get('zcrm_account_id')) in excluded['accounts']}
    profiles = index(snapshot.get('profiles', []), 'recurring_invoice_id')
    test_profiles = {i for i, r in profiles.items() if synthetic(r) or identity(r.get('customer_id')) in test_customers}
    # Use the same fixed-point/native-descendant population as financial reports.
    # Keep the original exclusion diagnostics; filtering is not evidence of zero TEST traffic.
    collections={k:link_rows[k] for k in collections}
    accounts,contacts,leads,deals=(collections[k] for k in ('accounts','contacts','leads','deals'))
    customers=link_rows['customers'];profiles=link_rows['profiles']
    recurring = {}
    for pid, profile in profiles.items():
        if pid in test_profiles: continue
        link = bind_profile(profile, customers.get(identity(profile.get('customer_id')), {}),
            list(collections['services'].values()), collections['sites'], snapshot.get('finance_invoices', []),
            snapshot.get('generated', {}).get(pid, []), reviewed=(recurring_links or {}).get(pid))
        if link['decision'] == 'LINKED' and link['service_id'] not in excluded['services']:
            recurring[pid] = link
    groups = {}; problems = defaultdict(int); outcomes = {}; lifetime = {}
    def group(record):
        touch = acquisition(record); key = (touch['source'], touch['medium'], touch['campaign'])
        if key not in groups:
            groups[key] = {'source':touch['source'], 'medium':touch['medium'], 'campaign':touch['campaign'], **{k: 0 for k in ('leads', 'qualified_leads', 'deals', 'estimates', 'accepted_estimates')},
                'invoice_value': {}, 'paid_invoice_value': {}, 'recurring_invoice_value': {},
                'spend': None, 'roas': None}
        return groups[key]
    def event(kind, rid):
        value = outcome(kind, rid);outcomes[value['key']] = value
    def amount(bucket, currency, value):
        if not re.fullmatch(r'[A-Z]{3}', str(currency or '')): raise ValueError('Native Invoice currency required')
        bucket[currency] = str(money(bucket.get(currency, '0')) + money(value))
    def canonical_deal(did, account):
        row = deals.get(did)
        if not row or not account or identity(row.get('Account_Name')) != account:
            return None
        return row
    for lid, row in leads.items():
        if lid in excluded['leads']: continue
        g = group(row);g['leads'] += 1
        if row.get('$converted') is True or row.get('Lead_Status') in {'Qualified', 'Prepare Estimate'}:
            g['qualified_leads'] += 1;event('qualified_lead', lid)
    for did, row in deals.items():
        if did in excluded['deals']: continue
        group(row)['deals'] += 1
        aid = identity(row.get('Account_Name'))
        if aid in accounts and row.get('Stage') == 'Closed Won': event('customer_won', aid)
    for eid, row in collections['finance_estimates'].items():
        aid = identity(row.get('Account_Name'));did = identity(row.get('Potential_Name'))
        if eid in excluded['finance_estimates'] or aid in excluded['accounts'] or did in excluded['deals']: continue
        books = link_rows['estimates'].get(identity(row.get('Estimate_ID')))
        if books and (synthetic(books) or identity(books.get('customer_id')) in test_customers):continue
        resolved=resolve_finance(books,'estimates',link_rows) if books else None
        if resolved and resolved['conflict']:
            problems['Estimate Deal association conflicts']+=1;continue
        did=resolved['deal_id'] if resolved else did
        deal = canonical_deal(did, aid)
        if not deal: problems['Estimate has no verified Deal association'] += 1
        g = group(deal or {});g['estimates'] += 1
        if not books: problems['Estimate status lacks Books observation'] += 1;continue
        cid = identity(books.get('customer_id'));customer = customers.get(cid)
        if cid in test_customers: continue
        if not customer or identity(customer.get('zcrm_account_id')) != aid:
            problems['Estimate customer/Account needs reconciliation'] += 1;continue
        if books.get('zcrm_potential_id') and identity(books['zcrm_potential_id']) != did:
            problems['Estimate Deal association conflicts'] += 1;continue
        status = books.get('status')
        if status in {'sent', 'accepted', 'declined'}: event('estimate_sent', eid)
        if status == 'accepted': g['accepted_estimates'] += 1;event('estimate_accepted', eid)
    native_finance = defaultdict(list)
    for fid, row in collections['finance_invoices'].items():
        native_finance[identity(row.get('Invoice_ID'))].append((fid, row))
    invoices = link_rows['invoices']
    for iid, invoice in invoices.items():
        cid = identity(invoice.get('customer_id'));pid = identity(invoice.get('recurring_invoice_id'))
        if synthetic(invoice) or cid in test_customers or pid in test_profiles: continue
        if invoice.get('status') in {'draft', 'void'}: continue
        related = native_finance.get(iid, [])
        if len(related) > 1: raise ValueError('Multiple CRM Finance records claim one Books Invoice')
        if related:
            fid, finance = related[0]
            if fid in excluded['finance_invoices'] or identity(finance.get('Account_Name')) in excluded['accounts'] or identity(finance.get('Potential_Name')) in excluded['deals']: continue
        else: finance = {}
        customer = customers.get(cid);aid = identity((customer or {}).get('zcrm_account_id'))
        linked_account = identity(finance.get('Account_Name'))
        if linked_account and linked_account != aid:
            problems['Invoice customer/Account needs reconciliation'] += 1;continue
        did = identity(finance.get('Potential_Name')) or identity(invoice.get('zcrm_potential_id'))
        if finance.get('Potential_Name') and invoice.get('zcrm_potential_id') and identity(invoice['zcrm_potential_id']) != identity(finance['Potential_Name']):
            problems['Invoice Deal association conflicts'] += 1;continue
        if did in excluded['deals']: continue
        resolved=resolve_finance(invoice,'invoices',link_rows)
        if resolved['conflict']:
            problems['Invoice Deal association conflicts']+=1;continue
        did=resolved['deal_id']
        deal = canonical_deal(did, aid)
        link = recurring.get(pid)
        if link and link['customer_id'] == cid and link['account_id'] == aid:
            # Retain the Service's acquisition Deal, not a new Lead per bill.
            deal = canonical_deal(link['deal_id'], aid)
        if not deal: problems['Invoice has no verified acquisition Deal'] += 1
        g = group(deal or {});currency = invoice.get('currency_code');value = invoice.get('total')
        amount(g['invoice_value'], currency, value)
        if invoice.get('status') == 'paid' and money(invoice.get('balance')) == Decimal('0'):
            amount(g['paid_invoice_value'], currency, value)
        if pid: amount(g['recurring_invoice_value'], currency, value)
        event('invoice_observed', iid)
        if aid in accounts:
            life = lifetime.setdefault(aid, {'account_id': aid, 'observed_invoice_value': {}, 'acquisition_sources': set()})
            amount(life['observed_invoice_value'], currency, value);life['acquisition_sources'].add(g['source'])
    for row in lifetime.values():row['acquisition_sources'] = sorted(row['acquisition_sources'])
    return {'schema': 1, 'scope': 'live', 'read_only': True, 'observed_at': snapshot.get('observed_at'),
            'groups': sorted(groups.values(), key=lambda r: (r['source'], r['campaign'])),
            'problems': dict(sorted(problems.items())), 'excluded': {k: len(v) for k,v in excluded.items()},
            'outcomes': sorted(outcomes.values(), key=lambda r: r['key']), 'customer_value': list(lifetime.values()),
            'external_conversion_upload': False, 'advertising_mutations': False, 'financial_writes': False,
            'value_policy': 'Gross non-draft/non-void Invoice value by native currency; paid Invoice value is not cash receipts or recognized revenue',
            'spend_state': 'UNAVAILABLE — no verified spend rows; ROAS not calculated'}


def render_marketing(view):
    h = lambda v: escape(str(v), quote=True)
    cols = ['source','medium','campaign','leads','qualified_leads','deals','estimates','accepted_estimates',
            'invoice_value','paid_invoice_value','recurring_invoice_value']
    names = ['Marketing source','Medium','Campaign','Leads','Qualified Leads','Deals','Estimates','Accepted Estimates',
             'Invoiced value','Paid Invoice value','Recurring invoiced value']
    def display(value):
        return ', '.join(currency+' '+amount for currency,amount in sorted(value.items())) if isinstance(value,dict) else value
    rows = ''.join('<tr>'+''.join('<td>'+h(display(r[k]))+'</td>' for k in cols)+'</tr>' for r in view['groups'])
    gaps = ''.join('<li>'+h(k)+': '+h(n)+'</li>' for k,n in view['problems'].items())
    return ("<!doctype html><html lang='en'><meta charset='utf-8'><title>Marketing Sources</title>"
            "<style>body{font:16px system-ui;margin:2rem}td,th{padding:.5rem;text-align:left;border-bottom:1px solid #ddd}table{width:100%}</style>"
            "<a href='/v1/operator/today'>Today</a><h1>Marketing Sources</h1><p>Read-only · TEST activity excluded</p>"
            '<p>'+h(view['value_policy'])+'</p><p>'+h(view['spend_state'])+'</p><p>Observed '+h(view['observed_at'])+' · collection '+h(view.get('collection',{}).get('state','UNKNOWN'))+'</p>'
            '<table><tr>'+''.join('<th>'+h(n)+'</th>' for n in names)+'</tr>'+rows+'</table>'
            '<h2>Attribution problems</h2><ul>'+gaps+'</ul><p>Missing source remains UNATTRIBUTED. Conversion uploads are OFF.</p></html>')
