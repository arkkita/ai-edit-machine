"""Versioned, explainable M1.1 relevance and editorial-quality scoring."""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from ..contracts import EvidenceGate, EvidenceRole
from ..m1_contracts import (
    EditorialConceptDraftV1,
    EditorialConceptScoreV1,
    EvidenceClaimRecordV2,
    EvidenceSourceRecordV2,
    FootageRequestV2,
    FootageVerificationLevel,
    LegacyConnectionType,
    OpportunityQualityScoreV1,
    OpportunityRankingWeightsV1,
    ResearchIntentV2,
    ShortFormEditPotentialV1,
    ShortFormPotentialBand,
    TrendOpportunityV2,
)


@dataclass(frozen=True, slots=True)
class RankingProfile:
    profile_id: str
    weights: OpportunityRankingWeightsV1


# Three profiles are exercised by the dated M1.1 evaluation harness. The
# selected production default is explicit; changing it requires updated golden
# scores rather than an opaque prompt tweak.
RANKING_PROFILES: dict[str, RankingProfile] = {
    "m1.1-intent-editorial-v1": RankingProfile(
        profile_id="m1.1-intent-editorial-v1",
        weights=OpportunityRankingWeightsV1(
            intent_fit=0.17,
            audience_fit=0.14,
            freshness=0.08,
            fandom_velocity=0.13,
            short_form_edit_potential=0.13,
            relationship_or_character_salience=0.10,
            footage_actionability=0.10,
            evidence_quality=0.09,
            source_diversity=0.06,
            uncertainty_penalty=0.25,
        ),
    ),
    "m1.1-balanced-v1": RankingProfile(
        profile_id="m1.1-balanced-v1",
        weights=OpportunityRankingWeightsV1(
            intent_fit=0.14,
            audience_fit=0.11,
            freshness=0.11,
            fandom_velocity=0.12,
            short_form_edit_potential=0.11,
            relationship_or_character_salience=0.10,
            footage_actionability=0.12,
            evidence_quality=0.11,
            source_diversity=0.08,
            uncertainty_penalty=0.22,
        ),
    ),
    "m1.1-freshness-heavy-control-v1": RankingProfile(
        profile_id="m1.1-freshness-heavy-control-v1",
        weights=OpportunityRankingWeightsV1(
            intent_fit=0.12,
            audience_fit=0.09,
            freshness=0.25,
            fandom_velocity=0.11,
            short_form_edit_potential=0.10,
            relationship_or_character_salience=0.08,
            footage_actionability=0.09,
            evidence_quality=0.10,
            source_diversity=0.06,
            uncertainty_penalty=0.20,
        ),
    ),
}

DEFAULT_RANKING_PROFILE_ID = "m1.1-intent-editorial-v1"


_FEMALE_AUDIENCE_DIRECT = re.compile(
    r"\b(?:female[\s-]*(?:skewing\s+)?(?:audience|fandom|fans?|viewers?)|"
    r"(?:girls?|women)\s+(?:audience|fandom|fans?|viewers?|watchers?|discussion)|"
    r"popular\s+(?:among|with)\s+(?:girls?|women))\b",
    re.IGNORECASE,
)
_FEMALE_AFFINITY_CUE = re.compile(
    r"\b(?:female[\s-]*(?:centered|centred|focused|led)|women\s+at\s+the\s+center|"
    r"cent(?:er|re)s?\s+(?:its\s+)?women|"
    r"heroines?|mother|daughter|sister|young[\s-]?adult|teen(?:age)?r?s?|romance|"
    r"romantic|romcom|ship(?:ping)?|couple|chemistry|kiss|confession|"
    r"relationship\s+fandom)\b",
    re.IGNORECASE,
)
_MALE_AUDIENCE_DIRECT = re.compile(
    r"\b(?:male[\s-]*(?:skewing\s+)?(?:audience|fandom|fans?|viewers?)|"
    r"(?:boys?|men)\s+(?:audience|fandom|fans?|viewers?|watchers?|discussion)|"
    r"popular\s+(?:among|with)\s+(?:boys?|men))\b",
    re.IGNORECASE,
)
_MALE_AFFINITY_CUE = re.compile(
    r"\b(?:male[\s-]*(?:centered|centred|focused|led)|action|combat|military|"
    r"sports?|rivalry|underdog|victory|power\s+shift)\b",
    re.IGNORECASE,
)
_EDITABILITY_SIGNAL = re.compile(
    r"\b(?:ship(?:ping)?|chemistry|kiss|confession|argument|reunion|reaction|"
    r"quote|dialogue|scene|clip|trailer|callback|parallel|friendship|rivalry|"
    r"breakup|betrayal|reveal|twist|character|relationship|fan\s+edit)\b",
    re.IGNORECASE,
)

_CONCEPT_STOP_WORDS = frozenset(
    {
        "about",
        "after",
        "again",
        "before",
        "between",
        "character",
        "characters",
        "clip",
        "clips",
        "current",
        "edit",
        "episode",
        "footage",
        "from",
        "into",
        "montage",
        "moment",
        "moments",
        "scene",
        "scenes",
        "series",
        "show",
        "their",
        "this",
        "trailer",
        "with",
    }
)
_PAYOFF_LANGUAGE = re.compile(
    r"\b(?:answer|callback|complete|echo|payoff|reframe|return|reveal|resolve|"
    r"recognition|reunion|then|now)\b",
    re.IGNORECASE,
)


def _bounded(value: float) -> float:
    return max(0.0, min(1.0, value))


def _content_tokens(value: str) -> set[str]:
    return {
        token.casefold()
        for token in re.findall(r"[A-Za-z][A-Za-z'-]{2,}", value)
        if token.casefold() not in _CONCEPT_STOP_WORDS
    }


def _verification_strength(level: FootageVerificationLevel) -> float:
    return {
        FootageVerificationLevel.VERIFIED: 1.0,
        FootageVerificationLevel.STRONGLY_SUPPORTED: 0.82,
        FootageVerificationLevel.LIKELY_INFERRED: 0.58,
        FootageVerificationLevel.UNKNOWN: 0.20,
    }[level]


def _anchor_coverage(anchor: set[str], value: str, *, target: int = 2) -> float:
    if not anchor:
        return 0.0
    return _bounded(len(anchor & _content_tokens(value)) / max(1, target))


def _soft_audience_fit(corpus: str, facet_ids: set[str]) -> float:
    """Return an evidence-derived audience prior, never a demographic claim.

    A direct audience statement scores highest. Two distinct affinity cues can
    clear the minimum quality gate, while one romance/action label alone stays
    below it. This mirrors the pre-synthesis evidence floor.
    """

    if "female_skewing_fandom" in facet_ids:
        if _FEMALE_AUDIENCE_DIRECT.search(corpus):
            return 0.90
        cue_count = len(
            {
                match.group(0).casefold()
                for match in _FEMALE_AFFINITY_CUE.finditer(corpus)
            }
        )
        return 0.55 if cue_count >= 2 else 0.30 if cue_count == 1 else 0.05
    if "male_skewing_fandom" in facet_ids:
        if _MALE_AUDIENCE_DIRECT.search(corpus):
            return 0.90
        cue_count = len(
            {
                match.group(0).casefold()
                for match in _MALE_AFFINITY_CUE.finditer(corpus)
            }
        )
        return 0.55 if cue_count >= 2 else 0.30 if cue_count == 1 else 0.05
    if "queer_fandom" in facet_ids:
        return 0.90 if re.search(
            r"\b(?:queer|lgbtq\+?|gay|lesbian|bisexual)\s+"
            r"(?:audience|fandom|fans?|viewers?|discussion)\b",
            corpus,
            re.IGNORECASE,
        ) else 0.05
    return 0.70


def score_opportunity_quality(
    *,
    intent: ResearchIntentV2,
    opportunity: TrendOpportunityV2,
    footage: FootageRequestV2,
    sources: list[EvidenceSourceRecordV2],
    claims: list[EvidenceClaimRecordV2],
    profile_id: str = DEFAULT_RANKING_PROFILE_ID,
) -> tuple[OpportunityQualityScoreV1, ShortFormEditPotentialV1 | None]:
    profile = RANKING_PROFILES[profile_id]
    selected_ids = {UUID(str(item.claim_id)) for item in opportunity.evidence}
    source_by_id = {UUID(str(item.source_id)): item for item in sources}
    selected_claims = [
        item for item in claims if UUID(str(item.claim_id)) in selected_ids
    ]
    selected_sources = [
        source_by_id[UUID(str(item.source_id))]
        for item in selected_claims
        if UUID(str(item.source_id)) in source_by_id
    ]
    corpus = " ".join(
        [
            opportunity.focus.relationship_or_topic,
            *opportunity.focus.characters,
            *(item.text for item in selected_claims),
            *(item.title for item in selected_sources),
        ]
    )
    facets = intent.interpretation.facets if intent.interpretation is not None else []
    facet_ids = {item.facet_id for item in facets}
    audience_requested = bool(
        facet_ids & {"female_skewing_fandom", "male_skewing_fandom", "queer_fandom"}
    )
    audience_fit = _soft_audience_fit(corpus, facet_ids)

    signal_claims = [
        item
        for item in opportunity.evidence
        if item.role is EvidenceRole.QUALITATIVE_SIGNAL and item.supports_why_now
    ]
    signal_groups = {item.independence_group for item in signal_claims}
    fandom_velocity = min(1.0, len(signal_groups) / 3.0)
    editability_hits = len(_EDITABILITY_SIGNAL.findall(corpus))
    has_specific_intro = bool(footage.intro_leads)
    short_form = min(
        1.0,
        0.15 * min(editability_hits, 4)
        + (0.20 if has_specific_intro else 0.0)
        + (0.20 if opportunity.focus.characters else 0.0)
        + (0.15 if fandom_velocity >= 2 / 3 else 0.0),
    )
    salience = min(
        1.0,
        (0.45 if opportunity.focus.characters else 0.0)
        + (0.30 if _EDITABILITY_SIGNAL.search(opportunity.focus.relationship_or_topic) else 0.0)
        + (0.25 if has_specific_intro else 0.0),
    )
    intent_fit = 0.45
    if opportunity.media_kind in intent.media_kinds:
        intent_fit += 0.20
    if not audience_requested or audience_fit >= 0.40:
        intent_fit += 0.20
    if "short_form_edit_potential" not in facet_ids or short_form >= 0.40:
        intent_fit += 0.15
    intent_fit = min(1.0, intent_fit)
    evidence_quality = 1.0 if opportunity.evidence_gate is EvidenceGate.PASSED else 0.62
    source_diversity = min(
        1.0,
        len({item.independence_group for item in opportunity.evidence}) / 4.0,
    )
    unknown_sources = [
        item
        for item in (
            *footage.required_sources,
            *footage.optional_sources,
            *footage.alternative_sources,
        )
        if item.verification_level is FootageVerificationLevel.UNKNOWN
    ]
    all_footage_sources = (
        len(footage.required_sources)
        + len(footage.optional_sources)
        + len(footage.alternative_sources)
    )
    uncertainty = min(
        1.0,
        (0.30 if opportunity.evidence_gate is EvidenceGate.LOW_CONFIDENCE else 0.0)
        + (0.35 if not has_specific_intro else 0.0)
        + (0.35 * len(unknown_sources) / max(1, all_footage_sources)),
    )
    values = {
        "intent_fit": intent_fit,
        "audience_fit": audience_fit,
        "freshness": opportunity.score.release_freshness,
        "fandom_velocity": fandom_velocity,
        "short_form_edit_potential": short_form,
        "relationship_or_character_salience": salience,
        "footage_actionability": opportunity.score.footage_actionability,
        "evidence_quality": evidence_quality,
        "source_diversity": source_diversity,
        "uncertainty_penalty": uncertainty,
    }
    weighted = sum(
        values[key] * getattr(profile.weights, key)
        for key in (
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
    )
    total = max(0.0, min(1.0, weighted - uncertainty * profile.weights.uncertainty_penalty))
    quality = OpportunityQualityScoreV1(
        profile_id=profile.profile_id,
        weights=profile.weights,
        total=total,
        **values,
    )
    inference: ShortFormEditPotentialV1 | None = None
    if "short_form_edit_potential" in facet_ids:
        signals: list[str] = []
        if audience_fit >= 0.40:
            signals.append("audience-fit discussion")
        if fandom_velocity >= 2 / 3:
            signals.append("independent current fandom discussion")
        if _EDITABILITY_SIGNAL.search(corpus):
            signals.append("character, relationship, quote, or scene salience")
        if has_specific_intro:
            signals.append("a specific intro lead")
        if footage.required_sources:
            signals.append("an actionable minimum footage set")
        if not signals:
            signals.append("limited cross-platform evidence")
        inference = ShortFormEditPotentialV1(
            band=(
                ShortFormPotentialBand.HIGH
                if short_form >= 0.70
                else ShortFormPotentialBand.MODERATE
                if short_form >= 0.40
                else ShortFormPotentialBand.LOW
            ),
            explanation=(
                "The band combines current independent fandom coverage with "
                "character/relationship salience, a usable intro direction, and source actionability."
            ),
            signals=signals,
            supporting_claim_ids=[item.claim_id for item in signal_claims]
            or [opportunity.evidence[0].claim_id],
        )
    return quality, inference


def opportunity_passes_m11_quality_gate(
    intent: ResearchIntentV2,
    score: OpportunityQualityScoreV1,
) -> tuple[bool, str | None]:
    facet_ids = {
        item.facet_id
        for item in (
            intent.interpretation.facets if intent.interpretation is not None else []
        )
    }
    if facet_ids & {"female_skewing_fandom", "male_skewing_fandom", "queer_fandom"}:
        if score.audience_fit < 0.40:
            return False, "quality:audience-fit"
    if "short_form_edit_potential" in facet_ids and score.short_form_edit_potential < 0.35:
        return False, "quality:short-form-edit-potential"
    if score.footage_actionability < 0.35:
        return False, "quality:footage-actionability"
    return True, None


def score_editorial_concept(
    *,
    draft: EditorialConceptDraftV1,
    footage: FootageRequestV2,
    evidence_quality: float,
) -> EditorialConceptScoreV1:
    """Score only observable structure; provider self-ratings are one bounded input.

    The dated M1.1 fixtures exercise these components independently. This keeps
    a model from receiving a high score merely because it filled every field or
    called its own prose creative. Exact factual support is still enforced by
    the workflow before this function is reached.
    """

    subject_anchor = _content_tokens(
        " ".join(
            value
            for value in (draft.central_subject, draft.central_relationship or "")
            if value
        )
    )
    intro_copy = " ".join(
        " ".join(
            value
            for value in (
                item.moment_description,
                item.why_it_might_lead_into_montage,
            )
            if value
        )
        for item in footage.intro_leads
    )
    arc_copy = " ".join(draft.montage_arc)
    subject_detail = _bounded(len(subject_anchor) / 5.0)
    concept_specificity = sum(
        (
            subject_detail,
            _anchor_coverage(subject_anchor, draft.current_event),
            _anchor_coverage(subject_anchor, intro_copy),
            _anchor_coverage(subject_anchor, draft.ending_or_payoff),
        )
    ) / 4.0

    intro_verification = max(
        _verification_strength(item.verification_level)
        for item in footage.intro_leads
    )
    intro_hook = sum(
        (
            _anchor_coverage(subject_anchor, intro_copy),
            _bounded(len(_content_tokens(intro_copy)) / 8.0),
        )
    ) / 2.0
    intro = sum((intro_verification, intro_hook)) / 2.0

    arc_token_sets = [_content_tokens(value) for value in draft.montage_arc]
    unique_arc_tokens = set().union(*arc_token_sets)
    adjacent_changes = sum(
        left != right
        for left, right in zip(arc_token_sets, arc_token_sets[1:], strict=False)
    )
    arc = sum(
        (
            _bounded(len(draft.montage_arc) / 4.0),
            _bounded(len(unique_arc_tokens) / 12.0),
            _bounded(adjacent_changes / max(1, len(draft.montage_arc) - 1)),
            _anchor_coverage(subject_anchor, arc_copy),
        )
    ) / 4.0

    bridge = {
        LegacyConnectionType.SAME_CHARACTER: 1.0,
        LegacyConnectionType.SAME_CANONICAL_UNIVERSE: 0.92,
        LegacyConnectionType.EXPLICIT_CALLBACK: 1.0,
        LegacyConnectionType.THEMATIC_PARALLEL: 0.66,
        LegacyConnectionType.FAN_INTERPRETATION: 0.48,
        LegacyConnectionType.ACTOR_CONNECTION_ONLY: 0.12,
        LegacyConnectionType.NONE: 0.38,
        LegacyConnectionType.UNSUPPORTED_SPECULATION: 0.0,
    }[draft.legacy_connection_type]
    legacy = {
        LegacyConnectionType.SAME_CHARACTER: 1.0,
        LegacyConnectionType.SAME_CANONICAL_UNIVERSE: 0.92,
        LegacyConnectionType.EXPLICIT_CALLBACK: 1.0,
        LegacyConnectionType.THEMATIC_PARALLEL: 0.62,
        LegacyConnectionType.FAN_INTERPRETATION: 0.38,
        LegacyConnectionType.ACTOR_CONNECTION_ONLY: 0.08,
        LegacyConnectionType.NONE: 0.25,
        LegacyConnectionType.UNSUPPORTED_SPECULATION: 0.0,
    }[draft.legacy_connection_type]

    event_tokens = _content_tokens(draft.current_event)
    event_intro_overlap = _bounded(
        len(event_tokens & _content_tokens(intro_copy)) / 2.0
    )
    current_event = sum(
        (
            _bounded(len(event_tokens) / 4.0),
            event_intro_overlap,
            _verification_strength(draft.verification_status),
            _bounded(len(draft.evidence) / 2.0),
        )
    ) / 4.0
    fan_recognition = sum(
        (
            _bounded(len(draft.evidence) / 3.0),
            _anchor_coverage(subject_anchor, draft.why_fans_may_care),
            _bounded(len(_content_tokens(draft.why_fans_may_care)) / 8.0),
        )
    ) / 3.0
    payoff = sum(
        (
            _anchor_coverage(subject_anchor, draft.ending_or_payoff),
            _bounded(len(_content_tokens(draft.ending_or_payoff)) / 7.0),
            1.0 if _PAYOFF_LANGUAGE.search(draft.ending_or_payoff) else 0.0,
            _bounded(
                len(
                    _content_tokens(draft.ending_or_payoff)
                    & (_content_tokens(intro_copy) | unique_arc_tokens)
                )
                / 3.0
            ),
        )
    ) / 4.0

    all_sources = [
        *footage.required_sources,
        *footage.optional_sources,
        *footage.alternative_sources,
    ]
    supported_sources = sum(
        item.verification_level is not FootageVerificationLevel.UNKNOWN
        for item in all_sources
    )
    known_source_ratio = supported_sources / max(1, len(all_sources))
    compact_minimum = 1.0 if len(footage.required_sources) <= 2 else (
        0.75 if len(footage.required_sources) <= 4 else 0.45
    )
    feasibility = sum(
        (
            draft.footage_feasibility,
            known_source_ratio,
            compact_minimum,
        )
    ) / 3.0
    source_actionability = sum(
        (
            1.0 if footage.required_sources else 0.0,
            _bounded(len(footage.search_queries) / max(1, len(footage.required_sources))),
            sum(bool(_content_tokens(item.scene_or_moment)) for item in all_sources)
            / max(1, len(all_sources)),
            known_source_ratio,
        )
    ) / 4.0
    originality = sum(
        (
            bridge,
            _bounded(len(unique_arc_tokens) / 12.0),
            _bounded(len(set(draft.montage_arc)) / 4.0),
        )
    ) / 3.0

    unknown_source_ratio = sum(
        item.verification_level is FootageVerificationLevel.UNKNOWN
        for item in all_sources
    ) / max(1, len(all_sources))
    inferred_intro_ratio = sum(
        item.verification_level
        in {
            FootageVerificationLevel.LIKELY_INFERRED,
            FootageVerificationLevel.UNKNOWN,
        }
        for item in footage.intro_leads
    ) / max(1, len(footage.intro_leads))
    uncertainties = sum(
        (
            _bounded(len(draft.known_uncertainties) / 4.0),
            unknown_source_ratio,
            inferred_intro_ratio,
        )
    ) / 3.0
    values = {
        "concept_specificity": concept_specificity,
        "intro_strength": intro,
        "emotional_arc_strength": arc,
        "narrative_bridge_strength": bridge,
        "fan_recognition": fan_recognition,
        "current_event_relevance": current_event,
        "legacy_context_value": legacy,
        "payoff_strength": payoff,
        "footage_feasibility": feasibility,
        "source_actionability": source_actionability,
        "originality": originality,
        "evidence_quality": _bounded(evidence_quality),
        "uncertainty_penalty": uncertainties,
    }
    positives = [value for key, value in values.items() if key != "uncertainty_penalty"]
    total = max(0.0, min(1.0, sum(positives) / len(positives) - 0.25 * uncertainties))
    return EditorialConceptScoreV1(total=total, **values)
