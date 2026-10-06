"""Lifecycle regressions and real consumer projections, with no providers."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
from tempfile import TemporaryDirectory
import unittest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from types import SimpleNamespace
from unittest.mock import patch
from workflow.automation.lifecycle_truth import derive, context_key, eligible_today, priority_order
from workflow.automation.lifecycle_projection import fact, ref, collect_states, reconcile_priority, conversation_state
from workflow.automation.manager_store import ManagerStore
from workflow.automation.manager_runtime import sync_priorities
from workflow.automation.manager_intelligence import build_manager, render_manager
from workflow.automation.sales_conversations import build_bundle
from workflow.operator_manager_api import install_manager_routes
from workflow.automation.today import build_today

NOW = datetime(2026, 10, 6, 14, tzinfo=timezone.utc)
CONTEXT = ref('BOOKS', 'ESTIMATE', '123')


def event(kind, days=1, source='BOOKS', **extra):
    at = (NOW - timedelta(days=days)).isoformat()
    return fact(CONTEXT, kind, source, at, None, NOW.isoformat(), kind,
                proof='BOOKS_SYSTEM_EMAIL_HISTORY' if source == 'BOOKS' else 'EXACT_THREAD', **extra)


def complete(context=CONTEXT):
    return {kind: {'completeness': 'COMPLETE', 'through_at': NOW.isoformat(), 'context_key': context_key(context)} for kind in ('response','downstream')}


def due(days):
    return {'authoritative': True, 'context_key': context_key(CONTEXT),
            'due_at': (NOW + timedelta(days=days)).isoformat(),
            'assigned_at': (NOW - timedelta(hours=12)).isoformat()}


class LifecycleTests(unittest.TestCase):
    def state(self, facts, **kwargs):
        return derive(facts, context=CONTEXT, now=NOW, coverage=kwargs.pop('coverage', complete()), **kwargs)

    def test_required_transition_scenarios(self):
        drafted = event('QUOTE_DRAFTED', 3)
        sent = event('QUOTE_SENT', 2)
        cases = [
            ([drafted], {}, 'QUOTE_DRAFTED', 'FINISH_QUOTE', 'ACTIONABLE_NOW'),
            ([drafted, sent], {}, 'WAITING_CUSTOMER', 'NO_ACTION', 'WAITING'),
            ([sent, event('CUSTOMER_REPLIED', 1, 'MAIL', detail={'reply_kind': 'QUESTION'})], {}, 'CUSTOMER_REPLIED', 'PROCESS_REPLY', 'ACTIONABLE_NOW'),
            ([sent, event('REVISION_REQUESTED', 1, 'MAIL', detail={'intent_confidence': 'HIGH'})], {}, 'REVISION_REQUESTED', 'REVISE_QUOTE', 'ACTIONABLE_NOW'),
            ([sent, event('QUOTE_ACCEPTED')], {}, 'ACCEPTED_WORK', 'REVIEW_ACCEPTED_WORK', 'ACTIONABLE_NOW'),
            ([sent, event('INVOICED')], {}, 'INVOICED', 'NO_ACTION', 'NO_ACTION'),
            ([sent, event('CUSTOMER_REPLIED', 1.5, 'MAIL'), event('RESPONSE_SENT', 1, 'MAIL')], {}, 'WAITING_CUSTOMER', 'NO_ACTION', 'WAITING'),
            ([sent], {'coverage': {}, 'followup': due(-.25)}, 'SENT_RESPONSE_UNKNOWN', 'VERIFY_RESPONSE_STATUS', 'VERIFY_FIRST'),
            ([sent], {'followup': due(2)}, 'WAITING_CUSTOMER', 'NO_ACTION', 'WAITING'),
            ([sent], {'followup': due(-.25)}, 'FOLLOWUP_DUE', 'FOLLOW_UP', 'ACTIONABLE_NOW'),
            ([sent, event('QUOTE_DECLINED')], {}, 'QUOTE_DECLINED', 'NO_ACTION', 'NO_ACTION'),
            ([event('TENDER_OPEN', 1, 'PUBLIC', truth_class='PUBLIC_SOURCE_FACT', detail={'deadline': (NOW + timedelta(hours=20)).isoformat()})], {}, 'TENDER_OPEN', 'VERIFY_ELIGIBILITY_AND_SUBMISSION', 'VERIFY_FIRST'),
        ]
        for facts, kwargs, state, action, gate in cases:
            with self.subTest(state=state, action=action):
                result = self.state(facts, **kwargs)
                self.assertEqual((result['current_state'], result['next_action'], result['actionability']), (state, action, gate))

    def test_quote_preparation_then_sent_error_shape(self):
        fixture=json.loads((Path(__file__).parent/'fixtures/lifecycle/quote-prepared-then-sent.json').read_text())
        result=derive(fixture['events'],context=fixture['context'],now=datetime.fromisoformat(fixture['now']),coverage=fixture['coverage'])
        self.assertEqual({k:result[k] for k in fixture['expected']},fixture['expected'])

    def test_collection_time_never_reorders_old_event(self):
        draft = event('QUOTE_DRAFTED', 5); draft['observed_at'] = NOW.isoformat()
        sent = event('QUOTE_SENT', 4); sent['observed_at'] = (NOW - timedelta(days=3)).isoformat()
        self.assertEqual(self.state([sent, draft])['latest_authoritative_event']['event_id'], sent['event_id'])

    def test_same_event_source_version_and_evidence_freshness_are_separate(self):
        older=event('TENDER_OPEN',20,'PUBLIC',truth_class='PUBLIC_SOURCE_FACT',detail={'deadline':(NOW+timedelta(hours=8)).isoformat()})
        older['source_at']=(NOW-timedelta(days=5)).isoformat()
        newer={**older,'event_id':'newer-version','source_at':(NOW-timedelta(days=2)).isoformat(),
               'detail':{'deadline':(NOW+timedelta(hours=20)).isoformat()}}
        result=self.state([newer,older])
        self.assertEqual(result['latest_authoritative_event']['event_id'],'newer-version')
        self.assertEqual(result['last_event_at'],older['event_at'])
        base={'actionability':'VERIFY_FIRST','readiness':'CURRENT','confidence':'HIGH','reason_code':'TENDER_DEADLINE','due_at':newer['detail']['deadline']}
        rows=[{**base,'priority_id':'a','lifecycle':{'evidence_observed_at':(NOW-timedelta(days=1)).isoformat()}},
              {**base,'priority_id':'z','lifecycle':{'evidence_observed_at':NOW.isoformat()}}]
        self.assertEqual(sorted(rows,key=lambda r:priority_order(r,NOW))[0]['priority_id'],'z')

    def test_status_only_does_not_prove_send(self):
        result = self.state([event('QUOTE_SENT_RECORDED')])
        self.assertEqual(result['current_state'], 'SENT_RECORDED_DELIVERY_UNKNOWN')
        sent = event('QUOTE_SENT'); sent.pop('proof')
        self.assertEqual(self.state([sent])['current_state'], 'UNKNOWN')

    def test_no_time_does_not_inherit_observation_time(self):
        e = event('QUOTE_SENT'); e['event_at'] = None
        self.assertEqual(self.state([e])['current_state'], 'UNKNOWN')

    def test_conflicting_authoritative_terminal_events_require_verification(self):
        result=self.state([event('QUOTE_ACCEPTED'),event('QUOTE_DECLINED')])
        self.assertEqual(result['reason_code'],'CONFLICTING_AUTHORITATIVE_EVENTS')

    def test_revision_request_with_partial_response_history_requires_verification(self):
        result=self.state([event('REVISION_REQUESTED',1,'MAIL')],coverage={})
        self.assertEqual(result['next_action'],'VERIFY_RESPONSE_STATUS')

    def test_identity_uncertain_is_unknown(self):
        for confidence in ('FUZZY', 'LIKELY', None):
            with self.subTest(confidence=confidence):
                e = event('QUOTE_SENT'); e['identity_confidence'] = confidence
                self.assertEqual(self.state([e])['current_state'], 'UNKNOWN')

    def test_derived_priority_is_never_source_truth(self):
        for source in ('TASK', 'PRIORITY', 'PROPOSAL', 'CACHE'):
            with self.subTest(source=source):
                e = event('QUOTE_DRAFTED', 0, source); e['truth_class'] = 'DERIVED_DETERMINISTICALLY'
                self.assertEqual(self.state([event('QUOTE_SENT'), e])['next_action'], 'NO_ACTION')

    def test_fact_specific_source_authority(self):
        crm = event('QUOTE_SENT', .25, 'CRM')
        self.assertEqual(self.state([event('QUOTE_DRAFTED'), crm])['next_action'], 'FINISH_QUOTE')
        self.assertEqual(self.state([event('QUOTE_DRAFTED', 2, 'CRM'), event('QUOTE_SENT', 1, 'MAIL')])['next_action'], 'NO_ACTION')

    def test_progress_does_not_regress_to_later_stale_draft(self):
        for kind in ('QUOTE_SENT', 'INVOICED', 'PAID', 'WORK_COMPLETED'):
            with self.subTest(kind=kind):
                self.assertNotEqual(self.state([event(kind, 2), event('QUOTE_DRAFTED', 1)])['next_action'], 'FINISH_QUOTE')

    def test_explicit_revision_reopens_preparation(self):
        result = self.state([event('QUOTE_SENT', 3), event('REVISION_REQUESTED', 2, 'MAIL'), event('QUOTE_REVISED', 1)])
        self.assertEqual(result['current_state'], 'QUOTE_REVISED')

    def test_later_customer_reply_after_payment_still_requires_reply(self):
        result=self.state([event('PAID',2),event('CUSTOMER_REPLIED',1,'MAIL')])
        self.assertEqual(result['commercial_stage'],'PAID')
        self.assertEqual(result['next_action'],'PROCESS_REPLY')

    def test_post_delivery_reply_does_not_reopen_quote_followup(self):
        result=self.state([event('PAID',3),event('CUSTOMER_REPLIED',2,'MAIL'),event('RESPONSE_SENT',1,'MAIL')],followup=due(-.25))
        self.assertEqual(result['current_state'],'PAID');self.assertEqual(result['next_action'],'NO_ACTION')

    def test_exact_tender_trigger_enters_shared_deadline_gate(self):
        inputs={'trigger-intelligence':{'rows':[{'key':'trigger','source_record_id':'ocds-ec9k95-99','source_provider':'seao','status':'OPEN','publish_date':(NOW-timedelta(days=20)).isoformat(),'closing_date':(NOW+timedelta(hours=20)).isoformat()}]}}
        states=collect_states(inputs,NOW)
        row=reconcile_priority({'targets':[ref('OPTIBRAIN','TRIGGER','trigger')],'readiness':'CURRENT'},states)
        self.assertEqual(row['reason_code'],'TENDER_DEADLINE');self.assertTrue(eligible_today(row,NOW))

    def test_uncertain_revision_text_requires_review(self):
        result = self.state([event('QUOTE_SENT', 2), event('CUSTOMER_REPLIED', 1, 'MAIL', detail={'reply_kind': 'REVISION', 'intent_confidence': 'TENTATIVE'})])
        self.assertEqual(result['next_action'], 'PROCESS_REPLY')

    def test_partial_and_not_collected_never_prove_no_reply(self):
        for state in ('PARTIAL', 'NOT_COLLECTED', 'STALE', 'UNKNOWN'):
            with self.subTest(state=state):
                coverage = complete(); coverage['response']['completeness'] = state
                result = self.state([event('QUOTE_SENT', 2)], coverage=coverage, followup=due(-.25))
                self.assertEqual(result['next_action'], 'VERIFY_RESPONSE_STATUS')

    def test_wrong_thread_or_stale_completeness_is_unknown(self):
        for change in ({'context_key': 'OTHER'}, {'through_at': (NOW - timedelta(hours=1)).isoformat()}):
            with self.subTest(change=change):
                coverage = complete(); coverage['response'].update(change)
                self.assertEqual(self.state([event('QUOTE_SENT')], coverage=coverage)['response_status'], 'UNKNOWN')

    def test_followup_policy_requires_authority_and_send_anchor(self):
        for policy in ({}, {**due(-.25), 'authoritative': False}, {**due(-.25), 'assigned_at': (NOW - timedelta(days=4)).isoformat()}):
            with self.subTest(policy=policy):
                self.assertEqual(self.state([event('QUOTE_SENT')], followup=policy)['followup_due_state'], 'POLICY_UNKNOWN')

    def test_documented_cadence_uses_real_send_time(self):
        policy = {'authoritative': True, 'context_key': context_key(CONTEXT), 'rule_id': 'existing-quote-rule', 'delay_days': 3}
        self.assertEqual(self.state([event('QUOTE_SENT', 4)], followup=policy)['followup_due_state'], 'DUE')

    def test_owner_assertion_is_not_an_actual_send_clock(self):
        e = event('QUOTE_SENT', 1, 'OWNER', truth_class='OWNER_VERIFIED_FACT', time_basis='ASSERTION_AT')
        self.assertEqual(self.state([e], followup=due(-.25))['followup_due_state'], 'POLICY_UNKNOWN')

    def test_newer_provider_event_supersedes_owner(self):
        owner = event('QUOTE_SENT', 2, 'OWNER', truth_class='OWNER_VERIFIED_FACT')
        result = self.state([owner, event('CUSTOMER_REPLIED', 1, 'MAIL')])
        self.assertEqual(result['current_state'], 'CUSTOMER_REPLIED')

    def test_owner_sent_assertion_does_not_claim_older_reply_is_answered(self):
        owner=event('QUOTE_SENT',0,'OWNER',truth_class='OWNER_VERIFIED_FACT',time_basis='ASSERTION_AT')
        result=self.state([event('CUSTOMER_REPLIED',1,'MAIL'),owner])
        self.assertEqual(result['next_action'],'VERIFY_RESPONSE_STATUS')
        self.assertEqual(result['response_status'],'REPLY_OBSERVED_ORDER_UNKNOWN')
        self.assertIsNone(result['last_event_at'])

    def test_apollo_ownership_prevents_manual_followup(self):
        result = self.state([event('QUOTE_SENT', 2)], followup=due(-.25), owner='APOLLO_CLAUDE')
        self.assertEqual(result['next_action'], 'REVIEW_WITH_CONVERSATION_OWNER')

    def test_waiting_states_are_no_action(self):
        for kind in ('WAITING_PROVIDER', 'WAITING_NATURAL_EVENT', 'OWNER_DEFERRED'):
            with self.subTest(kind=kind):
                self.assertEqual(self.state([event(kind, 1, 'CRM')])['next_action'], 'NO_ACTION')

    def test_deadline_and_actionability_dominate_importance(self):
        rows = [dict(priority_id='high-value', urgency='HIGH', actionability='WAITING', readiness='CURRENT'),
                dict(priority_id='real-deadline', urgency='MEDIUM', actionability='VERIFY_FIRST', readiness='CURRENT', due_at=(NOW + timedelta(hours=20)).isoformat()),
                dict(priority_id='work', urgency='HIGH', actionability='ACTIONABLE_NOW', readiness='CURRENT')]
        ranked = sorted(rows, key=lambda r: priority_order(r, NOW))
        self.assertEqual(ranked[0]['priority_id'], 'real-deadline')
        self.assertEqual([r['priority_id'] for r in ranked if eligible_today(r, NOW)], ['real-deadline', 'work'])


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = ManagerStore(Path(self.tmp.name) / 'phase12-autonomy.db')

    def priority(self, target=CONTEXT):
        inputs = {'business': {'snapshot': {'observed_at': NOW.isoformat(), 'leads': [{'id': 'lead', 'Created_Time': NOW.isoformat()}]}}}
        sync_priorities(inputs, self.store, NOW)
        row = deepcopy(self.store.rows('optibrain.business_priority')[0]['record'])
        row.update(priority_id='a' * 64, domain='SALES_INTELLIGENCE', targets=[target], what='Finish old quote', next_action='Finish quote')
        self.store.record(row)
        return next(p for p in self.store.rows('optibrain.business_priority') if p['record']['priority_id']=='a'*64)

    def test_today_and_brief_suppress_stale_sales_action_after_send(self):
        self.priority()
        inputs = {'business_events': [event('QUOTE_DRAFTED', 3), event('QUOTE_SENT', 2)]}
        manager = build_manager(inputs, self.store, NOW)
        today = build_today({'rows': [{'id': '123', 'name': 'Old quote',
            'quote': 'READY FOR QUOTE', 'action': 'Finish quote'}]}, {}, {}, {},
            {'signals': []}, now=NOW, manager=manager)
        self.assertFalse(manager['today'])
        self.assertFalse(manager['brief']['top_priorities'])
        self.assertEqual(today['attention_count'], 0)

    def test_today_uses_the_same_actionable_queue_as_owner_brief(self):
        self.priority()
        inputs = {'business_events': [event('QUOTE_DRAFTED', 2)]}
        manager = build_manager(inputs, self.store, NOW)
        today = build_today({}, {}, {}, {}, {'signals': []}, now=NOW, manager=manager)
        rows = today['sections']['Approvals']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['next_action'], 'FINISH_QUOTE')
        self.assertEqual(rows[0]['context'], manager['brief']['top_priorities'][0]['what'])

    def test_multi_estimate_separation_and_exact_revision(self):
        a = {'estimate_id': '123', 'status': 'draft', 'last_modified_time': (NOW - timedelta(days=3)).isoformat(), 'customer_id': 'same'}
        b = {'estimate_id': '456', 'status': 'sent', 'last_modified_time': (NOW - timedelta(days=2)).isoformat(), 'customer_id': 'same'}
        inputs = {'business': {'snapshot': {'books_estimate_index': {'123': a, '456': b}}},'business_events':[event('QUOTE_DRAFTED',2.5)]}
        states = collect_states(inputs, NOW)
        self.assertEqual(states['BOOKS:ESTIMATE:123']['next_action'], 'FINISH_QUOTE')
        b['supersedes_estimate_id'] = '123'
        inputs['business_events'] += [{**event('QUOTE_SENT', 1), 'context': ref('BOOKS', 'ESTIMATE', '456')}]
        states = collect_states(inputs, NOW)
        self.assertEqual(states['BOOKS:ESTIMATE:123']['next_action'], 'NO_ACTION')

    def test_native_draft_status_does_not_prove_incomplete_scope(self):
        inputs={'business':{'snapshot':{'books_estimate_index':{'123':{'estimate_id':'123','status':'draft','last_modified_time':NOW.isoformat()}}}}}
        state=collect_states(inputs,NOW)['BOOKS:ESTIMATE:123']
        self.assertEqual(state['actionability'],'VERIFY_FIRST')
        self.assertEqual(state['reason_code'],'VERIFY_QUOTE_COMPLETENESS')

    def test_exact_invoice_relation_closes_quote_without_customer_fuzzy_join(self):
        inputs = {'business': {'snapshot': {'books_invoices': [{'invoice_id': 'i', 'estimate_id': '123', 'last_modified_time': NOW.isoformat()}]}}, 'business_events': [event('QUOTE_DRAFTED', 2)]}
        state=collect_states(inputs, NOW)['BOOKS:ESTIMATE:123']
        self.assertEqual(state['current_state'], 'INVOICED')
        self.assertEqual(state['latest_authoritative_event']['source_context'],ref('BOOKS','INVOICE','i'))
        self.assertEqual(state['latest_authoritative_event']['source_reference'],'i')

    def test_revision_followup_scope_uses_current_object_independent_of_listing_order(self):
        new=ref('BOOKS','ESTIMATE','456')
        inputs={'business':{'snapshot':{'books_estimate_index':{'456':{'estimate_id':'456','status':'sent','last_modified_time':(NOW-timedelta(days=1)).isoformat(),'supersedes_estimate_id':'123'},'123':{'estimate_id':'123','status':'draft','last_modified_time':(NOW-timedelta(days=4)).isoformat()}}}},
                'business_events':[{**event('QUOTE_SENT',1),'context':new}],
                'lifecycle_coverage':{context_key(new):complete(new)},
                'followup_policies':{context_key(new):{**due(-.25),'context_key':context_key(new)}}}
        states=collect_states(inputs,NOW)
        for key in (context_key(CONTEXT),context_key(new)):
            self.assertEqual(states[key]['next_action'],'FOLLOW_UP')

    def test_exact_invoice_existence_does_not_need_perfect_historical_time(self):
        inputs={'business':{'snapshot':{'books_invoices':[{'invoice_id':'i','estimate_id':'123','status':'draft'}]}},'business_events':[event('QUOTE_DRAFTED')]}
        state=collect_states(inputs,NOW)['BOOKS:ESTIMATE:123']
        self.assertEqual(state['current_state'],'INVOICE_CREATED')
        self.assertIsNone(state['last_event_at']);self.assertEqual(state['next_action'],'NO_ACTION')

    def test_owner_fact_invalidates_priority_without_deleting_history(self):
        item = self.priority(); count = len(self.store.rows('optibrain.business_priority'))
        result = self.store.correct_fact('PRIORITY', item['record']['priority_id'], item['payload_hash'], 'QUOTE_SENT', 'owner', NOW, reason_code='DERIVED_ACTION_PERSISTED')
        view = build_manager({}, self.store, NOW)
        row = next(p for p in view['priorities'] if p['priority_id'] == item['record']['priority_id'])
        self.assertEqual(row['status'], 'SUPERSEDED'); self.assertEqual(row['next_action'], 'NO_ACTION')
        self.assertFalse(view['today']); self.assertFalse(view['brief']['top_priorities'])
        self.assertEqual(len(self.store.rows('optibrain.business_priority')), count)
        self.assertEqual(self.store.business_facts()[0]['detail']['reason_code'], 'DERIVED_ACTION_PERSISTED')
        self.assertEqual(result['provider_writes'], 0)
        self.assertIn('SUPERSEDED', render_manager(view))

    def test_owner_correction_requires_current_reviewed_version(self):
        item = self.priority()
        with self.assertRaises(ValueError):
            self.store.correct_fact('PRIORITY', item['record']['priority_id'], 'b' * 64, 'QUOTE_SENT', 'owner', NOW)

    def test_legacy_priority_loads_with_unknown_state(self):
        self.priority(); view = build_manager({}, self.store, NOW)
        row = next(p for p in view['priorities'] if p['priority_id'] == 'a' * 64)
        self.assertEqual(row['actionability'], 'VERIFY_FIRST'); self.assertFalse(view['today'])

    def test_morning_brief_includes_state_and_current_reason(self):
        self.priority()
        view = build_manager({'business_events': [event('QUOTE_DRAFTED')]}, self.store, NOW)
        self.assertEqual(view['today'][0]['reason_code'], 'QUOTE_DRAFT_INCOMPLETE')
        self.assertEqual(view['brief']['top_priorities'][0]['current_state'], 'QUOTE_DRAFTED')
        self.assertTrue(view['brief']['top_priorities'][0]['latest_authoritative_event'])

    def test_sales_reply_target_resolves_exact_conversation_fact(self):
        context=ref('OUTREACH','CONVERSATION','c')
        reply=fact(context,'RESPONSE_SENT','MAIL',NOW.isoformat(),None,NOW.isoformat(),'message',proof='EXACT_THREAD')
        states=collect_states({'sales-conversations':{'conversations':[{'conversation_id':'c'}]},'business_events':[reply]},NOW)
        self.assertEqual(states['OUTREACH:SALES_REPLY:c']['next_action'],'NO_ACTION')

    def test_retained_source_fact_survives_a_later_old_draft_projection(self):
        self.store.record_business_fact(event('QUOTE_SENT',2),NOW)
        inputs={'business_events':[event('QUOTE_DRAFTED',3)]}
        states=collect_states(inputs,NOW,self.store,record_facts=True)
        self.assertEqual(states[context_key(CONTEXT)]['next_action'],'NO_ACTION')
        count=len(self.store.business_facts());inputs['business_events'][0]['observed_at']=(NOW+timedelta(hours=1)).isoformat()
        collect_states(inputs,NOW+timedelta(hours=1),self.store,record_facts=True)
        self.assertEqual(len(self.store.business_facts()),count)

    def test_website_optimization_remains_independent(self):
        row = reconcile_priority({'targets': [ref('WEBSITE', 'WEBSITE_PAGE', 'page')], 'what': 'Improve camera page'}, {context_key(CONTEXT): derive([event('QUOTE_SENT')], context=CONTEXT, now=NOW)})
        self.assertEqual(row['what'], 'Improve camera page'); self.assertEqual(row['actionability'], 'OPTIONAL')

    def test_sales_later_exact_response_removes_duplicate_draft(self):
        from test_phase34_sales import fixture, NOW as SALES_NOW
        apollo, mail, crm = fixture()
        first = build_bundle(apollo, mail, crm, [], now=SALES_NOW)['conversations'][0]
        context = ref('OUTREACH', 'CONVERSATION', first['conversation_id'])
        mail['rows'][0]['business_events'] = [fact(context, 'RESPONSE_SENT', 'MAIL', (SALES_NOW + timedelta(minutes=1)).isoformat(), None, None, 'response', proof='EXACT_THREAD')]
        bundle = build_bundle(apollo, mail, crm, [], now=SALES_NOW + timedelta(minutes=2))
        self.assertIsNone(bundle['conversations'][0]['draft']); self.assertFalse(bundle['proposals'])

    def test_authenticated_same_origin_correction_and_immediate_projection(self):
        item = self.priority(); app = FastAPI()
        def verify(token):
            if token != 'fixture': raise ValueError('Identity required')
            return SimpleNamespace(actor='owner')
        install_manager_routes(app, verifier=SimpleNamespace(verify=verify), db_path=self.store.path, origin='https://owner.invalid', clock=lambda: NOW)
        client = TestClient(app); body = {'kind': 'PRIORITY', 'target': item['record']['priority_id'], 'version': item['payload_hash'], 'event_type': 'QUOTE_SENT', 'reason_code': 'DERIVED_ACTION_PERSISTED'}
        headers = {'Cf-Access-Jwt-Assertion': 'fixture', 'Origin': 'https://owner.invalid'}
        self.assertEqual(client.post('/v1/operator/manager/correction', json=body).status_code, 401)
        self.assertEqual(client.post('/v1/operator/manager/correction', json=body, headers={**headers, 'Origin': 'https://foreign.invalid'}).status_code, 403)
        self.assertEqual(client.post('/v1/operator/manager/correction', json=body, headers=headers).status_code, 200)
        with patch('workflow.operator_manager_api.collect', return_value={}):
            view = client.get('/v1/operator/manager?format=json', headers=headers).json()
        self.assertEqual(next(p for p in view['priorities'] if p['priority_id'] == 'a' * 64)['status'], 'SUPERSEDED')
