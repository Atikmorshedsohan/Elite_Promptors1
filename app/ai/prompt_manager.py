"""Prompt registry. One builder per use case.

Add a new prompt by dropping a function in this file and registering it
under a stable name. Services consume prompts only by name.
"""
from __future__ import annotations

from typing import Callable

from .complaint_prompt import build_complaint_prompt
from .reply_prompt import build_reply_prompt
from .summary_prompt import build_summary_prompt

PromptBuilder = Callable[..., str]

_REGISTRY: dict[str, PromptBuilder] = {
    "complaint": build_complaint_prompt,
    "summary": build_summary_prompt,
    "reply": build_reply_prompt,
}


def get_prompt(name: str) -> PromptBuilder:
    if name not in _REGISTRY:
        raise KeyError(f"unknown prompt: {name!r}")
    return _REGISTRY[name]


def list_prompts() -> list[str]:
    return sorted(_REGISTRY.keys())