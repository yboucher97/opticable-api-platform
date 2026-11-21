"""Bind the pinned model task to the existing development lease and journal."""
from copy import deepcopy
from datetime import datetime, timezone
from functools import partial

from .action_evidence import ActionEvidence
from .autonomy_pilot import LEASE_SECONDS, Pilot, Task, admission
from .autonomy_responses_reconcile import verified_checkpoint
from . import autonomy_responses_dispatch as sender

TASK = Task('first-live-synthetic-request', 90, lane='model')


def run_responses_task(scope, sample, *, source, body, expected, authorize, credential, clock=None):
    """Process one exact task from an independently verified launcher.

    The sample carries the SHA-256 of the verified recovery and billing receipts.
    The launcher is responsible for independently checking their authenticity,
    binding the canonical scope, enforcing restricted egress and applying the wall limit.
    """
    clock = clock or (lambda: datetime.now(timezone.utc))
    pilot = Pilot(scope, (TASK,), goal='Issue 174 first pinned model task', source=source,
                  input_hash=sender.PINNED_REQUEST)
    event_id = pilot.event_id(TASK)
    with scope.lock():
        now = clock()
        scope.verify(now)
        store, ids = pilot._open(now)
        store.recover_expired_claims(now=now)
        run_id = ids[event_id]
        row = store.get_run(run_id)
        journal = ActionEvidence(store.db_path)
        if row['status'] != 'queued':
            result = {'state': row['status'].upper(), 'run_id': run_id, 'checkpoint': row['context']}
            if row['status'] == 'human_action_required' and 'receipt' not in (row['context'] or {}):
                provider = journal.get(sender.ACTION_ID)
                result['provider_journal_state'] = provider['status'] if provider else 'NOT_STARTED'
                if provider and provider['status'] == 'SUCCEEDED':
                    try:
                        checkpoint = store.finalize_expired_verified_step(run_id, event_id=event_id,
                            step_id=TASK.name, action='ai.responses.one', now=clock(),
                            verify=partial(verified_checkpoint, source=source, body=body, expected=expected))
                    except (ValueError, TypeError, KeyError):
                        checkpoint = None
                    if checkpoint is not None:
                        return {'state': 'COMPLETED', 'run_id': run_id, 'checkpoint': checkpoint}
            return result

        def held(state, reason):
            return {'state': state, 'run_id': run_id, 'reason': reason}

        observed = sample()
        state, reason = admission(observed, clock())
        if state != 'ELIGIBLE':
            return held(state, reason)
        plan = journal.get(sender.ACTION_ID)
        if not plan or not plan.get('approval_record'):
            return held('APPROVAL_REQUIRED', 'independent_owner_approval_missing')
        if plan['status'] != 'PLANNED':
            return held('HUMAN_ACTION_REQUIRED', 'provider_journal_already_started_or_closed')
        try:
            plan = sender.approved_plan(journal, body, expected, clock())
        except ValueError:
            return held('APPROVAL_REQUIRED', 'pinned_plan_or_approval_changed')
        versions = plan['exact_versions']
        if (versions['source'] != source
                or versions['recovery_receipt'] != observed.get('offline_restore_receipt_sha256')
                or versions['project_receipt'] != observed.get('verified_project_receipt_sha256')):
            return held('APPROVAL_REQUIRED', 'source_or_verified_receipt_binding_missing')
        if authorize(deepcopy(plan)) is not True:
            return held('APPROVAL_REQUIRED', 'independent_authority_not_current')
        try:
            sender.cgroup_proof()
        except (OSError, ValueError):
            return held('BLOCKED', 'independent_kernel_limits_missing')

        attempt = store.claim_run(run_id, 'pinned-responses-worker', lease_seconds=LEASE_SECONDS, now=clock())
        if attempt is None:
            raise RuntimeError('Pinned request lease refused')
        marker = store.begin_claimed_action(run_id, attempt, step_id=TASK.name,
            action='ai.responses.one', action_identity=event_id, attempt=1, now=clock())
        if marker is None:
            raise RuntimeError('Pinned request action marker refused')

        def lease_credential():
            if not store.renew_claim(run_id, attempt, lease_seconds=LEASE_SECONDS, now=clock()):
                raise RuntimeError('Lease lost before credential access')
            return credential()

        # A changed approval or stale admission can only prevent dispatch.
        try:
            receipt = sender.dispatch_once(journal, body=body, expected=expected,
                authorize=lambda candidate: (candidate == plan and admission(observed, clock())[0] == 'ELIGIBLE'),
                credential=lease_credential, clock=clock)
        except (ValueError, RuntimeError, OSError):
            receipt = {'state': 'RECONCILE_REQUIRED', 'reason': 'prepared_dispatch_could_not_be_verified'}

        checkpoint = {'source': source, 'input_sha256': sender.PINNED_REQUEST, 'receipt': receipt}
        verified = receipt['state'] == 'VERIFIED_INTERNAL'
        failure = {}
        if not verified:
            failure = {'failure_category': 'rate_limited' if receipt.get('http_status') == 429 else 'ambiguous_external',
                       'reason_code': 'pinned_request_reconciliation_required'}
        when = clock()
        if not store.complete_claimed_action(run_id, attempt, marker, succeeded=verified, result=checkpoint,
                final_context=checkpoint if verified else None, **failure, now=when):
            raise RuntimeError('Result not checkpointed under its lease. Preserve the journal for reconciliation.')
        if not verified and not store.finish_claim(run_id, attempt, status='human_action_required',
                human_required=True, context=checkpoint, **failure, now=when):
            raise RuntimeError('Failed request requires separate reconciliation')
        return {'state': 'COMPLETED' if verified else 'HUMAN_ACTION_REQUIRED',
                'run_id': run_id, 'checkpoint': checkpoint}
