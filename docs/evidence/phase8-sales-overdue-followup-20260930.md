# Controlled Lead overdue follow-up read proof

Task: `phase8-sales-gap-independent`. Branch base: production `d2ca75d588665112d1d62329abfda23dd92d533f`.

On 2026-09-30 UTC, `ops/phase8/read_only_followup_probe.py` made one exact-ID Zoho CRM Lead GET for the controlled Lead `5062683000007880001`, then evaluated the returned snapshot locally at a clock one day after its existing follow-up deadline. It issued no CRM write, send, event, or approval. The projected clock is a simulation; the Lead was not actually overdue at observation time.

Command used, with credentials loaded privately from the existing service environment and never printed:

```sh
sudo bash -c 'set -a; . /etc/opticable-workflow-api.env; exec /opt/opticable-api-platform/apps/workflow-api/.venv/bin/python -I /var/tmp/optibrain-phase8-sales-overdue/ops/phase8/read_only_followup_probe.py'
```

Exact sanitized output:

```json
{"deadline_rewritten": false, "decision_followup_at": "2026-10-01T21:00:00+00:00", "lead_id": "5062683000007880001", "next_action": "draft_reply", "priority": "high", "projected_at": "2026-10-02T21:00:00+00:00", "provider_business_writes": 0, "provider_followup_at": "2026-10-01T21:00:00+00:00", "provider_reads": 1, "scenario": "one_live_controlled_lead_get_projected_one_day_past_due", "source_version": "2026-09-29T20:50:31+00:00"}
```

The old decision logic would compute a new future business deadline when the existing deadline was overdue. The branch preserves the provider-owned deadline so the neglected follow-up remains visible and `phase6_lead_patch` has no `Next_Followup_At` write for this case. The focused test also proves an advisory AI `wait` hint cannot suppress action on an overdue deadline; that specific hint was tested locally, not in the live GET probe.

Focused regression: `PYTHONPATH=apps/workflow-api /opt/opticable-api-platform/apps/workflow-api/.venv/bin/python -m unittest discover -s apps/workflow-api/tests -p test_phase6_sales_decision.py` passed: 14 tests, 0 failures.
