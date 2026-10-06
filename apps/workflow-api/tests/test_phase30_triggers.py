"""Isolated fixtures only: no real records, providers, messages or uploads."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import json
import tempfile
import unittest
import httpx

from workflow.automation.trigger_intelligence import assess, sales_rows, render_queue
from workflow.automation.trigger_runtime import build_queue, collect, due, projection, observe, research_roles
from workflow.automation.trigger_sources import PublicReader, permits, seao, expansion, TRICOR
from workflow.automation.trigger_store import TriggerStore
from workflow.automation.sales_feedback import SalesFeedback

NOW = datetime(2026, 10, 4, 22, tzinfo=timezone.utc)


def fixture():
    row = {'source_provider': 'fixture_permit', 'source_record_id': 'p1', 'source_url': 'https://company.test/project',
           'source_version': 'v1', 'source_version_at': (NOW-timedelta(days=1)).isoformat(),
           'source_effective_at': NOW.isoformat(), 'last_verified_at': NOW.isoformat(), 'publish_date': (NOW-timedelta(days=1)).isoformat(),
           'status': 'ISSUED', 'trigger_type': 'BUILDING PERMIT', 'title': 'New warehouse network and CCTV installation',
           'geography_class': 'MONTRÉAL', 'company_name': 'Company', 'domain': 'company.test',
           'company_identity': {'confidence': 'SUPPORTED', 'source_url': 'https://company.test/project'},
           'actors': [{'name': 'Company', 'role': 'FACILITY OPERATOR', 'confidence': 'SUPPORTED',
                       'source_actor_id': 'operator1', 'source_url': 'https://company.test/project'}]}
    apollo = {'at': NOW.isoformat(), 'contacts_complete': True, 'contacts': [], 'accounts': [], 'stages': [], 'messages': [], 'replies': []}
    crm = {'Accounts': [], 'Contacts': [], 'Leads': [], 'Deals': [], 'Services': [], 'Service_Locations': [], '_identity_complete': True}
    from workflow.automation.observation_completeness import complete, CRM_REQUIRED, APOLLO_REQUIRED
    crm['Customer_Context']=[]
    for name in APOLLO_REQUIRED:apollo.setdefault(name,[])
    crm['_modules']={n:complete(crm[n],NOW.isoformat()) for n in CRM_REQUIRED}
    apollo['modules']={n:complete(apollo[n],NOW.isoformat()) for n in APOLLO_REQUIRED}
    return row, apollo, crm


def decision(row, apollo=None, crm=None, **kw):
    _, a, c = fixture()
    return assess(row, apollo or a, crm or c, now=kw.pop('now', NOW), crm_at=kw.pop('crm_at', NOW.isoformat()), **kw)


class TriggerPolicyTests(unittest.TestCase):
    def test_native_procurement_identity_without_matchable_collision_stays_review(self):
        r,a,c=fixture();r.pop('domain');r.update(source_provider='seao',trigger_type='PUBLIC TENDER',status='OPEN',closing_date=(NOW+timedelta(days=2)).isoformat(),raw={'buyer':{'id':'buyer'}})
        r['company_identity']={'confidence':'EXACT','native_buyer_id':'buyer','source_url':r['source_url']}
        d=decision(r,a,c)
        self.assertEqual(d['company_resolution_status'],'EXACT');self.assertEqual(d['collision']['classification'],'UNKNOWN')
        self.assertEqual(d['priority_class'],'REVIEW');self.assertFalse(d['sales_review_eligible'])

    def test_exact_warehouse_with_native_crm_identity_is_owner_review(self):
        r,a,c = fixture();c['Accounts']=[{'id':'a','Website':'company.test'}]
        r['company_identity']['crm_account_id']='a'
        d=decision(r,a,c)
        self.assertEqual(d['company_resolution_status'],'EXACT');self.assertEqual(d['priority_class'],'REVIEW')
        self.assertEqual(d['evidence_confidence'],'STRONG');self.assertTrue(d['sales_review_eligible'])
        self.assertEqual(d['service_fit']['primary'],['network infrastructure'])
        self.assertIn('IP cameras / CCTV',d['service_fit']['secondary'])
        self.assertFalse(d['contact_allowed']);self.assertFalse(d['crm_promote_allowed'])

    def test_applicant_and_architect_do_not_become_buyer(self):
        r,a,c=fixture();r.pop('domain');r.pop('company_identity')
        r['actors']=[{'role':'ARCHITECT','name':'Architect','confidence':'EXACT','source_actor_id':'id','source_url':'https://company.test/'}]
        d=decision(r);self.assertEqual(d['priority_class'],'RESEARCH');self.assertEqual(d['actor_confidence'],'UNRESOLVED')
        self.assertEqual(sales_rows([d]),[])

    def test_foreign_and_unknown_french_geography_cannot_enter_sales(self):
        r,_,_=fixture();r['title']='Installation de câblage'
        for geo in ('FOREIGN','OTHER CANADA','UNKNOWN'):
            with self.subTest(geo=geo):
                d=decision({**r,'geography_class':geo});self.assertFalse(d['sales_review_eligible'])
                self.assertIn(d['priority_class'],{'IGNORE','RESEARCH'})
        d=decision({**r,'geography_class':'FOREIGN'})
        self.assertEqual(projection({'rows':[d]})['rows'],[])

    def test_expired_cancelled_and_unknown_tender_status_are_held(self):
        r,_,_=fixture();r.update(trigger_type='PUBLIC TENDER',status='OPEN',closing_date=(NOW-timedelta(seconds=1)).isoformat())
        d=decision(r);self.assertEqual(d['status'],'CLOSED');self.assertFalse(d['sales_review_eligible'])
        for state in ('CANCELLED','AWARDED','UNKNOWN'):
            with self.subTest(state=state):
                d=decision({**r,'status':state,'closing_date':None});self.assertFalse(d['sales_review_eligible'])

    def test_current_open_tender_urgency_requires_recent_publication_coverage(self):
        r,_,_=fixture();r.update(trigger_type='PUBLIC TENDER',status='OPEN',closing_date=(NOW+timedelta(days=3)).isoformat())
        fresh=decision(r);self.assertEqual(fresh['priority_class'],'ACT NOW')
        stale=decision({**r,'source_effective_at':(NOW-timedelta(days=4)).isoformat()})
        self.assertEqual(stale['priority_class'],'REVIEW');self.assertEqual(stale['evidence_confidence'],'MODERATE')
        self.assertFalse(stale['sales_review_eligible'])

    def test_apollo_membership_and_recent_send_preserve_owner(self):
        r,a,c=fixture();a['contacts']=[{'id':'c','email':'p@company.test','email_status':'verified','title':'Facilities Manager',
                                     'contact_campaign_statuses':[{'status':'active'}]}]
        d=decision(r,a,c);self.assertEqual(d['collision']['classification'],'ACTIVE OUTREACH')
        self.assertIn('existing Apollo',d['recommended_next_action']);self.assertFalse(d['cold_send_allowed'])
        self.assertEqual(len(d['collision']['role_candidates']),1)
        a['contacts'][0]['contact_campaign_statuses']=[];a['messages']=[{'contact_id':'c','status':'completed','completed_at':NOW.isoformat()}]
        self.assertEqual(decision(r,a,c)['collision']['classification'],'ACTIVE OUTREACH')

    def test_customer_services_open_deal_and_site_are_not_cold_prospects(self):
        r,a,c=fixture();c['Accounts']=[{'id':'a','Website':'company.test'}]
        c['Services']=[{'id':'s','Linked_Service_Location':{'id':'site'}}];c['Service_Locations']=[{'id':'site','Linked_Account':{'id':'a'}}]
        d=decision(r,a,c);self.assertEqual(d['collision']['classification'],'EXISTING CUSTOMER OPPORTUNITY')
        self.assertEqual(d['collision']['service_location_ids'],['site'])
        c['Deals']=[{'id':'deal','Account_Name':{'id':'a'},'Stage':'Proposal'}]
        self.assertEqual(decision(r,a,c)['collision']['classification'],'OPEN DEAL')
        c['Deals'][0]['Stage']='Closed Lost';self.assertEqual(decision(r,a,c)['collision']['open_deal_ids'],[])

    def test_crm_lead_domain_and_suppression_checked_without_person_email(self):
        r,a,c=fixture();c['Leads']=[{'id':'l','Email':'p@company.test','Email_Opt_Out':True}]
        d=decision(r,a,c);self.assertEqual(d['collision']['classification'],'SUPPRESSED')
        self.assertFalse(d['sales_review_eligible']);self.assertEqual(d['priority_class'],'WATCH')

    def test_likely_actor_weak_identity_corroboration_and_missing_economics(self):
        r,a,c=fixture();r['company_identity']['confidence']='LIKELY';r['actors'][0]['confidence']='LIKELY'
        weak=decision(r);self.assertEqual(weak['priority_class'],'RESEARCH');self.assertEqual(weak['evidence_confidence'],'TENTATIVE')
        r['corroboration']=[{'source_provider':'registry','source_url':'https://registry.test/id'}]
        self.assertEqual(decision(r)['independent_source_count'],2)
        r['company_identity']['confidence']='SUPPORTED';r['actors'][0]['confidence']='SUPPORTED'
        strong=decision(r);self.assertEqual(strong['evidence_confidence'],'STRONG')
        self.assertNotIn('cpc',strong);self.assertFalse(strong['contact_allowed'])

    def test_stale_incomplete_apollo_and_crm_never_clear_sales(self):
        r,a,c=fixture()
        for field in ('apollo','crm'):
            with self.subTest(field=field):
                aa=deepcopy(a);cc=deepcopy(c)
                if field=='apollo':aa['contacts_complete']=False
                else:cc['_identity_complete']=False
                self.assertFalse(decision(r,aa,cc)['sales_review_eligible'])
        self.assertFalse(decision(r,a,c,now=NOW+timedelta(days=10))['sales_review_eligible'])

    def test_owner_suppression_is_sticky_and_review_version_is_visible(self):
        r,a,c=fixture();d=decision(r)
        with tempfile.TemporaryDirectory() as tmp:
            ledger=SalesFeedback(Path(tmp)/'db');ledger.record(d,d['version'],'DO NOT CONTACT','owner',NOW)
            ledger.record(d,d['version'],'GOOD','owner',NOW+timedelta(minutes=1))
            result=decision(r,feedback=ledger.latest())
            self.assertEqual(result['priority_class'],'IGNORE');self.assertFalse(result['sales_review_eligible'])
            self.assertIn('version',ledger.latest()[d['key']])

    def test_ui_escapes_evidence_and_exposes_confidence_and_freshness(self):
        r,_,_=fixture();r['company_name']='<script>alert(1)</script>';d=decision(r)
        html=render_queue({'rows':[d]})
        self.assertNotIn('<script>',html);self.assertIn('STRONG',html);self.assertIn('MONTRÉAL',html);self.assertIn('source coverage',html)


class TriggerPersistenceTests(unittest.TestCase):
    def test_capacity_is_explicit_and_cannot_evict_current_active_records(self):
        r,a,c=fixture()
        with tempfile.TemporaryDirectory() as tmp:
            store=TriggerStore(Path(tmp)/'db');store.MAX_CURRENT=1
            store.upsert(r,now=NOW)
            q=build_queue(store,[{**r,'source_record_id':'other'}],a,c,now=NOW,crm_at=NOW.isoformat(),feedback={},source_health=[])
            self.assertEqual(q['storage_state'],'CAPACITY HELD — OWNER REVIEW REQUIRED')
            self.assertEqual(store.records()[0]['source_record_id'],'p1')
            self.assertEqual(store.version_count(),1)

    def test_terminal_history_retires_only_after_one_year(self):
        r,a,c=fixture();old=NOW-timedelta(days=366)
        with tempfile.TemporaryDirectory() as tmp:
            store=TriggerStore(Path(tmp)/'db')
            for rid,status,date in [('old','CANCELLED',old),('current','CANCELLED',NOW),('active','OPEN',old)]:
                store.upsert({**r,'source_record_id':rid,'source_version_at':date.isoformat(),'status':status},now=NOW)
            store.prune_triggers(NOW)
            self.assertEqual({r['source_record_id'] for r in store.records()},{'current','active'})
            self.assertEqual(store.version_count(),2)

    def test_replay_one_trigger_version_and_first_seen_stable(self):
        r,a,c=fixture()
        with tempfile.TemporaryDirectory() as tmp:
            store=TriggerStore(Path(tmp)/'existing.db')
            first=build_queue(store,[r],a,c,now=NOW,crm_at=NOW.isoformat(),feedback={},source_health=[])
            later={**r,'last_verified_at':(NOW+timedelta(hours=1)).isoformat()}
            second=build_queue(store,[later],a,c,now=NOW+timedelta(hours=1),crm_at=NOW.isoformat(),feedback={},source_health=[])
            self.assertEqual(second['updates'],{'REPLAY':1});self.assertEqual(first['trigger_count'],1)
            self.assertEqual(store.version_count(),1);self.assertEqual(store.records()[0]['first_observed_at'],NOW.isoformat())
            self.assertEqual(first['rows'][0]['company_id'],second['rows'][0]['company_id'])

    def test_latest_addendum_wins_history_survives_and_older_replay_is_held(self):
        r,a,c=fixture()
        with tempfile.TemporaryDirectory() as tmp:
            store=TriggerStore(Path(tmp)/'db');store.upsert(r,now=NOW)
            new={**r,'source_version':'v2','source_version_at':NOW.isoformat(),'status':'CANCELLED'}
            store.upsert(new,now=NOW);self.assertEqual(store.upsert(r,now=NOW)['state'],'OLDER VERSION HELD')
            self.assertEqual(store.records()[0]['status'],'CANCELLED');self.assertEqual(store.version_count(),2)

    def test_test_only_exclusion_unknown_vs_zero_and_shared_domain_identity(self):
        r,a,c=fixture()
        with tempfile.TemporaryDirectory() as tmp:
            store=TriggerStore(Path(tmp)/'db');store.upsert({**r,'test_only':True},now=NOW)
            self.assertEqual(store.records(),[])
            rows=[r,{**r,'source_provider':'registry_project','source_record_id':'z'}]
            q=build_queue(store,rows,a,c,now=NOW,crm_at=NOW.isoformat(),feedback={},source_health=[])
            self.assertEqual(len({row['company_id'] for row in q['rows']}),1)
            self.assertEqual(q['trigger_count'],2);self.assertEqual(q['crm_promotions'],0)
            self.assertEqual(q['rows'][0]['commercial_value_band'],'UNKNOWN')


class PublicSourceTests(unittest.TestCase):
    def test_camera_keyword_does_not_make_scientific_or_sewer_work_a_security_prospect(self):
        from workflow.automation.trigger_sources import relevant
        for title in ['Acquisition de caméra Laue','Inspection caméra de réseaux d’égout','Alarme incendie']:
            with self.subTest(title=title):self.assertFalse(relevant(title))
        self.assertTrue(relevant('Alarme incendie et intercommunication'))
        self.assertTrue(relevant('Modernisation des systèmes de vidéosurveillance'))

    def test_provider_transport_fixed_get_hosts_budget_byte_limit(self):
        calls=[]
        def respond(req):calls.append(req);return httpx.Response(200,json={'ok':True})
        reader=PublicReader(transport=httpx.MockTransport(respond),limit=1)
        try:
            with self.assertRaises(ValueError):reader.get('https://localhost/admin')
            reader.get('https://www.donneesquebec.ca/recherche/api/3/action/package_show')
            with self.assertRaises(ValueError):reader.get('https://www.donneesquebec.ca/research')
            self.assertEqual([r.method for r in calls],['GET'])
            self.assertNotIn('authorization',calls[0].headers)
        finally:reader.close()

    def test_feed_latest_closed_version_is_not_replaced_by_older_open(self):
        r={'ocid':'o','id':'20261003110000','date':'2026-10-03T07:00:00-04:00','buyer':{'id':'b','name':'Buyer'},
           'parties':[{'id':'b','address':{'locality':'Laval','region':'QC','countryName':'CAN'}}],
           'tender':{'status':'active','title':'Installation de caméras','tenderPeriod':{'endDate':'2026-10-09T10:00:00-04:00'}}}
        newer={**r,'id':'20261004110000','tender':{**r['tender'],'status':'cancelled'}}
        rows=seao([newer,r],now=NOW,verified_at=NOW.isoformat(),published_at=NOW.isoformat(),source_url='https://www.donneesquebec.ca/source')
        self.assertEqual(rows[0]['status'],'CANCELLED');self.assertEqual(rows[0]['geography_class'],'LAVAL')
        self.assertEqual(rows[0]['source_version_at'],'2026-10-04T11:00:00+00:00')

    def test_permit_contractors_are_separate_observed_unresolved_actors(self):
        raw={'NO_PERMIS':'p','DATE_EMISSION':'2026-10-01','CATEGORIE_BATIMENT':'COMM, INDUSTR','TYPE_PERMIS_DESCR':'Permis de construction','TYPE_BATIMENT':'Entrepôt','ENTREPRENEUR':'GC Inc.'}
        rows=permits([raw],provider='laval_permit',now=NOW,verified_at=NOW.isoformat())
        self.assertEqual(rows[0]['actors'][0]['role'],'GENERAL CONTRACTOR');self.assertEqual(rows[0]['actors'][0]['confidence'],'UNRESOLVED')

    def test_native_nullable_building_type_does_not_disable_entire_laval_feed(self):
        rows=[{'NO_PERMIS':'a','DATE_EMISSION':'2026-10-01','CATEGORIE_BATIMENT':'COMM','TYPE_PERMIS_DESCR':'Commercial renovation','TYPE_BATIMENT':None},
              {'NO_PERMIS':'b','DATE_EMISSION':'2026-03-31','CATEGORIE_BATIMENT':'COMM','TYPE_PERMIS_DESCR':'Commercial renovation','TYPE_BATIMENT':None}]
        result=permits(rows,provider='laval_permit',now=NOW,verified_at=NOW.isoformat())
        self.assertEqual([r['source_record_id'] for r in result],['a'])
        self.assertEqual(result[0]['company_name'],None)

    def test_known_buyer_name_cannot_override_explicit_foreign_source_location(self):
        row={'ocid':'foreign','id':'20261003110000','date':'2026-10-03T07:00:00-04:00',
             'buyer':{'id':'b','name':'Ville de Mont-Royal.'},'parties':[{'id':'b','address':{'countryName':'France'}}],
             'tender':{'status':'active','title':'Installation de caméras'}}
        result=seao([row],now=NOW,verified_at=NOW.isoformat(),published_at=NOW.isoformat(),source_url='https://www.donneesquebec.ca/source')
        self.assertEqual(result[0]['geography_class'],'FOREIGN')

    def test_public_failure_no_retry_and_prior_date_preserved(self):
        reader=PublicReader(transport=httpx.MockTransport(lambda req:httpx.Response(429)),limit=5)
        prior={'seao':{'records':[],'observed_at':(NOW-timedelta(days=4)).isoformat(),'attempted_at':(NOW-timedelta(days=4)).isoformat()}}
        try:
            rows,cache,health=collect(reader,prior,now=NOW,permits_cache={})
            self.assertEqual(reader.calls,3);self.assertEqual(cache['seao']['observed_at'],prior['seao']['observed_at'])
            self.assertFalse(due(cache['seao'],NOW+timedelta(minutes=1),86400))
        finally:reader.close()

    def test_expansion_body_evidence_does_not_trust_wrong_embedded_metadata(self):
        raw=b'<script>wrong date</script><h1>TricorBraun Opens New Quebec Distribution Warehouse</h1><p>August 10, 2026 new warehouse facility in Laval, Quebec</p>'
        r=expansion(raw,now=NOW);self.assertEqual(r['geography_class'],'LAVAL')
        self.assertEqual(r['publish_date'],'2026-08-10T12:00:00-04:00')
        from workflow.automation.trigger_intelligence import service_fit
        fit=service_fit(r);self.assertEqual(fit['basis'],'PROJECT-TYPE INFERENCE');self.assertFalse(fit['scope_confirmed'])
        with self.assertRaises(ValueError):expansion(b'<script>August 10, 2026</script>',now=NOW)

    def test_dry_run_and_kill_switch_cannot_call_providers_or_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch('workflow.automation.trigger_runtime.ROOT',Path(tmp)),patch('workflow.automation.trigger_runtime.PublicReader') as reader:
                self.assertIn('DRY_RUN',observe(SimpleNamespace(dry_run=True),None,now=NOW)['state']);reader.assert_not_called()
                (Path(tmp)/'TRIGGERS_STOP').touch()
                self.assertEqual(observe(SimpleNamespace(dry_run=False),None,now=NOW)['state'],'DISABLED');reader.assert_not_called()


class TriggerReviewSecurityTests(unittest.TestCase):
    def test_auth_origin_body_version_and_local_only_feedback(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from workflow.operator_phase7_api import install_phase7_canary_routes
        class Verifier:
            def verify(self, token):
                if token!='human':raise ValueError('No human')
                return SimpleNamespace(actor='owner',subject='owner')
        row,_,_=fixture();candidate=decision(row);queue={'rows':[candidate]}
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'automation.db'
            with patch('workflow.automation.today.read_internal_attention',return_value=queue) as read:
                app=FastAPI();install_phase7_canary_routes(app,verifier=Verifier(),client=object(),store=SimpleNamespace(db_path=db),
                    account_id='1',from_address='fixture@example.test',allowed_origin='https://example.test',clock=lambda:NOW)
                client=TestClient(app);url='/v1/operator/acquisition/review/'+candidate['key']
                self.assertEqual(client.get(url).status_code,401);read.assert_not_called()
                headers={'Cf-Access-Jwt-Assertion':'human'}
                self.assertEqual(client.get(url,headers=headers).status_code,200)
                fields={'version':candidate['version'],'choice':'GOOD TRIGGER'}
                self.assertEqual(client.post(url,headers=headers,data=fields).status_code,403)
                allowed={**headers,'Origin':'https://example.test'}
                self.assertEqual(client.post(url,headers=allowed,data={**fields,'version':'stale'}).status_code,409)
                self.assertEqual(client.post(url,headers=allowed,content='x'*513).status_code,415)
                self.assertEqual(client.post(url,headers=allowed,data=fields).status_code,200)
                recorded=SalesFeedback(db.with_name('phase12-autonomy.db')).latest()
                self.assertEqual(recorded[candidate['key']]['choice'],'GOOD TRIGGER')

    def test_trigger_display_contract_satisfies_existing_owner_reader(self):
        r,a,c=fixture()
        with tempfile.TemporaryDirectory() as tmp:
            queue=build_queue(TriggerStore(Path(tmp)/'db'),[r],a,c,now=NOW,crm_at=NOW.isoformat(),feedback={},source_health=[])
            display=projection(queue)
            self.assertEqual(display['schema'],1);self.assertEqual(display['scope'],'live');self.assertTrue(display['read_only'])
            self.assertLess(len(json.dumps(display,indent=2).encode()),131072)

    def test_people_research_current_employer_role_and_cached_replay(self):
        from workflow.automation.apollo_observation import ApolloReader
        calls=[]
        def response(req):
            calls.append(req)
            return httpx.Response(200,json={'people':[{'id':'right','title':'Facilities Manager','organization':{'primary_domain':'company.test'}},
                                                      {'id':'past','title':'IT Director','organization':{'primary_domain':'past.test'}},
                                                      {'id':'wrong','title':'Sales Manager','organization':{'primary_domain':'company.test'}}]})
        row,_,_=fixture();queue={'rows':[decision(row)]}
        reader=ApolloReader(SimpleNamespace(api_key='fixture'),transport=httpx.MockTransport(response),limit=3)
        with patch('workflow.automation.apollo_observation.ApolloReader',return_value=reader):
            cache,count=research_roles(queue,{},SimpleNamespace(apollo=SimpleNamespace(api_key='fixture')),now=NOW)
        self.assertEqual(count,1);self.assertEqual([p['id'] for p in queue['rows'][0]['collision']['role_candidates']],['right'])
        self.assertEqual(cache['company.test']['unresolved_people'],2)
        with patch('workflow.automation.apollo_observation.ApolloReader') as transport:
            newqueue={'rows':[decision(row)]}
            _,count=research_roles(newqueue,cache,None,now=NOW+timedelta(days=1));transport.assert_not_called()
            self.assertEqual(count,0)
        self.assertEqual(calls[0].method,'POST');self.assertTrue(str(calls[0].url).endswith('/mixed_people/api_search'))

    def test_people_research_denies_mass_or_paid_enrichment(self):
        from workflow.automation.apollo_observation import ApolloReader
        reader=ApolloReader(SimpleNamespace(api_key='fixture'),transport=httpx.MockTransport(lambda req:httpx.Response(200,json={})))
        try:
            for kind,params in [('people_research',{'q_organization_domains_list':['a.test','b.test']}),
                                ('people_research',{'q_organization_domains_list':['a.test'],'per_page':100}),('enrich',{})]:
                with self.subTest(kind=kind,params=params):
                    with self.assertRaises(ValueError):reader.read(kind,**params)
            self.assertEqual(reader.calls,0)
        finally:reader.close()

class ReleasePreservationTests(unittest.TestCase):
    def test_release_repin_preserves_original_authority_and_never_enables_test(self):
        import importlib.util
        root=Path(__file__).resolve().parents[3]
        spec=importlib.util.spec_from_file_location('phase30_stage',root/'ops/phase30/stage_runtime.py')
        stage=importlib.util.module_from_spec(spec);spec.loader.exec_module(stage)
        def require(ok,reason):
            if not ok:raise ValueError(reason)
        helper=SimpleNamespace(require=require,INTERNAL_SCOPES={'i'},CUSTOMER_SCOPES={'c'},INTERNAL_SOURCES={'i.py'},CUSTOMER_SOURCES={'c.py'},trusted=lambda p:p.read_bytes(),digest=lambda b:__import__('hashlib').sha256(b).hexdigest())
        prior={'internal_policy':{'lifecycle':{'enabled':True,'real_scopes':['i'],'test_scopes':[],'source_hashes':{'i.py':'old'},'expires_at':'original-expiry'}},
               'customer_policy':{'external_enabled':True,'test_enabled':False,'real_scopes':['c'],'test_scopes':[],'source_hashes':{'c.py':'old'},'activated_at':'original-cutoff'},
               'internal_activation':{'release_sha':'old','activated_at':'original-cutoff','scopes':['i']}}
        before=deepcopy(prior)
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/('a'*40)/'source';files=source/'apps/workflow-api/workflow';files.mkdir(parents=True)
            (files/'i.py').write_text('internal');(files/'c.py').write_text('customer')
            internal,customer,activation=stage.preserved(prior,source,helper)
            self.assertEqual(prior,before)
            self.assertEqual(internal['lifecycle']['expires_at'],'original-expiry')
            self.assertEqual(customer['activated_at'],'original-cutoff')
            self.assertEqual(activation['release_sha'],'a'*40);self.assertEqual(activation['scopes'],['i'])
            self.assertFalse(customer['test_enabled'])
            with self.assertRaises(ValueError):stage.preserved({**prior,'customer_policy':{**prior['customer_policy'],'external_enabled':False}},source,helper)
