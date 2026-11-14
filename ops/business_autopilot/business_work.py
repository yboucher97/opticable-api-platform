"""Private business preparation from exact native records. No transport or execution.

Customer text is evidence, never instructions. No name/email matching, prices,
qualification, reply status or revenue are invented. Business drafts never enter
the public marketing history. Stable source revisions prevent daily duplicate work.
"""
from datetime import datetime, timedelta
from hashlib import sha256
import json
import re


def synthetic(record):
    return record.get('test_only') is True or bool(re.search(
        r'optibrain[ _-]*test|opticable internal canary',
        json.dumps(record, ensure_ascii=False), re.I))


def fresh(at, now, hours=30):
    try:
        age=now-datetime.fromisoformat(at.replace('Z','+00:00'))
        return timedelta(minutes=-5) <= age <= timedelta(hours=hours)
    except (ValueError,TypeError,AttributeError):return False


def stable_id(value):
    # JSON numbers above 2**53 cannot preserve provider identity through JS.
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,120}',value):
        raise ValueError('Exact string native identifier required')
    return value


def inquiry_copy(item):
    f=item['fields'];lang=item['language'];name=f.get('name','').replace(',', ' ').strip()
    service=f.get('service','');notes=f.get('notes','')[:4000]
    if lang=='en':
        title='Draft response — '+f.get('company','service inquiry')
        intro=f'Hello {name},\n\nThank you for the project details. '
        if re.search(r'cabl',service,re.I):
            body=('You described cabling from the server room to the workstations. Before we prepare a priced scope, '
                  'could you confirm the number of data outlets at each workstation and whether the stated distance is the combined route or a single run? '
                  'Please also confirm which pathways or conduits already exist, whether work must take place outside garage operating hours, '
                  'and whether any workstations need PoE devices. A simple floor plan without credentials would help us plan an assessment.\n\n'
                  'We can then define the routes, termination points, labeling and test deliverables to include in the quotation. '
                  'Equipment, materials, schedule and pricing remain subject to assessment and your acceptance of the finished quotation.')
            checklist=['Confirm outlet count and destination labels','Measure each route; customer distance is provisional, not a takeoff',
                       'Assess existing conduit, access, working hours and site constraints','Confirm cable specification and PoE requirements',
                       'Separate materials, installation, termination, labeling and agreed testing in unpriced scope',
                       'Prepare port map and test handover; owner approves any priced quotation']
        else:
            body=('Could you confirm the areas to cover, the existing equipment and the timing constraints? '
                  'Please send a simple project outline without passwords or sensitive customer information. '
                  'We will use it to define the assessment and quotation scope; no price or schedule is committed by this draft.')
            checklist=['Confirm scope and existing equipment','Prepare access and assessment questions','Owner reviews finished quotation before any commitment']
        response=intro+body+'\n\nOpticable\n'
        scope='Unpriced quotation outline and site preparation\n\nCustomer-stated scope (unverified):\n'+notes+'\n\n'+'\n'.join('- '+x for x in checklist)+'\n\nNo quantities beyond customer evidence, unit prices, tax, final total or delivery promise have been supplied.\n'
    else:
        title='Projet de réponse — '+f.get('company','demande de service')
        intro=f'Bonjour {name},\n\nMerci pour les précisions sur votre projet. '
        if re.search(r'wi.?fi',service,re.I):
            body=('Pour cadrer le réseau Wi-Fi de votre immeuble, pouvez-vous préciser le nombre d’étages et de logements, '
                  'les espaces communs à couvrir et les usages attendus? Nous aimerions aussi savoir si une connexion Internet commune, '
                  'du câblage et des bornes sont déjà présents, et qui autorise l’accès aux locaux techniques. '
                  'Un plan simple, sans mots de passe ni renseignements sur les résidents, aiderait à préparer l’évaluation.\n\n'
                  'Nous pourrons ensuite distinguer la couverture, la capacité, le transport câblé et la séparation des accès. '
                  'Le choix des équipements, les travaux et l’échéancier devront être précisés dans une soumission après vérification.')
            checklist=['Confirmer logements, étages, espaces communs et usages','Inventorier fournisseur Internet, bornes, commutateurs et câblage',
                       'Définir les accès autorisés, les zones prioritaires et la séparation des réseaux',
                       'Préparer une visite et un relevé; ne pas présumer un nombre de bornes',
                       'Distinguer étude, câblage, équipements, configuration et vérifications dans la portée sans prix']
        else:
            body=('Pouvez-vous préciser les bâtiments et les zones concernés, le réseau actuel et les contraintes d’accès? '
                  'Un plan simple sans mots de passe permettra de préparer une évaluation. '
                  'La portée, les équipements et les travaux restent à valider avant toute soumission chiffrée.')
            checklist=['Préciser zones, distances et réseau actuel','Confirmer accès et contraintes de chantier','Faire approuver toute soumission chiffrée par le propriétaire']
        response=intro+body+'\n\nOpticable\n'
        scope='Portée sans prix et préparation du projet\n\nDemande du client (à valider) :\n'+notes+'\n\n'+'\n'.join('- '+x for x in checklist)+'\n\nAucun prix, quantité inventée, engagement de disponibilité ou promesse de résultat.\n'
    response='To / Destinataire: '+f.get('email','VERIFY_NATIVE_CONTACT_BEFORE_SEND')+'\n\n'+response
    return title,response,scope


def generate(source, context, now):
    """Generate bounded finished work, then a receipt with actual new artifact IDs."""
    prior=set(context.get('artifact_hashes',[]));out=[];opportunities=[];blocked=[]
    def add(key,title,text,lang,service,kind,urgency,evidence,scope=None):
        content=title+'\n\n'+text.strip()+'\n';h=sha256(content.encode()).hexdigest()
        logical=f'business-work/{kind}/{key}/{lang}/draft/{kind}.txt'
        if h not in prior:
            out.append({'logical_path':logical,'content':content,'language':lang,'service':service,
                'platform':'private internal business preparation','business_private':True,'urgency':urgency,
                'expected_impact':'Reduce preparation and follow-up time; no sale or revenue inferred',
                'required_execution_approval':scope or 'NONE_INTERNAL_ONLY','proposed_execution':{'operation':scope,'enabled':False,'artifact_sha256':h} if scope else None,
                'source_evidence':evidence,'evidence_ids':source.get('snapshot_ids',[]),
                'quality_checks':['Exact native record references','No inferred reply or sales outcome','No price or business commitment','No external adapter'],
                'estimated_incremental_cost':'0','licensing':'PRIVATE_BUSINESS_RECORD'})
            prior.add(h)
        return h
    mail=source.get('mail',{})
    if fresh(mail.get('observed_at'),now):
        for item in mail.get('inquiries',[])[:4]:
            if synthetic(item):continue
            identity=stable_id(item['message_id']);f=item['fields']
            evidence=[{'source':'Zoho Mail read','account_id':stable_id(item['account_id']),'message_id':identity,
                       'received_at':item.get('received_at'),'observed_at':mail['observed_at'],
                       'coverage':'Bounded submission search; reply status UNKNOWN; no complete sent-folder/thread audit'}]
            title,response,scope=inquiry_copy(item)
            h=add(identity,title,response,item['language'],f.get('service','assessment'),'response-draft','HIGH',evidence,'CUSTOMER_COMMUNICATION')
            add(identity,'Project preparation — '+f.get('company','inquiry'),scope,item['language'],f.get('service','assessment'),'quote-outline','HIGH',evidence,'PRICED_QUOTE_REQUIRES_SEPARATE_APPROVAL')
            opportunities.append({'native_id':identity,'kind':'INQUIRY_SCOPE_REVIEW','priority':90,'confidence':'DIRECT_PROVIDER_RECORD',
                'summary':f.get('company','')+' — '+f.get('service',''),'next_action':'Check actual reply status, review prepared draft and scope','reply_status':'UNKNOWN','artifact_sha256':h})
    else:blocked.append('Mail evidence is absent/stale; no current unanswered-inquiry claim or new customer draft')
    crm=source.get('crm',{});leads={x['id']:x for x in crm.get('leads',[]) if not synthetic(x)}
    if fresh(crm.get('observed_at'),now):
        for task in crm.get('tasks',[])[:50]:
            if synthetic(task) or task.get('Status') in ('Completed','Closed','Cancelled'):continue
            due=task.get('Due_Date');link=(task.get('What_Id') or {}).get('id');lead=leads.get(link)
            if not due or due>=now.date().isoformat() or not lead:continue
            identity=stable_id(task['id']);stable_id(lead['id'])
            evidence=[{'source':'Zoho CRM Tasks and Leads','task_id':identity,'lead_id':lead['id'],'join':'EXPLICIT_NATIVE_WHAT_ID','due':due,'observed_at':crm['observed_at'],'partial_inventory':crm.get('partial',True)}]
            name=' '.join(str(lead.get(k) or '') for k in ('First_Name','Last_Name')).strip()
            text=f"Task: {task['Subject']}\nDue: {due}; native status: {task.get('Status')}\nLead: {lead.get('Company','')} ({lead['id']})\n\n"
            text+='Prepared French follow-up (send only after exact approval):\n\n'+f'Bonjour {name},\n\n'
            text+='Nous revenons sur votre projet de liaison entre immeubles. Est-il toujours d’actualité? Pour préparer la prochaine étape, pouvez-vous préciser les bâtiments à relier, les distances approximatives, les passages existants et les usages du réseau? Un plan sommaire sans mots de passe nous aiderait à cadrer une visite et une portée de travaux.\n\nOpticable\n\n'
            text+='Internal preparation completed:\n- Verify present customer/contact ownership and whether follow-up already occurred.\n- Confirm building ownership/access permissions and available pathways.\n- Inventory switches, existing links, distances and intended traffic.\n- Evaluate an appropriate copper/fiber route only after assessment.\n- Keep route, materials, testing, labeling and handover separate in unpriced scope.\nNo CRM status or task date was modified.'
            h=add(identity,'Overdue inquiry review — '+lead.get('Company',''),text,'fr','network interconnection','overdue-task','HIGH',evidence,'CUSTOMER_COMMUNICATION')
            opportunities.append({'native_id':identity,'kind':'OVERDUE_NATIVE_TASK','priority':100,'confidence':'EXACT_TASK_LEAD_LINK','summary':task['Subject']+' — due '+due,'artifact_sha256':h})
    else:blocked.append('CRM task evidence absent/stale; no current overdue-inventory assertion')
    calendar=source.get('calendar',{})
    if fresh(calendar.get('observed_at'),now):
        for event in calendar.get('events',[])[:20]:
            if event.get('status')!='confirmed' or not event.get('start_time'):continue
            start=datetime.fromisoformat(event['start_time'].replace('Z','+00:00'))
            if not now<=start<=now+timedelta(days=8):continue
            identity=stable_id(event['id']);evidence=[{'source':'Authorized Google Calendar','calendar_id':calendar['calendar_id'],'event_id':identity,'observed_at':calendar['observed_at']}]
            text=f"Meeting: {event['summary']}\nWhen: {event['start_time']} to {event.get('end_time')}\nRSVP: {event.get('my_response_status','UNKNOWN')} (unchanged)\n\n"
            text+='Prepared 20-minute agenda:\n0–3 min: confirm partner roles, client segments and service territory.\n3–8 min: establish installation scope, handoff and site-assessment prerequisites.\n8–13 min: discuss lead ownership, scheduling, required site documentation and acceptance tests.\n13–18 min: clarify commercial responsibilities; do not commit rates or referral terms.\n18–20 min: agree on an owner-reviewed next step.\n\nQualification questions:\n- Who owns the customer relationship and site permissions?\n- What installation work and support are expected?\n- What documentation, testing and escalation does each party provide?\n- Does any proposed fee, tool or travel create an expense requiring approval?\n\nPreparation completed: agenda, questions and authority boundaries. No invitation, RSVP, fee acceptance or customer communication was sent.'
            h=add(identity,'Partnership meeting brief — '+event['summary'],text,'bilingual','partnerships','meeting-brief','MEDIUM',evidence,'CALENDAR_RSVP')
            opportunities.append({'native_id':identity,'kind':'MEETING_PREPARATION','priority':75,'confidence':'CONFIRMED_NATIVE_EVENT','summary':event['summary']+' — '+event['start_time'],'artifact_sha256':h})
    else:blocked.append('Authorized calendar capture needs refresh before current meeting/RSVP claims; no new calendar integration or permissions')
    blocked+=source.get('blocked',[])
    opportunities.sort(key=lambda x:(-x['priority'],x['native_id']))
    report={'schema':1,'opportunities':opportunities,'coverage':{'mail':mail.get('coverage'),'crm_partial':crm.get('partial',True),'calendar_observed_at':calendar.get('observed_at')},
            'blocked':blocked,'completed_artifact_hashes':[sha256(x['content'].encode()).hexdigest() for x in out],
            'owner_approvals':'Exact sends, calendar actions and priced quotations remain separate; editorial acceptance authorizes none',
            'external_mutations':0,'paid_calls':0,'qualified_leads':None,'revenue':None}
    # Source state, not the clock alone, determines new actionable task identities.
    key=sha256(json.dumps({'opportunities':opportunities,'blocked':blocked},sort_keys=True).encode()).hexdigest()[:20]
    add(key,'Prioritized private business work',json.dumps({k:v for k,v in report.items() if k!='completed_artifact_hashes'},ensure_ascii=False,indent=2),'bilingual','all services','priorities','HIGH',[{'source':'exact native business records','snapshot_ids':source.get('snapshot_ids',[])}])
    return out,report
