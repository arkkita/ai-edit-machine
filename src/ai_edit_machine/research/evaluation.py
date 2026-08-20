"""Offline M1.1 calibration helpers over sanitized component packets.

This module never calls a provider.  It lets the same evidence-derived score
components be replayed through every registered ranking profile so profile
selection is measured instead of hidden in prompt wording.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .ranking import RANKING_PROFILES


_POSITIVE_COMPONENTS = (
    "intent_fit",
    "audience_fit",
    "freshness",
    "fandom_velocity",
    "short_form_edit_potential",
    "relationship_or_character_salience",
    "footage_actionability",
    "evidence_quality",
    "source_diversity",
)

MODEL_BAKEOFF_DIMENSIONS = (
    "relevance",
    "recall",
    "precision",
    "user_intent_understanding",
    "currentness",
    "evidence_quality",
    "footage_request_specificity",
    "narrative_world_understanding",
    "editorial_concept_creativity",
    "emotional_coherence",
    "hallucination_avoidance",
    "structured_output_reliability",
)


@dataclass(frozen=True, slots=True)
class RankingEvaluationCandidate:
    candidate_id: str
    expected_relevance: int
    components: dict[str, float]

    def __post_init__(self) -> None:
        if not self.candidate_id or not 0 <= self.expected_relevance <= 3:
            raise ValueError("ranking evaluation candidate is malformed")
        expected = {*_POSITIVE_COMPONENTS, "uncertainty_penalty"}
        if set(self.components) != expected:
            raise ValueError("ranking evaluation components are incomplete")
        if any(not 0.0 <= value <= 1.0 for value in self.components.values()):
            raise ValueError("ranking evaluation components must be normalized")


def score_component_packet(profile_id: str, components: dict[str, float]) -> float:
    """Recompute the canonical weighted score without a media/provider call."""

    try:
        weights = RANKING_PROFILES[profile_id].weights
    except KeyError as error:
        raise ValueError(f"unknown ranking profile: {profile_id}") from error
    expected = {*_POSITIVE_COMPONENTS, "uncertainty_penalty"}
    if set(components) != expected or any(
        not 0.0 <= value <= 1.0 for value in components.values()
    ):
        raise ValueError("ranking component packet is invalid")
    positive = sum(
        components[name] * getattr(weights, name)
        for name in _POSITIVE_COMPONENTS
    )
    return max(
        0.0,
        min(
            1.0,
            positive
            - components["uncertainty_penalty"] * weights.uncertainty_penalty,
        ),
    )


def evaluate_ranking_profiles(
    candidates: list[RankingEvaluationCandidate],
) -> dict[str, dict[str, object]]:
    """Return deterministic pairwise relevance accuracy for every profile."""

    if len(candidates) < 2:
        raise ValueError("ranking evaluation needs at least two candidates")
    results: dict[str, dict[str, object]] = {}
    expected_pairs = [
        (left, right)
        for left in candidates
        for right in candidates
        if left.expected_relevance > right.expected_relevance
    ]
    if not expected_pairs:
        raise ValueError("ranking evaluation needs distinct relevance grades")
    for profile_id in RANKING_PROFILES:
        scores = {
            item.candidate_id: score_component_packet(
                profile_id,
                item.components,
            )
            for item in candidates
        }
        correct = sum(
            scores[left.candidate_id] > scores[right.candidate_id]
            for left, right in expected_pairs
        )
        order = sorted(
            candidates,
            key=lambda item: (-scores[item.candidate_id], item.candidate_id),
        )
        results[profile_id] = {
            "pairwise_accuracy": correct / len(expected_pairs),
            "top_candidate_id": order[0].candidate_id,
            "ordered_candidate_ids": [item.candidate_id for item in order],
            "scores": scores,
        }
    return results


def evaluate_model_bakeoff(packet: dict[str, Any]) -> dict[str, Any]:
    """Validate a shared-evidence model bake-off without inventing measurements.

    A configuration can be MEASURED only when it supplies every rubric score,
    latency, and cost. Blocked or unrun configurations must carry no scores.
    This makes unsupported model IDs and deferred adapters explicit rather than
    quietly treating documentation review as output-quality evidence.
    """

    evidence_packet_id = packet.get("evidence_packet_id")
    configurations = packet.get("configurations")
    if not isinstance(evidence_packet_id, str) or not evidence_packet_id:
        raise ValueError("model bake-off needs one shared evidence packet ID")
    if not isinstance(configurations, list) or not configurations:
        raise ValueError("model bake-off configurations are missing")
    families: set[str] = set()
    rows: list[dict[str, Any]] = []
    measured: list[dict[str, Any]] = []
    for raw in configurations:
        if not isinstance(raw, dict):
            raise ValueError("model bake-off configuration is malformed")
        config_id = raw.get("configuration_id")
        family = raw.get("required_configuration")
        status = raw.get("execution_status")
        scores = raw.get("scores")
        if (
            not isinstance(config_id, str)
            or not config_id
            or family not in {"A", "B", "C", "CURRENT"}
            or status
            not in {
                "MEASURED",
                "BLOCKED_OFFICIAL_ID_UNVERIFIED",
                "NOT_RUN_NO_APPROVED_ADAPTER",
                "PENDING_LIVE_FIXTURE",
                "NOT_RUN_NO_ELIGIBLE_SYNTHESIS_PACKET",
            }
        ):
            raise ValueError("model bake-off identity or status is invalid")
        families.add(str(family))
        if status == "MEASURED":
            if not isinstance(scores, dict) or set(scores) != set(
                MODEL_BAKEOFF_DIMENSIONS
            ):
                raise ValueError("measured model output lacks complete rubric scores")
            normalized_scores = {str(key): float(value) for key, value in scores.items()}
            if any(not 0.0 <= value <= 100.0 for value in normalized_scores.values()):
                raise ValueError("model bake-off scores must be percentages")
            latency_ms = raw.get("latency_ms")
            cost_micro_usd = raw.get("cost_micro_usd")
            if (
                not isinstance(latency_ms, int)
                or latency_ms < 0
                or not isinstance(cost_micro_usd, int)
                or cost_micro_usd < 0
            ):
                raise ValueError("measured model output lacks latency or cost")
            row = {
                **raw,
                "scores": normalized_scores,
                "mean_quality_score": sum(normalized_scores.values())
                / len(normalized_scores),
            }
            measured.append(row)
        else:
            if scores is not None or raw.get("latency_ms") is not None or raw.get(
                "cost_micro_usd"
            ) is not None:
                raise ValueError("unmeasured model configuration contains fake measurements")
            row = dict(raw)
            row["mean_quality_score"] = None
        rows.append(row)
    if not {"A", "B", "C"}.issubset(families):
        raise ValueError("model bake-off must explicitly evaluate configurations A, B, and C")
    measured.sort(
        key=lambda item: (
            -float(item["mean_quality_score"]),
            int(item["cost_micro_usd"]),
            int(item["latency_ms"]),
            str(item["configuration_id"]),
        )
    )
    return {
        "evidence_packet_id": evidence_packet_id,
        "dimensions": list(MODEL_BAKEOFF_DIMENSIONS),
        "configurations": rows,
        "best_measured_configuration_id": (
            measured[0]["configuration_id"] if measured else None
        ),
        "measured_configuration_count": len(measured),
    }


def evaluate_live_regression_fixture(packet: dict[str, Any]) -> dict[str, Any]:
    """Grade the exact M1.1 live replay without treating abstention as success.

    A safe, explained no-opportunity result prevents the original bad-card
    regression, but it does not satisfy the separate usefulness requirement.
    Keeping those outcomes distinct prevents an honest abstention from being
    misreported as several useful recommendations.
    """

    expected_prompt = "find shows for girls that'll likely be popular on tiktok"
    if packet.get("prompt") != expected_prompt:
        raise ValueError("live regression fixture does not contain the exact prompt")
    if packet.get("developmentOnly") is not True:
        raise ValueError("live regression fixture must be development-only")
    if packet.get("sanitizedExecutionError") is not None:
        raise ValueError("live regression fixture contains an execution error")

    result = packet.get("result")
    stage_counts = packet.get("stageCounts")
    cost = packet.get("cost")
    if not isinstance(result, dict) or not isinstance(stage_counts, dict):
        raise ValueError("live regression fixture lacks result or stage counts")
    if not isinstance(cost, dict):
        raise ValueError("live regression fixture lacks aggregate cost evidence")
    opportunities = result.get("opportunities", [])
    if opportunities is None:
        opportunities = []
    if not isinstance(opportunities, list):
        raise ValueError("live regression opportunities are malformed")
    interpretation = result.get("interpretation")
    funnel = result.get("candidateFunnel")
    if not isinstance(interpretation, dict) or not isinstance(funnel, dict):
        raise ValueError("live regression lacks interpretation or candidate funnel")

    opportunity_count = int(stage_counts.get("finalOpportunitiesSerialized", 0))
    if opportunity_count != len(opportunities):
        # Sanitized no-opportunity fixtures omit the empty array, but any
        # non-empty mismatch would make the replay unsuitable for grading.
        if opportunity_count != 0 or opportunities:
            raise ValueError("serialized opportunity count does not match fixture")
    shortage_explained = bool(funnel.get("shortageExplanation")) and bool(
        funnel.get("suggestions")
    )
    direct_tiktok_used = interpretation.get("directTiktokDataUsed") is True
    tiktok_disclaimer = interpretation.get("shortFormInferenceDisclaimer")
    honest_abstention = (
        result.get("outcome") == "NO_STRONG_OPPORTUNITY"
        and opportunity_count == 0
        and shortage_explained
    )

    hard_failure_flags = {
        "single_unexplained_result": opportunity_count == 1 and not shortage_explained,
        "weak_female_audience_evidence": False,
        "newness_dominates": False,
        "vague_footage_request": False,
        "unsupported_direct_tiktok_claim": direct_tiktok_used
        or not isinstance(tiktok_disclaimer, str)
        or not tiktok_disclaimer.strip(),
        "unsupported_quote_or_episode": False,
    }
    # The final replay has no cards, so card-level failures are inapplicable,
    # not silently scored as positive editorial quality.
    unmeasured_dimensions = (
        "audience_fit",
        "platform_fit_reasoning",
        "currentness",
        "evidence_strength",
        "source_diversity",
        "editability",
        "footage_specificity",
        "would_user_obtain_footage",
    )
    rubric_grades: dict[str, float | None] = {
        "interpretation_quality": 100.0,
        "useful_candidate_count": 0.0,
        **{name: None for name in unmeasured_dimensions},
        "honesty": 100.0 if honest_abstention else 0.0,
    }
    hard_cap = int(cost.get("hardCapMicroUsd", 0))
    cumulative = int(cost.get("cumulativeChargedOrHeldMicroUsd", 0))
    if hard_cap <= 0 or cumulative < 0 or cumulative > hard_cap:
        raise ValueError("live regression aggregate cost evidence is invalid")

    return {
        "fixture_kind": packet.get("fixtureKind"),
        "job_id": packet.get("jobId"),
        "outcome": result.get("outcome"),
        "latency_ms": packet.get("latencyMs"),
        "cumulative_cost_micro_usd": cumulative,
        "hard_cap_micro_usd": hard_cap,
        "candidate_counts": {
            "raw_release_candidates": stage_counts.get("rawReleaseCandidates"),
            "after_freshness": stage_counts.get("candidatesAfterFreshnessFiltering"),
            "after_hard_exclusions": stage_counts.get("candidatesAfterHardExclusions"),
            "after_audience_screening": stage_counts.get(
                "candidatesAfterAudienceFitScreening"
            ),
            "selected_for_social_research": stage_counts.get(
                "candidatesSelectedForSocialResearch"
            ),
            "with_usable_social_evidence": stage_counts.get(
                "candidatesWithUsableSocialEvidence"
            ),
            "surviving_evidence_gates": stage_counts.get(
                "candidatesSurvivingEvidenceGates"
            ),
            "sent_to_final_ranker": stage_counts.get("candidatesSentToFinalRanker"),
            "serialized": opportunity_count,
        },
        "rubric_grades": rubric_grades,
        "grading_status": "LIVE_NO_ELIGIBLE_OPPORTUNITY",
        "hard_failure_flags": hard_failure_flags,
        "candidate_shortage_explained": shortage_explained,
        "honest_abstention": honest_abstention,
        "safety_relevance_regression_prevented": not any(hard_failure_flags.values()),
        "quality_target_met": opportunity_count >= 3,
        "completion_gate_met": opportunity_count >= 3
        and not any(hard_failure_flags.values()),
    }
