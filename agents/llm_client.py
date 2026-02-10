# agents/llm_client.py
"""Abstract LLM client + OpenAI / OpenRouter adapters. Swappable via ENV (LFAS_LLM_PROVIDER, *_API_KEY)."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


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


class OpenRouterLLMClient(LLMClient):
    """OpenRouter (openrouter.ai) — Claude и др. Модель задаётся как 'anthropic/claude-sonnet-4.5'."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self._api_key = api_key or settings.openrouter_api_key
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
        client = AsyncOpenAI(
            base_url=OPENROUTER_BASE_URL,
            api_key=self._api_key,
        )
        m = model or self._model
        logger.info("OpenRouter request: model=%s", m)
        resp = await client.chat.completions.create(
            model=m,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if not resp.choices:
            return ""
        return (resp.choices[0].message.content or "").strip()


def get_llm_client(provider: str | None = None) -> LLMClient:
    """Возвращает клиент LLM. Временно только OpenRouter (Claude)."""
    p = (provider or settings.lfas_llm_provider or "openrouter").strip().lower()
    if p == "openrouter":
        if not settings.openrouter_api_key:
            raise ValueError("OPENROUTER_API_KEY not set")
        return OpenRouterLLMClient()
    raise ValueError(f"Unknown LLM provider: {p}. Use openrouter.")
