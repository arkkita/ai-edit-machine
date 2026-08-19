"""Milestone 1 research contracts.

These v2 contracts correct two limitations in the M0 seed: evidence sources and
claims now have independently joinable identifiers, and footage requests can
describe several required, optional, and substitutable sources without hiding
uncertainty.  Provider-authored drafts remain separate from canonical records.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, HttpUrl, UUID4, model_validator

from .contracts import (
    Confidence,
    EvidenceGate,
    EvidenceRole,
    EvidenceSourceType,
    ExcerptType,
    MediaKind,
    NonEmptyText,
    OpportunityFocus,
    Sha256,
    ShortText,
    SpoilerPolicy,
    StrictContract,
    VerificationState,
)


# TV metadata providers legitimately use calendar years as season identifiers
# for some daily/continuing series.  Keep the field numeric and bounded, but do
# not reject a verified value such as 2026 merely because it is not a small
# ordinal season number.
MAX_SEASON_NUMBER = 9_999


class ResearchIntentV2(StrictContract):
    schema_version: Literal["2.0.0"] = "2.0.0"
    query: Annotated[str, Field(min_length=1, max_length=4_000)]
    media_kinds: Annotated[list[MediaKind], Field(min_length=1, max_length=5)]
    focus_terms: Annotated[list[ShortText], Field(default_factory=list, max_length=20)]
    region: Annotated[str, Field(min_length=2, max_length=16)] = "US"
    freshness_days: Annotated[int, Field(ge=1, le=90)] = 14
    spoiler_policy: SpoilerPolicy = SpoilerPolicy.CURRENT_EPISODE
    exclusions: Annotated[list[ShortText], Field(default_factory=list, max_length=30)]
    max_results: Annotated[int, Field(ge=1, le=10)] = 5

    @model_validator(mode="after")
    def validate_unique_lists(self) -> Self:
        for label, values in (
            ("media_kinds", [value.value for value in self.media_kinds]),
            ("focus_terms", self.focus_terms),
            ("exclusions", self.exclusions),
        ):
            normalized = [value.casefold() for value in values]
            if len(normalized) != len(set(normalized)):
                raise ValueError(f"{label} must not contain duplicates")
        return self


class EvidenceClaimKind(str, Enum):
    WHY_NOW = "WHY_NOW"
    VIEWER_DISCUSSION = "VIEWER_DISCUSSION"
    EPISODE_IDENTITY = "EPISODE_IDENTITY"
    QUOTE = "QUOTE"
    SCENE_CONTEXT = "SCENE_CONTEXT"
    OFFICIAL_CLIP = "OFFICIAL_CLIP"
    CAST_IDENTITY = "CAST_IDENTITY"


class WhyNowEventKind(str, Enum):
    EPISODE_RELEASE = "EPISODE_RELEASE"
    FILM_RELEASE = "FILM_RELEASE"
    TRAILER_RELEASE = "TRAILER_RELEASE"
    OFFICIAL_CLIP_RELEASE = "OFFICIAL_CLIP_RELEASE"


class MediaIdentityV2(StrictContract):
    media_kind: MediaKind
    show_or_title: ShortText
    season_number: Annotated[int | None, Field(ge=0, le=MAX_SEASON_NUMBER)] = None
    episode_number: Annotated[int | None, Field(ge=1, le=9_999)] = None
    episode_title: Annotated[str | None, Field(max_length=500)] = None

    @model_validator(mode="after")
    def validate_locator(self) -> Self:
        if self.media_kind is MediaKind.TV_EPISODE:
            if self.season_number is None or self.episode_number is None:
                raise ValueError("TV_EPISODE identity requires season and episode numbers")
        elif (
            self.season_number is not None
            or self.episode_number is not None
            or self.episode_title is not None
        ):
            raise ValueError("only TV_EPISODE identity may carry episode locator fields")
        return self


class WhyNowEventFactV2(StrictContract):
    event_kind: WhyNowEventKind
    media_identity: MediaIdentityV2

    @model_validator(mode="after")
    def validate_kind(self) -> Self:
        expected = {
            WhyNowEventKind.EPISODE_RELEASE: MediaKind.TV_EPISODE,
            WhyNowEventKind.FILM_RELEASE: MediaKind.FILM,
            WhyNowEventKind.TRAILER_RELEASE: MediaKind.TRAILER,
            WhyNowEventKind.OFFICIAL_CLIP_RELEASE: MediaKind.OFFICIAL_CLIP,
        }[self.event_kind]
        if self.media_identity.media_kind is not expected:
            raise ValueError("why-now event kind must match its media identity")
        return self


class EpisodeLocatorFactV2(StrictContract):
    show_or_title: ShortText
    season_number: Annotated[int, Field(ge=0, le=MAX_SEASON_NUMBER)]
    episode_number: Annotated[int, Field(ge=1, le=9_999)]
    episode_title: Annotated[str | None, Field(max_length=500)] = None


class QuoteFactV2(StrictContract):
    exact_text: ShortText
    speaker: ShortText
    media_identity: MediaIdentityV2
    context: Annotated[str | None, Field(max_length=500)] = None
    episode_locator: EpisodeLocatorFactV2 | None = None

    @model_validator(mode="after")
    def validate_media_binding(self) -> Self:
        if self.episode_locator is not None:
            expected = MediaIdentityV2(
                media_kind=MediaKind.TV_EPISODE,
                show_or_title=self.episode_locator.show_or_title,
                season_number=self.episode_locator.season_number,
                episode_number=self.episode_locator.episode_number,
                episode_title=self.episode_locator.episode_title,
            )
            if self.media_identity != expected:
                raise ValueError("quote episode locator must match quote media identity")
        elif self.media_identity.media_kind is MediaKind.TV_EPISODE:
            raise ValueError("episode-bound quote identity requires an episode locator")
        return self


class CastIdentityFactV2(StrictContract):
    show_or_title: ShortText
    character_name: ShortText
    performer_name: ShortText


class SceneMomentFactV2(StrictContract):
    show_or_title: ShortText
    description: NonEmptyText
    characters: Annotated[list[ShortText], Field(default_factory=list, max_length=20)]
    relationship_or_topic: Annotated[str | None, Field(max_length=500)] = None
    episode_locator: EpisodeLocatorFactV2 | None = None


class EvidenceSourceRecordV2(StrictContract):
    """Trusted normalized source identity and policy record."""

    schema_version: Literal["2.0.0"] = "2.0.0"
    source_id: UUID4
    provider: Annotated[str, Field(min_length=1, max_length=64)]
    provider_record_id: Annotated[str | None, Field(max_length=256)] = None
    source_type: EvidenceSourceType
    canonical_url: HttpUrl
    title: ShortText
    author_or_channel: Annotated[str | None, Field(max_length=200)] = None
    source_created_at: AwareDatetime | None = None
    source_updated_at: AwareDatetime | None = None
    page_published_at: AwareDatetime | None = None
    retrieved_at: AwareDatetime
    query: Annotated[str, Field(min_length=1, max_length=1_000)]
    window_start: AwareDatetime | None = None
    window_end: AwareDatetime | None = None
    policy_class: Annotated[str, Field(min_length=1, max_length=64)]
    refresh_due_at: AwareDatetime | None = None
    purge_due_at: AwareDatetime | None = None
    expires_at: AwareDatetime | None = None
    deletion_required_at: AwareDatetime | None = None
    content_sha256: Sha256
    independence_group: Annotated[str, Field(min_length=1, max_length=128)]

    @model_validator(mode="after")
    def validate_dates(self) -> Self:
        if self.window_start and self.window_end and self.window_end <= self.window_start:
            raise ValueError("window_end must be later than window_start")
        for label, value in (
            ("refresh_due_at", self.refresh_due_at),
            ("purge_due_at", self.purge_due_at),
            ("expires_at", self.expires_at),
            ("deletion_required_at", self.deletion_required_at),
        ):
            if value is not None and value <= self.retrieved_at:
                raise ValueError(f"{label} must be later than retrieved_at")
        return self


class EvidenceClaimRecordV2(StrictContract):
    """One claim joined to exactly one normalized evidence source."""

    schema_version: Literal["2.0.0"] = "2.0.0"
    claim_id: UUID4
    source_id: UUID4
    claim_kind: EvidenceClaimKind
    excerpt_type: ExcerptType
    text: ShortText
    verification: VerificationState
    episode_locator: EpisodeLocatorFactV2 | None = None
    quote_fact: QuoteFactV2 | None = None
    why_now_event: WhyNowEventFactV2 | None = None
    scene_fact: SceneMomentFactV2 | None = None
    cast_fact: CastIdentityFactV2 | None = None
    event_or_release_at: AwareDatetime | None = None
    confidence: Confidence
    supports_why_now: bool
    content_sha256: Sha256

    @model_validator(mode="after")
    def validate_support(self) -> Self:
        if self.excerpt_type is ExcerptType.SHORT_QUOTE and self.claim_kind is not EvidenceClaimKind.QUOTE:
            raise ValueError("SHORT_QUOTE evidence must use claim kind QUOTE")
        if self.supports_why_now and self.claim_kind not in {
            EvidenceClaimKind.WHY_NOW,
            EvidenceClaimKind.OFFICIAL_CLIP,
            EvidenceClaimKind.VIEWER_DISCUSSION,
        }:
            raise ValueError("this claim kind cannot support why-now")
        if self.claim_kind is EvidenceClaimKind.EPISODE_IDENTITY:
            if self.episode_locator is None or any(
                value is not None
                for value in (self.quote_fact, self.why_now_event, self.scene_fact, self.cast_fact)
            ):
                raise ValueError("EPISODE_IDENTITY requires only an episode locator fact")
        elif self.claim_kind is EvidenceClaimKind.QUOTE:
            if self.quote_fact is None or any(
                value is not None
                for value in (self.episode_locator, self.why_now_event, self.scene_fact, self.cast_fact)
            ):
                raise ValueError("QUOTE requires a structured quote fact")
            if self.excerpt_type is not ExcerptType.SHORT_QUOTE:
                raise ValueError("QUOTE facts require SHORT_QUOTE evidence")
            if self.text != self.quote_fact.exact_text:
                raise ValueError("quote claim text must exactly match quote_fact.exact_text")
        elif self.claim_kind is EvidenceClaimKind.SCENE_CONTEXT:
            if self.scene_fact is None or any(
                value is not None
                for value in (self.episode_locator, self.quote_fact, self.why_now_event, self.cast_fact)
            ):
                raise ValueError("SCENE_CONTEXT requires a structured scene fact")
        elif self.claim_kind is EvidenceClaimKind.CAST_IDENTITY:
            if self.cast_fact is None or any(
                value is not None
                for value in (self.episode_locator, self.quote_fact, self.why_now_event, self.scene_fact)
            ):
                raise ValueError("CAST_IDENTITY requires a structured cast fact")
        elif self.claim_kind in {EvidenceClaimKind.WHY_NOW, EvidenceClaimKind.OFFICIAL_CLIP}:
            if self.why_now_event is None or self.event_or_release_at is None:
                raise ValueError("release/clip claims require a structured dated event")
            if self.quote_fact is not None or self.cast_fact is not None:
                raise ValueError("release/clip claims cannot carry quote or cast facts")
            identity = self.why_now_event.media_identity
            if identity.media_kind is MediaKind.TV_EPISODE:
                if self.episode_locator is None:
                    raise ValueError("episode release event requires the same episode locator")
                expected = EpisodeLocatorFactV2(
                    show_or_title=identity.show_or_title,
                    season_number=identity.season_number,
                    episode_number=identity.episode_number,
                    episode_title=identity.episode_title,
                )
                if self.episode_locator != expected:
                    raise ValueError("release event and episode locator must match exactly")
            elif self.episode_locator is not None:
                raise ValueError("non-episode release events cannot carry episode locators")
            if self.claim_kind is EvidenceClaimKind.WHY_NOW and self.scene_fact is not None:
                raise ValueError("WHY_NOW event and scene context must be separate claims")
        elif any(
            value is not None
            for value in (
                self.episode_locator,
                self.quote_fact,
                self.why_now_event,
                self.scene_fact,
                self.cast_fact,
            )
        ):
            raise ValueError("VIEWER_DISCUSSION cannot carry structured factual payloads")
        return self


class OpportunityEvidenceSelectionV2(StrictContract):
    """Provider selection; trusted code derives independence from the source join."""

    claim_id: UUID4
    role: EvidenceRole
    supports_why_now: bool


class TrustedOpportunityEvidenceReferenceV2(OpportunityEvidenceSelectionV2):
    independence_group: Annotated[str, Field(min_length=1, max_length=128)]


class OpportunityScoreV2(StrictContract):
    release_freshness: Confidence
    cross_source_agreement: Confidence
    scene_specificity: Confidence
    footage_actionability: Confidence
    independent_source_count: Annotated[int, Field(ge=0, le=30)]
    total: Confidence

    @model_validator(mode="after")
    def validate_total(self) -> Self:
        expected = (
            self.release_freshness
            + self.cross_source_agreement
            + self.scene_specificity
            + self.footage_actionability
        ) / 4.0
        if abs(expected - self.total) > 1e-9:
            raise ValueError("total must equal the mean of the four score dimensions")
        return self


_VIRAL_CERTAINTY = re.compile(
    r"(?:\bviral\b|\b\d{1,3}\s*%\s+chance\b)",
    re.IGNORECASE,
)
_PROHIBITED_ACQUISITION = re.compile(
    r"(?:\byt[ -]?dlp\b|\bm3u8\b|\bmanifest\b|\btorrents?\b|\bdownload(?:s|ing|ed)?\b|"
    r"\brip(?:s|ping|ped)?\b|\b(?:bypass|defeat|circumvent)\b|\bdrm\b|\bpaywall\b|"
    r"\bcookies?\b|\bauth(?:entication|orization)?\s+(?:token|header|bypass)\b)",
    re.IGNORECASE,
)


class TrendOpportunityDraftV2(StrictContract):
    """Untrusted model synthesis over an exact allow-list of claim IDs."""

    schema_version: Literal["2.0.0"] = "2.0.0"
    media_kind: MediaKind
    media_identity: MediaIdentityV2
    title: ShortText
    focus: OpportunityFocus
    why_now: NonEmptyText
    what_viewers_are_discussing: NonEmptyText
    creative_hook: NonEmptyText
    emotional_edit_direction: NonEmptyText
    evidence: Annotated[
        list[OpportunityEvidenceSelectionV2], Field(min_length=1, max_length=30)
    ]
    confidence: Confidence
    caveats: Annotated[list[ShortText], Field(default_factory=list, max_length=20)]

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        if self.media_identity.media_kind is not self.media_kind:
            raise ValueError("opportunity media kind must match its identity")
        claim_ids = [item.claim_id for item in self.evidence]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("evidence claim IDs must be unique")
        for value in (
            self.title,
            " ".join(self.focus.characters),
            self.focus.relationship_or_topic,
            self.why_now,
            self.what_viewers_are_discussing,
            self.creative_hook,
            self.emotional_edit_direction,
            *self.caveats,
        ):
            if _VIRAL_CERTAINTY.search(value):
                raise ValueError("opportunities cannot claim virality certainty")
            if _PROHIBITED_ACQUISITION.search(value):
                raise ValueError("opportunities cannot contain prohibited acquisition instructions")
        return self


class TrendOpportunityV2(StrictContract):
    schema_version: Literal["2.0.0"] = "2.0.0"
    opportunity_id: UUID4
    footage_request_id: UUID4
    media_kind: MediaKind
    media_identity: MediaIdentityV2
    title: ShortText
    focus: OpportunityFocus
    why_now: NonEmptyText
    what_viewers_are_discussing: NonEmptyText
    creative_hook: NonEmptyText
    emotional_edit_direction: NonEmptyText
    evidence: Annotated[
        list[TrustedOpportunityEvidenceReferenceV2], Field(min_length=1, max_length=30)
    ]
    evidence_gate: EvidenceGate
    confidence: Confidence
    score: OpportunityScoreV2
    caveats: Annotated[list[ShortText], Field(default_factory=list, max_length=20)]

    @model_validator(mode="after")
    def validate_trusted_gate_shape(self) -> Self:
        claim_ids = [item.claim_id for item in self.evidence]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("evidence claim IDs must be unique")
        if self.evidence_gate is EvidenceGate.PASSED:
            primary = [
                item
                for item in self.evidence
                if item.role is EvidenceRole.PRIMARY_WHY_NOW and item.supports_why_now
            ]
            signals = [
                item
                for item in self.evidence
                if item.role is EvidenceRole.QUALITATIVE_SIGNAL
                and item.supports_why_now
            ]
            groups = {item.independence_group for item in [*primary, *signals]}
            signal_groups = {item.independence_group for item in signals}
            if not primary or len(signals) < 2:
                raise ValueError("PASSED requires one primary and two qualitative signals")
            if len(groups) < 3 or len(signal_groups) < 2:
                raise ValueError("PASSED evidence must use trusted independent groups")
        for value in (
            self.title,
            " ".join(self.focus.characters),
            self.focus.relationship_or_topic,
            self.why_now,
            self.what_viewers_are_discussing,
            self.creative_hook,
            self.emotional_edit_direction,
            *self.caveats,
        ):
            if _VIRAL_CERTAINTY.search(value):
                raise ValueError("opportunities cannot claim virality certainty")
            if _PROHIBITED_ACQUISITION.search(value):
                raise ValueError("opportunities cannot contain prohibited acquisition instructions")
        return self


class FootageVerificationLevel(str, Enum):
    VERIFIED = "VERIFIED"
    STRONGLY_SUPPORTED = "STRONGLY_SUPPORTED"
    LIKELY_INFERRED = "LIKELY_INFERRED"
    UNKNOWN = "UNKNOWN"


class SourcePurpose(str, Enum):
    INTRO = "INTRO"
    MONTAGE = "MONTAGE"
    PAYOFF = "PAYOFF"
    OPTIONAL_CALLBACK = "OPTIONAL_CALLBACK"


class SourceAcquisitionKind(str, Enum):
    EPISODE = "EPISODE"
    OFFICIAL_TRAILER = "OFFICIAL_TRAILER"
    OFFICIAL_CLIP = "OFFICIAL_CLIP"
    SCENE_PACK = "SCENE_PACK"
    INDIVIDUAL_SCENES = "INDIVIDUAL_SCENES"


class FootageQuoteStatus(str, Enum):
    VERIFIED = "VERIFIED"
    PARAPHRASE = "PARAPHRASE"
    UNVERIFIED_LEAD = "UNVERIFIED_LEAD"


class FootageQuoteV2(StrictContract):
    status: FootageQuoteStatus
    text: ShortText
    speaker: Annotated[str | None, Field(max_length=200)] = None
    likely_context: Annotated[str | None, Field(max_length=500)] = None
    claim_id: UUID4

    @model_validator(mode="after")
    def validate_quote(self) -> Self:
        if self.status is FootageQuoteStatus.VERIFIED:
            if self.speaker is None:
                raise ValueError("VERIFIED quote requires a supported speaker")
        elif self.speaker is not None or self.likely_context is not None:
            raise ValueError(
                "non-authoritative quote leads cannot assert speaker or context"
            )
        return self


SourceKey = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")]


class RequestedSourceDraftV2(StrictContract):
    source_key: SourceKey
    priority: Annotated[int, Field(ge=1, le=30)]
    acquisition_effort: Annotated[int, Field(ge=1, le=5)]
    asset_kind: SourceAcquisitionKind
    show_or_title: ShortText
    season_number: Annotated[int | None, Field(ge=0, le=MAX_SEASON_NUMBER)] = None
    episode_number: Annotated[int | None, Field(ge=1, le=9_999)] = None
    episode_title: Annotated[str | None, Field(max_length=500)] = None
    characters: Annotated[list[ShortText], Field(default_factory=list, max_length=20)]
    relationship_or_topic: Annotated[str | None, Field(max_length=500)] = None
    scene_or_moment: NonEmptyText
    purposes: Annotated[list[SourcePurpose], Field(min_length=1, max_length=4)]
    verification_level: FootageVerificationLevel
    source_quality_summary: ShortText
    supporting_claim_ids: Annotated[list[UUID4], Field(default_factory=list, max_length=30)]
    quote: FootageQuoteV2 | None = None
    why_it_matters_emotionally: NonEmptyText
    search_queries: Annotated[list[ShortText], Field(min_length=1, max_length=20)]
    replaces_required_source_keys: Annotated[
        list[SourceKey], Field(default_factory=list, max_length=30)
    ]

    @model_validator(mode="after")
    def validate_source(self) -> Self:
        if (self.season_number is None) != (self.episode_number is None):
            raise ValueError("season_number and episode_number must be supplied together")
        if self.asset_kind is SourceAcquisitionKind.EPISODE and (
            self.season_number is None or self.episode_number is None
        ):
            raise ValueError("EPISODE requires season_number and episode_number")
        if self.asset_kind is not SourceAcquisitionKind.EPISODE and (
            self.season_number is not None
            or self.episode_number is not None
            or self.episode_title is not None
        ):
            raise ValueError("only EPISODE sources may carry episode locator fields")
        if self.verification_level is FootageVerificationLevel.UNKNOWN and (
            self.season_number is not None or self.episode_title is not None
        ):
            raise ValueError("UNKNOWN sources cannot carry an exact episode locator")
        if self.verification_level is not FootageVerificationLevel.UNKNOWN and not self.supporting_claim_ids:
            raise ValueError("a supported/inferred source requires supporting claim IDs")
        if len(self.supporting_claim_ids) != len(set(self.supporting_claim_ids)):
            raise ValueError("supporting claim IDs must be unique")
        if (
            self.quote is not None
            and self.quote.claim_id not in self.supporting_claim_ids
        ):
            raise ValueError("every displayed quote/paraphrase claim must support its source")
        if len(self.purposes) != len(set(self.purposes)):
            raise ValueError("source purposes must be unique")
        purpose_order = list(SourcePurpose)
        if self.purposes != sorted(self.purposes, key=purpose_order.index):
            raise ValueError("source purposes must use canonical editorial order")
        normalized_queries = [value.casefold() for value in self.search_queries]
        if len(normalized_queries) != len(set(normalized_queries)):
            raise ValueError("source search queries must be unique")
        return self


class RequestedSourceV2(RequestedSourceDraftV2):
    requested_source_id: UUID4


class NaturalFootageRequestV2(StrictContract):
    best: NonEmptyText
    alternative: NonEmptyText | None = None
    minimum: NonEmptyText
    optional_improvement: NonEmptyText | None = None


class IntroMaterialLeadDraftV2(StrictContract):
    source_key: SourceKey
    moment_description: NonEmptyText
    quote: FootageQuoteV2 | None = None
    why_it_might_lead_into_montage: NonEmptyText
    verification_level: FootageVerificationLevel
    supporting_claim_ids: Annotated[list[UUID4], Field(default_factory=list, max_length=30)]

    @model_validator(mode="after")
    def validate_support(self) -> Self:
        if not self.supporting_claim_ids:
            raise ValueError("every intro lead requires at least one evidence claim")
        if len(self.supporting_claim_ids) != len(set(self.supporting_claim_ids)):
            raise ValueError("intro supporting claim IDs must be unique")
        if (
            self.quote is not None
            and self.quote.claim_id not in self.supporting_claim_ids
        ):
            raise ValueError("every displayed quote/paraphrase claim must support its intro lead")
        return self


class IntroMaterialLeadV2(IntroMaterialLeadDraftV2):
    intro_lead_id: UUID4


def _validate_footage_request(
    *,
    natural_request: NaturalFootageRequestV2,
    required_sources: list[RequestedSourceDraftV2],
    optional_sources: list[RequestedSourceDraftV2],
    alternative_sources: list[RequestedSourceDraftV2],
    minimum_useful_source_keys: list[str],
    intro_leads: list[IntroMaterialLeadDraftV2],
    search_queries: list[str],
) -> None:
    all_sources = [*required_sources, *optional_sources, *alternative_sources]
    all_keys = [item.source_key for item in all_sources]
    if len(all_keys) != len(set(all_keys)):
        raise ValueError("requested source keys must be globally unique")
    required_keys = {item.source_key for item in required_sources}
    for label, bucket in (
        ("required", required_sources),
        ("optional", optional_sources),
        ("alternative", alternative_sources),
    ):
        priorities = [item.priority for item in bucket]
        if priorities != list(range(1, len(bucket) + 1)):
            raise ValueError(f"{label} source priorities must be contiguous and match list order")
    if set(minimum_useful_source_keys) != required_keys:
        raise ValueError("minimum useful source keys must equal the required source set")
    if len(minimum_useful_source_keys) != len(set(minimum_useful_source_keys)):
        raise ValueError("minimum useful source keys must be unique")
    for source in required_sources:
        if source.replaces_required_source_keys:
            raise ValueError("required sources cannot replace other required sources")
    for source in optional_sources:
        if source.replaces_required_source_keys:
            raise ValueError("optional sources cannot replace required sources")
    for source in alternative_sources:
        if not source.replaces_required_source_keys:
            raise ValueError("alternative sources must identify the required sources they replace")
        if set(source.replaces_required_source_keys) != required_keys:
            raise ValueError("each alternative must replace the complete required source set")
    if bool(alternative_sources) != bool(natural_request.alternative):
        raise ValueError("alternative copy must match the presence of alternative sources")
    if bool(optional_sources) != bool(natural_request.optional_improvement):
        raise ValueError("optional-improvement copy must match optional sources")
    known_keys = set(all_keys)
    for lead in intro_leads:
        if lead.source_key not in known_keys:
            raise ValueError("intro leads must reference a requested source")
    text_fields = [
        *(
            value
            for source in all_sources
            for value in (
                source.show_or_title,
                source.episode_title or "",
                " ".join(source.characters),
                source.relationship_or_topic or "",
                source.scene_or_moment,
                source.why_it_matters_emotionally,
                source.source_quality_summary,
                source.quote.text if source.quote else "",
                source.quote.speaker if source.quote and source.quote.speaker else "",
                source.quote.likely_context
                if source.quote and source.quote.likely_context
                else "",
            )
        ),
        natural_request.best,
        natural_request.minimum,
        natural_request.alternative or "",
        natural_request.optional_improvement or "",
        *search_queries,
        *(query for source in all_sources for query in source.search_queries),
        *(
            value
            for lead in intro_leads
            for value in (
                lead.moment_description,
                lead.why_it_might_lead_into_montage,
                lead.quote.text if lead.quote else "",
                lead.quote.speaker if lead.quote and lead.quote.speaker else "",
                lead.quote.likely_context
                if lead.quote and lead.quote.likely_context
                else "",
            )
        ),
    ]
    if any(_PROHIBITED_ACQUISITION.search(value) for value in text_fields):
        raise ValueError("footage requests cannot contain prohibited acquisition instructions")
    normalized_queries = [value.casefold() for value in search_queries]
    if len(normalized_queries) != len(set(normalized_queries)):
        raise ValueError("footage request search queries must be unique")


class FootageRequestDraftV2(StrictContract):
    schema_version: Literal["2.0.0"] = "2.0.0"
    summary: NonEmptyText
    natural_request: NaturalFootageRequestV2
    required_sources: Annotated[list[RequestedSourceDraftV2], Field(min_length=1, max_length=30)]
    optional_sources: Annotated[list[RequestedSourceDraftV2], Field(default_factory=list, max_length=30)]
    alternative_sources: Annotated[list[RequestedSourceDraftV2], Field(default_factory=list, max_length=30)]
    minimum_useful_source_keys: Annotated[list[SourceKey], Field(min_length=1, max_length=30)]
    smallest_useful_set_reason: NonEmptyText
    intro_leads: Annotated[list[IntroMaterialLeadDraftV2], Field(default_factory=list, max_length=20)]
    search_queries: Annotated[list[ShortText], Field(min_length=1, max_length=30)]
    warnings: Annotated[list[ShortText], Field(default_factory=list, max_length=20)]

    @model_validator(mode="after")
    def validate_request(self) -> Self:
        _validate_footage_request(
            natural_request=self.natural_request,
            required_sources=self.required_sources,
            optional_sources=self.optional_sources,
            alternative_sources=self.alternative_sources,
            minimum_useful_source_keys=self.minimum_useful_source_keys,
            intro_leads=self.intro_leads,
            search_queries=self.search_queries,
        )
        if _PROHIBITED_ACQUISITION.search(self.summary) or _PROHIBITED_ACQUISITION.search(
            self.smallest_useful_set_reason
        ) or any(_PROHIBITED_ACQUISITION.search(value) for value in self.warnings):
            raise ValueError("footage requests cannot contain prohibited acquisition instructions")
        return self


class FootageRequestV2(StrictContract):
    schema_version: Literal["2.0.0"] = "2.0.0"
    footage_request_id: UUID4
    opportunity_id: UUID4
    summary: NonEmptyText
    natural_request: NaturalFootageRequestV2
    required_sources: Annotated[list[RequestedSourceV2], Field(min_length=1, max_length=30)]
    optional_sources: Annotated[list[RequestedSourceV2], Field(default_factory=list, max_length=30)]
    alternative_sources: Annotated[list[RequestedSourceV2], Field(default_factory=list, max_length=30)]
    minimum_useful_source_keys: Annotated[list[SourceKey], Field(min_length=1, max_length=30)]
    smallest_useful_set_reason: NonEmptyText
    intro_leads: Annotated[list[IntroMaterialLeadV2], Field(default_factory=list, max_length=20)]
    search_queries: Annotated[list[ShortText], Field(min_length=1, max_length=30)]
    warnings: Annotated[list[ShortText], Field(default_factory=list, max_length=20)]

    @model_validator(mode="after")
    def validate_request(self) -> Self:
        _validate_footage_request(
            natural_request=self.natural_request,
            required_sources=list(self.required_sources),
            optional_sources=list(self.optional_sources),
            alternative_sources=list(self.alternative_sources),
            minimum_useful_source_keys=self.minimum_useful_source_keys,
            intro_leads=list(self.intro_leads),
            search_queries=self.search_queries,
        )
        source_ids = [
            source.requested_source_id
            for source in [
                *self.required_sources,
                *self.optional_sources,
                *self.alternative_sources,
            ]
        ]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("requested source IDs must be globally unique")
        intro_ids = [lead.intro_lead_id for lead in self.intro_leads]
        if len(intro_ids) != len(set(intro_ids)):
            raise ValueError("intro lead IDs must be unique")
        if _PROHIBITED_ACQUISITION.search(self.summary) or _PROHIBITED_ACQUISITION.search(
            self.smallest_useful_set_reason
        ) or any(_PROHIBITED_ACQUISITION.search(value) for value in self.warnings):
            raise ValueError("footage requests cannot contain prohibited acquisition instructions")
        return self


class SynthesisRecommendationDraftV2(StrictContract):
    """One untrusted recommendation pair produced from an evidence allow-list."""

    opportunity: TrendOpportunityDraftV2
    footage_request: FootageRequestDraftV2


class ResearchSynthesisDraftV2(StrictContract):
    """Bounded synthesis result; canonicalization may still reject every draft."""

    schema_version: Literal["2.0.0"] = "2.0.0"
    recommendations: Annotated[
        list[SynthesisRecommendationDraftV2], Field(default_factory=list, max_length=10)
    ]
    no_strong_opportunity_reason: Annotated[str | None, Field(max_length=1_000)] = None

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        if self.recommendations and self.no_strong_opportunity_reason is not None:
            raise ValueError("recommendations and a no-opportunity reason are exclusive")
        if not self.recommendations and not self.no_strong_opportunity_reason:
            raise ValueError("empty synthesis requires a no-opportunity reason")
        return self


class ResearchResultStatus(str, Enum):
    OPPORTUNITIES = "OPPORTUNITIES"
    NO_STRONG_OPPORTUNITY = "NO_STRONG_OPPORTUNITY"


class ResearchResultV2(StrictContract):
    schema_version: Literal["2.0.0"] = "2.0.0"
    run_id: UUID4
    status: ResearchResultStatus
    intent: ResearchIntentV2
    opportunities: Annotated[list[TrendOpportunityV2], Field(default_factory=list, max_length=10)]
    footage_requests: Annotated[list[FootageRequestV2], Field(default_factory=list, max_length=10)]
    message: NonEmptyText
    applied_exclusions: Annotated[list[ShortText], Field(default_factory=list, max_length=30)]
    warnings: Annotated[list[ShortText], Field(default_factory=list, max_length=30)]
    generated_at: AwareDatetime

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if len(self.opportunities) > self.intent.max_results:
            raise ValueError("result exceeds the intent's maximum opportunity count")
        if any(item.media_kind not in self.intent.media_kinds for item in self.opportunities):
            raise ValueError("result contains a media kind outside the intent")
        if self.status is ResearchResultStatus.NO_STRONG_OPPORTUNITY:
            if self.opportunities or self.footage_requests:
                raise ValueError("NO_STRONG_OPPORTUNITY must not carry recommendations")
        elif not self.opportunities:
            raise ValueError("OPPORTUNITIES requires at least one opportunity")
        if len(self.opportunities) != len(self.footage_requests):
            raise ValueError("each opportunity must have exactly one footage request")
        opportunity_ids = {item.opportunity_id for item in self.opportunities}
        request_ids = {item.footage_request_id for item in self.footage_requests}
        if len(opportunity_ids) != len(self.opportunities):
            raise ValueError("opportunity IDs must be unique")
        if len(request_ids) != len(self.footage_requests):
            raise ValueError("footage request IDs must be unique")
        for opportunity in self.opportunities:
            matching = [
                request
                for request in self.footage_requests
                if request.opportunity_id == opportunity.opportunity_id
                and request.footage_request_id == opportunity.footage_request_id
            ]
            if len(matching) != 1:
                raise ValueError("opportunity and footage request links must be one-to-one")
        normalized_exclusions = [value.casefold() for value in self.applied_exclusions]
        if normalized_exclusions != [value.casefold() for value in self.intent.exclusions]:
            raise ValueError("applied exclusions must exactly preserve the normalized intent")
        return self


PROVIDER_OUTPUT_CONTRACTS_V2: dict[str, type[StrictContract]] = {
    "research-intent": ResearchIntentV2,
    "trend-opportunity-draft": TrendOpportunityDraftV2,
    "footage-request-draft": FootageRequestDraftV2,
    "research-synthesis-draft": ResearchSynthesisDraftV2,
}

CANONICAL_STORAGE_CONTRACTS_V2: dict[str, type[StrictContract]] = {
    "research-intent": ResearchIntentV2,
    "evidence-source": EvidenceSourceRecordV2,
    "evidence-claim": EvidenceClaimRecordV2,
    "trend-opportunity": TrendOpportunityV2,
    "footage-request": FootageRequestV2,
    "research-result": ResearchResultV2,
}
