from __future__ import annotations

import copy
import unittest

from workflow.automation.mailbox_readiness import verify_mailbox_readiness


class FakeMailAccount:
    def __init__(self):
        self.calls = []
        self.data = {
            "accountId": "456",
            "enabled": True,
            "status": True,
            "mailboxStatus": "enabled",
            "outgoingBlocked": False,
            "smtpStatus": True,
            "emailAddress": [
                {"mailId": "info@opticable.ca", "isConfirmed": True, "isPrimary": True, "isAlias": False},
            ],
            "sendMailDetails": [
                {"fromAddress": "info@opticable.ca", "status": True, "mode": "mailbox"},
            ],
        }

    def request(self, service, method, path, **kwargs):
        self.calls.append((service, method, path, copy.deepcopy(kwargs)))
        if (service, method, path) != ("mail", "GET", "/api/accounts/456"):
            raise AssertionError("readiness probe must be one exact GET")
        return {
            "ok": True,
            "status": 200,
            "data": {"status": {"code": 200}, "data": copy.deepcopy(self.data)},
        }


class MailboxReadinessTests(unittest.TestCase):
    def setUp(self):
        self.mail = FakeMailAccount()

    def verify(self):
        return verify_mailbox_readiness(self.mail, account_id="456", from_address="info@opticable.ca")

    def test_ready_mailbox_and_sender_alias_pass_read_only(self):
        result = self.verify()
        self.assertEqual(result["result"], "PASS")
        self.assertEqual(result["provider_writes"], 0)
        self.assertEqual(self.mail.calls, [("mail", "GET", "/api/accounts/456", {})])

    def test_disabled_or_outbound_blocked_mailbox_fails(self):
        for changes in (
            {"enabled": False},
            {"status": False},
            {"mailboxStatus": "disabled"},
            {"outgoingBlocked": True},
            {"smtpStatus": False},
        ):
            with self.subTest(changes=changes):
                original = copy.deepcopy(self.mail.data)
                self.mail.data.update(changes)
                with self.assertRaises(ValueError):
                    self.verify()
                self.mail.data = original

    def test_unconfirmed_address_without_active_alias_fails(self):
        self.mail.data["emailAddress"][0]["isConfirmed"] = False
        self.mail.data["sendMailDetails"][0]["status"] = False
        with self.assertRaises(ValueError):
            self.verify()

    def test_active_alias_can_authorize_non_primary_sender(self):
        self.mail.data["sendMailDetails"].append(
            {"fromAddress": "soumissions@opticable.ca", "status": True, "mode": "mailbox"}
        )
        result = verify_mailbox_readiness(
            self.mail,
            account_id="456",
            from_address="soumissions@opticable.ca",
        )
        self.assertTrue(result["active_send_alias"])
        self.assertFalse(result["confirmed_address"])

    def test_inactive_alias_fails_even_if_address_inventory_mentions_it(self):
        self.mail.data["emailAddress"].append(
            {"mailId": "soumissions@opticable.ca", "isConfirmed": True, "isPrimary": False, "isAlias": True}
        )
        with self.assertRaises(ValueError):
            verify_mailbox_readiness(
                self.mail,
                account_id="456",
                from_address="soumissions@opticable.ca",
            )

    def test_invalid_account_or_sender_fails_before_network(self):
        with self.assertRaises(ValueError):
            verify_mailbox_readiness(self.mail, account_id="bad", from_address="info@opticable.ca")
        with self.assertRaises(ValueError):
            verify_mailbox_readiness(self.mail, account_id="456", from_address="bad")
        self.assertEqual(self.mail.calls, [])


if __name__ == "__main__":
    unittest.main()
