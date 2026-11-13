from datetime import timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import ast

from test_operational_recovery import NOW, grant, observed
from workflow.automation.operational_recovery import DevelopmentScope, RecoveryCoordinator, diagnose
from workflow.automation.defect_development import (
    develop_from_incident, DiagnosticCodingEnvironment, validate_generated_change, git, run_regression)

ROOT = Path(__file__).resolve().parents[3]


class GenerationTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
        self.root = Path(t.name);grant(self.root);self.scope = DevelopmentScope(self.root)
        self.c = RecoveryCoordinator(self.scope,now=NOW);self.source=self.root/'source';self.source.mkdir()
        git(self.source,'init','-q');git(self.source,'config','user.name','fixture');git(self.source,'config','user.email','fixture@localhost')
        for name in ['ops/connectivity_watch/check.py','ops/connectivity_watch/test_check.py']:
            p=self.source/name;p.parent.mkdir(parents=True,exist_ok=True);data=(ROOT/name).read_text()
            if name.endswith('/check.py'):
                # Fault injection stays reproducible after the generated fix is
                # integrated into the release candidate itself.
                node=next(n for n in ast.parse(data).body if isinstance(n,ast.FunctionDef) and n.name=='age_hours')
                lines=data.splitlines(keepends=True)
                bad='''def age_hours(value, now):
    try:
        return (now-dt.datetime.fromisoformat(value.replace("Z","+00:00"))).total_seconds()/3600
    except (ValueError,AttributeError,TypeError):
        return None
'''
                data=''.join(lines[:node.lineno-1])+bad+''.join(lines[node.end_lineno:])
            p.write_text(data)
        git(self.source,'add','.');git(self.source,'commit','-qm','Last known good with reproduced timestamp defect')
        self.sha=git(self.source,'rev-parse','HEAD')

    def incident(self,operation='timestamp-fixture',rule='future_timestamp',symptom='SOFTWARE_DEFECT'):
        one={**observed(symptom,operation),'diagnostic':{'rule':rule,'expected':'future age is UNKNOWN','actual':'negative duration'}}
        self.c.repair(one,{},now=NOW)
        self.c.repair({**one,'observed_at':(NOW+timedelta(minutes=1)).isoformat(),'evidence_sha256':'f'*64},{},now=NOW+timedelta(minutes=1))
        return 'incident:'+diagnose(one,NOW)['incident_key']

    def identity(self,repo,sha):
        return dict(repository=repo,sha=sha,tree_sha=git(self.source,'rev-parse','HEAD^{tree}'),
                    authenticated_read=True,base_ref='main',base_sha=sha)

    def develop(self,incident):
        return develop_from_incident(self.c,incident,self.source,source_sha=self.sha,
            github_read=self.identity,now=NOW+timedelta(minutes=2))

    def test_actual_generation_creates_source_tests_commit_and_draft_request(self):
        result=self.develop(self.incident());self.assertEqual(result['state'],'PREPARED',result)
        candidate=Path(result['candidate_checkout'])
        self.assertIn('instant > now',(candidate/'ops/connectivity_watch/check.py').read_text())
        self.assertNotIn('instant > now',(self.source/'ops/connectivity_watch/check.py').read_text())
        self.assertTrue(result['draft_pr_request']['draft']);self.assertEqual(result['usage']['cost_microusd'],0)
        self.assertEqual(self.develop(self.incident())['state'],'ALREADY_PREPARED')
        with self.c.audit.connect(readonly=True) as db:
            row=db.execute("SELECT evidence_json FROM action_evidence WHERE json_extract(evidence_json,'$.event')='GENERATED_REPAIR_VERIFIED'").fetchone()
        value=json.loads(row[0])['value'];self.assertEqual(value['tests']['network_isolation'],'Landlock+seccomp')
        self.assertEqual(value['retained_tests']['after']['tests'],14)

    def test_prior_validated_recipe_is_reused_with_fresh_paired_proof(self):
        first=self.develop(self.incident('first'));self.assertEqual(first['state'],'PREPARED',first)
        second=self.develop(self.incident('second'));self.assertEqual(second['state'],'PREPARED',second)
        self.assertTrue(second['reused_validated_repair']);self.assertEqual(second['usage']['tokens'],1)
        self.assertEqual(self.develop(self.incident('third'))['state'],'BUDGET_EXHAUSTED')

    def test_unknown_problem_rejected_and_failure_learning_retained(self):
        incident=self.incident(rule='unreviewed_rule')
        self.assertEqual(self.develop(incident)['state'],'REVIEW_REQUIRED')
        self.assertEqual(self.develop(incident)['state'],'REVIEW_REQUIRED')
        with self.c.audit.connect(readonly=True) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM action_evidence WHERE json_extract(evidence_json,'$.event')='GENERATED_REPAIR_REJECTED'").fetchone()[0],1)

    def test_connection_consent_failure_cannot_trigger_code_generation(self):
        with self.assertRaises(ValueError):self.develop(self.incident(symptom='AUTH_REJECTED'))

    def test_scope_and_static_guards_reject_protection_or_unrelated_changes(self):
        original=(self.source/'ops/connectivity_watch/check.py').read_text()
        p=DiagnosticCodingEnvironment().propose({'diagnostic':{'rule':'future_timestamp'}})
        for changed in [{**p,'path':'workflow/automation/mutation_control.py'},
                        {**p,'replacement':'def age_hours(value, now):\n import os\n return os.system(value)\n'},
                        {**p,'regression':'import os\nos.system("true")\n'}]:
            with self.assertRaises(ValueError):validate_generated_change(original,changed)


class SandboxTests(unittest.TestCase):
    def test_kernel_boundary_blocks_external_read_write_and_subprocess_network(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);tests=root/'apps/workflow-api/tests';tests.mkdir(parents=True)
            (tests/'test_boundary.py').write_text('''import unittest,pathlib,ctypes,errno,subprocess
class Boundary(unittest.TestCase):
 def test_secret_read(self):
  with self.assertRaises(PermissionError):pathlib.Path('/etc/passwd').read_text()
 def test_source_write(self):
  with self.assertRaises(PermissionError):pathlib.Path(__file__).write_text('tamper')
 def test_native_socket(self):
  lib=ctypes.CDLL(None,use_errno=True)
  self.assertEqual(lib.socket(2,1,0),-1);self.assertEqual(ctypes.get_errno(),errno.EPERM)
 def test_network_child(self):
  r=subprocess.run(['/usr/bin/python3','-I','-c','import socket;socket.socket()'],capture_output=True)
  self.assertNotEqual(r.returncode,0)
''')
            result=run_regression(root,'test_boundary.py',hardened=True)
            self.assertTrue(result['passed'],result);self.assertEqual(result['tests'],4)
