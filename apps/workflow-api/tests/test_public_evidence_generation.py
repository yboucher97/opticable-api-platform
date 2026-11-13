from datetime import timedelta
import json
from pathlib import Path
import tempfile
import unittest

from workflow.automation.defect_development import DiagnosticCodingEnvironment,develop_from_incident,git,validate_generated_change
from workflow.automation.operational_recovery import DevelopmentScope,RecoveryCoordinator,diagnose
from test_operational_recovery import grant,NOW,observed

ROOT=Path(__file__).resolve().parents[3]
BASE='b0b94f118a22e0dfcbee8d3f729f67d618cf99da'


class PublicGenerationTests(unittest.TestCase):
    def test_two_public_evidence_defect_classes_generate_a_verified_bounded_fix(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);grant(root);scope=DevelopmentScope(root);coordinator=RecoveryCoordinator(scope,now=NOW)
            source=root/'source';git(root,'clone','--no-hardlinks','--no-checkout',str(ROOT),str(source));git(source,'checkout','--detach',BASE)
            one={**observed('SOFTWARE_DEFECT','public-evidence-fixture'),
                'diagnostic':{'rule':'public_evidence_consistency','defects':['NON_SCALAR_STATUS_CRASH','CONFLICTING_ORIGIN_HEALTH_CLASSIFICATION']}}
            coordinator.repair(one,{},now=NOW)
            coordinator.repair({**one,'observed_at':(NOW+timedelta(minutes=1)).isoformat(),'evidence_sha256':'f'*64},{},now=NOW+timedelta(minutes=1))
            incident='incident:'+diagnose(one,NOW)['incident_key']
            def identity(repo,sha):
                return {'repository':repo,'sha':sha,'tree_sha':git(source,'rev-parse','HEAD^{tree}'),'authenticated_read':True,
                    'base_ref':'release/production-integration-v2-20261113','base_sha':BASE}
            result=develop_from_incident(coordinator,incident,source,source_sha=BASE,github_read=identity,now=NOW+timedelta(minutes=1))
            self.assertEqual(result['state'],'PREPARED',result)
            candidate=Path(result['candidate_checkout'])
            names=git(candidate,'diff','--name-only',BASE,'HEAD').splitlines()
            self.assertEqual(len(names),2)
            self.assertIn('apps/workflow-api/workflow/automation/readiness.py',names)
            self.assertTrue(any(n.startswith('apps/workflow-api/tests/test_verified_defect_') for n in names))
            for name in ['deploy/manual-guarded-release.py','apps/workflow-api/workflow/automation/defect_development.py','apps/workflow-api/workflow/automation/release_recovery.py','apps/workflow-api/workflow/automation/mutation_control.py']:
                self.assertEqual((source/name).read_bytes(),(candidate/name).read_bytes())

    def test_generated_classification_cannot_grant_policy_authority_or_edit_recovery(self):
        proposal=DiagnosticCodingEnvironment().propose({'diagnostic':{'rule':'public_evidence_consistency'}})
        original=(ROOT/'apps/workflow-api/workflow/automation/readiness.py').read_text()
        validate_generated_change(original,proposal)
        with self.assertRaises(ValueError):
            validate_generated_change(original,{**proposal,'path':'ops/phase14/readiness_refresh_entrypoint.py'})
        bad=proposal['replacement'].replace('automatic_policy_change_authorized=False','automatic_policy_change_authorized=True')
        with self.assertRaises(ValueError):validate_generated_change(original,{**proposal,'replacement':bad})
