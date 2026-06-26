"""Application configuration loaded from environment variables.

Centralized, typed configuration. No business logic here.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Override via environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- LLM ---
    gemini_api_key: str = Field(default="", description="Google Gemini API key")
    gemini_model: str = Field(default="gemini-1.5-flash")
    llm_timeout_seconds: float = Field(default=15.0, gt=0)
    llm_max_retries: int = Field(default=1, ge=0)

    # --- Latency budget ---
    analyze_max_seconds: float = Field(default=28.0, gt=0)
    health_max_seconds: float = Field(default=60.0, gt=0)

    # --- Evidence thresholds ---
    amount_tolerance_pct: float = Field(default=0.02, ge=0.0, le=0.5)
    date_window_days: int = Field(default=3, ge=0, le=30)
    high_value_threshold_taka: float = Field(default=10000.0, gt=0)
    critical_value_threshold_taka: float = Field(default=50000.0, gt=0)
    tie_score_delta: float = Field(default=0.05, ge=0.0, le=0.5)
    min_confidence_threshold: float = Field(default=0.6, ge=0.0, le=1.0)

    # --- Server ---
    app_env: Literal["development", "staging", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    cors_origins: str = Field(default="*")

    # --- Networking ---
    server_host: str = Field(default="127.0.0.1", min_length=1)
    server_port: int = Field(default=8080, ge=1, le=65535)
    server_auto_port: bool = Field(
        default=True,
        description=(
            "If True, fall back to a free port automatically when the "
            "configured port is unavailable (handles WinError 10013 "
            "and stale-process clashes on Windows)."
        ),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor."""
    return Settings()