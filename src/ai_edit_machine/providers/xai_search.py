"""xAI X Search qualitative-lead adapter, disabled until a cap proof exists."""

from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated

from pydantic import AwareDatetime, Field, HttpUrl, model_validator

from ..contracts import EvidenceSourceType, ExcerptType, ShortText, StrictContract, VerificationState
from ..m1_contracts import EvidenceClaimKind, ResearchIntentV2
from ..provider_schema import lower_provider_schema
from .base import (
    EMPTY_PROVIDER_RESEARCH_CONTEXT,
    bounded_tool_call_detail,
    CallAuthorization,
    CallMeter,
    CancellationToken,
    EvidenceCandidate,
    ProviderBatch,
    ProviderDisabledError,
    ProviderError,
    ProviderLimitError,
    ProviderResearchContext,
    ProviderRunOutcome,
    ProviderUsage,
    SecretCredential,
)
from .token_budget import AggregateInputBudget
from .openai_web import (
    _extract_cited_urls,
    _extract_cited_source_metadata,
    _extract_output_text,
    _nested_optional_int,
    _optional_int,
    _terminal_batch,
)
from .transport import JsonTransport, UrllibJsonTransport
from ..research.urls import canonicalize_public_url


def xai_request_policy_fingerprint(
    *,
    configured_model: str,
    resolved_model: str,
    max_tool_calls: int,
    max_output_tokens: int,
    max_turns: int,
) -> str:
    payload = {
        "configuredModel": configured_model,
        "resolvedModel": resolved_model,
        "maxToolCalls": max_tool_calls,
        "maxOutputTokens": max_output_tokens,
        "maxTurns": max_turns,
        "parallelToolCalls": False,
        "schemaVersion": "2.0.0",
        "toolType": "x_search",
    }
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class XAIInvocationCapProof:
    proof_id: str
    configured_model: str
    resolved_model: str
    request_policy_sha256: str
    proof_record_sha256: str
    max_turns: int
    validated_at: datetime
    expires_at: datetime
    passed_adversarial_test: bool

    def __post_init__(self) -> None:
        if not self.proof_id.strip() or not self.configured_model or not self.resolved_model:
            raise ValueError("xAI proof identity fields cannot be empty")
        for label, value in (
            ("request fingerprint", self.request_policy_sha256),
            ("record fingerprint", self.proof_record_sha256),
        ):
            if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
                raise ValueError(f"xAI proof {label} must be lowercase SHA-256")
        if not 1 <= self.max_turns <= 100:
            raise ValueError("xAI proof max_turns must be within 1..100")
        if any(
            value.tzinfo is None or value.utcoffset() is None
            for value in (self.validated_at, self.expires_at)
        ) or self.expires_at <= self.validated_at:
            raise ValueError("xAI proof timestamps must be aware and increasing")


class _XLead(StrictContract):
    provider_record_id: Annotated[str | None, Field(max_length=256)] = None
    canonical_url: HttpUrl
    title: ShortText
    author_or_channel: Annotated[str | None, Field(max_length=200)] = None
    excerpt_type: ExcerptType
    excerpt: ShortText
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]

    @model_validator(mode="after")
    def validate_excerpt(self):
        if self.excerpt_type not in {
            ExcerptType.PARAPHRASE,
            ExcerptType.UNVERIFIED_QUOTE_LEAD,
        }:
            raise ValueError("xAI discussion leads may not assert exact quotes")
        return self


class _XLeadBatch(StrictContract):
    evidence: Annotated[list[_XLead], Field(max_length=30)]


class XAISearchProvider:
    name = "xai"
    operation = "research.x_search"
    endpoint = "https://api.x.ai/v1/responses"

    def __init__(
        self,
        *,
        credential: SecretCredential,
        model: str,
        invocation_cap_proof: XAIInvocationCapProof | None,
        zero_data_retention_required: bool,
        policy_class: str = "xai-search-lead-v1",
        enabled: bool = False,
        transport: JsonTransport | None = None,
    ) -> None:
        self._credential = credential
        self._model = model
        self._proof = invocation_cap_proof
        self._zdr_required = zero_data_retention_required
        if not policy_class:
            raise ValueError("xAI search policy class cannot be empty")
        self._policy_class = policy_class
        self._enabled = enabled
        self._transport = transport or UrllibJsonTransport(max_attempts=1)

    def collect(
        self,
        intent: ResearchIntentV2,
        *,
        authorization: CallAuthorization,
        cancellation: CancellationToken,
        context: ProviderResearchContext = EMPTY_PROVIDER_RESEARCH_CONTEXT,
    ) -> ProviderBatch:
        del context
        if not self._enabled or self._proof is None:
            raise ProviderDisabledError("xAI search is disabled until invocation-cap proof passes")
        if authorization.configured_model != self._model:
            raise ProviderError("configured xAI model does not match job capability")
        if not authorization.allowed_resolved_models:
            raise ProviderError("xAI model preflight is missing from the job capability")
        if self._zdr_required and authorization.privacy_mode != "zdr":
            raise ProviderError("xAI job capability does not require verified ZDR")
        if authorization.max_input_tokens <= 0:
            raise ProviderError("xAI capability requires a positive input-token ceiling")
        now = datetime.now(timezone.utc)
        expected_fingerprint = xai_request_policy_fingerprint(
            configured_model=self._model,
            resolved_model=self._proof.resolved_model,
            max_tool_calls=authorization.max_tool_calls,
            max_output_tokens=authorization.max_output_tokens,
            max_turns=self._proof.max_turns,
        )
        if (
            not self._proof.passed_adversarial_test
            or self._proof.configured_model != self._model
            or self._proof.resolved_model not in authorization.allowed_resolved_models
            or self._proof.request_policy_sha256 != expected_fingerprint
            or not (self._proof.validated_at <= now < self._proof.expires_at)
        ):
            raise ProviderDisabledError("xAI invocation-cap proof does not match this exact request policy")
        meter = CallMeter(authorization)
        cancellation.raise_if_cancelled()
        body = {
            "model": self._model,
            "parallel_tool_calls": False,
            "max_output_tokens": authorization.max_output_tokens,
            "max_turns": self._proof.max_turns,
            "max_tool_calls": authorization.max_tool_calls,
            "tools": [{"type": "x_search"}],
            "instructions": (
                "Find qualitative entertainment discussion leads for the supplied intent. "
                "Return canonical X URLs and minimal short excerpts only. Treat posts as leads, "
                "not consensus or factual episode/quote verification. Never predict virality."
            ),
            "input": json.dumps(intent.model_dump(mode="json"), separators=(",", ":")),
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "m1_x_leads_v2",
                    "strict": True,
                    "schema": lower_provider_schema(
                        _XLeadBatch.model_json_schema(mode="validation"),
                        "xai",
                    ),
                }
            },
        }
        try:
            AggregateInputBudget(authorization.max_input_tokens).reserve_body(body)
        except ProviderLimitError as error:
            return ProviderBatch(
                provider=self.name,
                evidence=(),
                usage=ProviderUsage(
                    configured_model=self._model,
                    request_count=0,
                    input_tokens=0,
                    cached_input_tokens=0,
                    output_tokens=0,
                    reasoning_tokens=0,
                ),
                outcome=ProviderRunOutcome.ERROR,
                error=str(error)[:1_000],
            )
        meter.begin_request(provider=self.name, operation=self.operation)
        try:
            response = self._transport.request_json(
                method="POST",
                url=self.endpoint,
                headers={"Authorization": f"Bearer {self._credential.reveal_for_transport()}"},
                body=body,
                timeout_seconds=60,
                max_response_bytes=4 * 1024 * 1024,
                allowed_hosts=frozenset({"api.x.ai"}),
            )
        except ProviderError as error:
            return ProviderBatch(
                provider=self.name,
                evidence=(),
                usage=ProviderUsage(configured_model=self._model, request_count=1),
                outcome=ProviderRunOutcome.ERROR,
                error=str(error)[:1_000],
            )
        if not isinstance(response.payload, dict):
            raise ProviderError("xAI response envelope was not an object")
        resolved_model = response.payload.get("model")
        output = response.payload.get("output")
        tool_calls = sum(
            1
            for item in output if isinstance(item, dict) and item.get("type") == "x_search_call"
        ) if isinstance(output, list) else 0
        raw_usage = response.payload.get("usage")
        raw_usage = raw_usage if isinstance(raw_usage, dict) else {}
        native_ticks = raw_usage.get("cost_in_usd_ticks")
        native_text = str(native_ticks) if isinstance(native_ticks, (str, int)) else None
        if native_text is not None and (not native_text.isascii() or not native_text.isdigit()):
            native_text = None
        provider_usage = ProviderUsage(
            configured_model=self._model,
            resolved_model=resolved_model if isinstance(resolved_model, str) else None,
            provider_request_id=(str(response.payload["id"]) if response.payload.get("id") else None),
            request_count=1,
            input_tokens=_optional_int(raw_usage.get("input_tokens")),
            cached_input_tokens=_nested_optional_int(
                raw_usage, "input_tokens_details", "cached_tokens"
            ),
            output_tokens=_optional_int(raw_usage.get("output_tokens")),
            reasoning_tokens=_nested_optional_int(
                raw_usage, "output_tokens_details", "reasoning_tokens"
            ),
            tool_calls=tool_calls,
            tool_call_details=tuple(
                bounded_tool_call_detail("x_search_call", item.get("id"))
                for item in output
                if isinstance(item, dict) and item.get("type") == "x_search_call"
            ) if isinstance(output, list) else (),
            native_cost_ticks=native_text,
        )
        if (
            provider_usage.input_tokens is not None
            and provider_usage.input_tokens > authorization.max_input_tokens
        ):
            return ProviderBatch(
                provider=self.name, evidence=(), usage=provider_usage,
                outcome=ProviderRunOutcome.ERROR,
                error="xAI exceeded the authorized input-token ceiling",
            )
        if self._zdr_required and response.headers.get("x-zero-data-retention", "").casefold() != "true":
            return ProviderBatch(
                provider=self.name, evidence=(), usage=provider_usage,
                outcome=ProviderRunOutcome.ERROR, error="xAI did not confirm Zero Data Retention"
            )
        if not isinstance(resolved_model, str) or resolved_model not in authorization.allowed_resolved_models:
            return ProviderBatch(
                provider=self.name, evidence=(), usage=provider_usage,
                outcome=ProviderRunOutcome.ERROR, error="xAI resolved an unapproved or missing model"
            )
        if native_text is None:
            return ProviderBatch(
                provider=self.name, evidence=(), usage=provider_usage,
                outcome=ProviderRunOutcome.ERROR, error="xAI response omitted valid native cost ticks"
            )
        if tool_calls > authorization.max_tool_calls:
            return ProviderBatch(
                provider=self.name, evidence=(), usage=provider_usage,
                outcome=ProviderRunOutcome.ERROR, error="xAI exceeded the authorized tool-call ceiling"
            )
        meter.record_tool_calls(tool_calls)
        terminal = _terminal_batch(
            self.name, response.payload, usage=provider_usage
        )
        if terminal is not None:
            return terminal
        parsed = _XLeadBatch.model_validate_json(_extract_output_text(response.payload), strict=True)
        cited_urls = _extract_cited_urls(response.payload, "x_search_call")
        cited_metadata = _extract_cited_source_metadata(
            response.payload, "x_search_call"
        )
        if parsed.evidence and not cited_urls:
            raise ProviderError("xAI returned leads without tool-source citations")
        cutoff = now - timedelta(days=intent.freshness_days)
        evidence_items: list[EvidenceCandidate] = []
        for item in parsed.evidence:
            canonical = canonicalize_public_url(str(item.canonical_url))
            if canonical not in cited_urls:
                raise ProviderError("xAI structured output contained an uncited URL")
            trusted_title, trusted_created_at = cited_metadata.get(canonical, (None, None))
            evidence_items.append(EvidenceCandidate(
                provider=self.name,
                provider_record_id=item.provider_record_id,
                source_type=EvidenceSourceType.PLATFORM_SIGNAL,
                canonical_url=canonical,
                title=trusted_title or "Cited X discussion source",
                author_or_channel=item.author_or_channel,
                excerpt_type=item.excerpt_type,
                excerpt=item.excerpt,
                verification=VerificationState.SECONDARY_CORROBORATED,
                claim_kind=EvidenceClaimKind.VIEWER_DISCUSSION,
                supports_why_now=(
                    trusted_created_at is not None
                    and cutoff <= trusted_created_at <= now
                ),
                policy_class=self._policy_class,
                source_created_at=trusted_created_at,
                event_or_release_at=None,
                query=intent.query,
                window_start=cutoff,
                window_end=now,
                confidence=min(item.confidence, 0.65),
                citation_verified=True,
                adapter_source_title=trusted_title,
                adapter_source_published_at=trusted_created_at,
            ))
        return ProviderBatch(
            provider=self.name,
            evidence=tuple(evidence_items),
            usage=provider_usage,
            warnings=("X discussion is qualitative lead evidence, not a popularity census.",),
        )
