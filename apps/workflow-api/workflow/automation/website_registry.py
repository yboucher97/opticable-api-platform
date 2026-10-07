"""Reviewed site identities; observations use existing Acquisition SOURCE facts.

The catalog grants no provider authority. Production and preview are distinct
identities even when both consume the same static export.
"""
from copy import deepcopy
from urllib.parse import urlsplit
from dataclasses import dataclass

SITES = {
    'opticable.ca': {
        'site_id': 'opticable.ca', 'repository': 'yboucher97/opticable-website',
        'repository_numeric_id': 1179376497, 'default_branch': 'main', 'production_branch': 'main',
        'production_domain': 'opticable.ca', 'production_target': 'opticable-website',
        'production_deployment_model': 'CLOUDFLARE_WORKER_BUILDS_MAIN_ONLY',
        'preview_target': 'opticable-optimization-preview',
        'preview_deployment_model': 'ISOLATED_WORKER_STATIC_ASSETS_EXACT_VERSION',
        'build_definition': 'Pinned native sitegen.py; production-mode validation then isolated preview artifact',
        'test_definition': 'BUILD LINT ROUTES FR EN FORMS GA4 ATTRIBUTION LINKS SCHEMA ACCESSIBILITY RESPONSIVE SECRET_SCAN',
    },
    'ai.opticable.ca': {
        'site_id': 'ai.opticable.ca', 'repository': 'yboucher97/opticable-ai',
        'repository_numeric_id': 1379586689, 'default_branch': 'main', 'production_branch': 'main',
        'production_domain': 'ai.opticable.ca', 'production_target': 'opticable-ai',
        'production_deployment_model': 'CLOUDFLARE_PAGES_DIRECT_UPLOAD_GITHUB_MAIN',
        'preview_target': 'opticable-ai-optimization-preview',
        'preview_deployment_model': 'ISOLATED_WORKER_STATIC_ASSETS_EXACT_VERSION',
        'build_definition': 'pnpm build: next build --webpack; scripts/postprocess-static.mjs; output out/',
        'test_definition': 'BUILD LINT ROUTES FR EN FORMS GA4 ATTRIBUTION LINKS SCHEMA CANONICAL ASSETS ACCESSIBILITY RESPONSIVE SECRET_SCAN',
    },
}


def site_for(*, site_id=None, repository=None, page=None):
    matches = []
    if site_id is not None:
        if site_id not in SITES: raise ValueError('Reviewed site required')
        matches.append(site_id)
    if repository is not None:
        matches += [k for k, v in SITES.items() if v['repository'] == repository]
    if page:
        host = urlsplit(page).hostname
        if host == 'www.opticable.ca': host = 'opticable.ca'
        if host in SITES: matches.append(host)
    if not matches: return None
    if len(set(matches)) != 1: raise ValueError('Site/repository/page mismatch')
    value = SITES[matches[0]]
    if repository is not None and value['repository'] != repository:
        raise ValueError('Site-scoped repository mismatch')
    return deepcopy(value)


def require_site(site_id, repository, preview_target):
    value = site_for(site_id=site_id, repository=repository)
    if preview_target != value['preview_target']:
        raise ValueError('Site-scoped preview target mismatch')
    return value


def validate_scope(repository, *, page=None, preview_target=None, site_id=None):
    value = site_for(repository=repository, page=page, site_id=site_id)
    if value and preview_target is not None:
        require_site(value['site_id'], repository, preview_target)
    return value


@dataclass(frozen=True)
class LiveSiteScope:
    site_id: str
    proposal_id: str
    proposal_revision: int

    def value(self):
        from .website_preview_model import identifier
        identifier(self.proposal_id)
        if type(self.proposal_revision) is not int or self.proposal_revision < 1:raise ValueError('Exact revision required')
        return site_for(site_id=self.site_id)


def websites(store, proposal_rows, now):
    from .manager_sources import stamp
    observed = {r['repository_full_name']: r for r in store.repository_states()}
    result = []
    for identity in SITES.values():
        state = observed.get(identity['repository'], {})
        at = stamp(state.get('source_at'))
        current = bool(at and 0 <= (now-at).total_seconds() <= 3600)
        rows = [p for p in proposal_rows if p['decision_card'].get('site') == identity['site_id']]
        previews=[p['website_preview'] for p in rows if p.get('website_preview')]
        measured=[p['decision_card']['measured_result'] for p in rows if p['decision_card'].get('measured_result')]
        result.append({**deepcopy(identity), 'last_observed_sha': state.get('last_observed_sha'),
            'production_sha': state.get('last_production_sha'),
            'last_production_sha': state.get('last_production_sha'),
            'health': state.get('health_state', 'NOT_COLLECTED') if current else 'STALE' if at else 'NOT_COLLECTED',
            'observed_at': state.get('source_at'), 'github_installation_access': state.get('github_installation_access', 'NOT_COLLECTED'),
            'cloudflare_access': state.get('cloudflare_access', 'NOT_COLLECTED'),
            'pending_proposals': sum(p['status'] not in {'REJECTED','DEFERRED','WAIT','SUPERSEDED','SUCCESS','REGRESSION','NEVER'} for p in rows),
            'previews_ready': sum(bool(p.get('website_preview', {}).get('verified_url')) for p in rows),
            'stale_previews': sum(p.get('website_preview', {}).get('state') in {'STALE_PREVIEW','STALE_BASE','STALE_APPROVAL'} for p in rows),
            'last_preview_state':max(previews,key=lambda p:p.get('updated_at') or '')['state'] if previews else state.get('last_preview_state', 'NOT_COLLECTED'),
            'last_measured_result':max(measured,key=lambda r:r.get('observed_at') or '') if measured else state.get('last_measured_result'),
            'proposals': [p['proposal_id'] for p in rows]})
    return result
