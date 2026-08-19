"""Pure cache-key construction; durable cache storage remains Rust-owned."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel


def _canonical(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _canonical(value.model_dump(mode="json"))
    if is_dataclass(value):
        return _canonical(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("cache-key datetimes must be timezone aware")
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, dict):
        return {
            str(key): _canonical(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    return value


def research_cache_key(
    *,
    provider: str,
    resolved_model: str,
    operation: str,
    prompt_version: str,
    schema_version: str,
    normalized_parameters: object,
    input_content_sha256: str,
    freshness_bucket: str,
    privacy_mode: str,
) -> str:
    if re.fullmatch(r"[0-9a-f]{64}", input_content_sha256) is None:
        raise ValueError("input_content_sha256 must be a SHA-256 hex digest")
    payload = {
        "provider": provider,
        "resolved_model": resolved_model,
        "operation": operation,
        "prompt_version": prompt_version,
        "schema_version": schema_version,
        "normalized_parameters": _canonical(normalized_parameters),
        "input_content_sha256": input_content_sha256,
        "freshness_bucket": freshness_bucket,
        "privacy_mode": privacy_mode,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
