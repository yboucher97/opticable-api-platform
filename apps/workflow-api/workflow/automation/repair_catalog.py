"""Validate proposed standing permissions; contains no executor or credentials."""
from datetime import timedelta

from .acquisition_store import digest
from .action_evidence import stamp

ALLOWED = {
    'refresh-local-readiness': ({'optibrain-resource-sample.service'}, 45, 900),
    'restart-contained-support': ({'opticable-password-pdf.service', 'opticable-omada-site.service'}, 90, 3600),
    'exact-approved-release-rollback': ({'opticable-workflow-api.service'}, 180, 3600),
}
ACTIONS = {
    'refresh-local-readiness': [['/usr/bin/python3', '-I', '-B', '/usr/local/lib/optibrain/phase14-runtime-snapshot.py', '--current-services']],
    'restart-contained-support': [['/usr/bin/systemctl', 'restart', '{service}']],
    'exact-approved-release-rollback': [['existing-independent-supervisor', 'EXACT_CODE_CONFIG_ONCE_V1']],
}


def validate_catalog(catalog):
    if not isinstance(catalog, dict) or catalog.get('schema') != 1 or catalog.get('environment') != 'production':
        raise ValueError('Exact production repair proposal required')
    rows = catalog.get('playbooks')
    if not isinstance(rows, list) or len(rows) != len(ALLOWED) or {r.get('id') for r in rows} != set(ALLOWED):
        raise ValueError('Exact bounded playbook inventory required')
    for row in rows:
        services, timeout, cooldown = ALLOWED[row['id']]
        if (set(row.get('services', [])) != services or row.get('actions') != ACTIONS[row['id']]
                or type(row.get('maximum_attempts')) is not int or row['maximum_attempts'] != 1
                or type(row.get('execution_timeout_seconds')) is not int
                or not 1 <= row['execution_timeout_seconds'] <= timeout
                or type(row.get('cooldown_seconds')) is not int or row['cooldown_seconds'] < cooldown):
            raise ValueError('Action, service or execution budget exceeds reviewed catalog')
        for field in ('preconditions', 'success_checks', 'audit', 'prohibitions'):
            if not isinstance(row.get(field), list) or not row[field] or not all(isinstance(v, str) and v for v in row[field]):
                raise ValueError('Explicit evidence and prohibit conditions required')
        for field in ('rollback', 'escalation'):
            if not isinstance(row.get(field), str) or not row[field]:
                raise ValueError('Rollback and escalation behavior required')
        if row.get('approval', {}).get('maximum_permission_lifetime_seconds') != 604800:
            raise ValueError('Seven-day maximum standing permission lifetime required')
    return catalog


def check_standing_permission(catalog, playbook_id, grant, *, expected_digest, now, evidence):
    """Future trusted adapter preflight only; cannot execute a proposed action.

    Caller must supply independently root-verified approval, runtime and evidence.
    Published catalog remains disabled, and no production caller is installed.
    """
    validate_catalog(catalog)
    if digest(catalog) != expected_digest:
        raise ValueError('Independently pinned exact catalog digest required')
    row = next((r for r in catalog['playbooks'] if r['id'] == playbook_id), None)
    if catalog.get('permissions_enabled') is not True or not row or row.get('enabled') is not True:
        raise ValueError('Production repair permissions remain disabled')
    start, end = stamp(grant.get('starts_at')), stamp(grant.get('expires_at'))
    if (grant.get('approved') is not True or grant.get('authority') != 'OWNER_EXACT_STANDING_REPAIR'
            or grant.get('catalog_sha256') != expected_digest or grant.get('playbook_id') != playbook_id
            or grant.get('service') not in row['services'] or start is None or end is None
            or not start <= now < end or not timedelta(0) < end-start <= timedelta(days=7)
            or grant.get('root_verified') is not True):
        raise ValueError('Fresh independently verified exact owner standing grant required')
    required = ('executor_root_pin_verified', '45_flags_off', 'protected_settings_unchanged',
                'no_inflight_business_effects', 'no_recovery_hold', 'fresh_preconditions_verified',
                'exact_configuration_checkpoint_verified', 'existing_audit_ready')
    if not all(evidence.get(k) is True for k in required):
        raise ValueError('Current independent preconditions and execution evidence required')
    return {'playbook_id': playbook_id, 'service': grant['service'],
            'maximum_attempts': 1, 'production_execution_performed': False}
