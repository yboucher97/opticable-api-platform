"""Operational reconciliation never creates authority or hides uncertainty."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import io
from contextlib import redirect_stdout

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE));sys.path.insert(0,str(HERE.parents[1]/'apps/workflow-api'))
from business_work import execution_result
from business_sources import latest,performance_supplement
from workflow.automation.acquisition_store import AcquisitionStore
import engine
import runner

NOW=datetime(2026,11,14,23,tzinfo=timezone.utc)
PERIOD={'from':'2026-11-06','to':'2026-11-12'}


class ExecutionTests(unittest.TestCase):
    def test_full_pending_queue_skips_draft_construction(self):
        output=io.StringIO()
        with patch.object(runner,'load',return_value={'context':{'storage_budget':{'pending_slots':0}}}), \
             patch.object(engine,'make_artifacts',side_effect=AssertionError('Draft generation prohibited')),redirect_stdout(output):
            runner.child(HERE,Path('/nonexistent'),Path('/nonexistent'),NOW.isoformat())
        self.assertEqual(json.loads(output.getvalue()),[])

    def case(self,**fields):
        return {'key':'quote:123','native_id':'123','priority':100,'source_at':NOW.isoformat(),
            'reply_status':'UNKNOWN','next_action':'Review existing draft','status':'sent',
            'source_ids':['books:123'],'proposal_ids':['immutable-existing-proposal'],**fields}

    def test_empty_search_is_unknown_and_view_is_not_acceptance(self):
        case=self.case(mail_viewed=True,portal_viewed=False,search_matches=0,reply_status='NO_REPLY')
        got=execution_result({'cases':[case]}, {},NOW)['cases'][0]
        self.assertEqual(got['reply_status'],'UNKNOWN');self.assertFalse(got['acceptance_verified'])
        self.assertIn('Email viewed',got['view_evidence']);self.assertIn('False',got['view_evidence'])
        self.assertFalse(got['execution_enabled'])

    def test_contact_activity_cannot_accept_a_different_quote(self):
        got=execution_result({'cases':[self.case(project_linkage='UNVERIFIED',reply_status='RELATED_CONTACT_ACTIVITY_ONLY')]},{},NOW)['cases'][0]
        self.assertTrue(got['generic_reminder_suppressed']);self.assertFalse(got['acceptance_verified'])

    def test_source_age_not_import_or_render_clock_controls_action(self):
        case=self.case(source_at=(NOW-timedelta(hours=31)).isoformat(),imported_at=NOW.isoformat())
        got=execution_result({'cases':[case]}, {},NOW)['cases'][0]
        self.assertEqual(got['freshness'],'STALE_REVIEW_REQUIRED');self.assertIn('Refresh exact',got['next_action'])
        analysis={'freshness':'CURRENT','source_age_seconds':29*3600,'observed_at':(NOW-timedelta(hours=2)).isoformat()}
        self.assertEqual(execution_result({},analysis,NOW)['weekly']['freshness'],'STALE_REVIEW_REQUIRED')

    def test_native_identity_and_existing_proposal_are_preserved(self):
        case=self.case(preserved_inquiry_id='OB-I-LEGACY',captured_source='bing / organic')
        original=deepcopy(case);got=execution_result({'cases':[case]}, {},NOW)
        self.assertEqual(original,case);self.assertEqual(got['cases'][0]['proposal_ids'],case['proposal_ids'])
        self.assertEqual(got['cases'][0]['preserved_inquiry_id'],'OB-I-LEGACY')
        self.assertEqual([got[k] for k in ('new_artifacts','new_tasks','new_send_proposals','external_actions_completed')],[0]*4)
        with self.assertRaises(ValueError):execution_result({'cases':[self.case(native_id=1794236484734162600)]},{},NOW)
        with self.assertRaises(ValueError):execution_result({'cases':[case,case]},{},NOW)

    def test_bidder_deadline_not_later_internal_closing_controls_hold(self):
        case=self.case(deadline='2026-11-19T12:00:00-05:00',internal_closing='2026-11-25T10:30:00-05:00')
        got=execution_result({'cases':[case]}, {},NOW+timedelta(days=6))['cases'][0]
        self.assertTrue(got['deadline_passed']);self.assertIn('Deadline passed',got['next_action'])

    def test_attention_is_bounded_without_removing_context(self):
        cases=[self.case(key=str(i),native_id=str(i),priority=i) for i in range(8)]
        got=execution_result({'cases':cases}, {'ga4':{'key_events':5},'crm':{'leads':14}},NOW)
        self.assertEqual(len(got['cases']),8);self.assertEqual(len(got['top_attention']),5)
        self.assertEqual(got['top_attention'][0]['native_id'],'7')
        self.assertIsNone(got['weekly']['qualified_leads']);self.assertIsNone(got['weekly']['attributed_revenue'])

    def test_journal_reuse_does_not_write_files_or_accept_wrong_period(self):
        with tempfile.TemporaryDirectory() as directory:
            db=Path(directory)/'existing.db';store=AcquisitionStore(db)
            sid=store.snapshot('platform:business_v13:ga4:previous','https://analyticsdata.googleapis.com/',{'rows':[]},NOW,
                effective_from='2026-10-30',effective_to='2026-11-05')
            before={p:p.read_bytes() for p in Path(directory).iterdir()}
            got=performance_supplement(db,PERIOD,{})
            self.assertEqual(got['results'][0]['snapshot_id'],sid)
            self.assertEqual(performance_supplement(db,{'from':'2026-11-07','to':'2026-11-13'},{})['results'],[])
            self.assertEqual(latest(db,'absent'),{})
            self.assertEqual(before,{p:p.read_bytes() for p in Path(directory).iterdir()})

    def test_gsc_comparison_requires_seven_exact_nonduplicate_dates(self):
        native={'collection':{'period':PERIOD,'at':NOW.isoformat()},'snapshots':[]}
        rows=[{'keys':[(NOW.date()-timedelta(days=15-i)).isoformat()],'impressions':100,'clicks':2} for i in range(7)]
        source={'source':'platform:business_autopilot:gsc:previous','state':'WORKING',
            'period':{'from':'2026-10-30','to':'2026-11-05'},'data':{'rows':rows},'source_url':'https://www.googleapis.com/'}
        got=engine.analyse(native,{'results':[source]},NOW)
        self.assertEqual(got['gsc']['previous_clicks'],14);self.assertEqual(got['gsc']['previous_impressions'],700)
        source['data']['rows']=rows[:-1];self.assertIsNone(engine.analyse(native,{'results':[source]},NOW)['gsc']['previous_clicks'])
        source['data']['rows']=rows[:-1]+[rows[0]];self.assertIsNone(engine.analyse(native,{'results':[source]},NOW)['gsc']['previous_clicks'])


if __name__=='__main__':unittest.main()
