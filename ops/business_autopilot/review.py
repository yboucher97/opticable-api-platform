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

CATEGORIES = ('Business work','Website improvements','Social content','Articles','Marketing reports','SEO opportunities','Pending decisions')
CHOICES = {'APPROVE','REJECT','REQUEST_REVISION'}


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
            rows=db.execute("SELECT id,entity,retrieved_at,normalized_value FROM acquisition_facts WHERE source='platform:business_autopilot' ORDER BY retrieved_at,id LIMIT 3000").fetchall()
        result={}
        for row in rows:
            v=json.loads(row['normalized_value']); logical=v.get('logical_path','')
            if not v.get('path') or not re.fullmatch('[a-f0-9]{64}',v.get('sha256','')):continue
            parts=Path(logical).parts
            lang=next((p for p in parts if p in ('fr','en')),'bilingual')
            service=parts[3] if len(parts)>4 and parts[0]=='campaigns' else 'all services'
            platform=parts[-3] if len(parts)>3 and parts[-2]=='draft' else 'internal'
            item={**v,'id':v['sha256'],'category':category(logical),'language':v.get('language',lang),'service':v.get('service',service),'platform':v.get('platform',platform),
                  'title':Path(logical).stem.replace('-',' ').replace('_',' ').capitalize(),'revision':v['sha256'][:16],'registered_at':row['retrieved_at'],
                  'evidence':v.get('evidence_ids',[]) or self.source_evidence(v['sha256'],logical),
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
                if self.status(item,datetime.now(timezone.utc)) not in ('PENDING','REQUEST_REVISION','EXPIRED'):continue
            elif section and section!=item['category']:continue
            if query and query.casefold() not in json.dumps(item,ensure_ascii=False).casefold():continue
            if urgency and item['urgency']!=urgency:continue
            if filter_status and self.status(item,datetime.now(timezone.utc))!=filter_status:continue
            with sqlite3.connect(self.database.resolve().as_uri()+'?mode=ro',uri=True) as proof_db:
                item['source_details']=[{'snapshot_id':x[0],'source':x[1],'url':x[2],'observed_at':x[3],'effective_from':x[4],'effective_to':x[5]} for sid in item['evidence'][:20] for x in proof_db.execute('SELECT id,source,source_url,retrieved_at,effective_from,effective_to FROM acquisition_snapshots WHERE id=?',(sid,))]
            result[item['id']]=item
        return sorted(result.values(),key=lambda x:({'HIGH':0,'MEDIUM':1,'NORMAL':2}.get(x['urgency'],3),x['logical_path']))

    def source_evidence(self, asset_hash, logical):
        # V1 receipts are provenance references, not another artifact registry.
        result=[]
        for p in sorted(self.artifacts.parent.glob('run-*.json'))[-30:]:
            if p.stat().st_size>1024*1024:continue
            saved=json.loads(p.read_text())
            if any(x.get('sha256')==asset_hash or (logical.endswith('.png') and Path(x.get('logical_path','')).parent==Path(logical).parent and x.get('logical_path','').endswith('.svg')) for x in saved.get('manifest',[])):
                result.extend(saved.get('evidence_ids',[]))
        return sorted(set(result))

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
        if not history:return 'PENDING'
        last=history[-1]
        if last['choice']=='APPROVE' and now>=datetime.fromisoformat(last['expires_at']):return 'EXPIRED'
        return last['choice']

    def decision(self, payload, identity, now):
        from workflow.automation.action_evidence import ActionEvidence,envelope,approval_binding,validate
        if set(payload)-{'id','version','choice','reason','request_id'} or not all(k in payload for k in ('id','version','choice','request_id')):
            raise ValueError('Exact review fields required; actor,scope and expiry are server-controlled')
        if payload['choice'] not in CHOICES or not re.fullmatch('[a-f0-9]{32}',payload['request_id']):raise ValueError('Invalid choice/idempotency')
        reason=payload.get('reason','')
        if not isinstance(reason,str) or len(reason)>1500:raise ValueError('Bounded feedback required')
        if payload['choice']=='REQUEST_REVISION' and not reason.strip():raise ValueError('Revision feedback required')
        if identity.get('actor')!='owner:opticable-review' or now>=identity['expires_at']:
            raise PermissionError('Current authenticated owner identity required')
        item,_=self.item(payload['id'])
        if payload['version']!=item['sha256']:raise ValueError('Exact current artifact revision required')
        expiry=min(now+timedelta(hours=2),identity['expires_at'])
        event={**payload,'actor':identity['actor'],'at':now.isoformat(),'expires_at':expiry.isoformat(),
               'scope':item['execution_scope'],'binding':digest(item['execution_scope']),'execution_authorized':False}
        aid=self.action_id(item);audit=ActionEvidence(self.database)
        with audit.connect() as db:
            db.execute('BEGIN IMMEDIATE');ActionEvidence.setup(db)
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

    def render(self, query='', section='', identifier=None, now=None, urgency='', filter_status=''):
        now=now or datetime.now(timezone.utc);items=self.catalog(query,section,urgency,filter_status)
        head='''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="robots" content="noindex,nofollow"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Opticable owner review</title><style>body{font:17px/1.5 system-ui;max-width:1150px;margin:30px auto;padding:20px;background:#10251b;color:#f2faf5}a{color:#8df1b2}input,select,textarea,button{font:inherit;padding:10px;margin:6px 0;max-width:100%;box-sizing:border-box}label{display:block}button{cursor:pointer;min-height:44px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#193c2a;padding:18px}article{min-width:0;overflow-wrap:anywhere;padding:18px;border:1px solid #779685;border-radius:12px;margin:15px 0}img{max-width:100%;width:540px}code{overflow-wrap:anywhere}h2{font-size:1.25rem;overflow-wrap:anywhere}.tag{color:#a8efc2}nav a{display:inline-block;padding:10px}#status{min-height:28px}</style></head><body><h1>Opticable owner review</h1><p>Finished drafts and evidence. Decisions accept or reject a draft only. Publication, spending and deployment remain separately gated.</p>'''
        nav='<nav aria-label="Review categories"><a href="/review/">All</a>'+''.join('<a href="/review/?'+urlencode({'category':c})+'">'+escape(c)+'</a>' for c in CATEGORIES)+'</nav>'
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
            body='<p>'+str(len(items))+' registered artifacts. <a href="/fr/services/systemes-cameras-securite/">French camera preview</a> | <a href="/en/services/security-camera-systems/">English camera preview</a> | <a href="/review/website-package">Website review evidence</a> | <a href="/experiments/inquiry-attribution/">Protected tracking correction</a> | <a href="/experiments/cabling-handover/">New bilingual cabling review</a></p>'
            for item in items:
                body+='<article><h2><a href="/review/item/'+item['id']+'">'+escape(item['title'])+'</a></h2><p>'+escape(' | '.join((item['category'],item['service'],item['platform'],item['language'],item['urgency'],self.status(item,now))))+'</p><p>'+escape(item['expected_business_impact'])+'</p><p>Revision <code>'+item['revision']+'</code>; internal incremental cost $0. Separate exact approval: '+escape(item['approval_separation']['required_external_approval'])+'. Public execution disabled.</p></article>'
        return (head+nav+search+body+'</body></html>').encode()
