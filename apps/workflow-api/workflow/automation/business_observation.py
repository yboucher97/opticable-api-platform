"""Bounded native GET collector. This adapter has no mutation method."""
from datetime import datetime, timezone
from copy import deepcopy
from contextlib import contextmanager
from .service_inventory import SERVICE_FIELDS, LOCATION_FIELDS
from .recurring_lifecycle import identity, index, money

ORG = '802337532'


class ReadBudgetExceeded(ValueError):
    """No provider request was made for this rejected attempt."""


def same_version(summary, detail, id_field):
    """Exact native ID/version/customer evidence, shared by all detail reuse."""
    try:
        modified = datetime.fromisoformat(str(summary.get('last_modified_time')).replace('Z', '+00:00'))
    except (ValueError, TypeError):
        return False
    return bool(modified.tzinfo and identity(summary.get(id_field)) and
                identity(summary.get(id_field)) == identity(detail.get(id_field)) and
                summary.get('last_modified_time') == detail.get('last_modified_time') and
                (id_field == 'contact_id' or identity(summary.get('customer_id')) and
                 identity(summary.get('customer_id')) == identity(detail.get('customer_id'))))


def detail_shape(row, id_field):
    return {'contact_id':{'zcrm_account_id'},'recurring_invoice_id':{'sub_total'},
            'invoice_id':{'estimate_id','zcrm_potential_id'},'estimate_id':{'invoice_ids','zcrm_potential_id'}}[id_field] <= row.keys()


class NativeReader:
    def __init__(self, client, *, limit=140, previous=None, now=None):
        if type(limit) is not int or not 0 <= limit <= 160:raise ValueError('Bounded native read limit required')
        self.client = client;self.reads = 0;self.limit = limit
        self.at = (now or datetime.now(timezone.utc)).isoformat()
        self.attempted = self.successful = self.failed = 0
        self.stage_limit = limit;self.stages = {};self.modules = {}
        self.inventory = {};self.last_good = deepcopy((previous or {}).get('last_good_modules', {}))
        self.details = deepcopy((previous or {}).get('detail_checkpoint', {}))
        self.previous = (previous or {}).get('snapshot', {})
        source = self.previous.get('observed_at') or (previous or {}).get('observed_at')
        if not (previous or {}).get('collection'):
            for name in ('accounts','services','sites','finance_invoices','cases','installations',
                         'leads','contacts','deals','finance_estimates','customers','books_invoices'):
                if name in self.previous:self.last_good.setdefault(name, {'data':deepcopy(self.previous[name]),'source_at':source})
            if 'books_estimate_index' in self.previous:
                self.last_good.setdefault('books_estimate_index', {'data':list(self.previous['books_estimate_index'].values()),'source_at':source})
            if all(k in self.previous for k in ('profiles','customers','generated')):
                self.last_good.setdefault('recurring_details', {'data':{k:deepcopy(self.previous.get(k,[] if k!='generated' else {})) for k in ('profiles','customers','generated','profile_exceptions')},'source_at':source})
        # Upgrade schema3 caches without inferring that missing modules were read.
        for field, kind, id_field in [('profiles','recurringinvoices','recurring_invoice_id'),
                                     ('customers','contacts','contact_id'),('books_invoices','invoices','invoice_id')]:
            rows = list(self.previous.get(field, []))
            if kind == 'invoices':rows += [r for values in self.previous.get('generated', {}).values() for r in values]
            for row in rows:
                rid = identity(row.get(id_field))
                if rid and detail_shape(row,id_field):self.details.setdefault('/books/v3/'+kind+'/'+rid, {'data':deepcopy(row),'source_at':source})
        for rid,row in self.previous.get('books_estimate_index', {}).items():
            if detail_shape(row,'estimate_id'):self.details.setdefault('/books/v3/estimates/'+rid, {'data':deepcopy(row),'source_at':source})

    @property
    def remaining(self):return max(0, min(self.limit, self.stage_limit)-self.reads)

    def retain_inventory(self, kind, rows, id_field):
        """Retire cache entries only after a complete native inventory succeeds."""
        prefix='/books/v3/'+kind+'/'
        ids={identity(r.get(id_field)) for r in rows}
        self.details={p:v for p,v in self.details.items() if not p.startswith(prefix) or p[len(prefix):] in ids}

    def counts(self):return self.attempted, self.successful, self.failed, self.reads

    def metadata(self, before):
        return dict(zip(('attempted_reads','successful_reads','failed_reads','provider_reads'),
                        (a-b for a,b in zip(self.counts(), before))))

    @contextmanager
    def stage(self, name, budget):
        before = self.counts();prior_limit = self.stage_limit
        self.stage_limit = min(self.limit, self.reads+budget)
        status = dict(state='NOT_STARTED', completeness='NOT_COLLECTED_UNKNOWN', source_at=None,
                      observed_at=self.at, budget=budget)
        self.stages[name] = status;first = set(self.modules)
        try:
            yield status
        except (ValueError, KeyError, TypeError) as exc:
            status.update(state='SKIPPED_BUDGET' if isinstance(exc,ReadBudgetExceeded) else 'FAILED',
                          completeness='PARTIAL', error_type=type(exc).__name__)
        else:
            modules = [v for k,v in self.modules.items() if k not in first]
            complete = all(v['state']=='COMPLETE' for v in modules)
            status.update(state='COMPLETE' if complete else 'PARTIAL', completeness='COMPLETE' if complete else 'PARTIAL',
                          source_at=min((v['source_at'] for v in modules if v.get('source_at')), default=None) if complete else None)
            errors = [v for v in modules if v.get('error_type')]
            if errors:status['errors'] = [{k:v[k] for k in ('error_type','error_code') if k in v} for v in errors]
        finally:
            status.update(self.metadata(before));self.stage_limit = prior_limit

    def module(self, name, read):
        """Keep the last complete module separately from each current attempt."""
        before = self.counts();old = self.last_good.get(name, {})
        status = dict(state='NOT_STARTED', completeness='NOT_COLLECTED_UNKNOWN', source_at=None, observed_at=self.at)
        try:
            data = read()
        except (ValueError, KeyError, TypeError) as exc:
            state = 'SKIPPED_BUDGET' if isinstance(exc, ReadBudgetExceeded) else 'FAILED'
            status.update(state='STALE_REUSED' if 'data' in old else state,
                          attempt_state=state, completeness='STALE' if 'data' in old else 'PARTIAL' if self.reads>before[3] else 'FAILED',
                          source_at=old.get('source_at'), error_type=type(exc).__name__)
            if getattr(exc,'code',None) is not None:status['error_code']=exc.code
            data = deepcopy(old.get('data'))
        else:
            status.update(state='COMPLETE', completeness='COMPLETE_WITH_RECORDS' if data else 'COMPLETE_VERIFIED_EMPTY', source_at=self.at)
            self.last_good[name] = {'data':deepcopy(data),'source_at':self.at}
        status.update(self.metadata(before));self.modules[name] = status
        return data

    def get(self, path, query=None):
        if not (path.startswith('/crm/v8/') or path.startswith('/books/v3/')):
            raise ValueError('Only canonical native read paths supported')
        self.attempted += 1
        if not self.remaining: raise ReadBudgetExceeded('Observation read bound exceeded')
        self.reads += 1
        q = dict(query or {})
        if path.startswith('/books/'): q['organization_id'] = ORG
        try: result = self.client.request('zohoapis', 'GET', path, query=q)
        except Exception:
            self.failed += 1
            raise ValueError('Native read unavailable; no provider retry or effect') from None
        if not isinstance(result,dict):
            self.failed += 1
            raise ValueError('Malformed native response')
        if result.get('ok') is not True or result.get('status') not in {200, 204}:
            self.failed += 1
            error = ValueError('Native observation unavailable')
            if type(result.get('status')) is int:error.code=result['status']
            raise error
        if result['status'] == 204:
            self.successful += 1
            return {'data': [], 'info': {'more_records': False}}
        value = result.get('data')
        if not isinstance(value, dict) or path.startswith('/books/') and value.get('code') != 0:
            self.failed += 1
            raise ValueError('Malformed native observation')
        self.successful += 1
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
            if more is not True:
                if any(not isinstance(row,dict) for row in rows):raise ValueError('Malformed native collection row')
                id_fields={'data':'id','recurring_invoices':'recurring_invoice_id','invoice_history':'invoice_id',
                           'estimates':'estimate_id','invoices':'invoice_id','contacts':'contact_id',
                           'customerpayments':'payment_id','expenses':'expense_id'}
                if key in id_fields:index(rows,id_fields[key])
                return rows
        raise ValueError('Observation pagination incomplete')

    def crm(self, module, fields):
        rows = self.listing('/crm/v8/'+module, 'data', fields=fields);index(rows);return rows

    def record(self, path, key, id_key, expected, *, summary=None):
        prior = self.details.get(path, {})
        if summary is not None and same_version(summary, prior.get('data', {}), id_key):
            return {**deepcopy(prior['data']),**deepcopy(summary)}
        if path not in self.details and len(self.details)>=4000:raise ValueError('Detail checkpoint capacity exceeded')
        value = self.get(path).get(key)
        if not isinstance(value, dict) or identity(value.get(id_key)) != expected:
            raise ValueError('Native financial identity differs')
        self.details[path] = {'data':deepcopy(value), 'source_at':self.at}
        return value


def collect_recurring(reader, snapshot=None):
    strict = snapshot is None
    snapshot = snapshot if snapshot is not None else {'observed_at':reader.at}
    for name, module, fields in [
        ('accounts', 'Accounts', 'id,Account_Name,Account_Type,Website,OptiBrain_Test'),
        ('services', 'Services', SERVICE_FIELDS), ('sites', 'Service_Locations', LOCATION_FIELDS),
        ('finance_invoices', 'CustomModule5001', 'id,Invoice_ID,Account_Name,Potential_Name'),
        ('cases', 'Cases', 'id,Status,Account_Name,Related_To,Contact_Name,Deal_Name,OptiBrain_Test'),
        ('installations', 'Installations', 'id,Name,Installation_Status,Linked_Service,Installation_Date_Time,OptiBrain_Test')]:
        data = reader.module(name, lambda module=module,fields=fields:reader.crm(module,fields))
        if data is not None:snapshot[name] = data
    summaries = reader.module('profile_index', lambda:reader.listing('/books/v3/recurringinvoices', 'recurring_invoices'))
    if reader.modules['profile_index']['state']=='COMPLETE':reader.retain_inventory('recurringinvoices',summaries,'recurring_invoice_id')

    def details():
        if reader.modules['profile_index']['state'] != 'COMPLETE':raise ValueError('Current recurring inventory unavailable')
        profiles = index(summaries, 'recurring_invoice_id')
        result = {'profiles':[], 'customers':[], 'generated':{}, 'profile_exceptions':[]}
        customers = {};invoice_cache = {};invoice_profiles = {}
        for pid,summary in profiles.items():
            profile = reader.record('/books/v3/recurringinvoices/'+pid, 'recurring_invoice', 'recurring_invoice_id', pid, summary=summary)
            result['profiles'].append(profile);cid = identity(profile.get('customer_id'))
            if not cid:raise ValueError('Recurring customer identity missing')
            if cid not in customers:
                customers[cid] = reader.record('/books/v3/contacts/'+cid, 'contact', 'contact_id', cid,
                    summary=reader.inventory.get('customers', {}).get(cid))
            # Always read generated history. An unchanged profile cannot certify it.
            rows = reader.listing('/books/v3/recurringinvoices/'+pid+'/invoices', 'invoice_history')
            result['generated'][pid] = []
            for entry in rows:
                iid = identity(entry.get('invoice_id'))
                if not iid:raise ValueError('Native generated Invoice identity missing')
                if iid in invoice_profiles and invoice_profiles[iid] != pid:raise ValueError('Invoice appears under multiple recurring profiles')
                invoice_profiles[iid] = pid
                if iid not in invoice_cache:
                    invoice_cache[iid] = reader.record('/books/v3/invoices/'+iid, 'invoice', 'invoice_id', iid,
                        summary=reader.inventory.get('invoices', {}).get(iid) or entry)
                invoice = dict(invoice_cache[iid])
                if invoice.get('recurring_invoice_id') and identity(invoice['recurring_invoice_id']) != pid:
                    raise ValueError('Native generated Invoice profile mismatch')
                if identity(invoice.get('customer_id')) != cid:
                    modified = datetime.fromisoformat(profile['last_modified_time']).date()
                    historical = invoice.get('status') == 'paid' and money(invoice.get('balance')) == 0 and datetime.fromisoformat(invoice['date']).date() < modified
                    if not historical:raise ValueError('Unreconciled current Invoice customer mismatch')
                    result['profile_exceptions'].append({'profile_id':pid,'invoice_id':iid,
                        'kind':'HISTORICAL_CUSTOMER_DISCONTINUITY','severity':'P2',
                        'reason':'Paid historical invoice customer differs from current profile; owner review required',
                        'automatic_association':False})
                    continue
                invoice['recurring_invoice_id'] = pid;invoice['_native_generated_history'] = True
                result['generated'][pid].append(invoice)
        result['customers'] = list(customers.values())
        return result

    result = reader.module('recurring_details', details)
    if result is not None:
        # Marketing's complete customer inventory must not be narrowed to recurring customers.
        customers = index(snapshot.get('customers', []), 'contact_id')
        if reader.modules['recurring_details']['state']=='COMPLETE':
            customers.update(index(result['customers'], 'contact_id'))
        elif reader.modules.get('customers',{}).get('state')!='COMPLETE':
            for cid,row in index(result['customers'], 'contact_id').items():customers.setdefault(cid,row)
        snapshot.update({k:v for k,v in result.items() if k!='customers'})
        snapshot['customers'] = list(customers.values())
    snapshot['provider_reads'] = reader.reads
    if strict and any(v['state']!='COMPLETE' for v in reader.modules.values()):
        raise ValueError('Recurring observation incomplete; checkpoint retained')
    return snapshot


def collect_marketing(reader, snapshot, *, incremental=False):
    from .lifecycle_control import ATTR_FIELDS
    fields = ','.join(sorted(ATTR_FIELDS | {'id','OptiBrain_Test','Lead_Source','Created_Time',
        'Google_GCLID','Google_GBRAID','Google_WBRAID','Meta_FBCLID'}))
    for name,module,extra,query in [
        ('leads','Leads',',Lead_Status,$converted,$converted_detail',{'converted':'both'}),
        ('contacts','Contacts',',Account_Name',None),
        ('deals','Deals',',Account_Name,Contact_Name,Stage,Deal_Name,Amount,Currency,Closing_Date,Modified_Time,Service_Location,Next_Step',None),
        ('finance_estimates','CustomModule5002',None,None)]:
        f = 'id,Estimate_ID,Account_Name,Potential_Name' if name=='finance_estimates' else fields+extra
        data = reader.module(name, lambda module=module,f=f,query=query:reader.listing('/crm/v8/'+module,'data',fields=f,query=query))
        if data is not None:snapshot[name] = data
    for name,path,key,id_field in [('books_estimate_index','estimates','estimates','estimate_id'),
                                   ('books_invoices','invoices','invoices','invoice_id'),
                                   ('customer_index','contacts','contacts','contact_id')]:
        data = reader.module(name, lambda path=path,key=key:reader.listing('/books/v3/'+path,key))
        if data is not None:
            indexed = index(data,id_field)
            if reader.modules[name]['state']=='COMPLETE':reader.retain_inventory(path,data,id_field)
            if name=='customer_index':
                if reader.modules[name]['state']=='COMPLETE':reader.inventory['customers'] = indexed
            elif name=='books_invoices':
                if reader.modules[name]['state']=='COMPLETE':reader.inventory['invoices'] = indexed
                snapshot[name] = [{**reader.details.get('/books/v3/invoices/'+rid, {}).get('data', {}),**row}
                    if same_version(row,reader.details.get('/books/v3/invoices/'+rid, {}).get('data',{}),'invoice_id') else row
                    for rid,row in indexed.items()]
            else:snapshot[name] = indexed

    def customers():
        if any(reader.modules[k]['state']!='COMPLETE' for k in ('books_estimate_index','books_invoices','customer_index')):
            raise ValueError('Current financial/customer inventory unavailable')
        ids = {identity(r.get('customer_id')) for r in [*snapshot['books_invoices'], *snapshot['books_estimate_index'].values()]}
        # Include native customers without transactions. A financial subset
        # cannot prove absence of an existing customer relationship.
        ids |= {cid for cid,row in reader.inventory['customers'].items() if row.get('contact_type')!='vendor'}
        if '' in ids:raise ValueError('Financial customer ID missing')
        if not ids <= reader.inventory['customers'].keys():raise ValueError('Financial customer missing from native inventory')
        return [reader.record('/books/v3/contacts/'+cid,'contact','contact_id',cid,summary=reader.inventory['customers'][cid]) for cid in sorted(ids)]
    data = reader.module('customers', customers)
    if data is not None:snapshot['customers'] = data
    snapshot['provider_reads'] = reader.reads
    if not incremental and any(v['state']!='COMPLETE' for v in reader.modules.values()):raise ValueError('Marketing observation incomplete; checkpoint retained')
    return snapshot


def collect_business(reader, snapshot):
    """Optional complete bounded reads; unavailable data never becomes zero."""
    from copy import deepcopy
    result=deepcopy(snapshot);result['optional_reads']={}
    def organization():
        orgs=reader.get('/books/v3/organizations')['organizations']
        found=[r for r in orgs if identity(r.get('organization_id'))==ORG]
        if len(found)!=1:raise ValueError('Canonical Books organization unavailable')
        return found[0]['currency_code']
    result['base_currency']=reader.module('base_currency',organization)
    for name,path,key in [('payments','customerpayments','customerpayments'),('expenses','expenses','expenses')]:
        result[name]=reader.module(name,lambda path=path,key=key:reader.listing('/books/v3/'+path,key)) or []
        result['optional_reads'][name]='PROVEN' if reader.modules[name]['state']=='COMPLETE' else 'UNAVAILABLE'
    return result


def enrich_finance(reader, snapshot, *, previous=None, maximum=8):
    """Bounded incremental native detail reconciliation; cache exact versions only.

    List responses omit native parent IDs. Missing details remain pending,
    never guessed. Existing full generated Invoice observations are reused.
    """
    from copy import deepcopy
    if type(maximum) is not int or not 0<=maximum<=8:raise ValueError('Bounded finance detail limit required')
    result = deepcopy(snapshot); previous = previous or {}; pending = []; verified = 0
    prior_estimates = previous.get('books_estimate_index', {})
    prior_invoices = {identity(v.get('invoice_id')):v for v in previous.get('books_invoices', [])}
    for kind, rows, old, id_field in [
        ('estimates', list(result.get('books_estimate_index', {}).values()), prior_estimates, 'estimate_id'),
        ('invoices', result.get('books_invoices', []), prior_invoices, 'invoice_id')]:
        for row in rows:
            rid=identity(row.get(id_field));prior=reader.details.get('/books/v3/'+kind+'/'+rid,{}).get('data') or old.get(rid, {})
            detail_keys = {'zcrm_potential_id', 'invoice_ids'} if kind=='estimates' else {'zcrm_potential_id','estimate_id'}
            if not detail_keys <= row.keys() and detail_keys <= prior.keys():
                if same_version(row, prior, id_field):
                    row.update({**prior, **row})
            if detail_keys <= row.keys(): verified+=1;continue
            pending.append((kind,rid,row))
    pending.sort(key=lambda v: str(v[2].get('last_modified_time') or v[2].get('date') or ''),reverse=True)
    completed=0
    for kind,rid,row in pending[:min(maximum, reader.remaining)]:
        key='estimate' if kind=='estimates' else 'invoice'
        actual=reader.record('/books/v3/'+kind+'/'+rid,key,key+'_id',rid)
        if identity(actual.get('customer_id'))!=identity(row.get('customer_id')):
            raise ValueError('Finance customer changed; reconcile before publishing')
        row.clear();row.update(actual);completed+=1
    result['books_estimate_index']={identity(r['estimate_id']):r for r in list(result.get('books_estimate_index',{}).values())}
    result['finance_detail_coverage']={'verified':verified+completed,'pending':len(pending)-completed,
        'delta_reads':completed,'maximum_per_cycle':maximum,'native_only':True}
    return result
