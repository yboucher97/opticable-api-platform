import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('recovery_timeline',Path(__file__).resolve().parents[3]/'ops/phase14/recovery_timeline.py')
timeline=importlib.util.module_from_spec(spec);spec.loader.exec_module(timeline)


class TimelineTests(unittest.TestCase):
    def test_recorded_full_and_partial_timeline_never_claim_independent_proof(self):
        values={name:f'2026-10-02T00:{i:02}:00Z' for i,name in enumerate(timeline.MILESTONES)}
        value=timeline.measure(values)
        self.assertEqual(value['rto_seconds'],360);self.assertFalse(value['independently_proven'])
        partial=timeline.measure({'incident_start':values['incident_start'],'contained_boot':values['contained_boot']})
        self.assertIsNone(partial['rto_seconds']);self.assertEqual(partial['elapsed_seconds']['contained_boot'],180)
    def test_naive_reverse_unknown_and_missing_start_are_rejected(self):
        for values in ({'incident_start':'2026-10-02T00:00:00'},
                       {'incident_start':'2026-10-02T00:01:00Z','contained_boot':'2026-10-02T00:00:00Z'},
                       {'unsupported':'2026-10-02T00:00:00Z'}, {'contained_boot':'2026-10-02T00:00:00Z'}):
            with self.subTest(values=values),self.assertRaises(ValueError):timeline.measure(values)


if __name__=='__main__':unittest.main()
