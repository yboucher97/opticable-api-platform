"""One-shot OpenAI boundary for the separately approved synthetic milestone.

No launcher, credential source or approval issuer is defined here. The caller
owns the verified scope and the one worker lease.
"""
from copy import deepcopy
from datetime import datetime, timezone
import re

import httpx

from .action_evidence import ActionEvidence, approval_binding, envelope, stamp
from .autonomy_pilot import cgroup_proof, digest, retry_after
from .autonomy_responses import MAX_RESPONSE_BYTES, MODEL, review_response, validate_request

ACTION_ID = 'optibrain-174-first-synthetic-responses'
ENDPOINT = 'https://api.openai.com/v1/responses'
PINNED_REQUEST = 'e162bc7b56db09e61a92f41e8c6671d6fdc0d9c26d3ebd0bedaea34c46b22368'
MAX_CHARGE_MICROS = 310_000
AUTHORITY = 'EXACT_OWNER_APPROVAL_ONE_SYNTHETIC_REQUEST'


def dispatch_plan(body, expected, now, *, source, recovery_receipt, project_receipt, organization, project):
    """Prepare an immutable proposal for the independent owner review path."""
    validate_request(body, PINNED_REQUEST)
    if not re.fullmatch(r'[0-9a-f]{40}', source):
        raise ValueError('Exact reviewed source required')
    if not all(re.fullmatch(r'[0-9a-f]{64}', value) for value in (recovery_receipt, project_receipt)):
        raise ValueError('Exact recovery and project evidence required')
    if not all(re.fullmatch(r'[A-Za-z0-9_-]{1,120}', value) for value in (organization, project)):
        raise ValueError('Dedicated organization and project required')
    return envelope(
        ACTION_ID, 'ai.responses.one', {'type': 'OPENAI_PROJECT', 'identity': project}, now,
        provider='openai', authority_class=AUTHORITY, approval_required=True, mutation=True,
        before_supported=False, rollback_capability='IRREVERSIBLE', irreversible=True,
        reason='Verify one billed model response on a pinned synthetic task',
        business_rationale='Independent quality acceptance without customer data or production effects',
        consequence='A provider that accepts the request can charge for it.',
        compensating_action='Stop the isolated sender, revoke the dedicated credential, and reconcile usage.',
        unknowns=['The provider may accept a request even if the sender receives no response.'],
        exact_versions={'source': source, 'recovery_receipt': recovery_receipt, 'project_receipt': project_receipt},
        proposed_state={'organization': organization, 'project': project, 'endpoint': ENDPOINT,
                        'model': MODEL, 'request_sha256': PINNED_REQUEST, 'expected_sha256': digest(expected),
                        'max_charge_usd_micros': MAX_CHARGE_MICROS, 'requests': 1, 'retries': 0},
    )


def _client():
    return httpx.Client(transport=httpx.HTTPTransport(retries=0, trust_env=False),
                        http2=False, trust_env=False, follow_redirects=False,
                        timeout=httpx.Timeout(30.0, connect=8.0))


def _bounded_body(response):
    if response.headers.get('content-encoding', 'identity').lower() != 'identity':
        raise ValueError('Only uncompressed Responses results are accepted')
    body = bytearray()
    for chunk in response.iter_raw(chunk_size=4096):
        if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
            raise ValueError('Response exceeded byte limit')
        body.extend(chunk)
    return bytes(body)


def approved_plan(journal, body, expected, now):
    """Check an immutable approved plan before a lease is consumed."""
    return bind_approved_plan(journal.get(ACTION_ID), body, expected, now)


def bind_approved_plan(plan, body, expected, now):
    ActionEvidence.executable(plan, now)
    approval = plan['approval_record']
    issued_at = stamp(approval.get('at'))
    if issued_at is None or issued_at > now:
        raise ValueError('Owner approval is not current')
    proposed = plan['proposed_state']
    versions = plan['exact_versions']
    if plan['action_type'] != 'ai.responses.one' or plan['authority_class'] != AUTHORITY or not plan['approval_required']:
        raise ValueError('Exact previously approved one-shot plan required')
    pinned = dispatch_plan(
        body, expected, datetime.fromisoformat(plan['created_at']), source=versions['source'],
        recovery_receipt=versions['recovery_receipt'], project_receipt=versions['project_receipt'],
        organization=proposed['organization'], project=proposed['project'],
    )
    if approval_binding(plan) != approval_binding(pinned):
        raise ValueError('Draft, reviewed source or exact dispatch binding changed')
    return plan


def dispatch_once(journal, *, body, expected, authorize, credential, clock=None):
    """Use an already approved plan once in the reviewed isolated worker.

    The trusted caller must verify current recovery, saved billing and role,
    pinned source, exact ledger, egress fence and external 60 s wall limit.
    `authorize` rechecks that evidence and owner identity against the plan.
    `credential` supplies only the dedicated restricted project key.
    """
    clock = clock or (lambda: datetime.now(timezone.utc))
    now = clock()
    plan = approved_plan(journal, body, expected, now)
    proposed = plan['proposed_state']
    approval = plan['approval_record']
    cgroup_proof()

    def authority_check():
        if authorize(deepcopy(plan)) is not True:
            raise ValueError('Independent current authorization required')

    journal.start(ACTION_ID, now, authority_check=authority_check, expected_approval=approval, clock=clock)
    client_id = 'optibrain-' + approval_binding(plan)[:32]
    evidence = {'client_request_id': client_id}
    status = None
    stage = 'PROVIDER_EXECUTION'
    try:
        key = credential()
        if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{20,2048}', key):
            raise ValueError('Dedicated project credential unavailable')
        headers = {
            'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json',
            'Accept-Encoding': 'identity', 'OpenAI-Organization': proposed['organization'],
            'OpenAI-Project': proposed['project'], 'X-Client-Request-Id': client_id,
        }
        if clock() >= stamp(approval['expires_at']):
            raise ValueError('Owner approval expired before network dispatch')
        with _client() as client, client.stream('POST', ENDPOINT, content=body, headers=headers) as response:
            status = response.status_code
            evidence['http_status'] = status
            provider_id = response.headers.get('x-request-id', '')
            if re.fullmatch(r'[A-Za-z0-9_.:-]{1,150}', provider_id):
                evidence['provider_request_id'] = provider_id
            if status == 429:
                evidence['cooldown_until'] = retry_after(response.headers.get('retry-after'), 1, clock()).isoformat()
            if status != 200:
                raise ValueError('Responses transport did not return HTTP 200')
            stage = 'INDEPENDENT_VERIFICATION'
            reviewed = review_response(_bounded_body(response), expected)
            if reviewed['proposal_sha256'] != proposed['expected_sha256']:
                raise ValueError('Independent proposal binding changed after preparation')
            if reviewed['uncached_rate_upper_usd_micros'] > MAX_CHARGE_MICROS:
                raise ValueError('Response metering outside approved charge envelope')
        evidence.update({k: reviewed[k] for k in (
            'response_id', 'response_sha256', 'proposal_sha256', 'uncached_rate_upper_usd_micros')})
        # Exact counters are integers from the validator. Journal string
        # redaction still applies to opaque references and any unexpected data.
        evidence['metering'] = {'input': reviewed['input_tokens'], 'output': reviewed['output_tokens'],
                                'total': reviewed['total_tokens']}
    except Exception as exc:
        journal.finish(ACTION_ID, clock(), provider_success=False, response=evidence, failure={
            'stage': stage, 'error_class': type(exc).__name__, 'provider_status': status,
            'safe_details': 'One-shot request failed or could not be verified.', 'partial_effects': 'UNKNOWN',
            'recovery_action': 'Read-only project usage reconciliation. Never automatically resend.',
        })
        return {'state': 'RECONCILE_REQUIRED', **evidence}
    if not journal.finish(ACTION_ID, clock(), provider_success=True, actual_after=evidence,
                          verified=True, response=evidence):
        raise RuntimeError('Successful receipt could not be verified in the journal')
    return {'state': 'VERIFIED_INTERNAL', **evidence}
