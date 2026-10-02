from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from workflow.automation.readiness import queue_depth_signal

ROOT=Path(__file__).resolve().parents[3]


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value


bootstrap=module('phase15_bootstrap','ops/phase15/bootstrap.py')
queue=module('phase15_queue','ops/phase15/queue_metrics.py')
runtime=module('phase15_runtime','ops/phase14/runtime_snapshot.py')
NOW=datetime(2026,10,2,tzinfo=timezone.utc)


class RebuildSafetyTests(unittest.TestCase):
    def test_check_never_creates_missing_structure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);before=list(root.iterdir());value=bootstrap.check(root)
            self.assertFalse(value['supported_os']);self.assertTrue(value['missing_commands'])
            self.assertEqual(value['writes_performed'],0);self.assertEqual(before,list(root.iterdir()))
    def test_prepare_refuses_existing_release_before_any_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'etc').mkdir();(root/'etc/os-release').write_text('ID=ubuntu\nVERSION_ID="24.04"\n')
            (root/'etc/optibrain-rebuild-target').touch();p=root/'var/lib/optibrain/releases/current.json';p.parent.mkdir(parents=True);p.write_text('{}')
            before=sorted(root.rglob('*'))
            with patch.object(bootstrap.os,'geteuid',return_value=0),patch.object(bootstrap.subprocess,'run') as command:
                with self.assertRaisesRegex(ValueError,'Existing production release'):bootstrap.prepare(root)
                command.assert_not_called()
            self.assertEqual(before,sorted(root.rglob('*')))
    def test_target_symlink_cannot_escape(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'etc').symlink_to('/etc')
            with self.assertRaisesRegex(ValueError,'Symlink'):bootstrap.target_path(root,'/etc/optibrain/mutation-control.json')
    def test_nonroot_prepare_refused(self):
        with patch.object(bootstrap.os,'geteuid',return_value=1234):
            with self.assertRaisesRegex(ValueError,'Root prepare'):bootstrap.prepare(Path('/'))
    def test_bounded_journal_is_not_application_log_warning(self):
        self.assertEqual(runtime.growth_state(0,0,25*1024**2,512*1024**2),'OK')
        self.assertEqual(runtime.growth_state(0,0,65*1024**2,0),'DEGRADED')
        self.assertEqual(runtime.growth_state(0,0,0,641*1024**2),'ACTION REQUIRED')
        self.assertEqual(runtime.growth_state(26*1024**3,0,0,0),'ACTION REQUIRED')


class QueueObservationTests(unittest.TestCase):
    def sample(self,active=0,dlq=0,oldest=0,age=0):
        values={n:dict(backlog_count=c,backlog_bytes=0,oldest_message_timestamp_ms=oldest if c else 0)
                for n,c in [(queue.NAMES[1],dlq),(queue.NAMES[0],active)]} # reversed order must not change policy
        with tempfile.TemporaryDirectory() as temporary:
            p=Path(temporary)/'sample.json';p.write_text(json.dumps(dict(schema=1,status='measured',queues=values,
                captured_at=(NOW-timedelta(seconds=age)).isoformat())))
            return queue_depth_signal(NOW,p)
    def test_fresh_empty_and_old_dead_letters_are_visible(self):
        self.assertEqual(self.sample()['state'],'OK')
        self.assertEqual(self.sample(dlq=129)['state'],'ACTION REQUIRED')
    def test_stalled_active_backlog_and_large_queue(self):
        self.assertEqual(self.sample(active=1,oldest=int((NOW-timedelta(minutes=31)).timestamp()*1000))['state'],'ACTION REQUIRED')
        self.assertEqual(self.sample(active=101)['state'],'DEGRADED')
    def test_stale_future_and_missing_metric_fail_unknown(self):
        self.assertEqual(self.sample(age=5401)['state'],'UNKNOWN')
        self.assertEqual(self.sample(age=-1)['state'],'UNKNOWN')
        self.assertEqual(self.sample(active=True)['state'],'UNKNOWN')
    def test_sampler_only_selects_two_known_queues_and_metrics(self):
        calls=[]
        def request(path):
            calls.append(path)
            if path.endswith('/metrics'):return {'result':dict(backlog_count=0,backlog_bytes=0,oldest_message_timestamp_ms=0)}
            return {'result':[dict(queue_name=n,queue_id=str(i+1)*32) for i,n in enumerate(queue.NAMES)]}
        value=queue.sample('a'*32,'fixture-not-a-secret',request)
        self.assertEqual(set(value),set(queue.NAMES));self.assertEqual(len(calls),3)
        self.assertTrue(all('/messages' not in p for p in calls))
    def test_missing_queue_or_malformed_count_cannot_be_green(self):
        with self.assertRaises(ValueError):queue.sample('a'*32,'fixture',lambda _: {'result':[]})
        def request(path):
            if path.endswith('/metrics'):return {'result':dict(backlog_count=-1,backlog_bytes=0,oldest_message_timestamp_ms=0)}
            return {'result':[dict(queue_name=n,queue_id=str(i+1)*32) for i,n in enumerate(queue.NAMES)]}
        with self.assertRaises(ValueError):queue.sample('a'*32,'fixture',request)


if __name__=='__main__':unittest.main()
