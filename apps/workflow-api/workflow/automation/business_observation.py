"""Bounded native GET collector. This adapter has no mutation method."""
from datetime import datetime, timezone
from .service_inventory import SERVICE_FIELDS, LOCATION_FIELDS
from .recurring_lifecycle import identity, index, money

ORG = '802337532'


class NativeReader:
    def __init__(self, client, *, limit=140):
        self.client = client;self.reads = 0;self.limit = limit

    def get(self, path, query=None):
        if not (path.startswith('/crm/v8/') or path.startswith('/books/v3/')):
            raise ValueError('Only canonical native read paths supported')
        self.reads += 1
        if self.reads > self.limit: raise ValueError('Observation read bound exceeded')
        q = dict(query or {})
        if path.startswith('/books/'): q['organization_id'] = ORG
        try: result = self.client.request('zohoapis', 'GET', path, query=q)
        except Exception as exc: raise ValueError('Native read unavailable; no provider retry or effect') from exc
        if result.get('ok') is not True or result.get('status') not in {200, 204}:
            raise ValueError('Native observation unavailable')
        if result['status'] == 204: return {'data': [], 'info': {'more_records': False}}
        value = result.get('data')
        if not isinstance(value, dict) or path.startswith('/books/') and value.get('code') != 0:
            raise ValueError('Malformed native observation')
        return value

    def listing(self, path, key, *, fields=None, query=None):
        rows = []
        for page in range(1, 6):
            q = {**(query or {}), 'per_page': 200, 'page': page}
            if fields:q['fields'] = fields
            value = self.get(path, q)
            current = value.get(key)
            if not isinstance(current, list): raise ValueError('Native collection missing')
            rows.extend(current)
            more = value.get('info', {}).get('more_records') if path.startswith('/crm/') else value.get('page_context', {}).get('has_more_page')
            if not isinstance(more, bool): raise ValueError('Native pagination evidence missing')
            if more is not True: return rows
        raise ValueError('Observation pagination incomplete')

    def crm(self, module, fields):
        rows = self.listing('/crm/v8/'+module, 'data', fields=fields);index(rows);return rows

    def record(self, path, key, id_key, expected):
        value = self.get(path).get(key)
        if not isinstance(value, dict) or identity(value.get(id_key)) != expected:
            raise ValueError('Native financial identity differs')
        return value


def collect_recurring(reader):
    snapshot = {'observed_at': datetime.now(timezone.utc).isoformat()}
    for name, module, fields in [
        ('accounts', 'Accounts', 'id,Account_Name,OptiBrain_Test'),
        ('services', 'Services', SERVICE_FIELDS), ('sites', 'Service_Locations', LOCATION_FIELDS),
        ('finance_invoices', 'CustomModule5001', 'id,Invoice_ID,Account_Name,Potential_Name'),
        ('cases', 'Cases', 'id,Status,Account_Name,Related_To,Contact_Name,Deal_Name,OptiBrain_Test'),
        ('installations', 'Installations', 'id,Name,Installation_Status,Linked_Service,Installation_Date_Time,OptiBrain_Test')]:
        snapshot[name] = reader.crm(module, fields)
    summaries = reader.listing('/books/v3/recurringinvoices', 'recurring_invoices')
    profiles = index(summaries, 'recurring_invoice_id');snapshot['profiles'] = [];snapshot['customers'] = [];snapshot['generated'] = {}
    customers = {};invoice_cache = {};invoice_profiles = {};snapshot['profile_exceptions'] = []
    for pid in profiles:
        profile = reader.record('/books/v3/recurringinvoices/'+pid, 'recurring_invoice', 'recurring_invoice_id', pid)
        snapshot['profiles'].append(profile);cid = identity(profile.get('customer_id'))
        if not cid: raise ValueError('Recurring customer identity missing')
        if cid not in customers:customers[cid] = reader.record('/books/v3/contacts/'+cid, 'contact', 'contact_id', cid)
        rows = reader.listing('/books/v3/recurringinvoices/'+pid+'/invoices', 'invoice_history')
        snapshot['generated'][pid] = []
        for entry in rows:
            iid = identity(entry.get('invoice_id'))
            if not iid: raise ValueError('Native generated Invoice identity missing')
            if iid in invoice_profiles and invoice_profiles[iid] != pid: raise ValueError('Invoice appears under multiple recurring profiles')
            invoice_profiles[iid] = pid
            if iid not in invoice_cache:invoice_cache[iid] = reader.record('/books/v3/invoices/'+iid, 'invoice', 'invoice_id', iid)
            invoice = dict(invoice_cache[iid])
            if invoice.get('recurring_invoice_id') and identity(invoice['recurring_invoice_id']) != pid:
                raise ValueError('Native generated Invoice profile mismatch')
            if identity(invoice.get('customer_id')) != cid:
                # A current recurring profile can have older invoices for a
                # different customer. Never transfer historical revenue or
                # balances to the current customer. Only paid invoices older
                # than profile modification may be quarantined for review.
                modified = datetime.fromisoformat(profile['last_modified_time']).date()
                historical = invoice.get('status') == 'paid' and money(invoice.get('balance')) == 0 and datetime.fromisoformat(invoice['date']).date() < modified
                if not historical: raise ValueError('Unreconciled current Invoice customer mismatch')
                snapshot['profile_exceptions'].append({'profile_id': pid, 'invoice_id': iid,
                    'kind': 'HISTORICAL_CUSTOMER_DISCONTINUITY', 'severity': 'P2',
                    'reason': 'Paid historical invoice customer differs from current profile; owner review required',
                    'automatic_association': False})
                continue
            invoice['recurring_invoice_id'] = pid
            invoice['_native_generated_history'] = True
            snapshot['generated'][pid].append(invoice)
    snapshot['customers'] = list(customers.values());snapshot['provider_reads'] = reader.reads
    return snapshot


def collect_marketing(reader, recurring):
    from .lifecycle_control import ATTR_FIELDS
    from copy import deepcopy
    snapshot = deepcopy(recurring)
    fields = ','.join(sorted(ATTR_FIELDS | {'id','OptiBrain_Test','Lead_Source','Created_Time',
        'Google_GCLID','Google_GBRAID','Google_WBRAID','Meta_FBCLID'}))
    snapshot['leads'] = reader.listing('/crm/v8/Leads', 'data',
        fields=fields+',Lead_Status,$converted,$converted_detail', query={'converted':'both'})
    snapshot['contacts'] = reader.crm('Contacts', fields+',Account_Name')
    snapshot['deals'] = reader.crm('Deals', fields+',Account_Name,Contact_Name,Stage,Deal_Name,Amount,Currency,Closing_Date,Modified_Time,Service_Location,Next_Step')
    snapshot['finance_estimates'] = reader.crm('CustomModule5002', 'id,Estimate_ID,Account_Name,Potential_Name')
    books_estimates = reader.listing('/books/v3/estimates', 'estimates')
    snapshot['books_estimate_index'] = index(books_estimates, 'estimate_id')
    summaries = reader.listing('/books/v3/invoices', 'invoices')
    invoices = index(summaries, 'invoice_id')
    for pid, rows in recurring.get('generated', {}).items():
        for row in rows:
            iid = identity(row['invoice_id'])
            if iid in invoices:invoices[iid] = dict(row)
    snapshot['books_invoices'] = list(invoices.values())
    customers = index(snapshot['customers'], 'contact_id')
    ids = {identity(r.get('customer_id')) for r in [*invoices.values(), *books_estimates]}
    if '' in ids:raise ValueError('Financial customer ID missing')
    for cid in sorted(ids-customers.keys()):
        customers[cid] = reader.record('/books/v3/contacts/'+cid, 'contact', 'contact_id', cid)
    snapshot['customers'] = list(customers.values())
    snapshot['provider_reads'] = reader.reads
    return snapshot


def collect_business(reader, snapshot):
    """Optional complete bounded reads; unavailable data never becomes zero."""
    from copy import deepcopy
    result=deepcopy(snapshot);result['optional_reads']={}
    try:
        orgs=reader.get('/books/v3/organizations')['organizations']
        found=[r for r in orgs if identity(r.get('organization_id'))==ORG]
        if len(found)!=1:raise ValueError('Canonical Books organization unavailable')
        result['base_currency']=found[0]['currency_code']
    except (ValueError, KeyError, TypeError):result['base_currency']=None
    for name,path,key in [('payments','customerpayments','customerpayments'),('expenses','expenses','expenses')]:
        try:
            result[name]=reader.listing('/books/v3/'+path,key);result['optional_reads'][name]='PROVEN'
        except ValueError:result[name]=[];result['optional_reads'][name]='UNAVAILABLE'
    return result
