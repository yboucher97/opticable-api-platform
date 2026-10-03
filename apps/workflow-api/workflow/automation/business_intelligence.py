"""Owner-only read projections. Books facts, no predictions or business actions."""
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from html import escape
from zoneinfo import ZoneInfo
import csv, io, re
from .measurement import populations, audit_lineage, finance_link
from .recurring_lifecycle import identity, money
from .marketing_attribution import acquisition, label

TZ=ZoneInfo('America/Toronto')
PERIODS=('today','week','month','last_month','quarter','year','custom')


def period_bounds(period, now, start=None, end=None):
    if now.tzinfo is None:raise ValueError('Aware reporting time required')
    today=now.astimezone(TZ).date()
    if period=='custom':
        first=date.fromisoformat(str(start));last=date.fromisoformat(str(end))
        if last<first or (last-first).days>3660:raise ValueError('Invalid bounded custom range')
        return first,last+timedelta(days=1)
    if period not in PERIODS:raise ValueError('Unknown reporting period')
    first=today
    if period=='week':first=today-timedelta(days=today.weekday())
    if period=='month':first=today.replace(day=1)
    if period=='quarter':first=date(today.year,1+3*((today.month-1)//3),1)
    if period=='year':first=date(today.year,1,1)
    if period=='last_month':
        last=today.replace(day=1);return (last-timedelta(days=1)).replace(day=1),last
    return first,today+timedelta(days=1) # to date; future-dated financial rows do not count.


def business_day(value):
    if not value:return None
    text=str(value)
    if len(text)==10:return date.fromisoformat(text)
    at=datetime.fromisoformat(text.replace('Z','+00:00'))
    if at.tzinfo is None:raise ValueError('CRM timestamps must have offset')
    return at.astimezone(TZ).date()


def project_source(snapshot):
    """Minimize the private display file: no addresses, raw URLs, click IDs or secrets."""
    rows,excluded=populations(snapshot)
    fields={
        'accounts':('id','Account_Name'), 'contacts':('id','Account_Name'),
        'leads':('id','Lead_Status','$converted','Created_Time','First_Source','First_Medium','First_Campaign','Lead_Source'),
        'deals':('id','Deal_Name','Account_Name','Contact_Name','Stage','Amount','Currency','Created_Time','Closing_Date','Service_Location','Next_Step','First_Source','First_Medium','First_Campaign','Lead_Source'),
        'sites':('id','Linked_Account'), 'services':('id','Linked_Service_Location','Linked_Deal','Service_Type','Service_Stage','Contract_Type','OptiBrain_Renewal_On'),
        'finance_estimates':('id','Estimate_ID','Account_Name','Potential_Name'), 'finance_invoices':('id','Invoice_ID','Account_Name','Potential_Name'),
        'customers':('contact_id','zcrm_account_id','contact_name','currency_code'),
        'invoices':('invoice_id','customer_id','customer_name','estimate_id','zcrm_potential_id','recurring_invoice_id','date','due_date','status','total','balance','currency_code'),
        'estimates':('estimate_id','customer_id','date','status','total','currency_code','zcrm_potential_id'),
        'profiles':('recurring_invoice_id','customer_id','status','start_date','next_invoice_date','recurrence_frequency','repeat_every','sub_total','currency_code','zcrm_potential_id'),
        'payments':('payment_id','customer_id','date','payment_status','status','bcy_amount','bcy_refunded_amount'),
        'cases':('id','Status','Account_Name','Deal_Name'), 'installations':('id','Installation_Status','Linked_Service','Installation_Date_Time')}
    output={name:[{k:r[k] for k in keys if k in r} for r in rows[name].values()] for name,keys in fields.items()}
    output['books_invoices']=output.pop('invoices');output['books_estimate_index']={r['estimate_id']:r for r in output.pop('estimates')}
    output['generated']={pid:[{'invoice_id':r['invoice_id']} for r in values] for pid,values in snapshot.get('generated',{}).items()}
    output.update(observed_at=snapshot['observed_at'],base_currency=snapshot.get('base_currency'),optional_reads=snapshot.get('optional_reads',{}),
        cost_population={'rows':len(snapshot.get('expenses',[])), 'native_customer_allocated':sum(bool(r.get('customer_id')) for r in snapshot.get('expenses',[])),
                         'job_cost_completeness':'UNPROVEN'},test_excluded=excluded)
    return output


def build_business(snapshot, *, now=None, period='month', start=None, end=None):
    now=now or datetime.now(timezone.utc);first,last=period_bounds(period,now,start,end);today=now.astimezone(TZ).date()
    rows,excluded=populations(snapshot);issues=Counter();currency=lambda r:r.get('currency_code')
    def selected(r,field):
        try:d=business_day(r.get(field))
        except ValueError:issues['Invalid native date']+=1;return False
        if d is None:issues['Missing date for period metric']+=1;return False
        return first<=d<last
    def add(bucket,code,value):
        if not re.fullmatch('[A-Z]{3}',str(code or '')) or value is None:issues['Missing amount/currency']+=1;return
        bucket[code]=str(money(bucket.get(code,'0'))+money(value))
    financial={k:{} for k in ('invoiced_gross','paid_invoice_value','recorded_payments_gross','payment_refunds','outstanding','overdue')}
    sources={};customers={};services={};invoice_count=0;unattributed=0
    def source(r):
        touch=acquisition(r);key=(touch['source'],touch['medium'],touch['campaign'])
        return sources.setdefault(key,{**{k:touch[k] for k in ('source','medium','campaign')},'leads':0,'qualified_leads':0,'deals':0,
            'estimates':0,'accepted_estimates':0,'invoice_value':{},'confidence':'UNATTRIBUTED' if touch['source']=='UNATTRIBUTED' else 'PARTIAL'})
    new_leads=qualified=0
    for r in rows['leads'].values():
        if selected(r,'Created_Time'):
            new_leads+=1;source(r)['leads']+=1
            if r.get('$converted') is True or r.get('Lead_Status') in {'Qualified','Prepare Estimate','Pre-Qualified'}:
                qualified+=1;source(r)['qualified_leads']+=1
    pipeline={};deals=[]
    for did,r in rows['deals'].items():
        stage=label(r.get('Stage'),'Unknown stage');d=business_day(r.get('Created_Time'));age=(today-d).days if d else None
        if selected(r,'Created_Time'):source(r)['deals']+=1
        if stage not in {'Closed Won','Closed Lost','Lost','Cancelled'}:
            p=pipeline.setdefault(stage,{'stage':stage,'count':0,'value':{},'missing_value':0,'oldest_days':None})
            p['count']+=1
            if r.get('Amount') is None or not r.get('Currency'):p['missing_value']+=1
            else:add(p['value'],r['Currency'],r['Amount'])
            if age is not None:p['oldest_days']=max(p['oldest_days'] or 0,age)
            deals.append({'id':did,'name':label(r.get('Deal_Name'),'Deal'),'stage':stage,'age_days':age,
                          'next_action':label(r.get('Next_Step'),'Review in CRM'),'value':r.get('Amount'),'currency':r.get('Currency')})
    estimates=accepted=sent=0
    for r in rows['estimates'].values():
        if not selected(r,'date'):continue
        estimates+=1;link=finance_link(r,'estimates',rows);g=source(rows['deals'].get(link['deal_id'],{}));g['estimates']+=1
        if r.get('status') in {'sent','accepted','declined','invoiced'}:sent+=1
        if r.get('status') in {'accepted','invoiced'}:accepted+=1;g['accepted_estimates']+=1
    for iid,r in rows['invoices'].items():
        if r.get('status') in {'draft','void'}:continue
        link=finance_link(r,'invoices',rows);code=currency(r)
        if link['conflict']:issues['Conflicting financial relationship withheld']+=1;continue
        add(financial['outstanding'],code,r.get('balance'))
        due=business_day(r.get('due_date'))
        if due and due<today and money(r.get('balance',0))>0:add(financial['overdue'],code,r['balance'])
        cid=identity(r.get('customer_id'));aid=link['account_id'];customer=rows['customers'].get(cid,{})
        life=customers.setdefault(cid,{'customer_id':cid,'account_id':aid,'name':label(customer.get('contact_name') or r.get('customer_name'),'Customer'),
            'lifetime_invoiced':{},'paid_invoice_value':{},'selected_invoiced':{},'active_services':sum(identity(rows['sites'].get(identity(s.get('Linked_Service_Location')),{}).get('Linked_Account'))==aid and s.get('Service_Stage')=='Active' for s in rows['services'].values()) if aid else None})
        add(life['lifetime_invoiced'],code,r.get('total'))
        if r.get('status')=='paid' and money(r.get('balance',0))==0:add(life['paid_invoice_value'],code,r.get('total'))
        if selected(r,'date'):
            invoice_count+=1;add(financial['invoiced_gross'],code,r.get('total'));add(life['selected_invoiced'],code,r.get('total'))
            if r.get('status')=='paid' and money(r.get('balance',0))==0:add(financial['paid_invoice_value'],code,r.get('total'))
            g=source(rows['deals'].get(link['deal_id'],{}));add(g['invoice_value'],code,r.get('total'))
            if g['confidence']=='UNATTRIBUTED':unattributed+=1
            family='UNALLOCATED'
            categories={str(rows['services'][sid].get('Service_Type') or '') for sid in link['service_ids']}
            if len(categories)==1 and '' not in categories:family=label(next(iter(categories)))
            add(services.setdefault(family,{}),code,r.get('total'))
    for r in rows['payments'].values():
        if not selected(r,'date'):continue
        if (r.get('payment_status') or r.get('status')) not in {'paid','success'}:issues['Payment status unproven']+=1;continue
        add(financial['recorded_payments_gross'],snapshot.get('base_currency'),r.get('bcy_amount'))
        if r.get('bcy_refunded_amount') is not None:add(financial['payment_refunds'],snapshot.get('base_currency'),r['bcy_refunded_amount'])
        else:issues['Payment refund amount unobserved']+=1
    recurring={'active_billing_profiles':0,'active_recurring_services':sum(r.get('Contract_Type')=='Recurring Service' and r.get('Service_Stage')=='Active' for r in rows['services'].values()),
               'normalized_monthly_net':{},'annualized_net':{},'confidence':'PARTIAL','renewals_90d':0,'service_linkage':'See recurring view; billing profile is not a Service'}
    for r in rows['profiles'].values():
        if r.get('status')!='active':continue
        recurring['active_billing_profiles']+=1;begin=business_day(r.get('start_date'))
        if begin and begin>today:issues['Future recurring start excluded from normalized value']+=1;continue
        every=r.get('repeat_every');unit=r.get('recurrence_frequency')
        if not isinstance(every,int) or every<1 or unit not in {'months','years'} or r.get('sub_total') is None:
            issues['Recurring frequency/net value unproven']+=1;continue
        monthly=money(r['sub_total'])/Decimal(every*(12 if unit=='years' else 1))
        add(recurring['normalized_monthly_net'],currency(r),monthly);add(recurring['annualized_net'],currency(r),monthly*12)
    for r in rows['services'].values():
        due=business_day(r.get('OptiBrain_Renewal_On'))
        if due and 0<=(due-today).days<=90:recurring['renewals_90d']+=1
    operations={'open_cases':sum(r.get('Status') not in {'Closed','Resolved'} for r in rows['cases'].values()),
                'installation_states':dict(Counter(r.get('Installation_Status') or 'Unknown' for r in rows['installations'].values())),
                'attention':'Use Today for scheduling, access, return visits, billing and renewal actions'}
    lineage=audit_lineage(snapshot)['coverage']
    return {'schema':1,'scope':'live','read_only':True,'observed_at':snapshot['observed_at'],'timezone':'America/Toronto',
        'period':period,'start':str(first),'end_inclusive':str(last-timedelta(days=1)),
        'sales':{'new_leads':new_leads,'qualified_from_period_leads':qualified,'estimates_created':estimates,'sent_or_later_estimates':sent,
                 'accepted_or_invoiced_estimates':accepted,'open_deals':len(deals),'pipeline':list(pipeline.values()),'deals':deals,
                 'win_rate':None,'sales_cycle':None,'reason':'Historical population and native outcome timing incomplete; no inferred forecast'},
        'financial':financial,'invoice_count':invoice_count,'recurring':recurring,'operations':operations,
        'customer_value':sorted(customers.values(),key=lambda r:r['name']),'service_revenue':services,'marketing':list(sources.values()),
        'attribution':{'invoice_period_unattributed':unattributed,'coverage':lineage,'source_assignments':'No guesses'},
        'profitability':{'state':'NOT CURRENTLY MEASURABLE','gross_margin':None,'known_cost_population':snapshot.get('cost_population',{'rows':len(snapshot.get('expenses',[]))}),
                        'reason':'COST DATA INCOMPLETE: complete direct labour/vendor/item costs and exact Deal/Service allocation unproven'},
        'optional_read_states':snapshot.get('optional_reads',{}),'issues':dict(issues),'test_excluded':snapshot.get('test_excluded',excluded),
        'truth':{'native_counts':'PROVEN','financial_totals':'DERIVED DETERMINISTICALLY','recurring_service_value':'PARTIAL','profitability':'UNKNOWN','advertising_return':'UNKNOWN'},
        'spend':None,'roas':None,'financial_writes':False,'advertising_mutations':False,
        'basis':'Gross issued invoice value by issue date; paid Invoice value by issue date/current status; recorded customer payments by payment date/base currency, refunds separate. Outstanding/overdue and pipeline are current snapshot stocks, not period flows. No recognized revenue, bank settlement, net income or forecast claimed.'}


def render_business(view):
    h=lambda v:escape(str(v),quote=True)
    def val(v):
        if not isinstance(v,dict):return str(v)
        if all(re.fullmatch('[A-Z]{3}',k) for k in v):return ', '.join(k+' '+format(Decimal(n),'.2f') for k,n in sorted(v.items()))
        return '; '.join(k.replace('_',' ').title()+': '+val(n) for k,n in v.items())
    def table(headers,rows):return '<table><tr>'+''.join('<th>'+h(c)+'</th>' for c in headers)+'</tr>'+''.join('<tr>'+''.join('<td>'+h(val(v))+'</td>' for v in r)+'</tr>' for r in rows)+'</table>'
    parts=["<!doctype html><html lang='en'><meta charset='utf-8'><title>Business Overview</title><style>body{font:16px system-ui;margin:2rem;max-width:1200px}table{width:100%;border-collapse:collapse}td,th{padding:.5rem;text-align:left;border-bottom:1px solid #ddd}small{color:#555}</style>",
        "<a href='/v1/operator/today'>Today</a> · <a href='/v1/operator/recurring'>Recurring attention</a> · <a href='/v1/operator/marketing'>Marketing Sources</a><h1>Business Overview</h1>",
        '<p>Read-only · TEST excluded · '+h(view['start'])+' through '+h(view['end_inclusive'])+' · America/Toronto</p>',
        '<p>Source observed '+h(view['observed_at'])+'</p><p>Counts: PROVEN · financial totals: DERIVED DETERMINISTICALLY · recurring Service value: PARTIAL · profitability/advertising return: UNKNOWN</p>',
        "<form method='get'><label>Period <select name='period'>"+''.join("<option value='"+p+"'"+(' selected' if view['period']==p else '')+'>'+h(p.replace('_',' ').title())+'</option>' for p in PERIODS)+"</select></label> <label>From <input type='date' name='start'></label> <label>Through <input type='date' name='end'></label> <button>Show</button></form>",
        "<p><a href='?format=csv&amp;period="+h(view['period'])+'&amp;start='+h(view['start'])+'&amp;end='+h(view['end_inclusive'])+"'>Export these metrics as CSV</a></p>",
        '<h2>Sales</h2>'+table(['Metric','Count'],[(k.replace('_',' ').title(),v) for k,v in view['sales'].items() if isinstance(v,int)]),
        table(['Open Deal stage','Count','Value by currency','Missing value','Oldest days'],[[p[k] for k in ('stage','count','value','missing_value','oldest_days')] for p in view['sales']['pipeline']]),
        table(['Deal','Stage','Age days','Next action'],[[d[k] for k in ('name','stage','age_days','next_action')] for d in view['sales']['deals']]),
        '<p>'+h(view['sales']['reason'])+'</p><h2>Revenue and payments</h2><p>'+h(view['basis'])+'</p>',
        table(['Metric','Value'],[(k.replace('_',' ').title(),val(v) or 'No observed value; check coverage') for k,v in view['financial'].items()]),
        '<h2>Recurring revenue</h2>'+table(['Measure','Observed value'],[(k.replace('_',' ').title(),val(v)) for k,v in view['recurring'].items()]),
        '<p>Normalized recurring net value is before tax and depends on active Books profiles; Service/acquisition linkage remains partial. It is not guaranteed future revenue.</p>',
        '<h2>Customer value</h2><p>Lifetime means the complete bounded observed Books population, not data predating available records.</p>',
        table(['Customer','Observed lifetime invoiced','Paid Invoice value','Period invoiced','Active Services'],[[r[k] for k in ('name','lifetime_invoiced','paid_invoice_value','selected_invoiced','active_services')] for r in view['customer_value']]),
        '<h2>Service revenue</h2>'+table(['Category','Period invoiced'],list(view['service_revenue'].items())),
        '<h2>Marketing</h2><p>Missing source stays UNATTRIBUTED; incomplete lineage is PARTIAL. Spend/ROAS unavailable for this report until matched period/source data exists.</p>',
        table(['Source','Medium','Campaign','Leads','Qualified','Deals','Estimates','Accepted/invoiced','Invoiced','Confidence'],[[r[k] for k in ('source','medium','campaign','leads','qualified_leads','deals','estimates','accepted_estimates','invoice_value','confidence')] for r in view['marketing']]),
        '<h2>Operations and attention</h2>'+table(['Measure','Count'],[('Open Cases',view['operations']['open_cases']),*view['operations']['installation_states'].items()])+"<p><a href='/v1/operator/today'>Work from Today and CRM</a>",
        '<h2>Profitability</h2><p>'+h(view['profitability']['state'])+' · '+h(view['profitability']['reason'])+'</p>',
        '<details><summary>Coverage and gaps</summary><p>'+h(view['optional_read_states'])+'</p>'+table(['Area','Coverage'],list(view['attribution']['coverage'].items())),
        '<p>'+h(view['issues'])+'</p></details></html>']
    return ''.join(parts)


def export_csv(view):
    output=io.StringIO();writer=csv.writer(output);writer.writerow(['section','metric','currency','value','basis','source_observed_at','period_start','period_end'])
    def row(section,metric,code,value,basis):
        cells=[section,metric,code,str(value),basis,view['observed_at'],view['start'],view['end_inclusive']]
        writer.writerow(["'"+c if c.startswith(('=','+','-','@','\t','\r')) else c for c in cells])
    for k,v in view['sales'].items():
        if isinstance(v,int):row('sales',k,'',v,'Observed period/current stock as described')
    for k,values in view['financial'].items():
        for code,value in values.items():row('financial',k,code,value,view['basis'])
    for r in view['marketing']:
        for code,value in r['invoice_value'].items():row('marketing',r['source']+' / '+r['medium'],code,value,r['confidence'])
    for k in ('normalized_monthly_net','annualized_net'):
        for code,value in view['recurring'][k].items():row('recurring',k,code,value,'PARTIAL — active Books billing, before tax')
    row('profitability','gross_margin','','NOT CURRENTLY MEASURABLE','COST DATA INCOMPLETE')
    return output.getvalue()
