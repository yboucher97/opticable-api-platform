"""Bounded official structured sources; only public GET, no browser or enrichment."""
from datetime import datetime, timezone
from html.parser import HTMLParser
import hashlib
import json
import re
from time import monotonic
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
import httpx

from .acquisition_store import digest
from .sales_intelligence import stamp
from .trigger_evidence import latest_releases, tender_status

CKAN = 'https://www.donneesquebec.ca/recherche/api/3/action/'
SEAO_CATALOG = CKAN + 'package_show?id=systeme-electronique-dappel-doffres-seao'
LAVAL_RESOURCE = 'd4731ee2-b1e5-4a31-bc56-4e13115e74ef'
TRICOR = 'https://www.tricorbraun.com/tricorbraun-opens-new-quebec-distribution-warehouse-to-enhance-customer-service-in-canada'
QUEBEC_RESOURCE = 'ca02aca1-4082-4084-a87d-42f65e102cb8'
BUCKETS = {'Ville de Mont-Royal.': 'GREATER MONTRÉAL', 'Collège de Maisonneuve': 'MONTRÉAL'}
BUYER_PROOFS = {'OP-36446': ('ville.mont-royal.qc.ca', 'https://www.ville.mont-royal.qc.ca'),
                'OP-36229': ('cmaisonneuve.qc.ca', 'https://www.cmaisonneuve.qc.ca/environnement/approvisionnement/'),
                'OP-24857': ('parcolympique.qc.ca', 'https://parcolympique.qc.ca/a-propos/'),
                'OP-13505': ('ithq.qc.ca', 'https://www.ithq.qc.ca/nous-joindre/'),
                'OP-36590': ('stm.info', 'https://www.stm.info/fr/nous-joindre'),
                'OP-36233': ('umontreal.ca', 'https://www.umontreal.ca/fr/')}


def local_date(value):
    if stamp(value): return stamp(value).isoformat()
    try: return datetime.fromisoformat(str(value)).replace(tzinfo=ZoneInfo('America/Toronto')).isoformat()
    except ValueError: return None


def relevant(value):
    from .trigger_intelligence import text
    value = text(value)
    if re.search(r'egout|laue|microscop|radiolog|camera.{0,30}scientifi', value): return False
    if 'incendie' in value and not re.search(r'cablage|telecommunication|reseau informatique|wi.?fi|intercom|videosurveillance|controle d.acces',value): return False
    return bool(re.search(r'cablage|telecommunication|fibre optique|reseau informatique|wi.?fi|videosurveillance|camera|controle d.acces|intercom|low.voltage', value))


class PublicReader:
    def __init__(self, *, transport=None, limit=5):
        self.http = httpx.Client(timeout=httpx.Timeout(20, connect=3), follow_redirects=False, transport=transport)
        self.calls = 0; self.limit = min(limit, 5); self.started = monotonic()

    def get(self, url, *, params=None, max_bytes=2097152, headers=None):
        host = urlsplit(url).hostname
        if urlsplit(url).scheme != 'https' or host not in {'www.donneesquebec.ca', 'donnees.montreal.ca', 'www.tricorbraun.com', 'laval15.ecoparcmontoni.com', 'lovo.co', 'www.saq.com'}:
            raise ValueError('Only configured official public hosts are allowed')
        if self.calls >= self.limit or monotonic()-self.started > 55: raise ValueError('Public-source budget exceeded')
        self.calls += 1
        with self.http.stream('GET', url, params=params, headers=headers or {}) as response:
            if response.status_code == 304: return None, dict(response.headers)
            response.raise_for_status()
            if int(response.headers.get('content-length', '0')) > max_bytes: raise ValueError('Public response exceeds configured byte limit')
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > max_bytes or monotonic()-self.started > 55: raise ValueError('Public response exceeds budget')
            return bytes(body), dict(response.headers)

    def close(self): self.http.close()


def permits(records, *, provider, now, verified_at, published_at=None, retain_history=False):
    result = []
    from .trigger_intelligence import text
    for raw in records:
        laval = provider == 'laval_permit'
        rid = str(raw.get('NO_PERMIS') if laval else raw.get('id_permis') or '')
        issued = local_date(raw.get('DATE_EMISSION') if laval else raw.get('date_emission'))
        category = text(raw.get('CATEGORIE_BATIMENT') if laval else raw.get('description_type_batiment'))
        description = (str(raw.get('TYPE_PERMIS_DESCR') or '') + ' — ' + str(raw.get('TYPE_BATIMENT') or '')) if laval else str(raw.get('nature_travaux') or '')
        commercial = any(word in category for word in ('comm', 'industri', 'institut')) or ('5 log' not in category and 'mult' in category)
        if not rid or not issued or not commercial: continue
        if not retain_history and (now-stamp(issued)).days > 120: continue
        if re.search(r'toiture|abattage|auvent|marquise', text(description)) and not relevant(description): continue
        if not laval and raw.get('code_type_base_demande') != 'CO' and not re.search(r'reamenag|agrand|amenagement|electri|reseau', text(description)): continue
        url = 'https://www.donneesquebec.ca/recherche/dataset/permis-de-construction' if laval else 'https://donnees.montreal.ca/dataset/permis-construction'
        actors = []
        if laval and raw.get('ENTREPRENEUR'):
            actors = [{'role': 'GENERAL CONTRACTOR', 'name': raw['ENTREPRENEUR'], 'confidence': 'UNRESOLVED',
                       'source_actor_id': None, 'source_record_id': rid, 'source_url': url,
                       'note': 'Provider contractor label is observed; name alone does not resolve company or buying authority'}]
        result.append({'source_provider': provider, 'source_record_id': rid, 'source_url': url,
                       'source_version': digest(raw), 'source_version_at': issued, 'source_effective_at': published_at or verified_at,
                       'last_verified_at': verified_at, 'publish_date': issued, 'status': 'ISSUED', 'trigger_type': 'BUILDING PERMIT',
                       'title': description[:700], 'description': category + ' ' + description[:1200],
                       'location': raw.get('ADRESSE') if laval else raw.get('emplacement'),
                       'geography_class': 'LAVAL' if laval else 'MONTRÉAL', 'company_name': None, 'actors': actors,
                       'why_now': 'Commercial/industrial permit dated ' + issued[:10] + '; installation stage and buying organization require verification',
                       'raw': raw, 'refresh_seconds': 86400, 'coverage_seconds': 30*86400, 'event_max_age_days': 90})
    return result


def location_geography(city, region, country):
    from .trigger_intelligence import text
    c, r, nation = text(city), text(region), text(country)
    if nation and nation not in {'canada', 'ca', 'can'}: return 'FOREIGN'
    if c in {'montreal', 'saint-laurent'}: return 'MONTRÉAL'
    if c == 'laval': return 'LAVAL'
    if c in {'terrebonne', 'mascouche', 'blainville', 'saint-jerome', 'boisbriand', 'rosemere', 'mirabel'}: return 'RIVE-NORD'
    if c in {'quebec', 'quebec city'}: return 'QUÉBEC CITY'
    if r in {'quebec', 'qc'}: return 'OTHER QUÉBEC'
    return 'OTHER CANADA' if nation in {'canada', 'ca', 'can'} and r else 'UNKNOWN'


def quebec_permits(data, *, now, verified_at, published_at):
    """Official source lacks buyers; retain meaningful projects, not invented firms."""
    from .trigger_intelligence import text
    features = data.get('features')
    if not isinstance(features, list) or len(features) > 100000: raise ValueError('Québec permit feature bound')
    selected = []
    for feature in features:
        p = feature.get('properties') or {}; reason = str(p.get('RAISON') or ''); value = text(reason)
        issued = local_date(p.get('DATE_DELIVRANCE')); rid = p.get('NUMERO_PERMIS')
        commercial = re.search(r'commercial|industri|institution|entrepot|multifamilial de 9|9 logements et plus', value)
        if not commercial or not issued or not rid or re.search(r'enseigne|affichage|arbre|piscine|stationnement', text(p.get('DOMAINE'))): continue
        selected.append({'source_provider':'quebec_permit','source_record_id':str(rid),
            'source_url':'https://www.donneesquebec.ca/recherche/dataset/permis-delivres-ville-de-quebec',
            'source_version':digest(p),'source_version_at':issued,'source_effective_at':published_at,'last_verified_at':verified_at,
            'publish_date':issued,'status':'ISSUED','trigger_type':'BUILDING PERMIT','title':reason[:700],
            'description':reason[:1200],'geography_class':'QUÉBEC CITY','location':p.get('ADRESSE_TRAVAUX'),
            'company_name':None,'actors':[],'raw':p,'why_now':'Dated official commercial/institutional or9+unit project; owner/buyer and installation stage require research',
            'refresh_seconds':7*86400,'coverage_seconds':30*86400,'event_max_age_days':120})
    return sorted(selected,key=lambda r:(r['publish_date'],r['source_record_id']),reverse=True)[:150]


def seao(releases, *, now, verified_at, published_at, source_url):
    result = []
    for row in latest_releases(releases).values():
        tender = row.get('tender', {}); title = tender.get('title', '')
        if not relevant(title): continue
        buyer = row.get('buyer') or {}; parties = row.get('parties') or []
        party = next((p for p in parties if p.get('id') == buyer.get('id')), {})
        address = party.get('address') or {}
        city = str(address.get('locality') or '')
        region = str(address.get('region') or '')
        country = str(address.get('countryName') or '')
        from .trigger_intelligence import text
        normalized_city = text(city)
        geo = 'MONTRÉAL' if normalized_city in {'montreal', 'saint-laurent'} else 'LAVAL' if normalized_city == 'laval' else 'QUÉBEC CITY' if normalized_city in {'quebec', 'quebec city'} else 'OTHER QUÉBEC' if text(region) in {'qc', 'quebec'} else 'OTHER CANADA' if region and text(country) in {'canada','ca','can'} else 'UNKNOWN'
        if country and text(country) not in {'canada', 'ca', 'can'}: geo = 'FOREIGN'
        if geo == 'UNKNOWN' and not city and buyer.get('name') in BUCKETS: geo = BUCKETS[buyer['name']]
        proof = BUYER_PROOFS.get(buyer.get('id')); host, proof_url = proof or (None, None)
        if not proof:
            website = party.get('details', {}).get('url') or party.get('url')
            from .sales_intelligence import domain
            if isinstance(website, str) and website.startswith('https://'): host, proof_url = domain(website), website
        version = str(row.get('id') or '')
        try: version_at = datetime.strptime(version, '%Y%m%d%H%M%S').replace(tzinfo=timezone.utc).isoformat()
        except ValueError: version_at = local_date(row.get('date'))
        if not version_at: continue
        documents = tender.get('documents') or []
        url = next((d['url'] for d in documents if str(d.get('url', '')).startswith('https://seao.gouv.qc.ca/')), source_url)
        result.append({'source_provider': 'seao', 'source_record_id': row['ocid'], 'source_url': url,
                       'source_version': version, 'source_version_at': version_at, 'source_effective_at': published_at,
                       'last_verified_at': verified_at, 'publish_date': local_date(row.get('date')),
                       'closing_date': tender.get('tenderPeriod', {}).get('endDate'), 'status': tender_status(tender, now),
                       'trigger_type': 'PUBLIC TENDER', 'title': title[:700], 'description': str(tender.get('description') or title)[:2000],
                       'location': address or city or None, 'geography_class': geo, 'company_name': buyer.get('name'), 'domain': host,
                       'company_identity': {'confidence': 'EXACT' if buyer.get('id') else 'UNRESOLVED', 'source_url': proof_url or source_url, 'native_buyer_id': buyer.get('id')},
                       'actors': [{'role': 'BUYER', 'name': buyer.get('name'), 'source_actor_id': buyer.get('id'),
                                   'source_record_id': row['ocid'], 'source_url': source_url, 'confidence': 'EXACT' if buyer.get('id') else 'UNRESOLVED'}],
                       'raw': row, 'refresh_seconds': 86400, 'coverage_seconds': 7*86400, 'event_max_age_days': 90})
    return result


class VisibleText(HTMLParser):
    def __init__(self): super().__init__(); self.parts = []; self.skip = 0
    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style'}: self.skip += 1
    def handle_endtag(self, tag):
        if tag in {'script', 'style'}: self.skip = max(0, self.skip-1)
    def handle_data(self, data):
        if not self.skip: self.parts.append(data)


def expansion(raw, *, now):
    # One bounded primary-source proof. This is not a comprehensive news feed.
    parser = VisibleText(); parser.feed(raw.decode('utf-8', errors='replace'))
    text = ' '.join(' '.join(parser.parts).split())
    headline = 'TricorBraun Opens New Quebec Distribution Warehouse'
    if headline not in text or 'August 10, 2026' not in text or 'new warehouse facility in Laval, Quebec' not in text:
        raise ValueError('Primary expansion evidence changed; research requires revalidation')
    return {'source_provider': 'company_announcement', 'source_record_id': TRICOR, 'source_url': TRICOR,
            'source_version': digest([headline, '2026-08-10', 'new warehouse facility in Laval, Quebec']),
            'source_version_at': '2026-08-10T12:00:00-04:00', 'source_effective_at': now.isoformat(), 'last_verified_at': now.isoformat(),
            'publish_date': '2026-08-10T12:00:00-04:00', 'status': 'ANNOUNCED', 'trigger_type': 'COMPANY EXPANSION',
            'title': 'TricorBraun opened a Laval distribution warehouse', 'description': 'New warehouse facility; installation stage is unknown.',
            'company_name': 'TricorBraun', 'domain': 'tricorbraun.com', 'geography_class': 'LAVAL', 'location': 'Laval, Québec',
            'company_identity': {'confidence': 'SUPPORTED', 'source_url': TRICOR},
            'actors': [{'role': 'FACILITY OPERATOR', 'name': 'TricorBraun', 'source_actor_id': 'domain:tricorbraun.com', 'confidence': 'SUPPORTED', 'source_url': TRICOR}],
            'why_now': 'Company announced a Laval warehouse on August 10; owner should verify remaining network/support needs before any outreach.',
            'raw': {'headline': headline, 'published_date_text': 'August 10, 2026', 'observed_location': 'Laval, Quebec',
                    'body_sha256': hashlib.sha256(raw).hexdigest(), 'structured_metadata_note': 'Embedded NewsArticle refers to a different article; visible primary text used independently.'},
            'refresh_seconds': 7*86400, 'coverage_seconds': 14*86400, 'event_max_age_days': 90}
