"""Conservative provider JSON-Schema lowering shared by export and live adapters."""

from __future__ import annotations

from typing import Any


PROVIDER_DIALECTS = ("gemini", "openai", "xai")
_COMMON_OMITTED_KEYWORDS = frozenset({"default", "examples", "format", "title"})
# OpenAI Structured Outputs documents a deliberately small JSON-Schema subset.
# String length keywords are enforced again by the canonical Pydantic contract
# after generation, but they are not sent in the provider-facing schema.
_OPENAI_OMITTED_KEYWORDS = frozenset({"minLength", "maxLength"})


def lower_provider_schema(value: Any, dialect: str) -> Any:
    return _lower_provider_schema(value, dialect, property_map=False)


def _lower_provider_schema(value: Any, dialect: str, *, property_map: bool) -> Any:
    if dialect not in PROVIDER_DIALECTS:
        raise ValueError(f"unsupported provider schema dialect: {dialect}")
    if isinstance(value, list):
        return [
            _lower_provider_schema(item, dialect, property_map=False) for item in value
        ]
    if not isinstance(value, dict):
        return value
    omitted_keywords = _COMMON_OMITTED_KEYWORDS
    if dialect == "openai":
        omitted_keywords = omitted_keywords | _OPENAI_OMITTED_KEYWORDS
    lowered: dict[str, Any] = {}
    for key, item in value.items():
        # JSON Schema keywords such as ``title`` are omitted from schema
        # objects, but the same strings are valid domain property names.
        # Treating a ``properties`` map like a schema object silently removed
        # fields named ``title`` from strict provider schemas while canonical
        # validation still required them.
        if not property_map and key in omitted_keywords:
            continue
        lowered[key] = _lower_provider_schema(
            item,
            dialect,
            property_map=(not property_map and key == "properties"),
        )
    properties = lowered.get("properties")
    if not property_map and isinstance(properties, dict):
        lowered["additionalProperties"] = False
        lowered["required"] = list(properties)
    return lowered
