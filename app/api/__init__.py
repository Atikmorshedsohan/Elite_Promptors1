"""FastAPI router aggregation.

`api_router` is the single object `main.py` mounts at /api/v1.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.api.health import router as health_router
from app.api.routes import router as analyze_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(analyze_router)

__all__ = ["api_router"]
