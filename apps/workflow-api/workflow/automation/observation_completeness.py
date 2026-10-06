"""Source completeness only; collision decisions stay in the existing engine."""
from .sales_intelligence import stamp

CRM_MODULES = {'Leads':'leads','Contacts':'contacts','Accounts':'accounts','Deals':'deals',
               'Services':'services','Service_Locations':'sites','Books_Customers':'customers'}
CRM_REQUIRED = ('Leads','Contacts','Accounts','Deals','Services','Service_Locations','Customer_Context')
APOLLO_REQUIRED = ('contacts','accounts','sequences','stages','ownership','suppression','messages','replies')


def complete(rows, at):
    return {'state':'COMPLETE','completeness':'COMPLETE_WITH_RECORDS' if rows else 'COMPLETE_VERIFIED_EMPTY',
            'source_at':at}


def states(data, names, *, now, tolerance, metadata_key):
    """A present empty array needs independent collection proof and source date."""
    metadata = data.get(metadata_key, {})
    result = {}
    for name in names:
        meta = metadata.get(name, {})
        rows = data.get(name)
        source = stamp(meta.get('source_at'))
        state = meta.get('completeness') or meta.get('state') or 'NOT_COLLECTED_UNKNOWN'
        if meta.get('state') in {'FAILED','PARTIAL','NOT_STARTED','SKIPPED_BUDGET','STALE_REUSED'}:
            state='STALE' if meta['state']=='STALE_REUSED' else meta['state']
        if state in {'COMPLETE','COMPLETE_WITH_RECORDS','COMPLETE_VERIFIED_EMPTY'}:
            if not isinstance(rows,list):state='NOT_COLLECTED_UNKNOWN'
            elif not source or not 0 <= (now-source).total_seconds() <= tolerance:state='STALE' if source else 'NOT_COLLECTED_UNKNOWN'
            else:state='COMPLETE_WITH_RECORDS' if rows else 'COMPLETE_VERIFIED_EMPTY'
        result[name] = {'state':state,'source_at':meta.get('source_at'),
                        'complete':state in {'COMPLETE_WITH_RECORDS','COMPLETE_VERIFIED_EMPTY'}}
    return result


def crm_context(business, identities=None):
    """Merge the documented atomic legacy inventories without inventing modules."""
    snapshot = business.get('snapshot', {});crm = {};metadata = {}
    modules = (business.get('collection') or snapshot.get('collection') or {}).get('modules', {})
    legacy = business.get('schema') == 3 and not business.get('collection')
    for name,field in CRM_MODULES.items():
        if field in snapshot:
            crm[name] = snapshot[field]
            if field in modules:metadata[name] = modules[field]
            elif legacy and (name!='Books_Customers' or business.get('marketing')):
                metadata[name] = complete(snapshot[field], snapshot.get('observed_at') or business.get('observed_at'))
    identities = identities or {}
    for name in ('Leads','Contacts','Accounts'):
        if name in identities.get('crm',{}):
            prior={str(r['id']):r for r in crm.get(name,[]) if r.get('id')}
            crm[name] = [{**prior.get(str(r.get('id')),{}),**r} for r in identities['crm'][name]]
            metadata[name] = identities.get('modules',{}).get(name) or complete(crm[name],identities.get('at'))
    # A deterministic negative customer claim requires all native parent surfaces.
    dependencies = ('Accounts','Services','Service_Locations','Books_Customers')
    crm['Customer_Context'] = [{'account_id':str(c['zcrm_account_id'])} for c in crm.get('Books_Customers',[]) if c.get('zcrm_account_id')]
    proven = all(metadata.get(n,{}).get('state')=='COMPLETE' for n in dependencies)
    dates = [metadata.get(n,{}).get('source_at') for n in dependencies]
    metadata['Customer_Context'] = complete(crm['Customer_Context'],min(dates)) if proven and all(dates) else {'state':'PARTIAL','completeness':'PARTIAL','source_at':None}
    crm['_modules'] = metadata
    crm['_identity_complete'] = all(name in crm for name in CRM_REQUIRED)
    return crm


def collision_sources(apollo, crm, *, now):
    crm_states = states(crm,CRM_REQUIRED,now=now,tolerance=7200,metadata_key='_modules')
    apollo_states = states(apollo,APOLLO_REQUIRED,now=now,tolerance=21600,metadata_key='modules')
    crm_complete = all(v['complete'] for v in crm_states.values()) and crm.get('_identity_complete') is not False
    apollo_complete = all(v['complete'] for v in apollo_states.values()) and apollo.get('contacts_complete') is not False
    return {'crm':crm_states,'apollo':apollo_states,'crm_complete':crm_complete,'apollo_complete':apollo_complete}
