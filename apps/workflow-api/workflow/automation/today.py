"""Read-only attention home. Display data never authorizes a consequential action."""
from copy import deepcopy
from datetime import datetime, timezone
from html import escape
from threading import Lock
from time import monotonic
import json
import os
from pathlib import Path
import stat

from .business_autonomy import attention_scope
from .operations import build_operations
from .read_inventory_cache import build_lifecycle_display
from .sales_queue import build_sales_queue
from .sales_operator_view import CONTROLLED_LEAD_ID

CATEGORIES=('Leads needing response','Follow-ups due','Quote-ready opportunities',
            'Projects and install work','Maintenance and renewal','Sales research','Exceptions','Approvals')
LINKS={'sales':'/v1/operator/phase8/sales-queue','today sales':'/v1/operator/sales','lifecycle':'/v1/operator/phase10/customer-lifecycle',
       'business overview':'/v1/operator/business','recurring':'/v1/operator/recurring','marketing sources':'/v1/operator/marketing','operations':'/v1/operator/phase11/operations',
       'exceptions':'/v1/operator/phase12/exceptions','approvals':'/v1/operator/phase12/approvals',
       'health':'/v1/operator/system-health','test':'/v1/operator/phase12/autonomy'}


class TodaySources:
    """One small, live-only 60-second display cache per authenticated router."""
    def __init__(self,client,db_path,account_id,from_address):
        self.client=client;self.path=db_path;self.account=account_id;self.sender=from_address
        self.lock=Lock();self.cache={}
    def read(self,name,now):
        if name not in {'sales','lifecycle','operations'}:raise ValueError('Unknown Today source')
        with self.lock:
            saved=self.cache.get(name)
            if saved and 0<=monotonic()-saved[0]<60:return deepcopy(saved[1])
            if name=='sales':value=build_sales_queue(self.client,self.path,account_id=self.account,from_address=self.sender,scope='live',now=now)
            elif name=='lifecycle':value=build_lifecycle_display(self.client,self.path.with_name('phase10-service-events.db'),scope='live',now=now)
            else:value=build_operations(self.client,scope='live',now=now)
            self.cache[name]=(monotonic(),deepcopy(value))
            return value


def read_internal_attention(now,path=None):
    """Root-owned display projection; never grants authority or executes actions."""
    path=path or Path('/run/optibrain-readiness/lifecycle.json')
    try:
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
        with os.fdopen(fd) as f:
            s=os.fstat(f.fileno())
            if s.st_uid!=0 or s.st_mode&0o022 or not stat.S_ISREG(s.st_mode) or s.st_size>262144:return None
            value=json.load(f)
        at=datetime.fromisoformat(value['at'])
        if at.tzinfo is None or not 0<=(now-at).total_seconds()<=900:return None
        if value.get('schema')!=1 or value.get('scope')!='live' or value.get('read_only') is not True:return None
        return value
    except (OSError,ValueError,KeyError,TypeError):return None

def build_today(sales,lifecycle,operations,journal,readiness,*,now=None,unavailable=(),internal=None,communications=None,recurring=None,sales_intelligence=None):
    now=now or datetime.now(timezone.utc)
    sections={name:[] for name in CATEGORIES}
    def add(category,context,why,next_action,source,link,*,priority='MEDIUM',due=None,freshness=None):
        sections[category].append(dict(priority=priority,context=context,why=why,next_action=next_action,
                                      due=due,freshness=freshness,source=source,link=link))
    # Require the already-filtered live models; never render Lab data as urgency.
    for model in (sales,lifecycle,operations):
        if model and model.get('scope','live')!='live':raise ValueError('Today requires live display scope')
    for row in sales.get('rows',[]):
        if row.get('test_only') or str(row.get('name','')).startswith('OPTIBRAIN TEST'):continue
        context=row.get('name') or row.get('company') or 'Lead needing review'
        identity=str(row.get('id',''))
        link=('/v1/operator/phase8/sales-view/'+identity if identity==CONTROLLED_LEAD_ID
              else LINKS['sales']+'#lead-'+identity if identity.isdecimal() else LINKS['sales'])
        details=dict(priority=row.get('priority','MEDIUM'),due=row.get('deadline'),freshness=sales.get('read_at'))
        if row.get('reply') in {'REPLIED','REPLIED — NEEDS RESPONSE'} or row.get('followup')=='REPLIED — REVIEW RESPONSE':
            category='Leads needing response'
        elif row.get('followup') in {'DUE','OVERDUE'}:category='Follow-ups due'
        elif row.get('quote')=='READY FOR QUOTE':category='Quote-ready opportunities'
        elif row.get('priority')!='LOW' and row.get('followup')!='WAIT':category='Leads needing response'
        else:continue
        guard=(sales_intelligence or {}).get('lead_guards',{}).get(identity,{})
        if guard.get('outreach_owner')=='CLAUDE_APOLLO':
            add(category,context,'Already owned by Claude/Apollo; coordinate existing outreach',
                'Review the existing Apollo conversation before any follow-up','Apollo and CRM identity evidence',LINKS['today sales'],**details)
        elif guard.get('suppressed'):
            add(category,context,'Sales contact is suppressed','Review suppression; no outreach','Apollo suppression evidence',LINKS['sales'],**details)
        else:add(category,context,row.get('reason'),row.get('action'),'CRM and verified Mail evidence',link,**details)
    for row in lifecycle.get('rows',[]):
        if row.get('test_only'):continue
        if row.get('maintenance_due') or row.get('renewal_due'):
            add('Maintenance and renewal',row.get('account'),row.get('reason'),row.get('action'),
                'CRM service history',LINKS['recurring'] if row.get('renewal_due') else LINKS['lifecycle'],
                priority='HIGH',due=row.get('next_review'),freshness=lifecycle.get('read_at'))
        elif row.get('stage') in {'ACTIVE PROJECT','ACTIVE OPPORTUNITY'}:
            add('Projects and install work',row.get('account'),row.get('reason'),row.get('action'),
                'CRM lifecycle',LINKS['lifecycle'],freshness=lifecycle.get('read_at'))
    for row in operations.get('projects',[]):
        if row.get('test_only') or row.get('action')=='No action':continue
        # Current project registry is TEST_ONLY; keep it out of Today even if a
        # future producer accidentally labels its outer response live.
        if row.get('scope')=='lab' or operations.get('note','').startswith('Synthetic'):continue
        link='/v1/operator/phase11/project/'+str(row['id'])
        add('Projects and install work',row.get('customer') or row.get('name') or row['id'],
            row.get('reason') or 'Recorded work requires review',row.get('action'),'Verified project relationships',
            link,priority='HIGH',freshness=operations.get('read_at'))
    for row in journal.get('actions',[]):
        if attention_scope(row)!='REAL CURRENT':continue
        if row['state']=='approval_required':category='Approvals'
        elif row['state'] in {'reconcile','stale','failed','deferred'}:category='Exceptions'
        else:continue
        add(category,str(row.get('target_module'))+' '+str(row.get('target_id')),row.get('reason'),
            'Reconcile exact evidence before any retry' if row['state']=='reconcile' else 'Review the existing action evidence',
            'Immutable action journal',LINKS[category.lower()],priority='HIGH',freshness=row.get('updated_at'))
    signals=[r for r in readiness.get('signals',[]) if r['state']!='OK']
    if internal:
        if internal.get('scope')!='live' or internal.get('read_only') is not True:raise ValueError('Internal Today projection must be read-only live evidence')
        for row in internal.get('attention',[]):
            if row.get('test_only') or 'OPTIBRAIN TEST' in str(row.get('context','')).upper():continue
            module=row.get('module');identity=str(row.get('identity',''))
            link='https://crm.zoho.com/crm/org763070937/tab/'+module+'/'+identity if module in {'Leads','Deals','Installations','Tasks'} and identity.isdecimal() else LINKS['health']
            add('Exceptions' if row.get('priority')=='HIGH' else 'Projects and install work',row.get('context'),row.get('why'),row.get('next_action'),'Scoped internal lifecycle',link,priority=row.get('priority','MEDIUM'),freshness=internal.get('at'))
        signals.append({'name':'Internal lifecycle','state':'ACTION REQUIRED' if internal.get('state')=='HOLD' else 'OK','reason':internal.get('state','UNKNOWN')})
    if communications:
        if communications.get('scope')!='live' or communications.get('read_only') is not True:raise ValueError('Customer projection must be read-only live evidence')
        for row in communications.get('attention',[]):
            if row.get('test_only'):continue
            identity=str(row.get('identity',''))
            link='https://crm.zoho.com/crm/org763070937/tab/Deals/'+identity if identity.isdecimal() else LINKS['health']
            add('Exceptions',row.get('context'),row.get('why'),row.get('next_action'),'Customer communication evidence',link,
                priority=row.get('priority','HIGH'),freshness=communications.get('at'))
        signals.append({'name':'Customer communications','state':'ACTION REQUIRED' if communications.get('attention') else 'OK','reason':communications.get('state','UNKNOWN')})
    if recurring:
        if recurring.get('scope')!='live' or recurring.get('read_only') is not True:raise ValueError('Recurring projection must be read-only live evidence')
        for row in recurring.get('attention',[]):
            if row.get('test_only'):continue
            module=row.get('module');identity=str(row.get('identity',''))
            link='https://crm.zoho.com/crm/org763070937/tab/'+module+'/'+identity if module in {'Services','Service_Locations','Accounts'} and identity.isdecimal() else LINKS['recurring']
            add('Maintenance and renewal',row.get('context'),row.get('why'),row.get('next_action'),
                'Native CRM and Books recurring observations',link,priority=row.get('priority','MEDIUM'),freshness=recurring.get('observed_at'))
    if sales_intelligence:
        if sales_intelligence.get('scope')!='live' or sales_intelligence.get('read_only') is not True:raise ValueError('Sales projection must be read-only live evidence')
        for row in sales_intelligence.get('rows',[]):
            if row.get('kind') not in {'apollo_reply','trigger'}:continue
            add('Leads needing response' if row['kind']=='apollo_reply' else 'Sales research',
                row['title'],row['why'],row['action'],'Apollo reply / public project evidence',LINKS['today sales'],
                priority='HIGH' if row['kind']=='apollo_reply' else 'MEDIUM',freshness=sales_intelligence.get('observed_at'))
    for name in unavailable:
        signals.append(dict(name=name,state='ACTION REQUIRED',reason='Current business evidence unavailable; open its source view'))
    order={'HIGH':0,'MEDIUM':1,'LOW':2}
    for name,rows in sections.items():rows.sort(key=lambda row:(order.get(row['priority'],1),str(row['due'] or ''),str(row['context'])))
    return dict(schema=1,read_only=True,at=now.isoformat(),sections=sections,system=signals,
                scope_counts=journal.get('attention_scopes',{}),links=LINKS,
                source_freshness={name:model.get('read_at') for name,model in [('Sales',sales),('Lifecycle',lifecycle),('Operations',operations)]},
                attention_count=sum(len(rows) for rows in sections.values()))


def render_today(view):
    h=lambda value:escape(str(value if value is not None else 'Not recorded'),quote=True)
    parts=["<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>",
           "<title>OptiBrain · Today</title><style>body{font:16px/1.5 system-ui;max-width:1050px;margin:2rem auto;padding:0 1rem;color:#182536}nav{display:flex;flex-wrap:wrap;gap:1rem}article{border:1px solid #cdd6df;border-radius:8px;padding:1rem;margin:1rem 0}small{color:#526174}a{color:#075aa7}.priority{font-weight:700}h2{margin-top:2rem}</style></head><body>",
           f"<h1>Today</h1><p>What needs my attention now?</p><p>{h(view['attention_count'])} business items requiring review · Read-only</p>",
           '<nav>'+''.join(f"<a href='{h(link)}'>{h(name.title())}</a>" for name,link in LINKS.items() if name!='test')+'</nav>']
    for name,rows in view['sections'].items():
        parts.append(f'<section><h2>{h(name)} · {len(rows)}</h2>')
        if not rows:parts.append('<p>No attention item found in the available bounded evidence.</p>')
        for row in rows[:20]:
            parts.append(f"<article><span class='priority'>{h(row['priority'])}</span> · <b>{h(row['context'])}</b><p>{h(row['why'])}</p><p><b>Next:</b> {h(row['next_action'])} · Due {h(row['due'])}</p><small>Observed {h(row['freshness'])} · Source {h(row['source'])}</small><p><a href='{h(row['link'])}'>Review details</a></p></article>")
        if len(rows)>20:parts.append('<p>More items are available in the source view.</p>')
        parts.append('</section>')
    parts.append("<h2>System attention</h2><p>Unavailable or stale evidence may limit the business items shown above.</p>")
    for row in view['system']:parts.append(f"<p><b>{h(row['state'])}</b> · {h(row['name'])}: {h(row['reason'])}</p>")
    parts.append(f"<p><a href='{LINKS['health']}'>Operations / System Health</a></p><details><summary>Test Lab and historical evidence</summary><p>These counts are excluded from current business urgency.</p>")
    for name,count in view['scope_counts'].items():parts.append(f'<p>{h(name)}: {h(count)}</p>')
    parts.append(f"<a href='{LINKS['test']}'>Review retained action evidence</a></details><p><small>Bounded source lists and observed timestamps apply. No send or business execution is offered here.</small></p></body></html>")
    return ''.join(parts)


def render_system_health(view):
    h=lambda value:escape(str(value),quote=True)
    rows=''.join(f"<tr><td>{h(r['name'])}</td><td>{h(r['state'])}</td><td>{h(r['reason'])}</td><td>{h(r.get('observed_at') or 'Unavailable')}</td></tr>" for r in view['signals'])
    return ("<!doctype html><html lang='en'><meta charset='utf-8'><title>OptiBrain System Health</title>"
            "<style>body{font:16px system-ui;margin:2rem}td,th{padding:.5rem;text-align:left;border-bottom:1px solid #ddd}</style>"
            f"<a href='/v1/operator/today'>Today</a><h1>System Health · {h(view['state'])}</h1><p>Release {h(view.get('deployment_sha'))}</p>"
            '<table><tr><th>Signal</th><th>State</th><th>Meaning</th><th>Observed</th></tr>'+rows+'</table></html>')
