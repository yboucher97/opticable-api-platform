"""Bind already verified evidence to the existing one-shot queue.

The privileged launcher supplies the independently authenticated owner packet
digest and evidence for the enforced runtime. This module issues no approvals,
adds no credential source, and does not enable network access.
"""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
import re
import subprocess

from .action_evidence import stamp
from .autonomy_pilot import digest
from .autonomy_responses import validate_request
from .autonomy_responses_dispatch import ENDPOINT, MAX_CHARGE_MICROS, MODEL, PINNED_REQUEST
from .autonomy_responses_queue import run_responses_task
from .codex_fixture_protocol import strict_object

_REPO = Path(__file__).resolve().parents[4]
_LIMITS = {'requests': 1, 'retries': 0, 'output_units': 512, 'wall_seconds': 60,
           'max_usd_micros': MAX_CHARGE_MICROS}
_HASH = re.compile(r'[0-9a-f]{64}')
_ID = re.compile(r'[A-Za-z0-9_.@:-]{1,160}')


def _packet(raw):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= 8192:
        raise ValueError('Bounded evidence packet required')
    return strict_object(raw)


def _checkout_source():
    git = ['/usr/bin/git', '--no-optional-locks', '-c', 'core.fsmonitor=false', '-C', str(_REPO)]
    # These checks run against the executing checkout, without caller-supplied Git settings.
    env = {'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null'}
    if subprocess.check_output([*git, 'status', '--porcelain=v1'], env=env, timeout=5).strip():
        raise ValueError('Reviewed source checkout must be clean')
    return subprocess.check_output([*git, 'rev-parse', 'HEAD'], env=env, timeout=5).decode().strip()


def verify_launch_evidence(scope, *, owner, expected_owner_sha256, recovery, project, runtime, now):
    """Verify exact bindings. The owner digest must arrive through the trusted launcher."""
    approved = _packet(owner)
    if not isinstance(expected_owner_sha256, str) or not _HASH.fullmatch(expected_owner_sha256):
        raise ValueError('Independent owner approval digest required')
    if sha256(owner).hexdigest() != expected_owner_sha256:
        raise ValueError('Owner approval bytes disagree with the independently trusted digest')

    required = {'schema', 'owner', 'starts_at', 'expires_at', 'source', 'scope', 'recovery_sha256',
                'project_sha256', 'runtime_sha256', 'request_sha256', 'expected_sha256', 'endpoint', 'model', 'limits'}
    if approved.keys() != required or type(approved['schema']) is not int or approved['schema'] != 1:
        raise ValueError('Exact one-use authority fields required')
    start = stamp(approved['starts_at'])
    end = stamp(approved['expires_at'])
    if (not isinstance(approved['owner'], str) or not _ID.fullmatch(approved['owner'])
            or start is None or end is None or not start <= now < end
            or approved['request_sha256'] != PINNED_REQUEST
            or approved['endpoint'] != ENDPOINT or approved['model'] != MODEL
            or approved['limits'] != _LIMITS
            or any(type(v) is not int for v in approved['limits'].values())
            or approved['scope'] != str(scope.root)):
        raise ValueError('Owner approval is not current or does not authorize this exact launch')

    parsed = {}
    for name, raw in (('recovery', recovery), ('project', project), ('runtime', runtime)):
        parsed[name] = _packet(raw)
        if sha256(raw).hexdigest() != approved[name + '_sha256']:
            raise ValueError('Reviewed evidence bytes changed')

    restore = parsed['recovery']
    if (restore.get('result') != 'SIGNED_RECEIPT_MATCH'
            or not isinstance(restore.get('signed_receipt_sha256'), str)
            or not _HASH.fullmatch(restore['signed_receipt_sha256'])
            or restore.get('generation') != '20261121T024014Z'
            or restore.get('independent_review') is not True):
        raise ValueError('Independent offline restore evidence required')
    settings = parsed['project']
    checked = stamp(settings.get('verified_at'))
    limit = settings.get('hard_monthly_usd_micros')
    if (checked is None or not timedelta(0) <= now - checked <= timedelta(minutes=15)
            or settings.get('model') != MODEL or settings.get('service_tier') != 'global_standard'
            or settings.get('hard_limit_enforced') is not True or settings.get('automatic_reload') is not False
            or settings.get('funding_verified') is not True or settings.get('restricted_identity_verified') is not True
            or type(limit) is not int or not 0 < limit <= 1_000_000
            or settings.get('input_usd_cents_per_million') != 75
            or settings.get('output_usd_cents_per_million') != 450
            or not all(isinstance(settings.get(k), str) and _ID.fullmatch(settings[k])
                       for k in ('organization', 'project'))):
        raise ValueError('Dedicated project billing or identity evidence is insufficient')
    bounds = parsed['runtime']
    if (bounds.get('launcher_review') != 'PASS' or bounds.get('egress') != ENDPOINT
            or type(bounds.get('external_wall_seconds')) is not int
            or bounds['external_wall_seconds'] != _LIMITS['wall_seconds']
            or bounds.get('scope') != str(scope.root) or bounds.get('source') != approved['source']):
        raise ValueError('Reviewed exact launcher and external limits required')
    if not re.fullmatch(r'[0-9a-f]{40}', str(approved['source'])) or approved['source'] != _checkout_source():
        raise ValueError('Executing source is outside owner approval')
    return approved, settings


def run_reviewed_launch(scope, sample, *, owner, expected_owner_sha256, recovery, project, runtime,
                        body, expected, credential, clock=None):
    """Supply verified bindings to the existing queue without issuing an approval."""
    clock = clock or (lambda: datetime.now(timezone.utc))
    now = clock()
    scope.verify(now)
    validate_request(body, PINNED_REQUEST)
    approved, settings = verify_launch_evidence(scope, owner=owner, expected_owner_sha256=expected_owner_sha256,
        recovery=recovery, project=project, runtime=runtime, now=now)
    if approved['expected_sha256'] != digest(expected):
        raise ValueError('Exact reviewed expected result required')

    def observe():
        return sample() | {'offline_restore_receipt_sha256': approved['recovery_sha256'],
                           'verified_project_receipt_sha256': approved['project_sha256']}

    def owner_authority(plan):
        original = plan['approval_record']
        proposed = plan['proposed_state']
        return (original['actor'] == approved['owner']
                and stamp(original['expires_at']) == stamp(approved['expires_at'])
                and stamp(approved['starts_at']) <= stamp(original['at']) <= clock() < stamp(approved['expires_at'])
                and proposed['organization'] == settings['organization'] and proposed['project'] == settings['project'])

    return run_responses_task(scope, observe, source=approved['source'], body=body, expected=expected,
        authorize=owner_authority, credential=credential, clock=clock)


def recover_reviewed_checkpoint(scope, *, body, expected, clock=None):
    """Reopen an existing checkpoint offline even after the launch approval expires."""
    validate_request(body, PINNED_REQUEST)
    if not scope.path('automation.db').is_file():
        raise ValueError('Existing pinned queue ledger required')
    return run_responses_task(scope, dict, source=_checkout_source(), body=body, expected=expected,
        authorize=lambda _: False, credential=None, clock=clock)
