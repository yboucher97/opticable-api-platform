# OptiBrain connection watchdog (development candidate)

**No production installation, credential changes, business sends, or migrations.** This standalone Python 3.10+ standard-library script performs GET-only probes of explicitly configured endpoints. It does not persist credentials or response bodies.

Example `/etc/optibrain/connectivity.json`:

```json
{"checks":[
  {"name":"optibrain-local","url":"http://127.0.0.1:8100/health","allow_http_localhost":true},
  {"name":"external-api","url":"https://example.com/api/me","auth_env":"EXTERNAL_API_READ_TOKEN"}
]}
```

Run:

```bash
python3 ops/connectivity_watch/check.py --config /etc/optibrain/connectivity.json --state /var/lib/optibrain/connectivity-state.json --output /var/lib/optibrain/connectivity-last.json
```

The authenticated environment variables should be supplied through a restricted secrets facility. Never embed credentials in URL query strings or config. Use a dedicated unprivileged service user. No HTTP redirects are followed, protecting authorization headers from cross-host forwarding. Exit 0 means every configured probe succeeded; exit 1 means a failure or empty inventory.

**Freshness:** More than 24 hours since previous check, more than 72 hours since last success, or more than 30 days since separately recorded actual credential use are flagged. Last use is only reported when a separate trusted audit source populates `last_use`; it is not inferred from the probe itself. A fresh successful check cannot prove all API permission scopes work. Different authorized GET endpoints may be required per service.

**Before VPS installation:** inventory target endpoints, inspect the currently active production and rollback states, verify current approval gates, add hermetic tests and schedule via a restricted service timer. Production installation or privilege changes need an explicit rollout approval. This branch alone does not change the VPS or enable business operations.
