from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from workflow.config import GoogleOAuthSettings
from workflow.google_api import GoogleApiClient
from workflow.google_oauth import GoogleOAuthManager


class GoogleAdminControlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.settings = GoogleOAuthSettings(
            enabled=True,
            client_id="test-client.apps.googleusercontent.com",
            client_secret="test-secret",
            redirect_uri="https://api01.opticable.ca/v1/integrations/google/oauth/callback",
            scopes=(
                "https://www.googleapis.com/auth/analytics.edit",
                "https://www.googleapis.com/auth/tagmanager.edit.containers",
                "https://www.googleapis.com/auth/tagmanager.publish",
            ),
            credentials_path=self.root / "google-oauth.json",
            state_secret="unit-test-state-secret",
            state_ttl_seconds=900,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_oauth_state_roundtrip(self) -> None:
        manager = GoogleOAuthManager(self.settings)
        state = manager.build_state()
        manager.validate_state(state)
        with self.assertRaises(ValueError):
            manager.validate_state(state + "tampered")

    def test_authorization_url_requests_offline_incremental_access(self) -> None:
        manager = GoogleOAuthManager(self.settings)
        url = manager.build_authorization_redirect()
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        self.assertEqual(parsed.netloc, "accounts.google.com")
        self.assertEqual(query["access_type"], ["offline"])
        self.assertEqual(query["prompt"], ["consent"])
        self.assertEqual(query["include_granted_scopes"], ["true"])
        self.assertIn("https://www.googleapis.com/auth/analytics.edit", query["scope"][0])
        self.assertIn("https://www.googleapis.com/auth/tagmanager.publish", query["scope"][0])

    def test_saved_access_token_is_reused_without_refresh(self) -> None:
        payload = {
            "provider": "google",
            "client_id": self.settings.client_id,
            "redirect_uri": self.settings.redirect_uri,
            "connected_at": "2026-09-25T00:00:00Z",
            "scope": " ".join(self.settings.scopes),
            "refresh_token": "refresh-token",
            "access_token": "cached-access-token",
            "access_token_expires_at": int(time.time()) + 1800,
            "expires_in": 3600,
        }
        self.settings.credentials_path.write_text(json.dumps(payload), encoding="utf-8")
        manager = GoogleOAuthManager(self.settings)
        self.assertEqual(manager.access_token(), "cached-access-token")

    def test_api_client_rejects_unsafe_paths_before_network(self) -> None:
        manager = GoogleOAuthManager(self.settings)
        client = GoogleApiClient(manager)
        for unsafe in [
            "https://evil.example/path",
            "../oauth/token",
            "accounts/../secrets",
            "accounts\\bad",
            "accounts\nbad",
        ]:
            with self.subTest(path=unsafe), self.assertRaises(ValueError):
                client.request("tagmanager", "GET", unsafe)

    def test_api_client_rejects_unknown_service_and_method(self) -> None:
        manager = GoogleOAuthManager(self.settings)
        client = GoogleApiClient(manager)
        with self.assertRaises(ValueError):
            client.request("unknown", "GET", "accounts")
        with self.assertRaises(ValueError):
            client.request("tagmanager", "TRACE", "accounts")


if __name__ == "__main__":
    unittest.main()
