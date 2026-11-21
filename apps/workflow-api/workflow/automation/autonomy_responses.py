"""Validate one pinned synthetic Responses request and its result offline.

No network, credentials, execution authority, or live task registration.
"""
from hashlib import sha256
import re

from .autonomy_pilot import digest
from .codex_fixture_protocol import strict_object

MODEL = 'gpt-5.4-mini-2026-03-17'
MAX_INPUT_TOKENS = 400_000
MAX_OUTPUT_TOKENS = 512
MAX_REQUEST_BYTES = 4096
MAX_RESPONSE_BYTES = 16 * 1024

_REQUEST_FIELDS = frozenset({
    'background', 'input', 'instructions', 'max_output_tokens', 'model',
    'parallel_tool_calls', 'reasoning', 'service_tier', 'store', 'stream',
    'text', 'tool_choice', 'tools',
})


def validate_request(body: bytes, expected_sha256: str) -> None:
    """Bind exact bytes to the caller's verified request digest and envelope."""
    if (not isinstance(body, bytes) or not 0 < len(body) <= MAX_REQUEST_BYTES
            or sha256(body).hexdigest() != expected_sha256):
        raise ValueError('Pinned request bytes required')
    request = strict_object(body)
    if request.keys() != _REQUEST_FIELDS:
        raise ValueError('Unexpected request fields')
    if (request['model'] != MODEL or request['service_tier'] != 'default'
            or type(request['max_output_tokens']) is not int or request['max_output_tokens'] != MAX_OUTPUT_TOKENS
            or request['reasoning'] != {'effort': 'none'}
            or request['tools'] != [] or request['tool_choice'] != 'none'
            or any(request[key] is not False for key in ('background', 'parallel_tool_calls', 'store', 'stream'))
            or not all(isinstance(request[key], str) and request[key] for key in ('input', 'instructions'))):
        raise ValueError('Request outside the no-tools single-turn envelope')
    text = request['text']
    format_spec = text.get('format') if isinstance(text, dict) else None
    if (not isinstance(format_spec, dict) or format_spec.get('type') != 'json_schema'
            or format_spec.get('strict') is not True or not isinstance(format_spec.get('schema'), dict)):
        raise ValueError('Strict structured result required')


def _usage(response):
    usage = response.get('usage')
    if not isinstance(usage, dict):
        raise ValueError('Completed usage required')
    input_tokens, output_tokens, total = (usage.get(key) for key in ('input_tokens', 'output_tokens', 'total_tokens'))
    if (any(type(n) is not int for n in (input_tokens, output_tokens, total))
            or not 0 < input_tokens <= MAX_INPUT_TOKENS or not 0 < output_tokens <= MAX_OUTPUT_TOKENS
            or total != input_tokens + output_tokens):
        raise ValueError('Inconsistent or out-of-envelope usage')
    for group, counter, limit in (
        ('input_tokens_details', 'cached_tokens', input_tokens),
        ('output_tokens_details', 'reasoning_tokens', output_tokens),
    ):
        details = usage.get(group, {})
        if not isinstance(details, dict):
            raise ValueError('Invalid usage details')
        subset = details.get(counter, 0)
        if type(subset) is not int or not 0 <= subset <= limit:
            raise ValueError('Usage subsets exceed totals')
    # USD microdollars at published standard rates, with all input uncached.
    ceiling_micros = (3 * input_tokens + 18 * output_tokens + 3) // 4
    return {'input_tokens': input_tokens, 'output_tokens': output_tokens,
            'total_tokens': total, 'uncached_rate_upper_usd_micros': ceiling_micros}


def review_response(body: bytes, expected_proposal: dict) -> dict:
    """Return only hashes and metering for a completed, verified proposal."""
    if not isinstance(body, bytes) or not 0 < len(body) <= MAX_RESPONSE_BYTES:
        raise ValueError('Bounded response bytes required')
    response = strict_object(body)
    if (response.get('object') != 'response' or response.get('status') != 'completed'
            or response.get('model') != MODEL or response.get('service_tier') != 'default'
            or response.get('error') is not None or response.get('incomplete_details') is not None):
        raise ValueError('Complete response on the pinned model and tier required')
    response_id = response.get('id')
    if not isinstance(response_id, str) or not re.fullmatch(r'resp_[A-Za-z0-9_-]{1,150}', response_id):
        raise ValueError('Provider response identity required')
    outputs = response.get('output')
    if not isinstance(outputs, list) or len(outputs) != 1 or not isinstance(outputs[0], dict):
        raise ValueError('One assistant output required')
    message = outputs[0]
    parts = message.get('content')
    if (message.get('type') != 'message' or message.get('role') != 'assistant'
            or message.get('status') != 'completed' or not isinstance(parts, list)
            or len(parts) != 1 or not isinstance(parts[0], dict)
            or parts[0].get('type') != 'output_text' or not isinstance(parts[0].get('text'), str)):
        raise ValueError('One complete text result required')
    proposal = strict_object(parts[0]['text'])
    received = digest(proposal)
    if received != digest(expected_proposal):
        raise ValueError('Independent proposal check failed')
    return {'response_id': response_id, 'response_sha256': sha256(body).hexdigest(),
            'proposal_sha256': received, **_usage(response)}
