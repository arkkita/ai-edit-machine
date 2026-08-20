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


class IntentFacetCategory(str, Enum):
    HARD_CONSTRAINT = "HARD_CONSTRAINT"
    SOFT_PREFERENCE = "SOFT_PREFERENCE"
    AUDIENCE = "AUDIENCE"
    PLATFORM_FIT = "PLATFORM_FIT"
    CREATIVE_EDIT = "CREATIVE_EDIT"


class IntentFacetSource(str, Enum):
    EXPLICIT = "EXPLICIT"
    INFERRED_PRIOR = "INFERRED_PRIOR"


class IntentFacetV1(StrictContract):
    facet_id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")]
    category: IntentFacetCategory
    label: Annotated[str, Field(min_length=1, max_length=80)]
    source: IntentFacetSource
    removable: bool = True
    rationale: Annotated[str, Field(min_length=1, max_length=300)]


class IntentSearchQuestionV1(StrictContract):
    question_id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")]
    query: Annotated[str, Field(min_length=1, max_length=500)]
    evidence_goal: Annotated[str, Field(min_length=1, max_length=300)]


class UserIntentInterpretationV1(StrictContract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    facets: Annotated[list[IntentFacetV1], Field(default_factory=list, max_length=30)]
    search_questions: Annotated[
        list[IntentSearchQuestionV1], Field(default_factory=list, max_length=20)
    ]
    broad_query: bool = False
    clarification_needed: bool = False
    clarification_reason: Annotated[str | None, Field(max_length=500)] = None
    direct_tiktok_data_used: bool = False
    short_form_inference_disclaimer: Annotated[
        str | None, Field(max_length=500)
    ] = None

    @model_validator(mode="after")
    def validate_interpretation(self) -> Self:
        facet_ids = [item.facet_id for item in self.facets]
        question_ids = [item.question_id for item in self.search_questions]
        if len(facet_ids) != len(set(facet_ids)):
            raise ValueError("intent facet IDs must be unique")
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("intent search-question IDs must be unique")
        if self.clarification_needed != bool(self.clarification_reason):
            raise ValueError("clarification reason must match clarification-needed state")
        if self.direct_tiktok_data_used and self.short_form_inference_disclaimer:
            raise ValueError("direct TikTok data and a proxy-only disclaimer are exclusive")
        return self


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
    interpretation: UserIntentInterpretationV1 | None = None

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


class CandidateFunnelRejectionV1(StrictContract):
    reason_code: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9:._-]{0,119}$")]
    count: Annotated[int, Field(ge=1, le=1_000_000)]


class CandidateFailureClass(str, Enum):
    RETRIEVAL_RELATED = "RETRIEVAL_RELATED"
    EVIDENCE_RELATED = "EVIDENCE_RELATED"
    THRESHOLD_RELATED = "THRESHOLD_RELATED"
    SUPPORTED = "SUPPORTED"


class CandidateScoreStatus(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    INFORMATIONAL = "INFORMATIONAL"
    NOT_COMPUTED = "NOT_COMPUTED"


class CandidateScoreTraceV1(StrictContract):
    metric: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,79}$")]
    value: Confidence | None = None
    count_value: Annotated[int | None, Field(ge=0, le=1_000)] = None
    threshold: Confidence | None = None
    count_threshold: Annotated[int | None, Field(ge=0, le=1_000)] = None
    status: CandidateScoreStatus
    note: ShortText

    @model_validator(mode="after")
    def validate_trace(self) -> Self:
        if self.value is not None and self.count_value is not None:
            raise ValueError("candidate metric cannot carry float and count values together")
        if self.threshold is not None and self.count_threshold is not None:
            raise ValueError("candidate metric cannot carry float and count thresholds together")
        if self.status is CandidateScoreStatus.NOT_COMPUTED and any(
            value is not None
            for value in (self.value, self.count_value)
        ):
            raise ValueError("NOT_COMPUTED candidate metrics cannot carry a value")
        return self


class CandidateDiagnosticV1(StrictContract):
    candidate_name: ShortText
    title: ShortText
    shortlist_rank: Annotated[int, Field(ge=1, le=1_000)]
    shortlist_reason: ShortText
    current_hook: ShortText | None = None
    audience_fit_evidence: Annotated[list[ShortText], Field(default_factory=list, max_length=12)]
    fandom_evidence: Annotated[list[ShortText], Field(default_factory=list, max_length=12)]
    story_or_episode_evidence: Annotated[list[ShortText], Field(default_factory=list, max_length=12)]
    source_categories: Annotated[list[ShortText], Field(default_factory=list, max_length=20)]
    evidence_references: Annotated[list[UUID4], Field(default_factory=list, max_length=40)]
    inferred_short_form_edit_potential: ShortText
    scores_and_thresholds: Annotated[
        list[CandidateScoreTraceV1], Field(min_length=1, max_length=30)
    ]
    exact_rejection_gate: Annotated[
        str, Field(pattern=r"^[A-Z][A-Z0-9_:.-]{0,159}$")
    ]
    failure_class: CandidateFailureClass

    @model_validator(mode="after")
    def validate_candidate_diagnostic(self) -> Self:
        if len(self.evidence_references) != len(set(self.evidence_references)):
            raise ValueError("candidate diagnostic evidence references must be unique")
        metrics = [item.metric for item in self.scores_and_thresholds]
        if len(metrics) != len(set(metrics)):
            raise ValueError("candidate diagnostic metrics must be unique")
        if (
            self.failure_class is CandidateFailureClass.SUPPORTED
        ) != (self.exact_rejection_gate == "SUPPORTED"):
            raise ValueError("supported candidate diagnostics must use the SUPPORTED gate")
        return self


class CandidateFunnelV1(StrictContract):
    """Persistable M1.1 candidate funnel and sanitized title-level diagnostics."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    parsed_intent: Annotated[int, Field(ge=0, le=1)]
    generated_search_variants: Annotated[int, Field(ge=0, le=1_000)]
    raw_release_candidates: Annotated[int, Field(ge=0, le=1_000_000)]
    candidates_after_freshness: Annotated[int, Field(ge=0, le=1_000_000)]
    candidates_after_hard_exclusions: Annotated[int, Field(ge=0, le=1_000_000)]
    candidates_after_audience_fit_screening: Annotated[int, Field(ge=0, le=1_000_000)]
    candidates_selected_for_social_research: Annotated[int, Field(ge=0, le=1_000)]
    candidates_with_usable_social_evidence: Annotated[int, Field(ge=0, le=1_000)]
    candidates_surviving_evidence_gates: Annotated[int, Field(ge=0, le=1_000)]
    candidates_surviving_deduplication: Annotated[int, Field(ge=0, le=1_000)]
    candidates_sent_to_final_ranker: Annotated[int, Field(ge=0, le=1_000)]
    final_opportunities_serialized: Annotated[int, Field(ge=0, le=10)]
    removed_by_hard_constraints: Annotated[int, Field(ge=0, le=1_000_000)]
    lacking_current_fandom_evidence: Annotated[int, Field(ge=0, le=1_000)]
    lacking_actionable_footage_information: Annotated[int, Field(ge=0, le=1_000)]
    false_abstention_recovery_attempted: bool = False
    recovered_candidate_count: Annotated[int, Field(ge=0, le=1_000)] = 0
    evidence_coverage_warning: Annotated[str | None, Field(max_length=1_000)] = None
    rejection_reasons: Annotated[
        list[CandidateFunnelRejectionV1], Field(default_factory=list, max_length=50)
    ]
    candidate_diagnostics: Annotated[
        list[CandidateDiagnosticV1], Field(default_factory=list, max_length=30)
    ]
    shortage_explanation: Annotated[str | None, Field(max_length=1_000)] = None
    suggestions: Annotated[list[ShortText], Field(default_factory=list, max_length=10)]

    @model_validator(mode="after")
    def validate_funnel(self) -> Self:
        if self.final_opportunities_serialized >= 3 and self.shortage_explanation is not None:
            raise ValueError("shortage explanation is only valid below three opportunities")
        if not self.false_abstention_recovery_attempted and (
            self.recovered_candidate_count or self.evidence_coverage_warning is not None
        ):
            raise ValueError("recovery diagnostics require an attempted recovery pass")
        if self.final_opportunities_serialized and self.evidence_coverage_warning is not None:
            raise ValueError("evidence-coverage warning is only valid after recovery still yields no result")
        reason_codes = [item.reason_code for item in self.rejection_reasons]
        if len(reason_codes) != len(set(reason_codes)):
            raise ValueError("candidate-funnel rejection codes must be unique")
        diagnostic_titles = [item.title.casefold() for item in self.candidate_diagnostics]
        if len(diagnostic_titles) != len(set(diagnostic_titles)):
            raise ValueError("candidate diagnostics must have unique titles")
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


class OpportunityRankingWeightsV1(StrictContract):
    intent_fit: Confidence
    audience_fit: Confidence
    freshness: Confidence
    fandom_velocity: Confidence
    short_form_edit_potential: Confidence
    relationship_or_character_salience: Confidence
    footage_actionability: Confidence
    evidence_quality: Confidence
    source_diversity: Confidence
    uncertainty_penalty: Confidence

    @model_validator(mode="after")
    def validate_weights(self) -> Self:
        positive = (
            self.intent_fit
            + self.audience_fit
            + self.freshness
            + self.fandom_velocity
            + self.short_form_edit_potential
            + self.relationship_or_character_salience
            + self.footage_actionability
            + self.evidence_quality
            + self.source_diversity
        )
        if abs(positive - 1.0) > 1e-9:
            raise ValueError("positive opportunity-ranking weights must sum to one")
        return self


class OpportunityQualityScoreV1(StrictContract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    profile_id: Annotated[str, Field(min_length=1, max_length=100)]
    intent_fit: Confidence
    audience_fit: Confidence
    freshness: Confidence
    fandom_velocity: Confidence
    short_form_edit_potential: Confidence
    relationship_or_character_salience: Confidence
    footage_actionability: Confidence
    evidence_quality: Confidence
    source_diversity: Confidence
    uncertainty_penalty: Confidence
    weights: OpportunityRankingWeightsV1
    total: Confidence

    @model_validator(mode="after")
    def validate_weighted_total(self) -> Self:
        weighted = sum(
            (
                self.intent_fit * self.weights.intent_fit,
                self.audience_fit * self.weights.audience_fit,
                self.freshness * self.weights.freshness,
                self.fandom_velocity * self.weights.fandom_velocity,
                self.short_form_edit_potential
                * self.weights.short_form_edit_potential,
                self.relationship_or_character_salience
                * self.weights.relationship_or_character_salience,
                self.footage_actionability * self.weights.footage_actionability,
                self.evidence_quality * self.weights.evidence_quality,
                self.source_diversity * self.weights.source_diversity,
            )
        )
        expected = max(
            0.0,
            min(1.0, weighted - self.uncertainty_penalty * self.weights.uncertainty_penalty),
        )
        if abs(expected - self.total) > 1e-9:
            raise ValueError("quality total must match its recorded weighted components")
        return self


class ShortFormPotentialBand(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class ShortFormEditPotentialV1(StrictContract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    metric_name: Literal["SHORT_FORM_EDIT_POTENTIAL"] = "SHORT_FORM_EDIT_POTENTIAL"
    band: ShortFormPotentialBand
    direct_tiktok_data_used: Literal[False] = False
    explanation: NonEmptyText
    signals: Annotated[list[ShortText], Field(min_length=1, max_length=12)]
    supporting_claim_ids: Annotated[list[UUID4], Field(min_length=1, max_length=30)]
    disclaimer: Literal[
        "TikTok potential is inferred from cross-platform fandom and editability signals. Direct TikTok trend data was not used."
    ] = (
        "TikTok potential is inferred from cross-platform fandom and editability signals. Direct TikTok trend data was not used."
    )

    @model_validator(mode="after")
    def validate_signal_ids(self) -> Self:
        if len(self.supporting_claim_ids) != len(set(self.supporting_claim_ids)):
            raise ValueError("short-form supporting claim IDs must be unique")
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
_GENERIC_EDITORIAL_PLACEHOLDER = re.compile(
    r"\b(?:current\s+character\s+discussion|any\s+relevant\s+material|"
    r"exact\s+scene\s+(?:is\s+)?unknown|clips?\s+from\s+(?:this|the)\s+show|"
    r"intro\s*\+\s*montage\s*\+\s*payoff|use\s+scenes?\s+involving\s+the\s+main\s+character|"
    r"find\s+emotional\s+footage)\b",
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
    dossier_id: UUID4 | None = None
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
    quality_score: OpportunityQualityScoreV1 | None = None
    short_form_edit_potential: ShortFormEditPotentialV1 | None = None
    recommended_concept_id: UUID4 | None = None
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
    if any(_GENERIC_EDITORIAL_PLACEHOLDER.search(value) for value in text_fields):
        raise ValueError("generic footage placeholders fail the M1.1b quality gate")
    normalized_queries = [value.casefold() for value in search_queries]
    if len(normalized_queries) != len(set(normalized_queries)):
        raise ValueError("footage request search queries must be unique")


class FootageRequestDraftV2(StrictContract):
    schema_version: Literal["2.0.0"] = "2.0.0"
    concept_key: SourceKey | None = None
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
    concept_id: UUID4 | None = None
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


class LegacyConnectionType(str, Enum):
    NONE = "NONE"
    SAME_CHARACTER = "SAME_CHARACTER"
    SAME_CANONICAL_UNIVERSE = "SAME_CANONICAL_UNIVERSE"
    EXPLICIT_CALLBACK = "EXPLICIT_CALLBACK"
    THEMATIC_PARALLEL = "THEMATIC_PARALLEL"
    ACTOR_CONNECTION_ONLY = "ACTOR_CONNECTION_ONLY"
    FAN_INTERPRETATION = "FAN_INTERPRETATION"
    UNSUPPORTED_SPECULATION = "UNSUPPORTED_SPECULATION"


class DossierCurrentSourceKind(str, Enum):
    EPISODE = "EPISODE"
    SEASON = "SEASON"
    TRAILER = "TRAILER"
    OFFICIAL_CLIP = "OFFICIAL_CLIP"
    ANNOUNCEMENT = "ANNOUNCEMENT"
    INTERVIEW = "INTERVIEW"
    ARTICLE = "ARTICLE"
    OTHER = "OTHER"


class DossierEvidenceFactV1(StrictContract):
    text: NonEmptyText
    verification_status: FootageVerificationLevel
    supporting_claim_ids: Annotated[list[UUID4], Field(min_length=1, max_length=30)]

    @model_validator(mode="after")
    def validate_support(self) -> Self:
        if len(self.supporting_claim_ids) != len(set(self.supporting_claim_ids)):
            raise ValueError("dossier fact supporting claim IDs must be unique")
        if _PROHIBITED_ACQUISITION.search(self.text):
            raise ValueError("dossier facts cannot contain prohibited acquisition instructions")
        return self


class DossierCharacterV1(StrictContract):
    character_name: ShortText
    performer_name: Annotated[str | None, Field(max_length=200)] = None
    show_or_title: ShortText
    verification_status: FootageVerificationLevel
    supporting_claim_ids: Annotated[list[UUID4], Field(min_length=1, max_length=20)]

    @model_validator(mode="after")
    def validate_support(self) -> Self:
        if len(self.supporting_claim_ids) != len(set(self.supporting_claim_ids)):
            raise ValueError("dossier character supporting claim IDs must be unique")
        return self


class DossierCurrentSourceV1(StrictContract):
    source_kind: DossierCurrentSourceKind
    show_or_title: ShortText
    source_title: ShortText
    season_number: Annotated[int | None, Field(ge=0, le=MAX_SEASON_NUMBER)] = None
    episode_number: Annotated[int | None, Field(ge=1, le=9_999)] = None
    episode_title: Annotated[str | None, Field(max_length=500)] = None
    verification_status: FootageVerificationLevel
    supporting_claim_ids: Annotated[list[UUID4], Field(min_length=1, max_length=30)]

    @model_validator(mode="after")
    def validate_locator(self) -> Self:
        if (self.season_number is None) != (self.episode_number is None):
            raise ValueError("dossier season and episode numbers must be supplied together")
        if self.source_kind is DossierCurrentSourceKind.EPISODE and self.season_number is None:
            raise ValueError("dossier episode source requires an exact supported locator")
        if self.source_kind is not DossierCurrentSourceKind.EPISODE and any(
            value is not None
            for value in (self.season_number, self.episode_number, self.episode_title)
        ):
            raise ValueError("only an episode dossier source may carry an episode locator")
        if len(self.supporting_claim_ids) != len(set(self.supporting_claim_ids)):
            raise ValueError("dossier current-source claim IDs must be unique")
        return self


class DossierQuoteLeadV1(StrictContract):
    quote: FootageQuoteV2
    source_title: ShortText
    verification_status: FootageVerificationLevel
    supporting_claim_ids: Annotated[list[UUID4], Field(min_length=1, max_length=20)]

    @model_validator(mode="after")
    def validate_quote_support(self) -> Self:
        if self.quote.claim_id not in self.supporting_claim_ids:
            raise ValueError("dossier quote claim must be in its supporting evidence")
        if len(self.supporting_claim_ids) != len(set(self.supporting_claim_ids)):
            raise ValueError("dossier quote supporting claim IDs must be unique")
        return self


class DossierFranchiseConnectionV1(StrictContract):
    connection_type: LegacyConnectionType
    current_title: ShortText
    connected_title: ShortText
    characters: Annotated[list[ShortText], Field(default_factory=list, max_length=20)]
    description: NonEmptyText
    verification_status: FootageVerificationLevel
    supporting_claim_ids: Annotated[list[UUID4], Field(min_length=1, max_length=30)]

    @model_validator(mode="after")
    def validate_connection(self) -> Self:
        if self.connection_type is LegacyConnectionType.UNSUPPORTED_SPECULATION:
            raise ValueError("unsupported franchise speculation cannot enter a dossier")
        if self.connection_type is LegacyConnectionType.NONE:
            raise ValueError("a dossier connection record must describe a real connection type")
        if (
            self.connection_type is LegacyConnectionType.FAN_INTERPRETATION
            and self.verification_status
            in {
                FootageVerificationLevel.VERIFIED,
                FootageVerificationLevel.STRONGLY_SUPPORTED,
            }
        ):
            raise ValueError("fan interpretation cannot be presented as verified canon")
        if len(self.supporting_claim_ids) != len(set(self.supporting_claim_ids)):
            raise ValueError("dossier connection supporting claim IDs must be unique")
        return self


def _dossier_supporting_claim_ids(
    *,
    current_event_or_hook: DossierEvidenceFactV1,
    named_characters: list[DossierCharacterV1],
    central_relationship: DossierEvidenceFactV1 | None,
    current_source: DossierCurrentSourceV1,
    exact_or_likely_quote: DossierQuoteLeadV1 | None,
    franchise_connections: list[DossierFranchiseConnectionV1],
    relationship_or_character_history: list[DossierEvidenceFactV1],
    why_fans_currently_care: list[DossierEvidenceFactV1],
    audience_and_fandom_evidence: list[DossierEvidenceFactV1],
) -> set[UUID4]:
    values: list[UUID4] = [
        *current_event_or_hook.supporting_claim_ids,
        *current_source.supporting_claim_ids,
    ]
    for character in named_characters:
        values.extend(character.supporting_claim_ids)
    for fact in (
        central_relationship,
        *relationship_or_character_history,
        *why_fans_currently_care,
        *audience_and_fandom_evidence,
    ):
        if fact is not None:
            values.extend(fact.supporting_claim_ids)
    if exact_or_likely_quote is not None:
        values.extend(exact_or_likely_quote.supporting_claim_ids)
    for connection in franchise_connections:
        values.extend(connection.supporting_claim_ids)
    return set(values)


class FandomStoryDossierDraftV1(StrictContract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    dossier_key: SourceKey
    show_or_title: ShortText
    current_event_or_hook: DossierEvidenceFactV1
    named_characters: Annotated[list[DossierCharacterV1], Field(min_length=1, max_length=30)]
    central_relationship: DossierEvidenceFactV1 | None = None
    current_source: DossierCurrentSourceV1
    exact_or_likely_quote: DossierQuoteLeadV1 | None = None
    franchise_connections: Annotated[
        list[DossierFranchiseConnectionV1], Field(default_factory=list, max_length=20)
    ]
    relationship_or_character_history: Annotated[
        list[DossierEvidenceFactV1], Field(default_factory=list, max_length=20)
    ]
    why_fans_currently_care: Annotated[
        list[DossierEvidenceFactV1], Field(min_length=1, max_length=20)
    ]
    audience_and_fandom_evidence: Annotated[
        list[DossierEvidenceFactV1], Field(min_length=1, max_length=20)
    ]
    uncertainties: Annotated[list[ShortText], Field(default_factory=list, max_length=30)]
    evidence: Annotated[
        list[OpportunityEvidenceSelectionV2], Field(min_length=1, max_length=60)
    ]

    @model_validator(mode="after")
    def validate_dossier(self) -> Self:
        evidence_ids = {item.claim_id for item in self.evidence}
        if len(evidence_ids) != len(self.evidence):
            raise ValueError("dossier evidence claim IDs must be unique")
        referenced = _dossier_supporting_claim_ids(
            current_event_or_hook=self.current_event_or_hook,
            named_characters=self.named_characters,
            central_relationship=self.central_relationship,
            current_source=self.current_source,
            exact_or_likely_quote=self.exact_or_likely_quote,
            franchise_connections=self.franchise_connections,
            relationship_or_character_history=self.relationship_or_character_history,
            why_fans_currently_care=self.why_fans_currently_care,
            audience_and_fandom_evidence=self.audience_and_fandom_evidence,
        )
        if not referenced.issubset(evidence_ids):
            raise ValueError("every dossier fact must reference dossier evidence")
        character_keys = [item.character_name.casefold() for item in self.named_characters]
        if len(character_keys) != len(set(character_keys)):
            raise ValueError("dossier named characters must be unique")
        if any(_GENERIC_EDITORIAL_PLACEHOLDER.search(value) for value in (
            self.current_event_or_hook.text,
            *(item.text for item in self.why_fans_currently_care),
            *(item.text for item in self.audience_and_fandom_evidence),
        )):
            raise ValueError("generic placeholders cannot enter a fandom/story dossier")
        return self


class FandomStoryDossierV1(StrictContract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    dossier_id: UUID4
    opportunity_id: UUID4
    dossier_key: SourceKey
    show_or_title: ShortText
    current_event_or_hook: DossierEvidenceFactV1
    named_characters: Annotated[list[DossierCharacterV1], Field(min_length=1, max_length=30)]
    central_relationship: DossierEvidenceFactV1 | None = None
    current_source: DossierCurrentSourceV1
    exact_or_likely_quote: DossierQuoteLeadV1 | None = None
    franchise_connections: Annotated[
        list[DossierFranchiseConnectionV1], Field(default_factory=list, max_length=20)
    ]
    relationship_or_character_history: Annotated[
        list[DossierEvidenceFactV1], Field(default_factory=list, max_length=20)
    ]
    why_fans_currently_care: Annotated[
        list[DossierEvidenceFactV1], Field(min_length=1, max_length=20)
    ]
    audience_and_fandom_evidence: Annotated[
        list[DossierEvidenceFactV1], Field(min_length=1, max_length=20)
    ]
    uncertainties: Annotated[list[ShortText], Field(default_factory=list, max_length=30)]
    evidence: Annotated[
        list[TrustedOpportunityEvidenceReferenceV2], Field(min_length=1, max_length=60)
    ]

    @model_validator(mode="after")
    def validate_dossier(self) -> Self:
        evidence_ids = {item.claim_id for item in self.evidence}
        if len(evidence_ids) != len(self.evidence):
            raise ValueError("canonical dossier evidence claim IDs must be unique")
        referenced = _dossier_supporting_claim_ids(
            current_event_or_hook=self.current_event_or_hook,
            named_characters=self.named_characters,
            central_relationship=self.central_relationship,
            current_source=self.current_source,
            exact_or_likely_quote=self.exact_or_likely_quote,
            franchise_connections=self.franchise_connections,
            relationship_or_character_history=self.relationship_or_character_history,
            why_fans_currently_care=self.why_fans_currently_care,
            audience_and_fandom_evidence=self.audience_and_fandom_evidence,
        )
        if not referenced.issubset(evidence_ids):
            raise ValueError("canonical dossier facts must reference canonical evidence")
        return self


class EditorialConceptScoreV1(StrictContract):
    concept_specificity: Confidence
    intro_strength: Confidence
    emotional_arc_strength: Confidence
    narrative_bridge_strength: Confidence
    fan_recognition: Confidence
    current_event_relevance: Confidence
    legacy_context_value: Confidence
    payoff_strength: Confidence
    footage_feasibility: Confidence
    source_actionability: Confidence
    originality: Confidence
    evidence_quality: Confidence
    uncertainty_penalty: Confidence
    total: Confidence

    @model_validator(mode="after")
    def validate_total(self) -> Self:
        positives = (
            self.concept_specificity,
            self.intro_strength,
            self.emotional_arc_strength,
            self.narrative_bridge_strength,
            self.fan_recognition,
            self.current_event_relevance,
            self.legacy_context_value,
            self.payoff_strength,
            self.footage_feasibility,
            self.source_actionability,
            self.originality,
            self.evidence_quality,
        )
        expected = max(0.0, min(1.0, sum(positives) / len(positives) - 0.25 * self.uncertainty_penalty))
        if abs(expected - self.total) > 1e-9:
            raise ValueError("editorial-concept total must match its recorded components")
        return self


_GENERIC_CONCEPT = re.compile(
    r"^(?:this\s+show\s+is\s+(?:current|trending)[.!]?\s*)?"
    r"(?:get|use|find)\s+(?:clips?|scenes?|a\s+scene\s+pack)\s+from\s+(?:this|the)\s+show",
    re.IGNORECASE,
)


class EditorialConceptDraftV1(StrictContract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    concept_key: SourceKey
    dossier_key: SourceKey
    title: ShortText
    central_subject: NonEmptyText
    central_relationship: Annotated[str | None, Field(max_length=500)] = None
    core_emotion: ShortText
    viewer_hook: NonEmptyText
    why_fans_may_care: NonEmptyText
    current_event: NonEmptyText
    legacy_or_contextual_connection: NonEmptyText
    legacy_connection_type: LegacyConnectionType = LegacyConnectionType.NONE
    intro_leads: Annotated[list[IntroMaterialLeadDraftV2], Field(min_length=1, max_length=3)]
    song_handoff_idea: NonEmptyText
    montage_arc: Annotated[list[NonEmptyText], Field(min_length=3, max_length=6)]
    ending_or_payoff: NonEmptyText
    evidence: Annotated[
        list[OpportunityEvidenceSelectionV2], Field(min_length=1, max_length=30)
    ]
    verification_status: FootageVerificationLevel
    creative_strength: Confidence
    footage_feasibility: Confidence
    known_uncertainties: Annotated[list[ShortText], Field(default_factory=list, max_length=20)]
    footage_request: FootageRequestDraftV2

    @model_validator(mode="after")
    def validate_concept(self) -> Self:
        claim_ids = [item.claim_id for item in self.evidence]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("editorial-concept evidence IDs must be unique")
        if len({value.casefold() for value in self.montage_arc}) != len(self.montage_arc):
            raise ValueError("montage beats must be distinct")
        if self.intro_leads != self.footage_request.intro_leads:
            raise ValueError("concept intro leads must match its footage request")
        if self.footage_request.concept_key != self.concept_key:
            raise ValueError("concept footage request must reference its concept key")
        if self.legacy_connection_type is LegacyConnectionType.UNSUPPORTED_SPECULATION:
            raise ValueError("unsupported franchise speculation cannot become a concept")
        if (
            self.legacy_connection_type is LegacyConnectionType.FAN_INTERPRETATION
            and self.verification_status
            in {
                FootageVerificationLevel.VERIFIED,
                FootageVerificationLevel.STRONGLY_SUPPORTED,
            }
        ):
            raise ValueError("fan interpretation cannot be presented as verified canon")
        specific_copy = " ".join(
            (
                self.central_subject,
                self.viewer_hook,
                self.current_event,
                self.song_handoff_idea,
                *self.montage_arc,
                self.ending_or_payoff,
            )
        ).strip()
        if _GENERIC_CONCEPT.search(specific_copy) or _GENERIC_EDITORIAL_PLACEHOLDER.search(specific_copy):
            raise ValueError("generic get-clips concepts fail the M1.1 quality gate")
        if any(_PROHIBITED_ACQUISITION.search(value) for value in (
            self.title,
            specific_copy,
            self.why_fans_may_care,
            self.legacy_or_contextual_connection,
            *self.known_uncertainties,
        )):
            raise ValueError("editorial concepts cannot contain prohibited acquisition instructions")
        return self


class EditorialConceptV1(StrictContract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    concept_id: UUID4
    opportunity_id: UUID4
    dossier_id: UUID4
    concept_key: SourceKey
    title: ShortText
    central_subject: NonEmptyText
    central_relationship: Annotated[str | None, Field(max_length=500)] = None
    core_emotion: ShortText
    viewer_hook: NonEmptyText
    why_fans_may_care: NonEmptyText
    current_event: NonEmptyText
    legacy_or_contextual_connection: NonEmptyText
    legacy_connection_type: LegacyConnectionType
    intro_leads: Annotated[list[IntroMaterialLeadV2], Field(min_length=1, max_length=3)]
    song_handoff_idea: NonEmptyText
    montage_arc: Annotated[list[NonEmptyText], Field(min_length=3, max_length=6)]
    ending_or_payoff: NonEmptyText
    evidence: Annotated[
        list[TrustedOpportunityEvidenceReferenceV2], Field(min_length=1, max_length=30)
    ]
    verification_status: FootageVerificationLevel
    score: EditorialConceptScoreV1
    known_uncertainties: Annotated[list[ShortText], Field(default_factory=list, max_length=20)]
    footage_request: FootageRequestV2
    provisional_notice: Literal[
        "This concept is based on current story and fandom evidence. Once you provide the footage, the video analyzer will verify whether the proposed intro, quote, reactions, and montage material are actually present and usable."
    ] = (
        "This concept is based on current story and fandom evidence. Once you provide the footage, the video analyzer will verify whether the proposed intro, quote, reactions, and montage material are actually present and usable."
    )

    @model_validator(mode="after")
    def validate_links(self) -> Self:
        if self.footage_request.opportunity_id != self.opportunity_id:
            raise ValueError("concept footage request must belong to its opportunity")
        if self.footage_request.concept_id != self.concept_id:
            raise ValueError("concept footage request must reference its concept ID")
        if self.intro_leads != self.footage_request.intro_leads:
            raise ValueError("canonical concept intro leads must match its footage request")
        return self


class SynthesisRecommendationDraftV2(StrictContract):
    """One untrusted recommendation pair produced from an evidence allow-list."""

    opportunity: TrendOpportunityDraftV2
    fandom_story_dossier: FandomStoryDossierDraftV1
    editorial_concepts: Annotated[
        list[EditorialConceptDraftV1], Field(min_length=1, max_length=4)
    ]
    recommended_concept_key: SourceKey

    @model_validator(mode="after")
    def validate_concept_selection(self) -> Self:
        keys = [item.concept_key for item in self.editorial_concepts]
        if len(keys) != len(set(keys)):
            raise ValueError("editorial concept keys must be unique")
        if self.recommended_concept_key not in keys:
            raise ValueError("recommended concept key must identify a supplied concept")
        if any(
            item.dossier_key != self.fandom_story_dossier.dossier_key
            for item in self.editorial_concepts
        ):
            raise ValueError("editorial concepts must reference the recommendation dossier")
        if any(
            item.footage_request.concept_key != item.concept_key
            for item in self.editorial_concepts
        ):
            raise ValueError("every concept-specific footage request must reference its concept")
        dossier_ids = {item.claim_id for item in self.fandom_story_dossier.evidence}
        if any(
            not {selection.claim_id for selection in item.evidence}.issubset(dossier_ids)
            for item in self.editorial_concepts
        ):
            raise ValueError("editorial concepts may use only dossier evidence")
        return self


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
    fandom_story_dossiers: Annotated[
        list[FandomStoryDossierV1], Field(default_factory=list, max_length=10)
    ]
    footage_requests: Annotated[list[FootageRequestV2], Field(default_factory=list, max_length=10)]
    editorial_concepts: Annotated[
        list[EditorialConceptV1], Field(default_factory=list, max_length=40)
    ]
    candidate_funnel: CandidateFunnelV1 | None = None
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
            if (
                self.opportunities
                or self.fandom_story_dossiers
                or self.editorial_concepts
                or self.footage_requests
            ):
                raise ValueError("NO_STRONG_OPPORTUNITY must not carry recommendations")
        elif not self.opportunities:
            raise ValueError("OPPORTUNITIES requires at least one opportunity")
        if len(self.opportunities) != len(self.footage_requests):
            raise ValueError("each opportunity must have exactly one footage request")
        if len(self.opportunities) != len(self.fandom_story_dossiers):
            raise ValueError("each opportunity must have exactly one fandom/story dossier")
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
        concept_ids = [item.concept_id for item in self.editorial_concepts]
        if len(concept_ids) != len(set(concept_ids)):
            raise ValueError("editorial concept IDs must be unique")
        concept_request_ids = [
            item.footage_request.footage_request_id
            for item in self.editorial_concepts
        ]
        if len(concept_request_ids) != len(set(concept_request_ids)):
            raise ValueError("concept footage request IDs must be unique")
        dossier_ids = {item.dossier_id for item in self.fandom_story_dossiers}
        if len(dossier_ids) != len(self.fandom_story_dossiers):
            raise ValueError("fandom/story dossier IDs must be unique")
        for opportunity in self.opportunities:
            dossiers = [
                item
                for item in self.fandom_story_dossiers
                if item.opportunity_id == opportunity.opportunity_id
            ]
            if len(dossiers) != 1 or opportunity.dossier_id != dossiers[0].dossier_id:
                raise ValueError("opportunity must link to exactly one fandom/story dossier")
            concepts = [
                item
                for item in self.editorial_concepts
                if item.opportunity_id == opportunity.opportunity_id
            ]
            if not 1 <= len(concepts) <= 4:
                raise ValueError("each M1.1b opportunity needs one to four concepts")
            if any(item.dossier_id != dossiers[0].dossier_id for item in concepts):
                raise ValueError("every concept must be generated from its opportunity dossier")
            if opportunity.recommended_concept_id is None:
                raise ValueError("concept-bearing opportunity needs a recommended concept")
            selected = [
                item
                for item in concepts
                if item.concept_id == opportunity.recommended_concept_id
            ]
            if len(selected) != 1:
                raise ValueError("recommended concept must belong to the opportunity")
            selected_request = selected[0].footage_request
            if (
                selected_request.footage_request_id != opportunity.footage_request_id
                or selected_request.concept_id != selected[0].concept_id
                or selected_request not in self.footage_requests
            ):
                raise ValueError("selected concept must own the opportunity footage request")
        if any(
            item.opportunity_id not in opportunity_ids
            for item in (*self.editorial_concepts, *self.fandom_story_dossiers)
        ):
            raise ValueError("dossier or editorial concept belongs to an unknown opportunity")
        normalized_exclusions = [value.casefold() for value in self.applied_exclusions]
        if normalized_exclusions != [value.casefold() for value in self.intent.exclusions]:
            raise ValueError("applied exclusions must exactly preserve the normalized intent")
        return self


PROVIDER_OUTPUT_CONTRACTS_V2: dict[str, type[StrictContract]] = {
    "research-intent": ResearchIntentV2,
    "trend-opportunity-draft": TrendOpportunityDraftV2,
    "footage-request-draft": FootageRequestDraftV2,
    "fandom-story-dossier-draft": FandomStoryDossierDraftV1,
    "editorial-concept-draft": EditorialConceptDraftV1,
    "research-synthesis-draft": ResearchSynthesisDraftV2,
}

CANONICAL_STORAGE_CONTRACTS_V2: dict[str, type[StrictContract]] = {
    "research-intent": ResearchIntentV2,
    "evidence-source": EvidenceSourceRecordV2,
    "evidence-claim": EvidenceClaimRecordV2,
    "trend-opportunity": TrendOpportunityV2,
    "footage-request": FootageRequestV2,
    "fandom-story-dossier": FandomStoryDossierV1,
    "editorial-concept": EditorialConceptV1,
    "research-result": ResearchResultV2,
}
