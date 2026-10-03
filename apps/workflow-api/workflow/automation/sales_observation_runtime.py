"""Optional read-only shadow cache. Failure never disables working lifecycle scopes."""
from datetime import datetime, timezone
from pathlib import Path
import grp
import os
import httpx
from . import lifecycle_control as lc
from .apollo_observation import ApolloReader
from .sales_intelligence import build_sales, permit_signals, stamp
from .sales_feedback import SalesFeedback

ROOT = Path('/var/lib/optibrain/sales-intelligence')
DISPLAY = Path('/run/optibrain-readiness/sales-intelligence.json')
PERMITS = 'https://donnees.montreal.ca/api/3/action/datastore_search'
RESOURCE = '5232a72d-235a-48eb-ae20-bb9d501300ad'
DATABASE = Path('/var/lib/opticable-workflow-api/output/automation/phase12-autonomy.db')


def observe(engine, settings, *, now=None):
    from .real_internal import atomic
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:raise ValueError('Aware sales observation time required')
    disabled = ROOT/'STOP'
    if disabled.exists():return {'state':'DISABLED','provider_writes':0}
    source = ROOT/'apollo.json'
    apollo = lc.trusted_json(source,16777216) if source.exists() else None
    at = stamp((apollo or {}).get('at'))
    # Complete small workspace every six hours, not all provider history every cycle.
    if not apollo or not at or not 0 <= (now-at).total_seconds() < 6*3600:
        reader = ApolloReader(settings.apollo)
        try:apollo = reader.workspace()
        finally:reader.close()
        if not engine.dry_run:atomic(source,apollo)
    saved = lc.trusted_json(Path('/var/lib/optibrain/lifecycle/business-observation.json'),16777216)
    observed=stamp(saved.get('observed_at'))
    if not observed or not 0 <= (now-observed).total_seconds()<7200:
        raise ValueError('CRM observation stale; no collision clearance')
    s=saved['snapshot']
    crm={k:s.get(v,[]) for k,v in {'Leads':'leads','Contacts':'contacts','Accounts':'accounts','Deals':'deals','Cases':'cases'}.items()}
    # Reuse the full business observations; fill only missing identity fields in
    # three small CRM modules, hourly. Never repeat all Finance/provider history.
    identity_cache=ROOT/'crm.json'
    identities=lc.trusted_json(identity_cache,2097152) if identity_cache.exists() else {}
    identity_at=stamp(identities.get('at'))
    if not identity_at or not 0 <= (now-identity_at).total_seconds()<3600:
        from .business_observation import NativeReader
        reader=NativeReader(engine.client,limit=max(0,160-engine.reads))
        fields={'Leads':'id,Full_Name,Company,Email,Website,Lead_Status,OptiBrain_Test,Created_Time,Modified_Time',
                'Contacts':'id,Full_Name,Email,Account_Name,OptiBrain_Test',
                'Accounts':'id,Account_Name,Website,OptiBrain_Test'}
        try:identities={'schema':1,'at':now.isoformat(),'crm':{m:reader.crm(m,f) for m,f in fields.items()}}
        finally:engine.reads+=reader.reads
        if not engine.dry_run:atomic(identity_cache,identities)
    crm.update(identities['crm'])
    signals=[]
    manifest=ROOT/'public-triggers.json'
    if manifest.exists():
        value=lc.trusted_json(manifest,262144)
        if value.get('schema') != 1:raise ValueError('Invalid public trigger manifest')
        signals.extend(value.get('signals',[]))
    permits=ROOT/'permits.json'
    old=lc.trusted_json(permits,2097152) if permits.exists() else {}
    at=stamp(old.get('at'))
    if not at or not 0 <= (now-at).total_seconds()<86400:
        try:
            with httpx.Client(timeout=15,follow_redirects=False) as client:
                with client.stream('GET',PERMITS,params={'resource_id':RESOURCE,'limit':100,'sort':'date_emission desc'}) as response:
                    response.raise_for_status();body=b''
                    for chunk in response.iter_bytes():
                        body+=chunk
                        if len(body)>2097152:raise ValueError('Public source exceeds byte bound')
            import json
            data=json.loads(body)
            if data.get('success') is not True:raise ValueError('Public permit source unavailable')
            old={'schema':1,'at':now.isoformat(),'records':data['result']['records']}
            if not engine.dry_run:atomic(permits,old)
        except (httpx.HTTPError,ValueError,KeyError):pass
    if stamp(old.get('at')) and 0 <= (now-stamp(old['at'])).total_seconds()<7*86400:
        signals.extend(permit_signals(old['records'],now=now))
    feedback=SalesFeedback(DATABASE).latest()
    from .recurring_lifecycle import identity
    deals={str(d['id']):d for d in s.get('deals',[])}
    estimates=[]
    for e in s.get('finance_estimates',[]):
        did=identity(e.get('Potential_Name'));eid=identity(e.get('Estimate_ID'))
        if did not in deals:continue
        b=s.get('books_estimate_index',{}).get(eid,{})
        from .sales_intelligence import live
        if live(deals[did]) and live(b):estimates.append({'id':eid,'title':b.get('estimate_number'),'status':b.get('status'),'deal_id':did})
    view=build_sales(apollo,crm,signals,now=now,recurring=saved.get('recurring'),feedback=feedback,estimates=estimates)
    view['crm_observed_at']=saved['observed_at']
    view['identity_observed_at']=identities['at']
    view['public_permits_observed_at']=old.get('at')
    if not engine.dry_run:
        atomic(DISPLAY,view,0o600)
        os.chown(DISPLAY,0,grp.getgrnam('opticable-workflow-api').gr_gid);os.chmod(DISPLAY,0o640)
    return view
