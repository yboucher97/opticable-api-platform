# Business Manager and continuous optimization control center

AUTHORITATIVE CURRENT. Phase37/API1.28.0 consolidates the existing operator ecosystem at `/v1/operator/manager` (HTML) and `?format=json` (schema1, `optibrain.manager`). Business, Sales, Acquisition, Recurring, Marketing Sources and System Health retain detail ownership. Today links to Manager. No new provider, proposal database, priority database, orchestrator, timer or persistent model/development worker is installed.

The manager answers what changed, current business attention, prepared work, evidence, cost, blockers, results and next decisions. Today contains at most five current HIGH priorities. Separate sections cover Sales, Acquisition, Customers, Recurring, Finance, Marketing, Website/SEO, Ads, Content, System and Owner Actions. Counts retain their populations; acknowledged native Forms inquiries differ from native CRM Leads and diagnostic TEST submissions. Missing coverage is UNKNOWN. Books remains financial truth; cost allocation and profitability remain UNKNOWN.

## Machine and owner interface

Stable top-level keys: `schema`, `type`, `scope`, `at`, `state`, `projection_at`, `today`, `sections`, `proposals`, `proposal_counts`, `priorities`, `priority_count`, `sources`, `authority`, `events`, `activity`, `brief`, `manager_records`, `data_completeness`, `efficiency`, `intake`, `forms`, `preparation`, `safety`, `navigation`. API output bounds priorities/proposals to50, events to50, Today to5, content assets to20 and domain attention to5. Counts describe canonical populations rather than display lengths. Detail links resolve existing IDs. The root projection has a1MiB ceiling. GET performs local cache/journal reads only; no provider or model request.

`q`, `domain`, `status` filters are bounded100-character inputs. Proposal search includes linked service/company/page evidence; detailed prospect/contact search stays in Acquisition/Sales. The human must authenticate through existing Cloudflare Access verification. Every response is private/no-store with escaping, frame protection and a restrictive CSP. No impersonated owner identity or execute/send/publish endpoint exists.

`POST /v1/operator/manager/feedback` accepts exact `kind` (PROPOSAL/PRIORITY), `target`, immutable `version` payload hash and `choice`, plus bounded optional `reason`, `category`, `conditions`. JSON and same-origin forms are supported;8KiB body bound, unknown/duplicate fields rejected. Proposal choices APPROVE/REJECT/REQUEST_REVISION/WAIT/NOT_RELEVANT/NEVER and priority HIGHER/LOWER/WAIT/NOT_RELEVANT/NEVER preserve feedback. Exact current preview, measurement and rollback are required for approval intent. Approval is local owner intent, **never a provider execution grant**. A changed revision cannot inherit approval. Rejection/deferral survives identical semantic evidence; NEVER survives all automatic revisions of that idea. An owner can explicitly change feedback later. Existing suppression is never altered.

## Daily operation and recovery

The existing bounded internal observer invokes Manager after independent native/domain observations. It projects source/authority state, stores changed reference events, exact native relationships, priorities in the existing OptimizationStore, bounded local editorial previews and a concise daily owner brief. At most3 changed website drafts per invocation and10 considered opportunities; no model calls or new provider reads. Same evidence reuses drafts. Existing Sales/Ads preparation budgets remain intact. Manager errors become an attention item and cannot stop or arm unrelated execution.

Durable tables live in existing `phase12-autonomy.db`: manager_events, manager_feedback, manager_links, manager_briefs, manager_learning, manager_receipts. They retain references, feedback, dated briefs/results and observed operational invocations, not raw provider duplicates. Existing optimization_records/reviews and acquisition identity/source tables remain canonical. Current eight-store recovery already backs up this DB. SQLite backup/restore retains manager state; fresh authority remains OFF regardless of restored approval intent.

The brief includes changed evidence, Sales attention, Acquisition, Customers, Marketing/SEO/Ads, review-ready proposals, source/system blockers and top3–5 priorities. Initial observations are identified as baseline, not newly occurred business. An empty day reports no new evidence without inventing work or industry news.1d/7d actual activity totals cover only retained observed invocations since Phase37; configuration or last-cycle counters never reconstruct missing historical runs. Apollo/Claude sends are never attributed to OptiBrain.

## Honest completeness and remaining work

GREEN means working known coverage; GREEN — WAITING NATURAL DATA means a functioning path lacks a natural outcome; GREEN — INTENTIONALLY OPTIONAL means the domain is deliberately unnecessary. PARTIAL and BLOCKED retain exact gaps. No completeness percentages are invented.

Website preparation currently produces actual local copy/FAQ/link/creative/repurposing drafts. Existing Phase32/33 repository previews remain independently reviewable. New manager drafts need exact website repository mapping, isolated branch/build and owner production approval before deployment. Form intelligence retains known published identities/telemetry and UNKNOWN native required-field/abandonment coverage; only verified design/mapping defects generate a local migration preview. No native Form replacement or Holo/private API is invoked. Results require execution receipt, baseline/post windows and limitations; tiny samples stay INSUFFICIENT_DATA and no causal result is claimed.

## Stop and post-Phase37 order

Stop after Phase37. No Ads activation, outreach graduation, financial write or mass publication occurs here.

1. Resolve controllable source freshness and exact reply/thread/employer/collision gaps; retain weak prospects.
2. Review selected Sales drafts, the genuine inquiry queue, imminent tender and FR camera landing/measurement previews.
3. Finish selected website/Form branch/build/provider-draft previews where a supported exact adapter is available.
4. Owner chooses a sealed Ads CREATE_PAUSED pilot; activation/spend cap/stop are separate graduation decisions.
5. Graduate a separately sealed small outreach batch with fresh suppression/current-owner checks.
6. Extend useful draft preparation coverage, then measure real qualified outcomes in matched windows.
7. Graduate only proven low-risk maintenance/execution, with original authority boundaries and receipt fencing.

Separate future graduations: Ads CREATE_PAUSED, limited outreach, website/Form publication, content publication, customer communication expansion and English automation. None is activated by Manager approval.
