"""Exact native/owner-evidenced reporting links. Never financial mutations."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from .recurring_lifecycle import identity, bind_profile, synthetic
from .marketing_attribution import acquisition


def receipt_key(kind, record_id):
    if kind not in {'estimates', 'invoices', 'profiles'} or not identity(record_id):
        raise ValueError('Canonical finance identity required')
    return kind + ':' + record_id


def validate_confirmation(receipt, rows, *, now=None):
    """Revalidate each owner choice against current native parents, every read."""
    required = {'kind', 'record_id', 'customer_id', 'account_id', 'reviewed_by', 'reviewed_at', 'proof'}
    if not required <= receipt.keys() or not receipt['reviewed_by'] or not receipt['proof']:
        raise ValueError('Explicit owner confirmation evidence required')
    at = datetime.fromisoformat(receipt['reviewed_at'].replace('Z', '+00:00'))
    if at.tzinfo is None or at > (now or datetime.now(timezone.utc)):
        raise ValueError('Invalid owner confirmation time')
    kind = receipt['kind']; rid = identity(receipt['record_id'])
    receipt_key(kind, rid)
    row = rows[kind].get(rid)
    if not row or synthetic(row): raise ValueError('Native non-test finance record required')
    cid = identity(row.get('customer_id')); customer = rows['customers'].get(cid, {})
    aid = identity(customer.get('zcrm_account_id'))
    if not aid or (cid, aid) != (receipt['customer_id'], receipt['account_id']):
        raise ValueError('Owner evidence disagrees with native financial customer')
    did = identity(receipt.get('deal_id'))
    if kind != 'profiles' and not did: raise ValueError('Choose a native Deal')
    if did and identity(rows['deals'].get(did, {}).get('Account_Name')) != aid:
        raise ValueError('Owner Deal belongs to another Account or is absent')
    site = identity(receipt.get('site_id'))
    if site and identity(rows['sites'].get(site, {}).get('Linked_Account')) != aid:
        raise ValueError('Owner Site belongs to another Account or is absent')
    if did and site and identity(rows['deals'][did].get('Service_Location')) not in {'', site}:
        raise ValueError('Owner Site conflicts with native Deal')
    if kind == 'profiles':
        sid = identity(receipt.get('service_id'))
        service = rows['services'].get(sid, {})
        if not sid or not site or identity(service.get('Linked_Service_Location')) != site:
            raise ValueError('Choose an existing native Service and its exact Site')
    return dict(receipt)


def recurring_reviews(rows):
    result = dict(rows.get('_recurring_reviews', {}))
    for key, receipt in rows.get('_finance_reviews', {}).items():
        if receipt.get('kind') != 'profiles': continue
        confirmed = validate_confirmation(receipt, rows)
        if key != receipt_key('profiles', confirmed['record_id']):
            raise ValueError('Confirmation key disagrees with record')
        result[confirmed['record_id']] = {
            **confirmed, 'profile_id': confirmed['record_id']}
    return result


def resolve_finance(row, kind, rows):
    """Names, dates, amounts and unique-customer candidates never prove a Deal."""
    if kind not in {'estimates', 'invoices'}: raise ValueError('Unsupported transaction')
    key = 'invoice_id' if kind == 'invoices' else 'estimate_id'
    field = 'Invoice_ID' if kind == 'invoices' else 'Estimate_ID'
    rid = identity(row.get(key)); cid = identity(row.get('customer_id'))
    customer = rows['customers'].get(cid, {})
    aid = identity(customer.get('zcrm_account_id')); deals = set(); proof = []
    conflict = False; classification = 'UNLINKED'
    if aid: proof.append('Books customer_id → contact_id → zcrm_account_id')
    direct = identity(row.get('zcrm_potential_id'))
    if direct: deals.add(direct); proof.append('Books native zcrm_potential_id'); classification = 'NATIVE PROVEN'
    native = [r for r in rows['finance_' + kind].values() if identity(r.get(field)) == rid]
    if len(native) > 1: conflict = True
    for finance in native:
        account = identity(finance.get('Account_Name')); deal = identity(finance.get('Potential_Name'))
        if account and account != aid: conflict = True
        if deal: deals.add(deal); proof.append('CRM Finance native Books ID / Potential_Name'); classification = 'NATIVE PROVEN'
    if kind == 'invoices':
        # Forward native parent and reverse Estimate invoice_ids are independent
        # native identities; verify every customer and parent before derivation.
        parents = set()
        parent_id = identity(row.get('estimate_id'))
        if parent_id: parents.add(parent_id)
        for eid, estimate in rows['estimates'].items():
            references = estimate.get('invoice_ids') or []
            if isinstance(references, list) and rid in {
                identity(v.get('invoice_id')) if isinstance(v, dict) else identity(v) for v in references}:
                parents.add(eid)
        for eid in parents:
            parent = rows['estimates'].get(eid)
            if not parent or identity(parent.get('customer_id')) != cid:
                conflict = True; continue
            link = resolve_finance(parent, 'estimates', rows)
            if link['conflict']: conflict = True
            elif link['deal_id']:
                deals.add(link['deal_id']); proof.append('Native Invoice ↔ Estimate → verified Deal')
                if classification == 'UNLINKED': classification = 'DERIVED DETERMINISTICALLY'
        pid = identity(row.get('recurring_invoice_id')); profile = rows['profiles'].get(pid)
        if profile and identity(profile.get('customer_id')) == cid:
            relation = bind_profile(profile, customer, list(rows['services'].values()), rows['sites'],
                list(rows['finance_invoices'].values()),
                [r for r in rows['invoices'].values() if identity(r.get('recurring_invoice_id')) == pid],
                reviewed=recurring_reviews(rows).get(pid))
            if relation['decision'] == 'LINKED' and relation['deal_id']:
                deals.add(relation['deal_id']); proof.append('Verified recurring profile → Service original Deal')
                if classification == 'UNLINKED': classification = 'DERIVED DETERMINISTICALLY'
    review = rows.get('_finance_reviews', {}).get(receipt_key(kind, rid)) if rid else None
    if review:
        try:
            receipt = validate_confirmation(review, rows)
            deals.add(receipt['deal_id']); proof.append('Explicit owner confirmation: ' + receipt['reviewed_at'])
            if classification == 'UNLINKED': classification = 'OWNER CONFIRMED'
        except (ValueError, KeyError, TypeError): conflict = True
    if len(deals) > 1: conflict = True
    did = next(iter(deals)) if len(deals) == 1 else ''
    deal = rows['deals'].get(did)
    if did and (not aid or not deal or identity(deal.get('Account_Name')) != aid): conflict = True
    sites = set(); services = set()
    if deal and not conflict:
        if identity(deal.get('Service_Location')): sites.add(identity(deal['Service_Location']))
        for sid, service in rows['services'].items():
            if identity(service.get('Linked_Deal')) == did:
                services.add(sid); sites.add(identity(service.get('Linked_Service_Location')))
        # Existing acceptance state explicitly records durable Services reused
        # across Deals. Native Account/Site and accepted Estimate must still agree.
        owned = rows.get('_accepted_work', {}).get(did, {})
        eid = identity(owned.get('accepted_estimate_id'))
        estimate = rows['estimates'].get(eid)
        if owned.get('accepted') is True and estimate:
            parent = resolve_finance(estimate, 'estimates', {**rows, '_accepted_work': {}})
            if not parent['conflict'] and parent['deal_id'] == did and estimate.get('status') in {'accepted', 'invoiced'}:
                for sid in owned.get('service_ids', []):
                    if sid not in rows['services']: conflict = True; continue
                    services.add(sid); sites.add(identity(rows['services'][sid].get('Linked_Service_Location')))
                proof.append('Owned accepted-work Service IDs + current native parent validation')
        sites.discard('')
        if len(sites) > 1 or any(identity(rows['sites'].get(i, {}).get('Linked_Account')) != aid for i in sites): conflict = True
    touch = acquisition(deal or {})
    if conflict:
        aid = did = ''; sites = set(); services = set(); touch = acquisition({}); classification = 'AMBIGUOUS'
    return {'account_id': aid, 'deal_id': did, 'site_ids': sorted(sites), 'service_ids': sorted(services),
        'conflict': bool(conflict), 'proof': proof, 'classification': classification, 'acquisition': touch,
        'truth': 'UNKNOWN' if conflict else 'DERIVED DETERMINISTICALLY' if did else 'PARTIAL' if aid else 'UNKNOWN'}


def linkage_attention(snapshot, rows):
    """One compact rebuildable owner batch; candidates are choices, never proof."""
    output = []
    for kind, id_field in [('estimates', 'estimate_id'), ('invoices', 'invoice_id'), ('profiles', 'recurring_invoice_id')]:
        for rid, row in rows[kind].items():
            cid = identity(row.get('customer_id')); customer = rows['customers'].get(cid, {})
            aid = identity(customer.get('zcrm_account_id'))
            if kind == 'profiles':
                link = bind_profile(row, customer, list(rows['services'].values()), rows['sites'],
                    list(rows['finance_invoices'].values()), snapshot.get('generated', {}).get(rid, []),
                    reviewed=recurring_reviews(rows).get(rid))
                missing = link['decision'] != 'LINKED'
                reason = link.get('reason', '')
            else:
                link = resolve_finance(row, kind, rows); missing = not link['deal_id'] or link['conflict']
                reason = 'Conflicting native linkage' if link['conflict'] else 'No proven Deal; owner selects business context'
            if not missing: continue
            candidates = [i for i, deal in rows['deals'].items() if aid and identity(deal.get('Account_Name')) == aid]
            sites = [i for i, site in rows['sites'].items() if aid and identity(site.get('Linked_Account')) == aid]
            services = [i for i, service in rows['services'].items() if identity(service.get('Linked_Service_Location')) in sites]
            output.append({'key': sha256(('finance-linkage:v1:' + kind + ':' + rid).encode()).hexdigest(),
                'kind': kind, 'record_id': rid, 'account_id': aid, 'customer_id': cid,
                'number': row.get('estimate_number') or row.get('invoice_number') or row.get('recurrence_name'),
                'date': row.get('date') or row.get('start_date'), 'amount': row.get('total'), 'currency': row.get('currency_code'),
                'reason': reason, 'candidate_deals': candidates, 'candidate_sites': sites, 'candidate_services': services,
                'automatic_guess': False, 'provider_task_created': False})
    return output
