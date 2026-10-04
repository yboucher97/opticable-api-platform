"""Collection freshness is independent of credentials and traffic volume."""
from datetime import datetime
from zoneinfo import ZoneInfo

PRODUCTION_HOSTS = {'opticable.ca', 'www.opticable.ca', 'ai.opticable.ca'}


def collection_health(report, *, now, attempt=None):
    attempt = attempt or report
    auth = 'GREEN' if attempt.get('state') == 'WORKING' else attempt.get('state', 'UNKNOWN')
    rows = report.get('data', {}).get('rows', [])
    latest = {}
    sites = {}
    for row in rows:
        dims = [v.get('value', '') for v in row.get('dimensionValues', [])]
        if len(dims) != 3 or dims[2].lower() not in PRODUCTION_HOSTS:
            continue
        date, event, host = dims
        try:
            day = datetime.strptime(date, '%Y%m%d').date()
            count = int(float(row['metricValues'][0]['value']))
        except (ValueError, KeyError, IndexError, TypeError):
            continue
        if count <= 0 or day > now.astimezone(ZoneInfo('America/Toronto')).date():
            continue
        site = 'opticable.ca' if host.lower() in {'opticable.ca','www.opticable.ca'} else 'ai.opticable.ca'
        events = sites.setdefault(site,{})
        events[event] = max(events.get(event,''),day.isoformat())
        if event not in latest or day.isoformat() > latest[event]:
            latest[event] = day.isoformat()
    last = max(latest.values(), default=None)
    age = (now.astimezone(ZoneInfo('America/Toronto')).date() - datetime.fromisoformat(last).date()).days if last else None
    state = 'FRESH' if age is not None and age <= 3 else 'NO RECENT DATA' if auth == 'GREEN' else 'UNKNOWN'
    site_status={}
    for site in ('opticable.ca','ai.opticable.ca'):
        date=max(sites.get(site,{}).values(),default=None)
        age=(now.astimezone(ZoneInfo('America/Toronto')).date()-datetime.fromisoformat(date).date()).days if date else None
        site_status[site]={'status':'FRESH' if age is not None and age<=3 else 'NO RECENT DATA' if auth=='GREEN' else 'UNKNOWN','last_observed_data':date}
    return {'auth_status': auth, 'collection_status': state, 'property_id': '530093120',
            'last_observed_data': last, 'latest_events': latest, 'site_events': sites, 'site_status':site_status,'report_observed_at': report.get('observed_at'),
            'coverage_notes': 'Production hosts only; 90-day event report. No recent rows require tag/consent verification; they do not prove zero visitors.'}
