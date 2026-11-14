Business Autopilot V1.1 extends V1; no second portal, timer or database.

The same authenticated loopback preview now renders every registered artifact,
metadata, hashes, source dates, costs, tests and editorial review history.
Basic owner identity is checked on every request. Sessions are server-issued,
HttpOnly/SameSite,20minutes maximum,rotated on refresh and bounded by the existing
owner credential expiry. CSRF,Origin,Host,body,request-id and exact-hash checks
are enforced on the server. Client actors,expiry,scope and grants are rejected.
Approvals last at most2hours within the primary credential window. Rejection
and revision requests revoke editorial acceptance. All decisions use existing
append-only ActionEvidence tables and their hash chain.

Approve draft means editorial acceptance of that exact artifact/channel/language;
it never authorizes spending,publication,sending or deployment. Those transports
are absent. Existing production owner approval and guarded release controls remain
mandatory. The localhost fixture is not a registered hosted production deployment.

The same bounded worker reads existing source snapshots,current cached CRM inventory
and retained form receipts. It produces a funnel report separating traffic,inquiries,
qualification,quotes,won deals and recognized revenue. Unknowns remain unknown.
The daily/evidence/runtime/feedback receipt key does not depend on its own new assets,
preventing self-triggering work. New variants are selected from observed camera/WiFi
intent and owner-prioritized AI gaps,then deduplicated by content. Two new tasks per
cycle; no paid model/media calls. Current recipes include substantive bilingual AI
human-review articles,camera scope posts and WiFi symptom posts. Unsupported claims,
customer testimonials,reviews,unknown media rights and repetitive content are rejected.
Supported owner feedback makes a paired revision; unfamiliar feedback remains visible
for clarification and does not block other eligible tasks. Original revisions stay.
ManagerStore receipts expose actual completed counters for daily/weekly windows.

Development-only API changes add validated obq_ inquiry IDs to the existing native
notification parser and an exact-ID read-only funnel join. The website candidate
captures an attempt ID only with existing measurement consent,retains it across
reload,replaces it on explicit new inquiry,and passes it from captured form context
to the existing acknowledged generate_lead event. Names,email similarity and visitor
cookies cannot prove a CRM relationship. A UTM campaign ID is not a verified native
Ads campaign without account/provider readback. No historic data is rewritten.
The API parser must precede a future separately approved tracking-site release;
new CRM field/binding also remains unapproved. PR13's camera tool remains separate.

Only the artifact/review runtime is eligible for this task's existing internal-work
authorization. Do not install the development application's parser or lineage module,
merge application dependencies,or deploy website tracking without separate approval.
Runtime upgrade checkpoints every previous byte and preserves the43original artifacts,
the current owner credential identity/expiry,and the existing deployment pins.
Rollback restores exact V1 runtime and previous private preview only; no DB restore,
API restart,evidence purge or permission change. Review audit/history is retained.
