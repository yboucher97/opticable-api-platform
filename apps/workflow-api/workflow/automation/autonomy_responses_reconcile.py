"""Recover an existing checkpoint from independently checked local evidence."""
import re

from .action_evidence import ActionEvidence, approval_binding, stamp
from .autonomy_responses import MAX_INPUT_TOKENS, MAX_OUTPUT_TOKENS
from . import autonomy_responses_dispatch as sender


def verified_checkpoint(db, step_at, now, *, source, body, expected):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='action_evidence'").fetchone():
        return None
    record = ActionEvidence.current(db, sender.ACTION_ID)
    if not record or record.get('status') != 'SUCCEEDED':
        return None
    if not ActionEvidence.verify_chain(db, sender.ACTION_ID):
        return None

    reserved_at = stamp(step_at)
    started_at = stamp(record.get('started_at'))
    completed_at = stamp(record.get('completed_at'))
    if (not reserved_at or not started_at or not completed_at
            or not reserved_at <= started_at <= completed_at <= now
            or record.get('readback', {}).get('state') != 'VERIFIED'
            or record.get('effect_result') != 'VERIFIED' or record.get('final_result') != 'SUCCESS'):
        return None
    plan = sender.bind_approved_plan(record | {'status': 'PLANNED'}, body, expected, started_at)
    if plan['exact_versions']['source'] != source:
        return None

    receipt = record.get('after_state')
    required = {'client_request_id', 'response_id', 'http_status', 'response_sha256',
                'proposal_sha256', 'uncached_rate_upper_usd_micros', 'metering'}
    if (not isinstance(receipt, dict) or receipt != record.get('provider_response')
            or not required <= receipt.keys() <= required | {'provider_request_id'}):
        return None
    request_id = receipt.get('provider_request_id')
    if request_id is not None and not re.fullmatch(r'[A-Za-z0-9_.:-]{1,150}', request_id):
        return None
    if (receipt.get('client_request_id') != 'optibrain-' + approval_binding(plan)[:32]
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
