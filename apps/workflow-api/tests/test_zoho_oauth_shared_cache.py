from pathlib import Path
import json
import os
import stat
import tempfile
import time
import unittest
from unittest.mock import patch

from workflow.config import ZohoOAuthSettings
from workflow.zoho_oauth import ZohoOAuthManager


class ZohoSharedCacheTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "zoho-oauth.json"
        path.write_text(json.dumps({"refresh_token": "fixture-refresh", "access_token": "stale"}))
        path.chmod(0o640)
        self.path = path
        self.settings = ZohoOAuthSettings(enabled=True, client_id="fixture-id",
            client_secret="fixture-secret", redirect_uri="https://example.invalid/callback",
            accounts_base_url="https://accounts.zoho.com", scopes=("ZohoCRM.modules.READ",),
            credentials_path=path, state_secret="fixture-state", state_ttl_seconds=600)

    def test_new_process_reuses_persisted_token_without_second_refresh(self):
        calls = []
        class Response:
            status_code = 200
            def json(self):
                return {"access_token": "fresh-token", "expires_in": 3600}
        class Http:
            def __init__(self, *args, **kwargs): pass
            def __enter__(self): return self
            def __exit__(self, *args): return None
            def post(self, url, data):
                calls.append(url)
                return Response()
        with patch("workflow.zoho_oauth.httpx.Client", Http):
            self.assertEqual(ZohoOAuthManager(self.settings).access_token(), "fresh-token")
            self.assertEqual(ZohoOAuthManager(self.settings).access_token(), "fresh-token")
        self.assertEqual(len(calls), 1)
        saved = json.loads(self.path.read_text())
        self.assertGreater(saved["access_token_expires_at"], time.time() + 3400)
        self.assertEqual(saved["refresh_token"], "fixture-refresh")
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o640)
        self.assertEqual(stat.S_IMODE(self.path.with_suffix(".lock").stat().st_mode), 0o600)

    def test_untrusted_refresh_lock_fails_before_network(self):
        lock = self.path.with_suffix(".lock")
        lock.write_text("")
        lock.chmod(0o666)
        with patch("workflow.zoho_oauth.httpx.Client") as http:
            with self.assertRaisesRegex(ValueError, "not trusted"):
                ZohoOAuthManager(self.settings).access_token()
        http.assert_not_called()

    def test_failed_refresh_does_not_overwrite_credentials(self):
        before = self.path.read_bytes()
        class Response:
            status_code = 400
            text = '{"error":"Access Denied"}'
        class Http:
            def __init__(self, *args, **kwargs): pass
            def __enter__(self): return self
            def __exit__(self, *args): return None
            def post(self, url, data): return Response()
        with patch("workflow.zoho_oauth.httpx.Client", Http):
            with self.assertRaisesRegex(ValueError, "token refresh failed"):
                ZohoOAuthManager(self.settings).access_token()
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
