"""Persistent strict-JSONL M1 worker supervised by the trusted Rust host.

The worker deliberately has no environment, credential-store, SQLite, file, or
budget authority.  Every live adapter is constructed from one immutable
capability carried on ``research.execute`` and all actual usage is returned for
Rust reconciliation.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Annotated, Callable, Literal, Self
from urllib.parse import quote
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, UUID4, field_validator, model_validator

from .contracts import (
    EvidenceSourceType,
    ExcerptType,
    MediaKind,
    SpoilerPolicy,
    VerificationState,
)
from .m1_contracts import (
    EpisodeLocatorFactV2,
    EvidenceClaimKind,
    EvidenceClaimRecordV2,
    EvidenceSourceRecordV2,
    ResearchIntentV2,
    ResearchSynthesisDraftV2,
)
from .providers.base import (
    CallAuthorization,
    CancellationToken,
    EvidenceCandidate,
    ProviderBatch,
    ProviderCancelledError,
    ProviderError,
    ProviderRunOutcome,
    ProviderResearchContext,
    ProviderUsage,
    SecretCredential,
)
from .providers.fake import FakeResearchProvider
from .providers.openai_synthesis import OpenAIResearchSynthesizer
from .providers.openai_web import OpenAIWebVerifier
from .providers.transport import JsonResponse, JsonTransport, UrllibJsonTransport
from .providers.tvmaze import TVmazeProvider
from .providers.xai_search import XAIInvocationCapProof, XAISearchProvider
from .providers.youtube import YouTubeOfficialProvider
from .provider_debug_contract import (
    DEBUG_ENDPOINT,
    DEBUG_HARD_CAP_MICRO_USD,
    DEBUG_MAX_INPUT_TOKENS,
    DEBUG_MAX_OUTPUT_TOKENS,
    DEBUG_MAX_REQUESTS,
    DEBUG_MAX_TOOL_CALLS,
    DEBUG_MODE,
    DEBUG_MODEL,
    DEBUG_PROMPT,
    DEBUG_PROVIDER,
    DEBUG_RESERVED_MICRO_USD,
    DEBUG_SEED_EPISODE,
    DEBUG_SEED_EPISODE_TITLE,
    DEBUG_SEED_EVENT_AT,
    DEBUG_SEED_PROVIDER_RECORD_ID,
    DEBUG_SEED_SEASON,
    DEBUG_SEED_SHOW,
    DEBUG_SEED_URL,
)
from .research.intent import intent_from_query
from .research.policy import PolicyRule
from .research.synthesis import SynthesisProviderResult
from .research.workflow import ProviderPlan, ResearchWorkflow, ResearchWorkflowOutput
from .worker_protocol import (
    PROTOCOL_VERSION,
    WorkerProtocolError,
    hello_frame,
    read_json_frame,
    write_json_frame,
)


PAYLOAD_SCHEMA_VERSION = "1.0.0"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class _OneShotOpenAIDebugTransport:
    """Development-only guard that can delegate exactly one paid HTTP POST."""

    def __init__(self, transport: JsonTransport) -> None:
        self._transport = transport
        self._post_started = False

    def request_json(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        body: object | None,
        timeout_seconds: float,
        max_response_bytes: int,
        allowed_hosts: frozenset[str],
    ) -> JsonResponse:
        if method.upper() != "POST" or url != DEBUG_ENDPOINT:
            raise ProviderError(
                "development-only M1 probe blocked a request outside its fixed OpenAI POST"
            )
        if self._post_started:
            raise ProviderError(
                "development-only M1 probe blocked a second OpenAI POST"
            )
        # Consume the one-shot before network activity. A timeout or unknown
        # transport outcome must never make a retry possible in this process.
        self._post_started = True
        return self._transport.request_json(
            method=method,
            url=url,
            headers=headers,
            body=body,
            timeout_seconds=timeout_seconds,
            max_response_bytes=max_response_bytes,
            allowed_hosts=allowed_hosts,
        )
_BARE_HOST = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)


def _to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(item[:1].upper() + item[1:] for item in tail)


def _snake_case(value: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", value).casefold()


def _snake_keys(value: object) -> object:
    if isinstance(value, dict):
        return {_snake_case(str(key)): _snake_keys(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_snake_keys(item) for item in value]
    return value


class _WireModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=False,
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
    )


class _IntentInput(_WireModel):
    schema_version: Literal["2.0.0"]
    prompt: Annotated[str, Field(min_length=1, max_length=4_000)]
    media_kinds: Annotated[list[MediaKind] | None, Field(min_length=1, max_length=5)]
    region: Annotated[str | None, Field(min_length=2, max_length=16)]
    freshness_days: Annotated[int | None, Field(ge=1, le=90)]
    spoiler_policy: SpoilerPolicy | None
    exclusions: Annotated[list[str] | None, Field(max_length=30)]
    max_results: Annotated[int | None, Field(ge=1, le=10)]

    @model_validator(mode="after")
    def validate_unique_values(self) -> Self:
        for values in (self.media_kinds, self.exclusions):
            if values is not None:
                normalized = [str(value).casefold() for value in values]
                if len(normalized) != len(set(normalized)):
                    raise ValueError("intent override lists must be unique")
        return self


class _PreviewPayload(_WireModel):
    schema_version: Literal["1.0.0"]
    intent: _IntentInput
    input_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    now_unix_ms: Annotated[int, Field(gt=0)]


class _TVmazeConfig(_WireModel):
    kind: Literal["TVMAZE"]


class _OpenAIWebConfig(_WireModel):
    kind: Literal["OPENAI_WEB"]
    registry_version: Annotated[str, Field(min_length=1, max_length=128)]
    official_hosts: Annotated[list[str], Field(max_length=256)]
    search_context_size: Literal["low"]
    request_body_max_input_tokens: Annotated[int, Field(ge=1, le=1_000_000)]
    request_max_tool_calls: Annotated[int, Field(ge=1, le=1_000)]

    @model_validator(mode="after")
    def validate_registry(self) -> Self:
        if len(self.official_hosts) != len(set(self.official_hosts)) or any(
            value != value.casefold() or _BARE_HOST.fullmatch(value) is None
            for value in self.official_hosts
        ):
            raise ValueError("official hosts must be unique lowercase bare DNS names")
        return self


class _OpenAISynthesisConfig(_WireModel):
    kind: Literal["OPENAI_SYNTHESIS"]


class _YouTubeConfig(_WireModel):
    kind: Literal["YOUTUBE_OFFICIAL_CHANNELS"]
    registry_version: Annotated[str, Field(min_length=1, max_length=128)]
    official_channel_ids: Annotated[list[str], Field(min_length=1, max_length=64)]
    official_hosts: Annotated[list[str], Field(max_length=256)]

    @model_validator(mode="after")
    def validate_registry(self) -> Self:
        if len(self.official_channel_ids) != len(set(self.official_channel_ids)):
            raise ValueError("official channel IDs must be unique")
        if any(not value or len(value) > 128 for value in self.official_channel_ids):
            raise ValueError("official channel ID is empty or oversized")
        if len(self.official_hosts) != len(set(self.official_hosts)) or any(
            value != value.casefold() or _BARE_HOST.fullmatch(value) is None
            for value in self.official_hosts
        ):
            raise ValueError("official hosts must be unique lowercase bare DNS names")
        return self


class _XAIConfig(_WireModel):
    kind: Literal["XAI_SEARCH"]
    adversarial_proof_id: UUID4
    proof_record_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    request_policy_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    proof_checked_at_unix_ms: Annotated[int, Field(gt=0)]
    proof_expires_at_unix_ms: Annotated[int, Field(gt=0)]
    max_turns: Annotated[int, Field(ge=1, le=100)]

    @model_validator(mode="after")
    def validate_window(self) -> Self:
        if self.proof_expires_at_unix_ms <= self.proof_checked_at_unix_ms:
            raise ValueError("xAI proof expiry must follow its checked time")
        return self


_ProviderConfig = Annotated[
    _TVmazeConfig
    | _OpenAIWebConfig
    | _OpenAISynthesisConfig
    | _YouTubeConfig
    | _XAIConfig,
    Field(discriminator="kind"),
]


class _Capability(_WireModel):
    provider_run_id: UUID4
    reservation_id: UUID4
    planned_call_id: UUID4
    provider: Annotated[str, Field(min_length=1, max_length=64)]
    operation: Annotated[str, Field(min_length=1, max_length=128)]
    configured_model: Annotated[str | None, Field(max_length=256)]
    resolved_model: Annotated[str | None, Field(max_length=256)]
    maximum_micro_usd: Annotated[int, Field(ge=0)]
    max_requests: Annotated[int, Field(ge=0, le=10_000)]
    max_tool_calls: Annotated[int, Field(ge=0, le=10_000)]
    max_input_tokens: Annotated[int, Field(ge=0, le=100_000_000)]
    max_output_tokens: Annotated[int, Field(ge=0, le=10_000_000)]
    allow_one_repair: bool
    retention_mode: Annotated[str, Field(min_length=1, max_length=1_000)]
    data_use_mode: Annotated[str, Field(min_length=1, max_length=1_000)]
    no_storage_mode: Annotated[str, Field(min_length=1, max_length=1_000)]
    privacy_mode: Annotated[str, Field(min_length=1, max_length=128)]
    policy_class: Annotated[str, Field(min_length=1, max_length=128)]
    evidence_ttl_seconds: Annotated[int, Field(gt=0, le=315_360_000)]
    refresh_after_seconds: Annotated[int, Field(gt=0, le=315_360_000)]
    purge_after_seconds: Annotated[int, Field(gt=0, le=315_360_000)]
    deletion_after_seconds: Annotated[int | None, Field(gt=0, le=315_360_000)]
    credential: Annotated[str | None, Field(max_length=16_384)]
    provider_config: _ProviderConfig

    @model_validator(mode="after")
    def validate_operation_binding(self) -> Self:
        expected = {
            "TVMAZE": ("tvmaze", "research.metadata", False),
            "OPENAI_WEB": ("openai", "research.web_verify", True),
            "OPENAI_SYNTHESIS": ("openai", "research.synthesize", True),
            "YOUTUBE_OFFICIAL_CHANNELS": ("youtube", "research.youtube", True),
            "XAI_SEARCH": ("xai", "research.x_search", True),
        }[self.provider_config.kind]
        if (self.provider, self.operation) != expected[:2]:
            raise ValueError("provider configuration does not match the capability operation")
        if expected[2] and not self.credential:
            raise ValueError("live provider capability is missing its explicit credential")
        if not expected[2] and self.credential is not None:
            raise ValueError("credential-free provider capability must not carry a credential")
        if self.configured_model is None and self.provider in {"openai", "xai"}:
            raise ValueError("paid model capability is missing configured model")
        if self.resolved_model is None and self.provider in {"openai", "xai"}:
            raise ValueError("paid model capability is missing resolved preflight model")
        if self.provider in {"openai", "xai"} and self.maximum_micro_usd <= 0:
            raise ValueError("paid provider capability requires a positive reservation")
        if self.provider in {"openai", "xai"} and (
            self.max_requests <= 0
            or self.max_input_tokens <= 0
            or self.max_output_tokens <= 0
        ):
            raise ValueError(
                "paid provider capability requires positive request/input/output ceilings"
            )
        if self.provider in {"tvmaze", "youtube"} and self.max_input_tokens != 0:
            raise ValueError("non-token provider capability must use a zero input-token ceiling")
        expected_privacy = {
            "tvmaze": "public_metadata",
            "openai": "store_false",
            "youtube": "official_metadata_only",
            "xai": "zdr",
        }[self.provider]
        if self.privacy_mode != expected_privacy:
            raise ValueError("provider capability has an unsupported privacy mode")
        if self.evidence_ttl_seconds > self.purge_after_seconds or (
            self.deletion_after_seconds is not None
            and self.deletion_after_seconds < self.evidence_ttl_seconds
        ):
            raise ValueError("provider evidence deadlines are internally inconsistent")
        return self


class _ProviderDebugSeed(_WireModel):
    show_or_title: Annotated[str, Field(min_length=1, max_length=500)]
    season_number: Annotated[int, Field(ge=1, le=10_000)]
    episode_number: Annotated[int, Field(ge=1, le=10_000)]
    episode_title: Annotated[str, Field(min_length=1, max_length=500)]
    event_or_release_at: datetime
    canonical_url: Annotated[str, Field(min_length=1, max_length=2_048)]
    provider_record_id: Annotated[str, Field(min_length=1, max_length=512)]

    @model_validator(mode="after")
    def validate_time(self) -> Self:
        if (
            self.event_or_release_at.tzinfo is None
            or self.event_or_release_at.utcoffset() is None
        ):
            raise ValueError("provider-debug seed timestamp must be timezone aware")
        return self


class _DevelopmentDebug(_WireModel):
    schema_version: Literal["1.0.0"]
    mode: Literal[DEBUG_MODE]
    trace_id: UUID4
    seed: _ProviderDebugSeed


class _ExecutePayload(_WireModel):
    schema_version: Literal["1.0.0"]
    job_id: UUID4
    research_run_id: UUID4
    input_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    intent: _IntentInput
    normalized_intent: dict[str, object]
    capabilities: Annotated[list[_Capability], Field(min_length=1, max_length=20)]
    reusable_evidence_sources: Annotated[
        list[EvidenceSourceRecordV2], Field(default_factory=list, max_length=64)
    ]
    reusable_evidence_claims: Annotated[
        list[EvidenceClaimRecordV2], Field(default_factory=list, max_length=128)
    ]
    generated_at: Annotated[
        str,
        Field(
            pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$"
        ),
    ]
    development_debug: _DevelopmentDebug | None = None

    @field_validator("reusable_evidence_sources", mode="before")
    @classmethod
    def decode_canonical_sources(cls, value: object) -> object:
        # Rust persists and transports canonical contracts with camelCase wire
        # keys, while the provider-independent Pydantic domain models use
        # snake_case field names.  Convert only the bounded reusable-evidence
        # records before their strict nested validation.  Without this bridge,
        # a valid non-empty cache payload terminates the packaged worker at the
        # protocol boundary before any provider starts.
        if not isinstance(value, list):
            return value
        return [
            EvidenceSourceRecordV2.model_validate_json(
                json.dumps(_snake_keys(item), ensure_ascii=False, separators=(",", ":")),
                strict=True,
            )
            for item in value
        ]

    @field_validator("reusable_evidence_claims", mode="before")
    @classmethod
    def decode_canonical_claims(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        return [
            EvidenceClaimRecordV2.model_validate_json(
                json.dumps(_snake_keys(item), ensure_ascii=False, separators=(",", ":")),
                strict=True,
            )
            for item in value
        ]

    @model_validator(mode="after")
    def validate_capability_ids(self) -> Self:
        provider_runs = [item.provider_run_id for item in self.capabilities]
        reservations = [item.reservation_id for item in self.capabilities]
        planned = [item.planned_call_id for item in self.capabilities]
        operations = [(item.provider, item.operation) for item in self.capabilities]
        if len(provider_runs) != len(set(provider_runs)):
            raise ValueError("provider-run IDs must be unique")
        if len(reservations) != len(set(reservations)):
            raise ValueError("reservation IDs must be unique")
        if len(planned) != len(set(planned)):
            raise ValueError("planned-call IDs must be unique")
        source_ids = [item.source_id for item in self.reusable_evidence_sources]
        claim_ids = [item.claim_id for item in self.reusable_evidence_claims]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("reusable evidence source IDs must be unique")
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("reusable evidence claim IDs must be unique")
        known_sources = set(source_ids)
        if any(item.source_id not in known_sources for item in self.reusable_evidence_claims):
            raise ValueError("reusable evidence claim lost its source")
        claimed_sources = {item.source_id for item in self.reusable_evidence_claims}
        if any(source_id not in claimed_sources for source_id in source_ids):
            raise ValueError("reusable evidence source has no claim")
        if len(operations) != len(set(operations)):
            raise ValueError("provider operations must be unique within a job")
        synthesis_count = sum(
            item.operation == "research.synthesize" for item in self.capabilities
        )
        if (
            synthesis_count != 1
            and not _is_verifier_only_diagnostic(self)
            and not _is_m1_provider_debug(self)
        ):
            raise ValueError("research execution requires exactly one synthesis capability")
        return self


class _CancelPayload(_WireModel):
    schema_version: Literal["1.0.0"]
    job_id: UUID4


class _ShutdownPayload(_WireModel):
    schema_version: Literal["1.0.0"]
    reason: Annotated[str, Field(min_length=1, max_length=1_000)]


def _is_verifier_only_diagnostic(payload: _ExecutePayload) -> bool:
    """Recognize the one deliberately narrow, Rust-reserved M1 diagnostic."""

    if len(payload.capabilities) != 2:
        return False
    metadata, capability = payload.capabilities
    return (
        isinstance(metadata.provider_config, _TVmazeConfig)
        and metadata.provider == "tvmaze"
        and metadata.operation == "research.metadata"
        and metadata.maximum_micro_usd == 0
        and metadata.max_requests == 16
        and metadata.max_tool_calls == 0
        and metadata.max_input_tokens == 0
        and metadata.max_output_tokens == 0
        and metadata.allow_one_repair is False
        and isinstance(capability.provider_config, _OpenAIWebConfig)
        and capability.provider == "openai"
        and capability.operation == "research.web_verify"
        and capability.maximum_micro_usd == 91_200
        and capability.max_requests == 6
        and capability.max_tool_calls == 6
        and capability.max_input_tokens == 120_000
        and capability.max_output_tokens == 6_000
        and capability.allow_one_repair is False
    )


def _is_m1_provider_debug(payload: _ExecutePayload) -> bool:
    """Recognize only the fixed, one-shot, Rust-reserved development probe."""

    debug = payload.development_debug
    if debug is None or len(payload.capabilities) != 1:
        return False
    capability = payload.capabilities[0]
    config = capability.provider_config
    seed = debug.seed
    try:
        expected_event = datetime.fromisoformat(
            DEBUG_SEED_EVENT_AT.replace("Z", "+00:00")
        )
    except ValueError:
        return False
    return (
        payload.intent.prompt == DEBUG_PROMPT
        and payload.intent.media_kinds == [MediaKind.TV_EPISODE]
        and payload.intent.region == "US"
        and payload.intent.freshness_days == 14
        and payload.intent.spoiler_policy is SpoilerPolicy.CURRENT_EPISODE
        and payload.intent.exclusions == []
        and payload.intent.max_results == 5
        and not payload.reusable_evidence_sources
        and not payload.reusable_evidence_claims
        and isinstance(config, _OpenAIWebConfig)
        and capability.provider == DEBUG_PROVIDER
        and capability.operation == "research.web_verify"
        and capability.configured_model == DEBUG_MODEL
        and capability.resolved_model == DEBUG_MODEL
        and capability.maximum_micro_usd == DEBUG_RESERVED_MICRO_USD
        and capability.maximum_micro_usd <= DEBUG_HARD_CAP_MICRO_USD
        and capability.max_requests == DEBUG_MAX_REQUESTS
        and capability.max_tool_calls == DEBUG_MAX_TOOL_CALLS
        and capability.max_input_tokens == DEBUG_MAX_INPUT_TOKENS
        and capability.max_output_tokens == DEBUG_MAX_OUTPUT_TOKENS
        and capability.allow_one_repair is False
        and config.search_context_size == "low"
        and config.request_max_tool_calls == DEBUG_MAX_TOOL_CALLS
        and config.request_body_max_input_tokens <= DEBUG_MAX_INPUT_TOKENS
        and seed.show_or_title == DEBUG_SEED_SHOW
        and seed.season_number == DEBUG_SEED_SEASON
        and seed.episode_number == DEBUG_SEED_EPISODE
        and seed.episode_title == DEBUG_SEED_EPISODE_TITLE
        and seed.event_or_release_at.astimezone(timezone.utc) == expected_event
        and seed.canonical_url == DEBUG_SEED_URL
        and seed.provider_record_id == DEBUG_SEED_PROVIDER_RECORD_ID
    )


class _PreflightPayload(_WireModel):
    schema_version: Literal["1.0.0"]
    provider: Annotated[str, Field(min_length=1, max_length=64)]
    configured_model: Annotated[str | None, Field(max_length=256)]
    credential: Annotated[str | None, Field(max_length=16_384)]


class _ProviderStartedAck(_WireModel):
    schema_version: Literal["1.0.0"]
    job_id: UUID4
    provider_run_id: UUID4
    planned_call_id: UUID4


class _Envelope(_WireModel):
    protocol_version: Literal["1.0.0"]
    request_id: UUID4
    message_type: Annotated[str, Field(min_length=1, max_length=128)]
    payload: dict[str, object]


def _validate_wire(model: type[_WireModel], value: object) -> _WireModel:
    # model_validate_json retains strict JSON-origin conversions for UUIDs and
    # datetimes while still refusing Python coercions and unknown fields.
    return model.model_validate_json(
        json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    )


def _camel_keys(value: object) -> object:
    if isinstance(value, dict):
        return {_to_camel(str(key)): _camel_keys(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_camel_keys(item) for item in value]
    return value


def _domain_intent(value: dict[str, object]) -> ResearchIntentV2:
    return ResearchIntentV2.model_validate_json(
        json.dumps(_snake_keys(value), ensure_ascii=False, separators=(",", ":")),
        strict=True,
    )


def _normalize_intent(value: _IntentInput) -> ResearchIntentV2:
    local = intent_from_query(value.prompt, region=value.region or "US")
    exclusions: list[str] = list(local.exclusions)
    for item in value.exclusions or []:
        if item.casefold() not in {existing.casefold() for existing in exclusions}:
            exclusions.append(item)
    update: dict[str, object] = {"exclusions": exclusions}
    if value.region is not None:
        update["region"] = value.region
    for field_name in (
        "media_kinds",
        "freshness_days",
        "spoiler_policy",
        "max_results",
    ):
        override = getattr(value, field_name)
        if override is not None:
            update[field_name] = override
    return local.model_copy(update=update)


def _intent_input_sha256(raw_intent: object) -> str:
    if not isinstance(raw_intent, dict):
        raise ValueError("intent hash input must be an object")
    canonical = json.dumps(
        raw_intent,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


class _StartedProvider:
    def __init__(
        self,
        provider: object,
        capability: _Capability,
        start: Callable[[_Capability], None],
        record: Callable[[_Capability, ProviderBatch | None], None],
    ):
        self._provider = provider
        self._capability = capability
        self._start = start
        self._record = record
        self.name = getattr(provider, "name")

    def collect(self, *args: object, **kwargs: object) -> ProviderBatch:
        self._start(self._capability)
        try:
            result = getattr(self._provider, "collect")(*args, **kwargs)
        except Exception:
            self._record(self._capability, None)
            raise
        self._record(self._capability, result)
        return result


class _StartedSynthesizer:
    def __init__(
        self,
        synthesizer: object,
        capability: _Capability,
        start: Callable[[_Capability], None],
        record: Callable[[_Capability, SynthesisProviderResult | None], None],
    ):
        self._synthesizer = synthesizer
        self._capability = capability
        self._start = start
        self._record = record
        self.name = getattr(synthesizer, "name")

    def synthesize(self, *args: object, **kwargs: object) -> SynthesisProviderResult:
        self._start(self._capability)
        try:
            result = getattr(self._synthesizer, "synthesize")(*args, **kwargs)
        except Exception:
            self._record(self._capability, None)
            raise
        self._record(self._capability, result)
        return result


class _DebugEmptySynthesizer:
    """Zero-network synthesis used only by the exact development probe."""

    name = "debug-offline-synthesis"

    def synthesize(self, *args: object, **kwargs: object) -> SynthesisProviderResult:
        del args, kwargs
        return SynthesisProviderResult(
            provider=self.name,
            draft=ResearchSynthesisDraftV2(
                recommendations=[],
                no_strong_opportunity_reason=(
                    "Development replay delegates only to deterministic M1 fallbacks."
                ),
            ),
            usage=ProviderUsage(request_count=0),
        )


def _domain_payload(model: BaseModel) -> dict[str, object]:
    dumped = model.model_dump(mode="json")
    result = _camel_keys(dumped)
    assert isinstance(result, dict)
    return result


def _stage_counts_payload(output: ResearchWorkflowOutput) -> dict[str, object]:
    counts = output.stage_counts
    return {
        # Legacy diagnostic names remain while M1.1 clients migrate.
        "rawProviderResults": counts.parsed_results,
        "parsedResults": counts.parsed_results,
        "normalizedEvidence": counts.normalized_evidence,
        "evidenceSurvivingGates": counts.evidence_surviving_gates,
        "rankedOpportunities": counts.ranked_opportunities,
        "opportunitiesReturnedToUi": counts.opportunities_returned_to_ui,
        # Complete M1.1 candidate funnel. Rust and the UI fill their own
        # receipt/display boundaries rather than letting Python claim them.
        "parsedIntent": counts.parsed_intent,
        "generatedSearchVariants": counts.generated_search_variants,
        "rawReleaseCandidates": counts.raw_release_candidates,
        "candidatesAfterFreshnessFiltering": counts.candidates_after_freshness,
        "candidatesAfterHardExclusions": counts.candidates_after_hard_exclusions,
        "candidatesAfterAudienceFitScreening": (
            counts.candidates_after_audience_fit_screening
        ),
        "candidatesSelectedForSocialResearch": (
            counts.candidates_selected_for_social_research
        ),
        "candidatesWithUsableSocialEvidence": (
            counts.candidates_with_usable_social_evidence
        ),
        "candidatesSurvivingEvidenceGates": (
            counts.candidates_surviving_evidence_gates
        ),
        "candidatesSurvivingDeduplication": (
            counts.candidates_surviving_deduplication
        ),
        "candidatesSentToFinalRanker": counts.candidates_sent_to_final_ranker,
        "finalOpportunitiesSerialized": counts.final_opportunities_serialized,
        "finalOpportunitiesReceivedByRust": None,
        "finalOpportunitiesDisplayedByUi": None,
        "rejectionReasonCounts": dict(counts.rejection_reason_counts),
    }


def _provider_debug_seed_candidate(debug: _DevelopmentDebug) -> EvidenceCandidate:
    seed = debug.seed
    locator = EpisodeLocatorFactV2(
        show_or_title=seed.show_or_title,
        season_number=seed.season_number,
        episode_number=seed.episode_number,
        episode_title=seed.episode_title,
    )
    return EvidenceCandidate(
        provider="tvmaze",
        provider_record_id=seed.provider_record_id,
        source_type=EvidenceSourceType.METADATA,
        canonical_url=seed.canonical_url,
        title=(
            f"{seed.show_or_title} - S{seed.season_number:02d}"
            f"E{seed.episode_number:02d}: {seed.episode_title}"
        ),
        author_or_channel="TVmaze",
        excerpt_type=ExcerptType.PARAPHRASE,
        excerpt=(
            f"TVmaze lists {seed.episode_title} as Season {seed.season_number} "
            f"Episode {seed.episode_number}."
        ),
        verification=VerificationState.SECONDARY_CORROBORATED,
        claim_kind=EvidenceClaimKind.EPISODE_IDENTITY,
        supports_why_now=False,
        policy_class="tvmaze-metadata-v1",
        event_or_release_at=seed.event_or_release_at.astimezone(timezone.utc),
        citation_verified=True,
        episode_locator=locator,
    )


def _provider_debug_local_authorization(
    job_id: UUID,
    *,
    provider: str,
    operation: str,
    model: str | None,
    max_requests: int,
) -> CallAuthorization:
    return CallAuthorization(
        job_id=job_id,
        reservation_id=uuid4(),
        provider=provider,
        operation=operation,
        configured_model=model,
        allowed_resolved_models=(model,) if model else (),
        max_requests=max_requests,
        max_tool_calls=0,
        max_input_tokens=0,
        max_output_tokens=0,
        allow_one_repair=False,
        privacy_mode="development_only",
        live_calls_enabled=True,
    )


def _provider_debug_raw_result_count(events: list[dict[str, object]]) -> int:
    for event in reversed(events):
        if event.get("event") != "http.response":
            continue
        raw_body = event.get("raw_body")
        if not isinstance(raw_body, str):
            return 0
        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError:
            return 0
        if not isinstance(payload, dict):
            return 0
        count = 0
        output = payload.get("output")
        if not isinstance(output, list):
            return 0
        for item in output:
            if not isinstance(item, dict) or item.get("type") != "web_search_call":
                continue
            action = item.get("action")
            if isinstance(action, dict) and isinstance(action.get("sources"), list):
                count += len(action["sources"])
        return count
    return 0


def _provider_debug_trace_payload(
    debug: _DevelopmentDebug,
    events: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "schemaVersion": PAYLOAD_SCHEMA_VERSION,
        "developmentOnly": True,
        "traceId": str(debug.trace_id),
        "events": events,
    }


def _authorization(job_id: UUID, capability: _Capability) -> CallAuthorization:
    return CallAuthorization(
        job_id=job_id,
        reservation_id=capability.reservation_id,
        provider=capability.provider,
        operation=capability.operation,
        configured_model=capability.configured_model,
        allowed_resolved_models=(
            (capability.resolved_model,) if capability.resolved_model is not None else ()
        ),
        max_requests=capability.max_requests,
        max_tool_calls=capability.max_tool_calls,
        max_input_tokens=capability.max_input_tokens,
        max_output_tokens=capability.max_output_tokens,
        allow_one_repair=capability.allow_one_repair,
        privacy_mode=capability.privacy_mode,
        live_calls_enabled=True,
    )


def _build_workflow(
    payload: _ExecutePayload,
    *,
    start_provider: Callable[[_Capability], None] | None = None,
    record_provider: Callable[
        [_Capability, ProviderBatch | SynthesisProviderResult | None], None
    ]
    | None = None,
) -> tuple[ResearchWorkflow, list[tuple[_Capability, CallAuthorization]]]:
    start_provider = start_provider or (lambda capability: None)
    record_provider = record_provider or (lambda capability, result: None)
    official_hosts = {
        host
        for capability in payload.capabilities
        for host in (
            capability.provider_config.official_hosts
            if isinstance(
                capability.provider_config, (_OpenAIWebConfig, _YouTubeConfig)
            )
            else []
        )
    }
    bound: list[tuple[_Capability, CallAuthorization]] = []
    policy_rules: dict[str, PolicyRule] = {}
    provider_plans: list[ProviderPlan] = []
    synthesizer = None
    synthesis_authorization = None
    for capability in payload.capabilities:
        authority = _authorization(payload.job_id, capability)
        bound.append((capability, authority))
        config = capability.provider_config
        if capability.operation != "research.synthesize":
            rule = PolicyRule(
                policy_class=capability.policy_class,
                cache_ttl=timedelta(seconds=capability.evidence_ttl_seconds),
                refresh_after=timedelta(seconds=capability.refresh_after_seconds),
                purge_after=timedelta(seconds=capability.purge_after_seconds),
                deletion_after=(
                    timedelta(seconds=capability.deletion_after_seconds)
                    if capability.deletion_after_seconds is not None
                    else None
                ),
            )
            previous = policy_rules.get(capability.policy_class)
            if previous is not None and previous != rule:
                raise ValueError("one policy class has conflicting Rust-issued deadlines")
            policy_rules[capability.policy_class] = rule
        if isinstance(config, _TVmazeConfig):
            provider_plans.append(
                ProviderPlan(
                    provider=_StartedProvider(
                        TVmazeProvider(policy_class=capability.policy_class),
                        capability,
                        start_provider,
                        record_provider,
                    ),
                    authorization=authority,
                )
            )
        elif isinstance(config, _YouTubeConfig):
            assert capability.credential is not None
            provider_plans.append(
                ProviderPlan(
                    provider=_StartedProvider(
                        YouTubeOfficialProvider(
                            credential=SecretCredential(capability.credential),
                            official_channel_ids=tuple(config.official_channel_ids),
                            policy_class=capability.policy_class,
                        ),
                        capability,
                        start_provider,
                        record_provider,
                    ),
                    authorization=authority,
                )
            )
        elif isinstance(config, _OpenAIWebConfig):
            assert capability.credential is not None
            provider_plans.append(
                ProviderPlan(
                    provider=_StartedProvider(
                        OpenAIWebVerifier(
                            credential=SecretCredential(capability.credential),
                            model=capability.configured_model or "",
                            official_domains=tuple(config.official_hosts),
                            search_context_size=config.search_context_size,
                            request_body_max_input_tokens=(
                                config.request_body_max_input_tokens
                            ),
                            request_max_tool_calls=config.request_max_tool_calls,
                            policy_class=capability.policy_class,
                        ),
                        capability,
                        start_provider,
                        record_provider,
                    ),
                    authorization=authority,
                )
            )
        elif isinstance(config, _OpenAISynthesisConfig):
            assert capability.credential is not None
            synthesizer = _StartedSynthesizer(
                OpenAIResearchSynthesizer(
                    credential=SecretCredential(capability.credential),
                    model=capability.configured_model or "",
                ),
                capability,
                start_provider,
                record_provider,
            )
            synthesis_authorization = authority
        elif isinstance(config, _XAIConfig):
            assert capability.credential is not None
            checked = datetime.fromtimestamp(
                config.proof_checked_at_unix_ms / 1_000, tz=timezone.utc
            )
            expires = datetime.fromtimestamp(
                config.proof_expires_at_unix_ms / 1_000, tz=timezone.utc
            )
            proof = XAIInvocationCapProof(
                proof_id=str(config.adversarial_proof_id),
                configured_model=capability.configured_model or "",
                resolved_model=capability.resolved_model or "",
                request_policy_sha256=config.request_policy_sha256,
                proof_record_sha256=config.proof_record_sha256,
                max_turns=config.max_turns,
                validated_at=checked,
                expires_at=expires,
                passed_adversarial_test=True,
            )
            provider_plans.append(
                ProviderPlan(
                    provider=_StartedProvider(
                        XAISearchProvider(
                            credential=SecretCredential(capability.credential),
                            model=capability.configured_model or "",
                            invocation_cap_proof=proof,
                            zero_data_retention_required=True,
                            policy_class=capability.policy_class,
                            enabled=True,
                        ),
                        capability,
                        start_provider,
                        record_provider,
                    ),
                    authorization=authority,
                )
            )
    if synthesizer is None or synthesis_authorization is None:
        raise ValueError("research execution is missing its synthesis capability")
    return (
        ResearchWorkflow(
            providers=provider_plans,
            synthesizer=synthesizer,
            synthesis_authorization=synthesis_authorization,
            official_hosts=official_hosts,
            reusable_evidence_sources=tuple(payload.reusable_evidence_sources),
            reusable_evidence_claims=tuple(payload.reusable_evidence_claims),
            policy_rules=policy_rules,
        ),
        bound,
    )


def _usage_payload(
    capability: _Capability,
    usage: ProviderUsage,
    *,
    outcome: ProviderRunOutcome,
    output: object | None,
    repair_used: bool | None = None,
) -> dict[str, object]:
    rendered = None
    if output is not None:
        rendered = json.dumps(
            output,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    return {
        "providerRunId": str(capability.provider_run_id),
        "plannedCallId": str(capability.planned_call_id),
        "provider": capability.provider,
        "outcome": "FAILED" if outcome is ProviderRunOutcome.ERROR else outcome.value,
        "configuredModel": usage.configured_model,
        "resolvedModel": usage.resolved_model,
        "providerRequestId": usage.provider_request_id,
        "requests": usage.request_count,
        "inputTokens": usage.input_tokens,
        "cachedInputTokens": usage.cached_input_tokens,
        "outputTokens": usage.output_tokens,
        "reasoningTokens": usage.reasoning_tokens,
        "toolInvocations": usage.tool_calls,
        "repairUsed": repair_used,
        "toolUsage": list(usage.tool_call_details),
        "providerNativeTicks": usage.native_cost_ticks,
        "outputSha256": hashlib.sha256(rendered).hexdigest() if rendered is not None else None,
    }


def _recorded_outcome(
    capability: _Capability,
    result: ProviderBatch | SynthesisProviderResult | None,
) -> dict[str, object]:
    if result is None:
        return _usage_payload(
            capability,
            ProviderUsage(
                configured_model=capability.configured_model,
                resolved_model=capability.resolved_model,
                request_count=None,
            ),
            outcome=ProviderRunOutcome.ERROR,
            output=None,
            repair_used=None,
        )
    if isinstance(result, ProviderBatch):
        return _usage_payload(
            capability,
            result.usage,
            outcome=result.outcome,
            output=[candidate.excerpt for candidate in result.evidence],
            repair_used=False,
        )
    return _usage_payload(
        capability,
        result.usage,
        outcome=result.outcome,
        output=(
            result.draft.model_dump(mode="json")
            if result.draft is not None
            else result.error or result.refusal or result.incomplete
        ),
        repair_used=(
            result.usage.request_count is not None and result.usage.request_count > 1
        ),
    )


def _terminal_from_synthesis(output: ResearchWorkflowOutput) -> str | None:
    if output.synthesis is None or output.synthesis.outcome is ProviderRunOutcome.SUCCESS:
        return None
    return {
        ProviderRunOutcome.REFUSAL: "research.refusal",
        ProviderRunOutcome.INCOMPLETE: "research.incomplete",
        ProviderRunOutcome.ERROR: "research.error",
    }[output.synthesis.outcome]


def _terminal_from_provider_batches(
    batches: tuple[ProviderBatch, ...],
) -> tuple[str, str] | None:
    """Keep provider failures distinct from an evidence-based abstention."""

    message_types = {
        ProviderRunOutcome.REFUSAL: "research.refusal",
        ProviderRunOutcome.INCOMPLETE: "research.incomplete",
        ProviderRunOutcome.ERROR: "research.error",
    }
    for batch in batches:
        if batch.outcome is ProviderRunOutcome.SUCCESS:
            continue
        detail = (
            batch.refusal
            or batch.incomplete
            or batch.error
            or "The provider did not complete its bounded research call."
        )
        message = f"{batch.provider} research did not complete: {detail}"
        return message_types[batch.outcome], message[:1_000]
    return None


def _synthesis_message(value: SynthesisProviderResult) -> str:
    return (
        value.refusal
        or value.incomplete
        or value.error
        or "Recommendation synthesis did not complete."
    )[:1_000]


class _WorkerRuntime:
    def __init__(self) -> None:
        self._write_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._closed = False
        self._active: tuple[UUID, UUID, CancellationToken, threading.Thread] | None = None
        self._pending_starts: dict[UUID, tuple[UUID, UUID, threading.Event]] = {}

    def has_active_job(self) -> bool:
        with self._state_lock:
            return self._active is not None

    def emit(self, request_id: UUID, message_type: str, payload: dict[str, object]) -> None:
        with self._write_lock:
            if self._closed:
                return
            write_json_frame(
                sys.stdout.buffer,
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "requestId": str(request_id),
                    "messageType": message_type,
                    "payload": payload,
                },
            )

    def close_with_ack(self, request_id: UUID) -> None:
        with self._state_lock:
            if self._active is not None:
                self._active[2].cancel()
        with self._write_lock:
            if self._closed:
                return
            write_json_frame(
                sys.stdout.buffer,
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "requestId": str(request_id),
                    "messageType": "shutdown.ack",
                    "payload": {"schemaVersion": PAYLOAD_SCHEMA_VERSION},
                },
            )
            self._closed = True

    def execute(self, request_id: UUID, payload: _ExecutePayload) -> None:
        token = CancellationToken()
        thread = threading.Thread(
            target=self._execute_thread,
            args=(request_id, payload, token),
            daemon=True,
            name=f"research-{payload.job_id}",
        )
        with self._state_lock:
            if self._active is not None:
                self.emit(
                    request_id,
                    "research.error",
                    {
                        "schemaVersion": PAYLOAD_SCHEMA_VERSION,
                        "jobId": str(payload.job_id),
                        "message": "The worker already has an active research job.",
                        "providerOutcomes": [],
                    },
                )
                return
            self._active = (request_id, payload.job_id, token, thread)
        thread.start()

    def cancel(self, request_id: UUID, payload: _CancelPayload) -> None:
        with self._state_lock:
            active = self._active
            if active is not None and active[1] == payload.job_id:
                active[2].cancel()
        self.emit(
            request_id,
            "research.cancel.ack",
            {"schemaVersion": PAYLOAD_SCHEMA_VERSION, "jobId": str(payload.job_id)},
        )

    def start_provider(
        self,
        request_id: UUID,
        job_id: UUID,
        capability: _Capability,
        token: CancellationToken,
    ) -> None:
        event = threading.Event()
        run_id = UUID(str(capability.provider_run_id))
        with self._state_lock:
            active = self._active
            if active is None or active[0] != request_id or active[1] != job_id:
                raise ProviderCancelledError("research job is no longer active")
            if run_id in self._pending_starts:
                raise WorkerProtocolError("provider run start was requested more than once")
            self._pending_starts[run_id] = (
                UUID(str(capability.planned_call_id)),
                job_id,
                event,
            )
        self.emit(
            request_id,
            "provider.started",
            {
                "schemaVersion": PAYLOAD_SCHEMA_VERSION,
                "jobId": str(job_id),
                "providerRunId": str(run_id),
                "plannedCallId": str(capability.planned_call_id),
            },
        )
        deadline = time.monotonic() + 10.0
        try:
            while not event.wait(0.05):
                token.raise_if_cancelled()
                if time.monotonic() >= deadline:
                    raise WorkerProtocolError("provider-start acknowledgement timed out")
        finally:
            with self._state_lock:
                self._pending_starts.pop(run_id, None)

    def acknowledge_provider_start(
        self, request_id: UUID, payload: _ProviderStartedAck
    ) -> None:
        run_id = UUID(str(payload.provider_run_id))
        with self._state_lock:
            active = self._active
            pending = self._pending_starts.get(run_id)
            if (
                active is None
                or active[0] != request_id
                or active[1] != payload.job_id
                or pending is None
                or pending[0] != payload.planned_call_id
                or pending[1] != payload.job_id
            ):
                raise WorkerProtocolError("provider-start acknowledgement did not match")
            pending[2].set()

    def _run_m1_provider_debug(
        self,
        request_id: UUID,
        payload: _ExecutePayload,
        normalized: ResearchIntentV2,
        token: CancellationToken,
        record: Callable[[_Capability, ProviderBatch | None], None],
        outcomes_so_far: Callable[[], list[dict[str, object]]],
    ) -> None:
        debug = payload.development_debug
        assert debug is not None and _is_m1_provider_debug(payload)
        capability = payload.capabilities[0]
        config = capability.provider_config
        assert isinstance(config, _OpenAIWebConfig)
        generated_at = datetime.fromisoformat(
            payload.generated_at.replace("Z", "+00:00")
        )
        events: list[dict[str, object]] = []

        def trace_event(event: dict[str, object]) -> None:
            events.append({"traceId": str(debug.trace_id), **event})

        print(
            "DEVELOPMENT-ONLY M1 provider probe: one Rust-reserved OpenAI request",
            file=sys.stderr,
            flush=True,
        )
        trace_event(
            {
                "event": "provider.resolved",
                "provider": capability.provider,
                "configured_model": capability.configured_model,
                "resolved_model": capability.resolved_model,
                "development_only": True,
            }
        )
        verifier = _StartedProvider(
            OpenAIWebVerifier(
                credential=SecretCredential(capability.credential or ""),
                model=capability.configured_model or "",
                official_domains=tuple(config.official_hosts),
                search_context_size=config.search_context_size,
                request_body_max_input_tokens=config.request_body_max_input_tokens,
                request_max_tool_calls=config.request_max_tool_calls,
                policy_class=capability.policy_class,
                transport=_OneShotOpenAIDebugTransport(
                    UrllibJsonTransport(
                        max_attempts=1,
                        debug_trace_sink=trace_event,
                    )
                ),
                now_fn=lambda: generated_at,
            ),
            capability,
            lambda item: self.start_provider(
                request_id, payload.job_id, item, token
            ),
            record,
        )
        seed = _provider_debug_seed_candidate(debug)
        self.emit(
            request_id,
            "research.progress",
            {
                "schemaVersion": PAYLOAD_SCHEMA_VERSION,
                "jobId": str(payload.job_id),
                "percent": 20,
                "phase": "DEVELOPMENT-ONLY one-request provider probe",
            },
        )
        try:
            batch = verifier.collect(
                normalized,
                authorization=_authorization(payload.job_id, capability),
                cancellation=token,
                context=ProviderResearchContext(prior_evidence=(seed,)),
            )
        except Exception as error:
            counts = {
                "rawProviderResults": _provider_debug_raw_result_count(events),
                "parsedResults": 0,
                "normalizedEvidence": 0,
                "evidenceSurvivingGates": 0,
                "rankedOpportunities": 0,
                "opportunitiesReturnedToUi": 0,
            }
            trace_event({"event": "pipeline.counts", **counts})
            self.emit(
                request_id,
                "research.error",
                {
                    "schemaVersion": PAYLOAD_SCHEMA_VERSION,
                    "jobId": str(payload.job_id),
                    "message": _sanitize_error(error, payload.capabilities),
                    "providerOutcomes": outcomes_so_far(),
                    "debugTrace": _provider_debug_trace_payload(debug, events),
                    "stageCounts": counts,
                },
            )
            return

        if batch.outcome is not ProviderRunOutcome.SUCCESS:
            counts = {
                "rawProviderResults": _provider_debug_raw_result_count(events),
                "parsedResults": len(batch.evidence),
                "normalizedEvidence": 0,
                "evidenceSurvivingGates": 0,
                "rankedOpportunities": 0,
                "opportunitiesReturnedToUi": 0,
            }
            trace_event({"event": "pipeline.counts", **counts})
            terminal = {
                ProviderRunOutcome.REFUSAL: "research.refusal",
                ProviderRunOutcome.INCOMPLETE: "research.incomplete",
                ProviderRunOutcome.ERROR: "research.error",
            }[batch.outcome]
            detail = (
                batch.refusal
                or batch.incomplete
                or batch.error
                or "OpenAI provider probe did not complete."
            )
            self.emit(
                request_id,
                terminal,
                {
                    "schemaVersion": PAYLOAD_SCHEMA_VERSION,
                    "jobId": str(payload.job_id),
                    "message": detail[:1_000],
                    "providerOutcomes": outcomes_so_far(),
                    "debugTrace": _provider_debug_trace_payload(debug, events),
                    "stageCounts": counts,
                },
            )
            return

        metadata_batch = ProviderBatch(provider="tvmaze", evidence=(seed,))
        workflow = ResearchWorkflow(
            providers=[
                ProviderPlan(
                    FakeResearchProvider(
                        name="tvmaze",
                        operation="research.metadata",
                        batches=[metadata_batch],
                    ),
                    _provider_debug_local_authorization(
                        UUID(str(payload.job_id)),
                        provider="tvmaze",
                        operation="research.metadata",
                        model=None,
                        max_requests=1,
                    ),
                ),
                ProviderPlan(
                    FakeResearchProvider(
                        name=DEBUG_PROVIDER,
                        operation="research.web_verify",
                        batches=[batch],
                    ),
                    _authorization(payload.job_id, capability),
                ),
            ],
            synthesizer=_DebugEmptySynthesizer(),
            synthesis_authorization=_provider_debug_local_authorization(
                UUID(str(payload.job_id)),
                provider="debug-offline-synthesis",
                operation="research.synthesize",
                model=None,
                max_requests=0,
            ),
            official_hosts=set(),
        )
        output = workflow.run(
            normalized,
            generated_at=generated_at,
            cancellation=token,
            run_id=UUID(str(payload.research_run_id)),
        )
        counts = _stage_counts_payload(output)
        counts["rawProviderResults"] = _provider_debug_raw_result_count(events)
        counts["parsedResults"] = len(batch.evidence)
        trace_event({"event": "pipeline.counts", **counts})
        self.emit(
            request_id,
            "research.progress",
            {
                "schemaVersion": PAYLOAD_SCHEMA_VERSION,
                "jobId": str(payload.job_id),
                "percent": 100,
                "phase": "DEVELOPMENT-ONLY provider probe validated",
            },
        )
        self.emit(
            request_id,
            "research.result",
            {
                "schemaVersion": PAYLOAD_SCHEMA_VERSION,
                "jobId": str(payload.job_id),
                "result": _domain_payload(output.result),
                "evidenceSources": [
                    _domain_payload(item) for item in output.evidence_sources
                ],
                "evidenceClaims": [
                    _domain_payload(item) for item in output.evidence_claims
                ],
                "providerOutcomes": outcomes_so_far(),
                "debugTrace": _provider_debug_trace_payload(debug, events),
                "stageCounts": counts,
            },
        )

    def _execute_thread(
        self,
        request_id: UUID,
        payload: _ExecutePayload,
        token: CancellationToken,
    ) -> None:
        recorded: dict[UUID, dict[str, object]] = {}

        def record(
            capability: _Capability,
            result: ProviderBatch | SynthesisProviderResult | None,
        ) -> None:
            recorded[UUID(str(capability.provider_run_id))] = _recorded_outcome(
                capability, result
            )

        def outcomes_so_far() -> list[dict[str, object]]:
            return [
                recorded[UUID(str(capability.provider_run_id))]
                for capability in payload.capabilities
                if UUID(str(capability.provider_run_id)) in recorded
            ]

        try:
            normalized = _normalize_intent(payload.intent)
            supplied = _domain_intent(payload.normalized_intent)
            if supplied != normalized:
                raise ValueError(
                    "normalized intent does not match deterministic preview normalization"
                )
            self.emit(
                request_id,
                "research.progress",
                {
                    "schemaVersion": PAYLOAD_SCHEMA_VERSION,
                    "jobId": str(payload.job_id),
                    "percent": 5,
                    "phase": "validating capabilities",
                },
            )
            if _is_m1_provider_debug(payload):
                self._run_m1_provider_debug(
                    request_id,
                    payload,
                    normalized,
                    token,
                    record,
                    outcomes_so_far,
                )
                return
            if _is_verifier_only_diagnostic(payload):
                metadata_capability, capability = payload.capabilities
                metadata_provider = _StartedProvider(
                    TVmazeProvider(policy_class=metadata_capability.policy_class),
                    metadata_capability,
                    lambda item: self.start_provider(
                        request_id, payload.job_id, item, token
                    ),
                    record,
                )
                metadata_batch = metadata_provider.collect(
                    normalized,
                    authorization=_authorization(payload.job_id, metadata_capability),
                    cancellation=token,
                )
                if metadata_batch.outcome is not ProviderRunOutcome.SUCCESS:
                    detail = (
                        metadata_batch.refusal
                        or metadata_batch.incomplete
                        or metadata_batch.error
                        or "TVmaze seed collection did not complete."
                    )
                    self.emit(
                        request_id,
                        "research.error",
                        {
                            "schemaVersion": PAYLOAD_SCHEMA_VERSION,
                            "jobId": str(payload.job_id),
                            "message": detail[:1_000],
                            "providerOutcomes": outcomes_so_far(),
                        },
                    )
                    return
                config = capability.provider_config
                assert isinstance(config, _OpenAIWebConfig)
                verifier = _StartedProvider(
                    OpenAIWebVerifier(
                        credential=SecretCredential(capability.credential or ""),
                        model=capability.configured_model or "",
                        official_domains=tuple(config.official_hosts),
                        search_context_size=config.search_context_size,
                        request_body_max_input_tokens=(
                            config.request_body_max_input_tokens
                        ),
                        request_max_tool_calls=config.request_max_tool_calls,
                        policy_class=capability.policy_class,
                    ),
                    capability,
                    lambda item: self.start_provider(
                        request_id, payload.job_id, item, token
                    ),
                    record,
                )
                token.raise_if_cancelled()
                self.emit(
                    request_id,
                    "research.progress",
                    {
                        "schemaVersion": PAYLOAD_SCHEMA_VERSION,
                        "jobId": str(payload.job_id),
                        "percent": 20,
                        "phase": "running verifier-only diagnostic",
                    },
                )
                batch = verifier.collect(
                    normalized,
                    authorization=_authorization(payload.job_id, capability),
                    cancellation=token,
                    context=ProviderResearchContext(
                        prior_evidence=metadata_batch.evidence,
                        trusted_official_hosts=tuple(
                            sorted(metadata_batch.trusted_official_hosts)
                        ),
                    ),
                )
                if batch.outcome is ProviderRunOutcome.SUCCESS:
                    episode_seed_count = sum(
                        item.claim_kind is EvidenceClaimKind.EPISODE_IDENTITY
                        for item in metadata_batch.evidence
                    )
                    why_now_count = sum(
                        item.claim_kind is EvidenceClaimKind.WHY_NOW
                        and item.content_binding_verified
                        for item in batch.evidence
                    )
                    discussion_count = sum(
                        item.claim_kind is EvidenceClaimKind.VIEWER_DISCUSSION
                        and item.supports_why_now
                        and item.verification
                        is VerificationState.SECONDARY_CORROBORATED
                        for item in batch.evidence
                    )
                    detail = (
                        "OpenAI verifier-only diagnostic passed strict evidence "
                        f"validation after {episode_seed_count} TVmaze episode seed(s), "
                        f"with {len(batch.evidence)} evidence record(s): "
                        f"{why_now_count} bound why-now and {discussion_count} current "
                        f"discussion signal(s); {len(batch.warnings)} bounded warning(s)."
                    )
                    if batch.warnings:
                        detail = f"{detail} {' '.join(batch.warnings)}"[:1_000]
                else:
                    detail = (
                        batch.refusal
                        or batch.incomplete
                        or batch.error
                        or "OpenAI verifier-only diagnostic did not complete."
                    )
                self.emit(
                    request_id,
                    "research.error",
                    {
                        "schemaVersion": PAYLOAD_SCHEMA_VERSION,
                        "jobId": str(payload.job_id),
                        "message": detail[:1_000],
                        "providerOutcomes": outcomes_so_far(),
                    },
                )
                return
            workflow, _ = _build_workflow(
                payload,
                start_provider=lambda capability: self.start_provider(
                    request_id, payload.job_id, capability, token
                ),
                record_provider=record,
            )
            token.raise_if_cancelled()
            self.emit(
                request_id,
                "research.progress",
                {
                    "schemaVersion": PAYLOAD_SCHEMA_VERSION,
                    "jobId": str(payload.job_id),
                    "percent": 20,
                    "phase": "collecting bounded evidence",
                },
            )
            output = workflow.run(
                normalized,
                generated_at=datetime.fromisoformat(
                    payload.generated_at.replace("Z", "+00:00")
                ),
                cancellation=token,
                run_id=UUID(str(payload.research_run_id)),
            )
            outcomes = outcomes_so_far()
            token.raise_if_cancelled()
            provider_terminal = _terminal_from_provider_batches(output.provider_batches)
            if provider_terminal is not None:
                message_type, message = provider_terminal
                self.emit(
                    request_id,
                    message_type,
                    {
                        "schemaVersion": PAYLOAD_SCHEMA_VERSION,
                        "jobId": str(payload.job_id),
                        "message": message,
                        "providerOutcomes": outcomes,
                    },
                )
                return
            terminal = _terminal_from_synthesis(output)
            if terminal is not None:
                assert output.synthesis is not None
                self.emit(
                    request_id,
                    terminal,
                    {
                        "schemaVersion": PAYLOAD_SCHEMA_VERSION,
                        "jobId": str(payload.job_id),
                        "message": _synthesis_message(output.synthesis),
                        "providerOutcomes": outcomes,
                    },
                )
                return
            self.emit(
                request_id,
                "research.progress",
                {
                    "schemaVersion": PAYLOAD_SCHEMA_VERSION,
                    "jobId": str(payload.job_id),
                    "percent": 100,
                    "phase": "validated",
                },
            )
            self.emit(
                request_id,
                "research.result",
                {
                    "schemaVersion": PAYLOAD_SCHEMA_VERSION,
                    "jobId": str(payload.job_id),
                    "result": _domain_payload(output.result),
                    "evidenceSources": [
                        _domain_payload(item) for item in output.evidence_sources
                    ],
                    "evidenceClaims": [
                        _domain_payload(item) for item in output.evidence_claims
                    ],
                    "providerOutcomes": outcomes,
                    "stageCounts": _stage_counts_payload(output),
                },
            )
        except ProviderCancelledError:
            self.emit(
                request_id,
                "research.cancelled",
                {
                    "schemaVersion": PAYLOAD_SCHEMA_VERSION,
                    "jobId": str(payload.job_id),
                    "message": "Research was cancelled.",
                    "providerOutcomes": outcomes_so_far(),
                },
            )
        except Exception as error:  # fail closed at the process boundary
            self.emit(
                request_id,
                "research.error",
                {
                    "schemaVersion": PAYLOAD_SCHEMA_VERSION,
                    "jobId": str(payload.job_id),
                    "message": _sanitize_error(error, payload.capabilities),
                    "providerOutcomes": outcomes_so_far(),
                },
            )
        finally:
            with self._state_lock:
                if self._active is not None and self._active[1] == payload.job_id:
                    self._active = None


def _sanitize_error(error: Exception, capabilities: list[_Capability]) -> str:
    message = str(error).replace("\r", " ").replace("\n", " ")[:1_000]
    for capability in capabilities:
        if capability.credential:
            message = message.replace(capability.credential, "<redacted>")
    return message or "The worker rejected the request."


def _preflight(payload: _PreflightPayload) -> dict[str, object]:
    provider = payload.provider.casefold()
    credential = SecretCredential(payload.credential) if payload.credential else None
    transport = UrllibJsonTransport(max_attempts=1)
    resolved: str | None = None
    if provider == "tvmaze":
        if payload.configured_model is not None or credential is not None:
            raise ValueError("TVmaze preflight does not accept a model or credential")
        response = transport.request_json(
            method="GET",
            url="https://api.tvmaze.com/schedule?country=US",
            headers={"User-Agent": "AIEditMachine/0.1 (TVmaze attribution in UI)"},
            body=None,
            timeout_seconds=15,
            max_response_bytes=2 * 1024 * 1024,
            allowed_hosts=frozenset({"api.tvmaze.com"}),
        )
        if not isinstance(response.payload, list):
            raise ValueError("TVmaze preflight returned an unexpected response")
        retention, data_use, no_storage, privacy = (
            "public-service policy",
            "public metadata with CC BY-SA attribution",
            "not applicable",
            "public_metadata",
        )
    elif provider in {"openai", "xai"}:
        if payload.configured_model is None or credential is None:
            raise ValueError("model provider preflight needs a model and explicit credential")
        if provider == "openai":
            endpoint = "https://api.openai.com/v1/models/" + quote(
                payload.configured_model, safe=""
            )
            host = "api.openai.com"
            retention, data_use, no_storage, privacy = (
                "up to 30 days abuse monitoring unless approved controls apply",
                "API data is not used for training by default",
                "store=false for Responses; stronger ZDR is not assumed",
                "store_false",
            )
        else:
            endpoint = "https://api.x.ai/v1/models/" + quote(
                payload.configured_model, safe=""
            )
            host = "api.x.ai"
            retention, data_use, no_storage, privacy = (
                "provider default unless validated team ZDR applies",
                "xAI API data controls",
                "ZDR must be independently confirmed before X Search is enabled",
                "preflight_unconfirmed",
            )
        response = transport.request_json(
            method="GET",
            url=endpoint,
            headers={"Authorization": f"Bearer {credential.reveal_for_transport()}"},
            body=None,
            timeout_seconds=30,
            max_response_bytes=1024 * 1024,
            allowed_hosts=frozenset({host}),
        )
        if not isinstance(response.payload, dict):
            raise ValueError("model preflight returned an unexpected response")
        model_id = response.payload.get("id")
        if not isinstance(model_id, str) or not model_id:
            raise ValueError("model preflight did not return a resolved model ID")
        resolved = model_id
    elif provider == "youtube":
        if payload.configured_model is not None or credential is None:
            raise ValueError("YouTube preflight needs only an explicit API credential")
        response = transport.request_json(
            method="GET",
            url="https://www.googleapis.com/youtube/v3/i18nLanguages?part=snippet",
            headers={"X-Goog-Api-Key": credential.reveal_for_transport()},
            body=None,
            timeout_seconds=20,
            max_response_bytes=1024 * 1024,
            allowed_hosts=frozenset({"www.googleapis.com"}),
        )
        if not isinstance(response.payload, dict):
            raise ValueError("YouTube preflight returned an unexpected response")
        retention, data_use, no_storage, privacy = (
            "Public official-channel metadata is refreshed or deleted within 30 days.",
            "Exact trusted-title search with local acceptance restricted to reviewed official channel IDs; no audiovisual retrieval.",
            "Only canonical public metadata is normalized; no media or transcripts are requested.",
            "official_metadata_only",
        )
    else:
        raise ValueError("unknown provider preflight target")
    return {
        "schemaVersion": PAYLOAD_SCHEMA_VERSION,
        "provider": provider,
        "available": True,
        "resolvedModel": resolved,
        "retentionMode": retention,
        "dataUseMode": data_use,
        "noStorageMode": no_storage,
        "privacyMode": privacy,
    }


def _handle(runtime: _WorkerRuntime, raw: dict[str, object]) -> bool:
    envelope = _validate_wire(_Envelope, raw)
    assert isinstance(envelope, _Envelope)
    request_id = UUID(str(envelope.request_id))
    if runtime.has_active_job() and envelope.message_type not in {
        "research.cancel",
        "provider.started.ack",
        "shutdown",
    }:
        raise WorkerProtocolError("worker received a concurrent operation")
    if envelope.message_type == "research.preview":
        payload = _validate_wire(_PreviewPayload, envelope.payload)
        assert isinstance(payload, _PreviewPayload)
        if _intent_input_sha256(envelope.payload.get("intent")) != payload.input_sha256:
            raise WorkerProtocolError("research preview input hash mismatch")
        normalized = _normalize_intent(payload.intent)
        runtime.emit(
            request_id,
            "research.preview.result",
            {
                "schemaVersion": PAYLOAD_SCHEMA_VERSION,
                "normalizedIntent": _domain_payload(normalized),
            },
        )
    elif envelope.message_type == "research.execute":
        payload = _validate_wire(_ExecutePayload, envelope.payload)
        assert isinstance(payload, _ExecutePayload)
        if _intent_input_sha256(envelope.payload.get("intent")) != payload.input_sha256:
            raise WorkerProtocolError("research execution input hash mismatch")
        runtime.execute(request_id, payload)
    elif envelope.message_type == "research.cancel":
        payload = _validate_wire(_CancelPayload, envelope.payload)
        assert isinstance(payload, _CancelPayload)
        runtime.cancel(request_id, payload)
    elif envelope.message_type == "provider.preflight":
        payload = _validate_wire(_PreflightPayload, envelope.payload)
        assert isinstance(payload, _PreflightPayload)
        try:
            result = _preflight(payload)
            runtime.emit(request_id, "provider.preflight.result", result)
        except Exception as error:
            runtime.emit(
                request_id,
                "provider.preflight.error",
                {
                    "schemaVersion": PAYLOAD_SCHEMA_VERSION,
                    "provider": payload.provider.casefold(),
                    "message": _sanitize_error(error, []),
                },
            )
    elif envelope.message_type == "provider.started.ack":
        payload = _validate_wire(_ProviderStartedAck, envelope.payload)
        assert isinstance(payload, _ProviderStartedAck)
        runtime.acknowledge_provider_start(request_id, payload)
    elif envelope.message_type == "shutdown":
        payload = _validate_wire(_ShutdownPayload, envelope.payload)
        assert isinstance(payload, _ShutdownPayload)
        runtime.close_with_ack(request_id)
        return False
    else:
        raise WorkerProtocolError("worker received an unknown message type")
    return True


def main() -> int:
    runtime = _WorkerRuntime()
    try:
        write_json_frame(sys.stdout.buffer, hello_frame())
        while True:
            raw = read_json_frame(sys.stdin.buffer)
            if raw is None:
                return 0
            if not _handle(runtime, raw):
                return 0
    except (WorkerProtocolError, ValueError):
        # ValidationError includes input_value by default; never place raw wire
        # data or credentials on stderr.
        print("worker protocol failure", file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
