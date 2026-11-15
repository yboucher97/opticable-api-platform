"""Owner review on V1's loopback preview. Existing artifact/audit tables only.

Editorial decisions cannot grant publication, spending or deployment authority.
The actor, expiry and exact scope are established by the server, never the client.
"""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import urlencode
from collections import Counter, defaultdict

CATEGORIES = ('Business work','Website improvements','Social content','Articles','Marketing reports','SEO opportunities','Pending decisions')
CHOICES = {'APPROVE','REJECT','REQUEST_REVISION'}


def package_key(item):
    """Grouping is presentation only. Native identities never use fuzzy names."""
    parts=Path(item['logical_path']).parts; path=item['logical_path']
    if len(parts)>2 and parts[0]=='business-work':
        kind,native=parts[1:3]
        if kind in ('response-draft','quote-outline'):return 'inquiry:'+native
        if kind in ('quote-follow-up','quote-review'):return 'quote:'+native
        if kind=='overdue-task':return 'task:'+native
        if kind=='meeting-brief':return 'meeting:'+native
    if 'cabling-review-package' in path:return 'campaign:cabling-fiber'
    if any(x in path for x in ('measurement/','attribution','canonical-funnel','verified-business-funnel')):return 'project:attribution'
    if parts and parts[0]=='campaigns':
        if any(x in parts for x in ('ip-cameras','ip-cameras-ai')):return 'campaign:cameras'
        if 'ai-loss-prevention' in parts:return 'campaign:ai-loss-prevention'
        if any(x in parts for x in ('structured-cabling','fiber-optic-installation')):return 'campaign:cabling-fiber'
        if 'commercial-networking' in parts:return 'campaign:wifi'
        if any(x in parts for x in ('access-control','access-control-systems')):return 'campaign:access-control'
        if any(x in parts for x in ('intercom','intercom-systems')):return 'campaign:intercom'
        return 'campaign:calendar-faq'
    return 'reference:analysis-planning'


def source_date(item):
    dates=[]
    for row in item.get('source_details',[])+item.get('source_evidence',[]):
        if not isinstance(row,dict):continue
        for key in ('observed_at','retrieved_at'):
            try:
                value=datetime.fromisoformat(str(row.get(key,'')).replace('Z','+00:00'))
                if value.tzinfo:dates.append(value)
            except ValueError:pass
    # Earliest cited observation is conservative; registration is not source freshness.
    return min(dates) if dates else None


def package_profile(key, members):
    if key.startswith('task:'):return 105,'Overdue lead follow-up','Confirm the project is still active and review the prepared follow-up.'
    if key.startswith('inquiry:'):return 96,members[0]['title'],'Check whether already answered; review the response and unpriced scope together.'
    if key.startswith('quote:'):
        follow=any('/quote-follow-up/' in a['logical_path'] for a in members)
        return (101 if follow else 82),'Quotation — '+next((re.search(r'EST-\d+',a['title']).group() for a in members if re.search(r'EST-\d+',a['title'])),key.split(':')[1]),'Verify current quote/reply status; select one language alternative before any exact send approval.'
    if key.startswith('meeting:'):return 78,'Partnership meeting preparation','Review the existing agenda and decide the native RSVP after checking the meeting is still current.'
    return {
        'project:attribution':(92,'Website attribution and inquiry tracking','Review the coordinated tracking dependencies; production release remains separately gated.'),
        'campaign:cameras':(87,'Camera campaign and website review','Review existing camera articles,posts,visuals and protected previews together.'),
        'campaign:ai-loss-prevention':(86,'AI loss-prevention campaign','Review existing human-review and compatibility messaging; benefit remains unmeasured.'),
        'campaign:cabling-fiber':(65,'Cabling and fiber handover project','Review existing bilingual field guides,visuals and the private website package.'),
        'campaign:wifi':(64,'Commercial Wi-Fi campaign','Review existing symptom-led posts and scope guidance.'),
        'campaign:access-control':(55,'Access-control campaign','Review the existing bilingual scope and handover guidance when this campaign is needed.'),
        'campaign:intercom':(54,'Intercom campaign','Review existing visitor-call scenarios when this campaign is needed.'),
        'campaign:calendar-faq':(35,'Shared campaign calendar and FAQs','Select already prepared assets; no publishing schedule is activated.'),
        'reference:analysis-planning':(25,'Analysis,completed work and planning','Consult current evidence and plans; historical revisions remain available.')
    }.get(key,(20,'Other retained work','Review when relevant.'))


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',',':'), ensure_ascii=False).encode()).hexdigest()


def category(path):
    if path.startswith('business-work/'):return 'Business work'
    if '/social/' in path or '/social-media/' in path or re.search(r'/(linkedin|facebook|instagram)/', path): return 'Social content'
    if '/articles/' in path or '/website/' in path: return 'Articles'
    if '/seo/' in path or 'ranked-improvements' in path: return 'SEO opportunities'
    if 'measurement/' in path: return 'Website improvements'
    if '/advertising/' in path or '/video/' in path: return 'Pending decisions'
    return 'Marketing reports'


class Review:
    def __init__(self, database, artifacts):
        self.database = Path(database); self.artifacts = Path(artifacts).resolve()

    def catalog(self, query='', section='', urgency='', filter_status=''):
        # Read-only SQL: do not initialize or create a database during a GET.
        with sqlite3.connect(self.database.resolve().as_uri()+'?mode=ro',uri=True) as db:
            db.row_factory=sqlite3.Row
            rows=db.execute("SELECT id,entity,retrieved_at,normalized_value FROM acquisition_facts WHERE source='platform:business_autopilot' ORDER BY retrieved_at,id").fetchall()
            from storage import metadata, operation_id
            lifecycle_states = metadata(db)[2]
            proofs={r['id']:dict(r) for r in db.execute('SELECT id,source,source_url AS url,retrieved_at AS observed_at,effective_from,effective_to FROM acquisition_snapshots')}
        receipts=[]
        for p in sorted(self.artifacts.parent.glob('run-*.json')):
            if not p.is_symlink() and p.stat().st_size<=1024*1024:receipts.append(json.loads(p.read_text()))
        result={}
        for row in rows:
            v=json.loads(row['normalized_value']); logical=v.get('logical_path','')
            if not v.get('path') or not re.fullmatch('[a-f0-9]{64}',v.get('sha256','')):continue
            if lifecycle_states.get(operation_id(v), {}).get('state') in ('QUARANTINE_INTENT','QUARANTINED','DELETE_INTENT','DELETED','RECONCILE_HOLD'):continue
            parts=Path(logical).parts
            lang=next((p for p in parts if p in ('fr','en')),'bilingual')
            service=parts[3] if len(parts)>4 and parts[0]=='campaigns' else 'all services'
            platform=parts[-3] if len(parts)>3 and parts[-2]=='draft' else 'internal'
            item={**v,'id':v['sha256'],'category':category(logical),'language':v.get('language',lang),'service':v.get('service',service),'platform':v.get('platform',platform),
                  'title':Path(logical).stem.replace('-',' ').replace('_',' ').capitalize(),'revision':v['sha256'][:16],'registered_at':row['retrieved_at'],
                  'evidence':v.get('evidence_ids',[]) or self.source_evidence(v['sha256'],logical,receipts),
                  'expected_benefit':'Clarify commercial scope and prepare useful evidence-backed inquiries; conversion lift is unmeasured.',
                  'estimated_cost':{'internal_incremental':'0','currency':'CAD','publication_or_media_spend':'NOT_AUTHORIZED'},
                  'tests':v.get('quality_checks',[]) or ['Registered content hash verified on read','Existing V1 draft-only generation and isolation tests'],
                  'urgency':v.get('urgency','NORMAL'),'expected_business_impact':v.get('expected_impact') or v.get('objective','Prepare clearer project inquiries; lift unmeasured'),
                  'approval_separation':{'editorial':'Accept this exact draft only','required_external_approval':v.get('required_execution_approval','PUBLICATION_OR_DEPLOYMENT_EXACT_SCOPE'),
                     'publication':'Exact artifact + channel + time','website_release':'Exact source commit + manifest + rollback','advertising_or_expense':'Exact account/action + amount/currency + maximum cost',
                     'customer_or_financial':'Exact recipient/record + content/operation; separate financial approval','execution_enabled':False},
                  'execution_scope':{'operation':'EDITORIAL_REVIEW_ONLY','artifact_sha256':v['sha256'],'platform':v.get('platform',platform),
                                     'language':v.get('language',lang),'publication':False,'spending':False,'deployment':False}}
            path=self.artifacts/v['path']
            if v['path'].endswith('.txt') and not path.is_symlink() and path.resolve().is_relative_to(self.artifacts) and path.is_file():
                with path.open() as text_file:item['title']=text_file.readline(500).strip()[:180]
            if section=='Pending decisions':
                if self.status(item,datetime.now(timezone.utc)) not in ('PENDING','REQUEST_REVISION','EXPIRED','EXPIRED_DRAFT'):continue
            elif section and section!=item['category']:continue
            if query and query.casefold() not in json.dumps(item,ensure_ascii=False).casefold():continue
            if urgency and item['urgency']!=urgency:continue
            if filter_status and self.status(item,datetime.now(timezone.utc))!=filter_status:continue
            item['source_details']=[{'snapshot_id':sid,**proofs[sid]} for sid in item['evidence'][:20] if sid in proofs]
            result[item['id']]=item
        return sorted(result.values(),key=lambda x:({'HIGH':0,'MEDIUM':1,'NORMAL':2}.get(x['urgency'],3),x['logical_path']))

    def source_evidence(self, asset_hash, logical, receipts=None):
        # V1 receipts are provenance references, not another artifact registry.
        result=[]
        if receipts is None:
            receipts=[json.loads(p.read_text()) for p in sorted(self.artifacts.parent.glob('run-*.json')) if not p.is_symlink() and p.stat().st_size<=1024*1024]
        for saved in receipts:
            if any(x.get('sha256')==asset_hash or (logical.endswith('.png') and Path(x.get('logical_path','')).parent==Path(logical).parent and x.get('logical_path','').endswith('.svg')) for x in saved.get('manifest',[])):
                result.extend(saved.get('evidence_ids',[]))
        return sorted(set(result))

    def queue(self, now=None, items=None):
        """Derive ranking on read; never persist files,status changes or approvals."""
        now=now or datetime.now(timezone.utc);items=items if items is not None else self.catalog()
        grouped=defaultdict(list); histories={}
        with sqlite3.connect(self.database.resolve().as_uri()+'?mode=ro',uri=True) as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='action_evidence'").fetchone():
                for raw, in db.execute("SELECT evidence_json FROM action_evidence WHERE kind='business_review_decision' ORDER BY event_id"):
                    v=json.loads(raw);histories[v.get('id')]=v
        by_logical=defaultdict(list)
        for item in items:by_logical[item['logical_path']].append(item)
        superseded={a['id']:max(group,key=lambda x:(x['registered_at'],x['id']))['id'] for group in by_logical.values() if len(group)>1 for a in group if a['registered_at']<max(x['registered_at'] for x in group)}
        for original in items:
            item=dict(original);key=package_key(item);at=source_date(item)
            age=(now-at).total_seconds()/3600 if at else None
            threshold=30 if key.startswith(('task:','inquiry:','quote:','meeting:')) else 168
            freshness='UNKNOWN' if age is None or age < -0.0834 else ('STALE' if age>threshold else 'CURRENT')
            labels=[]
            if item['id'] in superseded:labels.append('SUPERSEDED_PRESENTATION')
            if freshness=='STALE':labels.append('STALE_SOURCE')
            if key.startswith('reference:'):labels.append('REFERENCE_LOW_PRIORITY')
            last=histories.get(item['id']);pending=not last or last.get('choice') not in ('APPROVE','REJECT')
            item['queue']={'package_key':key,'freshness':freshness,'source_observed_at':at.isoformat() if at else None,
                'classifications':labels,'superseded_by':superseded.get(item['id']),'pending':pending,'status':last.get('choice') if last else 'PENDING'}
            grouped[key].append(item)
        # Flag likely repetitions only within one project/language/channel.
        # Hashes and original items are retained; similarity never grants disposal.
        for key,group in grouped.items():
            seen=[]
            for item in sorted(group,key=lambda x:(x['registered_at'],x['id']),reverse=True):
                if item.get('business_private') or not item['path'].endswith('.txt'):continue
                p=self.artifacts/item['path']
                if p.is_symlink() or not p.resolve().is_relative_to(self.artifacts) or not p.is_file() or p.stat().st_size>65536:continue
                raw=p.read_bytes()
                if sha256(raw).hexdigest()!=item['sha256']:continue
                tokens=set(re.findall(r'\w+',raw.decode('utf-8').casefold()))
                signature=(item['language'],item['platform'])
                duplicate=next((other for sig,words,other in seen if sig==signature and len(tokens)>=30 and len(tokens & words)/max(1,len(tokens | words))>=0.9),None)
                if duplicate:item['queue']['classifications'].append('POTENTIAL_DUPLICATE');item['queue']['similar_to']=duplicate
                seen.append((signature,tokens,item['id']))
        packages=[]
        for key,members in grouped.items():
            base,title,decision=package_profile(key,members)
            current=[m for m in members if m['queue']['pending'] and 'SUPERSEDED_PRESENTATION' not in m['queue']['classifications']]
            freshness='CURRENT' if any(m['queue']['freshness']=='CURRENT' for m in current) else ('STALE' if current and all(m['queue']['freshness']=='STALE' for m in current) else 'UNKNOWN')
            score=base-(25 if freshness=='STALE' else 4 if freshness=='UNKNOWN' else 0)-(60 if not current else 0)
            for item in members:item['queue']['score']=score-(20 if item['queue']['classifications'] else 0)
            packages.append({'id':digest(key)[:24],'key':key,'title':title,'score':score,'decision':decision,
                'freshness':freshness,'pending_items':sum(m['queue']['pending'] for m in members),'member_count':len(members),
                'status':'PENDING_REVIEW' if current else 'RETAINED_REFERENCE','items':sorted(members,key=lambda m:(-m['queue']['score'],m['logical_path'],m['id'])),
                'manifest_sha256':digest(sorted([m['id'],m['execution_scope']] for m in members)),
                'approval_scope':'INDIVIDUAL_EXACT_DRAFT_ONLY','execution_enabled':False})
        packages.sort(key=lambda p:(-p['score'],p['key']))
        ranked=sorted((m for p in packages for m in p['items']),key=lambda m:(-m['queue']['score'],m['logical_path'],m['id']))
        for rank,item in enumerate(ranked,1):item['queue']['rank']=rank
        latest={};projection=self.artifacts.parent/'latest-cycle.json'
        if not projection.is_symlink() and projection.is_file() and projection.stat().st_size<=1024*1024:latest=json.loads(projection.read_text())
        from business_work import execution_result,fresh
        evidence=latest.get('operational',{})
        analysis=latest.get('analysis',{})
        if not fresh(latest.get('at'),now):analysis={**analysis,'freshness':'STALE_REVIEW_REQUIRED'}
        operational=execution_result({**evidence,'completed':evidence.get('completed_internal',[])},analysis,now)
        actual={p['key']:p for p in packages};sales=[]
        for op in latest.get('business_opportunities',[]):
            prefix={'OVERDUE_NATIVE_TASK':'task:','INQUIRY_SCOPE_REVIEW':'inquiry:','SENT_QUOTE_STATUS_REVIEW':'quote:','MEETING_PREPARATION':'meeting:'}.get(op.get('kind'))
            package=actual.get(str(prefix)+str(op.get('native_id'))) if prefix else None
            if not package:continue
            sales.append({'summary':op.get('summary'),'package_id':package['id'],'native_id':op.get('native_id'),
                'freshness':package['freshness'],'action':'Verify current status and review existing preparation; no send is authorized.',
                'reply_status':op.get('reply_status','UNKNOWN'),'priority':package['score']})
        sales.sort(key=lambda x:(-x['priority'],x['native_id']))
        return {'schema':1,'at':now.isoformat(),'registered_items':len(items),'package_count':len(packages),
            'default_package_limit':10,'default_packages':packages[:10],'packages':packages,'ranked_item_ids':[m['id'] for m in ranked],
            'top_decisions':[{'package_id':p['id'],'title':p['title'],'decision':p['decision'],'freshness':p['freshness']} for p in packages if p['status']=='PENDING_REVIEW'][:5],
            'sales_opportunities':sales,'operational':operational,'classification_counts':dict(Counter(c for p in packages for m in p['items'] for c in m['queue']['classifications'])),
            'completed_summary':{'registered_artifacts_preserved':len(items),'source_analysis_at':latest.get('at'),
                'generation_paused':latest.get('storage',{}).get('optional_paused',True),'existing_opportunities':len(sales),
                'new_content_created_by_view':0,'decisions_changed_by_view':0},'provider_calls':0,'files_written':0}

    def item(self, identifier):
        item=next((x for x in self.catalog() if x['id']==identifier),None)
        if not item:raise ValueError('Unknown registered artifact')
        p=self.artifacts/item['path']
        if p.is_symlink() or not p.resolve().is_relative_to(self.artifacts) or p.stat().st_size>8*1024*1024:
            raise ValueError('Artifact path or size invalid')
        raw=p.read_bytes()
        if sha256(raw).hexdigest()!=item['sha256']:raise ValueError('Artifact revision changed')
        return item,raw

    @staticmethod
    def action_id(item):return 'business-review:'+digest(item['execution_scope'])

    def history(self, item):
        with sqlite3.connect(self.database.resolve().as_uri()+'?mode=ro',uri=True) as db:
            rows=db.execute("SELECT evidence_json FROM action_evidence WHERE action_id=? AND kind='business_review_decision' ORDER BY event_id",(self.action_id(item),)).fetchall()
        return [json.loads(x[0]) for x in rows]

    def status(self, item, now):
        history=self.history(item)
        if not history:
            from storage import POLICY, timestamp
            if item.get('registered_at') and now >= timestamp(item['registered_at']) + timedelta(days=POLICY['draft_days']):return 'EXPIRED_DRAFT'
            return 'PENDING'
        last=history[-1]
        if last['choice']=='APPROVE' and now>=datetime.fromisoformat(last['expires_at']):return 'EXPIRED'
        return last['choice']

    def validate_decision(self, payload, identity, now, *, trusted_actor='owner:opticable-review'):
        if set(payload)-{'id','version','choice','reason','request_id'} or not all(k in payload for k in ('id','version','choice','request_id')):
            raise ValueError('Exact review fields required; actor,scope and expiry are server-controlled')
        if payload['choice'] not in CHOICES or not re.fullmatch('[a-f0-9]{32}',payload['request_id']):raise ValueError('Invalid choice/idempotency')
        reason=payload.get('reason','')
        if not isinstance(reason,str) or len(reason)>1500:raise ValueError('Bounded feedback required')
        if payload['choice']=='REQUEST_REVISION' and not reason.strip():raise ValueError('Revision feedback required')
        if not (trusted_actor=='owner:opticable-review' or re.fullmatch(r'human:[A-Za-z0-9][A-Za-z0-9._:-]{0,127}',trusted_actor)):
            raise PermissionError('Trusted owner actor required')
        if identity.get('actor')!=trusted_actor or now>=identity['expires_at']:
            raise PermissionError('Current authenticated owner identity required')
        item,_=self.item(payload['id'])
        if payload['version']!=item['sha256']:raise ValueError('Exact current artifact revision required')
        return item

    def decision(self, payload, identity, now, *, trusted_actor='owner:opticable-review'):
        from workflow.automation.action_evidence import ActionEvidence,envelope,approval_binding,validate
        item=self.validate_decision(payload,identity,now,trusted_actor=trusted_actor)
        expiry=min(now+timedelta(hours=2),identity['expires_at'])
        event={**payload,'actor':identity['actor'],'at':now.isoformat(),'expires_at':expiry.isoformat(),
               'scope':item['execution_scope'],'binding':digest(item['execution_scope']),'execution_authorized':False}
        aid=self.action_id(item);audit=ActionEvidence(self.database)
        with audit.connect() as db:
            db.execute('BEGIN IMMEDIATE');ActionEvidence.setup(db)
            # Cleanup uses the same SQLite writer lock; never approve a file
            # moved after the initial catalog read.
            from storage import metadata, operation_id
            if metadata(db)[2].get(operation_id(item), {}).get('state') in ('QUARANTINE_INTENT','QUARANTINED','DELETE_INTENT','DELETED','RECONCILE_HOLD'):
                raise ValueError('Artifact entered disposable lifecycle; restore and review exact identity first')
            prior=db.execute("SELECT evidence_json FROM action_evidence WHERE action_id=? AND kind='business_review_decision' AND json_extract(evidence_json,'$.request_id')=?",(aid,payload['request_id'])).fetchone()
            if prior:
                saved=json.loads(prior[0])
                if any(saved.get(k)!=payload.get(k) for k in ('id','version','choice','reason')):raise ValueError('Idempotency conflict')
                return saved
            plan=ActionEvidence.current(db,aid)
            if not plan:
                plan=envelope(aid,'BUSINESS_DRAFT_REVIEW',{'type':'CONTENT_ASSET','identity':item['id']},now,
                    reason='Owner editorial review of exact immutable draft; no external authority',approval_required=True,
                    exact_versions={'artifact_sha256':item['sha256'],'scope':item['execution_scope'],'environment':'private_review'},
                    mutation=False,authority_class='LOCAL_EVIDENCE_ONLY',before_state={'status':'DRAFT_ONLY'})
                ActionEvidence.plan_in(db,plan,now)
            plan.update(approval_record={'actor':identity['actor'],'binding':approval_binding(plan),'at':now.isoformat(),'expires_at':expiry.isoformat()} if payload['choice']=='APPROVE' else None,
                        approval_revision=plan['revision'] if payload['choice']=='APPROVE' else None)
            ActionEvidence.append(db,aid,'universal_state',validate(plan),now)
            ActionEvidence.append(db,aid,'business_review_decision',event,now)
        return event

    def external_authorized(self, item, operation, now):
        # This installed consumer has no publication/spend/deployment adapter.
        # Editorial acceptance cannot be promoted to a provider grant.
        return False

    def render(self, query='', section='', identifier=None, now=None, urgency='', filter_status='', package_identifier=None, view=''):
        now=now or datetime.now(timezone.utc);items=self.catalog(query,section,urgency,filter_status)
        head='''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="robots" content="noindex,nofollow"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Opticable owner review</title><style>body{font:17px/1.5 system-ui;max-width:1150px;margin:30px auto;padding:20px;background:#10251b;color:#f2faf5}a{color:#8df1b2}input,select,textarea,button{font:inherit;padding:10px;margin:6px 0;max-width:100%;box-sizing:border-box}label{display:block}button{cursor:pointer;min-height:44px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#193c2a;padding:18px}article{min-width:0;overflow-wrap:anywhere;padding:18px;border:1px solid #779685;border-radius:12px;margin:15px 0}img{max-width:100%;width:540px}code{overflow-wrap:anywhere}h2{font-size:1.25rem;overflow-wrap:anywhere}.tag{color:#a8efc2}nav a{display:inline-block;padding:10px}#status{min-height:28px}</style></head><body><h1>Opticable owner review</h1><p>Finished drafts and evidence. Decisions accept or reject a draft only. Publication, spending and deployment remain separately gated.</p>'''
        nav='<nav aria-label="Review categories"><a href="/review/">Focus</a><a href="/review/?view=items">All artifacts</a>'+''.join('<a href="/review/?'+urlencode({'category':c})+'">'+escape(c)+'</a>' for c in CATEGORIES)+'</nav>'
        search='<form method="get" action="/review/"><label>Search content metadata <input name="q" value="'+escape(query,quote=True)+'"></label><button>Search</button></form>'
        search=search.replace('<button>Search</button>',
          '<label>Urgency <select name="urgency">'+''.join('<option value="'+x+'"'+(' selected' if x==urgency else '')+'>'+ (x or 'All')+'</option>' for x in ('','HIGH','MEDIUM','NORMAL'))+'</select></label>'+
          '<label>Editorial status <select name="status">'+''.join('<option value="'+x+'"'+(' selected' if x==filter_status else '')+'>'+ (x or 'All')+'</option>' for x in ('','PENDING','APPROVE','REJECT','REQUEST_REVISION','EXPIRED'))+'</select></label><button>Search</button>')
        if identifier:
            item,raw=self.item(identifier);history=self.history(item)
            body='<a href="/review/">Back to all artifacts</a><article><h2>'+escape(item['logical_path'])+'</h2>'
            body+='<p class="tag">'+escape(' | '.join((item['service'],item['platform'],item['language'],item['urgency'],self.status(item,now))))+'</p><p>Draft review only. Separate exact authorization required: '+escape(item['approval_separation']['required_external_approval'])+'. External execution is disabled.</p>'
            if item['path'].endswith(('.png','.svg')):body+='<img alt="Unpublished '+escape(item['service'])+' campaign graphic" src="/review/artifact/'+item['id']+'">'
            else:body+='<pre>'+escape(raw.decode('utf-8'))+'</pre>'
            body+='<details><summary>Evidence, exact revision, cost and tests</summary><pre>'+escape(json.dumps(item,indent=2,ensure_ascii=False))+'</pre></details>'
            body+='<label>Revision feedback <textarea id="reason" maxlength="1500" rows="4"></textarea></label>'
            for choice,label in [('APPROVE','Approve draft'),('REJECT','Reject'),('REQUEST_REVISION','Request revision')]:
                body+='<button type="button" data-decision="'+choice+'">'+label+'</button> '
            body+='<p id="status" role="status" aria-live="polite"></p><h3>Approval audit history</h3><pre>'+escape(json.dumps(history,indent=2,ensure_ascii=False))+'</pre></article>'
            body+='''<script>(async()=>{const initial=await fetch('/review/session',{cache:'no-store'});if(!initial.ok)return;let session=await initial.json();let pending=false;document.querySelectorAll('[data-decision]').forEach(button=>button.addEventListener('click',async()=>{if(pending)return;pending=true;try{const result=await fetch('/review/decision',{method:'POST',headers:{'Content-Type':'application/json','X-Review-CSRF':session.csrf},body:JSON.stringify({id:ITEM_ID,version:ITEM_VERSION,choice:button.dataset.decision,reason:document.querySelector('#reason').value,request_id:crypto.randomUUID().replaceAll('-','')})});const data=await result.json();document.querySelector('#status').textContent=result.ok?'Recorded '+data.choice+'. External execution remains disabled.':data.error;}finally{pending=false;}}));setInterval(async()=>{const response=await fetch('/review/session/refresh',{method:'POST',headers:{'X-Review-CSRF':session.csrf}});if(response.ok)session=await response.json();},600000);})();</script>'''.replace('ITEM_ID',json.dumps(item['id'])).replace('ITEM_VERSION',json.dumps(item['sha256']))
        else:
            queue=self.queue(now,items);summary=queue['completed_summary']
            body='<section aria-labelledby="completed"><h2 id="completed">Completed work</h2><p>'+str(len(items))+' existing artifacts organized into '+str(queue['package_count'])+' review packages. No content generated or decisions changed by this view.</p><p>Current analysis and business planning continue. '+('New review files are paused at the admission limits.' if summary['generation_paused'] else 'Existing admission limits apply.')+'</p></section>'
            operational=queue['operational'];weekly=operational['weekly']
            if operational['cases']:
                body+='<section aria-labelledby="daily"><h2 id="daily">Verified internal work and next actions</h2><p>Source checks: '+escape(str(operational.get('captured_at')))+'. No customer-facing action completed.</p><ul>'
                for done in operational['completed_internal']:body+='<li>'+escape(done)+'</li>'
                body+='</ul><ol>'
                for case in operational['top_attention']:
                    body+='<li><strong>'+escape(case['title'])+'</strong> — '+escape(case['status'])+' ('+escape(case['freshness'])+'). '+escape(case['next_action'])+'<p>'+escape(case['blocker'])+'</p>'
                    if case.get('view_evidence'):body+='<p>'+escape(case['view_evidence'])+'</p>'
                    body+='</li>'
                body+='</ol><details><summary>All verified operational context and exact source references</summary><pre>'+escape(json.dumps(operational['cases'],ensure_ascii=False,indent=2))+'</pre></details></section>'
            if weekly.get('period'):
                body+='<section aria-labelledby="weekly"><h2 id="weekly">Weekly measured performance</h2><p>'+escape(str(weekly['period']))+'; '+escape(str(weekly['freshness']))+'. GA4 sessions '+escape(str(weekly['sessions']))+' vs '+escape(str(weekly['previous_sessions']))+'; key events '+escape(str(weekly['key_events']))+'. Search clicks '+escape(str(weekly['gsc_clicks']))+' vs '+escape(str(weekly['gsc_previous_clicks']))+'; impressions '+escape(str(weekly['gsc_impressions']))+' vs '+escape(str(weekly['gsc_previous_impressions']))+'.</p><p>'+escape(weekly['meaning'])+' Qualified leads and attributed revenue remain unknown.</p></section>'
            body+='<section aria-labelledby="decisions"><h2 id="decisions">Five most valuable pending decisions</h2><ol>'
            for decision in queue['top_decisions']:
                body+='<li><a href="/review/?package='+decision['package_id']+'">'+escape(decision['title'])+'</a>: '+escape(decision['decision'])+'</li>'
            body+='</ol></section>'
            if queue['sales_opportunities']:
                body+='<section aria-labelledby="sales"><h2 id="sales">Sales opportunities requiring a status check</h2><ul>'
                for op in queue['sales_opportunities'][:5]:
                    body+='<li><a href="/review/?package='+op['package_id']+'">'+escape(op['summary'])+'</a> — '+escape(op['freshness'])+' source evidence; reply status '+escape(op['reply_status'])+'. Check current status before acting.</li>'
                body+='</ul></section>'
            if view=='items' or query or section or urgency or filter_status:
                rank_order={identifier:rank for rank,identifier in enumerate(queue['ranked_item_ids'])}
                items=sorted(items,key=lambda item:rank_order[item['id']])
                body+='<h2>Searchable artifact inventory</h2><p>'+str(len(items))+' matches. Every exact draft remains individually reviewable.</p>'
                for item in items:
                    body+='<article data-artifact="'+item['id']+'"><h2><a href="/review/item/'+item['id']+'">'+escape(item['title'])+'</a></h2><p>'+escape(item['logical_path'])+'</p><p>SHA256 <code>'+item['sha256']+'</code>. '+escape(self.status(item,now))+'</p></article>'
            else:
                packages=queue['packages'] if view=='all' else queue['default_packages']
                if package_identifier:
                    packages=[p for p in queue['packages'] if p['id']==package_identifier]
                    if not packages:raise ValueError('Unknown review package')
                body+='<h2>'+('Review package' if package_identifier else 'Priority review packages')+'</h2><p>Showing '+str(len(packages))+' of '+str(queue['package_count'])+' packages. <a href="/review/?view=all">Browse every package</a> | <a href="/review/?view=items">Search all '+str(len(items))+' artifacts</a>. Priority is a review aid; business lift remains unmeasured.</p>'
                for package in packages:
                    body+='<article data-package="'+package['id']+'"><h2><a href="/review/?package='+package['id']+'">'+escape(package['title'])+'</a></h2><p>'+str(package['member_count'])+' retained artifacts | '+escape(package['freshness'])+' source evidence</p><p>'+escape(package['decision'])+'</p>'
                    if package['key']=='campaign:cameras':body+='<p><a href="/fr/services/systemes-cameras-securite/">Private French camera preview</a> | <a href="/en/services/security-camera-systems/">Private English camera preview</a></p>'
                    if package['key']=='project:attribution':body+='<p><a href="/experiments/inquiry-attribution/">Protected tracking preview</a></p>'
                    if package['key']=='campaign:cabling-fiber':body+='<p><a href="/experiments/cabling-handover/">Private cabling preview</a></p>'
                    body+='<details'+(' open' if package_identifier else '')+'><summary>Individual drafts,hashes and exact approval scopes</summary><ul>'
                    for member in package['items']:
                        labels=member['queue']['classifications']
                        body+='<li><a href="/review/item/'+member['id']+'">'+escape(member['title'])+'</a> — '+escape(member['language'])+'; '+escape(member['queue']['status'])+('<p>'+escape(', '.join(labels))+'</p>' if labels else '')+'<p>SHA256 <code>'+member['sha256']+'</code></p><p>'+escape(member['approval_separation']['required_external_approval'])+'; editorial acceptance applies to this exact individual draft only.</p></li>'
                    body+='</ul></details><p>No package-wide approval or execution. All originals remain recoverable.</p></article>'
        return (head+nav+search+body+'</body></html>').encode()
