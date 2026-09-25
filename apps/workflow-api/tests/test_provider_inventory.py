from __future__ import annotations

import unittest
from unittest.mock import patch

from workflow import api


class _BrokenOAuthManager:
    def status(self):
        raise ValueError("simulated credential status failure")


class ProviderInventoryResilienceTests(unittest.IsolatedAsyncioTestCase):
    async def test_oauth_status_failure_does_not_crash_inventory(self) -> None:
        with (
            patch.object(api, "_validate_api_key"),
            patch.object(api, "_zoho_oauth_manager", return_value=_BrokenOAuthManager()),
            patch.object(api.google_oauth_manager, "status", side_effect=ValueError("simulated")),
        ):
            payload = await api.provider_inventory("test")

        zoho = payload["providers"]["zoho"]
        google = payload["providers"]["google_admin"]
        self.assertFalse(zoho["connected"])
        self.assertFalse(google["connected"])
        self.assertEqual(zoho["status_error"], "ValueError")
        self.assertEqual(google["status_error"], "ValueError")
        self.assertIn("github", payload["providers"])
        self.assertIn("cloudflare", payload["providers"])


if __name__ == "__main__":
    unittest.main()
