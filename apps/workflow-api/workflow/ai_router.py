from __future__ import annotations

from typing import Any

import httpx

from .config import AiProviderSettings


class AiProviderError(RuntimeError):
    pass


class AiRouter:
    def __init__(self, settings: AiProviderSettings) -> None:
        self.settings = settings

    def configured(self) -> dict[str, bool]:
        return {
            "openai": bool(self.settings.openai_api_key and self.settings.openai_model),
            "anthropic": bool(self.settings.anthropic_api_key and self.settings.anthropic_model),
            "gemini": bool(self.settings.gemini_api_key and self.settings.gemini_model),
        }

    def generate(
        self,
        prompt: str,
        *,
        provider: str = "auto",
        system: str | None = None,
        max_tokens: int = 1200,
    ) -> dict[str, Any]:
        if not prompt.strip():
            raise ValueError("AI prompt cannot be empty.")
        if max_tokens < 1 or max_tokens > 32768:
            raise ValueError("max_tokens must be between 1 and 32768.")

        candidates = (
            list(self.settings.provider_order)
            if provider == "auto"
            else [provider.strip().lower()]
        )
        errors: list[str] = []
        configured = self.configured()

        for candidate in candidates:
            if candidate not in configured:
                errors.append(f"{candidate}: unsupported provider")
                continue
            if not configured[candidate]:
                errors.append(f"{candidate}: not configured")
                continue
            try:
                if candidate == "openai":
                    return self._openai(prompt, system=system, max_tokens=max_tokens)
                if candidate == "anthropic":
                    return self._anthropic(prompt, system=system, max_tokens=max_tokens)
                if candidate == "gemini":
                    return self._gemini(prompt, system=system, max_tokens=max_tokens)
            except Exception as exc:
                errors.append(f"{candidate}: {exc}")

        raise AiProviderError("No AI provider succeeded: " + " | ".join(errors))

    def _timeout(self) -> httpx.Timeout:
        return httpx.Timeout(float(self.settings.timeout_seconds), connect=20.0)

    def _openai(self, prompt: str, *, system: str | None, max_tokens: int) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.settings.openai_model,
            "input": prompt,
            "max_output_tokens": max_tokens,
            "store": False,
        }
        if system:
            body["instructions"] = system
        response = httpx.post(
            "https://api.openai.com/v1/responses",
            headers={
                "Authorization": f"Bearer {self.settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=self._timeout(),
        )
        data = self._json(response, "OpenAI")
        text = data.get("output_text")
        if not text:
            chunks: list[str] = []
            for item in data.get("output", []) or []:
                for content in item.get("content", []) or []:
                    if content.get("type") in {"output_text", "text"} and content.get("text"):
                        chunks.append(str(content["text"]))
            text = "\n".join(chunks)
        return {"provider": "openai", "model": self.settings.openai_model, "text": text or "", "raw": data}

    def _anthropic(self, prompt: str, *, system: str | None, max_tokens: int) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.settings.anthropic_model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            body["system"] = system
        response = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": str(self.settings.anthropic_api_key),
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=self._timeout(),
        )
        data = self._json(response, "Anthropic")
        chunks = [
            str(item.get("text"))
            for item in data.get("content", []) or []
            if item.get("type") == "text" and item.get("text")
        ]
        return {"provider": "anthropic", "model": self.settings.anthropic_model, "text": "\n".join(chunks), "raw": data}

    def _gemini(self, prompt: str, *, system: str | None, max_tokens: int) -> dict[str, Any]:
        body: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": max_tokens},
        }
        if system:
            body["system_instruction"] = {"parts": [{"text": system}]}
        model = str(self.settings.gemini_model).removeprefix("models/")
        response = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={
                "x-goog-api-key": str(self.settings.gemini_api_key),
                "Content-Type": "application/json",
            },
            json=body,
            timeout=self._timeout(),
        )
        data = self._json(response, "Gemini")
        chunks: list[str] = []
        for candidate in data.get("candidates", []) or []:
            for part in (candidate.get("content") or {}).get("parts", []) or []:
                if part.get("text"):
                    chunks.append(str(part["text"]))
        return {"provider": "gemini", "model": self.settings.gemini_model, "text": "\n".join(chunks), "raw": data}

    @staticmethod
    def _json(response: httpx.Response, provider: str) -> dict[str, Any]:
        try:
            data = response.json()
        except Exception:
            data = {"raw": response.text}
        if not response.is_success:
            raise AiProviderError(f"{provider} returned HTTP {response.status_code}: {str(data)[:2000]}")
        if not isinstance(data, dict):
            raise AiProviderError(f"{provider} returned an unexpected response.")
        return data
