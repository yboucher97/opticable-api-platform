import copy
from datetime import datetime, timedelta, timezone
import unittest

from workflow.automation import customer_communications as cc

NOW = datetime.fromisoformat("2026-10-07T15:00:00+00:00")


def fixture(now=NOW, language="en", mode="TEST_ONLY"):
    proof = {"mode": mode, "lineage_verified": True, "protected": False,
        "test_run": "phase18-fixture", "contact_id": "101", "account_id": "102",
        "deal_id": "103", "site_id": "104", "contact_email": "yboucher@opticable.ca",
        "contact_account_id": "102", "deal_account_id": "102", "deal_contact_id": "101",
        "deal_site_id": "104", "site_account_id": "102", "contact_version": "cv1",
        "deal_version": "dv1", "site_version": "sv1", "observed_at": now.isoformat(),
        "language": language, "language_source": "crm_preference", "opt_out": False}
    context = {"contact_id": "101", "account_id": "102", "deal_id": "103", "site_id": "104",
        "recipient_email": proof["contact_email"], "observed_at": now.isoformat(),
        "suppression_checked_at": now.isoformat(), **{key: False for key in cc.STOP_FLAGS},
        "object_id": "501", "estimate_id": "501", "estimate_number": "EST-001",
        "finance_integrated": True, "finance_account_id": "102", "finance_deal_id": "103",
        "finance_site_id": "104", "status": "sent", "sent_at": "2026-10-02T10:00:00-04:00",
        "expiry_date": "2026-11-01", "deal_active": True}
    return context, proof


def appointment(now=NOW, language="en"):
    context, proof = fixture(now, language)
    context.update(object_id="601", installation_id="601", installation_status="Scheduled",
        cancelled=False, human_schedule_confirmed=True, human_schedule_evidence="native-ui-event-v1",
        installation_account_id="102", installation_deal_id="103", installation_site_id="104",
        installation_contact_id="101", timezone="America/Toronto", scheduled_at="2026-10-08T10:00:00-04:00",
        technician_required=True, technician_id="tech1", site_display="123 Main Street, Montréal",
        access_instructions="Use the main entrance")
    return context, proof


def verified(plan, at=NOW, identity="m1"):
    result = {"family": plan["family"], "object_id": plan["object_id"], "effect_key": plan["effect_key"],
        "status": "verified", "sent_at": at.isoformat(), "provider_message_id": identity,
        "content_hash": plan["content_hash"]}
    if "sequence" in plan:
        result["sequence"] = plan["sequence"]
    return result


def sent_message(plan, identity="m1"):
    return {"id": identity, "outgoing": True, "to": [plan["recipient"]],
            "cc": [], "bcc": [], "subject": plan["subject"], "body": plan["body"]}


class QuoteCommunicationTests(unittest.TestCase):
    def plan(self, context=None, proof=None, history=(), now=NOW):
        base, association = fixture(now)
        return cc.plan_quote_reminder(context or base, proof or association, history, now, communications_enabled=True)

    def test_first_reminder_is_due_after_three_weekdays_not_three_calendar_days(self):
        due = cc.business_days_after("2026-10-02T10:00:00-04:00", 3)
        self.assertEqual(due.isoformat(), "2026-10-07T10:00:00-04:00")
        before = datetime.fromisoformat("2026-10-07T13:59:59+00:00")
        self.assertEqual(self.plan(now=before)["state"], "WAIT")
        plan = self.plan()
        self.assertEqual((plan["state"], plan["sequence"]), ("READY", 1))
        self.assertEqual(plan["effect_key"], "customer.quote.reminder:501:1")
        self.assertFalse(plan["send_authority"])

    def test_second_waits_five_business_days_after_actual_first_and_then_stops(self):
        first = self.plan()
        first_at = datetime.fromisoformat("2026-10-09T18:00:00+00:00")
        first_history = verified(first, first_at)
        early = datetime.fromisoformat("2026-10-15T18:00:00+00:00")
        self.assertEqual(self.plan(history=[first_history], now=early)["state"], "WAIT")
        due = datetime.fromisoformat("2026-10-16T18:00:00+00:00")
        second = self.plan(history=[first_history], now=due)
        self.assertEqual((second["state"], second["sequence"]), ("READY", 2))
        self.assertNotEqual(first["subject"], second["subject"])
        self.assertEqual(self.plan(history=[first_history, verified(second, due, "m2")], now=due)["state"], "HUMAN")

    def test_all_quote_stops_are_checked_before_send(self):
        changes = [{"status": status} for status in ("accepted", "declined", "draft", "expired")]
        changes += [{"deal_active": False}, {"expiry_date": "2026-10-06"}]
        changes += [{key: True} for key in cc.STOP_FLAGS]
        for change in changes:
            with self.subTest(change=change):
                context, proof = fixture();context.update(change)
                self.assertEqual(self.plan(context, proof)["state"], "SUPPRESSED")

    def test_native_finance_not_legacy_quote_and_exact_association_required(self):
        for change in ({"finance_integrated": False}, {"finance_deal_id": "999"},
                       {"finance_account_id": "999"}, {"finance_site_id": "999"}, {"object_id": "999"}):
            with self.subTest(change=change):
                context, proof = fixture();context.update(change)
                self.assertEqual(self.plan(context, proof)["state"], "HUMAN")

    def test_status_equivalent_fixture_is_explicit_test_only_not_a_finance_transaction(self):
        context, proof = fixture()
        context.update(finance_integrated=False, source_kind="TEST_STATUS_EQUIVALENT", status_equivalent_fixture=True)
        plan = self.plan(context, proof)
        self.assertEqual((plan["state"], plan["finance_basis"]), ("READY", "TEST_STATUS_EQUIVALENT"))
        context["recipient_email"] = proof["contact_email"] = "person@customer.ca"
        proof["mode"] = "REAL_NEW"
        context.update(native_books_verified=True, native_crm_finance_verified=True, finance_integrated=True)
        self.assertEqual(self.plan(context, proof)["state"], "HUMAN")

    def test_uncertain_ack_and_unknown_history_never_authorize_retry(self):
        for status in ("attempted", "provider_ack", "uncertain", "failed", "unknown"):
            with self.subTest(status=status):
                row = {"family": "customer.quote.reminder", "object_id": "501", "status": status}
                self.assertEqual(self.plan(history=[row])["state"], "RECONCILE")

    def test_foreign_object_history_does_not_block_or_consume_our_sequence(self):
        row = {"family": "customer.quote.reminder", "object_id": "999", "status": "uncertain"}
        self.assertEqual(self.plan(history=[row])["sequence"], 1)

    def test_bad_sent_or_expiry_timestamp_is_human_and_no_clock_guess(self):
        for field, value in (("sent_at", "2026-10-02T10:00:00"), ("sent_at", "nonsense"),
                             ("sent_at", "2027-10-02T10:00:00+00:00"), ("expiry_date", "nonsense")):
            with self.subTest(field=field, value=value):
                context, proof = fixture();context[field] = value
                self.assertEqual(self.plan(context, proof)["state"], "HUMAN")

    def test_weekday_cadence_preserves_toronto_wall_time_across_dst(self):
        self.assertEqual(cc.business_days_after("2026-10-30T10:00:00-04:00", 1).isoformat(), "2026-11-02T10:00:00-05:00")


class AssociationAndSuppressionTests(unittest.TestCase):
    def test_wrong_recipient_or_every_wrong_native_relationship_denied(self):
        changes = {"contact_email": "wrong@opticable.ca", "contact_account_id": "bad",
            "deal_account_id": "bad", "deal_contact_id": "bad", "deal_site_id": "bad", "site_account_id": "bad"}
        for field, value in changes.items():
            with self.subTest(field=field):
                context, proof = fixture();proof[field] = value
                self.assertEqual(cc.plan_quote_reminder(context, proof, [], NOW, communications_enabled=True)["state"], "HUMAN")

    def test_recipient_header_injection_lists_and_display_names_denied(self):
        for value in ("a@opticable.ca,b@opticable.ca", "a@opticable.ca\r\nBcc: b@other.ca", "Alice <a@opticable.ca>",
                      " a@opticable.ca", "a@opticable", "a..b@opticable.ca"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                cc.normalize_recipient(value)
        self.assertEqual(cc.normalize_recipient("ALICE@OPTICABLE.CA"), "alice@opticable.ca")

    def test_protected_and_false_lineage_denied_even_with_right_address(self):
        for field, value in (("protected", True), ("protected", None), ("lineage_verified", False), ("mode", "REAL"), ("test_run", "")):
            with self.subTest(field=field):
                context, proof = fixture();proof[field] = value
                self.assertEqual(cc.plan_quote_reminder(context, proof, [], NOW, communications_enabled=True)["state"], "HUMAN")

    def test_test_controlled_recipient_cannot_be_expanded_by_a_context_field(self):
        context, proof = fixture();context["recipient_email"] = proof["contact_email"] = "soumissions@opticable.ca"
        context["controlled_recipients"] = ["soumissions@opticable.ca"]
        self.assertEqual(cc.plan_quote_reminder(context, proof, [], NOW, communications_enabled=True)["state"], "HUMAN")

    def test_stale_missing_or_future_proofs_and_unknown_suppression_denied(self):
        for field in ("observed_at", "suppression_checked_at"):
            for value in (None, (NOW - timedelta(minutes=6)).isoformat(), (NOW + timedelta(seconds=1)).isoformat()):
                with self.subTest(field=field, value=value):
                    context, proof = fixture();context[field] = value
                    self.assertEqual(cc.plan_quote_reminder(context, proof, [], NOW, communications_enabled=True)["state"], "HUMAN")
        for flag in cc.STOP_FLAGS:
            with self.subTest(flag=flag):
                context, proof = fixture();context.pop(flag)
                self.assertEqual(cc.plan_quote_reminder(context, proof, [], NOW, communications_enabled=True)["state"], "HUMAN")

    def test_customer_kill_switch_defaults_stopped_and_does_not_create_effect(self):
        context, proof = fixture()
        plan = cc.plan_quote_reminder(context, proof, [], NOW)
        self.assertEqual(plan["state"], "SUPPRESSED")
        self.assertNotIn("effect_key", plan)

    def test_deterministic_fr_en_are_equivalent_and_language_is_not_guessed(self):
        bodies = []
        for language in ("fr", "en"):
            context, proof = fixture(language=language)
            plan = cc.plan_quote_reminder(context, proof, [], NOW, communications_enabled=True)
            self.assertEqual((plan["state"], plan["language"]), ("READY", language))
            self.assertTrue(plan["subject"].startswith("[OPTIBRAIN TEST]"))
            self.assertIn("EST-001", plan["body"]);bodies.append(plan["body"])
        self.assertNotEqual(*bodies)
        for language, source in ((None, "crm_preference"), ("en", "person_name"), ("de", "owner_selection")):
            with self.subTest(language=language, source=source):
                context, proof = fixture();proof.update(language=language, language_source=source)
                context["contact_name"] = "Jean Tremblay"
                self.assertEqual(cc.plan_quote_reminder(context, proof, [], NOW, communications_enabled=True)["state"], "HUMAN")

    def test_real_template_has_no_test_or_internal_ids_and_is_never_its_own_authority(self):
        context, proof = fixture(mode="REAL_NEW")
        context["recipient_email"] = proof["contact_email"] = "person@customer.ca"
        context.update(native_books_verified=True, native_crm_finance_verified=True)
        plan = cc.plan_quote_reminder(context, proof, [], NOW, communications_enabled=True)
        self.assertEqual(plan["state"], "READY")
        self.assertFalse(plan["send_authority"])
        for marker in ("OPTIBRAIN", "501", "103", "104", "idempotency", "automation"):
            self.assertNotIn(marker, plan["subject"] + plan["body"])
        self.assertEqual(plan["expected_native_bindings"]["deal_id"], "103")


class AppointmentCommunicationTests(unittest.TestCase):
    def test_confirmation_replay_and_reschedule_are_versioned(self):
        context, proof = appointment()
        first = cc.plan_appointment_confirmation(context, proof, [], NOW, communications_enabled=True)
        self.assertEqual(first["state"], "READY")
        history = [verified(first)]
        self.assertEqual(cc.plan_appointment_confirmation(context, proof, history, NOW, communications_enabled=True)["state"], "SUPPRESSED")
        context["scheduled_at"] = "2026-10-09T11:00:00-04:00"
        context["human_schedule_evidence"] = "native-ui-event-v2"
        updated = cc.plan_appointment_confirmation(context, proof, history, NOW, communications_enabled=True)
        self.assertEqual(updated["state"], "READY");self.assertTrue(updated["updated"])
        self.assertIn("Updated appointment", updated["subject"])
        self.assertNotEqual(first["effect_key"], updated["effect_key"])

    def test_return_to_prior_datetime_still_has_new_human_schedule_revision(self):
        context, proof = appointment();first = cc.plan_appointment_confirmation(context, proof, [], NOW, communications_enabled=True)
        context["human_schedule_evidence"] = "native-ui-event-v3"
        restored = cc.plan_appointment_confirmation(context, proof, [verified(first)], NOW, communications_enabled=True)
        self.assertEqual(restored["state"], "READY")
        self.assertNotEqual(first["schedule_version"], restored["schedule_version"])

    def test_schedule_fingerprint_includes_every_recipient_logistics_binding(self):
        context, _ = appointment();original = cc.schedule_fingerprint(context)
        changes = {"contact_id": "other", "site_id": "other", "site_display": "321 Main Street",
            "scheduled_at": "2026-10-09T10:00:00-04:00", "technician_id": "tech2", "access_instructions": "Side door",
            "human_schedule_evidence": "native-ui-event-v2"}
        for field, value in changes.items():
            with self.subTest(field=field):
                changed = {**context, field: value}
                self.assertNotEqual(cc.schedule_fingerprint(changed), original)

    def test_reminder_requires_current_confirmation_and_is_sent_once_in_last24hours(self):
        context, proof = appointment()
        self.assertEqual(cc.plan_appointment_reminder(context, proof, [], NOW, communications_enabled=True)["state"], "HUMAN")
        confirmation = cc.plan_appointment_confirmation(context, proof, [], NOW, communications_enabled=True)
        history = [verified(confirmation)]
        reminder = cc.plan_appointment_reminder(context, proof, history, NOW, communications_enabled=True)
        self.assertEqual(reminder["state"], "READY")
        history.append(verified(reminder, identity="m2"))
        self.assertEqual(cc.plan_appointment_reminder(context, proof, history, NOW, communications_enabled=True)["state"], "SUPPRESSED")
        earlier = NOW - timedelta(hours=2);context, proof = appointment(earlier)
        self.assertEqual(cc.plan_appointment_reminder(context, proof, [verified(confirmation, earlier)], earlier, communications_enabled=True)["state"], "WAIT")

    def test_cancellation_reschedule_wrong_customer_and_missing_human_schedule_stop(self):
        changes = [("cancelled", True, "SUPPRESSED"), ("installation_status", "Blocked", "SUPPRESSED"),
            ("human_schedule_confirmed", False, "HUMAN"), ("human_schedule_evidence", "", "HUMAN"),
            ("installation_contact_id", "wrong", "HUMAN"), ("installation_site_id", "wrong", "HUMAN"),
            ("scheduled_at", "2026-10-08", "HUMAN"), ("timezone", "UTC", "HUMAN"), ("technician_id", "", "HUMAN")]
        for field, value, expected in changes:
            with self.subTest(field=field):
                context, proof = appointment();context[field] = value
                self.assertEqual(cc.plan_appointment_confirmation(context, proof, [], NOW, communications_enabled=True)["state"], expected)

    def test_dst_nonexistent_time_is_denied_ambiguous_time_requires_explicit_valid_offset(self):
        context, _ = appointment()
        for value in ("2026-03-08T02:30:00-05:00", "2026-03-08T02:30:00-04:00", "2026-11-01T01:30:00"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                cc.schedule_fingerprint({**context, "scheduled_at": value})
        earlier = cc.schedule_fingerprint({**context, "scheduled_at": "2026-11-01T01:30:00-04:00"})
        later = cc.schedule_fingerprint({**context, "scheduled_at": "2026-11-01T01:30:00-05:00"})
        self.assertNotEqual(earlier, later)

    def test_exact24hour_reminder_window_handles_dst_in_elapsed_hours(self):
        now = datetime.fromisoformat("2026-10-31T16:30:00+00:00")
        context, proof = appointment(now);context["scheduled_at"] = "2026-11-01T11:30:00-05:00"
        confirmation = cc.plan_appointment_confirmation(context, proof, [], now, communications_enabled=True)
        reminder = cc.plan_appointment_reminder(context, proof, [verified(confirmation, now)], now, communications_enabled=True)
        self.assertEqual(reminder["state"], "READY")
        self.assertEqual(reminder["due_at"], now.isoformat())


class CompletionAndReconciliationTests(unittest.TestCase):
    def completion(self):
        context, proof = appointment()
        context.update(installation_status="Completed", return_visit_required=False,
            human_completion_confirmed=True, human_completion_evidence="native-completion-v1",
            completed_at="2026-10-07T10:00:00-04:00")
        return context, proof

    def test_completion_requires_human_and_final_work_then_sends_once_per_visit(self):
        context, proof = self.completion()
        plan = cc.plan_completion_message(context, proof, [], NOW, communications_enabled=True)
        self.assertEqual(plan["state"], "READY")
        self.assertEqual(cc.plan_completion_message(context, proof, [verified(plan)], NOW, communications_enabled=True)["state"], "SUPPRESSED")
        for field, value, expected in (("return_visit_required", True, "SUPPRESSED"),
            ("human_completion_confirmed", False, "HUMAN"), ("installation_status", "In Progress", "SUPPRESSED"),
            ("completed_at", "2026-10-08T10:00:00-04:00", "HUMAN"), ("installation_deal_id", "wrong", "HUMAN")):
            with self.subTest(field=field):
                changed = {**context, field: value}
                self.assertEqual(cc.plan_completion_message(changed, proof, [], NOW, communications_enabled=True)["state"], expected)

    def test_lost_ack_reconciles_one_exact_native_sent_effect_without_resend(self):
        context, proof = fixture();plan = cc.plan_quote_reminder(context, proof, [], NOW, communications_enabled=True)
        reconciled = cc.reconcile_delivery(plan, [sent_message(plan)])
        self.assertEqual((reconciled["state"], reconciled["provider_message_id"]), ("VERIFIED", "m1"))
        self.assertEqual(cc.reconcile_delivery(plan, [sent_message(plan), sent_message(plan)])["state"], "VERIFIED")
        self.assertEqual(cc.reconcile_delivery(plan, [sent_message(plan), sent_message(plan, "m2")])["state"], "DUPLICATE")
        missing = cc.reconcile_delivery(plan, [])
        self.assertEqual(missing["state"], "UNKNOWN");self.assertFalse(missing["resend_allowed"])

    def test_wrong_recipient_cc_bcc_incoming_or_body_cannot_prove_an_effect(self):
        context, proof = fixture();plan = cc.plan_quote_reminder(context, proof, [], NOW, communications_enabled=True)
        changes = ({"to": ["wrong@opticable.ca"]}, {"to": [plan["recipient"], "other@opticable.ca"]},
                   {"cc": ["other@opticable.ca"]}, {"bcc": ["other@opticable.ca"]}, {"outgoing": False},
                   {"subject": "Other subject"}, {"body": "Different body"}, {"body": None})
        for change in changes:
            with self.subTest(change=change):
                self.assertEqual(cc.reconcile_delivery(plan, [{**sent_message(plan), **change}])["state"], "UNKNOWN")

    def test_changed_plan_content_denied_and_inputs_remain_unmodified(self):
        context, proof = fixture();before = copy.deepcopy((context, proof))
        plan = cc.plan_quote_reminder(context, proof, [], NOW, communications_enabled=True)
        self.assertEqual((context, proof), before)
        plan["body"] = "Changed"
        with self.assertRaises(ValueError):
            cc.reconcile_delivery(plan, [])
