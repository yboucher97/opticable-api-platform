"""Root-only, hourly native observations; never provider actions or authority."""
from datetime import datetime, timezone
from pathlib import Path
from . import lifecycle_control as lc
from .business_observation import NativeReader, collect_recurring, collect_marketing, collect_business, enrich_finance
from .business_intelligence import project_source
from .recurring_lifecycle import build_recurring
from .marketing_attribution import build_marketing

ROOT = Path('/var/lib/optibrain/lifecycle')
DISPLAY = Path('/run/optibrain-readiness/recurring.json')


def observe(engine, *, now=None):
    from .real_internal import atomic
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None: raise ValueError('Aware observation time required')
    saved = ROOT/'business-observation.json';value = None;old = {}
    if saved.exists():
        old = lc.trusted_json(saved, 16777216)
        at = datetime.fromisoformat(old['observed_at'])
        if old.get('schema') == 3 and at.tzinfo is not None and 0 <= (now-at).total_seconds() < 3600:value = old
    if value is None:
        reader = NativeReader(engine.client, limit=max(0, 160-engine.reads))
        try:
            snapshot = collect_recurring(reader)
            links = lc.trusted_json(ROOT/'recurring-links.json', 262144) if (ROOT/'recurring-links.json').exists() else {}
            snapshot['recurring_reviews'] = links
            registry = lc.trusted_json(ROOT/'finance-links.json', 262144) if (ROOT/'finance-links.json').exists() else {'schema':1,'records':{}}
            if registry.get('schema')!=1 or not isinstance(registry.get('records'),dict):raise ValueError('Invalid owner finance evidence')
            snapshot['finance_reviews'] = registry['records']
            snapshot['accepted_work'] = {k:{f:v[f] for f in ('accepted','accepted_estimate_id','service_ids') if f in v} for k,v in getattr(engine,'state',{}).get('deals',{}).items()}
            recurring = build_recurring(snapshot, now=now, reviewed_links=links)
            marketing = None
            try:
                complete = collect_marketing(reader, snapshot)
                snapshot = collect_business(reader,complete)
                snapshot = enrich_finance(reader,snapshot,previous=old.get('snapshot',{}))
                from .measurement import populations
                from .finance_links import recurring_reviews
                verified_links=recurring_reviews(populations(snapshot)[0])
                snapshot['recurring_reviews']=verified_links
                recurring=build_recurring(snapshot,now=now,reviewed_links=verified_links)
                marketing = build_marketing(snapshot, recurring_links=verified_links)
            except (ValueError, KeyError, TypeError):
                pass  # Keep the verified recurring view; do not retry 100+ GETs every cycle.
            value = {'schema': 3, 'observed_at': now.isoformat(), 'snapshot': snapshot, 'recurring': recurring, 'marketing': marketing}
            if not engine.dry_run:atomic(saved,value)
        finally:engine.reads += reader.reads
    recurring = {**value['recurring'], 'at': now.isoformat(), 'observed_at': value['observed_at']}
    status=ROOT/'measurement-status.json'
    if status.exists():
        health=lc.trusted_json(status,16384)
        states=health.get('states',{})
        if set(states)!={'forms','ga4','google_ads','offline_conversions'} or not all(v in {'HEALTHY','PARTIAL','ISSUE','OFF','READY','ACTIVE'} for v in states.values()):
            raise ValueError('Invalid reviewed measurement health')
        value['snapshot']['measurement_health']=states
    if not engine.dry_run:
        atomic(DISPLAY,recurring,0o644)
        # Display contains aggregates only. Native identifiers/outcome plans and
        # customer value remain root-only, never a public readiness projection.
        if value['marketing']:
            marketing = {k:v for k,v in value['marketing'].items() if k not in {'outcomes','customer_value'}}
            atomic(Path('/run/optibrain-readiness/marketing.json'),{**marketing, 'at':now.isoformat()},0o644)
            # Customer/Deal detail is owner-only. The API service group may read
            # this minimized projection; ordinary host users may not.
            import grp, os
            path=Path('/run/optibrain-readiness/business.json')
            atomic(path,{'schema':1,'scope':'live','read_only':True,'at':now.isoformat(),
                         'observed_at':value['observed_at'],'snapshot':project_source(value['snapshot'])},0o600)
            os.chown(path,0,grp.getgrnam('opticable-workflow-api').gr_gid)
            os.chmod(path,0o640)
    if not value['marketing']:raise ValueError('Marketing observation incomplete; recurring evidence retained')
    return recurring
