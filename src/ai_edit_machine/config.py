"""Centralized non-secret defaults and explicitly development-only overrides.

Production authorization for a paid call will arrive as an immutable, per-job
capability from the trusted Rust host. Environment variables can never grant it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


def _environment_text(name: str, default: str) -> str:
    value = os.environ.get(name, default).strip()
    if not value:
        raise ValueError(f"{name} cannot be empty")
    return value


def _environment_decimal(name: str, default: str) -> Decimal:
    raw = os.environ.get(name, default).strip()
    try:
        value = Decimal(raw)
    except InvalidOperation as error:
        raise ValueError(f"{name} must be a decimal amount") from error
    if value < 0:
        raise ValueError(f"{name} cannot be negative")
    return value


def _environment_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")


@dataclass(frozen=True, slots=True)
class ModelDefaults:
    trend_research: str
    trend_research_fallback: str
    video_reasoning: str
    video_reasoning_fallback: str
    web_verifier: str
    rough_cut_critic: str | None


@dataclass(frozen=True, slots=True)
class RuntimeSettings:
    protocol_version: str
    development_live_calls_enabled: bool
    research_hard_limit_usd: Decimal
    project_hard_limit_usd: Decimal
    price_catalog_max_age_days: int
    models: ModelDefaults

    @classmethod
    def production_defaults(cls) -> "RuntimeSettings":
        """Return safe seeds without reading the process environment."""

        return cls(
            protocol_version="1.0.0",
            development_live_calls_enabled=False,
            research_hard_limit_usd=Decimal("0.50"),
            project_hard_limit_usd=Decimal("2.00"),
            price_catalog_max_age_days=7,
            models=ModelDefaults(
                trend_research="grok-4.6",
                trend_research_fallback="grok-4.3",
                video_reasoning="gemini-3.7-flash",
                video_reasoning_fallback="gemini-3.6-flash",
                web_verifier="gpt-5.6-luna",
                rough_cut_critic=None,
            ),
        )

    @classmethod
    def development_from_environment(cls) -> "RuntimeSettings":
        """Load a local developer/test profile; never call this in a release worker."""

        critic = os.environ.get("AI_EDIT_ROUGH_CUT_CRITIC_MODEL", "").strip() or None
        return cls(
            protocol_version="1.0.0",
            development_live_calls_enabled=_environment_bool(
                "AI_EDIT_LIVE_CALLS", False
            ),
            research_hard_limit_usd=_environment_decimal(
                "AI_EDIT_RESEARCH_HARD_LIMIT_USD", "0.50"
            ),
            project_hard_limit_usd=_environment_decimal(
                "AI_EDIT_PROJECT_HARD_LIMIT_USD", "2.00"
            ),
            price_catalog_max_age_days=7,
            models=ModelDefaults(
                trend_research=_environment_text(
                    "AI_EDIT_TREND_MODEL", "grok-4.6"
                ),
                trend_research_fallback=_environment_text(
                    "AI_EDIT_TREND_FALLBACK_MODEL", "grok-4.3"
                ),
                video_reasoning=_environment_text(
                    "AI_EDIT_VIDEO_MODEL", "gemini-3.7-flash"
                ),
                video_reasoning_fallback=_environment_text(
                    "AI_EDIT_VIDEO_FALLBACK_MODEL", "gemini-3.6-flash"
                ),
                web_verifier=_environment_text(
                    "AI_EDIT_WEB_VERIFIER_MODEL", "gpt-5.6-luna"
                ),
                rough_cut_critic=critic,
            ),
        )
