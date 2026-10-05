"""Evidence confidence, identity binding, collision and no-execution invariants."""
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
import json
import tempfile
import unittest
from test_phase30_triggers import fixture, NOW
from workflow.automation.trigger_runtime import build_queue
from workflow.automation.prospect_universe import ProspectStore, build_universe
from workflow.automation.prospect_enrichment import (apply, actor_seeds, validate, details,
    render_detail, resolve_document, lookup_due, remember_lookup, useful_role)
from workflow.automation.trigger_intelligence import sales_rows


class EnrichmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=ProspectStore(Path(self.tmp.name)/'db');self.row,self.apollo,self.crm=fixture()
        self.crm['_identity_complete']=True
        self.row.pop('domain',None)
        self.queue=build_queue(self.store,[self.row],self.apollo,self.crm,now=NOW,crm_at=NOW.isoformat(),feedback={},source_health=[])
        self.view=build_universe(self.store,self.queue,self.apollo,self.crm,now=NOW,crm_at=NOW.isoformat())
        self.p=self.view['records'][0]
        self.proof={'prospect_id':self.p['prospect_id'],'bindings':[{'provider':self.p['source_provenance'][0]['provider'],'record_id':self.p['source_provenance'][0]['record_id']}],
            'source_url':'https://company.test/team','observed_at':NOW.isoformat(),'domain':'company.test',
            'domain_confidence':'OFFICIAL','domain_evidence':'Official company directory names the organization.',
            'contacts':[{'id':'official:one','name':'Person','title':'Operations Manager','source_url':'https://company.test/team',
                'observed_at':NOW.isoformat(),'confidence':'SUPPORTED_CURRENT','current_employer_proven':True,'email':None}]}
        self.doc={'schema':1,'at':NOW.isoformat(),'organizations':[self.proof],'actors':[]}

    def run_apply(self,now=NOW):
        return apply(self.store,self.view,self.doc,self.apollo,self.crm,now=now,crm_at=NOW.isoformat())

    def test_domain_roles_and_new_collision_are_separate_no_send(self):
        self.run_apply();self.assertEqual(self.p['domain_confidence'],'OFFICIAL')
        self.assertEqual(self.p['contact_coverage']['valid_roles'],1)
        self.assertEqual(self.p['enrichment_readiness'],'PROSPECTING_READY')
        self.assertFalse(self.p['contacts'][0]['contact_allowed']);self.assertFalse(self.p['outbound_authorized'])

    def test_bare_domain_and_inferred_email_rejected(self):
        for key in ['domain_evidence','bindings']:
            doc=deepcopy(self.doc);doc['organizations'][0].pop(key)
            with self.assertRaises(ValueError):validate(doc)
        self.proof['contacts'][0]['email']='invented@company.test'
        with self.assertRaises(ValueError):validate(self.doc)

    def test_native_source_mismatch_held_not_applied(self):
        self.proof['bindings'][0]['record_id']='wrong';view=self.run_apply()
        self.assertEqual(len(view['enrichment_holds']),1);self.assertIsNone(self.p['domain'])

    def test_likely_retained_not_counted_and_stale_not_refreshed(self):
        c=self.proof['contacts'][0];c['confidence']='LIKELY';c['current_employer_proven']=False
        self.run_apply();self.assertEqual(self.p['contact_coverage']['valid_roles'],0)
        c['confidence']='SUPPORTED_CURRENT';c['current_employer_proven']=True;c['observed_at']=(NOW-timedelta(days=181)).isoformat()
        self.run_apply();self.assertEqual(self.p['contacts'][0]['confidence'],'STALE')

    def test_current_employer_required(self):
        self.proof['contacts'][0]['current_employer_proven']=False
        with self.assertRaises(ValueError):validate(self.doc)

    def test_multiple_roles_retained_not_same_email_double_count(self):
        one=self.proof['contacts'][0];one.update(email='person@company.test',email_source_url=one['source_url'])
        two={**one,'id':'official:two','title':'Facilities Manager'};self.proof['contacts'].append(two)
        self.run_apply();self.assertEqual(self.p['contact_coverage']['valid_roles'],1)
        two['email']='other@company.test';self.run_apply();self.assertEqual(self.p['contact_coverage']['valid_roles'],2)

    def test_shared_government_host_does_not_clear_collision(self):
        self.proof.update(domain='quebec.ca',shared_domain=True)
        self.run_apply();self.assertEqual(self.p['collision']['classification'],'UNKNOWN')
        self.assertNotEqual(self.p['enrichment_readiness'],'PROSPECTING_READY')

    def test_foreign_company_retained_but_not_ready(self):
        self.proof['geography_class']='FOREIGN';self.run_apply()
        self.assertEqual(self.p['prospecting_status'],'TERMINAL IGNORE')
        self.assertEqual(self.p['ignore_audit']['reason'],'WRONG_COUNTRY')
        self.assertNotEqual(self.p['enrichment_readiness'],'PROSPECTING_READY')

    def test_active_apollo_and_customer_not_cold(self):
        self.apollo['contacts']=[{'id':'p','account':{'primary_domain':'company.test'},'email':'p@company.test','email_status':'verified','title':'Operations Manager','updated_at':NOW.isoformat(),'contact_campaign_statuses':[{'status':'active'}]}]
        self.run_apply();self.assertEqual(self.p['enrichment_readiness'],'ACTIVE_ELSEWHERE')
        self.apollo['contacts']=[];self.crm['Accounts']=[{'id':'a','Website':'company.test','Account_Type':'customer'}]
        self.run_apply();self.assertEqual(self.p['prospecting_status'],'EXISTING CUSTOMER')

    def test_open_deal_and_native_opt_out(self):
        self.crm['Accounts']=[{'id':'a','Website':'company.test'}];self.crm['Deals']=[{'id':'d','Account_Name':{'id':'a'},'Stage':'Qualification'}]
        self.run_apply();self.assertEqual(self.p['prospecting_status'],'ACTIVE DEAL')
        self.proof['contacts'][0].update(email='p@company.test',email_source_url='https://company.test/team')
        self.crm['Contacts']=[{'id':'c','Account_Name':{'id':'a'},'Email':'p@company.test','Email_Opt_Out':True}]
        self.run_apply();self.assertEqual(self.p['enrichment_readiness'],'SUPPRESSED')

    def test_bad_bundle_reuses_dated_evidence_and_replay_is_immutable(self):
        good,state=resolve_document(self.store,self.doc,now=NOW);self.assertEqual(state,'WORKING')
        older,state=resolve_document(self.store,{'schema':9},now=NOW+timedelta(days=1))
        self.assertTrue(state.startswith('PARTIAL'));self.assertEqual(good,older)
        self.run_apply();self.run_apply()
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM acquisition_enrichment_proofs').fetchone()[0],1)

    def test_failed_lookup_fingerprint_blocks_exact_repeat_not_new_role(self):
        query={'domain':'company.test','titles':['Operations']}
        remember_lookup(self.store,'apollo','people',query,{'state':'NO_MATCH'},now=NOW)
        self.assertFalse(lookup_due(self.store,'apollo','people',query,now=NOW+timedelta(hours=1)))
        self.assertTrue(lookup_due(self.store,'apollo','people',query,now=NOW+timedelta(days=15)))
        self.assertTrue(lookup_due(self.store,'apollo','people',{'domain':'company.test','titles':['IT']},now=NOW))

    def test_unresolved_actor_stays_research_expired_event_stays_closed(self):
        self.row.pop('company_name');self.row.pop('company_identity');self.row['actors']=[];self.row['status']='EXPIRED'
        q=build_queue(self.store,[self.row],self.apollo,self.crm,now=NOW,crm_at=NOW.isoformat(),feedback={},source_health=[])
        event=next(r for r in q['rows'] if not r.get('company_name'))
        a={'trigger_id':event['trigger_id'],'source_record_id':event['source_record_id'],'name':'Known Tenant','role':'TENANT',
            'confidence':'SUPPORTED','organization_key':'tenant-native','source_url':'https://tenant.test/contact','observed_at':NOW.isoformat(),'domain':'tenant.test'}
        doc={'schema':1,'organizations':[],'actors':[a]};seeds=actor_seeds(doc,q,now=NOW)
        u=build_universe(self.store,q,self.apollo,self.crm,now=NOW,crm_at=NOW.isoformat(),seeds=seeds);u['_events']=q['rows']
        u=apply(self.store,u,doc,self.apollo,self.crm,now=NOW,crm_at=NOW.isoformat())
        project=next(p for p in u['records'] if p['entity_kind']=='UNRESOLVED PROJECT');tenant=next(p for p in u['records'] if p['canonical_name']=='Known Tenant')
        self.assertEqual(project['identity_status'],'UNRESOLVED');self.assertEqual(tenant['current_trigger_count'],0)
        self.assertEqual(sales_rows(q['rows']),[])

    def test_functional_role_endpoint_is_not_a_person(self):
        self.proof['contacts'][0].update(name=None,contact_kind='ROLE_ENDPOINT',title='Service ressources matérielles')
        self.run_apply();self.assertEqual(self.p['contact_coverage']['functional_endpoints'],1)
        self.assertEqual(self.p['contact_coverage']['named_people'],0)

    def test_role_strategy_and_private_detail_no_sensitive_contact_methods(self):
        for title in ['Président','Estimateur de projets','Directeur ressources matérielles','Facilities Manager']:
            self.assertTrue(useful_role(title))
        self.assertFalse(useful_role('Human Resources Payroll Clerk'))
        self.proof['contacts'][0].update(name='<script>',email='person@company.test',email_source_url='https://company.test/team')
        self.run_apply();d=details(self.view);page=render_detail(d['rows'][0])
        self.assertNotIn('<script>',page);self.assertNotIn('person@company.test',json.dumps(d))
        self.assertEqual(d['scope'],'live');self.assertTrue(d['read_only'])

    def test_enrichment_does_not_change_strict_sales_admission(self):
        before=sales_rows(deepcopy(self.queue['rows']));self.run_apply()
        self.assertEqual(before,sales_rows(self.queue['rows']))

    def test_native_crm_link_requires_public_exact_email_not_similar_name(self):
        self.proof.update(crm_account_id='a',crm_contact_email='person@company.test')
        self.crm['Accounts']=[{'id':'a','Account_Name':'Company'}]
        self.crm['Contacts']=[{'id':'c','Account_Name':{'id':'a'},'Email':'person@company.test'}]
        u=self.run_apply();self.assertEqual(u['enrichment_holds'][0]['reason'],'NATIVE CRM CONTACT BINDING MISMATCH')
        self.assertEqual(self.p['collision']['crm_account_ids'],[])
        self.proof['contacts'][0].update(email='person@company.test',email_source_url='https://company.test/team')
        u=self.run_apply();self.assertEqual(self.p['collision']['crm_account_ids'],['a'])

    def test_prospect_details_require_human_and_remain_get_only(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from types import SimpleNamespace
        from unittest.mock import patch
        from workflow.operator_phase7_api import install_phase7_canary_routes
        class Verifier:
            def verify(self,token):
                if token!='human':raise ValueError('Human required')
                return SimpleNamespace(actor='owner',subject='owner')
        self.run_apply();payload=details(self.view)
        with patch('workflow.automation.today.read_internal_attention',return_value=payload) as read:
            app=FastAPI();install_phase7_canary_routes(app,verifier=Verifier(),client=object(),store=SimpleNamespace(db_path=Path(self.tmp.name)/'operator.db'),account_id='1',from_address='fixture@example.test',allowed_origin='https://example.test',clock=lambda:NOW)
            client=TestClient(app);path='/v1/operator/acquisition?prospect_id='+self.p['prospect_id']
            self.assertEqual(client.get(path).status_code,401);read.assert_not_called()
            headers={'Cf-Access-Jwt-Assertion':'human'}
            response=client.get(path,headers=headers);self.assertEqual(response.status_code,200)
            self.assertIn('no-store',response.headers['cache-control'])
            self.assertEqual(client.get('/v1/operator/acquisition?prospect_id=../etc/passwd',headers=headers).status_code,404)
            self.assertEqual(client.post(path,headers=headers).status_code,405)


if __name__=='__main__':unittest.main()
