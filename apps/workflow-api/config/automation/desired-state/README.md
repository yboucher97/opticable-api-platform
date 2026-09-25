# Desired State

This directory is the Git-versioned source of truth for Opticable platform configuration.

A desired-state document declares **what should exist**, not a sequence of UI clicks.

The reconciliation engine performs:

1. discovery through a provider adapter
2. plan generation
3. dependency ordering
4. risk classification
5. controlled apply
6. verification on the next plan
7. drift detection when actual state diverges later

Provider adapters are intentionally separate from the reconciliation core.

Typical resources:

- Zoho CRM fields, layouts, workflows, functions, buttons, modules
- Zoho Creator app data/meta resources
- Google Tag Manager workspaces/tags/triggers/variables
- GA4 key events/custom dimensions/data streams
- Cloudflare DNS/Workers/KV/Queues/cron configuration
- Forms/Flow browser-managed configuration when no API exists

Example:

```yaml
api_version: opticable.io/v1alpha1
kind: DesiredState
name: lead-platform
version: 1
resources:
  - id: zoho.crm.field.leads.service_interest
    provider: zoho_crm
    kind: field
    name: Service Interest
    desired:
      module: Leads
      field_label: Service Interest
      data_type: picklist
      pick_list_values:
        - Cabling
        - Wi-Fi
        - Cameras
        - Access Control
        - AI Loss Prevention

  - id: zoho.crm.workflow.lead-intake
    provider: zoho_crm
    kind: workflow
    name: Lead Intake
    depends_on:
      - zoho.crm.field.leads.service_interest
    desired:
      module: Leads
      trigger: create
```

Destructive changes never apply unless the caller explicitly enables destructive changes.
High-risk changes also require a separate explicit apply flag.

Browser-only resources are represented in the same desired-state documents but use a browser adapter with deterministic pre/post verification.
