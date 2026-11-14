"""Evidence-conditioned original drafts; bounded recipes, no paid model or media.

Owner feedback selects constrained revisions. It never supplies executable code,
permission, spending or claims. Original assets and rejected versions are retained.
"""
from datetime import datetime
from hashlib import sha256
import json
import re


def quality(text, evidence, *, licensing='ORIGINAL_TEXT', history=()):
    if not evidence:raise ValueError('Source evidence required')
    if licensing not in {'ORIGINAL_TEXT','ORIGINAL_VECTOR'}:raise ValueError('Unapproved media rights')
    patterns=[r'\b\d+(?:[.,]\d+)?\s*%',r'\$\s*\d',r'\bguaranteed?\b',r'\bgaranti(?:e|s)?\b',
              r'\b(?:customer|client) (?:story|testimonial|saved|says)\b',r'\b(?:avis|review)\s*[45](?:[.,]\d)?\s*(?:star|étoile)',
              r'\b(?:ROI|ROAS)\s*(?:of|de|:|=)\s*\d',r'\b(?:stock photo|image client|customer footage)\b',r'\b(?:client|customer)s?\b.{0,80}\b(?:saved|reduced|économisé|témoigne|says|affirme)\b']
    if any(re.search(p,text,re.I) for p in patterns):raise ValueError('Unsupported business claim or customer/media assertion')
    normalized=' '.join(re.findall(r'\w+',text.casefold()))
    words=set(normalized.split())
    for prior in history:
        old=' '.join(re.findall(r'\w+',str(prior).casefold()))
        if normalized==old:raise ValueError('Duplicate content')
        tokens=set(old.split())
        if words and len(words&tokens)/len(words|tokens)>.86:raise ValueError('Repetitive content')
    return ['Source evidence attached','No numeric ROI/accuracy/savings claim','No invented customer/review','Original text/vector rights','No external publication or spending']


def feedback_rule(reason):
    text=reason.casefold()
    if any(x in text for x in ('shorter','plus court','raccourc','concise')):return 'SHORTER'
    if any(x in text for x in ('human','humaine','alert')):return 'HUMAN_REVIEW'
    if any(x in text for x in ('specific','précis','precis','scope','zone')):return 'SCOPING'
    return None


CAMERA={
 'fr':('Une demande caméra plus utile commence par trois scènes',
       'Avant de demander un nombre de caméras, choisissez trois scènes importantes : une entrée, une livraison et une zone de vente, par exemple. Pour chacune, notez la question à laquelle les images doivent répondre et les moments où l’éclairage pose problème.\n\nLa portée dépend aussi du câblage, de l’alimentation PoE, de l’enregistreur et de la conservation souhaitée. Un équipement présent peut être étudié pour réutilisation après vérification; sa compatibilité ne se présume pas.\n\nPréparez une fiche avec le type de bâtiment, les zones prioritaires et les contraintes d’accès. Aucun mot de passe, visage ni enregistrement client n’est nécessaire pour cette première discussion. Opticable peut ensuite préciser les éléments à évaluer.\n\nhttps://opticable.ca/fr/services/systemes-cameras-securite/'),
 'en':('A useful camera inquiry starts with three scenes',
       'Before requesting a camera count, choose three important scenes: an entrance, a delivery point and a sales area, for example. For each one, describe the question the footage should answer and when lighting becomes difficult.\n\nScope also depends on cabling, PoE power, recording equipment and desired retention. Existing equipment can be considered for reuse after assessment; compatibility must be checked.\n\nPrepare a brief with the building type, priority areas and access constraints. No passwords, faces or customer recordings are needed for this first discussion. Opticable can then help define what needs assessment.\n\nhttps://opticable.ca/en/services/security-camera-systems/')}
AI={
 'fr':('Prévention des pertes par IA : préparer la vérification humaine',
       'Une alerte vidéo doit aider une personne à vérifier une situation. Elle ne constitue pas, à elle seule, une conclusion sur le comportement d’un client. Avant un projet de prévention des pertes, décrivez le processus de traitement des alertes aussi soigneusement que les caméras.\n\nCommencez par les scènes. Quels angles montrent les gestes à examiner? Quels obstacles, reflets ou changements d’éclairage peuvent masquer l’action? La qualité et la compatibilité des flux doivent être évaluées avant toute intégration. Une liste d’équipements ne démontre pas qu’un cas d’usage fonctionnera.\n\nDéfinissez ensuite la vérification humaine. Qui reçoit une alerte? Comment consulte-t-on le contexte? Que fait-on lorsqu’une scène reste ambiguë? Les procédures d’accès aux images et de conservation doivent être convenues avec les responsables du commerce. Il faut éviter de transformer une notification technique en accusation automatique.\n\nSéparez les exigences du projet : caméras et angles, transport réseau, enregistrement, accès autorisés et traitement des alertes. Cette séparation facilite une discussion technique sans promettre un résultat financier ou une précision non mesurée.\n\nPour un premier échange avec Opticable, préparez le type de commerce, les zones prioritaires et un inventaire approximatif. N’envoyez ni mots de passe ni séquences identifiant des clients. Une évaluation pourra préciser les limites, les vérifications et la portée appropriée.\n\nhttps://ai.opticable.ca/fr/'),
 'en':('AI loss prevention: prepare the human review process',
       'A video alert should help a person review a situation. On its own, it is not a conclusion about a customer’s behaviour. Before an AI loss-prevention project, describe the alert-handling process as carefully as the cameras.\n\nStart with the scenes. Which views show the actions that need review? Which obstructions, reflections or lighting changes could hide them? Feed quality and compatibility need assessment before integration. An equipment list does not establish that a use case will work.\n\nThen define human review. Who receives an alert? How do they examine context? What happens when the scene remains ambiguous? Image access and retention procedures need agreement with the people responsible for the premises. A technical notification must not become an automatic accusation.\n\nSeparate the project requirements: camera views, network transport, recording, authorized access and alert handling. This makes the technical discussion useful without promising a financial result or unmeasured accuracy.\n\nFor an initial conversation with Opticable, prepare the type of business, priority areas and an approximate equipment inventory. Send no passwords or recordings identifying customers. An assessment can then clarify limits, verification and the appropriate scope.\n\nhttps://ai.opticable.ca/en/')}
WIFI={
 'fr':('Wi-Fi commercial : nommer le symptôme avant l’équipement',
       'Une zone sans signal et un réseau lent à l’heure de pointe ne posent pas la même question. Notez la zone, l’heure, les appareils touchés et les usages interrompus. Vérifiez aussi si un poste câblé rencontre le même problème : la liaison Internet et la couverture Wi-Fi sont deux pistes différentes.\n\nCes observations permettent de discuter de couverture, de capacité, d’interférences et de câblage avant de choisir des bornes. Préparez un plan simple, sans mots de passe, pour votre échange avec Opticable.\n\nhttps://opticable.ca/fr/services/installation-wifi-commercial/'),
 'en':('Commercial Wi-Fi: name the symptom before the equipment',
       'A dead zone and slow service at peak time raise different questions. Note the location, time, affected devices and interrupted activities. Also check whether a wired workstation has the same difficulty: Internet connectivity and Wi-Fi coverage are separate leads.\n\nThese observations help frame coverage, capacity, interference and cabling before selecting access points. Prepare a simple plan without passwords for your conversation with Opticable.\n\nhttps://opticable.ca/en/services/commercial-wifi-installation/')}


def generate(native, context, now):
    sources={s['source']:s for s in native['snapshots']};gsc=sources.get('platform:gsc:query_page',{})
    rows=gsc.get('data',{}).get('rows',[])
    camera=[r for r in rows if '/services/' in r['keys'][1] and 'camera' in r['keys'][1]]
    wifi=[r for r in rows if 'wifi' in r['keys'][1]]
    candidates=[]
    if camera:candidates.append(('camera-scope','ip-cameras',CAMERA,camera,2,'SEARCH_INTENT_OBSERVED'))
    candidates.append(('ai-human-review','ai-loss-prevention',AI,[],1,'OWNER_SERVICE_PRIORITY_AND_VERIFIED_SERVICE_SCOPE'))
    if wifi:candidates.append(('wifi-symptom','commercial-networking',WIFI,wifi,3,'SEARCH_INTENT_OBSERVED'))
    # Two useful tasks maximum. Never refresh provider APIs from drafting.
    candidates.sort(key=lambda x:x[4]);selected=candidates
    produced=[];prior=set(context.get('artifact_hashes',[]));history=context.get('prior_texts',[])
    previous_feedback=context.get('feedback',[])
    completed_tasks=0
    for recipe,service,copy,queries,rank,truth in selected:
        if completed_tasks>=2:break
        before_count=len(produced)
        evidence=[{'reference':gsc.get('id'),'truth_class':truth,'query_slice':[
            {'query':r['keys'][0],'page':r['keys'][1],'impressions':r['impressions'],'clicks':r['clicks']} for r in sorted(queries,key=lambda r:-r['impressions'])[:5]],
            'period':native['collection']['period'],'service_source':'https://ai.opticable.ca/' if service=='ai-loss-prevention' else 'https://opticable.ca/'}]
        for lang in ('fr','en'):
            feedback=next((x for x in reversed(previous_feedback) if x.get('service')==service and x.get('language',lang)==lang and x.get('choice') in ('REJECT','REQUEST_REVISION') and x.get('rule')),None)
            title,body=copy[lang];revision_of=None
            if feedback:
                revision_of=feedback['asset_sha256']
                if feedback['rule']=='SHORTER':
                    title=('L’essentiel du projet' if lang=='fr' else 'Project essentials')+' — '+service
                    body=body.split('\n\n')[0]+'\n\n'+body.split('\n\n')[-1]
                elif feedback['rule']=='SCOPING':
                    body=('À préciser avant l’évaluation : trois zones, le réseau présent et les accès nécessaires.\n\n' if lang=='fr' else 'Define before assessment: three areas, the existing network and required access.\n\n')+body
                elif feedback['rule']=='HUMAN_REVIEW':
                    body=('Une alerte demande une vérification humaine. Aucune conclusion automatique sur une personne.\n\n' if lang=='fr' else 'An alert requires human review. No automatic conclusion about a person.\n\n')+body
            text=title+'\n\n'+body+'\n';h=sha256(text.encode()).hexdigest()
            if h in prior:continue
            checks=quality(text,evidence,history=[x for x in history if sha256(str(x).encode()).hexdigest()!=revision_of])
            path=f'campaigns/intent-library/commercial-camera-ai/{service}/{lang}/'+('articles' if recipe=='ai-human-review' else 'social')+f'/draft/{recipe}.txt'
            produced.append({'logical_path':path,'content':text,'service':service,'language':lang,
                'platform':'website article' if recipe=='ai-human-review' else 'LinkedIn / Facebook draft',
                'recipe':recipe,'revision_of':revision_of,'evidence_ids':[gsc['id']] if gsc.get('id') else [],
                'source_evidence':evidence,'quality_checks':checks,'licensing':'ORIGINAL_TEXT',
                'objective':'Qualified project conversations; no measured business lift yet','estimated_incremental_cost':'0'})
        if len(produced)>before_count:completed_tasks+=1
    return produced
