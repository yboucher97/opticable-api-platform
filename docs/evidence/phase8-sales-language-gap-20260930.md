# Controlled AI-site Lead language qualification

Task: `phase8-real-sales-workflow`. Branch base: completed overdue follow-up fix `91cd6d86c56f634195e75bc414c07e115544dfbe`; production remains `d2ca75d588665112d1d62329abfda23dd92d533f`.

The existing controlled AI-site intake evidence at `/var/lib/optibrain/phase7/20260929-phase7-first-canary-sourcepin-200300/CANARY3_AND_INTAKE_RESULT.md` established one Lead, exact email identity, and an observed sales draft with `drafted=false,reason=observe`. The draft writer already requires a reviewed `fr` or `en` language. The sales decision previously reported no language gap despite `language=unknown`, so an operator could see `draft_reply` without the missing prerequisite. The branch adds bounded `preferred_language` missing-information metadata for active email-contactable Leads with unknown language and carries that metadata into the canary review plan. It does not select a language, authorize a draft, send mail, or change CRM fields.

The probe made exactly one controlled Lead GET and one exact-email search GET through `hydrate_unique_lead`. Both were guarded by `ReadOnlyControlledClient`; the exact-email result was unique. The process loaded existing credentials privately from the service environment. No request or response containing customer fields was persisted or printed.

Command:

```sh
sudo bash -c 'set -a; . /etc/opticable-workflow-api.env; exec /opt/opticable-api-platform/apps/workflow-api/.venv/bin/python -I /var/tmp/optibrain-phase8-sales-language/ops/phase8/read_only_language_gap_probe.py'
```

Exact sanitized output:

```json
{"dedupe_status": "unique_lead_email_match", "identity_hash": "d4c5ccb798742af6d28ed6802ceadd1e61f64e023736f35184da9486a007d494", "language": "unknown", "lead_id": "5062683000007880001", "missing_information": ["service_type", "preferred_language"], "next_action": "draft_reply", "outbound_eligible": false, "plan_hash": "e22dfec41ffe12adcd52c6e818c8304bcae1ea07cfb01937ad69bdb65f17e228", "provider_business_writes": 0, "provider_reads": 2, "scenario": "controlled_ai_site_lead_missing_language_qualification", "source_version": "2026-09-29T20:50:31+00:00"}
```

Focused tests: `/opt/opticable-api-platform/apps/workflow-api/.venv/bin/python -m unittest tests.test_phase6_sales_decision tests.test_phase7_canary -v` from `apps/workflow-api` passed 28 tests. They cover the explicit gap, opt-out boundary, hashed decision integrity, canary review visibility, and unknown-language outbound refusal. `git diff --check` passed.

An initial local probe invocation had no service environment and stopped before any provider request with `Local Zoho OAuth is not configured and connected.` The second invocation used the existing service environment and was the only live provider probe.
