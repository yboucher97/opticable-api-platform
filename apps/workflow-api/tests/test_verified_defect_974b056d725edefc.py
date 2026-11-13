import unittest,datetime as dt,importlib.util
from pathlib import Path
_spec=importlib.util.spec_from_file_location('v2_readiness',Path(__file__).resolve().parents[3]/'apps/workflow-api/workflow/automation/readiness.py')
_watch=importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_watch)
def classify_public(value,now):
 try:return _watch.public_verification_signal(value,now)
 except (TypeError,AttributeError,ValueError):return {'state':'CRASHED','classification':'CRASHED'}
class PublicEvidenceRegression(unittest.TestCase):
 def test_malformed_status_is_unknown(self):
  self.assertEqual(classify_public({'at':'2026-11-13T00:00:00Z','http_status':[]},dt.datetime(2026,11,13,tzinfo=dt.timezone.utc))['state'],'UNKNOWN')
 def test_nonobject_is_unknown(self):
  self.assertEqual(classify_public([],dt.datetime(2026,11,13,tzinfo=dt.timezone.utc))['state'],'UNKNOWN')
 def test_conflicting_origin_is_not_verified(self):
  self.assertEqual(classify_public({'at':'2026-11-13T00:00:00Z','http_status':200,'origin_healthy':False,'semantic_health_verified':True},dt.datetime(2026,11,13,tzinfo=dt.timezone.utc))['classification'],'ORIGIN_HEALTH_FAILURE')
 def test_denial_does_not_prove_origin_outage(self):
  self.assertFalse(classify_public({'at':'2026-11-13T00:00:00Z','http_status':403,'origin_healthy':True},dt.datetime(2026,11,13,tzinfo=dt.timezone.utc))['origin_outage_proven'])
 def test_good_public_health_retained(self):
  self.assertEqual(classify_public({'at':'2026-11-13T00:00:00Z','http_status':200,'origin_healthy':True,'semantic_health_verified':True},dt.datetime(2026,11,13,tzinfo=dt.timezone.utc))['state'],'OK')
 def test_security_authority_remains_false(self):
  self.assertFalse(classify_public({'at':'2026-11-13T00:00:00Z','http_status':403},dt.datetime(2026,11,13,tzinfo=dt.timezone.utc))['automatic_policy_change_authorized'])
