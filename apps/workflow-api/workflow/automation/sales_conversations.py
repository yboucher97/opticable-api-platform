"""Bounded sales context and actual draft preparation; no provider writers.

Facts, deterministic classifications and inferred buying intent stay separate.
Private immutable conversation revisions reuse the existing research journal.
"""
from collections import Counter
from datetime import timedelta
from html import escape, unescape
import json, re, sqlite3, unicodedata
from .acquisition_store import digest, safe
from .sales_intelligence import email, domain, stamp, live, contact_state
from .prospect_enrichment import useful_role

OWNERS={'APOLLO_CLAUDE','OPTIBRAIN_FUTURE','OWNER_MANUAL','CRM_INBOUND','CUSTOMER_RELATIONSHIP','OTHER'}
CLASSES={'POSITIVE_INTEREST','ASKING_QUESTION','MEETING_INTEREST','QUOTE_INTEREST','REFERRAL','FOLLOW_UP_LATER','NOT_NOW','NOT_INTERESTED','WRONG_PERSON','LEFT_COMPANY','AUTO_REPLY','OUT_OF_OFFICE','UNSUBSCRIBE','BOUNCE','OTHER','UNKNOWN'}

def plain(value):
    value=re.sub(r'(?is)<(style|script)\b[^>]*>.*?</\1>', '', str(value or ''))
    # Keep the author's portion before quoted HTML even when the provider does
    # not include a visible From/De header. Never classify a quoted send footer.
    quoted=re.search(r'''(?is)<blockquote\b|<div\b[^>]*class=["'][^"']*(?:gmail_quote|zmail_extra)''',value)
    if quoted:value=value[:quoted.start()]
    value=re.sub(r'(?i)<br\s*/?>|</(?:p|div|li)>','\n',value)
    value=unescape(re.sub('<[^>]*>',' ',value)).replace('\xa0',' ')
    lines=[]
    for line in value.splitlines():
        line=line.strip()
        if re.match(r'(?i)^(from|de|envoyé|sent|objet|subject)\s*:|^[- ]*(on .+ wrote|le .+écrit|original message|message d.origine)|^>',line):break
        if re.match(r'(?i)^avis\s*:|^notice\s*:|^vous appréciez nos services|^this e.mail (and|is)',line):break
        if '{' in line and '}' in line:continue  # Already flattened provider CSS.
        if line:lines.append(line)
    return '\n'.join(lines)[:2000]

def folded(value):
    return ''.join(c for c in unicodedata.normalize('NFKD',value.casefold()) if not unicodedata.combining(c))

def author_text(body,name):
    result=[]
    for line in plain(body).splitlines():
        if name and folded(line.strip())==folded(name.strip()):break
        result.append(line)
    return '\n'.join(result)

def classify(body,headers=None):
    """Explicit intent rules; ambiguous replies are retained for human review."""
    headers={str(k).lower():str(v).lower() for k,v in (headers or {}).items()}
    text=folded(plain(body)); label='UNKNOWN';confidence='INSUFFICIENT'
    checks=[('UNSUBSCRIBE',r'unsubscribe|desabonn|retirez.{0,30}(liste|courriel)|remove me|stop (email|contact)|ne (me|nous) contactez plus'),
            ('BOUNCE',r'undeliverable|delivery (failed|failure)|adresse.{0,20}invalide'),
            ('OUT_OF_OFFICE',r'out of (the )?office|absence du bureau|absent.{0,20}bureau|en vacances'),
            ('LEFT_COMPANY',r'left the company|no longer (work|with)|ne travaille plus|quitte l.entreprise'),
            ('WRONG_PERSON',r'wrong person|pas la bonne personne'),
            ('NOT_NOW',r'pas.{0,35}(pour le moment|en ce moment)|not (right )?now|si (jamais |nos )?(le besoin|besoins)|if (our )?needs change|rarement ce type'),
            ('NOT_INTERESTED',r'not interested|pas interesse|aucun interet|ne souhait.{0,25}(pas|plus)'),
            ('FOLLOW_UP_LATER',r'recontact|contact.{0,10}(later|next month)|revenez.{0,15}(mois|semaine)|rappelez.{0,20}(mois|semaine)'),
            ('REFERRAL',r'en copie|votre contact principal|refer.{0,25}(colleague|collegue)|forwarded|pour vous\.\.'),
            ('QUOTE_INTEREST',r'(?:demande|besoin|envoy|pouvez|voudrais|could|need|send).{0,55}(?:soumission|devis|estimate|quote)|quel.{0,25}(prix|cout)|how much|what.{0,12}price'),
            ('MEETING_INTEREST',r'disponible.{0,25}(repondre|discuter)|disponibilite.{0,20}(appel|call)|discussion pourrait|au plaisir de discuter|schedule.{0,15}(call|meeting)|rencontre|rendez.vous'),
            ('ASKING_QUESTION',r'\?|pouvez.vous|could you|can you'),
            ('POSITIVE_INTEREST',r'certainement interesse|would be interested|happy to discuss|ouvert.{0,15}echanger')]
    if headers.get('auto-submitted') not in {None,'no'} or headers.get('x-autoreply') or headers.get('x-autorespond'):
        label='OUT_OF_OFFICE' if re.search(checks[2][1],text) else 'AUTO_REPLY';confidence='MODERATE'
    else:
        for candidate,pattern in checks:
            if re.search(pattern,text):label=candidate;confidence='MODERATE';break
    if re.match(r'^pour vous[. ]*(?:\n|$)',text):label='REFERRAL';confidence='TENTATIVE'
    if re.search(r'opere.{0,20}(ville|region).{0,25}seulement',text):label='OTHER';confidence='MODERATE'
    urgency={'QUOTE_INTEREST':'HOT','MEETING_INTEREST':'HOT','ASKING_QUESTION':'HIGH','POSITIVE_INTEREST':'HIGH','REFERRAL':'MEDIUM','FOLLOW_UP_LATER':'MEDIUM'}.get(label,'LOW' if label=='UNKNOWN' else 'NONE')
    return {'reply_class':label,'urgency':urgency,'confidence':confidence,
            'commercial_intent':'POSSIBLE — HUMAN QUALIFICATION REQUIRED' if urgency in {'HOT','HIGH','MEDIUM'} else 'NOT PROVEN',
            'classification_method':'DETERMINISTIC_RULES_V1','execution_authorized':False}

def relationship(contact,crm):
    exact={m:[r for r in crm.get(m,[]) if live(r) and email(r.get('Email'))==email(contact.get('email')) and email(contact.get('email'))] for m in ('Leads','Contacts')}
    account_ids={str((r.get('Account_Name') or {}).get('id')) for r in exact['Contacts'] if isinstance(r.get('Account_Name'),dict)}
    accounts=[r for r in crm.get('Accounts',[]) if live(r) and (str(r.get('id')) in account_ids or domain(r.get('Website'))==domain(contact.get('email','').split('@')[-1]) and domain(r.get('Website')))]
    aids={str(r['id']) for r in accounts}
    deals=[r for r in crm.get('Deals',[]) if live(r) and not re.search('closed|lost|perdu',str(r.get('Stage','')),re.I) and
           (str((r.get('Account_Name') or {}).get('id')) in aids or str((r.get('Contact_Name') or {}).get('id')) in {str(c['id']) for c in exact['Contacts']})]
    return {'state':'OPEN DEAL' if deals else 'EXISTING CUSTOMER CONTEXT — VERIFY' if accounts or exact['Contacts'] else 'EXISTING PROSPECT' if exact['Leads'] else 'UNKNOWN — CUSTOMER CONTEXT NOT CLEARED',
            'Leads':[str(r['id']) for r in exact['Leads']],'Contacts':[str(r['id']) for r in exact['Contacts']],
            'Accounts':[str(r['id']) for r in accounts],'Deals':[str(r['id']) for r in deals],
            'finance_lineage':'UNKNOWN UNLESS EXISTING EXACT DEAL/ESTIMATE ASSOCIATION','fuzzy_matches':0,
            'execution_readiness':'HOLD','module_completeness':crm.get('_modules',{})}

def conversations(apollo,mail,crm,*,now):
    stages={r['id']:r.get('display_name','') for r in apollo.get('stages',[])}
    mail_rows={str(r['contact']['id']):r for r in mail.get('rows',[])}
    contacts={str(c['id']):c for c in apollo.get('contacts',[]) if live(c)}
    grouped={}
    for sent in apollo.get('replies',[])[:100]:
        c=contacts.get(str(sent.get('contact_id')))
        if not c:continue
        pid=digest(['person',email(c.get('email'))]) if email(c.get('email')) else digest(['apollo_contact',c['id']])
        grouped.setdefault(pid,[]).append((sent,c))
    output=[]
    for pid,items in grouped.items():
        sent,c=max(items,key=lambda p:p[0].get('completed_at') or '')
        records=[]
        for _,person in items:
            records.extend(mail_rows.get(str(person['id']),{}).get('replies',[]))
        unique={str(r['message_id']):r for r in records if r.get('match')=='EXACT_REFERENCES_AND_SENDER'}
        reply=max(unique.values(),key=lambda r:r.get('received_at','')) if unique else None
        trusted_row=mail_rows.get(str(c['id']),{})
        excerpt=author_text(reply['body'],c.get('name','')) if reply else ''
        result=classify(excerpt,reply.get('headers')) if reply and not trusted_row.get('diagnostic') else classify('')
        legal_step=bool(re.search(r'\bnda\b|non.disclosure|accord de confidentialite',folded(excerpt)))
        if legal_step:result.update(reply_class='OTHER',urgency='HIGH',confidence='MODERATE',commercial_intent='PARTNER ADMINISTRATIVE / LEGAL STEP — OWNER REVIEW')
        state=contact_state(c,apollo.get('messages',[])+apollo.get('replies',[]),stages,now=now)
        # A missing verification is a send HOLD, not evidence of an unsubscribe.
        suppressed=any(re.search('unsubscribe|do not contact|bounce|invalid',r,re.I) for r in state['reasons']) or result['reply_class'] in {'UNSUBSCRIBE','BOUNCE','LEFT_COMPANY','NOT_INTERESTED'}
        sequence=next((s for s in apollo.get('sequences',[]) if s['id']==sent.get('emailer_campaign_id')), {})
        strategy='PARTNER' if re.search('recrut|recruit',sequence.get('name',''),re.I) else 'ICP_VALUE'
        if re.search('partenariat|acquisition d.entreprise|vos differentes solutions',folded(excerpt)):strategy='PARTNER'
        if legal_step:strategy='PARTNER'
        if strategy=='PARTNER' and result['urgency']=='HOT':result['urgency']='HIGH'
        context=relationship(c,crm)
        own={m['id']:m for m in apollo.get('messages',[])+apollo.get('replies',[]) if str(m.get('contact_id'))==str(c['id'])}
        pressure={'last_outreach':max((m.get('completed_at') or '' for m in own.values()),default='') or None,
                  'recent_touch_count_lower_bound':sum(bool(m.get('status')=='completed' and stamp(m.get('completed_at')) and 0<=(now-stamp(m['completed_at'])).total_seconds()<30*86400) for m in own.values()),
                  'activity_complete':False,'manual_activity':'NOT CLEARED BY BOUNDED SNAPSHOT','next_contact_allowed':False}
        actions={'QUOTE_INTEREST':'PREPARE QUOTE','MEETING_INTEREST':'OWNER REVIEW','POSITIVE_INTEREST':'OWNER REVIEW','ASKING_QUESTION':'REPLY NOW','REFERRAL':'RESEARCH FIRST','FOLLOW_UP_LATER':'WAIT UNTIL DATE','UNKNOWN':'RESEARCH FIRST'}
        action='SUPPRESS' if suppressed else 'OWNER REVIEW' if legal_step else actions.get(result['reply_class'],'NO ACTION')
        latest=stamp(reply.get('received_at')) if reply else None
        stale=bool(latest and (now-latest).days>=14)
        output.append({'schema':1,'conversation_id':digest(['conversation',pid,'EMAIL']), 'provider':'APOLLO + ZOHO_MAIL',
            'person_id':pid,'company_id':c.get('organization_id') or c.get('account_id'),'person_name':c.get('name') or 'Known Apollo contact',
            'company':c.get('organization_name') or (c.get('organization') or {}).get('name') or 'UNKNOWN',
            'CRM_references':context,'Apollo_references':{'contact_ids':sorted({str(p['id']) for _,p in items}),'sequence_id':sent.get('emailer_campaign_id'),'sent_message_ids':sorted({s['id'] for s,_ in items})},
            'channel':'EMAIL','contact_history_complete':False,'first_contact_at':min(s.get('completed_at') or '' for s,_ in items) or None,
            'last_contact_at':pressure['last_outreach'],'last_reply_at':reply.get('received_at') if reply else None,
            'current_stage':'SUPPRESSED' if suppressed else 'REPLIED' if reply else 'REPLY_BODY_UNVERIFIED',
            **result,'urgency':'MEDIUM' if stale and result['urgency'] in {'HOT','HIGH'} else result['urgency'],
            'service_context':service_context(sent.get('subject','')+' '+sent.get('body_text','')+' '+' '.join(author_text(r['body'],c.get('name','')) for r in unique.values())),
            'project_context':[{'message_id':r['message_id'],'received_at':r['received_at'],'excerpt':author_text(r['body'],c.get('name',''))[:750]} for r in unique.values()
                if re.search(r'site survey|patch panel|besoin.{0,40}installation|projet',folded(author_text(r['body'],c.get('name',''))))],
            'human_controlled_commitment':legal_step,
            'trigger_context':'NO CURRENT TRIGGER','message_strategy':strategy,'current_owner':'APOLLO_CLAUDE',
            'next_best_action':action,'suppression':suppressed,'contact_confidence':'SUPPORTED_CURRENT' if reply else 'LIKELY',
            'role_confidence':'LIKELY — EMPLOYER NOT INDEPENDENTLY VERIFIED','role':c.get('title'),
            'identity_ambiguity':len({p.get('name') for _,p in items if p.get('name')})>1,
            'contact_pressure':pressure,'source_evidence':{'apollo_at':apollo.get('at'),'mail_at':mail.get('at'),
                'message_refs':[{'provider':'ZOHO_MAIL','id':r['message_id'],'at':r['received_at'],'match':r['match']} for r in unique.values()],
                'body_hash':digest(reply['body']) if reply else None,'provider_reply_class':sent.get('reply_class')},
            'last_verified_at':mail.get('at') if reply else apollo.get('at'),'reply_excerpt':excerpt[:800],
            'prior_message':plain(sent.get('body_text'))[:1400],'draft':None,'execution_authorized':False})
    return output

def service_context(text):
    t=folded(text)
    mapping={'AI loss prevention':r'detection de vol|loss prevention|veesion','commercial cameras':r'camera|cctv|surveillance','structured cabling':r'cablage|cabling|cat6|patch panel|filaires','commercial Wi-Fi':r'wi.fi|hot.spot','fiber':r'fib(re|er)','access control':r'controle d.acces|access control','intercom/security':r'intercom','managed support':r'maintenance|managed|support'}
    return [s for s,p in mapping.items() if re.search(p,t)]

def reply_draft(c):
    if c.get('identity_ambiguity'):return None
    if c.get('human_controlled_commitment') and not c['suppression']:
        return {'language':'FR','subject':'Re: existing partner conversation',
                'body':'Merci pour le document. Je vais revoir les modalités avant de confirmer la suite de la collaboration. Nous pourrons ensuite préciser le périmètre de la visite et des travaux envisagés.',
                'review_notes':['Owner reviews the actual document and any prior manual response. No signature, acceptance, legal opinion or appointment is authorized.'],
                'send_allowed':False,'owner':c['current_owner']}
    if c['suppression'] or c['reply_class'] not in {'QUOTE_INTEREST','MEETING_INTEREST','POSITIVE_INTEREST','ASKING_QUESTION','REFERRAL','FOLLOW_UP_LATER'}:return None
    if c['reply_class']=='REFERRAL' and c['confidence']=='TENTATIVE':return None
    fr=bool(re.search(r'bonjour|salut|merci|vous|nous',c['reply_excerpt'],re.I))
    if c['reply_class']=='QUOTE_INTEREST':
        body='Merci pour votre demande. Pour préparer la soumission, pouvez-vous préciser le site, le besoin et l’échéancier souhaité? Je pourrai ensuite confirmer les renseignements à compléter.' if fr else 'Thanks for your request. Could you confirm the site, scope and preferred timeline so I can prepare the estimate?'
    elif c['reply_class']=='REFERRAL':
        body='Merci pour la mise en relation. Je propose un court échange pour préciser le rôle de chacun et voir où nos services pourraient être complémentaires. Quel moment vous conviendrait?' if fr else 'Thanks for the introduction. Could we arrange a short call to clarify each team’s role and where our services could complement yours?'
    elif c['reply_class']=='FOLLOW_UP_LATER':
        body='Merci, je prends note. Quelle date préférez-vous pour reprendre la discussion?' if fr else 'Thanks, noted. What date would you prefer for us to revisit the discussion?'
    elif c['reply_class']=='ASKING_QUESTION':
        body='Merci pour votre question. Je vais vérifier les points techniques propres à votre situation avant de vous confirmer la réponse. Pouvez-vous préciser le site et le contexte?' if fr else 'Thanks for your question. I will verify the details for your situation before confirming an answer. Could you clarify the site and context?'
    else:
        body='Merci pour votre retour. Je vous propose un court appel pour préciser les besoins et voir si une collaboration serait utile. Quel créneau vous conviendrait?' if fr else 'Thanks for your reply. Could we schedule a short call to clarify your needs and see whether a collaboration would be useful?'
    if c['message_strategy']=='PARTNER' and re.search('disponible|disponibilite',folded(c['reply_excerpt'])):
        body='Merci pour vos disponibilités. Je vais confirmer avec vous un créneau encore possible pour un court appel. Nous pourrons préciser les types de mandats, votre disponibilité et les modalités de collaboration.'
    if c['message_strategy']=='PARTNER' and re.search('acquisition',folded(c['reply_excerpt'])):
        body='Merci pour votre ouverture. Je suis disponible pour discuter d’une collaboration sur l’installation terrain, selon les besoins de vos projets. Je propose de préciser d’abord ce volet; toute autre démarche stratégique demanderait une discussion distincte.'
    return {'language':'FR' if fr else 'EN','subject':'Re: existing conversation','body':body,
            'review_notes':['Verify the latest manual reply before use; draft cannot establish unanswered status.',
                            'Resolve current availability and any quoted dates with owner; no invented appointment or commitment.'],
            'send_allowed':False,'owner':c['current_owner']}

class ConversationStore:
    def __init__(self,path):self.path=path
    def record(self,row):
        safe(row)
        if row.get('current_owner') not in OWNERS or row.get('reply_class') not in CLASSES or row.get('execution_authorized') is not False:raise ValueError('Conversation safety contract')
        raw=json.dumps(row,sort_keys=True,ensure_ascii=False);fingerprint=digest(row)
        if len(raw.encode())>32768:raise ValueError('Conversation bound')
        with sqlite3.connect(self.path,timeout=10) as db:
            db.execute('CREATE TABLE IF NOT EXISTS sales_conversation_versions(conversation_id TEXT NOT NULL,revision INTEGER NOT NULL,hash TEXT NOT NULL,record TEXT NOT NULL,PRIMARY KEY(conversation_id,revision))')
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT revision,hash FROM sales_conversation_versions WHERE conversation_id=? ORDER BY revision DESC LIMIT 1',(row['conversation_id'],)).fetchone()
            if old and old[1]==fingerprint:return 'EXACT_REPLAY'
            db.execute('INSERT INTO sales_conversation_versions VALUES(?,?,?,?)',(row['conversation_id'],old[0]+1 if old else 1,fingerprint,raw))
        return 'RECORDED'

def evidence(provider,ref,at):
    return {'provider':provider,'source_reference':ref,'observed_at':at,'valid_until':None,'freshness':'CURRENT' if at else 'UNKNOWN','confidence':'MODERATE' if at else 'UNKNOWN','truth_class':'DERIVED_DETERMINISTIC','limitations':['Read-only bounded sample; not a contact or send authority.']}

def measurement():
    return {'metrics':[{'metric':'owner-verified meaningful replies / qualified opportunities','source_reference':'Canonical conversation + exact CRM/outcome references','unit':'count','baseline_value':None,'baseline_status':'UNKNOWN','baseline_sample':None,'baseline_window':None,'cohort_geography_language':'Exact reviewed recipients and language'}],
        'window':'28 days after separate authorized execution; review week 1 and week 2',
        'minimum_usable_sample':'At least 30 delivered messages and 5 independently reviewed replies for tentative comparison; smaller samples INSUFFICIENT.',
        'guardrails':['No duplicate owner, TEST business outcomes, suppressed contact, fabricated employer or promise.','Fresh collision, Mail/manual context and consent review immediately before any later execution.'],
        'success':'Owner-qualified commercial discussion with no guardrail breach; revenue requires deterministic Finance lineage.',
        'neutral':'Relevant replies but no supported opportunity improvement.','regression':'Suppression, collision, delivery or privacy breach; HOLD and retain evidence.',
        'insufficient_data':'Missing reply body, current role, outcome linkage or adequate sample.',
        'test_exclusion':'TEST_ONLY excluded from natural outcomes; fixtures never become prospects.',
        'attribution_limits':'Apollo delivery/reply flags are not positive intent; no invented outreach-to-revenue attribution.'}

def add_proposal(bundle,kind,target,title,why,detail,sources,now,urgency='MEDIUM'):
    system='CONTENT' if kind=='CONTENT_FEEDBACK' else 'SALES_PROCESS' if kind=='CUSTOMER_EXPANSION' else 'OUTREACH'
    pid=digest(['sales-optimization',kind,target]);at=now.isoformat();obj={'system':system,'entity_type':kind,'entity_id':target}
    record={'schema':1,'type':'optibrain.optimization_proposal','proposal_id':pid,'revision':1,'proposal_type':kind,
        'target_system':system,'target_object':obj,'target_url_or_record':'/v1/operator/sales',
        'created_at':at,'updated_at':at,'source_evidence':sources,'business_problem':why,'why_now':detail.get('why_now','NO CURRENT TRIGGER'),
        'recommended_change':title,'expected_benefit':'More relevant owner attention and legitimate future customer coverage; revenue UNKNOWN.',
        'risk':'Suppression, competing ownership, stale context and incomplete outcome lineage require human review.',
        'confidence':'MODERATE','data_quality':'Native message references or supported research; limitations retained separately.',
        'affected_files_or_records':[target],'preview_location':'/v1/operator/acquisition?proposal_id='+pid,
        'owner_action_required':'Review / modify / reject; separate sealed execution authority required.','authority_class':'C','status':'PREVIEW_READY',
        'approved_by':None,'approved_at':None,'execution_reference':None,'deployed_at':None,'measurement_plan':measurement(),
        'measurement_start':None,'measurement_end':None,'result':None,'learning':None,'rollback_reference':'No provider effect installed. Later exact authorized operation must preserve original state and support HOLD/rollback.'}
    bundle['proposals'].append({'record':record,'detail':detail})
    bundle['priorities'].append({'record':{'schema':1,'type':'optibrain.business_priority','priority_id':digest(['sales-priority',pid]),
        'domain':'SALES_INTELLIGENCE','targets':[obj],'proposal_id':pid,'what':title,'why':why,'business_impact':record['expected_benefit'],
        'urgency':urgency,'due_at':None,'confidence':record['confidence'],'data_quality':record['data_quality'],'source_evidence':sources,
        'priority_reasons':[why,'Preserve current outreach owner; preparation only.'],'dependency':'Fresh conversation/contact/suppression/manual owner context before execution.',
        'blocker':None,'actor':'OWNER','can_prepare':True,'owner_approval_required':True,'status':'OWNER_REVIEW','created_at':at,'updated_at':at,
        'next_action':'Review exact draft and source context; no send action.'},'detail':{}})

def build_bundle(apollo,mail,crm,prospects,*,now,sequence_evidence=None):
    rows=conversations(apollo,mail,crm,now=now);bundle={'proposals':[],'priorities':[],'assets':[]}
    for c in rows:
        c['draft']=reply_draft(c)
        if c['draft']:
            detail={'conversation':c,'draft':c['draft'],'strategy':c['message_strategy'],'why_now':'Authenticated inbound reply; manual follow-up may already exist.'}
            add_proposal(bundle,'SALES_REPLY',c['conversation_id'],'Review '+c['next_best_action']+' · '+c['company'],
                c['reply_class']+' from an exact message-linked reply; buying intent remains unqualified.',detail,
                [evidence('APOLLO / ZOHO_MAIL',c['conversation_id'],mail.get('at'))],now,'HIGH' if c['urgency'] in {'HOT','HIGH'} else 'MEDIUM')
            if c.get('human_controlled_commitment'):
                bundle['proposals'][-1]['record']['authority_class']='D'
                bundle['proposals'][-1]['record']['risk']='Human-controlled legal/contract context. No document signature, acceptance or legal judgment is prepared/executed.'
    coverage=Counter();gaps=Counter()
    for p in prospects:
        if p.get('enrichment_readiness')=='PROSPECTING_READY':coverage['shadow_prospecting_ready']+=1
        own=p.get('Apollo_state') not in {None,'NOT IN APOLLO'}
        current=[c for c in p.get('contacts',[]) if c.get('confidence') in {'SUPPORTED_CURRENT','VERIFIED_CURRENT'} and
                 (useful_role(c.get('title')) or re.search(r'chief executive|chef de la direction|\bceo\b',str(c.get('title','')),re.I)) and not c.get('suppressed')]
        if own:coverage['active_or_saved_apollo']+=1;gaps['ACTIVE_APOLLO' if 'ACTIVE' in p.get('Apollo_state','') else 'APOLLO_OWNERSHIP']+=1
        if not p.get('domain'):gaps['NO_DOMAIN']+=1
        if not current:gaps['NO_CONTACT']+=1
        if any(c.get('confidence') in {'LIKELY','STALE','UNRESOLVED'} for c in p.get('contacts',[])):gaps['UNCERTAIN_ROLE']+=1
        if 'UNKNOWN' in str(p.get('CRM_state','')):gaps['UNKNOWN_COLLISION']+=1
        if p.get('suppression_state')=='SUPPRESSED':coverage['suppressed']+=1;continue
        customer='CUSTOMER' in str(p.get('CRM_state',''))
        if customer:coverage['existing_customer']+=1
        if customer and not own and not current and p.get('service_categories_seen'):
            detail={'company':p['canonical_name'],'owner':'CUSTOMER_RELATIONSHIP','service':p['service_categories_seen'],
                    'why_now':'NO CURRENT TRIGGER','draft':{'subject':'Customer service review — owner preparation only',
                    'body':'Prepare a relationship review: confirm current sites/services, existing owner and maintenance needs before contacting anyone.', 'send_allowed':False},
                    'execution_blockers':['No supported current role','Owner confirms existing service/location and customer consent'],
                    'recurring_potential':'Possible maintenance or managed support; need, scope, price and margin UNKNOWN'}
            add_proposal(bundle,'CUSTOMER_EXPANSION',p['prospect_id'],'Review existing-customer maintenance/support context · '+p['canonical_name'],
                'Known customer context; review existing relationship instead of cold outreach.',detail,
                [evidence('PROSPECT_UNIVERSE',p['prospect_id'],p.get('last_enriched'))],now)
        if not current or own or p.get('CRM_state')=='UNKNOWN' or p.get('company_confidence') not in {'EXACT','SUPPORTED'}:continue
        if not p.get('service_categories_seen'):gaps['NO_SERVICE_FIT']+=1;continue
        service=p['service_categories_seen'][0];person=current[0]
        # FR is a preparation default, not a claim about a person's language.
        language=p.get('language') if p.get('language') in {'FR','EN'} else 'FR'
        trigger=p.get('why_now') if p.get('current_trigger_count',0)>0 else 'NO CURRENT TRIGGER'
        name=p['canonical_name'];role=person.get('title') or 'Relevant role';no_trigger=trigger=='NO CURRENT TRIGGER'
        body=(f'Bonjour,\n\nJe souhaite vérifier qui s’occupe de {service} chez {name}. Opticable accompagne les organisations pour la préparation et l’installation de ces systèmes. Est-ce un sujet que votre équipe évalue, ou y a-t-il une personne responsable à qui adresser cette question?\n\nMerci,\nYan-Erik Boucher' if language=='FR' else
              f'Hello,\n\nWho oversees {service} at {name}? Opticable helps organizations plan and install these systems. Is this something your team is considering, or should I direct the question to another role?\n\nThank you,\nYan-Erik Boucher')
        if language=='FR':
            translations={'IP cameras / CCTV':'caméras IP commerciales','commercial cameras':'caméras commerciales','commercial Wi-Fi':'Wi-Fi commercial',
                          'structured cabling':'câblage structuré','fiber':'fibre optique','access control':'contrôle d’accès','managed support':'support réseau'}
            body=body.replace(service,translations.get(service,service))
        if customer:body=f'Bonjour,\n\nPour vos prochains besoins en {service}, souhaitez-vous revoir la couverture et les possibilités de maintenance? Je propose de confirmer ensemble votre situation et le périmètre avant de préparer quoi que ce soit.\n\nMerci,\nYan-Erik Boucher'
        detail={'company':name,'target_role':role,'target_person':person.get('name'),'language':language,'language_status':'DRAFT — OWNER MUST CONFIRM','service':service,
            'why_opticable':p.get('why_opticable'),'why_now':trigger,'message_strategy':'TRIGGER_BASED' if not no_trigger else 'ICP_VALUE',
            'contact_confidence':person['confidence'],'CRM_state':p.get('CRM_state'),'Apollo_state':p.get('Apollo_state'),
            'suppression':p.get('suppression_state'),'owner':'CUSTOMER_RELATIONSHIP' if customer else 'OWNER_MANUAL',
            'draft':{'subject':service+' — '+name,'body':body,'send_allowed':False},'follow_up_strategy':'One primary role first; secondary role only after explicit owner review. No automatic follow-up cadence.',
            'roles':[{'name':c.get('name'),'title':c.get('title'),'confidence':c['confidence'],'priority':'PRIMARY' if i==0 else 'SECONDARY'} for i,c in enumerate(current)],
            'execution_blockers':['Exact person/channel verification','Fresh Mail/manual-contact and suppression check','Language confirmation','Separate execution approval'],
            'public_procurement':'Confirm procurement process; do not bypass an open tender.' if 'centre de services' in name.lower() or 'mrc' in name.lower() or 'institut' in name.lower() else None,
            'recurring_potential':'Maintenance/managed support may fit; scope, price and margin UNKNOWN','historical_repeat_buyer':p.get('repeat_buyer_count',0)>1,
            'evidence_reference':p['prospect_id'],'execution_authorized':False}
        add_proposal(bundle,'CUSTOMER_EXPANSION' if customer else 'OUTREACH_PROPOSAL',p['prospect_id'],'Review '+('customer expansion' if customer else 'role-addressed outreach draft')+' · '+name,
            'Supported current role and service-fit research; '+trigger,detail,[evidence('PROSPECT_UNIVERSE',p['prospect_id'],p.get('last_enriched'))],now)
        coverage['ready_for_draft_review']+=1;coverage['execution_ready']+=0
    bundle.update(conversations=rows,coverage=dict(coverage),coverage_gaps=dict(gaps),sequence_evidence=sequence_evidence or {})
    # Sequence and list issues use the SAME proposal/review/measurement contract.
    for issue in (sequence_evidence or {}).get('issues',[]):
        add_proposal(bundle,'SEQUENCE_CHANGE',issue['sequence_id']+':'+issue['kind'],issue['title'],issue['why'],issue,
                     [evidence('APOLLO',issue['sequence_id'],sequence_evidence.get('at'))],now,'HIGH')
    for c in rows:
        if c['reply_class'] not in {'REFERRAL','MEETING_INTEREST','POSITIVE_INTEREST','ASKING_QUESTION'} or c['confidence']=='TENTATIVE':continue
        hook='Partner role and installation scope before discussing a collaboration' if c['message_strategy']=='PARTNER' else 'Define the technical need before proposing a service'
        record={'schema':1,'type':'optibrain.optimization_asset','asset_id':digest(['sales-hook',c['conversation_id'],hook]),'asset_type':'HOOK',
            'proposal_id':None,'service':', '.join(c['service_context']) or 'Role and collaboration discovery','icp':'Verified existing sales conversation',
            'geography':'UNKNOWN unless source-bound','channel':'SALES_EMAIL','language':c['draft']['language'] if c.get('draft') else 'UNKNOWN',
            'source_evidence':[evidence('ZOHO_MAIL',c['conversation_id'],mail.get('at'))],'draft_or_asset_reference':'/v1/operator/sales',
            'provider':'OPTIBRAIN_DETERMINISTIC','brief_or_prompt_reference':'OPTIBRAIN_OUTREACH_INTELLIGENCE_CONTRACT.md',
            'rights_source_status':'Original draft; private source message retained outside Git.','usage':'DRAFT ONLY','illustrative':True,'performance_evidence':[], 'created_at':now.isoformat()}
        bundle['assets'].append({'record':record,'detail':{'text':hook,'evidence_strength':'TENTATIVE','positive_response_not_customer_conversion':True}})
    partners=[c for c in rows if c['message_strategy']=='PARTNER' and c['reply_class'] in {'REFERRAL','MEETING_INTEREST','POSITIVE_INTEREST'}]
    if partners:
        draft={'headline':'Collaborer avec Opticable : préciser les responsabilités avant le projet',
               'faq':{'question':'Comment préparer une collaboration d’installation?',
                      'answer':'Précisez le site, le périmètre des travaux, la personne responsable et les contraintes d’accès. Les responsabilités et modalités seront confirmées avant toute intervention.'},
               'article_outline':['Identifier les rôles et le périmètre','Vérifier les prérequis réseau et accès','Confirmer les modalités de collaboration'],
               'sales_collateral':'Checklist: scope / site / project owner / responsibilities / access / next step.',
               'claim_boundary':'Educational draft informed by a small partner sample; no recurring objection or performance winner claimed.'}
        add_proposal(bundle,'CONTENT_FEEDBACK','partner-role-clarity','Review partner-scope FAQ and sales checklist',
            'Source-linked conversations ask for a discussion/referral; clarify partner vs client responsibilities before proposing work.',
            {'content_draft':draft,'conversation_references':[c['conversation_id'] for c in partners],'publication':'NOT AUTHORIZED',
             'Ads_cross_learning':'Service/positioning learning only; Apollo replies are not Ads-attributed outcomes.'},
            [evidence('ZOHO_MAIL',c['conversation_id'],mail.get('at')) for c in partners],now)
    for c in rows:
        if not c['project_context']:continue
        hook='Préparer le câblage et le Wi-Fi avant la visite technique'
        asset={'schema':1,'type':'optibrain.optimization_asset','asset_id':digest(['sales-project-hook',c['conversation_id']]),
            'asset_type':'HOOK','proposal_id':None,'service':'structured cabling / commercial Wi-Fi','icp':'IT partner / commercial facility',
            'geography':'UNKNOWN unless verified in the private project context','language':'FR','channel':'SALES_EMAIL',
            'source_evidence':[evidence('ZOHO_MAIL',c['project_context'][0]['message_id'],mail.get('at'))],
            'provider':'OPTIBRAIN_DETERMINISTIC','brief_or_prompt_reference':'OPTIBRAIN_HOOK_CONTENT_CONTRACT.md',
            'draft_or_asset_reference':'/v1/operator/sales','rights_source_status':'Original educational angle; no customer identity/project image/public case study.',
            'usage':'DRAFT ONLY','illustrative':True,'performance_evidence':[],'created_at':now.isoformat()}
        bundle['assets'].append({'record':asset,'detail':{'text':hook,'evidence_strength':'TENTATIVE','strategy':'PROJECT_BASED','Ads_attribution':'NONE'}})
    return bundle

def render(view):
    h=lambda x:escape(str(x if x is not None else 'UNKNOWN'),quote=True)
    out='<section><h2>Sales conversation intelligence</h2><p>Read / analyze / prepare only. No send or Apollo change.</p>'
    out+='<p>'+h(view.get('state'))+' · '+h(view.get('collection_origin'))+' collection · '+h(view.get('preparation_origin'))+' preparation</p>'
    out+='<p>Coverage: '+h(view.get('coverage'))+' · Gaps: '+h(view.get('coverage_gaps'))+'</p>'
    for r in view.get('conversations',[]):
        out+='<article><h3>'+h(r['company'])+' · '+h(r['person_name'])+'</h3><p>'+h(r['reply_class'])+' · '+h(r['urgency'])+' · '+h(r['next_best_action'])+'</p><p>Owner: '+h(r['current_owner'])+' · '+h(r['CRM_references']['state'])+'</p><p>'+h(r['contact_pressure'])+'</p>'
        out+='<details><summary>Source context and draft</summary><p>'+h(r['reply_excerpt'] or 'Reply body unavailable; do not infer intent.')+'</p><p>Previously sent: '+h(r['prior_message'])+'</p><pre>'+h(json.dumps(r.get('draft'),ensure_ascii=False,indent=2))+'</pre></details></article>'
    out+='<h3>Drafts and sequence proposals ready for local review</h3>'
    for p in view.get('proposals',[]):
        out+="<p><a href='/v1/operator/acquisition?proposal_id="+h(p['proposal_id'])+"'>"+h(p['title'])+'</a> · '+h(p['status'])+'</p>'
    return out+'</section>'

def render_proposal(item):
    h=lambda v:escape(str(v),quote=True);r=item['record'];pid=r['proposal_id']
    out="<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Sales draft review</title><style>body{font:16px/1.5 system-ui;max-width:950px;margin:auto;padding:24px}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style></head><body>"
    out+='<p><a href="/v1/operator/sales">Sales</a></p><h1>'+h(r['recommended_change'])+'</h1><p>'+h(item['effective_status'])+' · '+h(r['confidence'])+'</p>'
    for key in ('business_problem','why_now','expected_benefit','risk','data_quality'):
        out+='<h2>'+h(key.replace('_',' ').title())+'</h2><p>'+h(r[key])+'</p>'
    for key in ('draft','conversation','roles','proposed_copy','content_draft'):
        if item['detail'].get(key):out+='<h2>'+h(key.replace('_',' ').title())+'</h2><pre>'+h(json.dumps(item['detail'][key],ensure_ascii=False,indent=2))+'</pre>'
    out+='<details><summary>Complete preview and evidence</summary><pre>'+h(json.dumps(item['detail'],ensure_ascii=False,indent=2))+'</pre><pre>'+h(json.dumps(r['source_evidence'],ensure_ascii=False,indent=2))+'</pre></details>'
    out+='<h2>Measurement</h2><pre>'+h(json.dumps(r['measurement_plan'],ensure_ascii=False,indent=2))+'</pre><p>Local review only. No email, Apollo, Claude, CRM, Ads or publishing effect is authorized.</p>'
    out+=f"<form method='post' action='/v1/operator/acquisition/proposal/{pid}/review'><input type='hidden' name='revision' value='{r['revision']}'><input type='hidden' name='payload_hash' value='{h(item['payload_hash'])}'><label>Review <select name='choice'><option>REVIEWED</option><option>RESEARCH</option><option>REJECT</option></select></label><button>Record local review</button></form></body></html>"
    return out
