"""Fake-provider and real SQLite proof for the unregistered Lead create boundary."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from workflow.automation.crm_write_boundary import require_authority, verify_transport_authority
from workflow.automation.phase7_lead_create import (
    LeadCreateLedger, canonical_payload, dedupe_preflight, execute_approved_create,
    inspect_ambiguous_create, request_hash,
)
from workflow.automation.store import AutomationStore


FIELDS = {"First_Name": "OptiBrain", "Last_Name": "Phase 7 Canary",
          "Company": "Opticable Internal Canary", "Email": "hckyan97@gmail.com",
          "Lead_Status": "Not Contacted", "Email_Opt_Out": False}
NOW = datetime.now(timezone.utc).replace(microsecond=0)


class FakeZoho:
    def __init__(self):
        self.calls = []
        self.records = {}
        self.writes = 0
        self.lose_response = False
        self.malformed_ack = False
        self.before_transport = None
        self.more_records = False
        self.contacts = ()
        self.search_stale = False

    def request(self, service, method, path, **kwargs):
        self.calls.append((service, method, path))
        if service != "zohoapis":
            raise AssertionError("Unexpected provider")
        if method == "GET" and path.endswith("/search"):
            if self.search_stale:
                return {"ok": True, "status": 204, "data": ""}
            rows = ([{"id": key, "Email": value["Email"]} for key,value in self.records.items()]
                    if "/Leads/" in path else
                    [{"id": key, "Email": FIELDS["Email"]} for key in self.contacts])
            return {"ok": True, "status": 200, "data": {"data": rows,
                    "info": {"more_records": self.more_records}}}
        if method == "GET" and path in {"/crm/v8/Leads", "/crm/v8/Contacts"}:
            rows = ([{"id": key, "Email": value["Email"]} for key,value in self.records.items()]
                    if path.endswith("Leads") else
                    [{"id": key, "Email": FIELDS["Email"]} for key in self.contacts])
            return {"ok": True, "status": 200, "data": {"data": rows or [{"id":"999", "Email":"other@example.net"}],
                    "info": {"more_records": self.more_records}}}
        if method == "GET" and path.startswith("/crm/v8/Leads/"):
            identity = path.rsplit("/",1)[1]
            return {"ok": True, "status": 200,
                    "data": {"data": [{"id": identity, **self.records[identity]}]}}
        if method == "POST" and path == "/crm/v8/Leads":
            body=kwargs["body"]
            require_authority(self, service, method, path, body, None)
            if self.before_transport:
                self.before_transport()
            verify_transport_authority(self, service, method, path, body, None)
            self.writes += 1
            self.records["1234567890"] = dict(body["data"][0])
            if self.lose_response:
                raise TimeoutError("Accepted, response lost")
            if self.malformed_ack:
                return {"ok": True, "status": 201, "data": {"data": [{}]}}
            return {"ok": True, "status": 201,
                    "data": {"data": [{"status": "success", "details": {"id": "1234567890"}}]}}
        raise AssertionError("Unreviewed provider call")


class LeadCreateTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(prefix="phase7-create-")
        self.addCleanup(tmp.cleanup)
        self.store=AutomationStore(Path(tmp.name)/"automation.db")
        self.client=FakeZoho()
        self.ledger=LeadCreateLedger(self.store)
        self.proof=dedupe_preflight(self.client, FIELDS, now=NOW)
        self.approval=self.ledger.issue(actor="human:owner", fields=FIELDS, dedupe=self.proof,
            expires_at=(NOW+timedelta(minutes=30)).isoformat(), now=NOW)
        self.client.calls.clear()

    def run_create(self, fields=None):
        return execute_approved_create(self.client,self.store,self.approval.approval_id,
                                       fields or FIELDS, now=NOW)

    def enabled(self):
        return patch.dict(os.environ, {"OPTIBRAIN_LEAD_CREATE_CANARY":"phase7-single-lead-create-v1",
                                    "OPTIBRAIN_LEAD_CREATE_APPROVAL_ID":self.approval.approval_id})

    def test_disabled_has_no_provider_calls(self):
        with patch.dict(os.environ,{"OPTIBRAIN_LEAD_CREATE_CANARY":""}):
            with self.assertRaisesRegex(ValueError,"disabled"):
                self.run_create()
        self.assertEqual(self.client.calls,[])

    def test_exact_create_single_use_and_restart(self):
        with self.enabled():
            result=self.run_create()
            self.assertEqual(result["provider_id"],"1234567890")
            self.assertEqual(self.client.writes,1)
            with self.assertRaises(ValueError): self.run_create()
        restarted=LeadCreateLedger(AutomationStore(self.store.db_path))
        self.assertEqual(restarted.inspect(self.approval.approval_id)["state"],"consumed")
        self.assertEqual(self.client.writes,1)

    def test_changed_payload_rejected_before_provider(self):
        with self.enabled():
            with self.assertRaises(ValueError): self.run_create({**FIELDS,"Company":"Different"})
        self.assertEqual(self.client.writes,0)
        self.assertEqual(self.ledger.inspect(self.approval.approval_id)["state"],"issued")

    def test_extra_field_and_different_module_rejected(self):
        with self.assertRaises(ValueError): canonical_payload({**FIELDS,"Owner":"someone"})
        with self.enabled():
            with self.assertRaises(ValueError):
                require_authority(self.client,"zohoapis","POST","/crm/v8/Contacts",
                                  {"data":[FIELDS],"trigger":[]},None)
        self.assertEqual(self.client.writes,0)

    def test_existing_exact_lead_or_contact_blocks(self):
        with self.enabled():
            self.client.records["111"] = dict(FIELDS)
            with self.assertRaisesRegex(ValueError,"already exists"):
                self.run_create()
            self.client.records.clear();self.client.contacts=("222",)
            with self.assertRaisesRegex(ValueError,"already exists"):
                self.run_create()
        self.assertEqual(self.client.writes,0)

    def test_incomplete_search_fails_closed(self):
        self.client.more_records=True
        with self.enabled():
            with self.assertRaisesRegex(ValueError,"incomplete"):
                self.run_create()
        self.assertEqual(self.client.writes,0)

    def test_stale_search_204_does_not_hide_existing_inventory_record(self):
        self.client.search_stale=True
        self.client.records["111"]=dict(FIELDS)
        with self.enabled():
            with self.assertRaisesRegex(ValueError,"already exists"):
                self.run_create()
        self.assertEqual(self.client.writes,0)

    def test_response_loss_is_manual_and_never_retries(self):
        self.client.lose_response=True
        with self.enabled():
            with self.assertRaisesRegex(ValueError,"human reconciliation"):
                self.run_create()
            with self.assertRaises(ValueError): self.run_create()
        self.assertEqual(self.client.writes,1)
        self.assertEqual(self.ledger.inspect(self.approval.approval_id)["state"],"manual")
        evidence=inspect_ambiguous_create(self.client,self.store,self.approval.approval_id,FIELDS)
        self.assertEqual(evidence["conclusion"],"exact_record_observed_human_review_required")
        self.assertEqual(evidence["provider_id"],"1234567890")
        self.assertEqual(self.client.writes,1)

    def test_malformed_ack_is_manual(self):
        self.client.malformed_ack=True
        with self.enabled():
            with self.assertRaisesRegex(ValueError,"human reconciliation"):
                self.run_create()
        self.assertEqual(self.client.writes,1)
        self.assertEqual(self.ledger.inspect(self.approval.approval_id)["state"],"manual")

    def test_policy_revoked_before_transport_blocks_write(self):
        self.client.before_transport=lambda:os.environ.__setitem__("OPTIBRAIN_LEAD_CREATE_CANARY","")
        with self.enabled():
            with self.assertRaisesRegex(ValueError,"human reconciliation"):
                self.run_create()
        self.assertEqual(self.client.writes,0)
        self.assertEqual(self.ledger.inspect(self.approval.approval_id)["state"],"manual")

    def test_expired_and_duplicate_approval_refused(self):
        with self.assertRaises(ValueError):
            self.ledger.issue(actor="human:owner",fields=FIELDS,dedupe=self.proof,
                expires_at=(NOW+timedelta(hours=2)).isoformat(),now=NOW)
        with self.assertRaisesRegex(ValueError,"already approved"):
            self.ledger.issue(actor="human:owner",fields=FIELDS,dedupe=self.proof,
                expires_at=(NOW+timedelta(minutes=30)).isoformat(),now=NOW)

    def test_audit_contains_no_raw_personal_data(self):
        with self.store._connect() as conn:
            audit='\n'.join(row[0] for row in conn.execute(
                "SELECT metadata_json FROM automation_audit WHERE category='phase7_lead_create_approval_v1'"))
        self.assertNotIn(FIELDS["Email"],audit)
        self.assertNotIn(FIELDS["Last_Name"],audit)
        self.assertIn(request_hash(FIELDS),audit)


if __name__ == '__main__': unittest.main()
