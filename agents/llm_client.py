# agents/llm_client.py
"""Abstract LLM client + OpenAI adapter. Swappable via ENV (OPENAI_API_KEY, LFAS_LLM_PROVIDER)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.config import settings


class LLMClient(ABC):
    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> str:
        """Return assistant text only."""
        ...


class OpenAILLMClient(LLMClient):
    def __init__(self, api_key: str | None = None, model: str | None = None):
        self._api_key = api_key or settings.openai_api_key
        self._model = model or settings.lfas_llm_model

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> str:
        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise RuntimeError("openai package not installed")
        client = AsyncOpenAI(api_key=self._api_key)
        m = model or self._model
        resp = await client.chat.completions.create(
            model=m,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if not resp.choices:
            return ""
        return (resp.choices[0].message.content or "").strip()


def get_llm_client() -> LLMClient:
    provider = (settings.lfas_llm_provider or "openai").lower()
    if provider == "openai":
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY not set")
        return OpenAILLMClient()
    raise ValueError(f"Unknown LLM provider: {provider}")
