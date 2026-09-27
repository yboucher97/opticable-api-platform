from __future__ import annotations

import unittest
from datetime import datetime, timezone

from workflow.automation.retry_control import classify_failure, decide_retry


class RetryControlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = datetime(2026, 9, 27, 16, tzinfo=timezone.utc)

    def test_http_and_network_categories(self) -> None:
        self.assertEqual(classify_failure(http_status=429), "rate_limited")
        self.assertEqual(classify_failure(http_status=503), "provider_unavailable")
        self.assertEqual(classify_failure(http_status=401), "authentication_expired")
        self.assertEqual(classify_failure(http_status=403), "authentication_expired")
        self.assertEqual(classify_failure(http_status=400), "permanent")
        self.assertEqual(classify_failure(http_status=408), "network_timeout")
        self.assertEqual(classify_failure(network_timeout=True), "network_timeout")

    def test_bounded_exponential_backoff_and_exhaustion(self) -> None:
        delays = [decide_retry(attempt=n, safe_to_retry=True, network_timeout=True,
                               base_delay_seconds=2, jitter_fraction=0, now=self.clock).delay_seconds
                  for n in range(1, 5)]
        self.assertEqual(delays, [2, 4, 8, 16])
        terminal = decide_retry(attempt=5, safe_to_retry=True, network_timeout=True, now=self.clock)
        self.assertEqual((terminal.action, terminal.delay_seconds), ("dead_letter", 0))

    def test_retry_after_seconds_and_http_date(self) -> None:
        seconds = decide_retry(attempt=1, safe_to_retry=True, http_status=429,
                               retry_after="45", now=self.clock)
        self.assertEqual(seconds.delay_seconds, 45)
        date = decide_retry(attempt=1, safe_to_retry=True, http_status=503,
                            retry_after="Sun, 27 Sep 2026 16:01:00 GMT", now=self.clock)
        self.assertEqual(date.delay_seconds, 60)
        self.assertEqual(decide_retry(attempt=1, safe_to_retry=True, http_status=429,
                                      retry_after="3600", now=self.clock).action,
                         "human_action_required")
        self.assertEqual(decide_retry(attempt=1, safe_to_retry=True, http_status=429,
                                      retry_after="bad", now=self.clock).action,
                         "human_action_required")

    def test_ambiguous_write_and_auth_failure_never_retry(self) -> None:
        for kwargs in ({"network_timeout": True}, {"http_status": 429}, {"http_status": 503}):
            decision = decide_retry(attempt=1, safe_to_retry=False, now=self.clock, **kwargs)
            self.assertEqual(decision.action, "human_action_required")
        self.assertEqual(decide_retry(attempt=1, safe_to_retry=True, http_status=401,
                                      now=self.clock).action, "human_action_required")
        self.assertEqual(decide_retry(attempt=1, safe_to_retry=True, http_status=404,
                                      now=self.clock).action, "dead_letter")

    def test_jitter_and_policy_bounds(self) -> None:
        decision = decide_retry(attempt=2, safe_to_retry=True, http_status=503,
                                base_delay_seconds=10, jitter_fraction=1, now=self.clock)
        self.assertEqual(decision.delay_seconds, 24)
        for kwargs in ({"attempt": 0}, {"attempt": 6}, {"max_attempts": 6},
                       {"base_delay_seconds": 0}, {"max_delay_seconds": 301},
                       {"jitter_fraction": -1}):
            with self.assertRaises(ValueError):
                options = {"attempt": 1, "safe_to_retry": True,
                           "http_status": 503, "now": self.clock}
                options.update(kwargs)
                decide_retry(**options)


if __name__ == "__main__":
    unittest.main()
