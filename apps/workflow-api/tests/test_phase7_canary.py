"""Synthetic-only Phase 7 canary planning; provider access is forbidden."""
from datetime import datetime, timezone
import json
import unittest
from unittest.mock import patch

from workflow.automation.event_schema import digest
from workflow.automation.phase7_canary import (
    IdentityEvidence, build_canary_plan, build_review_package, hydrate_unique_lead,
)


NOW = datetime(2026, 9, 29, 18, 30, tzinfo=timezone.utc)
VERSION = "2026-09-29T18:00:00+00:00"


def record(**overrides):
    value = {
        "id": "1234567890", "Modified_Time": VERSION, "Created_Time": VERSION,
        "Lead_Status": "Not Contacted", "Converted__s": False,
        "Email": "customer@example.net", "Email_Opt_Out": False,
        "Phone": "+1 514 555 0100", "Company": "Example Customer",
        "City": "Montreal", "Preferred_Language": "en",
        "Normalized_Email": "customer@example.net",
        "Normalized_Phone": "+15145550100",
    }
    value.update(overrides)
    return value


def evidence(*ids, version=VERSION):
    return IdentityEvidence(lead_id="1234567890", source_version=version,
                            matching_lead_ids=tuple(ids), query_hash="a" * 64)


class Phase7CanaryTests(unittest.TestCase):
    def test_exact_reprocessing_is_deterministic_and_provider_free(self):
        with patch("socket.socket", side_effect=AssertionError("network forbidden")):
            first = build_canary_plan(record(), evidence("1234567890"), now=NOW)
            second = build_canary_plan(record(), evidence("1234567890"), now=NOW)
        self.assertEqual(first, second)
        self.assertEqual(first.dedupe_status, "unique_lead_email_match")
        self.assertEqual(first.qualification_score, 50)
        self.assertEqual(first.next_action, "draft_reply")
        self.assertTrue(first.outbound_eligible)
        self.assertEqual(len(first.folder_paths), 6)
        self.assertTrue(all(path.startswith("leads/1234567890/OB-J-") for path in first.folder_paths))
        self.assertIsNone(first.crm_account_id)
        self.assertIsNone(first.crm_contact_id)
        self.assertIsNone(first.crm_deal_id)

    def test_stale_version_and_ambiguous_identity_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "exact Lead version"):
            build_canary_plan(record(), evidence("1234567890", version="2026-09-29T17:00:00+00:00"), now=NOW)
        for matches in [(), ("1234567890", "888"), ("888",), ("1234567890", "1234567890")]:
            with self.subTest(matches=matches), self.assertRaises(ValueError):
                build_canary_plan(record(), evidence(*matches), now=NOW)

    def test_converted_and_inactive_leads_are_refused(self):
        for change in ({"Converted__s": True}, {"Lead_Status": "Junk Lead"}):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "active, unconverted"):
                build_canary_plan(record(**change), evidence("1234567890"), now=NOW)

    def test_opt_out_blocks_outbound_and_ai_cannot_authorize(self):
        plan = build_canary_plan(record(Email_Opt_Out=True), evidence("1234567890"), now=NOW,
                                 ai_hint={"recommended_next_action": "draft_reply", "priority": "urgent"})
        self.assertFalse(plan.outbound_eligible)
        self.assertNotEqual(plan.next_action, "draft_reply")
        self.assertEqual(set(plan.crm_patch), {"Next_Followup_At"})

    def test_audit_contains_only_non_sensitive_ids_and_hashes(self):
        plan = build_canary_plan(record(Normalized_Email=""), evidence("1234567890"), now=NOW)
        self.assertEqual(plan.crm_patch["Normalized_Email"], "customer@example.net")
        self.assertEqual(set(plan.crm_patch), {"Normalized_Email", "Next_Followup_At"})
        evidence_text = json.dumps(plan.audit_evidence(), sort_keys=True)
        self.assertNotIn("customer@example.net", evidence_text)
        self.assertNotIn("Example Customer", evidence_text)
        self.assertNotIn("+15145550100", evidence_text)
        self.assertEqual(plan.crm_patch_hash, digest(plan.crm_patch))

    def test_provider_ids_are_never_invented_or_accepted_malformed(self):
        plan = build_canary_plan(record(Contact_Id="123", Account_Id="456", Deal_Id="789"),
                                 evidence("1234567890"), now=NOW)
        self.assertEqual((plan.crm_contact_id, plan.crm_account_id, plan.crm_deal_id), ("123", "456", "789"))
        with self.assertRaisesRegex(ValueError, "relationship ID"):
            build_canary_plan(record(Account_Id="../../etc"), evidence("1234567890"), now=NOW)

    def test_invalid_clock_identity_and_query_hash_refused(self):
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            build_canary_plan(record(), evidence("1234567890"), now=datetime(2026, 9, 29))
        with self.assertRaisesRegex(ValueError, "numeric Zoho Lead"):
            build_canary_plan(record(id="../customer"), evidence("1234567890"), now=NOW)
        bad = IdentityEvidence(lead_id="1234567890", source_version=VERSION,
                               matching_lead_ids=("1234567890",), query_hash="bad")
        with self.assertRaisesRegex(ValueError, "query hash"):
            build_canary_plan(record(), bad, now=NOW)

    def test_changed_record_version_changes_plan_identity(self):
        newer = "2026-09-29T19:00:00+00:00"
        old = build_canary_plan(record(), evidence("1234567890"), now=NOW)
        new = build_canary_plan(record(Modified_Time=newer), evidence("1234567890", version=newer),
                                now=datetime(2026, 9, 29, 19, 10, tzinfo=timezone.utc))
        self.assertNotEqual(old.plan_hash, new.plan_hash)
        self.assertEqual(old.project_ref, new.project_ref)

    def test_hydration_uses_get_only_and_exact_email_identity(self):
        class FakeClient:
            def __init__(self):
                self.calls = []

            def request(self, provider, method, path, **kwargs):
                self.calls.append((provider, method, path, kwargs))
                if path.endswith("/1234567890"):
                    return {"ok": True, "status": 200, "data": {"data": [record()]}}
                return {"ok": True, "status": 200,
                        "data": {"data": [{"id": "999", "Email": "other@example.net"},
                                           {"id": "1234567890", "Email": "CUSTOMER@example.net"}],
                                 "info": {"more_records": False}}}

        client = FakeClient()
        lead, proof = hydrate_unique_lead(client, "1234567890")
        plan = build_canary_plan(lead, proof, now=NOW)
        self.assertEqual(plan.lead_id, "1234567890")
        self.assertEqual([call[1] for call in client.calls], ["GET", "GET"])
        self.assertEqual(client.calls[1][3]["query"]["email"], "customer@example.net")

    def test_hydration_refuses_unindexed_duplicate_or_more_pages(self):
        class FakeClient:
            def __init__(self, hits, more=False):
                self.hits, self.more = hits, more

            def request(self, _provider, method, path, **_kwargs):
                if method != "GET":
                    raise AssertionError("provider write attempted")
                if path.endswith("/1234567890"):
                    return {"ok": True, "status": 200, "data": {"data": [record()]}}
                return {"ok": True, "status": 200,
                        "data": {"data": self.hits, "info": {"more_records": self.more}}}

        cases = [FakeClient([]),
                 FakeClient([{"id": "1234567890", "Email": "customer@example.net"},
                             {"id": "777", "Email": "customer@example.net"}]),
                 FakeClient([{"id": "1234567890", "Email": "customer@example.net"}], more=True)]
        for client in cases:
            with self.subTest(client=client.hits, more=client.more), self.assertRaises(ValueError):
                hydrate_unique_lead(client, "1234567890")

    def test_review_package_shows_exact_values_but_redacts_audit(self):
        lead = record(Normalized_Email="")
        plan = build_canary_plan(lead, evidence("1234567890"), now=NOW)
        package = build_review_package(plan, lead, account_id="12345",
                                       from_address="sales@opticable.ca")
        self.assertEqual(package.crm_before["Normalized_Email"], "")
        self.assertEqual(package.crm_after["Normalized_Email"], "customer@example.net")
        self.assertEqual(package.recipient, "customer@example.net")
        self.assertIn("Thank you", package.content)
        receipt = json.dumps(package.audit_evidence())
        self.assertNotIn("customer@example.net", receipt)
        self.assertNotIn("Thank you", receipt)
        self.assertNotIn("sales@opticable.ca", receipt)

    def test_review_package_refuses_drift_internal_recipient_and_opt_out(self):
        lead = record()
        plan = build_canary_plan(lead, evidence("1234567890"), now=NOW)
        for changed in (record(Email="other@example.net"), record(Email_Opt_Out=True)):
            with self.subTest(changed=changed["Email"]), self.assertRaises(ValueError):
                build_review_package(plan, changed, account_id="12345",
                                     from_address="sales@opticable.ca")
        internal_lead = record(Email="staff@opticable.ca")
        internal_plan = build_canary_plan(internal_lead, evidence("1234567890"), now=NOW)
        with self.assertRaisesRegex(ValueError, "external customer"):
            build_review_package(internal_plan, internal_lead, account_id="12345",
                                 from_address="sales@opticable.ca")
        with self.assertRaisesRegex(ValueError, "Owned sender"):
            build_review_package(plan, lead, account_id="12345",
                                 from_address="other@example.net")

    def test_ai_language_cannot_replace_explicit_human_language_review(self):
        lead = record(Preferred_Language=None)
        plan = build_canary_plan(lead, evidence("1234567890"), now=NOW,
                                 ai_hint={"language": "fr"})
        self.assertEqual(plan.language, "unknown")
        self.assertIn("preferred_language", plan.missing_information)
        self.assertFalse(plan.outbound_eligible)
        with self.assertRaisesRegex(ValueError, "not eligible"):
            build_review_package(plan, lead, account_id="12345",
                                 from_address="sales@opticable.ca")
        package = build_review_package(plan, lead, account_id="12345",
                                       from_address="sales@opticable.ca",
                                       reviewed_language="fr")
        self.assertEqual(package.reviewed_language, "fr")
        self.assertIn("Bonjour", package.content)
        with self.assertRaisesRegex(ValueError, "not eligible"):
            build_review_package(plan, lead, account_id="12345",
                                 from_address="sales@opticable.ca",
                                 reviewed_language="es")
