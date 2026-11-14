from datetime import datetime, timezone, timedelta
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parent))
import engine
import runner
NOW = datetime(2026,11,14,1,0,tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parent


def fixtures():
    summary = {'at': NOW.isoformat(), 'period': {'from':'2026-11-05','to':'2026-11-11'}}
    def snap(name, data):
        return {'id':name, 'source':'platform:'+name, 'source_url':'https://opticable.ca/',
                'retrieved_at':NOW.isoformat(),'data':data}
    ga = {'dimensionHeaders':[{'name':'date'},{'name':'sessionSourceMedium'}],
          'metricHeaders':[{'name':'sessions'},{'name':'keyEvents'}],
          'rows':[{'dimensionValues':[{'value':'20261105'},{'value':'google / organic'}],
                   'metricValues':[{'value':'29'},{'value':'5'}]}]}
    native = {'collection':summary,'snapshots':[snap('ga4:530093120',ga),
        snap('gsc:daily', {'rows':[{'keys':['2026-11-05'],'clicks':6,'impressions':746,'position':3}]}),
        snap('gsc:query_page', {'rows':[{'keys':['cameras','https://opticable.ca/en/services/security-camera-systems/'],
                                      'clicks':0,'impressions':74,'position':77}]}),
        snap('crm_marketing',{'observed_at':NOW.isoformat(),'groups':[{'source':'UNATTRIBUTED','leads':13},{'source':'zoho_form','leads':1}]})]}
    old=copy.deepcopy(ga);old['rows'][0]['metricValues'][0]['value']='55'
    sup={'results':[{'source':'platform:business_autopilot:ga4:530093120:previous','state':'WORKING',
        'source_url':'https://analyticsdata.googleapis.com/', 'period':{'from':'2026-10-29','to':'2026-11-04'},'data':old}]}
    return native,sup


class BusinessAutopilotTests(unittest.TestCase):
    def test_equal_period_comparison_and_no_qualified_claim(self):
        n,s=fixtures();a=engine.analyse(n,s,NOW)
        self.assertEqual(a['ga4']['session_change_percent'],-47.27)
        self.assertEqual(a['ga4']['key_events'],5)
        self.assertIsNone(a['ads']['roas']);self.assertIsNone(a['ads']['cpql'])
        self.assertEqual(a['crm']['qualified_outcome_mapping'],'UNVERIFIED')
        self.assertIn('inventory',a['crm']['scope'])

    def test_missing_gsc_days_and_query_slices_are_not_totals(self):
        n,s=fixtures();a=engine.analyse(n,s,NOW)
        self.assertEqual(a['gsc']['returned_days'],1);self.assertEqual(a['gsc']['requested_days'],7)
        self.assertEqual(a['gsc']['clicks'],6);self.assertEqual(a['gsc']['query_page_clicks'],0)
        self.assertIsNone(a['cloudflare']['requests'])

    def test_wrong_period_is_not_compared(self):
        n,s=fixtures();s['results'][0]['period']['from']='2026-10-28'
        self.assertIsNone(engine.analyse(n,s,NOW)['ga4']['previous_sessions'])

    def test_stale_evidence_never_becomes_fresh(self):
        n,s=fixtures();a=engine.analyse(n,s,NOW+timedelta(days=3))
        self.assertEqual(a['freshness'],'STALE_REVIEW_REQUIRED')
        self.assertEqual(a['evidence'][0]['retrieved_at'],NOW.isoformat())
        with self.assertRaises(ValueError):engine.analyse(n,s,NOW-timedelta(days=1))

    def test_no_spending_publishing_or_live_mutation(self):
        for action in engine.FORBIDDEN | {'paid_model','image_generation','grant_approval','unknown'}:
            with self.subTest(action=action),self.assertRaises(PermissionError):engine.authorize(action)
        for cost in ('0.01','-1','NaN'):
            with self.assertRaises((PermissionError,ValueError)):engine.authorize('draft',incremental_cost=cost)
        with self.assertRaises(PermissionError):engine.authorize('draft',external_effect=True)
        self.assertTrue(engine.authorize('draft'))

    def test_preview_requires_all_verified_protections(self):
        p=dict.fromkeys(('authenticated','loopback_only','noindex','sitemap_excluded','analytics_disabled','customer_flows_disabled'),True)
        self.assertTrue(engine.authorize('private_preview',preview=p))
        for key in p:
            with self.subTest(key=key),self.assertRaises(PermissionError):engine.authorize('private_preview',preview={**p,key:False})

    def test_finished_bilingual_calendar_and_ad_limits(self):
        n,s=fixtures();bank=json.loads((ROOT/'content_bank.json').read_text())
        files=engine.make_artifacts(n,s,bank,NOW)
        calendar=json.loads(next(v for k,v in files.items() if k.endswith('/calendar.json')))
        self.assertEqual(len(calendar),14);self.assertEqual(len({p['date'] for p in calendar}),7)
        self.assertEqual(min(p['date'] for p in calendar),'2026-11-16')
        self.assertTrue(all(not p['published'] for p in calendar))
        for lang in ('fr','en'):
            for x in bank['ad_copy'][lang]['headlines']:self.assertLessEqual(len(x),30)
            for x in bank['ad_copy'][lang]['descriptions']:self.assertLessEqual(len(x),90)
        self.assertFalse(any(b'TODO' in v or b'TBD' in v for v in files.values()))

    def test_revision_idempotency_preserves_original_and_rejects_escape(self):
        with tempfile.TemporaryDirectory() as d:
            m1=engine.write_bundle(d,{'a/draft.txt':b'original'})
            self.assertEqual(m1,engine.write_bundle(d,{'a/draft.txt':b'original'}))
            m2=engine.write_bundle(d,{'a/draft.txt':b'revision'})
            self.assertNotEqual(m1,m2);self.assertEqual((Path(d)/m1[0]['path']).read_bytes(),b'original')
            with self.assertRaises(ValueError):engine.write_bundle(d,{'../bad':b'x'})
            with tempfile.TemporaryDirectory() as outside:
                (Path(d)/'link').symlink_to(outside,target_is_directory=True)
                with self.assertRaises(ValueError):engine.write_bundle(d,{'link/new/file':b'x'})
                self.assertEqual(list(Path(outside).iterdir()),[])

    def test_minimization_and_read_only_snapshot_extraction(self):
        with tempfile.TemporaryDirectory() as d:
            dbpath=Path(d)/'fixture.db'
            raw={'observed_at':NOW.isoformat(),'groups':[{'source':'UNATTRIBUTED','leads':13,'invoice_value':999,'email':'private@example.invalid'}]}
            blob=json.dumps(raw).encode()
            with sqlite3.connect(dbpath) as db:
                db.execute('CREATE TABLE acquisition_snapshots(id,source,source_url,retrieved_at,effective_from,effective_to,raw,raw_bytes)')
                db.execute('INSERT INTO acquisition_snapshots VALUES(?,?,?,?,?,?,?,?)',('a','platform:crm_marketing','https://opticable.ca/',NOW.isoformat(),None,None,zlib.compress(blob),len(blob)))
            before=hashlib.sha256(dbpath.read_bytes()).hexdigest()
            out=runner.collect_input(dbpath,{'snapshot_ids':['a']})
            self.assertNotIn('private@',json.dumps(out));self.assertNotIn('invoice_value',json.dumps(out))
            self.assertEqual(hashlib.sha256(dbpath.read_bytes()).hexdigest(),before)

    def test_real_sandbox_execution_blocks_network_and_outside_writes(self):
        sandbox=ROOT.parents[1]/'apps/workflow-api/workflow/automation/development_sandbox.py'
        if not sys.platform.startswith('linux'):
            self.skipTest('Linux security integration')
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as outside:
            scratch=Path(d);code=scratch/'probe.py'
            code.write_text('import socket\nfrom pathlib import Path\n'
                'try: socket.socket(); raise AssertionError("network escaped")\nexcept PermissionError: pass\n'
                f'try: Path({str(Path(outside)/"forbidden")!r}).write_text("x"); raise AssertionError("write escaped")\nexcept PermissionError: pass\n'
                'Path("safe").write_text("ok")\nprint("isolated")\n')
            spec=importlib.util.spec_from_file_location('sandbox',sandbox);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            result=subprocess.run(['/usr/bin/python3','-I','-B',str(code)],cwd=d,env={'PATH':'/usr/bin:/bin'},
                preexec_fn=lambda:module.restrict_child(ROOT,scratch),capture_output=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr.decode());self.assertEqual((scratch/'safe').read_text(),'ok')
            self.assertFalse((Path(outside)/'forbidden').exists())

    def test_real_execution_path_builds_then_deduplicates(self):
        n,s=fixtures()
        with tempfile.TemporaryDirectory() as d:
            p=Path(d); runtime=p/'runtime';runtime.mkdir();out=p/'output';out.mkdir()
            for name in ('engine.py','runner.py','content_bank.json'):(runtime/name).write_bytes((ROOT/name).read_bytes())
            (runtime/'sandbox.py').write_bytes((ROOT.parents[1]/'apps/workflow-api/workflow/automation/development_sandbox.py').read_bytes())
            request=out/'input.json';request.write_text(json.dumps({'native':n,'supplement':s}))
            first=runner.run_child(runtime,out,request,NOW);second=runner.run_child(runtime,out,request,NOW)
            self.assertEqual(first,second);self.assertEqual(len(first),37)
            self.assertTrue(any(x['logical_path'].endswith('seven-day-bilingual-calendar.txt') for x in first))


if __name__=='__main__':unittest.main()
