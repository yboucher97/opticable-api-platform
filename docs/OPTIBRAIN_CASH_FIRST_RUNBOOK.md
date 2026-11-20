# Cash-first preparation on the NEW VPS

This candidate adds a private, rebuildable revenue brief to the existing business observer. It grants no execution authority and is not a production installation. The source starts from installed A2 commit `6616ac41ab875057907591abd808e8241be3747b`; existing dependency PRs remain unmerged.

The current owner priority is collections, accepted work, quotation conversion, genuine intake and existing service retention. Dashboard authentication work is deferred. Do not investigate or change Cloudflare, Google authentication, tracking, DNS or public routing under this task.

## Inputs and definitions

Reuse `observation_runtime.observe` and its existing bounded hourly native collection. No additional provider requests, database, timer, notification or endpoint are introduced. Read the existing intake receipt ledger in SQLite read-only/query-only mode. Never initialize a missing ledger from the reporting path.

`revenue_brief.brief` accepts the native snapshot/collection envelope and optional private review evidence. Source timestamps, completeness and customer/version checks control current financial totals. A failed, stale or missing collection is unknown, not zero. The private review expires after 30 hours; financial annotations require exact native source versions. No response is inferred absent from a bounded search.

Overdue collections use current positive invoice balances, grouped by currency. Booked payments, invoice balances, quote face values, bank settlement and cash attributable to OptiBrain are separate measures. Date-only Books fields remain dates; timestamp boundaries use America/Toronto. Converted historical leads are retained outside active pipeline. TEST identity and native descendants remain excluded, including synthetic Closed Won records. Contact classification never authorizes financial attribution.

Potential duplicate CRM identities are reversible presentation flags. A shared mailbox alone does not establish duplicate people. Matching names, amounts or dates never establishes a financial Deal or an invoice duplicate. Conflicting native estimate parents or recurring customer identity withhold attribution. Unknown quote alternatives or additive scopes are not summed.

Drafts require exact native source IDs. Stable intent/source hashes reuse one draft; exact body hashes preserve approval scope. Paid, changed-version or stale invoice data suppress collection drafts. Language variants are alternatives. Existing immutable customer proposals are reused where sufficient. No provider draft record, customer task or send is created by a projection.

## Private output and use

After a separately approved source installation, the existing observer replaces only `/var/lib/optibrain/lifecycle/cash-first-latest.json` (root, mode 0600). Optional `/var/lib/optibrain/lifecycle/cash-first-review.json` must be root-owned validated input. It is not an execution grant. No private record is added to public readiness output.

Before installation, the CLI runs entirely from an isolated source candidate:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=apps/workflow-api \
  /opt/opticable-api-platform/apps/workflow-api/.venv/bin/python \
  -m workflow.automation.revenue_brief --snapshot PRIVATE_OBSERVATION.json \
  --review PRIVATE_REVIEW.json --format json
```

`--format md` emits a text brief; `--forms-db EXISTING_LEDGER` adds the existing read-only receipt projection. Keep files containing customer details owner-private. The current home text report and matching JSON are prepared independently of the dashboard. Do not install another cron or notification to consume them.

## Validation and recovery

Run the focused revenue, finance-link, recurring, observer, attribution, business-intelligence and form-receipt tests, then the full API suite and existing business-autopilot regression suite. Recovery capsule tests require a committed clean source tree; refusal of uncommitted source is expected protection, not a reason to weaken the test. Fixtures use synthetic identities only.

Record the exact commit, changed-file SHA256 manifest, input hashes, test logs and production preservation readbacks in the existing task evidence directory. The private report records current collection/source coverage and limitations. Preserve all existing flags/settings, artifact hashes, packages, journal prefixes, backups and the OLD VPS fence.

No installation or rollback was executed for this candidate. A future source-only rollback restores only verified previous application source/receipt through the existing authorized recovery mechanism. Never restore an older business database, journal, receipt ledger, customer file or backup generation. Do not stop the command-center or its Tunnel for a reporting-only candidate. Stop on source/config drift; production installation requires its own exact scope and approval.

## Errors and limitations

Connector result limits must be obeyed; rejected arguments are not a provider outage or a successful empty search. Zoho Mail body IDs can be unsafe JSON numbers; verify the exact string metadata ID against the requested ID. Do not copy rounded body IDs into business links. Project template tasks and old waiting-installation labels require current customer evidence before becoming sales priorities. Unknown costs, bank settlement, acquisition lineage and customer authority remain unknown.
