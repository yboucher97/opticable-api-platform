from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import unittest
from workflow.automation import observation_runtime as runtime

NOW=datetime(2026,10,3,tzinfo=timezone.utc)


class ObservationRuntimeTests(unittest.TestCase):
    def setUp(self):
        for target,value in [('collect_business',{}),('project_source',{})]:
            patcher=patch.object(runtime,target,return_value=value);patcher.start();self.addCleanup(patcher.stop)
        for target in ('os.chown','os.chmod'):
            patcher=patch(target);patcher.start();self.addCleanup(patcher.stop)
    def engine(self, dry=True):return SimpleNamespace(client=object(),reads=6,dry_run=dry)
    def test_native_read_budget_preserves_existing_bound(self):
        e=self.engine()
        with patch.object(runtime.Path,'exists',return_value=False),patch.object(runtime,'NativeReader') as reader, \
             patch.object(runtime,'collect_recurring',return_value={}),patch.object(runtime,'build_recurring',return_value={}), \
             patch.object(runtime,'collect_marketing',return_value={}),patch.object(runtime,'build_marketing',return_value={'groups':[]}):
            reader.return_value.reads=140;runtime.observe(e,now=NOW)
            self.assertEqual(reader.call_args.kwargs['limit'],154);self.assertEqual(e.reads,146)
    def test_failed_marketing_preserves_recurring_does_not_publish_stale_marketing(self):
        e=self.engine(False)
        with patch.object(runtime.Path,'exists',return_value=False),patch.object(runtime,'NativeReader') as reader, \
             patch.object(runtime,'collect_recurring',return_value={}),patch.object(runtime,'build_recurring',return_value={'scope':'live'}), \
             patch.object(runtime,'collect_marketing',side_effect=ValueError('provider unavailable')), \
             patch('workflow.automation.real_internal.atomic') as atomic:
            reader.return_value.reads=140
            with self.assertRaises(ValueError):runtime.observe(e,now=NOW)
            paths=[c.args[0].name for c in atomic.call_args_list]
            self.assertEqual(paths,['business-observation.json','recurring.json'])
    def test_aggregate_display_excludes_customer_and_conversion_ids(self):
        e=self.engine(False)
        with patch.object(runtime.Path,'exists',return_value=False),patch.object(runtime,'NativeReader') as reader, \
             patch.object(runtime,'collect_recurring',return_value={}),patch.object(runtime,'build_recurring',return_value={'scope':'live'}), \
             patch.object(runtime,'collect_marketing',return_value={}),patch.object(runtime,'build_marketing',return_value={'groups':[],'outcomes':[{'record_id':'1'}],'customer_value':[{'account_id':'2'}]}), \
             patch('workflow.automation.real_internal.atomic') as atomic:
            reader.return_value.reads=140;runtime.observe(e,now=NOW)
            public=next(c.args[1] for c in atomic.call_args_list if c.args[0].name=='marketing.json')
            self.assertNotIn('customer_value',public);self.assertNotIn('outcomes',public)
