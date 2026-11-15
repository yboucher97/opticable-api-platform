from datetime import datetime,timedelta,timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE));sys.path.insert(0,str(HERE.parents[1]/'apps/workflow-api'))
from workflow.automation.acquisition_store import AcquisitionStore
from workflow.automation.action_evidence import ActionEvidence
from review import Review,package_key,source_date
import storage_accounting as accounting
import runner,storage

NOW=datetime(2026,11,14,22,tzinfo=timezone.utc)


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.assets=self.root/'artifacts';self.assets.mkdir();self.db=self.root/'existing.db';self.store=AcquisitionStore(self.db)
        with ActionEvidence(self.db).connect() as db:ActionEvidence.setup(db)
        self.review=Review(self.db,self.assets);self.i=0

    def add(self,path,at=NOW,text=None,**fields):
        self.i+=1;text=text or f'Finished original draft {self.i}';raw=text.encode();h=sha256(raw).hexdigest();f=self.assets/(str(self.i)+'.txt');f.write_bytes(raw)
        value={'logical_path':path,'path':f.name,'sha256':h,'scope':'live','status':'DRAFT_ONLY','source_evidence':[{'observed_at':at.isoformat()}],**fields}
        self.store.record('CONTENT_ASSET',value,source='platform:business_autopilot',native_id=h,url='https://opticable.ca/',now=at)
        return h

    def test_all_items_partition_once_and_default_is_ten(self):
        for i in range(91):self.add(f'business-work/response-draft/native-{i}/en/draft/reply.txt')
        q=self.review.queue(NOW)
        self.assertEqual(q['registered_items'],91);self.assertEqual(q['package_count'],91);self.assertEqual(len(q['default_packages']),10)
        ids=[a['id'] for p in q['packages'] for a in p['items']];self.assertEqual(len(ids),len(set(ids)))
        self.assertEqual(set(ids),set(q['ranked_item_ids']))
        self.assertEqual(sorted(a['queue']['rank'] for p in q['packages'] for a in p['items']),list(range(1,92)))
        html=self.review.render(now=NOW).decode();self.assertEqual(len(re.findall('data-package=',html)),10)
        html=self.review.render(now=NOW,view='items').decode();self.assertEqual(len(re.findall('data-artifact=',html)),91)

    def test_campaign_posts_article_image_and_languages_stay_together(self):
        paths=['campaigns/2026-W47/commercial-camera-ai/ip-cameras/en/social/draft/post.txt',
               'campaigns/intent-library/commercial-camera-ai/ip-cameras/fr/website/draft/article.txt',
               'campaigns/2026-W47/commercial-camera-ai/ip-cameras/en/social-media/draft/card.svg']
        hashes=[self.add(p) for p in paths];q=self.review.queue(NOW);self.assertEqual(q['package_count'],1)
        self.assertEqual(set(hashes),{a['id'] for a in q['packages'][0]['items']})
        self.assertTrue(all(a['execution_scope']['artifact_sha256']==a['sha256'] for a in q['packages'][0]['items']))

    def test_native_quote_and_inquiry_join_exact_identity_only(self):
        for kind in ('quote-review','quote-follow-up'):self.add(f'business-work/{kind}/exact-1/en/draft/a.txt')
        self.add('business-work/quote-follow-up/exact-2/en/draft/a.txt',text='Same customer name')
        self.assertEqual(self.review.queue(NOW)['package_count'],2)
        self.assertNotEqual(package_key({'logical_path':'business-work/response-draft/exact-1/en/a'}),package_key({'logical_path':'business-work/response-draft/exact-2/en/a'}))

    def test_priorities_include_sales_tracking_camera_and_ai_before_generic_material(self):
        paths=['business-work/overdue-task/t1/fr/draft/a.txt','business-work/quote-follow-up/q1/fr/draft/a.txt',
               'business-work/response-draft/m1/en/draft/a.txt','campaigns/service-intent/measurement/draft/tracking.json',
               'campaigns/week/x/ip-cameras/en/social/draft/a.txt','campaigns/week/x/ai-loss-prevention/en/social/draft/a.txt','planning/monthly.json']
        for p in reversed(paths):self.add(p)
        keys=[p['key'] for p in self.review.queue(NOW)['packages']]
        self.assertEqual(keys[:3],['task:t1','quote:q1','inquiry:m1']);self.assertEqual(keys[-1],'reference:analysis-planning')

    def test_stale_source_is_not_refreshed_by_registration(self):
        self.add('business-work/overdue-task/t1/fr/draft/a.txt',source_evidence=[{'observed_at':(NOW-timedelta(days=5)).isoformat()}])
        q=self.review.queue(NOW);self.assertEqual(q['packages'][0]['freshness'],'STALE')
        self.assertIn('STALE_SOURCE',q['packages'][0]['items'][0]['queue']['classifications'])
        self.assertIsNone(source_date({'registered_at':NOW.isoformat()}))

    def test_supersession_is_a_reversible_label_not_deletion_or_approval(self):
        h1=self.add('analytics/day/performance.json',at=NOW-timedelta(hours=1));h2=self.add('analytics/day/performance.json')
        before=sha256(self.db.read_bytes()).hexdigest();q=self.review.queue(NOW)
        labels={a['id']:a['queue'] for p in q['packages'] for a in p['items']}
        self.assertEqual(labels[h1]['superseded_by'],h2);self.assertTrue(labels[h1]['pending'])
        self.assertEqual(before,sha256(self.db.read_bytes()).hexdigest());self.assertEqual(len(list(self.assets.iterdir())),2)

    def test_similar_drafts_flagged_without_removing_originals(self):
        words=' '.join(f'word{i}' for i in range(100))
        self.add('campaigns/week/x/ip-cameras/en/social/draft/a.txt',text=words+' first')
        self.add('campaigns/week/x/ip-cameras/en/social/draft/b.txt',text=words+' second')
        q=self.review.queue(NOW);self.assertEqual(q['classification_counts']['POTENTIAL_DUPLICATE'],1)
        self.assertEqual(sum(p['member_count'] for p in q['packages']),2)

    def test_private_customer_text_never_merged_by_similarity(self):
        words=' '.join(f'word{i}' for i in range(100))
        for native in ('id1','id2'):self.add(f'business-work/response-draft/{native}/en/draft/a.txt',text=words+native,business_private=True)
        q=self.review.queue(NOW);self.assertNotIn('POTENTIAL_DUPLICATE',q['classification_counts']);self.assertEqual(q['package_count'],2)

    def test_review_scopes_and_existing_decisions_remain_exact(self):
        h=self.add('campaigns/week/x/ip-cameras/en/social/draft/a.txt');item=self.review.item(h)[0]
        with ActionEvidence(self.db).connect() as db:ActionEvidence.append(db,self.review.action_id(item),'business_review_decision',{'id':h,'choice':'REJECT','at':NOW.isoformat()},NOW)
        q=self.review.queue(NOW);self.assertEqual(q['packages'][0]['items'][0]['queue']['status'],'REJECT')
        self.assertFalse(q['packages'][0]['execution_enabled']);self.assertEqual(q['packages'][0]['items'][0]['execution_scope'],item['execution_scope'])

    def test_unknown_package_cannot_be_reviewed_and_client_package_approval_rejected(self):
        h=self.add('planning/a.txt')
        with self.assertRaises(ValueError):self.review.render(package_identifier='unknown',now=NOW)
        with self.assertRaises(ValueError):self.review.decision({'id':h,'package_id':'fake','version':h,'choice':'APPROVE','request_id':'a'*32},{'actor':'owner:opticable-review','expires_at':NOW+timedelta(hours=1)},NOW)

    def test_full_inventory_search_and_xss_escaping(self):
        self.add('planning/<unsafe>.txt',text='<script>alert(1)</script>')
        html=self.review.render(query='unsafe',now=NOW).decode();self.assertIn('&lt;script&gt;',html);self.assertNotIn('<script>alert(1)</script>',html)

    def test_sales_snapshot_never_invents_reply_or_execution(self):
        self.add('business-work/response-draft/native-1/en/draft/a.txt')
        (self.root/'latest-cycle.json').write_text(json.dumps({'at':NOW.isoformat(),'business_opportunities':[{'kind':'INQUIRY_SCOPE_REVIEW','native_id':'native-1','summary':'Known inquiry'}]}))
        q=self.review.queue(NOW);self.assertEqual(q['sales_opportunities'][0]['reply_status'],'UNKNOWN')
        self.assertEqual(q['files_written'],0);self.assertEqual(q['provider_calls'],0)

    def test_operational_view_rechecks_age_and_escapes_customer_text(self):
        self.add('planning/retained.txt')
        case={'key':'mail:exact','native_id':'exact','priority':100,'source_at':NOW.isoformat(),
            'title':'<script>customer</script>','status':'Invitation only','next_action':'Review existing context',
            'blocker':'Plans unknown','reply_status':'UNKNOWN'}
        (self.root/'latest-cycle.json').write_text(json.dumps({'at':NOW.isoformat(),
            'operational':{'cases':[case],'completed_internal':['Reconciled source IDs']}}))
        before=sha256(self.db.read_bytes()).hexdigest();html=self.review.render(now=NOW).decode()
        self.assertIn('&lt;script&gt;customer&lt;/script&gt;',html);self.assertNotIn('<script>customer',html)
        q=self.review.queue(NOW+timedelta(hours=31))
        self.assertEqual(q['operational']['cases'][0]['freshness'],'STALE_REVIEW_REQUIRED')
        self.assertEqual(q['registered_items'],1);self.assertEqual(before,sha256(self.db.read_bytes()).hexdigest())

    def test_empty_cycle_reuses_journal_without_new_receipt_files(self):
        self.add('planning/existing.txt');before=set(self.root.rglob('*'))
        self.assertFalse(runner.empty_cycle_cached(self.db,'same-evidence'))
        with ActionEvidence(self.db).connect() as db:
            aid,value=storage.reserve(db,'same-evidence',{'marketing_slots':0,'generation_bytes':8388608,'policy_sha256':storage.digest(storage.POLICY)},NOW)
            storage.complete(db,aid,value,[],NOW)
        runner.record_empty_cycle(self.db,'same-evidence',NOW,{'provider_calls':0})
        self.assertTrue(runner.empty_cycle_cached(self.db,'same-evidence'));self.assertEqual(before,set(self.root.rglob('*')))
        digest=sha256(self.db.read_bytes()).hexdigest();self.assertTrue(runner.empty_cycle_cached(self.db,'same-evidence'))
        self.assertEqual(digest,sha256(self.db.read_bytes()).hexdigest())


class AccountingTests(unittest.TestCase):
    def test_hardlinks_and_overlapping_aliases_count_once(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'source').mkdir();p=root/'source'/'data';p.write_bytes(b'x'*8192);os.link(p,root/'hardlink')
            (root/'alias').mkdir();(root/'alias'/'same').write_bytes(b'y'*4096)
            r=accounting.scan(root,aliases={str(root/'alias'):str(root/'source')})
            self.assertEqual(r['hardlink_aliases_excluded'],1)
            self.assertEqual(r['unique_allocated_bytes'],sum(v['allocated_bytes'] for v in r['categories'].values()))
            self.assertEqual(sum(v.get('logical_bytes',0) for v in r['categories'].values()),8192)

    def test_symlink_is_not_followed_and_directory_blocks_included(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'link').symlink_to('/var/backups/optibrain');r=accounting.scan(root,aliases={})
            self.assertEqual(r['symlinks_not_followed'],1);self.assertGreaterEqual(r['unique_allocated_bytes'],root.stat().st_blocks*512)

    def test_mount_alias_parser_uses_root_device_and_unescapes(self):
        raw='1 0 8:1 / / rw - ext4 /dev/sda1 rw\n2 1 8:1 /source /alias rw - ext4 /dev/sda1 rw\n3 1 0:1 / /proc rw - proc proc rw'
        self.assertEqual(accounting.mount_aliases(raw),{'/alias':'/source'})

    def test_bytecode_requires_retained_source_age_ownership_and_no_active_worktree(self):
        import py_compile,time
        with tempfile.TemporaryDirectory() as d,patch.object(accounting,'DEV',Path(d)):
            root=Path(d);work=root/'checkout';work.mkdir();source=work/'module.py';source.write_text('x=1\n')
            target=Path(py_compile.compile(str(source),doraise=True));at=time.time()-8*86400;os.utime(target,(at,at))
            source.chmod(0o600);target.chmod(0o600)
            c=accounting.cache_candidate(target,expected_uid=os.getuid());self.assertTrue(c['eligible']);self.assertFalse(c['covered_by_current_policy'])
            self.assertIsNone(accounting.cache_candidate(target,active_roots=[work],expected_uid=os.getuid()))
            source.unlink();self.assertIsNone(accounting.cache_candidate(target,expected_uid=os.getuid()))


if __name__=='__main__':unittest.main()
