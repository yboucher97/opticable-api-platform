#!/usr/bin/env python3
"""Non-destructive connection status probe; no tokens or response bodies in output."""
import argparse
import hashlib
import ipaddress
import time
from urllib.parse import urlsplit
import datetime as dt
import json
import os
from pathlib import Path
import tempfile
import urllib.error
import urllib.request

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

OPENER = urllib.request.build_opener(NoRedirect)
UTC = dt.timezone.utc

def age_hours(value, now):
    try:
        return (now - dt.datetime.fromisoformat(value.replace("Z", "+00:00"))).total_seconds() / 3600
    except (ValueError, AttributeError, TypeError):
        return None

def valid_url(item):
    try:
        u = urlsplit(item["url"])
        if u.username or u.password or u.query or u.fragment:
            return False
        if u.scheme == "https":
            return bool(u.hostname)
        if u.scheme == "http" and item.get("allow_http_localhost"):
            return ipaddress.ip_address(u.hostname).is_loopback
    except (ValueError, TypeError, KeyError):
        return False
    return False

def probe(item):
    name, url = item["name"], item["url"]
    if not valid_url(item):
        return {"name": name, "status": "CONFIG_ERROR"}
    token = os.environ.get(item["auth_env"]) if item.get("auth_env") else None
    if item.get("auth_env") and not token:
        return {"name": name, "status": "MISSING_CREDENTIAL"}
    headers = {"User-Agent": "OptiBrain-Connection-Watch/1"}
    if token:
        header_name = item.get("auth_header", "Authorization")
        if header_name not in ("Authorization", "X-API-Key"):
            return {"name": name, "status": "CONFIG_ERROR"}
        headers[header_name] = f'{item.get("auth_scheme", "Bearer")} {token}' if header_name == "Authorization" else token
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with OPENER.open(req, timeout=min(max(float(item.get("timeout", 10)), 1), 30)) as response:
            code = response.status
    except urllib.error.HTTPError as e:
        code = e.code
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        return {"name": name, "status": "UNREACHABLE", "reason": type(e).__name__}
    if code == 401:
        status = "UNAUTHORIZED"
    elif code == 403:
        status = "FORBIDDEN"
    elif code == 429:
        status = "RATE_LIMITED"
    elif code in (301, 302, 303, 307, 308):
        status = "REDIRECT_BLOCKED"
    elif code >= 500:
        status = "SERVER_ERROR"
    elif code >= 400:
        status = "HTTP_ERROR"
    else:
        status = "HEALTHY"
    return {"name": name, "status": status, "http_status": code}

def probe_with_retry(item):
    retries = min(max(int(item.get("retries", 1)), 0), 2)
    for attempt in range(retries + 1):
        result = probe(item)
        if result["status"] not in ("UNREACHABLE", "SERVER_ERROR", "RATE_LIMITED"):
            return result
        if attempt < retries:
            time.sleep(min(2 ** attempt, 2))
    return result

def event_key(name, status):
    return hashlib.sha256((name + "|" + status).encode()).hexdigest()[:16]

def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".conn-check-")
    try:
        with os.fdopen(fd, "w") as out:
            json.dump(data, out, indent=2)
            out.write("\n")
        os.chmod(temp, 0o600)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.remove(temp)

def main():
    ap = argparse.ArgumentParser()
    for opt in ("config", "state", "output"):
        ap.add_argument("--" + opt, required=True, type=Path)
    args = ap.parse_args()
    config = json.loads(args.config.read_text())
    checks = config.get("checks", [])
    if not isinstance(checks, list) or not checks:
        ap.error("nonempty checks list required")
    names = [x["name"] for x in checks]
    if len(names) != len(set(names)):
        ap.error("duplicate check names")
    previous = json.loads(args.state.read_text()) if args.state.exists() else {}
    now = dt.datetime.now(UTC)
    results, history, events = [], {}, []
    for item in checks:
        name = item["name"]
        old = previous.get(name, {})
        result = probe(item)
        last_success = now.isoformat() if result["status"] == "HEALTHY" else old.get("last_success")
        checked_age = age_hours(old.get("last_checked"), now)
        success_age = age_hours(last_success, now)
        use_age = age_hours(old.get("last_use"), now)
        first_seen = old.get("first_seen") or now.isoformat()
        first_seen_age = age_hours(first_seen, now)
        result.update(last_checked=now.isoformat(), last_success=last_success,
            check_gap_over_24h=checked_age is not None and checked_age > 24,
            no_success_over_72h=(success_age if success_age is not None else first_seen_age) is not None and (success_age if success_age is not None else first_seen_age) > 72,
            unused_over_30d=use_age is not None and use_age > 720,
            never_verified=last_success is None)
        status = result["status"]
        stale = any(result[key] for key in ("check_gap_over_24h", "no_success_over_72h", "unused_over_30d"))
        event_status = status if status != "HEALTHY" else ("STALE" if stale else "HEALTHY")
        prior_event_status = old.get("event_status")
        if event_status != prior_event_status and (event_status != "HEALTHY" or prior_event_status not in (None, "HEALTHY")):
            events.append({"name": name, "event": "RECOVERED" if event_status == "HEALTHY" else "ATTENTION", "status": event_status, "key": event_key(name, event_status)})
        history[name] = {"last_checked": now.isoformat(), "last_success": last_success, "status": status, "event_status": event_status, "first_seen": first_seen}
        if old.get("last_use"):
            history[name]["last_use"] = old["last_use"]
        results.append(result)
    report = {"timestamp": now.isoformat(), "checks": results, "events": events,
              "summary": {"healthy": sum(x["status"] == "HEALTHY" for x in results), "total": len(results)}}
    write_json(args.state, history)
    write_json(args.output, report)
    print(json.dumps(report, separators=(",", ":")))
    return 0 if checks and all(x["status"] == "HEALTHY" for x in results) else 1

if __name__ == "__main__":
    raise SystemExit(main())
