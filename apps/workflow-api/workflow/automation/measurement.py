"""Rebuildable, non-mutating native lineage and reporting populations."""
from collections import Counter
from .recurring_lifecycle import identity, index, synthetic, bind_profile
from .marketing_attribution import acquisition


def populations(snapshot):
    names = ('accounts','contacts','leads','deals','sites','services','finance_estimates','finance_invoices','cases','installations')
    rows = {name:index(snapshot.get(name, [])) for name in names}
    excluded = {name:{i for i,r in values.items() if synthetic(r)} for name,values in rows.items()}
    # Fixed point closes TEST lineage regardless of relation ordering.
    for _ in range(4):
        for name, links in {
            'contacts':{'Account_Name':'accounts'}, 'deals':{'Account_Name':'accounts','Contact_Name':'contacts'},
            'sites':{'Linked_Account':'accounts'}, 'services':{'Linked_Service_Location':'sites','Linked_Deal':'deals'},
            'finance_estimates':{'Account_Name':'accounts','Potential_Name':'deals'},
            'finance_invoices':{'Account_Name':'accounts','Potential_Name':'deals'},
            'cases':{'Account_Name':'accounts','Contact_Name':'contacts','Deal_Name':'deals'},
            'installations':{'Linked_Service':'services'}}.items():
            for i,r in rows[name].items():
                if any(identity(r.get(field)) in excluded[parent] for field,parent in links.items()):excluded[name].add(i)
        for lid,r in rows['leads'].items():
            detail=r.get('$converted_detail') or {}
            if any(identity(detail.get(k)) in excluded[n] for k,n in [('account','accounts'),('contact','contacts'),('deal','deals')]):excluded['leads'].add(lid)
            if lid in excluded['leads']:
                for k,n in [('account','accounts'),('contact','contacts'),('deal','deals')]:
                    if identity(detail.get(k)):excluded[n].add(identity(detail[k]))
    customers=index(snapshot.get('customers',[]),'contact_id')
    test_customers={i for i,r in customers.items() if synthetic(r) or identity(r.get('zcrm_account_id')) in excluded['accounts']}
    rows={n:{i:r for i,r in values.items() if i not in excluded[n]} for n,values in rows.items()}
    finance_ids={kind:{identity(r.get(field)) for i,r in index(snapshot.get(name,[])).items() if i in excluded[name]}
        for kind,name,field in [('estimates','finance_estimates','Estimate_ID'),('invoices','finance_invoices','Invoice_ID')]}
    rows['customers']={i:r for i,r in customers.items() if i not in test_customers}
    for name,key,items in [('invoices','invoice_id',snapshot.get('books_invoices',[])),
                          ('estimates','estimate_id',list(snapshot.get('books_estimate_index',{}).values())),
                          ('profiles','recurring_invoice_id',snapshot.get('profiles',[])),
                          ('payments','payment_id',snapshot.get('payments',[]))]:
        rows[name]={i:r for i,r in index(items,key).items() if not synthetic(r) and identity(r.get('customer_id')) not in test_customers
                    and identity(r.get('zcrm_potential_id')) not in excluded['deals'] and i not in finance_ids.get(name,set())}
    return rows, {k:len(v) for k,v in excluded.items()}


def finance_link(row, kind, rows):
    """No names, dates, amounts or single-customer Deal guesses."""
    key='invoice_id' if kind=='invoices' else 'estimate_id';field='Invoice_ID' if kind=='invoices' else 'Estimate_ID'
    native=[r for r in rows['finance_'+kind].values() if identity(r.get(field))==identity(row.get(key))]
    customer=rows['customers'].get(identity(row.get('customer_id')), {})
    account=identity(customer.get('zcrm_account_id'));did=identity(row.get('zcrm_potential_id'))
    proof=['Books customer_id → contact_id → zcrm_account_id'] if account else []
    conflict=len(native)>1
    if native:
        aid=identity(native[0].get('Account_Name'));fid=identity(native[0].get('Potential_Name'))
        conflict=conflict or bool(aid and aid!=account) or bool(fid and did and fid!=did)
        did=fid or did;proof.append('CRM Finance native Books ID / Account_Name / Potential_Name')
    # Exact native Invoice → Estimate can supply its Deal only after parent verification.
    if kind=='invoices' and identity(row.get('estimate_id')) in rows['estimates']:
        estimate=rows['estimates'][identity(row['estimate_id'])]
        if identity(estimate.get('customer_id'))!=identity(row.get('customer_id')):conflict=True
        else:
            parent=finance_link(estimate,'estimates',rows)
            if parent['conflict'] or (did and parent['deal_id'] and did!=parent['deal_id']):conflict=True
            elif parent['deal_id']:did=did or parent['deal_id'];proof.append('Books Invoice estimate_id → verified Estimate Deal')
    if kind=='invoices' and identity(row.get('recurring_invoice_id')) in rows['profiles']:
        pid=identity(row['recurring_invoice_id']);profile=rows['profiles'][pid]
        if identity(profile.get('customer_id'))==identity(row.get('customer_id')):
            link=bind_profile(profile,customer,list(rows['services'].values()),rows['sites'],list(rows['finance_invoices'].values()),
                              [r for r in rows['invoices'].values() if identity(r.get('recurring_invoice_id'))==pid])
            if link['decision']=='LINKED':
                if did and did!=link['deal_id']:conflict=True
                else:did=link['deal_id'];proof.append('Native recurring profile → Service original acquisition Deal')
    deal=rows['deals'].get(did)
    if did and (not deal or not account or identity(deal.get('Account_Name'))!=account):conflict=True
    site_ids=set();service_ids=set()
    if deal and not conflict:
        if identity(deal.get('Service_Location')):site_ids.add(identity(deal['Service_Location']))
        for sid,service in rows['services'].items():
            if identity(service.get('Linked_Deal'))==did:
                service_ids.add(sid);site_ids.add(identity(service.get('Linked_Service_Location')))
        site_ids.discard('')
        if any(identity(rows['sites'].get(i,{}).get('Linked_Account'))!=account for i in site_ids):conflict=True
    touch=acquisition(deal or {})
    if conflict:account=did='';site_ids=set();service_ids=set();touch=acquisition({})
    return {'account_id':account,'deal_id':did,'site_ids':sorted(site_ids),'service_ids':sorted(service_ids),
        'conflict':bool(conflict),'proof':proof,'acquisition':touch,
        'truth':'UNKNOWN' if conflict else 'DERIVED DETERMINISTICALLY' if did else 'PARTIAL' if account else 'UNKNOWN'}


def audit_lineage(snapshot, *, protected=None, recurring_links=None):
    rows,excluded=populations(snapshot);coverage={};financial={};protected=protected or {}
    for name in ('leads','contacts','accounts','deals','sites','services'):
        counts=Counter('FULLY ATTRIBUTED' if acquisition(r)['source']!='UNATTRIBUTED' else 'UNATTRIBUTED' for r in rows[name].values())
        coverage[name]={'total':len(rows[name]),'fully_attributed':counts['FULLY ATTRIBUTED'],'unattributed':counts['UNATTRIBUTED']}
    for kind in ('estimates','invoices'):
        links={i:finance_link(r,kind,rows) for i,r in rows[kind].items()};financial[kind]=links
        counts=Counter('AMBIGUOUS' if link['conflict'] else 'DETERMINISTICALLY LINKED' if link['deal_id'] else
            'LINKABLE WITH SAFE EXISTING ID' if link['account_id'] else 'UNATTRIBUTED' for link in links.values())
        coverage[kind]={'total':len(links),'classifications':dict(counts),'account_linked':sum(bool(l['account_id']) for l in links.values()),
            'deal_linked':sum(bool(l['deal_id']) for l in links.values()),'fully_attributed':sum(l['acquisition']['source']!='UNATTRIBUTED' for l in links.values()),
            'protected_account_references':sum(l['account_id'] in protected.get('Accounts',set()) for l in links.values())}
    linked=0
    for pid,profile in rows['profiles'].items():
        link=bind_profile(profile,rows['customers'].get(identity(profile.get('customer_id')),{}),list(rows['services'].values()),rows['sites'],
            list(rows['finance_invoices'].values()),snapshot.get('generated',{}).get(pid,[]),reviewed=(recurring_links or {}).get(pid))
        linked+=link['decision']=='LINKED'
    coverage['recurring_profiles']={'total':len(rows['profiles']),'service_linked':linked,'unlinked':len(rows['profiles'])-linked}
    return {'schema':1,'scope':'live','read_only':True,'observed_at':snapshot.get('observed_at'),
        'coverage':coverage,'excluded':excluded,'financial_links':financial,'financial_writes':False,
        'advertising_mutations':False,'conversion_uploads':False,'historical_mutations':False}
