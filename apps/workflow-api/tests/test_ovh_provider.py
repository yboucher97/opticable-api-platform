from __future__ import annotations

import unittest
from unittest.mock import patch

import httpx

from workflow.config import OvhSettings
from workflow.ovh_api import OvhApiClient


class OvhApiTests(unittest.TestCase):
    def setUp(self):
        self.client = OvhApiClient(OvhSettings(
            endpoint="ovh-ca",
            application_key="app",
            application_secret="secret",
            consumer_key="consumer",
            timeout_seconds=60,
        ))

    def test_signed_get(self):
        captured = {}
        def fake_request(method, url, **kwargs):
            captured["method"] = method
            captured["url"] = url
            captured["headers"] = kwargs["headers"]
            return httpx.Response(200, json={"nichandle": "xx"}, request=httpx.Request(method, url))
        with patch("workflow.ovh_api.time.time", return_value=1000), patch("workflow.ovh_api.httpx.request", side_effect=fake_request):
            result = self.client.request("/me")
        self.assertTrue(result["ok"])
        self.assertEqual(captured["headers"]["X-Ovh-Timestamp"], "1000")
        self.assertTrue(captured["headers"]["X-Ovh-Signature"].startswith("$1$"))

    def test_rejects_unsafe_path(self):
        with self.assertRaises(ValueError):
            self.client.request("//evil")


if __name__ == "__main__":
    unittest.main()
