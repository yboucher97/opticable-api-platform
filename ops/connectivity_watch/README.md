# OptiBrain connection probe (offline regression utility)

**Do not install another VPS watchdog or timer.** NEW already runs the resource sampler, operations monitor, required provider-read registry, native platform collection and same-user OAuth refresh. This script remains an offline regression/manual diagnostic utility. It does not persist credentials or response bodies and has no notification transport.

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

**Current integration:** existing `optibrain-resource-sample.timer` invokes the reviewed queue sampler and local readiness projection. `optibrain-operations.timer` retains the existing bounded alert route. `optibrain-credential-refresh.timer` owns renewable authentication; this script must not create another token cache or refresh flow. The example auth variable now matches `SITE_WORKFLOW_API_KEY`; optional user-token provider examples are not GitHub App or Zoho refresh configuration.

HTTP 200 here proves transport only. The production readiness reader validates semantic states, timestamps and queue evidence; native marketing collection validates actual reporting data and rejects Windsor placeholders. Do not replace those checks with this utility or treat it as write authority.

CLI integration regressions exercise `main -> probe_with_retry -> probe -> HTTP boundary`, including transient recovery, exhaustion, no auth retry and zero retries. No scheduled collector, state directory or alert stream is deployed by this PR.
