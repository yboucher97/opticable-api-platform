from __future__ import annotations

import unittest
from unittest.mock import patch

import httpx

from workflow.ai_router import AiRouter
from workflow.config import AiProviderSettings


class AiRouterTests(unittest.TestCase):
    def settings(self):
        return AiProviderSettings(
            openai_api_key="o",
            openai_model="openai-test",
            anthropic_api_key="a",
            anthropic_model="anthropic-test",
            gemini_api_key="g",
            gemini_model="gemini-test",
            provider_order=("openai", "anthropic", "gemini"),
            timeout_seconds=30,
        )

    def test_openai(self):
        router=AiRouter(self.settings())
        response=httpx.Response(
            200,
            json={"output_text":"ok","output":[]},
            request=httpx.Request("POST","https://api.openai.com/v1/responses"),
        )
        with patch("workflow.ai_router.httpx.post", return_value=response):
            result=router.generate("hello", provider="openai")
        self.assertEqual(result["provider"], "openai")
        self.assertEqual(result["text"], "ok")

    def test_auto_falls_back(self):
        router=AiRouter(self.settings())
        fail=httpx.Response(500,json={"error":"x"},request=httpx.Request("POST","https://api.openai.com/v1/responses"))
        success=httpx.Response(
            200,
            json={"content":[{"type":"text","text":"fallback"}]},
            request=httpx.Request("POST","https://api.anthropic.com/v1/messages"),
        )
        with patch("workflow.ai_router.httpx.post", side_effect=[fail, success]):
            result=router.generate("hello", provider="auto")
        self.assertEqual(result["provider"], "anthropic")
        self.assertEqual(result["text"], "fallback")


if __name__ == "__main__":
    unittest.main()
