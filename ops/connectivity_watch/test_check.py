"""Offline tests: python3 -m unittest discover -s ops/connectivity_watch -p 'test_*.py'"""
import datetime as dt
import contextlib
import io
import json
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import urllib.error

spec = importlib.util.spec_from_file_location("connection_watch", Path(__file__).with_name("check.py"))
watch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watch)

class WatchdogTests(unittest.TestCase):
    def execute(self, retries, responses):
        """Exercise argparse -> main -> retry -> real probe -> HTTP boundary."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / 'config.json'
            config.write_text(json.dumps({'checks': [{'name': 'fixture',
                'url': 'https://example.invalid/health', 'retries': retries}]}))
            args = ['check', '--config', str(config), '--state', str(root / 'state.json'),
                    '--output', str(root / 'output.json')]
            with patch.object(sys, 'argv', args), patch.object(watch.OPENER, 'open', side_effect=responses) as http, \
                    patch.object(watch.time, 'sleep') as sleep, contextlib.redirect_stdout(io.StringIO()):
                code = watch.main()
            return code, json.loads((root / 'output.json').read_text()), http.call_count, sleep.call_count

    @staticmethod
    def response(code):
        if code >= 400:
            return urllib.error.HTTPError('https://example.invalid/health', code, 'fixture', {}, None)
        response = Mock();response.status = code
        response.__enter__ = Mock(return_value=response);response.__exit__ = Mock(return_value=False)
        return response

    def test_main_dispatches_configured_retry_then_records_success(self):
        code, report, calls, sleeps = self.execute(1, [self.response(503), self.response(200)])
        self.assertEqual(calls, 2);self.assertEqual(sleeps, 1)
        self.assertEqual(code, 0);self.assertEqual(report['checks'][0]['status'], 'HEALTHY')
        self.assertIsNotNone(report['checks'][0]['last_success'])

    def test_main_exhausts_bounded_retry_and_records_failure(self):
        code, report, calls, sleeps = self.execute(999, [self.response(503) for _ in range(3)])
        self.assertEqual(calls, 3);self.assertEqual(sleeps, 2)
        self.assertEqual(code, 1);self.assertEqual(report['checks'][0]['status'], 'SERVER_ERROR')
        self.assertIsNone(report['checks'][0]['last_success'])

    def test_main_does_not_retry_authentication_failures(self):
        for status in (401, 403):
            code, report, calls, sleeps = self.execute(2, [self.response(status)])
            self.assertEqual(calls, 1);self.assertEqual(sleeps, 0);self.assertEqual(code, 1)

    def test_main_zero_retries_performs_one_attempt(self):
        code, report, calls, sleeps = self.execute(0, [self.response(503)])
        self.assertEqual(calls, 1);self.assertEqual(sleeps, 0);self.assertEqual(code, 1)

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
