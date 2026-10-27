# OptiBrain independent heartbeat guard — staging only

The `heartbeat_guard.py` module is a **read-only** evaluator of independently collected successful job-completion evidence. This branch does **not** contain a live collector, independent scheduler, persistent heartbeat store or notification route. It does not create or authorize provider actions. **Do not deploy/merge until the existing last-good, prechange, postchange and restore gates are verified.**

**Trust model.** Supply two different sources of evidence:
1. Owner-reviewed, immutable **roster** of every expected job, including deliberately disabled jobs, each named scheduler and maximum permitted silence. Never let the observed service redefine its own obligations.
2. Fresh **snapshot** independently collected outside the watched service's failure domain. `last_success_utc` must indicate actual *end-to-end successful completion* (not Cron dispatch, process start, HTTP 200 or enqueue).

JSON schema examples — **fixtures only, not a production job inventory**:

Roster:
```json
{"schema":1,"jobs":[{"job_id":"cloudflare-cron","scheduler":"cloudflare","expected":"active","max_silence_seconds":1800},{"job_id":"customer-mail","scheduler":"systemd","expected":"disabled_intentionally"}]}
```

Snapshot:
```json
{"schema":1,"observed_at_utc":"2026-10-27T05:14:00Z","jobs":[{"job_id":"cloudflare-cron","scheduler":"cloudflare","last_success_utc":"2026-10-27T05:10:00Z"},{"job_id":"customer-mail","scheduler":"systemd","last_success_utc":null}]}
```

Local offline test: `cd ops/observability && python3 -m unittest -v test_heartbeat_guard.py`.

Only once safely deployed on an isolated monitor: `python3 heartbeat_guard.py APPROVED_ROSTER.json COLLECTOR_SNAPSHOT.json`. Exit `0`=healthy, `1`=overdue/unknown, `2`=unverifiable, including missing jobs. Do not put secrets, recipient addresses or customer records in input. `--now-utc` is for fixtures only.

Graduation requirements: (a) actual isolated restore of last-good application state; (b) fresh separate versioned encrypted prechange backup and independent restore (databases, root policies, claims, off-host manifests); (c) reviewed real job inventory, one authoritative scheduler and intentional OFF states; (d) durable heartbeat **even for empty cron slots**, plus actual downstream completion; (e) separately hosted collector and observer with independent timer, tested alert routing and no effect writers; (f) tests for missing heartbeat, stale evidence, network outage, queue and backup failure, intentional disable, duplicate concurrent scheduler and expiry; (g) exact-SHA reviewed release and separate postchange backup and independent restore. No silent renewal of November 1 customer/internal authority; leave Books writes and customer email disabled outside authorized scope.
