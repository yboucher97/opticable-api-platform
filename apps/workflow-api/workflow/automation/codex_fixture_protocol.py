"""Bounded parser for the documented Codex exec JSONL contract.

Used only with the offline rehearsal. This module does not spawn a process,
read credentials, make a provider request or grant execution authority.
"""
import json

MAX_TRACE_BYTES = 24 * 1024
MAX_EVENTS = 32
MAX_MESSAGE_BYTES = 8 * 1024


def strict_object(raw):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError('Duplicate JSON property')
            result[key] = value
        return result

    def refuse_constant(_):
        raise ValueError('Non-finite JSON number')

    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=refuse_constant)
    if not isinstance(value, dict):
        raise ValueError('Expected JSON object')
    return value


def _usage(value):
    if not isinstance(value, dict):
        raise ValueError('Missing terminal usage')
    fields = ('input_tokens', 'cached_input_tokens', 'output_tokens')
    counters = {key: value.get(key) for key in fields}
    counters['reasoning_output_tokens'] = value.get('reasoning_output_tokens', 0)
    if any(type(n) is not int or not 0 <= n <= 10**8 for n in counters.values()):
        raise ValueError('Invalid token counters')
    if (counters['cached_input_tokens'] > counters['input_tokens']
            or counters['reasoning_output_tokens'] > counters['output_tokens']):
        raise ValueError('Inconsistent token counters')
    return counters


def fixture_reply(envelope):
    """Read a proposal and post-turn counters from a successful fixture transcript."""
    trace = envelope.get('stdout_jsonl')
    if not isinstance(trace, str) or len(trace.encode()) > MAX_TRACE_BYTES:
        raise ValueError('Invalid fixture transcript size')
    lines = trace.removesuffix('\n').split('\n')
    if not 4 <= len(lines) <= MAX_EVENTS:
        raise ValueError('Expected bounded single-turn transcript')
    head = strict_object(lines[0])
    if head.get('type') != 'thread.started' or not isinstance(head.get('thread_id'), str) or not head['thread_id']:
        raise ValueError('Missing thread start')
    if strict_object(lines[1]).get('type') != 'turn.started':
        raise ValueError('Missing turn start')

    proposal_text = None
    for line in lines[2:-1]:
        event = strict_object(line)
        item = event.get('item')
        if not isinstance(item, dict) or event.get('type') not in {'item.started', 'item.updated', 'item.completed'}:
            raise ValueError('Unexpected or failed turn event')
        if item.get('type') == 'reasoning' and proposal_text is None:
            continue
        if (proposal_text is not None or item.get('type') != 'agent_message'
                or event['type'] != 'item.completed' or not isinstance(item.get('text'), str)
                or len(item['text'].encode()) > MAX_MESSAGE_BYTES):
            raise ValueError('Tool, duplicate message or unsupported output')
        proposal_text = item['text']

    terminal = strict_object(lines[-1])
    if terminal.get('type') != 'turn.completed' or proposal_text is None:
        raise ValueError('Missing complete turn evidence')
    usage = _usage(terminal.get('usage'))
    try:
        proposal = strict_object(proposal_text)
    except (ValueError, RecursionError):
        proposal = None  # Completed, charged turn. Independent review can request bounded repair.
    return ({'status': 200, 'tokens': usage['input_tokens'] + usage['output_tokens'],
             'seconds': envelope.get('seconds'), 'proposal': proposal}, usage)


def billing_blockers(observation):
    """A supported account snapshot reports usage, never execution authority."""
    reasons = ['provider_enforced_included_only_unverified']
    if observation.get('existing_credit_availability') is True:
        reasons.append('credits_available_for_automatic_overflow')
    elif observation.get('existing_credit_availability') is not False:
        reasons.append('credit_availability_unknown')
    if observation.get('automatic_reload_setting') != 'VERIFIED_DISABLED':
        reasons.append('automatic_reload_unverified')
    return {'state': 'BLOCKED_SCOPE_AND_BILLING', 'reasons': reasons, 'model_turns_started': 0}
