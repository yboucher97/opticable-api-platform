"""Fail-closed exact-release registration and operator route fixtures."""
from datetime import datetime, timedelta, timezone
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from workflow.automation.engine import AutomationEngine
from workflow.automation.phase7_lead_create import LeadCreateLedger, dedupe_preflight, request_hash
from workflow.automation.crm_write_boundary import require_authority, verify_transport_authority
from workflow.automation.store import AutomationStore
from workflow.operator_access import AccessPrincipal
from workflow.operator_phase7_create_api import install_phase7_create_routes
from workflow.phase7_registration import MODE, _PINNED_SOURCES, maybe_install_phase7, validate_registration
from workflow.phase7_registration import verify_source_hashes


SHA="a"*40
NOW=datetime.now(timezone.utc).replace(microsecond=0)
FIELDS={"First_Name":"OptiBrain","Last_Name":"Phase 7 Canary",
        "Company":"Opticable Internal Canary","Email":"hckyan97@gmail.com",
        "Lead_Status":"Not Contacted","Email_Opt_Out":False}


def manifest():
    return {"mode":MODE,"candidate_sha":SHA,"api_version":"1.32.0",
            "allowed_origin":"https://approvals.opticable.ca",
            "team_domain":"https://opticable.cloudflareaccess.com",
            "access_audience":"fixture-audience-123", "allowed_subjects":["owner"],
            "allowed_emails":[],"mailbox_account_id":"12345",
            "from_address":"sales@opticable.ca", "create_approval_id":None,
            "create_request_hash":None,
            "crm_approval_id":None,"outbound_approval_id":None,
            "business_actions_enabled":False,
            "source_hashes":{path:"a"*64 for path in _PINNED_SOURCES}}


class FakeVerifier:
    def verify(self, token):
        if token!="signed-human-fixture": raise ValueError("not verified")
        return AccessPrincipal(subject="owner",email="owner@opticable.ca",actor="human:owner")


class FakeCrm:
    def __init__(self): self.calls=[];self.created=None;self.writes=0
    def request(self, service, method, path, **kwargs):
        self.calls.append((service,method,path))
        if service!="zohoapis": raise AssertionError("Unexpected provider")
        if method=="GET" and path.endswith("/search"):
            if self.created and "/Leads/" in path:
                return {"ok":True,"status":200,"data":{"data":[{"id":"1234567890","Email":FIELDS["Email"]}],
                        "info":{"more_records":False}}}
            return {"ok":True,"status":204,"data":""}
        if method=="GET" and path in {"/crm/v8/Leads","/crm/v8/Contacts"}:
            rows=([{"id":"1234567890","Email":FIELDS["Email"]}] if self.created and path.endswith("Leads")
                  else [{"id":"999","Email":"other@example.net"}])
            return {"ok":True,"status":200,"data":{"data":rows,"info":{"more_records":False}}}
        if method=="GET" and path=="/crm/v8/Leads/1234567890":
            return {"ok":True,"status":200,"data":{"data":[{"id":"1234567890",**self.created}]}}
        if method=="POST" and path=="/crm/v8/Leads":
            require_authority(self,service,method,path,kwargs["body"],None)
            verify_transport_authority(self,service,method,path,kwargs["body"],None)
            self.writes+=1;self.created=dict(kwargs["body"]["data"][0])
            return {"ok":True,"status":201,"data":{"data":[{"status":"success","details":{"id":"1234567890"}}]}}
        raise AssertionError("Unreviewed provider call")


class RegistrationTests(unittest.TestCase):
    def test_default_absence_registers_no_route_or_action(self):
        app=FastAPI()
        with patch.dict(os.environ,{},clear=True):
            result=maybe_install_phase7(app,client=None,store=None,engine=None,api_version="1.32.0")
        self.assertFalse(result["registered"])
        self.assertEqual(TestClient(app).post("/v1/operator/phase7/lead-create/review").status_code,404)

    def test_exact_release_manifest_is_required(self):
        env={"OPTIBRAIN_PHASE7_REGISTRATION":MODE,"OPTIBRAIN_PHASE7_RELEASE_SHA":SHA}
        self.assertEqual(validate_registration(manifest(),checkout_sha=SHA,env=env),
                         {"registered":True,"create":False,"crm":False,"outbound":False})
        for key,value in (("candidate_sha","b"*40),("api_version","1.10.0"),
                          ("mode","wrong")):
            changed={**manifest(),key:value}
            with self.assertRaises(ValueError): validate_registration(changed,checkout_sha=SHA,env=env)
        with self.assertRaises(ValueError):
            validate_registration(manifest(),checkout_sha="b"*40,env=env)
        with self.assertRaises(ValueError):
            validate_registration(manifest(),checkout_sha=SHA,env={**env,"OPTIBRAIN_PHASE7_RELEASE_SHA":"b"*40})

    def test_controls_only_registration_installs_routes_without_writer(self):
        tmp=tempfile.TemporaryDirectory(prefix="phase7-registration-gate-")
        self.addCleanup(tmp.cleanup)
        store=AutomationStore(Path(tmp.name)/"automation.db")
        engine=AutomationEngine(store,Path(tmp.name)/"workflows")
        fake=FakeCrm();app=FastAPI()
        env={"OPTIBRAIN_PHASE7_REGISTRATION":MODE,"OPTIBRAIN_PHASE7_RELEASE_SHA":SHA}
        with (patch.dict(os.environ,env),
              patch('workflow.phase7_registration._trusted_manifest',return_value=manifest()),
              patch('workflow.phase7_registration.verify_source_hashes')):
            result=maybe_install_phase7(app,client=fake,store=store,engine=engine,api_version="1.32.0")
        self.assertTrue(result["registered"])
        self.assertFalse(any(result[k] for k in ("create","crm","outbound")))
        self.assertNotIn("lifecycle.mail_send_approved_v2",engine.action_names())
        client=TestClient(app)
        self.assertEqual(client.post("/v1/operator/phase7/lead-create/review",
                                     json={"fields":FIELDS},
                                     headers={"Origin":"https://approvals.opticable.ca"}).status_code,401)
        self.assertFalse(fake.calls)

    def test_enabled_registration_matches_current_api_and_rejects_previous_version(self):
        # Production enables this fence; default-disabled startup alone cannot prove it.
        from workflow.api import API_VERSION
        env={"OPTIBRAIN_PHASE7_REGISTRATION":MODE,"OPTIBRAIN_PHASE7_RELEASE_SHA":SHA}
        self.assertEqual(manifest()["api_version"], API_VERSION)
        with (patch.dict(os.environ,env,clear=True),
              patch('workflow.phase7_registration._trusted_manifest') as read_manifest):
            with self.assertRaisesRegex(ValueError,"requires API 1.32.0"):
                maybe_install_phase7(FastAPI(),client=None,store=None,engine=None,api_version="1.20.0")
            read_manifest.assert_not_called()
        with self.assertRaises(ValueError):
            validate_registration({**manifest(),"api_version":"1.20.0"},checkout_sha=SHA,env=env)

    def test_business_action_requires_exact_pin(self):
        env={"OPTIBRAIN_PHASE7_REGISTRATION":MODE,"OPTIBRAIN_PHASE7_RELEASE_SHA":SHA}
        changed={**manifest(),"business_actions_enabled":True}
        with self.assertRaises(ValueError): validate_registration(changed,checkout_sha=SHA,env=env)
        changed["create_approval_id"]="f"*32
        changed["create_request_hash"]="a"*64
        self.assertEqual(validate_registration(changed,checkout_sha=SHA,env=env)["create"],True)
        changed["create_approval_id"]="*"
        with self.assertRaises(ValueError): validate_registration(changed,checkout_sha=SHA,env=env)

    def test_source_hashes_bind_readable_files_without_git_access(self):
        tmp=tempfile.TemporaryDirectory(prefix="phase7-source-pin-")
        self.addCleanup(tmp.cleanup)
        root=Path(tmp.name)
        hashes={}
        for relative in _PINNED_SOURCES:
            path=root/relative
            path.parent.mkdir(parents=True,exist_ok=True)
            data=(relative+'\n').encode()
            path.write_bytes(data);path.chmod(0o644)
            hashes[relative]=hashlib.sha256(data).hexdigest()
        verify_source_hashes(hashes,root=root)
        chosen=root/'workflow/api.py'
        chosen.write_text('changed\n')
        with self.assertRaisesRegex(ValueError,"differs"):
            verify_source_hashes(hashes,root=root)
        chosen.unlink();chosen.symlink_to(root/'workflow/operator_access.py')
        with self.assertRaises(OSError): verify_source_hashes(hashes,root=root)

    def test_human_review_issue_and_disabled_consume(self):
        tmp=tempfile.TemporaryDirectory(prefix="phase7-registration-")
        self.addCleanup(tmp.cleanup)
        store=AutomationStore(Path(tmp.name)/"automation.db")
        fake=FakeCrm();app=FastAPI()
        install_phase7_create_routes(app,verifier=FakeVerifier(),client=fake,store=store,
                                     allowed_origin="https://approvals.opticable.ca",clock=lambda:NOW)
        client=TestClient(app)
        headers={"Cf-Access-Jwt-Assertion":"signed-human-fixture","Origin":"https://approvals.opticable.ca"}
        path="/v1/operator/phase7/lead-create/review"
        self.assertEqual(client.post(path,json={"fields":FIELDS}).status_code,403)
        self.assertEqual(client.post(path,content="{}",headers=headers).status_code,415)
        review=client.post(path,json={"fields":FIELDS},headers=headers)
        self.assertEqual(review.status_code,200)
        self.assertEqual(review.json()["request_hash"],request_hash(FIELDS))
        issue=client.post("/v1/operator/phase7/lead-create/approvals",
                          json={"fields":FIELDS,"request_hash":request_hash(FIELDS)},headers=headers)
        self.assertEqual(issue.status_code,201)
        approval_id=issue.json()["approval_id"]
        self.assertEqual(LeadCreateLedger(store).inspect(approval_id)["state"],"issued")
        consume=client.post(f"/v1/operator/phase7/lead-create/approvals/{approval_id}/consume",
                            json={"fields":FIELDS},headers=headers)
        self.assertEqual(consume.status_code,409)
        self.assertEqual(consume.json()["reason"],"lead_create_not_registered")
        self.assertTrue(all(method=="GET" for _,method,_ in fake.calls))

    def test_exact_release_and_approval_pin_enable_only_one_fixture_create(self):
        tmp=tempfile.TemporaryDirectory(prefix="phase7-active-registration-")
        self.addCleanup(tmp.cleanup)
        store=AutomationStore(Path(tmp.name)/"automation.db")
        engine=AutomationEngine(store,Path(tmp.name)/"workflows")
        fake=FakeCrm()
        current=datetime.now(timezone.utc).replace(microsecond=0)
        proof=dedupe_preflight(fake,FIELDS,now=current)
        approval=LeadCreateLedger(store).issue(
            actor="human:owner",fields=FIELDS,dedupe=proof,
            expires_at=(current+timedelta(minutes=30)).isoformat(),
            now=current)
        reviewed={**manifest(),"business_actions_enabled":True,
                  "create_approval_id":approval.approval_id,"create_request_hash":request_hash(FIELDS)}
        env={"OPTIBRAIN_PHASE7_REGISTRATION":MODE,"OPTIBRAIN_PHASE7_RELEASE_SHA":SHA,
             "OPTIBRAIN_LEAD_CREATE_CANARY":"phase7-single-lead-create-v1",
             "OPTIBRAIN_LEAD_CREATE_APPROVAL_ID":approval.approval_id}
        app=FastAPI()
        with (patch.dict(os.environ,env),
              patch('workflow.phase7_registration._trusted_manifest',return_value=reviewed),
              patch('workflow.phase7_registration.verify_source_hashes'),
              patch('workflow.phase7_registration.AccessIdentityVerifier',return_value=FakeVerifier())):
            plan=maybe_install_phase7(app,client=fake,store=store,engine=engine,api_version="1.32.0")
            self.assertTrue(plan["create"])
            url=f"/v1/operator/phase7/lead-create/approvals/{approval.approval_id}/consume"
            headers={"Cf-Access-Jwt-Assertion":"signed-human-fixture",
                     "Origin":"https://approvals.opticable.ca"}
            first=TestClient(app).post(url,json={"fields":FIELDS},headers=headers)
            self.assertEqual(first.status_code,200,first.text)
            self.assertEqual(first.json()["provider_id"],"1234567890")
            self.assertEqual(TestClient(app).post(url,json={"fields":FIELDS},headers=headers).status_code,409)
        self.assertEqual(fake.writes,1)


if __name__=='__main__': unittest.main()
