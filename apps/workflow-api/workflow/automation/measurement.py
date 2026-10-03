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
    # Native Finance descendants inherit TEST ownership even when the Books
    # customer itself is real. Never count an unmarked invoice of a TEST Estimate.
    all_estimates=index(list(snapshot.get('books_estimate_index',{}).values()),'estimate_id')
    denied_estimates=set(all_estimates)-set(rows['estimates'])
    denied_profiles={identity(r.get('recurring_invoice_id')) for r in snapshot.get('profiles',[])}-set(rows['profiles'])
    denied_invoices=set(finance_ids['invoices'])
    for eid in denied_estimates:
        for ref in all_estimates[eid].get('invoice_ids') or []:
            denied_invoices.add(identity(ref.get('invoice_id')) if isinstance(ref,dict) else identity(ref))
    rows['invoices']={i:r for i,r in rows['invoices'].items() if i not in denied_invoices
        and identity(r.get('estimate_id')) not in denied_estimates
        and identity(r.get('recurring_invoice_id')) not in denied_profiles}
    native_ids={'estimates':set(all_estimates),'invoices':set(index(snapshot.get('books_invoices',[]),'invoice_id'))}
    for name,kind,field in [('finance_estimates','estimates','Estimate_ID'),('finance_invoices','invoices','Invoice_ID')]:
        denied={i for i,r in rows[name].items() if identity(r.get(field)) in native_ids[kind]
            and identity(r.get(field)) not in rows[kind]}
        excluded[name].update(denied)
        rows[name]={i:r for i,r in rows[name].items() if i not in denied}
    rows['_finance_reviews']=snapshot.get('finance_reviews', {})
    rows['_recurring_reviews']=snapshot.get('recurring_reviews', {})
    rows['_accepted_work']=snapshot.get('accepted_work', {})
    return rows, {k:len(v) for k,v in excluded.items()}


def finance_link(row, kind, rows):
    from .finance_links import resolve_finance
    return resolve_finance(row, kind, rows)


def audit_lineage(snapshot, *, protected=None, recurring_links=None):
    rows,excluded=populations(snapshot);coverage={};financial={};protected=protected or {}
    from .finance_links import recurring_reviews
    reviewed_profiles=recurring_reviews(rows)
    for name in ('leads','contacts','accounts','deals','sites','services'):
        counts=Counter('FULLY ATTRIBUTED' if acquisition(r)['source']!='UNATTRIBUTED' else 'UNATTRIBUTED' for r in rows[name].values())
        coverage[name]={'total':len(rows[name]),'fully_attributed':counts['FULLY ATTRIBUTED'],'unattributed':counts['UNATTRIBUTED']}
    for kind in ('estimates','invoices'):
        links={i:finance_link(r,kind,rows) for i,r in rows[kind].items()};financial[kind]=links
        counts=Counter('AMBIGUOUS' if link['conflict'] else 'DETERMINISTICALLY LINKED' if link['deal_id'] else
            'LINKABLE WITH SAFE EXISTING ID' if link['account_id'] else 'UNATTRIBUTED' for link in links.values())
        coverage[kind]={'total':len(links),'classifications':dict(counts),'relationship_classifications':dict(Counter(l['classification'] for l in links.values())),'account_linked':sum(bool(l['account_id']) for l in links.values()),
            'deal_linked':sum(bool(l['deal_id']) for l in links.values()),'fully_attributed':sum(l['acquisition']['source']!='UNATTRIBUTED' for l in links.values()),
            'protected_account_references':sum(l['account_id'] in protected.get('Accounts',set()) for l in links.values())}
    linked=0
    for pid,profile in rows['profiles'].items():
        link=bind_profile(profile,rows['customers'].get(identity(profile.get('customer_id')),{}),list(rows['services'].values()),rows['sites'],
            list(rows['finance_invoices'].values()),snapshot.get('generated',{}).get(pid,[]),reviewed=(recurring_links or reviewed_profiles).get(pid))
        linked+=link['decision']=='LINKED'
    coverage['recurring_profiles']={'total':len(rows['profiles']),'service_linked':linked,'unlinked':len(rows['profiles'])-linked}
    return {'schema':1,'scope':'live','read_only':True,'observed_at':snapshot.get('observed_at'),
        'coverage':coverage,'excluded':excluded,'financial_links':financial,'financial_writes':False,
        'advertising_mutations':False,'conversion_uploads':False,'historical_mutations':False}
