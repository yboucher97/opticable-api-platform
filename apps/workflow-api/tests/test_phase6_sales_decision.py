from datetime import datetime, timezone
import unittest

from workflow.automation.sales_decision import (
    POLICY_VERSION,
    build_sales_decision,
    business_due,
    validate_sales_decision,
)
from workflow.automation.providers.crm_leads import phase6_lead_patch


class Phase6SalesDecisionTests(unittest.TestCase):
    def lead(self, **changes):
        value = {
            "id": "5062683000007400001",
            "Modified_Time": "2026-09-25T14:00:00-04:00",
            "Created_Time": "2026-09-25T13:00:00-04:00",
            "Lead_Status": "Not Contacted",
            "Converted__s": False,
            "Email": "customer@example.com",
            "Phone": "514-555-0101",
            "Mobile": None,
            "Email_Opt_Out": False,
            "Service_Types": "Structured Cabling",
            "Next_Followup_At": None,
            "City": "Montreal",
            "State": "Quebec",
        }
        value.update(changes)
        return value

    def test_converted_lead_never_schedules_or_contacts(self):
        decision = build_sales_decision(
            self.lead(Converted__s=True),
            now=datetime(2026, 9, 28, 14, tzinfo=timezone.utc),
            ai_hint={
                "priority": "urgent",
                "recommended_next_action": "draft_reply",
            },
        )
        self.assertFalse(decision.active)
        self.assertTrue(decision.converted)
        self.assertFalse(decision.contactable)
        self.assertFalse(decision.email_contactable)
        self.assertEqual(decision.priority, "low")
        self.assertEqual(decision.next_action, "wait")
        self.assertIsNone(decision.followup_at)

    def test_email_opt_out_blocks_draft_but_phone_can_drive_call(self):
        decision = build_sales_decision(
            self.lead(Email_Opt_Out=True),
            now=datetime(2026, 9, 28, 14, tzinfo=timezone.utc),
            ai_hint={"recommended_next_action": "draft_reply"},
        )
        self.assertFalse(decision.email_contactable)
        self.assertTrue(decision.contactable)
        self.assertEqual(decision.next_action, "call")

    def test_ai_cannot_invent_unsafe_action_or_language(self):
        decision = build_sales_decision(
            self.lead(Phone=None),
            now=datetime(2026, 9, 28, 14, tzinfo=timezone.utc),
            ai_hint={
                "language": "de",
                "priority": "super-critical",
                "recommended_next_action": "send_email_now",
            },
        )
        self.assertEqual(decision.language, "unknown")
        self.assertEqual(decision.priority, "high")
        self.assertEqual(decision.next_action, "draft_reply")

    def test_stale_prequalified_lead_is_high_and_quote_review(self):
        decision = build_sales_decision(
            self.lead(Lead_Status="Pre-Qualified"),
            now=datetime(2026, 9, 28, 14, tzinfo=timezone.utc),
        )
        self.assertEqual(decision.priority, "high")
        self.assertEqual(decision.next_action, "quote_review")
        self.assertEqual(decision.policy_version, POLICY_VERSION)
        self.assertTrue(decision.followup_at.endswith("+00:00"))

    def test_contact_in_future_preserves_explicit_future_timestamp(self):
        decision = build_sales_decision(
            self.lead(
                Lead_Status="Contact in Future",
                Next_Followup_At="2026-10-05T09:30:00-04:00",
            ),
            now=datetime(2026, 9, 28, 14, tzinfo=timezone.utc),
            ai_hint={
                "priority": "urgent",
                "recommended_next_action": "call",
            },
        )
        self.assertEqual(decision.next_action, "wait")
        self.assertEqual(
            decision.followup_at,
            "2026-10-05T13:30:00+00:00",
        )

    def test_future_followup_is_stable_for_active_non_wait_lead(self):
        decision = build_sales_decision(
            self.lead(
                Lead_Status="Not Contacted",
                Next_Followup_At="2026-10-05T09:30:00-04:00",
            ),
            now=datetime(2026, 9, 28, 14, tzinfo=timezone.utc),
        )
        self.assertEqual(decision.next_action, "draft_reply")
        self.assertEqual(decision.followup_at, "2026-10-05T13:30:00+00:00")

    def test_overdue_followup_remains_visible_without_rewriting_crm_deadline(self):
        record = self.lead(
            Lead_Status="Contact in Future",
            Next_Followup_At="2026-09-25T17:00:00-04:00",
            Normalized_Email="customer@example.com",
            Normalized_Phone="5145550101",
        )
        decision = build_sales_decision(
            record,
            now=datetime(2026, 9, 29, 21, 0, tzinfo=timezone.utc),
            ai_hint={"recommended_next_action": "wait"},
        )
        self.assertEqual(decision.followup_at, "2026-09-25T21:00:00+00:00")
        self.assertEqual(decision.next_action, "draft_reply")
        self.assertEqual(decision.priority, "high")
        self.assertNotIn("Next_Followup_At", phase6_lead_patch(record, decision))

    def test_trusted_service_hint_is_separate_from_ai(self):
        record = self.lead(Service_Types=None)
        ai_only = build_sales_decision(
            record,
            now=datetime(2026, 9, 28, 14, tzinfo=timezone.utc),
            ai_hint={"service_type": "Structured Cabling", "confidence": 1.0},
        )
        self.assertIsNone(ai_only.service_type)
        self.assertIsNone(ai_only.service_type_source)

        invalid_evidence = build_sales_decision(
            record,
            now=datetime(2026, 9, 28, 14, tzinfo=timezone.utc),
            trusted_service_hint={
                "value": "Structured Cabling",
                "evidence": "ai_confidence",
            },
        )
        self.assertIsNone(invalid_evidence.service_type)

        trusted = build_sales_decision(
            record,
            now=datetime(2026, 9, 28, 14, tzinfo=timezone.utc),
            trusted_service_hint={
                "value": "Structured Cabling",
                "evidence": "explicit_customer_selection",
            },
        )
        self.assertEqual(trusted.service_type, "Structured Cabling")
        self.assertEqual(trusted.service_type_source, "trusted_hint")

    def test_tampered_decision_hash_is_rejected(self):
        decision = build_sales_decision(
            self.lead(),
            now=datetime(2026, 9, 28, 14, tzinfo=timezone.utc),
        ).model_dump()
        decision["priority"] = "urgent"
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            validate_sales_decision(decision)

    def test_two_business_days_from_friday_lands_tuesday(self):
        # 2026-10-02 is Friday. Toronto is UTC-4 on this date.
        now = datetime(2026, 10, 2, 15, 0, tzinfo=timezone.utc)
        due = business_due(now, 2)
        self.assertEqual(
            due.isoformat(),
            "2026-10-06T21:00:00+00:00",
        )

    def test_same_day_after_close_rolls_to_next_business_day(self):
        # Friday 18:00 Toronto -> Monday 17:00 Toronto.
        now = datetime(2026, 10, 2, 22, 0, tzinfo=timezone.utc)
        due = business_due(now, 0)
        self.assertEqual(
            due.isoformat(),
            "2026-10-05T21:00:00+00:00",
        )

    def test_missing_information_is_bounded_metadata_only(self):
        decision = build_sales_decision(
            self.lead(
                Email=None,
                Phone=None,
                Mobile=None,
                Service_Types=None,
                City=None,
                State=None,
            ),
            now=datetime(2026, 9, 28, 14, tzinfo=timezone.utc),
        )
        self.assertEqual(
            decision.missing_information,
            ["service_type", "contact_method", "location"],
        )
        self.assertEqual(decision.next_action, "review")

    def test_unknown_language_is_explicit_gap_for_email_followup(self):
        decision = build_sales_decision(
            self.lead(Language=None, Preferred_Language=None),
            now=datetime(2026, 9, 28, 14, tzinfo=timezone.utc),
        )
        self.assertIn("preferred_language", decision.missing_information)
        self.assertEqual(decision.language, "unknown")
        self.assertEqual(decision.next_action, "draft_reply")
        self.assertEqual(validate_sales_decision(decision), decision)

        opted_out = build_sales_decision(
            self.lead(Email_Opt_Out=True, Language=None, Preferred_Language=None),
            now=datetime(2026, 9, 28, 14, tzinfo=timezone.utc),
        )
        self.assertNotIn("preferred_language", opted_out.missing_information)

    def test_hash_is_stable_for_irrelevant_ai_keys(self):
        now = datetime(2026, 9, 28, 14, tzinfo=timezone.utc)
        first = build_sales_decision(
            self.lead(),
            now=now,
            ai_hint={"language": "fr", "unused": "one"},
        )
        second = build_sales_decision(
            self.lead(),
            now=now,
            ai_hint={"language": "fr", "unused": "two"},
        )
        self.assertEqual(first.decision_hash, second.decision_hash)

    def test_naive_timestamps_and_bad_ids_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "Invalid lead id"):
            build_sales_decision(
                self.lead(id="bad"),
                now=datetime(2026, 9, 28, 14, tzinfo=timezone.utc),
            )
        with self.assertRaisesRegex(ValueError, "timezone"):
            build_sales_decision(
                self.lead(Modified_Time="2026-09-28T10:00:00"),
                now=datetime(2026, 9, 28, 14, tzinfo=timezone.utc),
            )


if __name__ == "__main__":
    unittest.main()
