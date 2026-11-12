"""Offline tests: python3 -m unittest discover -s ops/connectivity_watch -p 'test_*.py'"""
import datetime as dt
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("connection_watch", Path(__file__).with_name("check.py"))
watch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watch)

class WatchdogTests(unittest.TestCase):
    def test_rejects_insecure_remote_http(self):
        self.assertEqual(watch.probe({"name": "a", "url": "http://example.com/health"})["status"], "CONFIG_ERROR")

    def test_missing_credential(self):
        self.assertEqual(watch.probe({"name": "a", "url": "https://example.com/health", "auth_env": "MISSING_OPTIBRAIN_TEST_SECRET_1193"})["status"], "MISSING_CREDENTIAL")

    def test_last_success_age(self):
        now = dt.datetime(2026, 11, 12, tzinfo=dt.timezone.utc)
        self.assertEqual(watch.age_hours("2026-11-11T00:00:00+00:00", now), 24)

    def test_unknown_last_use_not_assumed(self):
        self.assertIsNone(watch.age_hours(None, dt.datetime.now(dt.timezone.utc)))

    def test_block_credentials_in_url(self):
        self.assertFalse(watch.valid_url({"url": "https://user:pass@example.com/health"}))
        self.assertFalse(watch.valid_url({"url": "https://example.com/health?token=secret"}))

    def test_only_loopback_http(self):
        self.assertTrue(watch.valid_url({"url": "http://127.0.0.1:8100/health", "allow_http_localhost": True}))
        self.assertFalse(watch.valid_url({"url": "http://127.0.0.1.evil.test:8100/health", "allow_http_localhost": True}))

    def test_bounded_retry_on_503(self):
        with patch.object(watch, "probe", side_effect=[
            {"name": "a", "status": "SERVER_ERROR"},
            {"name": "a", "status": "HEALTHY"}]) as request, patch.object(watch.time, "sleep"):
            result = watch.probe_with_retry({"name": "a", "url": "https://example.com", "retries": 2})
        self.assertEqual(result["status"], "HEALTHY")
        self.assertEqual(request.call_count, 2)

    def test_auth_errors_are_not_retried(self):
        with patch.object(watch, "probe", return_value={"name": "a", "status": "UNAUTHORIZED"}) as request:
            result = watch.probe_with_retry({"name": "a", "url": "https://example.com"})
        self.assertEqual(result["status"], "UNAUTHORIZED")
        self.assertEqual(request.call_count, 1)

    def test_event_key_stable(self):
        self.assertEqual(watch.event_key("zoho", "UNAUTHORIZED"), watch.event_key("zoho", "UNAUTHORIZED"))
        self.assertNotEqual(watch.event_key("zoho", "UNAUTHORIZED"), watch.event_key("zoho", "HEALTHY"))

    def test_redirect_handler_does_not_forward(self):
        self.assertIsNone(watch.NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://other.example/"))

if __name__ == "__main__":
    unittest.main()
