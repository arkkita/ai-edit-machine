"""Provider-independent call authorization and normalized evidence shapes."""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Protocol
from uuid import UUID

from ..contracts import EvidenceSourceType, ExcerptType, VerificationState
from ..m1_contracts import (
    CastIdentityFactV2,
    EpisodeLocatorFactV2,
    EvidenceClaimKind,
    QuoteFactV2,
    ResearchIntentV2,
    SceneMomentFactV2,
    WhyNowEventFactV2,
)


class ProviderError(RuntimeError):
    """Sanitized provider failure safe for UI/logging."""


class ProviderDisabledError(ProviderError):
    pass


class ProviderLimitError(ProviderError):
    pass


def bounded_tool_call_detail(tool_type: str, opaque_provider_id: object) -> str:
    """Return a protocol-safe audit label without trusting an opaque provider ID."""

    if (
        not tool_type
        or len(tool_type) > 64
        or not tool_type.isascii()
        or any(not (character.isalnum() or character == "_") for character in tool_type)
    ):
        raise ValueError("tool type is not a bounded protocol identifier")
    if opaque_provider_id is None:
        return f"{tool_type}:unidentified"
    if isinstance(opaque_provider_id, str):
        raw = opaque_provider_id.encode("utf-8", errors="strict")
    elif isinstance(opaque_provider_id, (int, float, bool)):
        raw = repr(opaque_provider_id).encode("ascii")
    else:
        raw = repr(opaque_provider_id).encode("utf-8", errors="replace")
    digest = hashlib.sha256(raw).hexdigest()
    return f"{tool_type}:{digest}"


class ProviderCancelledError(ProviderError):
    pass


class ProviderRunOutcome(str, Enum):
    SUCCESS = "SUCCESS"
    REFUSAL = "REFUSAL"
    INCOMPLETE = "INCOMPLETE"
    ERROR = "ERROR"


class SecretCredential:
    """A deliberately non-printable credential supplied explicitly by Rust."""

    __slots__ = ("__value",)

    def __init__(self, value: str) -> None:
        if not value or not value.strip():
            raise ValueError("credential cannot be empty")
        self.__value = value

    def reveal_for_transport(self) -> str:
        return self.__value

    def __repr__(self) -> str:
        return "SecretCredential(<redacted>)"

    __str__ = __repr__


@dataclass(frozen=True, slots=True)
class CallAuthorization:
    """Immutable Rust-issued authority for one bounded provider operation."""

    job_id: UUID
    reservation_id: UUID
    provider: str
    operation: str
    configured_model: str | None
    allowed_resolved_models: tuple[str, ...]
    max_requests: int
    max_tool_calls: int
    max_output_tokens: int
    allow_one_repair: bool
    privacy_mode: str
    live_calls_enabled: bool
    # Aggregate billed-input ceiling across every request in this provider run.
    # Rust derives it from the reserved price components; zero means no paid
    # input tokens are authorized.
    max_input_tokens: int = 0

    def __post_init__(self) -> None:
        if (
            self.max_requests < 0
            or self.max_tool_calls < 0
            or self.max_input_tokens < 0
            or self.max_output_tokens < 0
        ):
            raise ValueError("call authorization limits cannot be negative")
        if not self.provider or not self.operation or not self.privacy_mode:
            raise ValueError("call authorization identity fields cannot be empty")


@dataclass(slots=True)
class CallMeter:
    authorization: CallAuthorization
    requests_used: int = 0
    tool_calls_used: int = 0
    repair_used: bool = False

    def begin_request(self, *, provider: str, operation: str) -> None:
        authority = self.authorization
        if not authority.live_calls_enabled:
            raise ProviderDisabledError("live provider calls are disabled")
        if provider != authority.provider or operation != authority.operation:
            raise ProviderLimitError("provider operation is outside the job capability")
        if self.requests_used >= authority.max_requests:
            raise ProviderLimitError("provider request limit is exhausted")
        self.requests_used += 1

    def record_tool_calls(self, count: int) -> None:
        if count < 0:
            raise ValueError("tool call count cannot be negative")
        if self.tool_calls_used + count > self.authorization.max_tool_calls:
            raise ProviderLimitError("provider tool-call ceiling was exceeded")
        self.tool_calls_used += count

    def begin_repair(self) -> None:
        if not self.authorization.allow_one_repair or self.repair_used:
            raise ProviderLimitError("repair allowance is exhausted")
        self.repair_used = True


class CancellationToken:
    __slots__ = ("_event",)

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise ProviderCancelledError("operation was cancelled")


@dataclass(frozen=True, slots=True)
class EvidenceCandidate:
    provider: str
    provider_record_id: str | None
    source_type: EvidenceSourceType
    canonical_url: str
    title: str
    author_or_channel: str | None
    excerpt_type: ExcerptType
    excerpt: str
    verification: VerificationState
    claim_kind: EvidenceClaimKind
    supports_why_now: bool
    policy_class: str
    source_created_at: datetime | None = None
    source_updated_at: datetime | None = None
    page_published_at: datetime | None = None
    event_or_release_at: datetime | None = None
    query: str = "provider research"
    window_start: datetime | None = None
    window_end: datetime | None = None
    confidence: float = 0.5
    adapter_origin_id: str | None = None
    citation_verified: bool = False
    adapter_source_title: str | None = None
    adapter_source_published_at: datetime | None = None
    content_binding_verified: bool = False
    episode_locator: EpisodeLocatorFactV2 | None = None
    quote_fact: QuoteFactV2 | None = None
    why_now_event: WhyNowEventFactV2 | None = None
    scene_fact: SceneMomentFactV2 | None = None
    cast_fact: CastIdentityFactV2 | None = None


@dataclass(frozen=True, slots=True)
class ProviderResearchContext:
    """Bounded, provider-independent facts collected earlier in this run.

    Collectors receive only normalized adapter candidates and trusted official
    hosts from successful earlier collectors.  This is immutable context, not
    additional provider authority: each receiving adapter still has to validate
    and selectively translate the fields it understands.
    """

    prior_evidence: tuple[EvidenceCandidate, ...] = ()
    trusted_official_hosts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if len(self.prior_evidence) > 200:
            raise ValueError("provider research context is too large")
        normalized_hosts = tuple(value.casefold().strip(" .") for value in self.trusted_official_hosts)
        if (
            normalized_hosts != self.trusted_official_hosts
            or len(normalized_hosts) != len(set(normalized_hosts))
            or any(
                not value
                or len(value) > 253
                or any(not (part and len(part) <= 63 and all(character.isalnum() or character == "-" for character in part)) for part in value.split("."))
                for value in normalized_hosts
            )
        ):
            raise ValueError("trusted official hosts must be unique normalized DNS names")


EMPTY_PROVIDER_RESEARCH_CONTEXT = ProviderResearchContext()


# M1 may return at most ``ResearchIntent.max_results`` opportunities, but the
# metadata discovery pool must be wider than the requested output count.  A
# five-card request previously collapsed the entire current TV landscape to
# five schedule rows before the verifier had a chance to compare them.  These
# bounds keep the provider context below its 200-record ceiling while allowing
# the verifier to choose among a meaningfully diverse candidate set.
MAX_TVMAZE_DISCOVERY_SHOWS = 15
MAX_M11_TVMAZE_DISCOVERY_SHOWS = 30
MAX_TVMAZE_CAST_SHOWS = 8


@dataclass(frozen=True, slots=True)
class ProviderCandidateTrace:
    """Sanitized immutable identity for one deep-research candidate.

    The trace deliberately contains no URL, excerpt, query, provider payload,
    or user-secret data.  It exists so a development/result diagnostic can
    explain which exact title consumed a bounded deep-research slot.
    """

    candidate_name: str
    title: str
    shortlist_rank: int
    shortlist_reason: str
    season_number: int | None = None
    episode_number: int | None = None
    episode_title: str | None = None

    def __post_init__(self) -> None:
        text_values = (
            self.candidate_name,
            self.title,
            self.shortlist_reason,
            *(value for value in (self.episode_title,) if value is not None),
        )
        if (
            not 1 <= self.shortlist_rank <= 1_000
            or any(
                not value
                or len(value) > 500
                or any(character in value for character in "\r\n\0")
                for value in text_values
            )
            or (self.season_number is None) != (self.episode_number is None)
            or (self.season_number is not None and self.season_number < 0)
            or (self.episode_number is not None and self.episode_number < 1)
        ):
            raise ValueError("provider candidate trace is invalid")


@dataclass(frozen=True, slots=True)
class ProviderCandidateFunnel:
    """Provider observability for M1 candidate allocation.

    Counters remain value-free. Candidate traces contain only bounded immutable
    title/episode identities and a host-authored allocation reason; they never
    retain queries, URLs, excerpts, or provider payloads.
    """

    generated_search_variants: int = 0
    raw_release_candidates: int = 0
    candidates_after_freshness: int = 0
    candidates_after_hard_exclusions: int = 0
    candidates_after_audience_fit_screening: int = 0
    candidates_selected_for_social_research: int = 0
    candidates_with_usable_social_evidence: int = 0
    candidate_traces: tuple[ProviderCandidateTrace, ...] = ()

    def __post_init__(self) -> None:
        values = (
            self.generated_search_variants,
            self.raw_release_candidates,
            self.candidates_after_freshness,
            self.candidates_after_hard_exclusions,
            self.candidates_after_audience_fit_screening,
            self.candidates_selected_for_social_research,
            self.candidates_with_usable_social_evidence,
        )
        if any(value < 0 for value in values):
            raise ValueError("candidate-funnel counters cannot be negative")
        if len(self.candidate_traces) > 30:
            raise ValueError("candidate-funnel trace exceeds the bounded title slate")
        ranks = [item.shortlist_rank for item in self.candidate_traces]
        titles = [item.title.casefold() for item in self.candidate_traces]
        if len(ranks) != len(set(ranks)) or len(titles) != len(set(titles)):
            raise ValueError("candidate-funnel traces must have unique ranks and titles")


@dataclass(frozen=True, slots=True)
class ProviderUsage:
    configured_model: str | None = None
    resolved_model: str | None = None
    provider_request_id: str | None = None
    # None means a started provider run terminated before the adapter could
    # prove how many remote requests were accepted. Rust reconciles that state
    # conservatively as unverified rather than silently treating it as zero.
    request_count: int | None = 0
    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    tool_calls: int = 0
    tool_call_details: tuple[str, ...] = ()
    native_cost_ticks: str | None = None
    cache_hit: bool = False
    quota_units: int = 0
    quota_unit_name: str | None = None

    def __post_init__(self) -> None:
        numeric = (
            self.request_count,
            self.input_tokens,
            self.cached_input_tokens,
            self.output_tokens,
            self.reasoning_tokens,
            self.tool_calls,
            self.quota_units,
        )
        if any(value is not None and value < 0 for value in numeric):
            raise ValueError("provider usage counters cannot be negative")
        if self.cached_input_tokens is not None and self.input_tokens is not None:
            if self.cached_input_tokens > self.input_tokens:
                raise ValueError("cached input tokens cannot exceed total input tokens")
        if len(self.tool_call_details) != self.tool_calls:
            raise ValueError("tool-call detail count must equal tool_calls")
        if any(
            not detail
            or len(detail) > 256
            or not detail.isascii()
            or any(character in detail for character in "\r\n\0")
            for detail in self.tool_call_details
        ):
            raise ValueError("tool-call details must be bounded ASCII audit labels")
        if self.quota_units and not self.quota_unit_name:
            raise ValueError("quota usage requires a unit name")
        if self.native_cost_ticks is not None and (
            not self.native_cost_ticks.isascii() or not self.native_cost_ticks.isdigit()
        ):
            raise ValueError("native cost ticks must be a nonnegative integer string")


@dataclass(frozen=True, slots=True)
class ProviderBatch:
    provider: str
    evidence: tuple[EvidenceCandidate, ...]
    usage: ProviderUsage = field(default_factory=ProviderUsage)
    warnings: tuple[str, ...] = ()
    outcome: ProviderRunOutcome = ProviderRunOutcome.SUCCESS
    refusal: str | None = None
    incomplete: str | None = None
    error: str | None = None
    attributions: tuple[str, ...] = ()
    trusted_official_hosts: tuple[str, ...] = ()
    candidate_funnel: ProviderCandidateFunnel = field(
        default_factory=ProviderCandidateFunnel
    )

    def __post_init__(self) -> None:
        details = [self.refusal, self.incomplete, self.error]
        if self.outcome is ProviderRunOutcome.SUCCESS:
            if any(value is not None for value in details):
                raise ValueError("SUCCESS provider batch cannot carry failure detail")
        elif self.outcome is ProviderRunOutcome.REFUSAL:
            if not self.refusal or self.incomplete is not None or self.error is not None:
                raise ValueError("REFUSAL requires only refusal detail")
        elif self.outcome is ProviderRunOutcome.INCOMPLETE:
            if not self.incomplete or self.refusal is not None or self.error is not None:
                raise ValueError("INCOMPLETE requires only incomplete detail")
        elif not self.error or self.refusal is not None or self.incomplete is not None:
            raise ValueError("ERROR requires only error detail")
        if self.outcome is not ProviderRunOutcome.SUCCESS and self.evidence:
            raise ValueError("non-success provider batches cannot carry evidence")
        if self.outcome is not ProviderRunOutcome.SUCCESS and self.trusted_official_hosts:
            raise ValueError("non-success provider batches cannot mint official hosts")


class ResearchProvider(Protocol):
    name: str

    def collect(
        self,
        intent: ResearchIntentV2,
        *,
        authorization: CallAuthorization,
        cancellation: CancellationToken,
        context: ProviderResearchContext = EMPTY_PROVIDER_RESEARCH_CONTEXT,
    ) -> ProviderBatch: ...
