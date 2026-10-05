"""Patch staging preserves scope/expiry/claim authority exactly."""
import importlib.util
from pathlib import Path
import test_phase22_release_preservation as prior_tests
ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('forms_stage',ROOT/'ops/forms_polling_remediation/stage_runtime.py')
stage=importlib.util.module_from_spec(spec);spec.loader.exec_module(stage)

class FormsReleasePreservationTests(prior_tests.ReleasePreservationTests):
 def test_patch_preserves_authority_and_original_input(self):
  from copy import deepcopy
  prior=self.fixture();saved=deepcopy(prior)
  i,c,a=stage.preserved(prior,Path('/immutable/new-sha/source'),self.helper())
  self.assertEqual(prior,saved)
  for policy,original in ((i['lifecycle'],saved['internal_policy']['lifecycle']),(c,saved['customer_policy'])):
   for key in ('real_scopes','test_scopes','activated_at','expires_at'):self.assertEqual(policy[key],original[key])
  self.assertEqual(a['run'],saved['internal_activation']['run'])
  self.assertEqual(a['scopes'],saved['internal_activation']['scopes'])
