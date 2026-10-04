"""Evidence strength and geographic scope never confer action authority."""
import math,re,unicodedata


def numeric(value):
    if value is None or isinstance(value,bool):return None
    try:value=float(value)
    except (ValueError,TypeError):return None
    return value if math.isfinite(value) and value>=0 else None


def fold(value):
    return ''.join(c for c in unicodedata.normalize('NFKD',str(value or '').casefold()) if not unicodedata.combining(c))


def geo_bucket(value):
    v=fold(value).strip()
    if v in {'can','ca','canada'}:return 'CANADA'
    if v in {'qc','quebec','quebec province'}:return 'QUÉBEC'
    if 'quebec city' in v or 'ville de quebec' in v:return 'QUÉBEC CITY'
    if 'greater montreal' in v or 'grand montreal' in v:return 'GREATER MONTRÉAL'
    if 'montreal' in v:return 'MONTRÉAL'
    if 'laval' in v:return 'LAVAL'
    if 'rive-nord' in v:return 'RIVE-NORD'
    if v in {'usa','us','united states','fr','france','gb','uk','united kingdom','de','germany','foreign'}:return 'FOREIGN'
    if v=='other canada' or any(re.search(r'\b'+x+r'\b',v) for x in ('toronto','ottawa','vancouver','calgary')):return 'OTHER CANADA'
    if re.search(r'\b(albuquerque|las vegas|los angeles|new york|texas|florida|united states|france|united kingdom)\b',v):return 'FOREIGN'
    if re.search(r'\bquebec\b',v):return 'QUÉBEC'
    return 'UNKNOWN'


def geography_evidence(row):
    # Language never supplies geographic evidence. Owner seed targets are not
    # measured geography, and query location is intent, not visitor location.
    declared=row.get('geography')
    source='UNKNOWN' if row.get('seed_only') or row.get('geography_basis')=='TARGET HYPOTHESIS' else geo_bucket(declared)
    country_value=str(row.get('country') or '').strip()
    country=geo_bucket(country_value)
    if country=='UNKNOWN' and re.fullmatch('[A-Za-z]{2,3}',country_value):country='FOREIGN'
    countries=row.get('source_countries',[])
    if countries:
        buckets={'CANADA' if str(c).casefold() in {'can','ca','canada'} else 'FOREIGN' for c in countries}
        country=next(iter(buckets)) if len(buckets)==1 else 'UNKNOWN'
    if source=='UNKNOWN':source=country
    query=geo_bucket(row.get('query',''))
    result=query if query!='UNKNOWN' else source
    excluded=result in {'FOREIGN','OTHER CANADA'} or source=='FOREIGN'
    conflict=query=='FOREIGN' and source not in {'UNKNOWN','FOREIGN'} or source=='FOREIGN' and query not in {'UNKNOWN','FOREIGN'}
    return {'geography':result,'source_geography':source,'query_geography':query,
            'truth':'DERIVED FACT' if query!='UNKNOWN' else 'MEASURED FACT' if source!='UNKNOWN' else 'UNKNOWN',
            'basis':'Explicit query location; not traffic geography' if query!='UNKNOWN' else 'Provider scope' if source!='UNKNOWN' else 'No geographic evidence; language is insufficient',
            'target_geography':row.get('target_geography') or (declared if row.get('seed_only') else None),
            'source_countries':countries,
            'conflict':bool(conflict),'quebec_recommendation_allowed':not excluded,
            'relevance':'FOREIGN / OUT OF SCOPE — RESEARCH ONLY' if excluded else 'UNKNOWN' if result=='UNKNOWN' else 'IN SCOPE; precise market coverage may remain partial'}


def search_evidence(row):
    n=numeric(row.get('impressions'));clicks=numeric(row.get('clicks'));position=numeric(row.get('position'))
    strength='INSUFFICIENT EVIDENCE' if n is None or n==0 else 'STRONG EVIDENCE' if n>=100 else 'MODERATE EVIDENCE' if n>=10 else 'TENTATIVE EVIDENCE'
    ctr=numeric(row.get('ctr'))
    if ctr is None and n and clicks is not None:ctr=clicks/n
    # Position signal is independent of statistical support. Sparse queries
    # remain interesting, but cannot earn the same confidence bonus as n=100.
    support=min(1,math.log1p(n)/math.log(101)) if n is not None else 0
    return {'class':strength,'impressions':n,'clicks':clicks,'ctr':ctr,'position':position,
            'date_from':row.get('date_from'),'date_to':row.get('date_to'),
            'observed_at':row.get('observed_at'),'source':row.get('source') or 'Search Console',
            'position_support':round(support,4),
            'near_page_one_signal':position is not None and 8<=position<=20 and bool(n),
            'position_note':f'Average position {position:g} based on {n:g} impressions ({strength.lower()})' if position is not None and n is not None else 'Position/sample unknown'}


def fact(value,source,truth='MEASURED FACT'):
    return {'value':value,'source':source,'truth':'UNKNOWN' if value is None else truth}
