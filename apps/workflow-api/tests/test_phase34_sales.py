"""Sales intent, exact identity, shared previews and explicit execution denial."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone,timedelta
from pathlib import Path
from types import SimpleNamespace
import json,sqlite3,tempfile,unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from workflow.automation.sales_conversations import classify,plain,conversations,build_bundle,ConversationStore,render_proposal
from workflow.automation.optimization_store import OptimizationStore,validate
from workflow.automation.ads_runtime import persist,projection
from workflow.automation.sales_reply_reader import read_replies
from workflow.automation.outreach_graduation import seal,validate_candidate,execution_allowed
from workflow.automation.today import build_today
from workflow.automation.store import AutomationStore
from workflow.operator_phase7_api import install_phase7_canary_routes
from workflow.operator_access import AccessPrincipal

NOW=datetime(2026,10,5,23,tzinfo=timezone.utc)

def fixture(body='Pouvez-vous envoyer une soumission pour des caméras?'):
    c={'id':'native-contact','email':'person@example.invalid','name':'Fixture Person','title':'Facilities Manager','organization_name':'Fixture Business','email_status':'verified','contact_campaign_statuses':[{'status':'active'}]}
    m={'id':'sent','contact_id':c['id'],'status':'completed','replied':True,'completed_at':(NOW-timedelta(days=1)).isoformat(),'emailer_campaign_id':'sequence','subject':'Commercial camera installation','body_text':'Installation scope, no invented claim','from_email':'yboucher@opticable.ca','provider_message_id':'<original@example.invalid>'}
    a={'at':NOW.isoformat(),'contacts':[c],'messages':[m],'replies':[m],'accounts':[],'stages':[],'sequences':[{'id':'sequence','name':'Business cameras'}]}
    mail={'at':NOW.isoformat(),'origin':'MANUAL','rows':[{'contact':c,'sent':m,'replies':[{'message_id':'1234','received_at':NOW.isoformat(),'match':'EXACT_REFERENCES_AND_SENDER','body':body,'headers':{}}]}]}
    return a,mail,{'Leads':[],'Contacts':[],'Accounts':[],'Deals':[]}

def prospect(**changes):
    p={'prospect_id':'p','canonical_name':'Fixture Warehouse','company_confidence':'EXACT','domain':'example.invalid','last_enriched':NOW.isoformat(),
       'CRM_state':'NEW','Apollo_state':'NOT IN APOLLO','suppression_state':'UNKNOWN','enrichment_readiness':'PROSPECTING_READY',
       'service_categories_seen':['commercial Wi-Fi'],'current_trigger_count':0,'repeat_buyer_count':2,'why_opticable':'Facilities/network fit',
       'contacts':[{'name':'Fixture Operator','title':'Operations Manager','confidence':'SUPPORTED_CURRENT','source_url':'https://example.invalid/team','suppressed':False}]}
    return {**p,**changes}

class SalesIntentTests(unittest.TestCase):
    def test_a_price_request_hot_actual_draft(self):
        b=build_bundle(*fixture(),[],now=NOW);c=b['conversations'][0]
        self.assertEqual(c['reply_class'],'QUOTE_INTEREST');self.assertEqual(c['urgency'],'HOT')
        self.assertIn('soumission',c['draft']['body']);self.assertFalse(c['draft']['send_allowed'])

    def test_b_negative_no_followup(self):
        b=build_bundle(*fixture('Not interested. Do not contact us.'),[],now=NOW)
        self.assertEqual(b['conversations'][0]['next_best_action'],'SUPPRESS');self.assertFalse(b['proposals'])

    def test_c_referral_research_first(self):
        c=conversations(*fixture('Je mets notre responsable en copie; ce sera votre contact principal.'),now=NOW)[0]
        self.assertEqual(c['reply_class'],'REFERRAL');self.assertEqual(c['next_best_action'],'RESEARCH FIRST')

    def test_d_auto_reply_not_positive(self):
        self.assertEqual(classify('Happy to discuss after returning',{'auto-submitted':'auto-replied'})['reply_class'],'AUTO_REPLY')
        self.assertEqual(classify('Out of office. Please send a quote.')['urgency'],'NONE')

    def test_e_customer_reconciled_by_exact_email(self):
        a,m,crm=fixture();crm['Contacts']=[{'id':'contact','Email':'person@example.invalid','Account_Name':{'id':'account'}}];crm['Accounts']=[{'id':'account'}]
        c=conversations(a,m,crm,now=NOW)[0];self.assertIn('CUSTOMER',c['CRM_references']['state']);self.assertEqual(c['current_owner'],'APOLLO_CLAUDE')

    def test_f_open_deal_context(self):
        a,m,crm=fixture();crm['Contacts']=[{'id':'contact','Email':'person@example.invalid'}];crm['Deals']=[{'id':'deal','Stage':'Proposal','Contact_Name':{'id':'contact'}}]
        c=conversations(a,m,crm,now=NOW)[0];self.assertEqual(c['CRM_references']['Deals'],['deal']);self.assertEqual(c['CRM_references']['state'],'OPEN DEAL')

    def test_g_apollo_owned_prospect_no_competing_draft(self):
        b=build_bundle(*fixture(),[prospect(Apollo_state='ACTIVE SEQUENCE / RECENT CONTACT')],now=NOW)
        self.assertFalse(any(p['record']['proposal_type']=='OUTREACH_PROPOSAL' for p in b['proposals']))

    def test_h_suppressed_contact_no_outreach(self):
        b=build_bundle(*fixture(),[prospect(suppression_state='SUPPRESSED')],now=NOW)
        self.assertEqual(b['coverage']['suppressed'],1);self.assertFalse(any(p['record']['proposal_type']=='OUTREACH_PROPOSAL' for p in b['proposals']))

    def test_i_uncertain_employer_needs_verification(self):
        p=prospect();p['contacts'][0]['confidence']='LIKELY'
        b=build_bundle(*fixture(),[p],now=NOW);self.assertEqual(b['coverage_gaps']['UNCERTAIN_ROLE'],1)
        self.assertFalse(any(p['record']['proposal_type']=='OUTREACH_PROPOSAL' for p in b['proposals']))

    def test_j_trigger_and_two_roles_preserved_not_sent(self):
        p=prospect(current_trigger_count=1,why_now='Verified active project');p['contacts'].append({**p['contacts'][0],'name':'Second','title':'IT Manager'})
        b=build_bundle(*fixture(),[p],now=NOW);d=next(p['detail'] for p in b['proposals'] if p['record']['proposal_type']=='OUTREACH_PROPOSAL')
        self.assertEqual(d['why_now'],'Verified active project');self.assertEqual(len(d['roles']),2);self.assertFalse(d['draft']['send_allowed'])

    def test_k_no_trigger_is_legitimate_unsent_preview(self):
        b=build_bundle(*fixture(),[prospect()],now=NOW);d=next(p['detail'] for p in b['proposals'] if p['record']['proposal_type']=='OUTREACH_PROPOSAL')
        self.assertEqual(d['why_now'],'NO CURRENT TRIGGER');self.assertIn('Language confirmation',d['execution_blockers'])

    def test_l_high_bounce_sequence_actual_change_preview(self):
        a,m,c=fixture();seq={'at':NOW.isoformat(),'issues':[{'sequence_id':'sequence','kind':'BOUNCE','title':'Clean before reactivation','why':'13 / 46 bounces','proposed_copy':'Prepare identity/list cleanup, no reactivation'}]}
        b=build_bundle(a,m,c,[],now=NOW,sequence_evidence=seq)
        self.assertTrue(any(p['record']['proposal_type']=='SEQUENCE_CHANGE' for p in b['proposals']))

    def test_m_small_sample_never_winner(self):
        b=build_bundle(*fixture('A discussion could be useful?'),[],now=NOW)
        for p in b['proposals']:self.assertIn('INSUFFICIENT',p['record']['measurement_plan']['minimum_usable_sample'])

    def test_n_duplicate_person_one_logical_conversation(self):
        a,m,c=fixture();a['contacts'].append({**a['contacts'][0],'id':'second'});a['replies'].append({**a['replies'][0],'id':'sent2','contact_id':'second'})
        rows=conversations(a,m,c,now=NOW);self.assertEqual(len(rows),1);self.assertEqual(len(rows[0]['Apollo_references']['contact_ids']),2)

    def test_o_quote_context_no_invented_financial_lineage(self):
        c=conversations(*fixture(),now=NOW)[0];self.assertEqual(c['next_best_action'],'PREPARE QUOTE');self.assertIn('UNKNOWN',c['CRM_references']['finance_lineage'])

    def test_quoted_outbound_and_css_do_not_create_intent(self):
        for body in ['Not interested.\nFrom: seller@example.invalid\nPlease send a quote?', '<style>quotes are great</style>Bonjour\nDe : Sales\nUnsubscribe and quote request']:
            text=plain(body);self.assertNotIn('send a quote',text);self.assertNotIn('Unsubscribe',text)
        self.assertEqual(classify('Pas de besoin pour le moment. Merci, je vous recontacterai si cela change.')['reply_class'],'NOT_NOW')
        self.assertEqual(classify('Merci pour votre retour.<blockquote>Unsubscribe. Send a quote?</blockquote>')['reply_class'],'UNKNOWN')

    def test_missing_reply_not_positive_from_apollo_flag(self):
        a,m,c=fixture();m['rows']=[];a['replies'][0]['reply_class']='willing_to_meet'
        row=conversations(a,m,c,now=NOW)[0];self.assertEqual(row['reply_class'],'UNKNOWN');self.assertIsNone(row['draft'])

    def test_shared_records_validate_replay_and_concurrency(self):
        b=build_bundle(*fixture(),[prospect()],now=NOW)
        for p in b['proposals']+b['priorities']+b['assets']:validate(p['record'])
        with tempfile.TemporaryDirectory() as tmp:
            store=OptimizationStore(Path(tmp)/'existing.db');persist(b,store)
            with store.connect() as db:n=db.execute('SELECT count(*) FROM optimization_records').fetchone()[0]
            persist(build_bundle(*fixture(),[prospect()],now=NOW+timedelta(minutes=1)),store)
            with store.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM optimization_records').fetchone()[0],n)
            conv=ConversationStore(Path(tmp)/'existing.db');row=b['conversations'][0];conv.record(row)
            with ThreadPoolExecutor(max_workers=2) as pool:self.assertEqual(list(pool.map(lambda _:conv.record(row),range(2))),['EXACT_REPLAY']*2)

    def test_customer_expansion_review_without_invented_contact(self):
        b=build_bundle(*fixture(),[prospect(CRM_state='EXISTING CUSTOMER',contacts=[])],now=NOW)
        d=next(p['detail'] for p in b['proposals'] if p['record']['proposal_type']=='CUSTOMER_EXPANSION')
        self.assertIn('No supported current role',d['execution_blockers']);self.assertFalse(d['draft']['send_allowed'])

    def test_actual_referral_hook_uses_complete_shared_asset_contract(self):
        b=build_bundle(*fixture('Bonjour, je mets votre contact principal en copie.'),[],now=NOW)
        self.assertTrue(b['assets'])
        for asset in b['assets']:validate(asset['record'])

    def test_release_preserves_prior_authority_and_effects(self):
        import importlib.util
        import test_phase20_release_preservation as previous
        root=Path(__file__).resolve().parents[3]
        spec=importlib.util.spec_from_file_location('phase34_stage',root/'ops/phase34/stage_runtime.py');stage=importlib.util.module_from_spec(spec);spec.loader.exec_module(stage)
        t=previous.ReleasePreservationTests();prior=t.fixture();saved=deepcopy(prior)
        i,c,a=stage.preserved(prior,Path('/immutable/new/source'),t.helper())
        self.assertEqual(prior,saved)
        for x,y in ((i['lifecycle'],saved['internal_policy']['lifecycle']),(c,saved['customer_policy'])):
            for k in ('enabled','external_enabled','real_scopes','test_scopes','activated_at','expires_at'):
                if k in y:self.assertEqual(x[k],y[k])
        self.assertEqual(a['run'],saved['internal_activation']['run'])

    def test_execution_seal_and_authority_denial(self):
        s={'proposal':{'id':'exact','revision':1},'recipients':[{'native_person_id':'native','owner':'OPTIBRAIN_FUTURE','contact_confidence':'SUPPORTED_CURRENT','suppressed':False,'collision':'CLEAR','recent_contact':False,'manual_context_verified':True}],
           'message':'Exact message','channel':'APOLLO','limits':{'expires_at':(NOW+timedelta(hours=1)).isoformat(),'daily_cap':5,'kill_switch':False},'hash':'','approval_receipt':{}}
        s['hash']=seal(s['proposal'],s['recipients'],s['message'],s['channel'],s['limits']);s['approval_receipt']={'hash':s['hash'],'approved_by':'owner','approved_at':NOW.isoformat()}
        self.assertFalse(validate_candidate(s,now=NOW)['execution_authorized']);self.assertFalse(execution_allowed(s))
        altered=deepcopy(s);altered['message']='Changed'
        with self.assertRaisesRegex(ValueError,'Altered'):validate_candidate(altered,now=NOW)

    def test_today_top_three_no_research_dump(self):
        b=build_bundle(*fixture(),[],now=NOW)
        view=build_today({},{},{},{},{},now=NOW,sales_conversations={'scope':'live','read_only':True,'priorities':[p['record'] for p in b['priorities']],'observed_at':NOW.isoformat()})
        self.assertLessEqual(len(view['sections']['Approvals']),3)

    def test_failed_mail_lookup_cooldown_no_repeat(self):
        a,m,c=fixture();client=SimpleNamespace(request=lambda *a,**k:(_ for _ in ()).throw(ValueError('provider unavailable')))
        first=read_replies(client,a,{},now=NOW);self.assertEqual(first['provider_reads'],1)
        second=read_replies(client,a,first,now=NOW+timedelta(minutes=1));self.assertEqual(second['provider_reads'],0)

    def test_wrong_header_reference_never_reads_body(self):
        a,m,c=fixture();paths=[]
        def call(service,method,path,query=None):
            self.assertEqual(method,'GET');paths.append(path)
            if path.endswith('/search'):data=[{'messageId':'1234','folderId':'987','fromAddress':'person@example.invalid'}]
            elif path.endswith('/header'):data={'headerContent':{'from':['person@example.invalid'],'to':['yboucher@opticable.ca'],'references':['<different@example.invalid>']}}
            else:raise AssertionError('Unlinked body read')
            return {'ok':True,'status':200,'data':{'status':{'code':200},'data':data}}
        read=read_replies(SimpleNamespace(request=call),a,{},now=NOW)
        self.assertFalse(read['rows'][0]['replies']);self.assertEqual(len(paths),2)

    def test_exact_header_body_bind_and_provider_failure_are_distinct(self):
        a,m,c=fixture()
        def call(service,method,path,query=None):
            self.assertEqual(method,'GET')
            if path.endswith('/search'):data=[{'messageId':'1234','folderId':'987','fromAddress':'person@example.invalid','receivedTime':int(NOW.timestamp()*1000)}]
            elif path.endswith('/header'):data={'headerContent':{'from':['person@example.invalid'],'to':['yboucher@opticable.ca'],'references':['<original@example.invalid>']}}
            else:data={'content':'Please send a quote.'}
            return {'ok':True,'status':200,'data':{'status':{'code':200},'data':data}}
        read=read_replies(SimpleNamespace(request=call),a,{},now=NOW)
        self.assertEqual(read['rows'][0]['replies'][0]['match'],'EXACT_REFERENCES_AND_SENDER')
        self.assertEqual(read['provider_reads'],3);self.assertEqual(read['provider_writes'],0)

    def test_changed_message_evidence_is_retained_and_classification_held(self):
        a,m,c=fixture();m['rows'][0]['diagnostic']='MESSAGE_REPRESENTATION_CHANGED'
        row=conversations(a,m,c,now=NOW)[0];self.assertEqual(row['reply_class'],'UNKNOWN')

    def test_test_records_do_not_enter_business_conversations(self):
        a,m,c=fixture();a['contacts'][0]['OptiBrain_Test']=True
        self.assertFalse(conversations(a,m,c,now=NOW))

    def test_ambiguous_short_forward_is_not_a_response_draft(self):
        b=build_bundle(*fixture('Pour vous..\nGet Outlook for Android'),[],now=NOW)
        self.assertEqual(b['conversations'][0]['confidence'],'TENTATIVE');self.assertFalse(b['proposals']);self.assertFalse(b['assets'])

    def test_legal_step_not_a_signature_footer_question(self):
        b=build_bundle(*fixture('Voici le NDA à signer.\nFixture Person\nCEO\nVous appréciez nos services ?'),[],now=NOW)
        c=b['conversations'][0];self.assertEqual(c['reply_class'],'OTHER');self.assertEqual(c['urgency'],'HIGH')
        self.assertEqual(c['next_best_action'],'OWNER REVIEW');self.assertEqual(b['proposals'][0]['record']['authority_class'],'D')
        self.assertIn('No signature',c['draft']['review_notes'][0])

    def test_earlier_project_context_preserved_separately_from_current_nda(self):
        a,m,c=fixture('Voici le NDA à signer.');r=deepcopy(m['rows'][0]['replies'][0]);r.update(message_id='earlier',received_at=(NOW-timedelta(hours=2)).isoformat(),body='Visite site survey: installer un patch panel et un hot-spot.')
        m['rows'][0]['replies'].append(r);b=build_bundle(a,m,c,[],now=NOW)
        row=b['conversations'][0];self.assertTrue(row['project_context']);self.assertIn('commercial Wi-Fi',row['service_context'])
        self.assertEqual(row['reply_class'],'OTHER');self.assertTrue(b['assets'])
        for item in b['proposals']+b['priorities']+b['assets']:validate(item['record'])

    def test_ads_projection_does_not_include_sales_records(self):
        import test_phase33_ads
        from workflow.automation.ads_intelligence import build_bundle as ads_bundle
        with tempfile.TemporaryDirectory() as tmp:
            store=OptimizationStore(Path(tmp)/'existing.db');ads=ads_bundle(test_phase33_ads.fixture(),NOW)
            persist(ads,store);persist(build_bundle(*fixture(),[],now=NOW),store)
            view=projection(ads,store,collection_origin='MANUAL',preparation_origin='MANUAL',health={})
            self.assertEqual(view['proposal_count'],len(ads['proposals']));self.assertEqual(view['hook_count'],len(ads['assets']))

class SalesOperatorTests(unittest.TestCase):
    def test_private_authenticated_preview_no_send_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'automation.db';store=AutomationStore(db);opt=OptimizationStore(db.with_name('phase12-autonomy.db'))
            p=build_bundle(*fixture(),[],now=NOW)['proposals'][0];p['detail']['draft']['body']='<script>private</script>';opt.record(p['record'],p['detail'])
            verifier=SimpleNamespace(verify=lambda token:AccessPrincipal(subject='owner',email='fixture@example.invalid',actor='human:fixture') if token=='fixture' else (_ for _ in ()).throw(ValueError('no auth')))
            provider=SimpleNamespace(request=lambda *args,**kwargs:(_ for _ in ()).throw(AssertionError('No provider call')))
            app=FastAPI();install_phase7_canary_routes(app,verifier=verifier,client=provider,store=store,account_id='123',from_address='fixture@example.invalid',allowed_origin='https://owner.example',clock=lambda:NOW)
            cli=TestClient(app);url='/v1/operator/acquisition?proposal_id='+p['record']['proposal_id'];self.assertEqual(cli.get(url).status_code,401)
            r=cli.get(url,headers={'Cf-Access-Jwt-Assertion':'fixture'});self.assertEqual(r.status_code,200);self.assertIn('&lt;script&gt;',r.text);self.assertIn('no-store',r.headers['cache-control'])
            self.assertEqual(cli.post('/v1/operator/sales/send',headers={'Cf-Access-Jwt-Assertion':'fixture'}).status_code,404)

if __name__=='__main__':unittest.main()
