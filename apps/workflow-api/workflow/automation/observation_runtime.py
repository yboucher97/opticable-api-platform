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
        from .sales_intelligence import stamp
        at = stamp(old.get('attempted_at') or old.get('observed_at'))
        if old.get('schema') == 3 and old.get('collection') and at and 0 <= (now-at).total_seconds() < 3600:value = old
    if value is None:
        reader = NativeReader(engine.client, limit=max(0, 160-engine.reads), previous=old, now=now)
        # Reserve identity reads for the existing sales observer. Required stages
        # own independent allocations; optional work only follows both attempts.
        reserved = min(3,reader.limit)
        usable = reader.limit-reserved
        marketing_budget = (usable*45+99)//100
        recurring_budget = usable-marketing_budget
        snapshot = {'observed_at':old.get('snapshot',{}).get('observed_at') or old.get('observed_at') or now.isoformat()}
        try:
            with reader.stage('marketing', marketing_budget):
                collect_marketing(reader, snapshot, incremental=True)
            with reader.stage('recurring', recurring_budget):
                collect_recurring(reader, snapshot)
            with reader.stage('business_optional', min(3, max(0,reader.remaining-3))):
                snapshot = collect_business(reader, snapshot)
            with reader.stage('finance_details', min(8, max(0,reader.remaining-3))) as finance_status:
                snapshot = enrich_finance(reader,snapshot,previous=old.get('snapshot',{}))
            if snapshot.get('finance_detail_coverage',{}).get('pending'):
                finance_status.update(state='PARTIAL', completeness='PARTIAL')
            links = lc.trusted_json(ROOT/'recurring-links.json', 262144) if (ROOT/'recurring-links.json').exists() else {}
            registry = lc.trusted_json(ROOT/'finance-links.json', 262144) if (ROOT/'finance-links.json').exists() else {'schema':1,'records':{}}
            if registry.get('schema')!=1 or not isinstance(registry.get('records'),dict):raise ValueError('Invalid owner finance evidence')
            snapshot['finance_reviews'] = registry['records']
            snapshot['accepted_work'] = {k:{f:v[f] for f in ('accepted','accepted_estimate_id','service_ids') if f in v} for k,v in getattr(engine,'state',{}).get('deals',{}).items()}
            recurring = old.get('recurring');marketing = old.get('marketing')
            views = dict(old.get('view_sources', {}))
            for name in ('recurring','marketing'):
                if old.get(name) and name not in views:views[name]=old[name].get('observed_at') or old.get('observed_at')
            if recurring and 'observed_at' not in recurring:recurring={**recurring,'observed_at':views.get('recurring')}
            for name,build in [('recurring',lambda:build_recurring(snapshot,now=now,reviewed_links=links)),
                               ('marketing',lambda:build_marketing(snapshot,recurring_links=links))]:
                deps = [name]
                parents = () if name=='recurring' else ('accounts','services','sites','finance_invoices')
                if all(reader.stages[k]['state']=='COMPLETE' for k in deps) and all(reader.modules.get(k,{}).get('state')=='COMPLETE' for k in parents):
                    try:
                        if name=='marketing':
                            from .measurement import populations
                            from .finance_links import recurring_reviews
                            links=recurring_reviews(populations(snapshot)[0])
                        snapshot['recurring_reviews']=links
                        built=build()
                    except (ValueError,KeyError,TypeError) as exc:
                        reader.stages[name].update(state='FAILED',completeness='FAILED',error_type=type(exc).__name__)
                    else:
                        if name=='recurring':recurring=built
                        else:marketing=built
                        views[name]=min([reader.stages[k]['source_at'] or now.isoformat() for k in deps]+[reader.modules[k]['source_at'] for k in parents])
                        built['observed_at']=views[name]
            complete = all(reader.stages[k]['state']=='COMPLETE' for k in ('marketing','recurring'))
            source = min((m['source_at'] for m in reader.modules.values() if m.get('source_at')), default=None)
            snapshot['observed_at'] = source or snapshot['observed_at']
            collection = {'schema':1,'state':'COMPLETE' if complete else 'PARTIAL','attempted_at':now.isoformat(),
                          'source_at':source,'budget':reader.limit,'reserved_sales_reads':reserved,
                          'stages':reader.stages,'modules':reader.modules,**reader.metadata((0,0,0,0))}
            snapshot['collection'] = collection
            value = {'schema':3,'attempted_at':now.isoformat(),'observed_at':source,
                     'snapshot':snapshot,'recurring':recurring,'marketing':marketing,'collection':collection,
                     'view_sources':views,'detail_checkpoint':reader.details,'last_good_modules':reader.last_good}
            if not engine.dry_run:atomic(saved,value)
        finally:engine.reads += reader.reads
    recurring = {**(value.get('recurring') or {'schema':1,'scope':'live','read_only':True,'rows':[],'attention':[]}),
                 'at':now.isoformat(),'observed_at':value.get('view_sources',{}).get('recurring') or old.get('observed_at'),
                 'state':'READY' if value['collection']['stages']['recurring']['state']=='COMPLETE' else 'PARTIAL',
                 'collection':value['collection']}
    status=ROOT/'measurement-status.json'
    if status.exists():
        health=lc.trusted_json(status,16384)
        states=health.get('states',{})
        if set(states)!={'forms','ga4','google_ads','offline_conversions'} or not all(v in {'HEALTHY','PARTIAL','ISSUE','OFF','READY','ACTIVE'} for v in states.values()):
            raise ValueError('Invalid reviewed measurement health')
        value['snapshot']['measurement_health']=states
    google=Path('/var/lib/optibrain/acquisition-intelligence/google-current.json')
    if google.exists():
        from .measurement_health import collection_health
        try:
            reports=lc.trusted_json(google,2097152)
            health=collection_health(reports.get('reads',{}).get('ga4_collection',{}),now=now,
                attempt=reports.get('attempts',{}).get('ga4_collection') or reports.get('attempts',{}).get('collection'))
        except (ValueError,OSError):health={'auth_status':'UNKNOWN','collection_status':'UNKNOWN','coverage_notes':'Optional reporting cache unavailable; working lifecycle scopes are unaffected.'}
        value['snapshot']['ga4_collection_health']=health
    if not engine.dry_run:
        atomic(DISPLAY,recurring,0o644)
        # Display contains aggregates only. Native identifiers/outcome plans and
        # customer value remain root-only, never a public readiness projection.
        if value.get('marketing'):
            marketing = {k:v for k,v in value['marketing'].items() if k not in {'outcomes','customer_value'}}
            atomic(Path('/run/optibrain-readiness/marketing.json'),{**marketing, 'at':now.isoformat(), 'observed_at':value.get('view_sources',{}).get('marketing') or value['observed_at'], 'collection':value['collection']},0o644)
            # Customer/Deal detail is owner-only. The API service group may read
            # this minimized projection; ordinary host users may not.
        import grp, os
        path=Path('/run/optibrain-readiness/business.json')
        atomic(path,{'schema':1,'scope':'live','read_only':True,'at':now.isoformat(),
                         'observed_at':value['observed_at'],'snapshot':project_source(value['snapshot'])},0o600)
        os.chown(path,0,grp.getgrnam('opticable-workflow-api').gr_gid)
        os.chmod(path,0o640)
    if value['collection']['state']!='COMPLETE':raise ValueError('Business observation partial; dated last-good evidence retained')
    return recurring
