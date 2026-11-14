"""Reviewed zero-cost service knowledge, finished copy and measured-gap selection.

Owner priorities and native service source are explicit evidence; unobserved
search demand or conversion lift is never invented. No customer records used.
"""
from datetime import timedelta
from hashlib import sha256
from html import escape
from content_variations import quality

# Native service routes from verified website source, not generated testimonials.
PACKS={
'structured-cabling':{
 'routes':('cablage-structure','structured-cabling'),
 'fr':('Câblage structuré : ce qui doit rester après les travaux',
       'Un projet de câblage ne se résume pas à tirer des câbles. Après l’installation, votre équipe doit pouvoir retrouver une prise, comprendre où elle aboutit et consulter les vérifications convenues. Ces livrables se précisent avant les travaux.\n\nCommencez par une liste des postes et des appareils à raccorder. Distinguez les prises de données, les appareils alimentés par PoE et les réserves souhaitées. Les distances annoncées servent à préparer une visite; elles ne remplacent pas un relevé des parcours, des passages disponibles et des contraintes d’accès.\n\nDemandez ensuite une convention de repérage commune aux prises et aux panneaux. Un plan des ports évite de devoir deviner quelle liaison dessert quelle zone. Précisez le type de vérification attendu et le format du compte rendu dans la portée de la soumission. Un voyant réseau allumé ne remplace pas tous les essais possibles.\n\nPour préparer une discussion avec Opticable, apportez un plan simple, une liste de destinations et les plages de travail possibles. Les matériaux, la méthode d’installation, les essais et la remise documentaire doivent être évalués ensemble.',
       'Avant votre prochain projet de câblage, demandez trois livrables : des prises repérées, un plan des ports et un compte rendu des vérifications convenues. Une portée claire se prépare avant le chantier. Quel document manque aujourd’hui à votre équipe?',
       'Faut-il fournir une longueur totale?\nUne estimation aide à préparer la visite; le relevé doit préciser les parcours et les destinations.\n\nQuels documents demander?\nUne convention de repérage, un plan des ports et les résultats des vérifications prévus dans la soumission.',
       'Plan 1 : prise sans étiquette — « Une prise, mais quelle destination? »\nPlan 2 : panneau et prise portant le même repère — « Reliez les deux extrémités par un repérage clair. »\nPlan 3 : plan de ports et dossier de vérification fictifs — « Précisez aussi ce qui sera vérifié et remis. »\nConclusion : « Préparez votre portée avec Opticable. »'),
 'en':('Structured cabling: what should remain after installation',
       'A cabling project is more than pulling cable. After installation, your team should be able to identify an outlet, find its destination and consult the agreed verification records. Define those deliverables before work begins.\n\nStart with the workstations and devices to connect. Separate data outlets, PoE devices and requested spare capacity. A customer-provided distance helps prepare an assessment; it does not replace a survey of routes, available pathways and access constraints.\n\nNext, agree on labels shared by outlets and patch panels. A port map removes guesswork about which link serves which area. Specify the required verification and report format in the quotation scope. An illuminated network light does not substitute for every possible test.\n\nBring a simple floor plan, a destination list and available working hours to an initial discussion with Opticable. Materials, installation methods, testing and handover documentation need to be assessed together.',
       'Before your next cabling project, ask for three handover items: labeled outlets, a port map and the agreed verification records. Define them before the work starts. Which document would make your team’s next move easier?',
       'Should I provide a total distance?\nAn estimate helps prepare the assessment; surveyed routes and destinations define the scope.\n\nWhat records should I request?\nAn agreed labeling scheme, a port map and the verification results specified in the quotation.',
       'Shot 1: an unlabeled outlet — “An outlet, but where does it go?”\nShot 2: matching outlet and panel labels — “Identify both ends consistently.”\nShot 3: fictional port map and test folder — “Define what gets checked and handed over.”\nClose: “Prepare your project scope with Opticable.”')},
'fiber-optic-installation':{
 'routes':('installation-fibre-optique','fiber-optic-installation'),
 'fr':('Relier des immeubles : préparer le parcours avant la fibre',
       'Pour relier des bâtiments, la première question concerne le parcours disponible. Quels locaux techniques faut-il joindre? Les passages sont-ils accessibles et autorisés? Une liaison extérieure ou souterraine doit être étudiée selon les conditions réelles du site.\n\nPréparez un plan des bâtiments et indiquez les équipements aux deux extrémités. La longueur approximative, les usages du réseau, les passages existants et les possibilités d’alimentation aident à cadrer l’évaluation. Ils ne suffisent pas à choisir un câble ou des modules optiques. La compatibilité doit être vérifiée.\n\nLa portée peut distinguer le parcours, le câble, les terminaisons, les équipements actifs et les vérifications. Demandez comment les extrémités seront repérées et quels résultats seront remis. Gardez aussi une trace du trajet retenu pour les interventions futures.\n\nUne première fiche pour Opticable peut contenir le plan, les distances approximatives et les contraintes d’accès. N’y ajoutez aucun mot de passe. Le choix technique et le coût doivent suivre l’évaluation, sans présumer des autorisations de passage.',
       'Deux immeubles à relier? Commencez par un plan du parcours, les locaux techniques et les autorisations d’accès. Le choix de fibre et des équipements vient après les vérifications de terrain et de compatibilité.',
       'Une distance suffit-elle pour choisir la fibre?\nNon. Le parcours, l’environnement, les terminaisons et les équipements doivent aussi être évalués.\n\nQue préparer avant une visite?\nUn plan, les distances approximatives, les usages attendus et les contraintes de passage.',
       'Plan 1 : schéma original de deux bâtiments — « Quels points faut-il relier? »\nPlan 2 : trajet pointillé — « Quel parcours est disponible et autorisé? »\nPlan 3 : deux équipements sans marque — « Vérifiez les deux extrémités. »\nConclusion : « Définissez la liaison avant de choisir les composants. »'),
 'en':('Connecting buildings: plan the route before selecting fiber',
       'When connecting buildings, begin with the available route. Which technical rooms need to connect? Are the pathways accessible and authorized? An outdoor or underground link needs assessment against actual site conditions.\n\nPrepare a building plan and identify the equipment at both ends. Approximate distance, network use, existing pathways and power availability help frame the assessment. They do not determine the cable or optical modules on their own. Compatibility needs verification.\n\nThe scope can separate the pathway, cable, terminations, active equipment and verification. Ask how the endpoints will be labeled and which results will be handed over. Keep a record of the chosen route for future maintenance.\n\nAn initial Opticable brief can include the plan, approximate distances and access constraints. Leave out passwords. Technical selection and pricing should follow assessment, without assuming permission to use a route.',
       'Connecting two buildings? Start with a route plan, technical-room locations and access permissions. Fiber and equipment selection follows site and compatibility checks.',
       'Is distance enough to select fiber?\nNo. The route, environment, terminations and equipment also need assessment.\n\nWhat should I prepare for a visit?\nA plan, approximate distances, intended use and pathway constraints.',
       'Shot 1: original diagram of two buildings — “Which endpoints need a connection?”\nShot 2: dotted route — “Which pathway is available and authorized?”\nShot 3: two unbranded devices — “Verify both ends.”\nClose: “Define the link before selecting components.”')},
'access-control-systems':{
 'routes':('systemes-controle-acces','access-control-systems'),
 'fr':('Contrôle d’accès : définir qui peut passer, où et quand',
       'Le point de départ d’un contrôle d’accès est une règle d’usage : quelles personnes doivent accéder à quelles portes et pendant quelles périodes? Une liste des portes et des horaires aide davantage qu’un simple choix de lecteur.\n\nPour chaque porte, relevez l’usage actuel, le type de quincaillerie à faire évaluer et les responsables des autorisations. Décrivez l’arrivée d’un nouvel utilisateur, la perte d’un identifiant et le retrait d’un accès. Ces situations demandent un processus clair, même avec une installation récente.\n\nLe réseau, l’alimentation et la gestion des utilisateurs doivent être examinés avec le matériel de porte. Les exigences de sortie et les contraintes du bâtiment nécessitent une vérification appropriée; aucune modification de serrure ne devrait être présumée compatible à distance.\n\nPréparez pour Opticable une liste de portes, les horaires et les rôles qui administreront les accès. Ne transmettez pas de codes actuels. Une portée documentée permet de préciser le matériel, la configuration, la formation et les essais à discuter.',
       'Votre projet de contrôle d’accès commence par une matrice simple : porte, groupe autorisé, horaire, responsable. Ajoutez la procédure de retrait d’un accès avant de choisir les lecteurs.',
       'Dois-je envoyer mes codes actuels?\nNon. Décrivez les usages et les rôles sans transmettre de codes.\n\nPeut-on choisir une serrure à partir d’une photo?\nLa porte, la quincaillerie et les exigences du bâtiment nécessitent une évaluation adaptée.',
       'Plan 1 : matrice portes/groupes/horaires fictive — « Qui, où et quand? »\nPlan 2 : identifiant barré, sans code — « Comment retirer un accès? »\nPlan 3 : liste de vérification — « Évaluez la porte et son environnement. »\nConclusion : « Commencez par vos règles d’usage. »'),
 'en':('Access control: define who can enter, where and when',
       'An access-control project starts with an operating rule: which people need access to which doors, and at what times? A door and schedule list is more useful than choosing a reader first.\n\nFor each door, record its current use, the hardware that needs assessment and the people responsible for permissions. Describe onboarding, a lost credential and access removal. These situations need a clear process even with new equipment.\n\nNetwork connectivity, power and user administration need review alongside the door hardware. Egress requirements and building constraints need appropriate verification; lock compatibility cannot be assumed from a remote description.\n\nPrepare a door list, schedules and administrator roles for Opticable. Do not send existing codes. A documented scope helps clarify the hardware, configuration, training and testing to discuss.',
       'Start access-control planning with a simple matrix: door, authorized group, schedule and responsible person. Add the process for removing access before selecting readers.',
       'Should I send existing access codes?\nNo. Describe roles and usage without sharing codes.\n\nCan a lock be chosen from a photo?\nThe door, hardware and building requirements need appropriate assessment.',
       'Shot 1: fictional door/group/schedule matrix — “Who, where and when?”\nShot 2: revoked credential icon, no code — “How is access removed?”\nShot 3: assessment checklist — “Review the door and its environment.”\nClose: “Start with your operating rules.”')},
'intercom-systems':{
 'routes':('systemes-interphone','intercom-systems'),
 'fr':('Intercom : tester le trajet d’un appel visiteur',
       'Un visiteur appelle à l’entrée. Qui doit répondre? Depuis quel appareil? Que doit-il se passer en cas d’absence? Décrire ce trajet aide à préparer un projet d’intercom sans commencer par les fonctionnalités d’un modèle.\n\nInventoriez les entrées, les postes existants, les occupants ou groupes à joindre et les périodes de service. Pour chaque scénario, séparez la conversation, la vérification du visiteur et l’éventuelle commande d’ouverture. Une communication réussie ne suffit pas à valider le fonctionnement de la porte.\n\nLe câblage, le réseau, l’alimentation et la compatibilité avec le matériel en place doivent être examinés. Une intégration avec un contrôle d’accès exige de définir les responsabilités et les essais. La reprise d’un équipement existant se confirme après vérification.\n\nApportez à Opticable un schéma simple des entrées et un exemple de parcours d’appel. N’envoyez ni codes ni listes nominatives d’occupants pour cette première discussion. Le dossier peut ensuite préciser le matériel, les scénarios d’essai et la remise en service.',
       'Pour cadrer un intercom, dessinez le parcours d’un appel : entrée, personne qui répond, appareil utilisé, procédure en cas d’absence. Vérifiez séparément la communication et la commande de porte.',
       'Un intercom existant peut-il être réutilisé?\nLa compatibilité du câblage et du matériel doit être vérifiée avant de le confirmer.\n\nQue faut-il tester?\nLes scénarios d’appel, les réponses en cas d’absence et toute commande de porte prévue dans la portée.',
       'Plan 1 : bouton d’appel illustré — « Le visiteur appelle. »\nPlan 2 : flèches vers un poste générique — « Qui répond, et que se passe-t-il en cas d’absence? »\nPlan 3 : communication et porte séparées — « Vérifiez chaque étape. »\nConclusion : « Préparez vos scénarios avant le choix du matériel. »'),
 'en':('Intercom planning: follow a visitor’s call',
       'A visitor calls from the entrance. Who should answer? On which device? What happens if no one is available? Describing that path helps plan an intercom project before focusing on a particular model.\n\nList the entrances, existing stations, people or groups to reach and service hours. For each scenario, separate the conversation, visitor verification and any door-release command. A successful call alone does not verify the door operation.\n\nCabling, networking, power and compatibility with existing hardware need assessment. An access-control integration needs clear responsibilities and testing. Reusing existing equipment must be confirmed after verification.\n\nBring Opticable a simple entrance diagram and an example call flow. Do not send codes or named occupant lists for an initial discussion. The scope can then define equipment, test scenarios and the return to service.',
       'Plan an intercom by tracing a visitor’s call: entrance, person answering, device used and fallback when no one answers. Check communication and door release as separate steps.',
       'Can existing intercom equipment be reused?\nCabling and hardware compatibility need verification before reuse can be confirmed.\n\nWhat should be tested?\nCall scenarios, unanswered calls and any door-release function included in the scope.',
       'Shot 1: illustrated call button — “The visitor calls.”\nShot 2: arrows to an unbranded station — “Who answers, and what happens if nobody does?”\nShot 3: separate call and door symbols — “Check each step.”\nClose: “Prepare the scenarios before selecting equipment.”')}
}


def generate(native, context, now):
    out=[];prior=set(context.get('artifact_hashes',[]));history=context.get('prior_texts',[])
    for service,pack in PACKS.items():
        for index,lang in enumerate(('fr','en')):
            title,article,post,faq,video=pack[lang]
            source=f'https://opticable.ca/{lang}/services/{pack["routes"][index]}/'
            evidence=[{'source':source,'kind':'VERIFIED_NATIVE_SERVICE_SOURCE','source_commit':'4cd93f92abb86965304f673a03f73271064b454c',
                       'demand_evidence':'Owner service priority; no search volume or conversion lift inferred','objective':'Better scoped project inquiries'}]
            feedback=next((f for f in reversed(context.get('feedback',[])) if f.get('service')==service and f.get('language')==lang and f.get('choice') in ('REJECT','REQUEST_REVISION') and f.get('rule')),None)
            revision=None
            if feedback:
                revision=feedback['asset_sha256']
                if feedback['rule']=='SHORTER':article=article.split('\n\n')[0]+'\n\n'+article.split('\n\n')[-1]
                elif feedback['rule']=='SCOPING':article=('À préciser : portée, accès et livrables.\n\n' if lang=='fr' else 'Define scope, access and handover records.\n\n')+article
            labels=('Article / candidat de page','Publication sociale','FAQ','Script vidéo / storyboard','Variante publicitaire sans budget') if lang=='fr' else ('Article / page candidate','Social post','FAQ','Video script / storyboard','Advertising variation without budget')
            ad=(title+'\nPréparez une évaluation avec Opticable. Portée à confirmer avant soumission.' if lang=='fr' else title+'\nPrepare an assessment with Opticable. Scope needs confirmation before a quotation.')
            text=title+'\n\n'+'\n\n'.join(label+'\n'+body for label,body in zip(labels,(article,post,faq,video,ad)))+'\n\n'+source+'\n'
            h=sha256(text.encode()).hexdigest()
            if h in prior:continue
            checks=quality(text,evidence,history=[p for p in history if sha256(p.encode()).hexdigest()!=revision])
            out.append({'logical_path':f'campaigns/service-intent/{service}/{lang}/articles/draft/field-guide-pack.txt','content':text,
                        'service':service,'language':lang,'platform':'article / social / FAQ / video / ad draft','recipe':'service-field-guide',
                        'source_evidence':evidence,'evidence_ids':[],'quality_checks':checks,'licensing':'ORIGINAL_TEXT','revision_of':revision,
                        'objective':'Qualified scope conversations; actual business lift unmeasured','estimated_incremental_cost':'0','required_execution_approval':'PUBLICATION_EXACT_ITEM_CHANNEL_TIME'})
    return out


def calendar(now):
    monday=now.date()+timedelta(days=(7-now.weekday())%7)
    slots=[('IP cameras / Caméras IP','Compare priority scenes / Définir les scènes prioritaires'),
           ('AI loss prevention / Prévention des pertes IA','Human review workflow / Processus de vérification humaine'),
           ('Structured cabling / Câblage structuré','Labels and handover / Repérage et remise documentaire'),
           ('Access control / Contrôle d’accès','Doors, roles, schedules / Portes, rôles, horaires'),
           ('Fiber / Fibre','Route and endpoint assessment / Parcours et extrémités'),
           ('Intercom / Intercom','Visitor call flow / Trajet d’appel visiteur'),
           ('Wi-Fi / Wi-Fi','Coverage versus capacity / Couverture et capacité')]
    return 'Rolling bilingual editorial calendar — week of '+monday.isoformat()+'\n\n'+ '\n'.join(
        f'{monday+timedelta(days=i)} | {service} | {angle} | Existing registered finished draft; review revision/hash before selection | UNPUBLISHED; exact publication approval pending'
        for i,(service,angle) in enumerate(slots))+'\n\nDo not fill an empty slot with repeated copy. Check owner feedback and measured results before reusing a topic. No publishing schedule is activated.\n'


def diagram(lang):
    fr=lang=='fr';title='Du parcours au dossier de liaison' if fr else 'From pathway to link records'
    labels=['Parcours','Extrémités','Vérification','Dossier remis'] if fr else ['Pathway','Endpoints','Verification','Handover records']
    cards=''.join(f'<rect x="{50+i*280}" y="210" width="245" height="150" rx="18" fill="#173d2b" stroke="#8be3af"/><text x="{172+i*280}" y="295" text-anchor="middle" fill="#fff" font-size="23">{escape(label)}</text>' for i,label in enumerate(labels))
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630" role="img" aria-labelledby="title"><title id="title">{escape(title)}</title><rect width="1200" height="630" fill="#10251b"/><text x="50" y="110" fill="#fff" font-family="sans-serif" font-size="39">{escape(title)}</text><g font-family="sans-serif">{cards}</g><text x="50" y="540" fill="#8be3af" font-family="sans-serif" font-size="25">Opticable · {"Portée à valider avant soumission" if fr else "Scope to verify before quotation"}</text></svg>\n'
