"""Base protocol and result contract for LLM providers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from pydantic import BaseModel


@dataclass(frozen=True)
class ProviderResult:
    """Raw text, model identifier, and token counts returned by an LLM provider."""

    raw_text: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0


@runtime_checkable
class LLMProvider(Protocol):
    """Interface implemented by all concrete LLM provider adapters."""

    @property
    def name(self) -> str:
        """Short identifier for this provider (e.g. 'mock', 'gemini')."""
        ...

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
        """Execute one raw completion targeting ``response_model`` JSON output."""
        ...
