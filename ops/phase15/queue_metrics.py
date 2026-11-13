#!/usr/bin/env python3
"""GET-only Cloudflare backlog sampler. No queue bodies or credential values emitted."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile
import time
import urllib.error
import urllib.request

NAMES = ('opticable-business-events', 'opticable-business-events-dlq')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_json(path, token, *, opener=None, sleep=time.sleep):
    """Fixed-origin GET only; two attempts, bounded responses, no secret errors."""
    if not re.fullmatch(r'/accounts/[0-9a-f]{32}/queues(?:/[0-9a-f]{32}/metrics)?', path):
        raise ValueError('queue_read_path_refused')
    opener = opener or urllib.request.build_opener(NoRedirect)
    for attempt in range(2):
        req = urllib.request.Request('https://api.cloudflare.com/client/v4' + path,
                                     headers={'Authorization': 'Bearer ' + token}, method='GET')
        try:
            with opener.open(req, timeout=5) as response:
                if response.status != 200:
                    raise ValueError('queue_read_status_unexpected')
                raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ValueError('queue_read_response_too_large')
            value = json.loads(raw)
            if not isinstance(value, dict) or value.get('success') is not True:
                raise ValueError('metrics_read_failed')
            return value
        except urllib.error.HTTPError as exc:
            retry = exc.code in (408, 429, 500, 502, 503, 504)
            # A longer provider delay means defer to the next existing timer.
            raw_delay = exc.headers.get('Retry-After', '1') if exc.headers else '1'
            try:
                delay = float(raw_delay)
            except (ValueError, TypeError):
                # HTTP-date or unknown format: do not retry before provider permits.
                delay = float('inf')
            exc.close()
            if not retry or attempt or not 0 <= delay <= 2:
                raise ValueError('queue_read_http_' + str(exc.code)) from None
            sleep(max(1, delay))
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt:
                raise ValueError('queue_read_unreachable') from None
            sleep(1)


def sample(account, token, request):
    if not re.fullmatch(r'[0-9a-f]{32}', account or '') or not token:
        raise ValueError('configuration_unavailable')
    prefix = '/accounts/' + account + '/queues'
    listing = request(prefix)
    matches = [q for q in listing['result'] if q.get('queue_name') in NAMES]
    selected = {q['queue_name']: q['queue_id'] for q in matches}
    if (len(matches) != len(NAMES) or set(selected) != set(NAMES)
            or len(set(selected.values())) != len(NAMES)
            or any(not re.fullmatch(r'[0-9a-f]{32}', q) for q in selected.values())):
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
            return request_json(path, token)
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
