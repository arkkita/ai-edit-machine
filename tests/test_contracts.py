from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

from pydantic import ValidationError


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_edit_machine.config import RuntimeSettings  # noqa: E402
from ai_edit_machine.contracts import (  # noqa: E402
    CANONICAL_STORAGE_CONTRACTS,
    PROVIDER_OUTPUT_CONTRACTS,
    TRUSTED_EXECUTION_CONTRACTS,
    AssetClockMapping,
    AudioAccent,
    BoundaryKind,
    ClipAudioPlan,
    ClipAudioPolicy,
    ClipPlan,
    ClipRole,
    CompiledEditPlan,
    CostEstimate,
    EndingPlan,
    EndingPreset,
    EvidenceGate,
    EvidenceRole,
    FootageRequirementDraft,
    MediaKind,
    MediaPoint,
    ModelRunEnvelope,
    ModelRunOutcome,
    OpportunityEvidenceReference,
    OpportunityFocus,
    MANDATORY_PLAN_VALIDATION_CODES,
    PlanValidationReport,
    PriceComponent,
    QuoteStatus,
    Rational,
    ResearchIntent,
    ResolvedBoundary,
    ResolvedMediaRange,
    SongHandoffPlan,
    SignedRational,
    StreamType,
    TrendOpportunityDraft,
    ValidationCheck,
    calculate_compiled_plan_fingerprint,
)


HASH = "a" * 64
STREAM_HASH = "c" * 64
NOW = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)


def resolved_range(
    start: int,
    end: int,
    *,
    stream_type: StreamType = StreamType.VIDEO,
    stream_index: int = 0,
    time_base: Rational | None = None,
    source_id: UUID | None = None,
    clock_mapping_id: UUID | None = None,
    start_frame: int | None = None,
    end_frame: int | None = None,
) -> ResolvedMediaRange:
    time_base = time_base or Rational(numerator=1, denominator=30)
    source_id = source_id or uuid4()
    clock_mapping_id = clock_mapping_id or uuid4()
    if stream_type is StreamType.VIDEO:
        boundary_kind = BoundaryKind.DECODED_VIDEO_FRAME
        start_frame = 0 if start_frame is None else start_frame
        end_frame = start_frame + 1 if end_frame is None else end_frame
    else:
        boundary_kind = BoundaryKind.DECODED_AUDIO_SAMPLE
        start_frame = None
        end_frame = None
    return ResolvedMediaRange(
        start=ResolvedBoundary(
            source_media_id=source_id,
            source_sha256=HASH,
            stream_signature_sha256=STREAM_HASH,
            stream_index=stream_index,
            stream_type=stream_type,
            point=MediaPoint(
                pts=start,
                time_base=time_base,
                frame_index=start_frame,
            ),
            boundary_kind=boundary_kind,
            resolver_id="ffmpeg-frame-index-v1",
            resolution_evidence_id=uuid4(),
            confidence=0.99,
        ),
        end=ResolvedBoundary(
            source_media_id=source_id,
            source_sha256=HASH,
            stream_signature_sha256=STREAM_HASH,
            stream_index=stream_index,
            stream_type=stream_type,
            point=MediaPoint(
                pts=end,
                time_base=time_base,
                frame_index=end_frame,
            ),
            boundary_kind=boundary_kind,
            resolver_id="ffmpeg-frame-index-v1",
            resolution_evidence_id=uuid4(),
            confidence=0.99,
        ),
        asset_clock_mapping_id=clock_mapping_id,
    )


def clip(
    *,
    order: int,
    timeline_start: int,
    timeline_end: int,
    source_start: int = 0,
    source_end: int | None = None,
    transition_after: str | None = None,
    role: ClipRole = ClipRole.MONTAGE,
    keep_audio: bool = False,
) -> ClipPlan:
    source_end = source_end if source_end is not None else source_start + (
        timeline_end - timeline_start
    )
    picture_range = resolved_range(
        source_start,
        source_end,
        start_frame=0,
        end_frame=source_end - source_start,
    )
    audio_plan = ClipAudioPlan(policy=ClipAudioPolicy.MUTE_SOURCE)
    if keep_audio:
        audio_time_base = Rational(numerator=1, denominator=48_000)
        audio_range = resolved_range(
            source_start * 1_600,
            source_end * 1_600,
            stream_type=StreamType.AUDIO,
            stream_index=1,
            time_base=audio_time_base,
            source_id=picture_range.start.source_media_id,
            clock_mapping_id=picture_range.asset_clock_mapping_id,
        )
        mapping = AssetClockMapping(
            mapping_id=picture_range.asset_clock_mapping_id,
            source_media_id=picture_range.start.source_media_id,
            source_sha256=HASH,
            video_stream_index=0,
            audio_stream_index=1,
            video_origin=MediaPoint(
                pts=0,
                time_base=Rational(numerator=1, denominator=30),
                frame_index=0,
            ),
            audio_origin=MediaPoint(pts=0, time_base=audio_time_base),
            resolver_id="ffprobe-stream-clock-map-v1",
            resolution_evidence_id=uuid4(),
            confidence=0.99,
        )
        audio_plan = ClipAudioPlan(
            policy=ClipAudioPolicy.KEEP_SOURCE,
            source_range=audio_range,
            clock_mapping=mapping,
        )
    return ClipPlan(
        clip_id=uuid4(),
        order=order,
        role=role,
        source_range=picture_range,
        source_handle_before_pts=0,
        source_handle_after_pts=0,
        timeline_start_frame=timeline_start,
        timeline_end_frame=timeline_end,
        transition_after=transition_after,
        transition_preset_version=(
            "CLEAN_CUT@1" if transition_after is not None else None
        ),
        audio=audio_plan,
        evidence_ids=[uuid4()],
        rationale="The shot advances the concept.",
    )


def valid_clips() -> list[ClipPlan]:
    return [
        clip(
            order=0,
            timeline_start=0,
            timeline_end=150,
            transition_after="CLEAN_CUT",
            role=ClipRole.INTRO_DIALOGUE,
            keep_audio=True,
        ),
        clip(
            order=1,
            timeline_start=150,
            timeline_end=180,
            transition_after="CLEAN_CUT",
            role=ClipRole.HANDOFF,
        ),
        clip(
            order=2,
            timeline_start=180,
            timeline_end=210,
            role=ClipRole.MONTAGE,
        ),
    ]


def plan_from_payload(
    payload: dict[str, object],
    *,
    compiler_version: str = "m0-contract-seed",
    check_codes: set[str] | frozenset[str] = MANDATORY_PLAN_VALIDATION_CODES,
    fingerprint: str | None = None,
) -> CompiledEditPlan:
    bound_fingerprint = fingerprint or calculate_compiled_plan_fingerprint(
        payload, compiler_version
    )
    return CompiledEditPlan(
        **payload,
        validation_report=PlanValidationReport(
            compiler_run_id=uuid4(),
            compiler_version=compiler_version,
            validated_at=NOW,
            input_fingerprint=bound_fingerprint,
            checks=[
                ValidationCheck(
                    code=code,
                    passed=True,
                    detail=f"Trusted compiler passed {code}.",
                )
                for code in sorted(check_codes)
            ],
        ),
    )


def compiled_plan(clips: list[ClipPlan]) -> CompiledEditPlan:
    handoff_frame = next(
        (
            value.timeline_start_frame
            for value in clips
            if value.role is ClipRole.HANDOFF
        ),
        0,
    )
    beat_id = uuid4()
    clips = [
        value.model_copy(update={"song_beat_anchor_id": beat_id})
        if value.role is ClipRole.HANDOFF
        else value
        for value in clips
    ]
    song_time_base = Rational(numerator=1, denominator=48_000)
    song_range = resolved_range(
        0,
        max(240_000, (clips[-1].timeline_end_frame - handoff_frame + 60) * 1_600),
        stream_type=StreamType.AUDIO,
        stream_index=0,
        time_base=song_time_base,
    )
    payload: dict[str, object] = {
        "schema_version": "1.0.0",
        "plan_id": uuid4(),
        "revision": 1,
        "parent_plan_id": None,
        "grammar_id": "DIALOGUE_DROP_EDIT_V1",
        "grammar_version": "1.0.0",
        "preset_registry_version": "m0-safe-1",
        "concept": "A cause-and-consequence dialogue-drop edit.",
        "output_aspect": Rational(numerator=4, denominator=3),
        "output_frame_rate": Rational(numerator=30, denominator=1),
        "conform_policy": "EXACT_OR_ONE_OUTPUT_FRAME",
        "song_handoff": SongHandoffPlan(
            song_map_id=uuid4(),
            beat_id=beat_id,
            song_source_range=song_range,
            song_timeline_start_frame=handoff_frame,
            beat_point=MediaPoint(pts=0, time_base=song_time_base),
            resolved_timeline_frame=handoff_frame,
            quantization_error=SignedRational(numerator=0, denominator=1),
            dialogue_tail_frames=min(30, handoff_frame),
            music_pre_lap_frames=0,
            source_fade_out_frames=min(5, handoff_frame),
            song_fade_in_frames=15,
            accent=AudioAccent.NONE,
        ),
        "ending": EndingPlan(preset=EndingPreset.END_ON_IMAGE, duration_frames=0),
        "expected_duration_frames": clips[-1].timeline_end_frame,
        "clips": clips,
    }
    return plan_from_payload(payload)


def passed_evidence() -> list[OpportunityEvidenceReference]:
    return [
        OpportunityEvidenceReference(
            claim_id=uuid4(),
            role=EvidenceRole.PRIMARY_WHY_NOW,
            independence_group="official-network",
            supports_why_now=True,
        ),
        OpportunityEvidenceReference(
            claim_id=uuid4(),
            role=EvidenceRole.QUALITATIVE_SIGNAL,
            independence_group="x-discussion",
            supports_why_now=True,
        ),
        OpportunityEvidenceReference(
            claim_id=uuid4(),
            role=EvidenceRole.QUALITATIVE_SIGNAL,
            independence_group="editorial-coverage",
            supports_why_now=True,
        ),
    ]


class ContractTests(unittest.TestCase):
    def test_research_intent_forbids_extra_fields(self) -> None:
        with self.assertRaises(ValidationError):
            ResearchIntent(
                query="recent character rivalry",
                media_kinds=[MediaKind.TV_EPISODE],
                unexpected=True,
            )

    def test_strict_primitives_reject_string_integers(self) -> None:
        with self.assertRaises(ValidationError):
            Rational(numerator="1", denominator=30)

    def test_opportunity_pass_requires_structured_independent_evidence(self) -> None:
        opportunity = TrendOpportunityDraft(
            media_kind=MediaKind.TV_EPISODE,
            title="Example — S01E03",
            focus=OpportunityFocus(
                characters=["A", "B"],
                relationship_or_topic="trust after a reversal",
            ),
            why_now="A new episode centers this conflict.",
            creative_hook="Set up the broken promise, then contrast earlier trust.",
            evidence=passed_evidence(),
            evidence_gate=EvidenceGate.PASSED,
            confidence=0.8,
        )
        self.assertEqual(len(opportunity.evidence), 3)

    def test_opportunity_rejects_copied_signal_groups(self) -> None:
        evidence = passed_evidence()
        evidence[2] = evidence[2].model_copy(
            update={"independence_group": "x-discussion"}
        )
        with self.assertRaises(ValidationError):
            TrendOpportunityDraft(
                media_kind=MediaKind.TV_EPISODE,
                title="Example — S01E03",
                focus=OpportunityFocus(
                    relationship_or_topic="trust after a reversal"
                ),
                why_now="A new episode centers this conflict.",
                creative_hook="Contrast earlier trust with the reversal.",
                evidence=evidence,
                evidence_gate=EvidenceGate.PASSED,
                confidence=0.8,
            )

    def test_verified_quote_requires_authoritative_claim(self) -> None:
        with self.assertRaises(ValidationError):
            FootageRequirementDraft(
                order=0,
                required=True,
                media_title="Example",
                season_episode_or_asset="S01E03",
                moment_description="The promise is broken.",
                quote_status=QuoteStatus.VERIFIED,
                quote_text="I promised.",
                rationale="Sets up the reversal.",
            )

    def test_media_range_rejects_reverse_pts(self) -> None:
        with self.assertRaises(ValidationError):
            resolved_range(30, 10)

    def test_media_range_rejects_cross_stream_endpoints(self) -> None:
        valid = resolved_range(0, 30)
        wrong_end = valid.end.model_copy(update={"stream_index": 2})
        with self.assertRaises(ValidationError):
            ResolvedMediaRange(
                start=valid.start,
                end=wrong_end,
                asset_clock_mapping_id=valid.asset_clock_mapping_id,
            )

    def test_negative_pts_and_vfr_frame_resolution_are_valid(self) -> None:
        value = resolved_range(
            -3_003,
            87_087,
            time_base=Rational(numerator=1, denominator=90_000),
            start_frame=0,
            end_frame=30,
        )
        self.assertEqual(value.start.point.pts, -3_003)

    def test_video_frame_indices_must_increase_with_pts(self) -> None:
        valid = resolved_range(0, 30, start_frame=10, end_frame=11)
        bad_point = valid.end.point.model_copy(update={"frame_index": 9})
        bad_end = valid.end.model_copy(update={"point": bad_point})
        with self.assertRaises(ValidationError):
            ResolvedMediaRange(
                start=valid.start,
                end=bad_end,
                asset_clock_mapping_id=valid.asset_clock_mapping_id,
            )

    def test_audio_and_video_ranges_keep_separate_time_bases(self) -> None:
        source_id = uuid4()
        mapping_id = uuid4()
        picture = resolved_range(
            0,
            90_000,
            time_base=Rational(numerator=1, denominator=90_000),
            source_id=source_id,
            clock_mapping_id=mapping_id,
            start_frame=0,
            end_frame=30,
        )
        audio = resolved_range(
            0,
            48_000,
            stream_type=StreamType.AUDIO,
            stream_index=1,
            time_base=Rational(numerator=1, denominator=48_000),
            source_id=source_id,
            clock_mapping_id=mapping_id,
        )
        mapping = AssetClockMapping(
            mapping_id=mapping_id,
            source_media_id=source_id,
            source_sha256=HASH,
            video_stream_index=0,
            audio_stream_index=1,
            video_origin=MediaPoint(
                pts=0,
                time_base=Rational(numerator=1, denominator=90_000),
                frame_index=0,
            ),
            audio_origin=MediaPoint(
                pts=0,
                time_base=Rational(numerator=1, denominator=48_000),
            ),
            resolver_id="ffprobe-stream-clock-map-v1",
            resolution_evidence_id=uuid4(),
            confidence=0.99,
        )
        value = ClipPlan(
            clip_id=uuid4(),
            order=0,
            role=ClipRole.INTRO_DIALOGUE,
            source_range=picture,
            source_handle_before_pts=0,
            source_handle_after_pts=0,
            timeline_start_frame=0,
            timeline_end_frame=30,
            audio=ClipAudioPlan(
                policy=ClipAudioPolicy.KEEP_SOURCE,
                source_range=audio,
                clock_mapping=mapping,
            ),
            evidence_ids=[uuid4()],
            rationale="Preserves the opening dialogue.",
        )
        self.assertEqual(value.audio.source_range.start.stream_index, 1)

    def test_audio_interval_must_map_to_picture_duration(self) -> None:
        value = clip(
            order=0,
            timeline_start=0,
            timeline_end=30,
            role=ClipRole.INTRO_DIALOGUE,
            keep_audio=True,
        )
        assert value.audio.source_range is not None
        long_audio = resolved_range(
            0,
            480_000,
            stream_type=StreamType.AUDIO,
            stream_index=1,
            time_base=Rational(numerator=1, denominator=48_000),
            source_id=value.source_range.start.source_media_id,
            clock_mapping_id=value.source_range.asset_clock_mapping_id,
        )
        bad_audio = value.audio.model_copy(update={"source_range": long_audio})
        with self.assertRaises(ValidationError):
            ClipPlan(**{**value.model_dump(), "audio": bad_audio})

    def test_unregistered_and_reserved_velocity_presets_are_rejected(self) -> None:
        base = clip(order=0, timeline_start=0, timeline_end=30)
        for value in ("100 -> 437 -> 28 -> 191", "IMPACT", "SOFT_PUSH"):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                ClipPlan(**{**base.model_dump(), "velocity_preset": value})

    def test_static_duration_must_match_timeline(self) -> None:
        clips = valid_clips()
        clips[2] = clip(
            order=2,
            timeline_start=180,
            timeline_end=240,
            source_start=0,
            source_end=30,
            role=ClipRole.MONTAGE,
        )
        with self.assertRaises(ValidationError):
            compiled_plan(clips)

    def test_plan_requires_contiguous_order_and_timeline(self) -> None:
        clips = valid_clips()
        clips[2] = clips[2].model_copy(update={"order": 3})
        with self.assertRaises(ValidationError):
            compiled_plan(clips)

    def test_terminal_transition_is_rejected(self) -> None:
        clips = valid_clips()
        clips[2] = clips[2].model_copy(
            update={
                "transition_after": "CLEAN_CUT",
                "transition_preset_version": "CLEAN_CUT@1",
            }
        )
        with self.assertRaises(ValidationError):
            compiled_plan(clips)

    def test_valid_compiled_plan(self) -> None:
        value = compiled_plan(valid_clips())
        self.assertEqual(value.expected_duration_frames, 210)
        self.assertEqual(value.song_handoff.resolved_timeline_frame, 150)

    def test_dialogue_drop_requires_intro_handoff_and_montage_roles(self) -> None:
        clips = valid_clips()
        clips[0] = clips[0].model_copy(update={"role": ClipRole.MONTAGE})
        with self.assertRaises(ValidationError):
            compiled_plan(clips)

    def test_beat_quantization_is_recomputed(self) -> None:
        value = compiled_plan(valid_clips())
        payload = value.model_dump(mode="python", exclude={"validation_report"})
        handoff = value.song_handoff.model_copy(
            update={
                "song_timeline_start_frame": 120,
                "beat_point": MediaPoint(
                    pts=48_000,
                    time_base=Rational(numerator=1, denominator=48_000),
                ),
                "music_pre_lap_frames": 30,
                "quantization_error": SignedRational(numerator=1, denominator=2),
            }
        )
        payload["song_handoff"] = handoff
        with self.assertRaises(ValidationError):
            plan_from_payload(payload)

    def test_cumulative_static_rounding_cannot_drift(self) -> None:
        clips = valid_clips()[:2]
        for index in range(20):
            is_last = index == 19
            clips.append(
                clip(
                    order=index + 2,
                    timeline_start=180 + index * 30,
                    timeline_end=210 + index * 30,
                    source_start=0,
                    source_end=29,
                    transition_after=None if is_last else "CLEAN_CUT",
                    role=ClipRole.MONTAGE,
                )
            )
        with self.assertRaises(ValidationError):
            compiled_plan(clips)

    def test_validation_report_requires_all_mandatory_codes(self) -> None:
        value = compiled_plan(valid_clips())
        payload = value.model_dump(mode="python", exclude={"validation_report"})
        missing = set(MANDATORY_PLAN_VALIDATION_CODES) - {"source.boundaries"}
        with self.assertRaises(ValidationError):
            plan_from_payload(payload, check_codes=missing)

    def test_validation_report_fingerprint_binds_payload(self) -> None:
        value = compiled_plan(valid_clips())
        payload = value.model_dump(mode="python", exclude={"validation_report"})
        with self.assertRaises(ValidationError):
            plan_from_payload(payload, fingerprint=HASH)

    def test_price_component_uses_rounded_micro_usd_arithmetic(self) -> None:
        with self.assertRaises(ValidationError):
            PriceComponent(
                category="model_tokens",
                quantity=Decimal("0.3333333"),
                unit="million_tokens",
                unit_price_micro_usd=2_000_000,
                maximum_cost_micro_usd=666_666,
            )

    def test_cost_estimate_total_must_equal_components(self) -> None:
        component = PriceComponent(
            category="model_tokens",
            quantity=Decimal("1"),
            unit="request",
            unit_price_micro_usd=400_000,
            maximum_cost_micro_usd=400_000,
        )
        with self.assertRaises(ValidationError):
            CostEstimate(
                estimate_id=uuid4(),
                operation="research.run",
                provider="xai",
                configured_model="grok-4.6",
                price_card_id=uuid4(),
                components=[component],
                expected_cost_micro_usd=0,
                maximum_cost_micro_usd=0,
                hard_limit_micro_usd=500_000,
                already_spent_or_reserved_micro_usd=0,
                privacy_notice="Public search queries only.",
            )

    def test_cost_estimate_cannot_cross_hard_limit(self) -> None:
        component = PriceComponent(
            category="model_tokens",
            quantity=Decimal("1"),
            unit="request",
            unit_price_micro_usd=400_000,
            maximum_cost_micro_usd=400_000,
        )
        with self.assertRaises(ValidationError):
            CostEstimate(
                estimate_id=uuid4(),
                operation="research.run",
                provider="xai",
                configured_model="grok-4.6",
                price_card_id=uuid4(),
                components=[component],
                expected_cost_micro_usd=300_000,
                maximum_cost_micro_usd=400_000,
                hard_limit_micro_usd=500_000,
                already_spent_or_reserved_micro_usd=200_000,
                privacy_notice="Public search queries only.",
            )

    def test_cache_hit_cost_must_be_zero(self) -> None:
        component = PriceComponent(
            category="cache_replay",
            quantity=Decimal("1"),
            unit="replay",
            unit_price_micro_usd=1,
            maximum_cost_micro_usd=1,
        )
        with self.assertRaises(ValidationError):
            CostEstimate(
                estimate_id=uuid4(),
                operation="research.run",
                provider="xai",
                configured_model="grok-4.6",
                price_card_id=uuid4(),
                components=[component],
                expected_cost_micro_usd=1,
                maximum_cost_micro_usd=1,
                hard_limit_micro_usd=500_000,
                already_spent_or_reserved_micro_usd=0,
                cache_hit=True,
                privacy_notice="No provider call; replaying a validated cache entry.",
            )

    def test_micro_usd_rejects_sqlite_integer_overflow(self) -> None:
        with self.assertRaises(ValidationError):
            PriceComponent(
                category="overflow",
                quantity=Decimal("1"),
                unit="request",
                unit_price_micro_usd=9_223_372_036_854_775_808,
                maximum_cost_micro_usd=9_223_372_036_854_775_808,
            )

    def test_production_defaults_ignore_hostile_environment(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "AI_EDIT_LIVE_CALLS": "true",
                "AI_EDIT_TREND_MODEL": "attacker-model",
                "AI_EDIT_RESEARCH_HARD_LIMIT_USD": "999999",
            },
        ):
            settings = RuntimeSettings.production_defaults()
        self.assertFalse(settings.development_live_calls_enabled)
        self.assertEqual(settings.models.trend_research, "grok-4.6")
        self.assertEqual(settings.research_hard_limit_usd, Decimal("0.50"))

    def test_development_settings_are_explicit(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "AI_EDIT_LIVE_CALLS": "false",
                "AI_EDIT_VIDEO_MODEL": "gemini-3.7-flash",
            },
        ):
            settings = RuntimeSettings.development_from_environment()
        self.assertFalse(settings.development_live_calls_enabled)
        self.assertEqual(settings.models.video_reasoning, "gemini-3.7-flash")

    def test_model_envelope_rejects_naive_datetime(self) -> None:
        with self.assertRaises(ValidationError):
            ModelRunEnvelope(
                schema_name="trend-opportunity-draft",
                prompt_version="m1-v1",
                trace_id=uuid4(),
                job_id=uuid4(),
                provider="xai",
                configured_model="grok-4.6",
                generated_at=datetime.now(),
                input_fingerprint=HASH,
                outcome=ModelRunOutcome.SUCCESS,
                payload_sha256=HASH,
            )

    def test_model_envelope_outcomes_are_exclusive(self) -> None:
        with self.assertRaises(ValidationError):
            ModelRunEnvelope(
                schema_name="trend-opportunity-draft",
                prompt_version="m1-v1",
                trace_id=uuid4(),
                job_id=uuid4(),
                provider="xai",
                configured_model="grok-4.6",
                generated_at=NOW,
                input_fingerprint=HASH,
                outcome=ModelRunOutcome.REFUSAL,
                payload_sha256=HASH,
                refusal="Policy refusal.",
                incomplete="Maximum output reached.",
            )

    def test_execution_contracts_are_not_provider_outputs(self) -> None:
        self.assertTrue(
            set(PROVIDER_OUTPUT_CONTRACTS).isdisjoint(TRUSTED_EXECUTION_CONTRACTS)
        )
        self.assertIn("compiled-edit-plan", TRUSTED_EXECUTION_CONTRACTS)
        self.assertIn("model-run-envelope", CANONICAL_STORAGE_CONTRACTS)


if __name__ == "__main__":
    unittest.main()
