"""Async Google Gemini LLM provider using the google-genai SDK."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from llm.providers.base import ProviderResult


class GeminiProvider:
    """Google Gemini structured-output provider wrapping google.genai async APIs."""

    def __init__(
        self,
        *,
        api_key: str,
        default_model: str = "gemini-2.5-flash",
        client: Any | None = None,
    ) -> None:
        self._api_key = api_key
        self._default_model = default_model
        self._client: Any | None = client

    @property
    def name(self) -> str:
        return "gemini"

    @property
    def default_model(self) -> str:
        return self._default_model

    def _get_client(self) -> Any:
        if self._client is None:
            if not self._api_key.strip():
                raise RuntimeError("GEMINI_API_KEY is required for GeminiProvider")
            from google import genai

            self._client = genai.Client(api_key=self._api_key)
        return self._client

    async def generate_raw(
        self,
        *,
        prompt: str,
        response_model: type[BaseModel],
        system_instruction: str | None = None,
        model_override: str | None = None,
        temperature: float = 0.2,
        seed: int | None = None,
    ) -> ProviderResult:
        from google.genai import types

        client = self._get_client()
        target_model = model_override or self._default_model
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=response_model,
            temperature=temperature,
            seed=seed,
        )
        response = await client.aio.models.generate_content(
            model=target_model,
            contents=prompt,
            config=config,
        )
        usage = getattr(response, "usage_metadata", None)
        tokens_in = int(getattr(usage, "prompt_token_count", 0) or 0)
        tokens_out = int(getattr(usage, "candidates_token_count", 0) or 0)
        raw_text = str(getattr(response, "text", "") or "")
        return ProviderResult(
            raw_text=raw_text,
            model=target_model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )
