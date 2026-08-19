"""Versioned contract seeds for the Milestone 0 architecture.

The registries at the bottom deliberately separate provider-authored drafts,
canonical persisted records, and trusted execution contracts.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import ROUND_CEILING, Decimal
from enum import Enum
from fractions import Fraction
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    UUID4,
    model_validator,
)


NonEmptyText = Annotated[str, Field(min_length=1, max_length=2_000)]
ShortText = Annotated[str, Field(min_length=1, max_length=500)]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]
MicroUsd = Annotated[int, Field(ge=0, le=9_223_372_036_854_775_807)]


class StrictContract(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
    )


def _canonical_json_value(value: object) -> object:
    if isinstance(value, BaseModel):
        return _canonical_json_value(value.model_dump(mode="python"))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {
            str(key): _canonical_json_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_json_value(item) for item in value]
    return value


def calculate_compiled_plan_fingerprint(
    plan_without_report: dict[str, object], compiler_version: str
) -> str:
    """Hash the canonical execution payload plus compiler version."""

    rendered = json.dumps(
        {
            "compiler_version": compiler_version,
            "plan": _canonical_json_value(plan_without_report),
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(rendered).hexdigest()


class MediaKind(str, Enum):
    TV_EPISODE = "TV_EPISODE"
    TV_SERIES = "TV_SERIES"
    FILM = "FILM"
    TRAILER = "TRAILER"
    OFFICIAL_CLIP = "OFFICIAL_CLIP"


class SpoilerPolicy(str, Enum):
    AVOID = "AVOID"
    CURRENT_EPISODE = "CURRENT_EPISODE"
    ALLOW = "ALLOW"


class EvidenceSourceType(str, Enum):
    PRIMARY_RELEASE = "PRIMARY_RELEASE"
    OFFICIAL_CLIP = "OFFICIAL_CLIP"
    PLATFORM_SIGNAL = "PLATFORM_SIGNAL"
    ARTICLE = "ARTICLE"
    METADATA = "METADATA"


class ExcerptType(str, Enum):
    SHORT_QUOTE = "SHORT_QUOTE"
    PARAPHRASE = "PARAPHRASE"
    UNVERIFIED_QUOTE_LEAD = "UNVERIFIED_QUOTE_LEAD"


class VerificationState(str, Enum):
    PRIMARY_VERIFIED = "PRIMARY_VERIFIED"
    SECONDARY_CORROBORATED = "SECONDARY_CORROBORATED"
    LEAD_ONLY = "LEAD_ONLY"
    STALE = "STALE"
    RETRACTED = "RETRACTED"


class EvidenceGate(str, Enum):
    PASSED = "PASSED"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"


class EvidenceRole(str, Enum):
    PRIMARY_WHY_NOW = "PRIMARY_WHY_NOW"
    QUALITATIVE_SIGNAL = "QUALITATIVE_SIGNAL"
    QUOTE_PROOF = "QUOTE_PROOF"
    CONTEXT = "CONTEXT"


class QuoteStatus(str, Enum):
    NONE = "NONE"
    VERIFIED = "VERIFIED"
    PARAPHRASE = "PARAPHRASE"
    UNVERIFIED_LEAD = "UNVERIFIED_LEAD"


class ClipRole(str, Enum):
    INTRO_DIALOGUE = "INTRO_DIALOGUE"
    INTRO_REACTION = "INTRO_REACTION"
    HANDOFF = "HANDOFF"
    MONTAGE = "MONTAGE"
    PAYOFF = "PAYOFF"
    ENDING = "ENDING"


class ResearchIntent(StrictContract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    query: NonEmptyText
    media_kinds: Annotated[list[MediaKind], Field(min_length=1, max_length=5)]
    focus_terms: Annotated[list[ShortText], Field(default_factory=list, max_length=20)]
    region: Annotated[str, Field(min_length=2, max_length=16)] = "US"
    freshness_days: Annotated[int, Field(ge=1, le=90)] = 14
    spoiler_policy: SpoilerPolicy = SpoilerPolicy.CURRENT_EPISODE
    exclusions: Annotated[list[ShortText], Field(default_factory=list, max_length=30)]
    max_results: Annotated[int, Field(ge=1, le=10)] = 5


class EvidenceRecord(StrictContract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    evidence_id: UUID4
    provider: Annotated[str, Field(min_length=1, max_length=64)]
    provider_record_id: Annotated[str | None, Field(max_length=256)] = None
    source_type: EvidenceSourceType
    canonical_url: HttpUrl
    title: ShortText
    author_or_channel: Annotated[str | None, Field(max_length=200)] = None
    excerpt_type: ExcerptType
    excerpt: ShortText
    verification: VerificationState
    source_created_at: AwareDatetime | None = None
    source_updated_at: AwareDatetime | None = None
    page_published_at: AwareDatetime | None = None
    event_or_release_at: AwareDatetime | None = None
    retrieved_at: AwareDatetime
    query: Annotated[str, Field(min_length=1, max_length=1_000)]
    window_start: AwareDatetime | None = None
    window_end: AwareDatetime | None = None
    confidence: Confidence
    policy_class: Annotated[str, Field(min_length=1, max_length=64)]
    refresh_due_at: AwareDatetime | None = None
    purge_due_at: AwareDatetime | None = None
    expires_at: AwareDatetime | None = None
    content_sha256: Sha256

    @model_validator(mode="after")
    def validate_dates(self) -> Self:
        if self.window_start and self.window_end and self.window_end <= self.window_start:
            raise ValueError("window_end must be later than window_start")
        if self.expires_at and self.expires_at <= self.retrieved_at:
            raise ValueError("expires_at must be later than retrieved_at")
        return self


class OpportunityFocus(StrictContract):
    characters: Annotated[list[ShortText], Field(default_factory=list, max_length=20)]
    relationship_or_topic: ShortText


class OpportunityEvidenceReference(StrictContract):
    claim_id: UUID4
    role: EvidenceRole
    independence_group: Annotated[str, Field(min_length=1, max_length=128)]
    supports_why_now: bool


class TrendOpportunityDraft(StrictContract):
    """Provider-authored synthesis; trusted code assigns persisted entity IDs."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    media_kind: MediaKind
    title: ShortText
    focus: OpportunityFocus
    why_now: NonEmptyText
    creative_hook: NonEmptyText
    evidence: Annotated[
        list[OpportunityEvidenceReference], Field(min_length=1, max_length=30)
    ]
    evidence_gate: EvidenceGate
    confidence: Confidence
    caveats: Annotated[list[ShortText], Field(default_factory=list, max_length=20)]

    @model_validator(mode="after")
    def validate_evidence_shape(self) -> Self:
        claim_ids = [reference.claim_id for reference in self.evidence]
        if len(set(claim_ids)) != len(claim_ids):
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
                if item.role is EvidenceRole.QUALITATIVE_SIGNAL and item.supports_why_now
            ]
            if not primary or len(signals) < 2:
                raise ValueError(
                    "PASSED requires a why-now primary and two qualitative signals"
                )
            signal_groups = {item.independence_group for item in signals}
            support_groups = {
                item.independence_group for item in [*primary, *signals]
            }
            if len(signal_groups) < 2 or len(support_groups) < 3:
                raise ValueError("PASSED evidence must come from independent groups")
        return self


class TrendOpportunity(TrendOpportunityDraft):
    """Canonical persisted opportunity with trusted, preallocated UUIDv4 IDs."""

    opportunity_id: UUID4
    footage_request_id: UUID4


class FootageRequirementDraft(StrictContract):
    order: Annotated[int, Field(ge=0)]
    required: bool
    media_title: ShortText
    season_episode_or_asset: ShortText
    characters_or_relationship: Annotated[
        list[ShortText], Field(default_factory=list, max_length=20)
    ]
    moment_description: NonEmptyText
    quote_status: QuoteStatus = QuoteStatus.NONE
    quote_text: Annotated[str | None, Field(max_length=500)] = None
    quote_claim_id: UUID4 | None = None
    rationale: NonEmptyText
    alternatives: Annotated[list[ShortText], Field(default_factory=list, max_length=20)]

    @model_validator(mode="after")
    def validate_quote(self) -> Self:
        if self.quote_status is QuoteStatus.NONE:
            if self.quote_text is not None or self.quote_claim_id is not None:
                raise ValueError("NONE quote status cannot carry quote data")
            return self
        if not self.quote_text:
            raise ValueError("quote_status requires quote_text")
        if self.quote_status is QuoteStatus.VERIFIED and self.quote_claim_id is None:
            raise ValueError("VERIFIED requires an authoritative quote claim ID")
        return self


class FootageRequirement(FootageRequirementDraft):
    requirement_id: UUID4


class FootageRequestDraft(StrictContract):
    """Provider-authored request; entity and requirement IDs are server-owned."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    summary: NonEmptyText
    requirements: Annotated[
        list[FootageRequirementDraft], Field(min_length=1, max_length=30)
    ]
    search_terms: Annotated[list[ShortText], Field(min_length=1, max_length=30)]
    warnings: Annotated[list[ShortText], Field(default_factory=list, max_length=20)]

    @model_validator(mode="after")
    def validate_requirement_order(self) -> Self:
        orders = [requirement.order for requirement in self.requirements]
        if orders != list(range(len(orders))):
            raise ValueError("requirement order must be contiguous and match list order")
        return self


class FootageRequest(StrictContract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    footage_request_id: UUID4
    opportunity_id: UUID4
    summary: NonEmptyText
    requirements: Annotated[list[FootageRequirement], Field(min_length=1, max_length=30)]
    search_terms: Annotated[list[ShortText], Field(min_length=1, max_length=30)]
    warnings: Annotated[list[ShortText], Field(default_factory=list, max_length=20)]

    @model_validator(mode="after")
    def validate_requirement_order(self) -> Self:
        orders = [requirement.order for requirement in self.requirements]
        if orders != list(range(len(orders))):
            raise ValueError("requirement order must be contiguous and match list order")
        ids = [requirement.requirement_id for requirement in self.requirements]
        if len(set(ids)) != len(ids):
            raise ValueError("requirement IDs must be unique")
        return self


class PriceComponent(StrictContract):
    """Trusted price-card arithmetic expressed in integer micro-USD."""

    category: Annotated[str, Field(min_length=1, max_length=64)]
    quantity: Annotated[Decimal, Field(ge=0)]
    unit: Annotated[str, Field(min_length=1, max_length=64)]
    unit_price_micro_usd: MicroUsd
    maximum_cost_micro_usd: MicroUsd

    @model_validator(mode="after")
    def validate_component_total(self) -> Self:
        calculated = (self.quantity * Decimal(self.unit_price_micro_usd)).to_integral_value(
            rounding=ROUND_CEILING
        )
        if calculated != self.maximum_cost_micro_usd:
            raise ValueError("component maximum must equal rounded quantity × unit price")
        return self


class CostEstimate(StrictContract):
    """Trusted runtime preview/reservation input; never a provider output."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    estimate_id: UUID4
    operation: Annotated[str, Field(min_length=1, max_length=128)]
    provider: Annotated[str, Field(min_length=1, max_length=64)]
    configured_model: Annotated[str, Field(min_length=1, max_length=128)]
    resolved_model: Annotated[str | None, Field(max_length=256)] = None
    price_card_id: UUID4
    currency: Literal["USD"] = "USD"
    components: Annotated[list[PriceComponent], Field(min_length=1, max_length=30)]
    expected_cost_micro_usd: MicroUsd
    maximum_cost_micro_usd: MicroUsd
    hard_limit_micro_usd: MicroUsd
    already_spent_or_reserved_micro_usd: MicroUsd
    cache_hit: bool = False
    privacy_notice: ShortText

    @model_validator(mode="after")
    def validate_amounts(self) -> Self:
        component_total = sum(
            component.maximum_cost_micro_usd for component in self.components
        )
        if component_total != self.maximum_cost_micro_usd:
            raise ValueError("maximum cost must equal the sum of component maxima")
        if self.expected_cost_micro_usd > self.maximum_cost_micro_usd:
            raise ValueError("expected cost cannot exceed maximum cost")
        if self.cache_hit and (
            self.expected_cost_micro_usd != 0 or self.maximum_cost_micro_usd != 0
        ):
            raise ValueError("cache-hit estimates must have zero expected/maximum cost")
        committed = (
            self.maximum_cost_micro_usd
            + self.already_spent_or_reserved_micro_usd
        )
        if committed > self.hard_limit_micro_usd:
            raise ValueError("estimate would exceed the hard limit")
        return self


class Rational(StrictContract):
    numerator: Annotated[int, Field(gt=0)]
    denominator: Annotated[int, Field(gt=0)]


class SignedRational(StrictContract):
    numerator: int
    denominator: Annotated[int, Field(gt=0)]

    @model_validator(mode="after")
    def validate_reduced(self) -> Self:
        value = Fraction(self.numerator, self.denominator)
        if value.numerator != self.numerator or value.denominator != self.denominator:
            raise ValueError("signed rational must be in lowest terms")
        return self


class MediaPoint(StrictContract):
    # Raw container/stream PTS may be negative before timeline normalization.
    pts: int
    time_base: Rational
    frame_index: Annotated[int | None, Field(ge=0)] = None


class StreamType(str, Enum):
    VIDEO = "VIDEO"
    AUDIO = "AUDIO"


class BoundaryKind(str, Enum):
    DECODED_VIDEO_FRAME = "DECODED_VIDEO_FRAME"
    USER_CONFIRMED_VIDEO_FRAME = "USER_CONFIRMED_VIDEO_FRAME"
    DECODED_AUDIO_SAMPLE = "DECODED_AUDIO_SAMPLE"


class ResolvedBoundary(StrictContract):
    source_media_id: UUID4
    source_sha256: Sha256
    stream_signature_sha256: Sha256
    stream_index: Annotated[int, Field(ge=0)]
    stream_type: StreamType
    point: MediaPoint
    boundary_kind: BoundaryKind
    resolver_id: Annotated[str, Field(min_length=1, max_length=128)]
    resolution_evidence_id: UUID4
    confidence: Confidence

    @model_validator(mode="after")
    def validate_boundary_kind(self) -> Self:
        if self.stream_type is StreamType.VIDEO:
            if self.boundary_kind not in {
                BoundaryKind.DECODED_VIDEO_FRAME,
                BoundaryKind.USER_CONFIRMED_VIDEO_FRAME,
            }:
                raise ValueError("video boundaries must resolve to decoded frames")
            if self.point.frame_index is None:
                raise ValueError("video boundaries require a decoded frame index")
        elif self.boundary_kind is not BoundaryKind.DECODED_AUDIO_SAMPLE:
            raise ValueError("audio boundaries must resolve to decoded samples")
        return self


class ResolvedMediaRange(StrictContract):
    """One exact stream range; transcript and beat times are anchors, not authorities."""

    start: ResolvedBoundary
    end: ResolvedBoundary
    asset_clock_mapping_id: UUID4

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        identity_fields = (
            "source_media_id",
            "source_sha256",
            "stream_signature_sha256",
            "stream_index",
            "stream_type",
        )
        for field_name in identity_fields:
            if getattr(self.start, field_name) != getattr(self.end, field_name):
                raise ValueError(f"range endpoints disagree on {field_name}")
        if self.start.point.time_base != self.end.point.time_base:
            raise ValueError("range endpoints must share a stream time base")
        if self.end.point.pts <= self.start.point.pts:
            raise ValueError("end PTS must be greater than start PTS")
        if self.start.stream_type is StreamType.VIDEO:
            start_frame = self.start.point.frame_index
            end_frame = self.end.point.frame_index
            if start_frame is None or end_frame is None or end_frame <= start_frame:
                raise ValueError("video frame indices must increase with PTS")
        return self


class CropPlan(StrictContract):
    mode: Literal["CENTER"] = "CENTER"
    preset_version: Literal["CENTER@1"] = "CENTER@1"


class ClipAudioPolicy(str, Enum):
    MUTE_SOURCE = "MUTE_SOURCE"
    KEEP_SOURCE = "KEEP_SOURCE"
    DUCK_UNDER_SONG = "DUCK_UNDER_SONG"


class AssetClockMapping(StrictContract):
    mapping_id: UUID4
    source_media_id: UUID4
    source_sha256: Sha256
    video_stream_index: Annotated[int, Field(ge=0)]
    audio_stream_index: Annotated[int, Field(ge=0)]
    video_origin: MediaPoint
    audio_origin: MediaPoint
    resolver_id: Annotated[str, Field(min_length=1, max_length=128)]
    resolution_evidence_id: UUID4
    confidence: Confidence


class ClipAudioPlan(StrictContract):
    policy: ClipAudioPolicy
    source_range: ResolvedMediaRange | None = None
    clock_mapping: AssetClockMapping | None = None

    @model_validator(mode="after")
    def validate_audio_range(self) -> Self:
        if self.policy is ClipAudioPolicy.MUTE_SOURCE:
            if self.source_range is not None or self.clock_mapping is not None:
                raise ValueError("MUTE_SOURCE cannot carry an audio range/mapping")
        else:
            if self.source_range is None or self.clock_mapping is None:
                raise ValueError("source-audio policies require a range and clock mapping")
            if self.source_range.start.stream_type is not StreamType.AUDIO:
                raise ValueError("audio plan must reference an audio stream")
        return self


class ClipPlan(StrictContract):
    """Trusted compiled clip. Only M0-calibrated presets are executable."""

    clip_id: UUID4
    order: Annotated[int, Field(ge=0)]
    role: ClipRole
    source_range: ResolvedMediaRange
    source_handle_before_pts: Annotated[int, Field(ge=0)]
    source_handle_after_pts: Annotated[int, Field(ge=0)]
    timeline_start_frame: Annotated[int, Field(ge=0)]
    timeline_end_frame: Annotated[int, Field(gt=0)]
    velocity_preset: Literal["STATIC"] = "STATIC"
    velocity_preset_version: Literal["STATIC@1"] = "STATIC@1"
    transition_after: Literal["CLEAN_CUT"] | None = None
    transition_preset_version: Literal["CLEAN_CUT@1"] | None = None
    crop: CropPlan = Field(default_factory=CropPlan)
    audio: ClipAudioPlan
    song_beat_anchor_id: UUID4 | None = None
    evidence_ids: Annotated[list[UUID4], Field(min_length=1, max_length=30)]
    rationale: NonEmptyText

    @model_validator(mode="after")
    def validate_clip(self) -> Self:
        if self.timeline_end_frame <= self.timeline_start_frame:
            raise ValueError("timeline_end_frame must be greater than timeline_start_frame")
        if self.source_range.start.stream_type is not StreamType.VIDEO:
            raise ValueError("picture source_range must reference a video stream")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("clip evidence IDs must be unique")
        if (self.transition_after is None) != (self.transition_preset_version is None):
            raise ValueError("transition name and version must both be set or both be absent")
        if self.audio.source_range is not None:
            audio_range = self.audio.source_range
            video_range = self.source_range
            mapping = self.audio.clock_mapping
            if mapping is None:
                raise ValueError("clip audio requires a clock mapping")
            if audio_range.start.source_media_id != video_range.start.source_media_id:
                raise ValueError("clip audio and picture must belong to the same asset")
            if audio_range.start.source_sha256 != video_range.start.source_sha256:
                raise ValueError("clip audio and picture fingerprints must match")
            if audio_range.asset_clock_mapping_id != video_range.asset_clock_mapping_id:
                raise ValueError("clip audio and picture require the same clock mapping")
            if mapping.mapping_id != video_range.asset_clock_mapping_id:
                raise ValueError("clock-mapping record ID does not match the ranges")
            if (
                mapping.source_media_id != video_range.start.source_media_id
                or mapping.source_sha256 != video_range.start.source_sha256
            ):
                raise ValueError("clock mapping belongs to a different source revision")
            if (
                mapping.video_stream_index != video_range.start.stream_index
                or mapping.audio_stream_index != audio_range.start.stream_index
            ):
                raise ValueError("clock mapping stream indices do not match the ranges")
            video_time_base = video_range.start.point.time_base
            audio_time_base = audio_range.start.point.time_base
            if mapping.video_origin.time_base != video_time_base:
                raise ValueError("video clock origin uses the wrong time base")
            if mapping.audio_origin.time_base != audio_time_base:
                raise ValueError("audio clock origin uses the wrong time base")

            def mapped_offset(point: MediaPoint, origin: MediaPoint) -> Fraction:
                return Fraction(point.pts - origin.pts) * Fraction(
                    point.time_base.numerator,
                    point.time_base.denominator,
                )

            tolerance = Fraction(
                audio_time_base.numerator,
                audio_time_base.denominator,
            )
            for video_point, audio_point in (
                (video_range.start.point, audio_range.start.point),
                (video_range.end.point, audio_range.end.point),
            ):
                difference = abs(
                    mapped_offset(video_point, mapping.video_origin)
                    - mapped_offset(audio_point, mapping.audio_origin)
                )
                if difference > tolerance:
                    raise ValueError(
                        "audio interval does not map to picture within one audio sample"
                    )
        return self


class AudioAccent(str, Enum):
    NONE = "NONE"
    SOURCE_HIT = "SOURCE_HIT"
    SONG_HIT = "SONG_HIT"


class SongHandoffPlan(StrictContract):
    song_map_id: UUID4
    beat_id: UUID4
    song_source_range: ResolvedMediaRange
    song_timeline_start_frame: Annotated[int, Field(ge=0)]
    beat_point: MediaPoint
    resolved_timeline_frame: Annotated[int, Field(ge=0)]
    quantization_error: SignedRational
    dialogue_tail_frames: Annotated[int, Field(ge=0)]
    music_pre_lap_frames: Annotated[int, Field(ge=0)]
    source_fade_out_frames: Annotated[int, Field(ge=0)]
    song_fade_in_frames: Annotated[int, Field(ge=0)]
    accent: AudioAccent = AudioAccent.NONE
    policy: Literal["DIALOGUE_TO_SONG_CUT_V1@1"] = "DIALOGUE_TO_SONG_CUT_V1@1"

    @model_validator(mode="after")
    def validate_handoff_shape(self) -> Self:
        song_range = self.song_source_range
        if song_range.start.stream_type is not StreamType.AUDIO:
            raise ValueError("song source range must reference an audio stream")
        if self.beat_point.time_base != song_range.start.point.time_base:
            raise ValueError("beat point and selected song range need one time base")
        if not (
            song_range.start.point.pts
            <= self.beat_point.pts
            < song_range.end.point.pts
        ):
            raise ValueError("beat point must fall inside the selected song range")
        if self.song_timeline_start_frame > self.resolved_timeline_frame:
            raise ValueError("song cannot begin after its handoff beat")
        if (
            self.resolved_timeline_frame - self.song_timeline_start_frame
            != self.music_pre_lap_frames
        ):
            raise ValueError("music pre-lap must equal song-start to handoff distance")
        if self.source_fade_out_frames > self.dialogue_tail_frames:
            raise ValueError("source fade cannot exceed the declared dialogue tail")
        return self


class EndingPreset(str, Enum):
    END_ON_IMAGE = "END_ON_IMAGE"
    END_TO_BLACK = "END_TO_BLACK"
    END_TITLE_BLACK = "END_TITLE_BLACK"


class EndingPlan(StrictContract):
    preset: EndingPreset
    duration_frames: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def validate_ending_duration(self) -> Self:
        if self.preset is EndingPreset.END_ON_IMAGE and self.duration_frames != 0:
            raise ValueError("END_ON_IMAGE has no separate ending bed")
        if self.preset is not EndingPreset.END_ON_IMAGE and self.duration_frames == 0:
            raise ValueError("black/title endings require a positive duration")
        return self


class ValidationCheck(StrictContract):
    code: Annotated[str, Field(min_length=1, max_length=128)]
    passed: Literal[True]
    detail: ShortText


MANDATORY_PLAN_VALIDATION_CODES = frozenset(
    {
        "audio.clock-mapping",
        "audio.song-handoff",
        "evidence.linkage",
        "grammar.dialogue-drop-v1",
        "output.duration",
        "presets.enabled",
        "source.boundaries",
        "timeline.order",
        "timeline.static-duration",
    }
)


class PlanValidationReport(StrictContract):
    status: Literal["PASSED"] = "PASSED"
    compiler_run_id: UUID4
    compiler_version: Annotated[str, Field(min_length=1, max_length=128)]
    validated_at: AwareDatetime
    input_fingerprint: Sha256
    checks: Annotated[list[ValidationCheck], Field(min_length=1, max_length=100)]


class CompiledEditPlan(StrictContract):
    """Execution input emitted only by trusted deterministic compiler code."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    plan_id: UUID4
    revision: Annotated[int, Field(ge=1)]
    parent_plan_id: UUID4 | None = None
    grammar_id: Literal["DIALOGUE_DROP_EDIT_V1"] = "DIALOGUE_DROP_EDIT_V1"
    grammar_version: Literal["1.0.0"] = "1.0.0"
    preset_registry_version: Literal["m0-safe-1"] = "m0-safe-1"
    concept: NonEmptyText
    output_aspect: Rational = Field(
        default_factory=lambda: Rational(numerator=4, denominator=3)
    )
    output_frame_rate: Rational
    conform_policy: Literal["EXACT_OR_ONE_OUTPUT_FRAME"] = "EXACT_OR_ONE_OUTPUT_FRAME"
    song_handoff: SongHandoffPlan
    ending: EndingPlan
    expected_duration_frames: Annotated[int, Field(gt=0)]
    clips: Annotated[list[ClipPlan], Field(min_length=1, max_length=500)]
    validation_report: PlanValidationReport

    @model_validator(mode="after")
    def validate_compiled_plan(self) -> Self:
        clip_ids = [clip.clip_id for clip in self.clips]
        if len(set(clip_ids)) != len(clip_ids):
            raise ValueError("clip IDs must be unique")
        orders = [clip.order for clip in self.clips]
        if orders != list(range(len(self.clips))):
            raise ValueError("clip order must be contiguous and match list order")
        if self.clips[0].timeline_start_frame != 0:
            raise ValueError("compiled timeline must begin at frame zero")

        handoff_indices = [
            index for index, clip in enumerate(self.clips) if clip.role is ClipRole.HANDOFF
        ]
        if len(handoff_indices) != 1:
            raise ValueError("DIALOGUE_DROP_EDIT_V1 requires exactly one HANDOFF clip")
        handoff_index = handoff_indices[0]
        if self.clips[0].role is not ClipRole.INTRO_DIALOGUE:
            raise ValueError("DIALOGUE_DROP_EDIT_V1 must begin with INTRO_DIALOGUE")
        if any(
            clip.role not in {ClipRole.INTRO_DIALOGUE, ClipRole.INTRO_REACTION}
            for clip in self.clips[:handoff_index]
        ):
            raise ValueError("only intro dialogue/reaction roles may precede HANDOFF")
        if any(
            clip.role not in {ClipRole.MONTAGE, ClipRole.PAYOFF, ClipRole.ENDING}
            for clip in self.clips[handoff_index + 1 :]
        ):
            raise ValueError("only montage/payoff/ending roles may follow HANDOFF")
        if not any(
            clip.role is ClipRole.MONTAGE for clip in self.clips[handoff_index + 1 :]
        ):
            raise ValueError("DIALOGUE_DROP_EDIT_V1 requires montage after HANDOFF")
        for intro_clip in self.clips[:handoff_index]:
            if (
                intro_clip.role is ClipRole.INTRO_DIALOGUE
                and intro_clip.audio.policy is ClipAudioPolicy.MUTE_SOURCE
            ):
                raise ValueError("INTRO_DIALOGUE must retain a mapped source-audio range")

        handoff_clip = self.clips[handoff_index]
        handoff_frame = self.song_handoff.resolved_timeline_frame
        if handoff_frame != handoff_clip.timeline_start_frame:
            raise ValueError("song handoff must coincide with the HANDOFF clip boundary")
        if handoff_clip.song_beat_anchor_id != self.song_handoff.beat_id:
            raise ValueError("HANDOFF clip must reference the resolved song beat")
        fps = Fraction(
            self.output_frame_rate.numerator,
            self.output_frame_rate.denominator,
        )
        setup_seconds = Fraction(handoff_frame, 1) / fps
        if setup_seconds < 5 or setup_seconds > 24:
            raise ValueError("dialogue setup must be between 5 and 24 seconds")
        if self.song_handoff.dialogue_tail_frames > handoff_frame:
            raise ValueError("dialogue tail extends before the timeline begins")

        one_output_frame = Fraction(1, 1) / fps
        cumulative_static_error = Fraction(0, 1)
        for index, clip in enumerate(self.clips):
            is_last = index == len(self.clips) - 1
            if is_last and clip.transition_after is not None:
                raise ValueError("the terminal clip cannot carry a transition_after")
            if not is_last and clip.transition_after != "CLEAN_CUT":
                raise ValueError("every non-terminal clip requires CLEAN_CUT in m0-safe-1")
            if index:
                previous = self.clips[index - 1]
                if clip.timeline_start_frame != previous.timeline_end_frame:
                    raise ValueError(
                        "compiled clips must be contiguous; represent gaps explicitly in a future schema"
                    )

            source_start = clip.source_range.start.point
            source_end = clip.source_range.end.point
            source_seconds = Fraction(source_end.pts - source_start.pts) * Fraction(
                source_start.time_base.numerator,
                source_start.time_base.denominator,
            )
            timeline_frames = clip.timeline_end_frame - clip.timeline_start_frame
            timeline_seconds = Fraction(timeline_frames) * Fraction(
                self.output_frame_rate.denominator,
                self.output_frame_rate.numerator,
            )
            static_error = source_seconds - timeline_seconds
            if abs(static_error) > one_output_frame:
                raise ValueError(
                    "STATIC source duration must match timeline duration within one output frame"
                )
            cumulative_static_error += static_error

        if abs(cumulative_static_error) > one_output_frame:
            raise ValueError("cumulative STATIC conform error exceeds one output frame")

        picture_end = self.clips[-1].timeline_end_frame
        if handoff_frame >= picture_end:
            raise ValueError("song handoff must resolve inside the picture timeline")
        song_range = self.song_handoff.song_source_range
        beat_delta_seconds = Fraction(
            self.song_handoff.beat_point.pts - song_range.start.point.pts
        ) * Fraction(
            self.song_handoff.beat_point.time_base.numerator,
            self.song_handoff.beat_point.time_base.denominator,
        )
        exact_beat_frame = Fraction(
            self.song_handoff.song_timeline_start_frame
        ) + beat_delta_seconds * fps
        floor_frame = exact_beat_frame.numerator // exact_beat_frame.denominator
        remainder = exact_beat_frame - floor_frame
        nearest_frame = floor_frame + (1 if remainder * 2 >= 1 else 0)
        expected_quantization_error = Fraction(nearest_frame) - exact_beat_frame
        supplied_quantization_error = Fraction(
            self.song_handoff.quantization_error.numerator,
            self.song_handoff.quantization_error.denominator,
        )
        if nearest_frame != handoff_frame:
            raise ValueError("resolved handoff frame does not match rational beat quantization")
        if supplied_quantization_error != expected_quantization_error:
            raise ValueError("reported beat quantization error is inconsistent")
        if abs(supplied_quantization_error) > Fraction(1, 2):
            raise ValueError("beat quantization error exceeds half an output frame")

        song_duration_seconds = Fraction(
            song_range.end.point.pts - song_range.start.point.pts
        ) * Fraction(
            song_range.start.point.time_base.numerator,
            song_range.start.point.time_base.denominator,
        )
        selected_song_frames = song_duration_seconds * fps
        required_song_frames = picture_end - self.song_handoff.song_timeline_start_frame
        if selected_song_frames + 1 < required_song_frames:
            raise ValueError("selected song range does not cover the picture timeline")
        if self.song_handoff.song_fade_in_frames > selected_song_frames:
            raise ValueError("song fade exceeds the selected song range")

        calculated_duration = picture_end + self.ending.duration_frames
        if calculated_duration != self.expected_duration_frames:
            raise ValueError("expected duration must equal picture plus ending duration")

        check_codes = [check.code for check in self.validation_report.checks]
        if len(set(check_codes)) != len(check_codes):
            raise ValueError("validation-report check codes must be unique")
        if set(check_codes) != MANDATORY_PLAN_VALIDATION_CODES:
            raise ValueError("validation report is missing or adds mandatory gate codes")
        payload = self.model_dump(mode="python", exclude={"validation_report"})
        expected_fingerprint = calculate_compiled_plan_fingerprint(
            payload,
            self.validation_report.compiler_version,
        )
        if expected_fingerprint != self.validation_report.input_fingerprint:
            raise ValueError("validation report fingerprint does not bind this plan")
        return self


class ModelRunOutcome(str, Enum):
    SUCCESS = "SUCCESS"
    REFUSAL = "REFUSAL"
    INCOMPLETE = "INCOMPLETE"


class ModelRunEnvelope(StrictContract):
    """Trusted metadata paired with, but not authored inside, a provider payload."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    schema_name: Annotated[str, Field(min_length=1, max_length=128)]
    prompt_version: Annotated[str, Field(min_length=1, max_length=128)]
    trace_id: UUID4
    job_id: UUID4
    provider: Annotated[str, Field(min_length=1, max_length=64)]
    configured_model: Annotated[str, Field(min_length=1, max_length=128)]
    resolved_model: Annotated[str | None, Field(max_length=256)] = None
    generated_at: AwareDatetime
    input_fingerprint: Sha256
    outcome: ModelRunOutcome
    payload_sha256: Sha256 | None = None
    refusal: Annotated[str | None, Field(max_length=1_000)] = None
    incomplete: Annotated[str | None, Field(max_length=1_000)] = None

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        if self.outcome is ModelRunOutcome.SUCCESS:
            if self.payload_sha256 is None or self.refusal is not None or self.incomplete is not None:
                raise ValueError("SUCCESS requires only a payload hash")
        elif self.outcome is ModelRunOutcome.REFUSAL:
            if not self.refusal or self.incomplete is not None or self.payload_sha256 is not None:
                raise ValueError("REFUSAL requires only refusal detail")
        elif (
            not self.incomplete
            or self.refusal is not None
            or self.payload_sha256 is not None
        ):
            raise ValueError("INCOMPLETE requires only incomplete detail")
        return self


PROVIDER_OUTPUT_CONTRACTS: dict[str, type[StrictContract]] = {
    "research-intent": ResearchIntent,
    "trend-opportunity-draft": TrendOpportunityDraft,
    "footage-request-draft": FootageRequestDraft,
}

CANONICAL_STORAGE_CONTRACTS: dict[str, type[StrictContract]] = {
    "research-intent": ResearchIntent,
    "evidence-record": EvidenceRecord,
    "trend-opportunity": TrendOpportunity,
    "footage-request": FootageRequest,
    "model-run-envelope": ModelRunEnvelope,
}

TRUSTED_EXECUTION_CONTRACTS: dict[str, type[StrictContract]] = {
    "cost-estimate": CostEstimate,
    "compiled-edit-plan": CompiledEditPlan,
}
