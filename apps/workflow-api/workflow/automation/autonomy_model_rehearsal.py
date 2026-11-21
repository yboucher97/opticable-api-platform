"""Offline model-turn contract rehearsal. No credentials, prompts, or transport."""

from datetime import datetime, timezone
import json
import re

from .autonomy_pilot import Pilot, Task, allowance, current, digest, instant, retry_after

ATTEMPTS = 3
TURN_TOKENS = 1600
TOTAL_TOKENS = 3200
TURN_SECONDS = 45
FIXTURE_KINDS = {'collection': 0, 'quote': 1, 'qualified_lead': 2}


def evidence_plan(evidence, now):
    """Compute the acceptable recommendation from independently supplied facts."""
    candidates = []
    seen = set()
    for row in evidence:
        rid = row['id']
        kind = row['kind']
        if not re.fullmatch(r'[A-Z]{2}[0-9]{2}', rid) or rid in seen or kind not in FIXTURE_KINDS:
            raise ValueError('Unique typed fixture evidence required')
        seen.add(rid)
        origin = 'FORM_RECEIPT' if kind == 'qualified_lead' else 'BOOKS'
        if (row.get('source') != origin or row['classification'] != 'REAL'
                or not current(row['observed_at'], now, 180)):
            continue
        if (row['status'] != {'collection': 'overdue', 'quote': 'sent', 'qualified_lead': 'qualified'}[kind] or
                not re.fullmatch(r'[0-9a-f]{64}', row['version'])):
            continue
        amount = row.get('cents')
        if kind in {'collection', 'quote'} and (
                row.get('currency') != 'CAD' or type(amount) is not int or not 0 < amount <= 10**10):
            raise ValueError('Exact positive CAD fixture cents required')
        candidates.append(row)
    candidates.sort(key=lambda row: (FIXTURE_KINDS[row['kind']], -(row.get('cents') or 0), row['id']))

    selected = []
    groups = set()
    for row in candidates:
        group = row.get('exclusive_group')
        if row['kind'] == 'quote' and (not group or group in groups):
            continue
        if group:
            groups.add(group)
        selected.append({'id': row['id'], 'version': row['version']})
        if len(selected) == 3:
            break
    chosen = {item['id'] for item in selected}
    totals = {kind: sum(row['cents'] for row in candidates if row['id'] in chosen and row['kind'] == kind)
              for kind in ('collection', 'quote')}
    return {'selected': selected, 'overdue_cents': totals['collection'],
            'conditional_quote_cents': totals['quote'], 'currency': 'CAD',
            'disposition': 'PREPARE_INTERNAL'}


def assess_reply(reply, evidence, now, *, attempt, charged):
    """The controller judges exact output independently of fixture assertions."""
    tokens = reply.get('tokens')
    seconds = reply.get('seconds')
    code = reply.get('status')
    safe = type(tokens) is int and 0 <= tokens <= TURN_TOKENS and charged + tokens <= TOTAL_TOKENS
    safe = safe and type(seconds) is int and 0 <= seconds <= TURN_SECONDS
    if not safe:
        return {'state': 'REJECTED', 'reason': 'budget_or_usage_evidence_invalid', 'simulated_total_tokens': TOTAL_TOKENS}
    out = {'simulated_total_tokens': charged + tokens, 'simulated_tokens': tokens}
    if code in (429, 503) and reply.get('confirmed_unaccepted') is True:
        if attempt == ATTEMPTS:
            return out | {'state': 'REJECTED', 'reason': 'retry_budget_exhausted'}
        wait = retry_after(reply.get('retry_after'), attempt, now, jitter=2)
        return out | {'state': 'RETRY_WAIT', 'reason': f'fixture_http_{code}', 'next_at': wait.isoformat(),
                      'new_observation_after': now.isoformat()}
    if code != 200:
        return out | {'state': 'HUMAN_ACTION_REQUIRED', 'reason': 'unknown_or_ambiguous_delivery'}
    expected = evidence_plan(evidence, now)
    proposal = reply.get('proposal')
    if not expected['selected'] or not isinstance(proposal, dict) or digest(proposal) != digest(expected):
        return out | {'state': 'REJECTED' if attempt == ATTEMPTS else 'REPAIR_REQUIRED',
                      'reason': 'independent_evidence_check_failed'}
    return out | {'state': 'VERIFIED_INTERNAL', 'result_sha256': digest(expected)}


class ModelRehearsal:
    """Drive up to three separately fenced fixture attempts through AutomationStore."""

    def __init__(self, scope, *, source, evidence, fixtures):
        if len(fixtures) != ATTEMPTS or len(evidence) > 30:
            raise ValueError('Bounded synthetic rehearsal inputs required')
        if len(json.dumps([evidence, fixtures], allow_nan=False).encode()) > 32 * 1024:
            raise ValueError('Fixture input budget exceeded')
        self.evidence = evidence
        self.fixtures = fixtures
        tasks = [Task(f'model-fixture-{n}', 100 - n, (f'model-fixture-{n-1}',) if n > 1 else ())
                 for n in range(1, ATTEMPTS + 1)]
        tasks += [Task('deterministic-evidence', 75), Task('live-model', 60, lane='model')]
        self.pilot = Pilot(scope, tasks, goal='Offline approval-gated Codex response and recovery rehearsal',
                           source=source, input_hash=digest({'evidence': evidence, 'fixture_replies': fixtures}))

    def run(self, sample, quota, *, clock=None):
        clock = clock or (lambda: datetime.now(timezone.utc))
        cycle = {}
        actions = {}
        reviewers = {}
        for number, reply in enumerate(self.fixtures, 1):
            name = f'model-fixture-{number}'
            actions[name] = lambda n=number, r=reply: self._dispatch(n, r, cycle)
            reviewers[name] = lambda value, n=number, r=reply: self._review(n, r, value, cycle)
        actions['deterministic-evidence'] = lambda: {
            'selected_count': len(evidence_plan(self.evidence, clock())['selected'])}
        reviewers['deterministic-evidence'] = lambda out: {
            'passed': out['selected_count'] == len(evidence_plan(self.evidence, clock())['selected']),
            'check': 'Bounded static evidence projection'}

        def gate(task, prior, now):
            if not task.name.startswith('model-fixture-'):
                return 'ELIGIBLE', None
            number = int(task.name.rsplit('-', 1)[1])
            if cycle.get('dispatched'):
                return 'RETRY_WAIT', 'one_fixture_turn_per_invocation'
            previous = {}
            if number > 1:
                previous = prior[f'model-fixture-{number-1}']['checkpoint']['review']['assessment']
                if previous['state'] not in {'RETRY_WAIT', 'REPAIR_REQUIRED'}:
                    return 'BLOCKED', 'previous_attempt_is_terminal'
                if previous['simulated_total_tokens'] + TURN_TOKENS > TOTAL_TOKENS:
                    return 'BLOCKED', 'insufficient_reserved_fixture_tokens'
                if previous.get('next_at') and now < instant(previous['next_at']):
                    return 'RETRY_WAIT', 'provider_cooldown'
                if previous.get('new_observation_after') and (
                        not current(quota.get('observed_at'), now, 5) or
                        instant(quota['observed_at']) <= instant(previous['new_observation_after'])):
                    return 'BLOCKED', 'fresh_independent_allowance_required'
            metered, reset = self._meter(quota, now)
            cycle['reset'] = reset
            if metered != 'ELIGIBLE':
                return metered if metered == 'RETRY_WAIT' else 'BLOCKED', 'allowance_unavailable'
            cycle['prior_charged'] = previous.get('simulated_total_tokens', 0)
            cycle['reviewed_at'] = now
            return 'ELIGIBLE', None

        results = self.pilot.run(sample, actions, reviewers, clock=clock, task_gate=gate)
        reset = cycle.get('reset')
        results['mode'] = 'OFFLINE_FIXTURES'
        results['live_model_acceptance'] = 'BLOCKED'
        results['fixture_allowance'] = {'next_at': reset.isoformat() if reset else None}
        return results

    def _meter(self, quota, now):
        # This one private checkpoint is read and written under the existing
        # Pilot lock. A fresher percentage cannot shorten the observed boundary.
        name = 'model-quota-hold.json'
        scope = self.pilot.scope
        path = scope.path(name)
        previous = None
        if path.exists():
            if path.stat().st_size > 1024:
                raise ValueError('Quota checkpoint exceeds bound')
            hold = json.loads(path.read_text())
            previous = instant(hold.get('reset_at'))
            if hold.get('plan_sha256') != self.pilot.plan_hash or previous is None:
                raise ValueError('Quota checkpoint does not bind the exact plan')
        state, reset = allowance(quota, now, windows=(10080,), prior_reset=previous)
        if state == 'RETRY_WAIT' and reset and reset != previous:
            scope.write(name, json.dumps({'plan_sha256': self.pilot.plan_hash,
                                          'reset_at': reset.isoformat()}).encode())
        return state, reset

    @staticmethod
    def _dispatch(number, reply, cycle):
        cycle['dispatched'] = True
        return {'attempt': number, 'fixture_response_sha256': digest(reply)}

    def _review(self, number, reply, value, cycle):
        expected_receipt = {'attempt': number, 'fixture_response_sha256': digest(reply)}
        if value != expected_receipt:
            return {'passed': False, 'check': 'Exact fixture response hash'}
        assessment = assess_reply(reply, self.evidence, cycle['reviewed_at'], attempt=number,
                                  charged=cycle['prior_charged'])
        return {'passed': True, 'check': 'Independent fixture receipt, timing and evidence validation',
                'candidate_accepted': assessment['state'] == 'VERIFIED_INTERNAL', 'assessment': assessment}
