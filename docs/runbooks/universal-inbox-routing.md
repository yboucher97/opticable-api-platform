# Universal Inbox + Next Action — rollout

Date: 2026-09-26

## Safety contract
- Additive rollout only. Existing aliases, folders, workflows and historical mail stay intact.
- Never delete mail as part of routing.
- Zoho Books is observation/read-only. No Books create/update/delete operations.
- `quotes@opticable.ca` and `soumissions@opticable.ca` intentionally remain separate public EN/FR addresses but converge on one sales pipeline.
- Legacy `@opti-plex.ca` aliases remain enabled during migration.

## Existing folders created safely
- `/Opticable/Partners/Partner Jobs`
- `/Opticable/Admin and Providers`
- `/Business Records/Bills and Receipts/Supplier Invoices`
- `/Business Records/Legacy Opti-Plex Migration`

## Manual prerequisites
Two new aliases should be created in Zoho Mail Admin Console for the existing Yan-Erik/Opticable mailbox:
1. `partners@opticable.ca`
2. `factures@opticable.ca`

Do not remove or rename any current aliases.

After aliases exist, confirm each by sending one test email from an external address. Do not create destructive move/delete rules yet; OptiBrain should classify first and routing can be enabled progressively.

## Intended behavior
- `quotes@` and `soumissions@` -> Lead/Deal intake and `/Opticable/Leads and Quotes`.
- `support@` -> customer/service identification and `/Opticable/Support and Service`.
- `installations@` -> active Service/Installation coordination and `/Opticable/Clients and Projects`.
- `partners@` -> partner/subcontract opportunity extraction and `/Opticable/Partners/Partner Jobs`.
- `admin@` -> provider/SaaS/admin correspondence and `/Opticable/Admin and Providers`.
- `factures@` -> supplier invoice observation and `/Business Records/Bills and Receipts/Supplier Invoices`; never write to Books.
- Any message using `@opti-plex.ca` should continue to deliver normally while creating a migration candidate toward `admin@opticable.ca` where the address belongs to a provider account.

## Deployment procedure
1. Pull the reviewed branch or merge its PR into main.
2. On OptiBrain VPS: `cd /opt/opticable-api-platform && git pull --ff-only`.
3. Run the repository's existing tests/smoke tests before restarting anything.
4. Restart only the workflow API if required by the existing deployment mechanism.
5. Verify `/health` remains OK.
6. Initially run routing in classify/observe mode; compare decisions against real mail.
7. Enable automatic filing/task creation only after classification checks pass.

## Rollback
Because this phase adds configuration and folders without deleting or moving historical data, rollback is to disable the new routing configuration/workflow and revert its commit. Keep the folders and aliases in place; they are harmless and preserve received mail.
