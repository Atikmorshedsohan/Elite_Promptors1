"""LLM client wrapper.

Single entry point: `LLMClient.safe_generate(prompt) -> str`. Always returns
a string; on timeout/error it returns a safe fallback so the pipeline never
crashes. The provider is configured via `GEMINI_API_KEY` and `GEMINI_MODEL`.
"""
from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from typing import Any

from ..config import get_settings
from ..utils.logger import get_logger

log = get_logger(__name__)


class LLMClient(ABC):
    """Interface — swap providers without changing services."""

    @abstractmethod
    def safe_generate(self, prompt: str, *, expect_json: bool = False) -> str:
        """Generate text from a prompt. Never raise; return safe fallback."""


class GeminiClient(LLMClient):
    """Google Gemini implementation with timeout, retry, and fallback."""

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        settings = get_settings()
        self._api_key = api_key or settings.gemini_api_key
        self._model_name = model or settings.gemini_model
        self._timeout = settings.llm_timeout_seconds
        self._max_retries = settings.llm_max_retries
        self._model: Any | None = None
        if self._api_key:
            self._init_model()

    def _init_model(self) -> None:
        try:
            import google.generativeai as genai  # type: ignore
            genai.configure(api_key=self._api_key)
            self._model = genai.GenerativeModel(self._model_name)
        except Exception as exc:  # pragma: no cover - import/runtime guard
            log.warning("gemini_init_failed", extra={"stage": "llm_init"})
            self._model = None

    def safe_generate(self, prompt: str, *, expect_json: bool = False) -> str:
        if not self._model:
            log.warning("llm_unavailable", extra={"stage": "llm_generate"})
            return "" if not expect_json else "{}"
        attempt = 0
        last_exc: Exception | None = None
        while attempt <= self._max_retries:
            attempt += 1
            start = time.perf_counter()
            try:
                # Gemini has no native timeout arg; we wrap the call in a thread
                # via the genai SDK's built-in `request_options` if available.
                resp = self._model.generate_content(
                    prompt,
                    request_options={"timeout": self._timeout},
                )
                text = (getattr(resp, "text", "") or "").strip()
                duration_ms = int((time.perf_counter() - start) * 1000)
                log.info(
                    "llm_generate_ok",
                    extra={"stage": "llm_generate", "duration_ms": duration_ms},
                )
                if expect_json:
                    return self._coerce_json(text)
                return text
            except Exception as exc:
                last_exc = exc
                duration_ms = int((time.perf_counter() - start) * 1000)
                log.warning(
                    "llm_generate_failed",
                    extra={
                        "stage": "llm_generate",
                        "duration_ms": duration_ms,
                        "attempt": attempt,
                    },
                )
        log.error("llm_generate_giving_up", extra={"stage": "llm_generate"})
        return "" if not expect_json else "{}"

    @staticmethod
    def _coerce_json(text: str) -> str:
        """Best-effort extract of a JSON object from LLM output."""
        if not text:
            return "{}"
        # Strip code fences.
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
        # First { ... last }
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = text[start : end + 1]
            try:
                json.loads(candidate)
                return candidate
            except json.JSONDecodeError:
                pass
        return "{}"


class StubLLMClient(LLMClient):
    """Deterministic stub used in tests / when no API key is set."""

    def safe_generate(self, prompt: str, *, expect_json: bool = False) -> str:
        if expect_json:
            return '{"intent": "unknown", "confidence": 0.0}'
        return ""


def build_default_llm() -> LLMClient:
    """Factory used by FastAPI dependencies."""
    settings = get_settings()
    if not settings.gemini_api_key:
        log.warning("no_gemini_key_using_stub", extra={"stage": "llm_init"})
        return StubLLMClient()
    return GeminiClient()