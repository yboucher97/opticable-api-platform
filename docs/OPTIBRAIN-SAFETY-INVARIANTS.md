# OptiBrain Safety & Autonomy Invariants

These rules are mandatory for every automated production mutation.

## Change transaction
1. Identify and record the current last-known-good Git SHA and runtime release.
2. Create a pre-change snapshot before any mutation.
3. Apply the smallest reversible change.
4. Validate syntax, tests, health endpoints, and critical provider connectivity.
5. On validation failure, stop and roll back to the pre-change snapshot.
6. On success, create a post-change snapshot and mark it as the new candidate known-good state.
7. Record the change, validation evidence, rollback point, and outcome in the audit/runbook log.

## Backup separation
Git history is not a complete backup. Production recovery must use independent copies for source, runtime configuration, databases/state, and secrets metadata. Secret values must never be committed to Git.

At least one backup copy must be outside the primary GitHub account/credential boundary. Backup credentials must not have write/delete access to production.

## Autonomous execution
All scheduled or event-driven jobs must be idempotent, bounded by timeouts, use retries with exponential backoff for transient failures, and send exhausted work to a recoverable dead-letter/error state rather than silently dropping it.

Health monitoring must verify both HTTP availability and critical dependency/provider state. A failed health check must not automatically deploy new code.

## Destructive and financial guardrails
Zoho Books and CRM-synced finance modules may have full OAuth scopes, but they are operationally **strictly read-only**. All Books/Books-synced POST, PUT, PATCH, and DELETE operations are blocked in the canonical gateway with no approval bypass. Other Zoho applications retain the broader autonomous gateway policy. Irreversible deletes/purges elsewhere remain audited.

Bulk deletes, destructive migrations, credential rotation, permission expansion, and irreversible external actions require an explicit safety gate and verified recovery point.

## Recovery objective
A future operator or ChatGPT session must be able to determine: what is running, what changed, the last known-good version, the pre-change version, how validation behaved, and how to restore service without reconstructing history from memory.