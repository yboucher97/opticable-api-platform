"""Recover an existing checkpoint from independently checked local evidence."""
import re

from .action_evidence import ActionEvidence, approval_binding, stamp
from .autonomy_responses import MAX_INPUT_TOKENS, MAX_OUTPUT_TOKENS
from . import autonomy_responses_dispatch as sender


def verified_checkpoint(db, step_at, now, previous_result, *, source, body, expected, failed=False):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='action_evidence'").fetchone():
        return None
    record = ActionEvidence.current(db, sender.ACTION_ID)
    if not record or record.get('status') != ('FAILED' if failed else 'SUCCEEDED'):
        return None
    if not ActionEvidence.verify_chain(db, sender.ACTION_ID):
        return None

    reserved_at = stamp(step_at)
    started_at = stamp(record.get('started_at'))
    completed_at = stamp(record.get('completed_at'))
    if (not reserved_at or not started_at or not completed_at
            or not reserved_at <= started_at <= completed_at <= now
            or record.get('readback', {}).get('state') != ('FAILED' if failed else 'VERIFIED')
            or record.get('effect_result') != ('UNVERIFIED' if failed else 'VERIFIED')):
        return None
    plan = sender.bind_approved_plan(record | {'status': 'PLANNED'}, body, expected, started_at)
    if plan['exact_versions']['source'] != source:
        return None

    if failed:
        receipt = rate_limit_receipt(record, plan, completed_at)
        if receipt is None:
            return None
        checkpoint = {'source': source, 'input_sha256': sender.PINNED_REQUEST, 'receipt': receipt}
        if previous_result is not None and previous_result != checkpoint:
            return None
        return checkpoint | {'recovery': {'kind': 'rate_limited_provider_journal',
                                          'completed_at': completed_at.isoformat()}}

    receipt = record.get('after_state')
    required = {'client_request_id', 'response_id', 'http_status', 'response_sha256',
                'proposal_sha256', 'uncached_rate_upper_usd_micros', 'metering'}
    if (record.get('final_result') != 'SUCCESS'
            or not isinstance(receipt, dict) or receipt != record.get('provider_response')
            or not required <= receipt.keys() <= required | {'provider_request_id'}):
        return None
    if (not correlated(receipt, plan)
            or receipt.get('proposal_sha256') != plan['proposed_state']['expected_sha256']
            or receipt.get('http_status') != 200
            or not re.fullmatch(r'[0-9a-f]{64}', receipt.get('response_sha256', ''))
            or not re.fullmatch(r'resp_[A-Za-z0-9_-]{1,150}', receipt.get('response_id', ''))):
        return None
    metering = receipt.get('metering', {})
    if not isinstance(metering, dict):
        return None
    units_in, units_out, units_total = (metering.get(k) for k in ('input', 'output', 'total'))
    if (any(type(n) is not int for n in (units_in, units_out, units_total))
            or not 0 < units_in <= MAX_INPUT_TOKENS or not 0 < units_out <= MAX_OUTPUT_TOKENS
            or units_total != units_in + units_out):
        return None
    charge = (3 * units_in + 18 * units_out + 3) // 4
    if type(receipt.get('uncached_rate_upper_usd_micros')) is not int or (
            receipt['uncached_rate_upper_usd_micros'] != charge or charge > sender.MAX_CHARGE_MICROS):
        return None
    return {'source': source, 'input_sha256': sender.PINNED_REQUEST,
            'receipt': {**receipt, 'state': 'VERIFIED_INTERNAL'},
            'recovery': {'kind': 'verified_provider_journal', 'completed_at': completed_at.isoformat()}}


def correlated(receipt, plan):
    upstream = receipt.get('provider_request_id')
    return (receipt.get('client_request_id') == 'optibrain-' + approval_binding(plan)[:32]
            and ('provider_request_id' not in receipt
                 or isinstance(upstream, str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,150}', upstream) is not None))


def rate_limit_receipt(record, plan, completed_at):
    failure = record.get('final_result')
    receipt = record.get('provider_response')
    required = {'client_request_id', 'http_status', 'cooldown_until'}
    if (not isinstance(failure, dict) or failure.get('provider_status') != 429
            or failure.get('stage') != 'PROVIDER_EXECUTION' or failure.get('partial_effects') != 'UNKNOWN'
            or record.get('after_state') is not None
            or not isinstance(receipt, dict) or not required <= receipt.keys() <= required | {'provider_request_id'}
            or receipt.get('http_status') != 429 or not correlated(receipt, plan)):
        return None
    until = stamp(receipt['cooldown_until'])
    if until is None or until < completed_at:
        return None
    return {**receipt, 'state': 'RECONCILE_REQUIRED'}
