"""Offline business artifacts. No provider, spending, publishing or deployment adapter.

Inputs are minimized snapshots from the existing native collector. All outputs
are drafts; approval is delegated to the existing website/content workflow.
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

INTERNAL = frozenset(('cached_analysis', 'draft', 'organize_new', 'test', 'private_preview'))
FORBIDDEN = frozenset(('publish', 'send', 'spend', 'advertising_change', 'production_write', 'delete_existing'))
MAX_INPUT = 8 * 1024 * 1024
MAX_FILES = 100
MAX_OUTPUT = 8 * 1024 * 1024


def authorize(action, *, incremental_cost=0, external_effect=False, preview=None):
    if action not in INTERNAL or Decimal(str(incremental_cost)) != 0 or external_effect:
        raise PermissionError('Exact finished owner approval required through existing workflow')
    if action == 'private_preview' and (not preview or not all(preview.get(k) is True for k in
            ('authenticated', 'loopback_only', 'noindex', 'sitemap_excluded', 'analytics_disabled', 'customer_flows_disabled'))):
        raise PermissionError('Verified isolated private preview required')
    return True


def encoded(x):
    return json.dumps(x, ensure_ascii=False, sort_keys=True, indent=2).encode() + b'\n'


def rows(data):
    dimensions = [x['name'] for x in data.get('dimensionHeaders', [])]
    metrics = [x['name'] for x in data.get('metricHeaders', [])]
    return [{**dict(zip(dimensions, [x['value'] for x in r['dimensionValues']])),
             **{k: float(v['value']) for k, v in zip(metrics, r['metricValues'])}}
            for r in data.get('rows', [])]


def analyse(native, supplement, now):
    period = native['collection']['period']
    sources = {s['source']: s for s in native['snapshots']}
    extras = {s['source']: s for s in supplement.get('results', []) if s.get('state') == 'WORKING'}
    def data(name):
        return sources.get('platform:' + name, {}).get('data', {})
    def extra(name):
        s = extras.get('platform:business_autopilot:' + name, {})
        # Never silently compare differently dated reports.
        return s.get('data', {}) if s.get('period') == period or name.endswith(':previous') else {}
    ga = rows(data('ga4:530093120'))
    prior_source = extras.get('platform:business_autopilot:ga4:530093120:previous', {})
    expected_start = datetime.fromisoformat(period['from']).date() - timedelta(days=7)
    expected_end = datetime.fromisoformat(period['from']).date() - timedelta(days=1)
    prior_valid = prior_source.get('period') == {'from': expected_start.isoformat(), 'to': expected_end.isoformat()}
    prior = rows(prior_source.get('data', {})) if prior_valid else []
    sessions = sum(r.get('sessions', 0) for r in ga) if 'platform:ga4:530093120' in sources else None
    previous = sum(r.get('sessions', 0) for r in prior) if prior_valid else None
    channels = defaultdict(float)
    for row in ga:
        channels[row['sessionSourceMedium']] += row.get('sessions', 0)
    daily = data('gsc:daily').get('rows', [])
    dates = sorted({r['keys'][0] for r in daily})
    impressions = sum(r['impressions'] for r in daily)
    clicks = sum(r['clicks'] for r in daily)
    pages = defaultdict(lambda: {'impressions': 0, 'clicks': 0, 'position_weight': 0, 'query_rows': 0})
    for r in data('gsc:query_page').get('rows', []):
        p = pages[r['keys'][1]]
        p['impressions'] += r['impressions']; p['clicks'] += r['clicks']
        p['position_weight'] += r['impressions'] * r['position']; p['query_rows'] += 1
    for p in pages.values():
        p['weighted_position'] = round(p.pop('position_weight') / p['impressions'], 2) if p['impressions'] else None
    crm = data('crm_marketing')
    groups = crm.get('groups', [])
    cf = data('cloudflare:daily').get('data', {}).get('viewer', {}).get('zones', [])
    cfrows = [r for z in cf for r in z.get('httpRequests1dGroups', [])]
    collected = datetime.fromisoformat(native['collection']['at'])
    if collected.tzinfo is None or now.tzinfo is None:
        raise ValueError('Timezone-aware evidence required')
    age = (now - collected).total_seconds()
    if age < -300:
        raise ValueError('Evidence from future')
    references = [{'snapshot_id': s['id'], 'source': s['source'], 'url': s['source_url'],
                   'retrieved_at': s['retrieved_at'], 'effective_from': s.get('effective_from'),
                   'effective_to': s.get('effective_to')} for s in native['snapshots']]
    references += [{'snapshot_id': s.get('snapshot_id'), 'source': s['source'], 'url': s['source_url'],
                    'retrieved_at': supplement.get('observed_at'), 'period': s.get('period')}
                   for s in supplement.get('results', [])]
    return {'schema': 1, 'observed_at': now.isoformat(), 'period': period,
            'freshness': 'CURRENT' if age <= 30 * 3600 else 'STALE_REVIEW_REQUIRED', 'source_age_seconds': age,
            'ga4': {'property': '530093120', 'timezone': 'America/Toronto', 'sessions': sessions,
                    'previous_period': prior_source.get('period') if prior_valid else None, 'previous_sessions': previous,
                    'session_change_percent': round((sessions / previous - 1) * 100, 2) if sessions is not None and previous else None,
                    'key_events': sum(r.get('keyEvents', 0) for r in ga) if ga else None,
                    'channels_sessions': dict(channels), 'events': rows(extra('ga4:530093120:events')),
                    'pages': rows(extra('ga4:530093120:pages')),
                    'second_property': '530619880', 'second_property_observation': 'EMPTY_RESPONSE' if not data('ga4:530619880').get('rows') else 'ROWS_PRESENT'},
            'gsc': {'timezone': 'America/Los_Angeles', 'returned_dates': dates, 'returned_days': len(dates),
                    'requested_days': (datetime.fromisoformat(period['to']) - datetime.fromisoformat(period['from'])).days + 1,
                    'clicks': clicks if daily else None, 'impressions': impressions if daily else None,
                    'ctr_percent': round(clicks / impressions * 100, 3) if impressions else None,
                    'query_page_clicks': sum(p['clicks'] for p in pages.values()),
                    'page_query_slices': dict(sorted(pages.items(), key=lambda p: -p[1]['impressions']))},
            'crm': {'observed_at': crm.get('observed_at'), 'scope': 'visible live inventory; not new leads in period',
                    'leads': sum(g.get('leads', 0) for g in groups) if groups else None,
                    'unattributed': sum(g.get('leads', 0) for g in groups if g.get('source') == 'UNATTRIBUTED') if groups else None,
                    'qualified_outcome_mapping': 'UNVERIFIED', 'problems': crm.get('problems', {})},
            'ads': {'daily_rows': len(data('ads:daily').get('results', [])),
                    'campaign_statuses': [x.get('campaign', {}).get('status') for x in extra('ads:campaign_inventory').get('results', [])],
                    'spend': None, 'roas': None, 'cpql': None},
            'cloudflare': {'requests': sum(r.get('sum', {}).get('requests', 0) for r in cfrows) if cfrows else None,
                           'timezone': 'UTC', 'semantics': 'HTTP requests include bots; not GA4 sessions or leads'},
            'evidence': references,
            'limitations': ['Small samples; no causal conversion-lift claim.', 'GA4 key events are events, not unique qualified CRM leads.',
                           'Missing GSC dates are not zero; query/page slices do not equal property totals.',
                           'No currency blending, ROI, unique-user summation, or invoice-inventory attribution.',
                           'No Meta spend source; fb/paid sessions alone do not establish advertising efficiency.']}


def priorities(a):
    pages = a['gsc']['page_query_slices']
    camera = sum(p['impressions'] for url, p in pages.items() if '/services/' in url and ('camera' in url or 'cameras' in url))
    wifi = pages.get('https://opticable.ca/fr/checklist-audit-wifi-commercial/', {})
    return [
        {'id': 'measurement-qualified-leads', 'rank': 1, 'status': 'DRAFT_READY', 'service': 'all',
         'evidence': {'visible_crm_inventory': a['crm']['leads'], 'unattributed': a['crm']['unattributed'], 'key_events': a['ga4']['key_events']},
         'action': 'Validate event-to-lead mapping, deduplicate by immutable lead/event ID, preserve UTMs and consent. Stage a specification; no live tag/CRM edits.',
         'success_check': 'A synthetic staging submission creates one logical lead and one intended key event; duplicates ignored, unknown attribution retained.',
         'approval_needed': 'Exact production measurement/CRM change only after staging review'},
        {'id': 'camera-project-brief', 'rank': 2, 'status': 'PRIVATE_PREVIEW_CANDIDATE', 'service': 'ip-cameras-ai',
         'evidence': {'visible_camera_query_impressions': camera, 'period': a['period']},
         'action': 'Provide bilingual local project-brief builder and explain zones, reuse, PoE, recording and human-reviewed AI alerts.',
         'success_check': 'Usable keyboard/mobile brief; zero sends/tracking in private preview. Later compare scoped inquiries against baseline, not just clicks.',
         'approval_needed': 'Exact finished website source and deployment separately'},
        {'id': 'wifi-search-intent', 'rank': 3, 'status': 'DRAFT_READY', 'service': 'commercial-networking',
         'evidence': wifi, 'action': 'Add evidence-based WiFi audit FAQs and service links to the existing checklist; draft included.',
         'success_check': 'Track the same query/page cohort after approved release; distinguish qualified inquiries from impressions.',
         'approval_needed': 'Finished public content only'},
        {'id': 'ai-human-review-campaign', 'rank': 4, 'status': 'DRAFT_READY', 'service': 'ai-loss-prevention',
         'evidence': {'camera_interest': camera, 'qualified_ai_demand': 'UNVERIFIED'},
         'action': 'Use bilingual human-review and compatibility-led messaging; no accuracy, savings or loss-reduction guarantees.',
         'success_check': 'Owner-approved wording; compatibility requests measured separately from verified opportunities.',
         'approval_needed': 'Public publication and any future paid campaign each separately'}]


def make_artifacts(native, supplement, bank, now):
    authorize('cached_analysis'); authorize('draft'); authorize('organize_new')
    a = analyse(native, supplement, now)
    local = now.astimezone(ZoneInfo('America/Toronto')).date()
    monday = local + timedelta(days=(7 - local.weekday()) % 7)
    week = monday.isocalendar(); campaign = f'campaigns/{week.year}-W{week.week:02d}/commercial-camera-ai'
    files = {}
    def put(path, value):
        data = encoded(value) if not isinstance(value, str) else value.encode()
        if len(files) >= MAX_FILES or sum(len(x) for x in files.values()) + len(data) > MAX_OUTPUT:
            raise ValueError('Artifact budget exceeded')
        if Path(path).is_absolute() or '..' in Path(path).parts:
            raise ValueError('Unsafe output path')
        files[path] = data
    # One daily analysis per evidence/day. Source timestamps never replaced by run time.
    put(f'analytics/{local}/performance.json', a)
    ranked = priorities(a)
    put(f'planning/{local}/ranked-improvements.json', ranked)
    report = [f'Opticable performance — {a["period"]["from"]} to {a["period"]["to"]}',
              f'Native observation: {native["collection"]["at"]}; freshness: {a["freshness"]}',
              f'GA4 530093120: {a["ga4"]["sessions"]} sessions vs {a["ga4"]["previous_sessions"]} previously ({a["ga4"]["session_change_percent"]}%).',
              f'{a["ga4"]["key_events"]} key events; unique qualified lead count remains unknown.',
              f'GSC returned {a["gsc"]["returned_days"]}/{a["gsc"]["requested_days"]} requested days: {a["gsc"]["clicks"]} clicks, {a["gsc"]["impressions"]} impressions, CTR {a["gsc"]["ctr_percent"]}%.',
              f'Visible CRM inventory: {a["crm"]["leads"]} leads, {a["crm"]["unattributed"]} unattributed; not new daily/weekly leads.',
              f'Cloudflare: {a["cloudflare"]["requests"]} HTTP requests; not visitors or qualified leads.',
              'Google Ads has no daily report rows; inventory and spend evidence must be reviewed before any paid action.',
              'Channel sessions: ' + json.dumps(a['ga4']['channels_sessions'], ensure_ascii=False),
              'GA4 event evidence: ' + json.dumps(a['ga4']['events'], ensure_ascii=False),
              'Ads campaign inventory statuses: ' + json.dumps(a['ads']['campaign_statuses']),
              '', *a['limitations'], '', 'Ranked completed-work opportunities:']
    report += [f'{r["rank"]}. {r["id"]}: {r["action"]}\nEvidence: {json.dumps(r["evidence"], ensure_ascii=False)}\nSuccess: {r["success_check"]}' for r in ranked]
    report += ['', 'Reproduction: performance.json retains provider grain and immutable snapshot IDs; native-input.json and supplement.json contain raw query responses.',
               'Public service context: https://opticable.ca/fr/services/systemes-cameras-securite/ ; https://ai.opticable.ca/fr/ ; https://opticable.ca/fr/services/installation-wifi-commercial/']
    put(f'analytics/{local}/performance.txt', '\n'.join(report) + '\n')
    calendar = []
    for post in bank['posts']:
        day = (monday + timedelta(days=post['day'])).isoformat()
        for lang in ('fr', 'en'):
            path = f'{campaign}/{post["service"]}/{lang}/{post["channel"].lower()}/draft/day-{post["day"]+1}.txt'
            put(path, post[lang + '_title'] + '\n\n' + post[lang] + '\n\nSTATUS: DRAFT — no publication authorized.\n')
            calendar.append({'date': day, 'language': lang, 'service': post['service'], 'channel': post['channel'],
                             'title': post[lang + '_title'], 'path': path, 'status': 'DRAFT_ONLY', 'published': False})
    for topic, labels in {
        'ip-cameras': {'fr': ('VOTRE PROJET CAMÉRA', ['Les bonnes vues.', 'Le bon réseau.', 'Une portée claire.'], 'Préparez les zones à couvrir.'),
                       'en': ('YOUR CAMERA PROJECT', ['Useful views.', 'A planned network.', 'A clear scope.'], 'Start with the areas that matter.')},
        'ai-loss-prevention': {'fr': ('ANALYSE VIDÉO PAR IA', ['Une alerte', 'se vérifie.'], 'Compatibilité et vérification humaine.'),
                               'en': ('AI VIDEO ANALYSIS', ['An alert needs', 'human review.'], 'Assess compatibility before integration.')},
        'commercial-networking': {'fr': ('WI-FI COMMERCIAL', ['Observez avant', 'de remplacer.'], 'Couverture. Capacité. Câblage.'),
                                  'en': ('COMMERCIAL WI-FI', ['Observe before', 'replacing.'], 'Coverage. Capacity. Cabling.')}
    }.items():
        for lang, (eyebrow, lines, footer) in labels.items():
            text = ''.join(f'<text x="88" y="{350+i*100}" font-size="72" font-weight="700">{escape(line)}</text>' for i,line in enumerate(lines))
            svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="1080" viewBox="0 0 1080 1080" role="img" aria-labelledby="title desc">'
                f'<title id="title">{escape(eyebrow)}</title><desc id="desc">{escape(" ".join(lines)+" "+footer)}</desc>'
                '<rect width="1080" height="1080" fill="#0d1c16"/><path d="M850 0H1080V1080H680Z" fill="#163a2a"/>'
                '<g fill="none" stroke="#52d882" stroke-width="3" opacity=".45"><circle cx="975" cy="230" r="150"/><circle cx="975" cy="230" r="100"/><path d="M700 230h380M975 0v460"/></g>'
                '<g fill="#f4f9f5" font-family="Arial, sans-serif"><text x="88" y="120" font-size="39" font-weight="700">OPTICABLE</text>'
                f'<text x="88" y="225" font-size="25" letter-spacing="3" fill="#6fe89b">{escape(eyebrow)}</text>{text}'
                f'<text x="88" y="805" font-size="29">{escape(footer)}</text><rect x="88" y="865" width="70" height="6" fill="#52d882"/>'
                '<text x="88" y="950" font-size="30">opticable.ca</text></g></svg>')
            put(f'{campaign}/{topic}/{lang}/social-media/draft/card.svg', svg)
    put(f'{campaign}/calendar.json', calendar)
    put(f'{campaign}/seven-day-bilingual-calendar.txt', '\n\n'.join(
        f'{row["date"]} | {row["language"].upper()} | {row["service"]} | {row["channel"]}\n{row["title"]}\n' +
        files[row['path']].decode().split('\n\n', 1)[1] for row in calendar))
    for lang in ('fr', 'en'):
        article = next(x for x in bank['articles'] if x['language'] == lang)
        put(f'{campaign}/ip-cameras/{lang}/website/draft/article.txt', article['title'] + '\n\n' + article['body'])
        put(f'{campaign}/ip-cameras/{lang}/advertising/draft/copy.json', bank['ad_copy'][lang])
        faq = '\n\n'.join(item[lang + '_q'] + '\n' + item[lang + '_a'] for item in bank['faqs'])
        put(f'{campaign}/all-services/{lang}/seo/draft/faqs.txt', faq)
        shots = '\n\n'.join(f'{s["seconds"]}: {s["visual"]}\n{s[lang + '_voice']}' for s in bank['video']['shots'])
        put(f'{campaign}/ai-loss-prevention/{lang}/video/draft/script-storyboard.txt', bank['video'][lang + '_title'] + '\n\n' + shots)
    spec = {'schema': 1, 'status': 'STAGING_SPEC_ONLY', 'production_changes': False,
            'events': {'quote_request_click': 'interaction only; not a qualified lead', 'generate_lead': 'one confirmed submission per immutable event/lead ID',
                       'ads_conversion_Request_quote_1': 'legacy mapping requires owner-reviewed deduplication before consolidation'},
            'join': ['immutable event_id', 'CRM lead_id', 'event timestamp and period', 'campaign/source/medium with consent and missing-value labels'],
            'tests': ['Same event twice -> one logical submission', 'Same person new inquiry -> distinct event retained',
                      'Missing campaign -> UNATTRIBUTED, never invented', 'No verified qualified stage -> CPQL and ROAS null'],
            'prohibited': ['Sending real customer data from preview', 'Changing live tags', 'Counting inventory as weekly acquisition']}
    put(f'{campaign}/measurement/draft/event-contract.json', spec)
    plan = [f'Opticable weekly business-growth plan — {monday} to {monday + timedelta(days=6)}',
            'Available draft bank: bilingual social copy, articles, ad copy, video storyboards, FAQs and a staging measurement contract. Actual new work and counts are recorded in the daily completion artifact and existing manager receipts; reused drafts are not newly completed work.',
            'Monday: review measurement contract and camera private preview; retain baseline and obtain approval only for exact finished external changes.',
            'Tuesday: prepare camera/AI campaign assets and verify compatibility claims; no paid launch.',
            'Wednesday: inspect qualified-outcome and source mapping evidence; keep unidentified outcomes explicitly unknown.',
            'Thursday: review WiFi intent FAQ against returned GSC queries and finish owner publication package.',
            'Friday: compare fresh native evidence to same-period baseline; do not infer outcomes from sparse data.',
            'Weekend: organize new artifacts, check pending exact approvals and retain failed/blocked work evidence.',
            'Targets: source provenance on every initiative, 14 reviewed draft posts, one tested camera preview, zero unapproved external changes.',
            'Outcome targets (qualified leads, CPQL, ROAS): establish baseline after attribution is verified; no invented forecast.',
            'Pending publishing approvals do not stop internal analysis, drafting or tests.']
    put(f'planning/{week.year}-W{week.week:02d}/weekly-growth-plan.txt', '\n'.join(plan) + '\n')
    put(f'planning/{local:%Y-%m}/monthly-review.json', {'status': 'PARTIAL_PERIOD_BASELINE', 'period_observed': a['period'],
        'measured_results': {'sessions': a['ga4']['sessions'], 'qualified_leads': None, 'roas': None},
        'priorities': [r['id'] for r in ranked], 'monthly_totals_available': False,
        'next_review': 'Use retained native history and approved initiative outcomes; do not extrapolate partial week to month.'})
    put(f'learning/{local}/completed-work.json', {'evidence_ids': [r['snapshot_id'] for r in a['evidence']],
        'initiatives': [{'id': r['id'], 'stage': 'DRAFT', 'artifact_created': True, 'owner_approved': False,
                         'deployed': False, 'measured_outcome': None, 'review_required': r['approval_needed']} for r in ranked],
        'blocked': [{'action': 'remote_staging', 'reason': 'testopti HTTP403 alone does not verify protection or deployment authority'},
                    {'action': 'cloud_folder_upload', 'reason': 'No verified dedicated Opticable cloud folder; preserve unrelated company folders'}],
        'learning': 'Attribution and GSC date coverage constrain decisions. Improve evidence before spend. No fake qualified conversions.'})
    return files


def write_bundle(root, files):
    """Immutable content revisions. Same input is a no-op; never overwrite originals."""
    root = Path(root)
    if root.is_symlink():
        raise ValueError('Symlink output root')
    root = root.resolve(); root.mkdir(mode=0o700, parents=True, exist_ok=True)
    manifest = []
    for relative, data in sorted(files.items()):
        if Path(relative).is_absolute() or '..' in Path(relative).parts:
            raise ValueError('Unsafe output path')
        h = sha256(data).hexdigest()
        base = root / relative
        # Every mutable-looking logical name resolves to a content-addressed revision.
        path = base.with_name(base.stem + '.r-' + h[:16] + base.suffix)
        cursor = root
        for component in Path(relative).parts[:-1]:
            cursor = cursor / component
            if cursor.is_symlink():
                raise ValueError('Symlink output parent')
            cursor.mkdir(mode=0o700, exist_ok=True)
        if not path.resolve().is_relative_to(root) or path.is_symlink():
            raise ValueError('Symlink escape')
        try:
            with path.open('xb') as f:
                f.write(data)
            path.chmod(0o600)
        except FileExistsError:
            if path.read_bytes() != data:
                raise ValueError('Existing revision corruption')
        manifest.append({'logical_path': relative, 'path': str(path.relative_to(root)), 'sha256': h, 'bytes': len(data), 'status': 'DRAFT_ONLY'})
    return manifest
