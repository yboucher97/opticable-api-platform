"""Bounded zero-credit Apollo reads. No outreach or enrichment transport."""
from datetime import datetime, timezone
from time import monotonic
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

    def workspace(self):
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
        accounts = self.read('accounts', page=1, per_page=100)
        sequences = self.read('sequences', page=1, per_page=100)
        for data in (accounts, sequences):
            if data['pagination']['total_pages'] > 1:
                raise ValueError('Apollo account/sequence population exceeds bounded inventory')
        messages = self.read('messages', page=1, per_page=100)['emailer_messages']
        replies = self.read('messages', page=1, per_page=100,
                            **{'emailer_message_stats[]': 'replied'})['emailer_messages']
        return {'schema': 1, 'at': datetime.now(timezone.utc).isoformat(),
                'contacts_complete': True, 'contacts': contacts,
                'accounts': accounts['accounts'], 'sequences': sequences['emailer_campaigns'],
                'messages': messages, 'replies': replies, 'stages': self.read('stages')['contact_stages'],
                'labels': self.read('labels'), 'provider_mutations': 0, 'credit_consuming_calls': 0}

    def close(self):
        self.http.close()
