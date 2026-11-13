import unittest,datetime as dt,importlib.util
from pathlib import Path
_spec=importlib.util.spec_from_file_location('v2_target',Path(__file__).resolve().parents[3]/'ops/connectivity_watch/check.py')
_watch=importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_watch)
age_hours=_watch.age_hours
class TimestampRegression(unittest.TestCase):
 def test_future_is_unknown(self):
  self.assertIsNone(age_hours('2026-11-14T00:00:00+00:00',dt.datetime(2026,11,13,tzinfo=dt.timezone.utc)))
 def test_naive_is_unknown(self):
  self.assertIsNone(age_hours('2026-11-12T00:00:00',dt.datetime(2026,11,13,tzinfo=dt.timezone.utc)))
 def test_valid_age_retained(self):
  self.assertEqual(age_hours('2026-11-12T00:00:00+00:00',dt.datetime(2026,11,13,tzinfo=dt.timezone.utc)),24)
