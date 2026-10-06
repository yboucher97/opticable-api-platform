"""Bounded zero-credit Apollo reads. No outreach or enrichment transport."""
from datetime import datetime, timezone
from time import monotonic
from copy import deepcopy
import httpx


READS = {
    'contacts': ('POST', '/contacts/search', {'page', 'per_page', 'sort_by_field', 'sort_ascending'}),
    'accounts': ('POST', '/accounts/search', {'page', 'per_page'}),
    'sequences': ('POST', '/emailer_campaigns/search', {'page', 'per_page'}),
    'messages': ('GET', '/emailer_messages/search', {'page', 'per_page', 'emailer_message_stats[]'}),
    'labels': ('GET', '/labels', set()),
    'stages': ('GET', '/contact_stages', set()),
    'mailboxes': ('GET', '/email_accounts', set()),
    'people_research': ('POST', '/mixed_people/api_search', {'q_organization_domains_list','person_titles','page','per_page'}),
}


class ApolloReader:
    """Fixed documented read/search endpoints only, including read-only POSTs."""
    def __init__(self, settings, *, transport=None, limit=32):
        if not settings.api_key:
            raise ValueError('Apollo credential unavailable')
        self.http = httpx.Client(base_url='https://api.apollo.io/api/v1',
            headers={'x-api-key': settings.api_key, 'Accept': 'application/json'},
            timeout=httpx.Timeout(5, connect=3), follow_redirects=False, transport=transport)
        self.calls = 0
        self.limit = min(limit, 32)
        self.started = monotonic()

    def read(self, kind, **params):
        if kind not in READS or not set(params) <= READS[kind][2]:
            raise ValueError('Only fixed Apollo observation requests are supported')
        if kind == 'people_research':
            from .sales_intelligence import domain
            hosts=params.get('q_organization_domains_list')
            if not isinstance(hosts,list) or len(hosts)!=1 or domain(hosts[0])!=hosts[0] or params.get('page',1)!=1 or params.get('per_page',5)>5:
                raise ValueError('Research requires one resolved domain and at most five people')
            titles=params.get('person_titles',[])
            if not isinstance(titles,list) or len(titles)>12 or any(not isinstance(t,str) or len(t)>80 for t in titles):
                raise ValueError('Bounded business roles required')
        if not 1 <= params.get('page', 1) <= 20 or not 1 <= params.get('per_page', 100) <= 100:
            raise ValueError('Apollo pagination bound exceeded')
        if self.calls >= self.limit or monotonic()-self.started>40:
            raise ValueError('Apollo observation budget exceeded')
        method, path, _ = READS[kind]
        self.calls += 1
        try:
            response = self.http.request(method, path, params=params if method == 'GET' else None,
                                         json=params if method == 'POST' else None)
        except httpx.HTTPError:
            raise ValueError('Apollo observation unavailable; no effect attempted') from None
        if not response.is_success:
            raise ValueError('Apollo read unavailable: HTTP ' + str(response.status_code))
        if kind=='people_research' and len(response.content)>1048576:raise ValueError('Apollo research response exceeds byte bound')
        return response.json()

    def workspace(self, *, previous=None):
        """Complete saved identity inventory, bounded at 2,000; no partial clearance."""
        contacts = []
        total = None
        for page in range(1, 21):
            data = self.read('contacts', page=page, per_page=100,
                             sort_by_field='contact_updated_at', sort_ascending=False)
            pagination = data.get('pagination', {})
            count = pagination.get('total_entries')
            if type(count) is not int or count > 2000 or total is not None and count != total:
                raise ValueError('Apollo identity population incomplete or changed')
            total = count
            contacts.extend(data['contacts'])
            if page >= pagination['total_pages']:
                break
        if len({r['id'] for r in contacts}) != total or len(contacts) != total:
            raise ValueError('Apollo identity pagination incomplete')
        from .observation_completeness import complete
        at = datetime.now(timezone.utc).isoformat()
        result = {'schema':1,'at':at,'contacts_complete':True,'contacts':contacts,
                  'modules':{'contacts':complete(contacts,at)},'provider_mutations':0,'credit_consuming_calls':0}
        for name,kind,key,params in [('accounts','accounts','accounts',{'page':1,'per_page':100}),
                                     ('sequences','sequences','emailer_campaigns',{'page':1,'per_page':100}),
                                     ('messages','messages','emailer_messages',{'page':1,'per_page':100}),
                                     ('replies','messages','emailer_messages',{'page':1,'per_page':100,'emailer_message_stats[]':'replied'}),
                                     ('stages','stages','contact_stages',{})]:
            before = self.calls
            try:
                data = self.read(kind,**params);rows = data[key]
                if not isinstance(rows,list):raise ValueError('Apollo module malformed')
                result[name] = rows
                pagination = data.get('pagination',{})
                # A bounded activity sample cannot prove absence of sends/replies.
                proven = name=='stages' or (type(pagination.get('total_entries')) is int and
                    pagination['total_entries']==len(rows) and pagination.get('total_pages') in {0,1} and
                    len({str(r['id']) for r in rows})==len(rows))
                result['modules'][name] = complete(rows,at) if proven else {'state':'PARTIAL','completeness':'PARTIAL','source_at':at}
            except (ValueError,KeyError,TypeError):
                prior=(previous or {}).get(name)
                result[name] = deepcopy(prior) if isinstance(prior,list) else []
                source=(previous or {}).get('modules',{}).get(name,{}).get('source_at') or (previous or {}).get('at')
                result['modules'][name] = {'state':'STALE_REUSED' if isinstance(prior,list) else 'FAILED',
                    'completeness':'FAILED','source_at':source if isinstance(prior,list) else None,'error_type':'ReadUnavailable'}
            result['modules'][name]['attempted_reads'] = self.calls-before
        memberships = [c.get('contact_campaign_statuses') for c in contacts]
        ownership = all(isinstance(m,list) and all(r.get('status') in {'active','scheduled','paused','finished','completed','failed','stopped'} for r in m) for m in memberships)
        stage_ids={r['id'] for r in result['stages']}
        suppression = all(all(k in c for k in ('email_unsubscribed','person_deleted','email_status','contact_stage_id')) and
            type(c['email_unsubscribed']) is bool and type(c['person_deleted']) is bool and
            (c['contact_stage_id'] is None or c['contact_stage_id'] in stage_ids) for c in contacts)
        result['ownership'] = [r for m in memberships if isinstance(m,list) for r in m]
        result['suppression'] = [{'id':c['id']} for c in contacts]
        for name,proven in [('ownership',ownership),('suppression',suppression)]:
            result['modules'][name] = complete(result[name],at) if proven else {'state':'PARTIAL','completeness':'PARTIAL','source_at':at}
        return result

    def close(self):
        self.http.close()
