"""FastAPI dependency providers.

A single `get_pipeline()` is the composition root for the request
lifecycle. FastAPI caches it per-request via the default dependency
cache.
"""
from __future__ import annotations

from functools import lru_cache

from app.ai.llm_client import LLMClient, build_default_llm
from app.services.investigation_service import InvestigationPipeline


@lru_cache(maxsize=1)
def get_llm() -> LLMClient:
    """Cached LLM client. Same instance reused across requests."""
    return build_default_llm()


@lru_cache(maxsize=1)
def get_pipeline() -> InvestigationPipeline:
    """Cached pipeline. Same instance reused across requests.

    Caching is safe because InvestigationPipeline is stateless across
    calls — every service it owns is also stateless.
    """
    return InvestigationPipeline(llm=get_llm())


__all__ = ["get_llm", "get_pipeline"]
