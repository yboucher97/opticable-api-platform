"""Root-only, hourly native observations; never provider actions or authority."""
from datetime import datetime, timezone
from pathlib import Path
from . import lifecycle_control as lc
from .business_observation import NativeReader, collect_recurring, collect_marketing
from .recurring_lifecycle import build_recurring
from .marketing_attribution import build_marketing

ROOT = Path('/var/lib/optibrain/lifecycle')
DISPLAY = Path('/run/optibrain-readiness/recurring.json')


def observe(engine, *, now=None):
    from .real_internal import atomic
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None: raise ValueError('Aware observation time required')
    saved = ROOT/'business-observation.json';value = None
    if saved.exists():
        old = lc.trusted_json(saved, 16777216)
        at = datetime.fromisoformat(old['observed_at'])
        if old.get('schema') == 2 and at.tzinfo is not None and 0 <= (now-at).total_seconds() < 3600:value = old
    if value is None:
        reader = NativeReader(engine.client, limit=max(0, 160-engine.reads))
        try:
            snapshot = collect_recurring(reader)
            links = lc.trusted_json(ROOT/'recurring-links.json', 262144) if (ROOT/'recurring-links.json').exists() else {}
            recurring = build_recurring(snapshot, now=now, reviewed_links=links)
            marketing = None
            try:
                complete = collect_marketing(reader, snapshot)
                marketing = build_marketing(complete, recurring_links=links)
                snapshot = complete
            except (ValueError, KeyError, TypeError):
                pass  # Keep the verified recurring view; do not retry 100+ GETs every cycle.
            value = {'schema': 2, 'observed_at': now.isoformat(), 'snapshot': snapshot, 'recurring': recurring, 'marketing': marketing}
            if not engine.dry_run:atomic(saved,value)
        finally:engine.reads += reader.reads
    recurring = {**value['recurring'], 'at': now.isoformat(), 'observed_at': value['observed_at']}
    if not engine.dry_run:
        atomic(DISPLAY,recurring,0o644)
        # Display contains aggregates only. Native identifiers/outcome plans and
        # customer value remain root-only, never a public readiness projection.
        if value['marketing']:
            marketing = {k:v for k,v in value['marketing'].items() if k not in {'outcomes','customer_value'}}
            atomic(Path('/run/optibrain-readiness/marketing.json'),{**marketing, 'at':now.isoformat()},0o644)
    if not value['marketing']:raise ValueError('Marketing observation incomplete; recurring evidence retained')
    return recurring
