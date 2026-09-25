from __future__ import annotations

import unittest
from unittest.mock import patch

import httpx

from workflow.apollo_api import ApolloApiClient, ApolloApiError
from workflow.cloudflare_api import CloudflareApiClient, CloudflareApiError
from workflow.config import ApolloSettings, CloudflareSettings, GithubSettings
from workflow.github_api import GithubApiClient, GithubApiError


class CoreProviderTests(unittest.TestCase):
    def test_cloudflare_blocks_billing(self):
        client=CloudflareApiClient(CloudflareSettings(api_token="x", account_id="a", timeout_seconds=30))
        with self.assertRaises(CloudflareApiError):
            client.request("/accounts/a/billing/profile")

    def test_github_restricts_owner(self):
        client=GithubApiClient(GithubSettings(api_token="x", app_id=None, installation_id=None, private_key_path=None, owner="yboucher97", timeout_seconds=30))
        with self.assertRaises(GithubApiError):
            client.request("/repos/someone-else/repo")

    def test_apollo_credit_guard(self):
        client=ApolloApiClient(ApolloSettings(api_key="x", timeout_seconds=30, allow_credit_consumption=False))
        with self.assertRaises(ApolloApiError):
            client.request("/people/match", "POST", body={"email":"x@example.com"})

    def test_apollo_auth_header(self):
        client=ApolloApiClient(ApolloSettings(api_key="secret", timeout_seconds=30, allow_credit_consumption=False))
        def fake_request(method,url,**kwargs):
            self.assertEqual(kwargs["headers"]["x-api-key"], "secret")
            return httpx.Response(200,json={"ok":True},request=httpx.Request(method,url))
        with patch("workflow.apollo_api.httpx.request", side_effect=fake_request):
            result=client.request("/auth/health")
        self.assertTrue(result["ok"])


if __name__ == "__main__":
    unittest.main()
