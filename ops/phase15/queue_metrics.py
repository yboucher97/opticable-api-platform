#!/usr/bin/env python3
"""GET-only Cloudflare backlog sampler. No queue bodies or credential values emitted."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile
import urllib.request

NAMES = ('opticable-business-events', 'opticable-business-events-dlq')


def sample(account, token, request):
    if not re.fullmatch(r'[0-9a-f]{32}', account or '') or not token:
        raise ValueError('configuration_unavailable')
    prefix = '/accounts/' + account + '/queues'
    listing = request(prefix)
    selected = {q['queue_name']: q['queue_id'] for q in listing['result'] if q.get('queue_name') in NAMES}
    if set(selected) != set(NAMES) or any(not re.fullmatch(r'[0-9a-f]{32}', q) for q in selected.values()):
        raise ValueError('queue_inventory_mismatch')
    result = {}
    for name in NAMES:
        value = request(prefix + '/' + selected[name] + '/metrics')['result']
        fields = ('backlog_count', 'backlog_bytes', 'oldest_message_timestamp_ms')
        if any(type(value.get(k)) is not int or value[k] < 0 for k in fields):
            raise ValueError('metric_schema_unavailable')
        result[name] = {k: value[k] for k in fields}
    return result


def main():
    if os.geteuid() != 0:
        raise SystemExit('Root-installed sampler required')
    os.umask(0o077)
    result = dict(schema=1, captured_at=datetime.now(timezone.utc).isoformat(), status='unavailable', queues={})
    try:
        env = {}
        for line in Path('/etc/opticable-workflow-api.env').read_text().splitlines():
            key, sep, value = line.partition('=')
            if sep and key in {'CLOUDFLARE_API_TOKEN', 'CLOUDFLARE_ACCOUNT_ID'}:
                env[key] = value.strip().strip('"').strip("'")
        token = env.get('CLOUDFLARE_API_TOKEN')
        def request(path):
            req = urllib.request.Request('https://api.cloudflare.com/client/v4' + path,
                                         headers={'Authorization': 'Bearer ' + (token or '')}, method='GET')
            with urllib.request.urlopen(req, timeout=10) as response:
                value = json.load(response)
            if value.get('success') is not True:
                raise ValueError('metrics_read_failed')
            return value
        result['queues'] = sample(env.get('CLOUDFLARE_ACCOUNT_ID'), token, request)
        result['status'] = 'measured'
    except Exception as exc:
        # Provider errors may contain headers/URLs. Persist a fixed type only.
        result['error_type'] = type(exc).__name__
    target = Path('/run/optibrain-readiness')
    target.mkdir(mode=0o755, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.queue-', dir=target)
    with os.fdopen(fd, 'w') as stream:
        json.dump(result, stream, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(name, 0o644)
    os.replace(name, target / 'queue-depth.json')
    print(json.dumps({'queue_metrics': result['status'], 'provider_mutations': 0}))


if __name__ == '__main__':
    main()
