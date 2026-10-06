#!/usr/bin/env python3
"""Manual private preview from existing authenticated evidence; no network."""
from datetime import datetime,timezone
from collections import Counter
import json,os,sys
from pathlib import Path
ROOT=Path('/var/lib/optibrain/phase34')
CODE=Path(__file__).resolve().parents[2]
def main():
    if os.geteuid()!=0:raise ValueError('Root-only private data')
    os.umask(0o077);sys.path.insert(0,str(CODE/'apps/workflow-api'))
    from workflow.automation.sales_conversations import build_bundle
    from workflow.automation.optimization_store import validate
    apollo=json.loads(Path('/var/lib/optibrain/sales-intelligence/apollo.json').read_text())
    mail=json.loads((ROOT/'mail-reconciled-validated.json').read_text());mail['origin']='MANUAL'
    crm=json.loads(Path('/var/lib/optibrain/lifecycle/business-observation.json').read_text())['snapshot']
    crm={k:crm.get(v,[]) for k,v in {'Leads':'leads','Contacts':'contacts','Accounts':'accounts','Deals':'deals','Service_Locations':'service_locations'}.items()}
    crm.update(json.loads(Path('/var/lib/optibrain/sales-intelligence/crm.json').read_text())['crm'])
    prospects=json.loads(Path('/run/optibrain-readiness/prospect-details.json').read_text())
    now=datetime.now(timezone.utc);at=now.isoformat()
    load=lambda f:json.loads((ROOT/f).read_text())
    sequence={'schema':1,'at':at,'origin':'MANUAL','periods':{p:load(f)['summary'] for p,f in [('last_7_days','analytics7d.json'),('last_30_days','analytics-last_30_days.json'),('last_3_months','analytics-last_3_months.json')]},
              'variants':load('variant-performance.json')['summary'],'issues':[
        {'sequence_id':'6ab91e8fd7481600147f58cb','kind':'BOUNCE','title':'Clean recruitment list before any reactivation',
         'current_state':'INACTIVE — unchanged','why':'Native analytics reports 13 bounces / 46 sends (28.3%). Metadata splits 12 bounced + 1 spam-blocked; retain denominator/source differences.',
         'proposed_copy':'Do not reactivate the unchanged list. Prepare exact verification/replacement review for invalid addresses and stale roles; preserve unsubscribe/DNC history.',
         'risk':'List quality and suppression; no removal or re-enrollment now.','measurement':'Delivered, bounce, unsubscribe and independently classified replies; no opens winner.'},
        {'sequence_id':'6ab2db604d5d0500107af236','kind':'MANUAL_TASK_BURDEN','title':'Review 124 unfinished overdue subcontracting tasks',
         'current_state':'ACTIVE — unchanged','why':'30-day/historical report has 124 unfinished overdue tasks; 7-day has 98 and zero completed LinkedIn tasks. Current task search confirms 124 entries; first 100 privately sampled.',
         'step_references':['6ab329b03efe57000c1dc0ca','6ab329b03efe57000c1dc0cc'],
         'proposed_copy':'Prepare a per-contact keep/research/skip recommendation for the oldest LinkedIn steps; owner decides whether to simplify future manual steps. No bulk completion or auto-LinkedIn action.',
         'risk':'A task is not proof that a prospect needs another touch; recheck reply/manual owner context first.'},
        {'sequence_id':'6ab329e03efe57000c1dc14b','kind':'CLAIM_REVIEW','title':'Review AI loss-prevention claims before any new variant',
         'current_state':'ACTIVE — unchanged','why':'Existing copy includes hosting/compliance claims without independent current business proof in this mission; 27 delivered / 1 reply is too small and reply body remains unbound.',
         'proposed_copy':{'subject':'Évaluer la prévention des pertes avec vos caméras',
                          'body':'Bonjour,\n\nVotre équipe évalue-t-elle des outils pour repérer les situations de vol en magasin? Opticable peut vous aider à examiner la compatibilité de vos caméras et le fonctionnement d’une solution de détection. Une discussion permettrait de préciser vos besoins avant toute proposition.\n\nMerci,\nYan-Erik Boucher'},
         'risk':'No guaranteed savings, Canadian-hosting assertion, legal compliance claim or automated variant change.'}]}
    bundle=build_bundle(apollo,mail,crm,prospects['rows'],now=now,sequence_evidence=sequence)
    for row in bundle['proposals']+bundle['priorities']+bundle['assets']:validate(row['record'])
    (ROOT/'prepared-bundle.json').write_text(json.dumps(bundle,ensure_ascii=False))
    (ROOT/'sequence-evidence.json').write_text(json.dumps(sequence,ensure_ascii=False))
    summary={'schema':1,'at':at,'provider_writes':0,'named_organizations_snapshot':len(prospects['rows']),
      'conversations':len(bundle['conversations']),'reply_classes':dict(Counter(c['reply_class'] for c in bundle['conversations'])),
      'urgency':dict(Counter(c['urgency'] for c in bundle['conversations'])),
      'CRM_context':dict(Counter(c['CRM_references']['state'] for c in bundle['conversations'])),
      'suppressed_conversations':sum(c['suppression'] for c in bundle['conversations']),
      'proposals':dict(Counter(p['record']['proposal_type'] for p in bundle['proposals'])),
      'coverage':bundle['coverage'],'coverage_gaps':bundle['coverage_gaps'],'hooks':len(bundle['assets']),
      'drafts':sum(bool(c['draft']) for c in bundle['conversations'])}
    (ROOT/'preview-summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary))
if __name__=='__main__':main()
