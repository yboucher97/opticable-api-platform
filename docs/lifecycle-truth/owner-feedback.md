# Owner current-state correction

An owner correction is a local business assertion with provenance, not a company-specific exception or provider edit.

1. The authenticated owner selects an exact current priority/proposal version and asserts a business event such as `QUOTE_SENT`, `RESPONSE_SENT` or `DELIVERABLE_COMPLETED`.
2. `ManagerStore.correct_fact` verifies the exact revision, commercial target, bounded actor and explicit reason code.
3. It appends `OWNER_VERIFIED_FACT` to the existing `manager_events` journal, including actor, reviewed target/version, assertion/source time and context. Actual occurrence time remains unknown unless independently supplied as a structured source fact.
4. The shared engine recomputes current state. Completed quote/reply work is suppressed or replaced with a justified current verification.
5. Manager's next read reflects the correction; obsolete Sales previews cease to be current. Source evidence, canonical old records and historical morning snapshots remain intact.
6. Later provider events can confirm or supersede the assertion. An unknown send time cannot overrule an observed reply as if it proved the reply answered.

The JSON route is `POST /v1/operator/manager/correction`, with verified existing owner authentication, same-origin protection and a 4 KiB bound:

```json
{
  "kind": "PRIORITY",
  "target": "<exact current priority ID>",
  "version": "<exact current payload hash>",
  "event_type": "QUOTE_SENT",
  "reason_code": "DERIVED_ACTION_PERSISTED"
}
```

Supported reason codes: `MISSING_EVENT`, `BAD_SOURCE_PRECEDENCE`, `STALE_CACHE`, `FAILED_IDENTITY_LINK`, `MISSING_REPLY_DETECTION`, `DERIVED_ACTION_PERSISTED`, `OWNER_CURRENT_STATE`. They preserve the reason for the correction explicitly; no model silently learns or rewrites provider data.

Noveco's supplied correction was represented as facts on the three identified native estimates in [the audit](current-evidence.json), then recorded in the isolated replay journal. It was **not** written to the production journal: this candidate was not deployed and runtime/provider data remained read-only. The generic authenticated flow was integration-tested, including immediate projection, wrong revision, authentication and same-origin rejection.

Normal higher/lower/wait/reject preferences remain separate from verified business facts. A preference cannot prove a send, payment or acceptance. Neither feedback path grants provider execution or renews authority.
