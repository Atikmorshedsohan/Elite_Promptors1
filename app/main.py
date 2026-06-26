"""FastAPI application entry point.

Run locally with:

    uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

Or via the convenience script if one is added later.

Health check:    GET  /health
Main endpoint:   POST /analyze-ticket
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.config import get_settings
from app.utils.logger import get_logger

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Boot/shutdown hooks."""
    settings = get_settings()
    log.info(
        "service_starting",
        extra={
            "stage": "boot",
            "app_env": settings.app_env,
            "log_level": settings.log_level,
            "gemini_key_set": bool(settings.gemini_api_key),
        },
    )
    yield
    log.info("service_stopping", extra={"stage": "shutdown"})


def create_app() -> FastAPI:
    """Application factory — used by `uvicorn app.main:app` and tests."""
    settings = get_settings()

    app = FastAPI(
        title="bKash QueueStorm Investigator",
        version="1.0.0",
        description=(
            "Evidence-based complaint investigation for bKash mobile "
            "financial services. Returns a strict, typed verdict for "
            "every ticket — never guesses."
        ),
        lifespan=lifespan,
    )

    # CORS — judges may invoke from a browser-based harness.
    origins = (
        [o.strip() for o in settings.cors_origins.split(",")]
        if settings.cors_origins != "*"
        else ["*"]
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount the single router at /api/v1. The health endpoint stays at
    # the root for platform health probes.
    app.include_router(api_router, prefix="/api/v1")

    @app.get("/", tags=["meta"])
    def root() -> dict:
        return {
            "service": "ticket-investigator",
            "version": "1.0.0",
            "endpoints": {
                "health": "/api/v1/health",
                "analyze": "/api/v1/analyze-ticket",
            },
        }

    # Quiet down noisy third-party loggers unless explicitly enabled.
    if settings.log_level != "DEBUG":
        for noisy in ("httpx", "httpcore", "urllib3"):
            logging.getLogger(noisy).setLevel(logging.WARNING)

    return app


# `uvicorn app.main:app` resolves this.
app = create_app()


__all__ = ["app", "create_app"]