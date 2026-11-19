OptiBrain bounded owner-acceptance controller (prepare only)

This is a single foreground test controller, not an installed daemon, scheduler,
database, application runtime or general-purpose action system. The installed A2
runtime is unchanged. Only a separately sealed Test D package may launch it, after
new exact owner approval and a fresh READY recorded within ten minutes. Earlier
B/C grants cannot authorize D. No controller command restarts a service.

Verified Test C failure
The read-only app GET timed out reading its HTTPS response with urllib's seven-
second socket timeout. No HTTP error status, rate-limit evidence or provider
outage was established. urllib created a new connection with Connection: close;
a stale connection pool is unsupported by the evidence. The runner had no read
retry and coupled mandatory security reads with optional monitoring. Its finally
restored the original settings, but the propagated timeout skipped normal post-
test checks. Three sequential follow-up GETs succeeded in 0.64-0.75 seconds;
these later successes do not prove the original underlying network cause.

Controller bounds and separation
Use existing curl with an eight-second total-transfer cap, a connect cap of three
seconds, subprocess kill budget of transfer+0.5 seconds, verified TLS, no redirects
and no curl retries. Credentials/bodies travel via stdin, never argv or logs.
GET only: at most two attempts, >=1-second backoff, honor numeric Retry-After
within the enclosing budget. Invalid/auth/security failures never retry. A read
that fails, is cancelled, is late, malformed or lacks success=true is not proof.
Each required app+policy read batch has a forty-second budget. Required reads run
at sixty-second intervals after each completed batch; ninety-second verification
staleness aborts. Optional local tunnel counters use a separate read-only thread
at fifteen-second intervals and cannot starve required checks. Workers may never
write provider settings. Foreground restoration cancels but never joins workers.

Mutation and rollback
Root-only sealed files, exact endpoint/body allowlists, full semantic readbacks,
a common nonblocking application lock, durable single-use ledger and write-ahead
mutation intents prevent overlapping or duplicate execution. Reload the ledger
AFTER obtaining the lock. PUT/POST are never automatically retried. Record every
acknowledged status and classified failure without cookie/token/header values.
Unknown write acknowledgement is reconciled through GET, never assumed successful.
An interrupted RESTORE PUT may be reissued once only after an independent GET
proves a reviewed known state still requires that exact idempotent restoration.
An ambiguous app-token revocation is never replayed; report its unknown outcome.

Begin with binding ON. Shorten only the existing non-reusable owner policy to
15m, verify, revoke only this app's old tokens once, and wait >=60 seconds after
acknowledgement. Persist the monotonic deadline and boot identity before the
single app binding-OFF/15m PUT. Independent readback and unchanged guards must
pass before inviting the owner. Immediately print OWNER_TEST_OPEN; the operator
must notify the live owner at once. No synthetic result is owner acceptance.

Normal restoration dispatch is at elapsed 1379 seconds (one-second margin before
minute 23), or earlier on failure/owner completion. The hard bound is 1500 seconds
from pre-PUT intent, conservatively including disable latency. Restore binding ON
and application 1h first; GET-verify while the owner policy remains short. Restore
the owner policy 1h, verify the full exact original state, revoke this app's test
tokens once, and independently GET-verify again. Restoration network work has a
110-second budget within the remaining hard deadline. Run final independent
configuration, integrity and core checks even after a safely restored test error.

Operator recovery
Do not kill the process or reboot intentionally while the test is open. SIGINT,
SIGTERM and SIGHUP request restoration. A root owner-stop.json marker requests
early restoration without waiting for the deadline. If the foreground process is
interrupted, rerun only the sealed runner --recover with the SAME D authorization
receipt. It acquires the same lock, reads durable state and restores only; it does
not reopen the test or repeat a known/ambiguous revocation. Unknown configuration
is not overwritten. Preserve ledger/logs and escalate an unverifiable restoration.

No local program can guarantee provider acceptance during Cloudflare outage,
host loss, SIGKILL or storage failure. Recovery records a missed/unverifiable time
bound honestly and never claims restored without required readbacks/revocation
acknowledgement. No new scheduler or permanent weaker configuration is created.

Verification
Run python -B -m unittest discover -s ops/business_autopilot -p 'test_*.py' -v.
Synthetic tests inject read timeout, 429/Retry-After, authentication/API errors,
network failure, drift, blocked optional/required reads, stale verification,
interrupted writes/revocations, early completion, deadline and overlapping calls.
A real slow loopback fixture tests curl's total-transfer bound without credentials.
The sealed runner defaults to read-only preflight; execution requires new approval
and READY. Never use the preparation instruction itself as execution approval.

Security tradeoff and owner test
Binding OFF temporarily removes stolen-bearer replay binding. Fifteen-minute
tokens, exact Google owner policy, JWT checks, HTTPS, origin sessions and CSRF
remain required but do not replace binding. Existing Access logout may end the
owner's sessions across other Access applications/global Access SSO; it does not
log out the Google account. Marketing/consent cookies must remain continuous.
No cookie values, tokens, screenshots or HARs are collected. Owner-reported
browser acceptance and sanitized origin/edge evidence are recorded separately.
