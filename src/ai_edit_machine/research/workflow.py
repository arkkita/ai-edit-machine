"""Single trusted M1 workflow from bounded collectors to canonical recommendations."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable
from uuid import UUID, uuid4

from ..contracts import (
    EvidenceGate,
    EvidenceRole,
    EvidenceSourceType,
    ExcerptType,
    MediaKind,
    OpportunityFocus,
    SpoilerPolicy,
    VerificationState,
)
from ..m1_contracts import (
    CandidateDiagnosticV1,
    CandidateFailureClass,
    CandidateFunnelRejectionV1,
    CandidateFunnelV1,
    CandidateScoreStatus,
    CandidateScoreTraceV1,
    FandomStoryDossierDraftV1,
    FandomStoryDossierV1,
    EditorialConceptDraftV1,
    EditorialConceptV1,
    EvidenceClaimKind,
    EvidenceClaimRecordV2,
    EvidenceSourceRecordV2,
    FootageRequestDraftV2,
    FootageVerificationLevel,
    LegacyConnectionType,
    IntroMaterialLeadDraftV2,
    MediaIdentityV2,
    NaturalFootageRequestV2,
    OpportunityEvidenceSelectionV2,
    RequestedSourceDraftV2,
    ResearchIntentV2,
    ResearchResultStatus,
    ResearchResultV2,
    SourceAcquisitionKind,
    SourcePurpose,
    TrustedOpportunityEvidenceReferenceV2,
    TrendOpportunityDraftV2,
)
from ..providers.base import (
    CallAuthorization,
    CancellationToken,
    EvidenceCandidate,
    ProviderBatch,
    ProviderCancelledError,
    ProviderError,
    ProviderResearchContext,
    ProviderRunOutcome,
    ProviderUsage,
    ResearchProvider,
)
from ..providers.normalize import normalize_batches
from .evidence import EvidenceIndex, build_trusted_opportunity
from .footage import canonicalize_footage_request, render_natural_request
from .intent import violates_exclusions
from .policy import PolicyRule
from .ranking import (
    opportunity_passes_m11_quality_gate,
    score_editorial_concept,
    score_opportunity_quality,
)
from .source_ownership import (
    source_record_binds_media_title,
    source_record_binds_tvmaze_show,
)
from .synthesis import ResearchSynthesizer, SynthesisProviderResult


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
_QUEER_AUDIENCE_DIRECT = re.compile(
    r"\b(?:queer|lgbtq\+?|lesbian|gay|bisexual)\s+"
    r"(?:audience|fandom|fans?|viewers?|discussion)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ProviderPlan:
    provider: ResearchProvider
    authorization: CallAuthorization


@dataclass(frozen=True, slots=True)
class ResearchStageCounts:
    """Non-contract observability for the deterministic M1 pipeline."""

    parsed_results: int
    normalized_evidence: int
    evidence_surviving_gates: int
    ranked_opportunities: int
    opportunities_returned_to_ui: int
    parsed_intent: int = 1
    generated_search_variants: int = 0
    raw_release_candidates: int = 0
    candidates_after_freshness: int = 0
    candidates_after_hard_exclusions: int = 0
    candidates_after_audience_fit_screening: int = 0
    candidates_selected_for_social_research: int = 0
    candidates_with_usable_social_evidence: int = 0
    candidates_surviving_evidence_gates: int = 0
    candidates_surviving_deduplication: int = 0
    candidates_sent_to_final_ranker: int = 0
    final_opportunities_serialized: int = 0
    false_abstention_recovery_attempted: bool = False
    recovered_candidate_count: int = 0
    evidence_coverage_warning: str | None = None
    rejection_reason_counts: tuple[tuple[str, int], ...] = ()
    candidate_diagnostics: tuple[CandidateDiagnosticV1, ...] = ()


@dataclass(frozen=True, slots=True)
class ResearchWorkflowOutput:
    result: ResearchResultV2
    evidence_sources: tuple[EvidenceSourceRecordV2, ...]
    evidence_claims: tuple[EvidenceClaimRecordV2, ...]
    provider_batches: tuple[ProviderBatch, ...]
    synthesis: SynthesisProviderResult | None
    stage_counts: ResearchStageCounts


def _stage_counts(
    *,
    batches: list[ProviderBatch],
    normalized_claim_count: int,
    gate_claims: list[EvidenceClaimRecordV2] | None = None,
    deduplicated_opportunity_count: int = 0,
    ranker_input_count: int = 0,
    serialized_opportunity_count: int = 0,
    false_abstention_recovery_attempted: bool = False,
    recovered_candidate_count: int = 0,
    evidence_coverage_warning: str | None = None,
    rejection_reason_counts: dict[str, int] | None = None,
    candidate_diagnostics: list[CandidateDiagnosticV1] | None = None,
) -> ResearchStageCounts:
    """Combine value-free provider counters into the canonical 14-stage funnel."""

    tvmaze_funnel = next(
        (batch.candidate_funnel for batch in batches if batch.provider == "tvmaze"),
        None,
    )
    web_funnel = next(
        (
            batch.candidate_funnel
            for batch in batches
            if batch.provider in {"openai", "xai"}
            and batch.candidate_funnel.generated_search_variants > 0
        ),
        None,
    )
    gate_titles = {
        _normalized(title)
        for claim in (gate_claims or [])
        if (title := _claim_show_or_title(claim)) is not None
    }
    selected_for_social = (
        web_funnel.candidates_selected_for_social_research
        if web_funnel is not None
        else (
            tvmaze_funnel.candidates_selected_for_social_research
            if tvmaze_funnel is not None
            else 0
        )
    )
    serialized = max(0, serialized_opportunity_count)
    return ResearchStageCounts(
        parsed_results=sum(len(item.evidence) for item in batches),
        normalized_evidence=normalized_claim_count,
        # Preserve the pre-M1.1 diagnostic meaning for existing fixtures while
        # exposing the distinct-title gate count separately below.
        evidence_surviving_gates=len(gate_claims or []),
        ranked_opportunities=max(0, ranker_input_count),
        opportunities_returned_to_ui=serialized,
        parsed_intent=1,
        generated_search_variants=(
            web_funnel.generated_search_variants if web_funnel is not None else 0
        ),
        raw_release_candidates=(
            tvmaze_funnel.raw_release_candidates if tvmaze_funnel is not None else 0
        ),
        candidates_after_freshness=(
            tvmaze_funnel.candidates_after_freshness
            if tvmaze_funnel is not None
            else 0
        ),
        candidates_after_hard_exclusions=(
            tvmaze_funnel.candidates_after_hard_exclusions
            if tvmaze_funnel is not None
            else 0
        ),
        candidates_after_audience_fit_screening=(
            tvmaze_funnel.candidates_after_audience_fit_screening
            if tvmaze_funnel is not None
            else 0
        ),
        candidates_selected_for_social_research=selected_for_social,
        candidates_with_usable_social_evidence=(
            web_funnel.candidates_with_usable_social_evidence
            if web_funnel is not None
            else 0
        ),
        candidates_surviving_evidence_gates=len(gate_titles),
        candidates_surviving_deduplication=max(0, deduplicated_opportunity_count),
        candidates_sent_to_final_ranker=max(0, ranker_input_count),
        final_opportunities_serialized=serialized,
        false_abstention_recovery_attempted=false_abstention_recovery_attempted,
        recovered_candidate_count=max(0, recovered_candidate_count),
        evidence_coverage_warning=evidence_coverage_warning,
        rejection_reason_counts=tuple(
            sorted(
                (code, count)
                for code, count in (rejection_reason_counts or {}).items()
                if code and count > 0
            )
        ),
        candidate_diagnostics=tuple(candidate_diagnostics or ()),
    )


def _attach_candidate_funnel(
    result: ResearchResultV2,
    counts: ResearchStageCounts,
) -> ResearchResultV2:
    removed_hard = max(
        0,
        counts.candidates_after_freshness
        - counts.candidates_after_hard_exclusions,
    )
    lacking_fandom = max(
        0,
        counts.candidates_selected_for_social_research
        - counts.candidates_with_usable_social_evidence,
    )
    lacking_gate = max(
        0,
        counts.candidates_with_usable_social_evidence
        - counts.candidates_surviving_evidence_gates,
    )
    lacking_actionability = max(
        0,
        counts.candidates_surviving_evidence_gates
        - counts.candidates_sent_to_final_ranker,
    )
    shortage = counts.final_opportunities_serialized < 3
    explanation = None
    suggestions: list[str] = []
    if shortage:
        explanation = (
            f"The search found {counts.raw_release_candidates} raw release record(s); "
            f"{removed_hard} were removed by hard constraints, {lacking_fandom} of the "
            "social-research shortlist lacked usable current fandom evidence, "
            f"{lacking_gate} had usable evidence but did not jointly meet the "
            "source-diversity, current-evidence, and requested-audience floor, and "
            f"{lacking_actionability} evidence-gated candidate(s) did not reach the "
            "final ranker with an actionable concept and footage request."
        )
        suggestions = [
            "Broaden the freshness window.",
            "Loosen one soft audience or genre preference.",
            "Include upcoming official trailers.",
            "Include films as well as television.",
            "Include clearly labeled, less-proven opportunities.",
            "Try a narrower character, relationship, or genre interpretation.",
        ]
    rejection_counts = dict(counts.rejection_reason_counts)
    if lacking_gate:
        rejection_counts["evidence_or_audience_gate"] = (
            rejection_counts.get("evidence_or_audience_gate", 0) + lacking_gate
        )
    funnel = CandidateFunnelV1(
        parsed_intent=counts.parsed_intent,
        generated_search_variants=counts.generated_search_variants,
        raw_release_candidates=counts.raw_release_candidates,
        candidates_after_freshness=counts.candidates_after_freshness,
        candidates_after_hard_exclusions=counts.candidates_after_hard_exclusions,
        candidates_after_audience_fit_screening=(
            counts.candidates_after_audience_fit_screening
        ),
        candidates_selected_for_social_research=(
            counts.candidates_selected_for_social_research
        ),
        candidates_with_usable_social_evidence=(
            counts.candidates_with_usable_social_evidence
        ),
        candidates_surviving_evidence_gates=(
            counts.candidates_surviving_evidence_gates
        ),
        candidates_surviving_deduplication=(
            counts.candidates_surviving_deduplication
        ),
        candidates_sent_to_final_ranker=counts.candidates_sent_to_final_ranker,
        final_opportunities_serialized=counts.final_opportunities_serialized,
        removed_by_hard_constraints=removed_hard,
        lacking_current_fandom_evidence=lacking_fandom,
        lacking_actionable_footage_information=lacking_actionability,
        false_abstention_recovery_attempted=(
            counts.false_abstention_recovery_attempted
        ),
        recovered_candidate_count=counts.recovered_candidate_count,
        evidence_coverage_warning=counts.evidence_coverage_warning,
        rejection_reasons=[
            CandidateFunnelRejectionV1(reason_code=code, count=count)
            for code, count in sorted(rejection_counts.items())
        ],
        candidate_diagnostics=list(counts.candidate_diagnostics),
        shortage_explanation=explanation,
        suggestions=suggestions,
    )
    return result.model_copy(update={"candidate_funnel": funnel})


class ResearchWorkflow:
    """No persistence or secret lookup; Rust supplies every capability explicitly."""

    def __init__(
        self,
        *,
        providers: list[ProviderPlan],
        synthesizer: ResearchSynthesizer,
        synthesis_authorization: CallAuthorization,
        official_hosts: set[str],
        reusable_evidence_sources: tuple[EvidenceSourceRecordV2, ...] = (),
        reusable_evidence_claims: tuple[EvidenceClaimRecordV2, ...] = (),
        policy_rules: dict[str, PolicyRule] | None = None,
        uuid_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._providers = list(providers)
        self._synthesizer = synthesizer
        self._synthesis_authorization = synthesis_authorization
        self._official_hosts = set(official_hosts)
        self._reusable_evidence_sources = tuple(reusable_evidence_sources)
        self._reusable_evidence_claims = tuple(reusable_evidence_claims)
        self._policy_rules = dict(policy_rules) if policy_rules is not None else None
        self._uuid_factory = uuid_factory

    def run(
        self,
        intent: ResearchIntentV2,
        *,
        generated_at: datetime,
        cancellation: CancellationToken,
        run_id: UUID | None = None,
    ) -> ResearchWorkflowOutput:
        if generated_at.tzinfo is None or generated_at.utcoffset() is None:
            raise ValueError("workflow generated_at must be timezone aware")
        authoritative_run_id = run_id or self._uuid_factory()
        if (
            intent.interpretation is not None
            and intent.interpretation.clarification_needed
        ):
            result = _no_opportunity(
                intent,
                generated_at=generated_at,
                run_id=authoritative_run_id,
                message=intent.interpretation.clarification_reason
                or "This request needs clarification before research can begin.",
                warnings=[
                    "No provider was contacted because explicit request constraints conflict."
                ],
            )
            stage_counts = _stage_counts(
                batches=[],
                normalized_claim_count=0,
                serialized_opportunity_count=0,
            )
            result = _attach_candidate_funnel(result, stage_counts)
            return ResearchWorkflowOutput(
                result=result,
                evidence_sources=(),
                evidence_claims=(),
                provider_batches=(),
                synthesis=None,
                stage_counts=stage_counts,
            )
        batches: list[ProviderBatch] = []
        warnings: list[str] = []
        broad_recovery = bool(
            intent.interpretation is not None
            and intent.interpretation.broad_query
        )
        recovery_attempted = False
        recovered_candidate_count = 0
        evidence_coverage_warning: str | None = None
        prior_evidence = []
        trusted_official_hosts: set[str] = set()
        for plan in self._providers:
            cancellation.raise_if_cancelled()
            context_evidence = list(prior_evidence)
            if plan.provider.name == "openai" and len(context_evidence) < 200:
                context_evidence.extend(
                    _provider_reusable_discussion_context(
                        self._reusable_evidence_sources,
                        self._reusable_evidence_claims,
                        current_evidence=tuple(prior_evidence),
                        generated_at=generated_at,
                        max_items=200 - len(context_evidence),
                    )
                )
            try:
                batch = plan.provider.collect(
                    intent,
                    authorization=plan.authorization,
                    cancellation=cancellation,
                    context=ProviderResearchContext(
                        prior_evidence=tuple(context_evidence),
                        trusted_official_hosts=tuple(sorted(trusted_official_hosts)),
                    ),
                )
            except ProviderCancelledError:
                raise
            except ProviderError as error:
                batch = ProviderBatch(
                    provider=plan.provider.name,
                    evidence=(),
                    outcome=ProviderRunOutcome.ERROR,
                    error=str(error)[:1_000],
                    usage=ProviderUsage(
                        configured_model=plan.authorization.configured_model,
                        request_count=None,
                    ),
                )
            if batch.provider != plan.provider.name or any(
                item.provider != batch.provider for item in batch.evidence
            ):
                raise ValueError("provider returned evidence under an unexpected identity")
            batches.append(batch)
            if batch.outcome is ProviderRunOutcome.SUCCESS:
                prior_evidence.extend(batch.evidence)
                if batch.provider == "tvmaze":
                    trusted_official_hosts.update(batch.trusted_official_hosts)
            warnings.extend(batch.warnings)
            warnings.extend(f"Attribution: {item}" for item in batch.attributions)
            if batch.outcome is not ProviderRunOutcome.SUCCESS:
                warnings.append(
                    f"{batch.provider} research ended as {batch.outcome.value.lower()}."
                )

        sources, claims = normalize_batches(
            batches,
            retrieved_at=generated_at,
            official_hosts=self._official_hosts,
            policy_rules=self._policy_rules,
            uuid_factory=self._uuid_factory,
        )
        sources, claims, reused_count = _merge_reusable_evidence(
            sources,
            claims,
            self._reusable_evidence_sources,
            self._reusable_evidence_claims,
            generated_at=generated_at,
        )
        if reused_count:
            warnings.append(
                f"Reused {reused_count} still-current, policy-valid discussion source(s) from the local evidence cache."
            )
        sources, claims = _apply_exclusions(intent, sources, claims)
        strict_support = _could_support_recommendation(
            sources, claims, generated_at, intent
        )
        recovery_support = strict_support
        if broad_recovery:
            recovery_attempted = True
            recovery_support = _could_support_recommendation(
                sources,
                claims,
                generated_at,
                intent,
                relaxed_soft_preferences=True,
            )
        if not recovery_support:
            if recovery_attempted:
                evidence_coverage_warning = (
                    "The bounded false-abstention recovery pass used alternate semantic "
                    "title-slate retrieval, reviewed lawful publisher sources, and a one-cue "
                    "soft-audience floor, but no candidate retained the unchanged factual "
                    "current-event and fandom-evidence requirements."
                )
                warnings.append(evidence_coverage_warning)
            result = _no_opportunity(
                intent,
                generated_at=generated_at,
                run_id=authoritative_run_id,
                message="No strong opportunity found under these constraints.",
                warnings=warnings,
            )
            stage_counts = _stage_counts(
                batches=batches,
                normalized_claim_count=len(claims),
                false_abstention_recovery_attempted=recovery_attempted,
                recovered_candidate_count=0,
                evidence_coverage_warning=evidence_coverage_warning,
                candidate_diagnostics=_build_candidate_diagnostics(
                    batches=batches,
                    sources=sources,
                    claims=claims,
                    intent=intent,
                    now=generated_at,
                    recovery_attempted=recovery_attempted,
                ),
            )
            result = _attach_candidate_funnel(result, stage_counts)
            return ResearchWorkflowOutput(
                result=result,
                evidence_sources=tuple(sources),
                evidence_claims=tuple(claims),
                provider_batches=tuple(batches),
                synthesis=None,
                stage_counts=stage_counts,
            )

        strict_synthesis_sources, strict_synthesis_claims = _select_synthesis_evidence(
            intent,
            sources,
            claims,
            now=generated_at,
        )
        synthesis_sources = strict_synthesis_sources
        synthesis_claims = strict_synthesis_claims
        if broad_recovery:
            recovery_sources, recovery_claims = _select_synthesis_evidence(
                intent,
                sources,
                claims,
                now=generated_at,
                relaxed_soft_preferences=True,
            )
            strict_titles = {
                _normalized(title)
                for claim in strict_synthesis_claims
                if (title := _claim_show_or_title(claim)) is not None
                and claim.claim_kind
                in {
                    EvidenceClaimKind.WHY_NOW,
                    EvidenceClaimKind.OFFICIAL_CLIP,
                    EvidenceClaimKind.EPISODE_IDENTITY,
                }
            }
            recovery_titles = {
                _normalized(title)
                for claim in recovery_claims
                if (title := _claim_show_or_title(claim)) is not None
                and claim.claim_kind
                in {
                    EvidenceClaimKind.WHY_NOW,
                    EvidenceClaimKind.OFFICIAL_CLIP,
                    EvidenceClaimKind.EPISODE_IDENTITY,
                }
            }
            recovered_candidate_count = len(recovery_titles - strict_titles)
            synthesis_sources, synthesis_claims = recovery_sources, recovery_claims
            warnings.append(
                "Completed one bounded false-abstention recovery pass: alternate semantic "
                "title-slate queries and reviewed lawful publisher sources were evaluated, "
                "only soft audience affinity was relaxed, and factual verification gates "
                f"were unchanged; {recovered_candidate_count} additional candidate(s) entered "
                "the synthesis allow-list."
            )
        if not synthesis_sources or not synthesis_claims:
            warnings.append(
                "The trusted synthesis allow-list was empty after title, media-kind, "
                "freshness, and publisher-independence checks; paid synthesis was skipped."
            )
            if recovery_attempted:
                evidence_coverage_warning = (
                    "The bounded recovery pass still produced no synthesis allow-list; the "
                    "available sources did not jointly establish a current factual hook, "
                    "credible fandom interest, and requested-audience relevance."
                )
                warnings.append(evidence_coverage_warning)
            result = _no_opportunity(
                intent,
                generated_at=generated_at,
                run_id=authoritative_run_id,
                message="No strong opportunity found under these constraints.",
                warnings=warnings,
            )
            stage_counts = _stage_counts(
                batches=batches,
                normalized_claim_count=len(claims),
                false_abstention_recovery_attempted=recovery_attempted,
                recovered_candidate_count=recovered_candidate_count,
                evidence_coverage_warning=evidence_coverage_warning,
                candidate_diagnostics=_build_candidate_diagnostics(
                    batches=batches,
                    sources=sources,
                    claims=claims,
                    intent=intent,
                    now=generated_at,
                    recovery_attempted=recovery_attempted,
                ),
            )
            result = _attach_candidate_funnel(result, stage_counts)
            return ResearchWorkflowOutput(
                result=result,
                evidence_sources=tuple(sources),
                evidence_claims=tuple(claims),
                provider_batches=tuple(batches),
                synthesis=None,
                stage_counts=stage_counts,
            )
        synthesis = self._synthesizer.synthesize(
            intent,
            evidence_sources=synthesis_sources,
            evidence_claims=synthesis_claims,
            authorization=self._synthesis_authorization,
            cancellation=cancellation,
        )
        if synthesis.outcome is not ProviderRunOutcome.SUCCESS:
            warnings.append(
                f"Recommendation synthesis ended as {synthesis.outcome.value.lower()}."
            )

        evidence_index = EvidenceIndex.build(sources, claims)
        allowed_claim_ids = {UUID(str(item.claim_id)) for item in synthesis_claims}
        canonical_pairs = []
        dossiers_by_opportunity: dict[UUID, FandomStoryDossierV1] = {}
        concepts_by_opportunity: dict[UUID, list[EditorialConceptV1]] = {}
        rejected = 0
        rejection_codes: dict[str, int] = {}
        recommendations = (
            synthesis.draft.recommendations
            if synthesis.outcome is ProviderRunOutcome.SUCCESS
            and synthesis.draft is not None
            else []
        )
        synthesis_source_by_id = {
            UUID(str(item.source_id)): item for item in synthesis_sources
        }
        for recommendation in recommendations:
            concept_drafts = [
                item.model_copy(
                    update={
                        "footage_request": _attach_official_video_sources(
                            item.footage_request,
                            show_or_title=(
                                recommendation.opportunity.media_identity.show_or_title
                            ),
                            claims=synthesis_claims,
                            source_by_id=synthesis_source_by_id,
                        )
                    }
                )
                for item in recommendation.editorial_concepts
            ]
            recommended_concept_key = recommendation.recommended_concept_key
            selected_drafts = [
                item
                for item in concept_drafts
                if item.concept_key == recommended_concept_key
            ]
            if len(selected_drafts) != 1:
                rejected += 1
                rejection_codes["concept:missing-selected"] = (
                    rejection_codes.get("concept:missing-selected", 0) + 1
                )
                continue
            footage_draft = selected_drafts[0].footage_request
            try:
                for concept_draft in concept_drafts:
                    _validate_pair_against_intent(
                        intent,
                        recommendation.opportunity,
                        concept_draft.footage_request,
                        evidence_index=evidence_index,
                        allow_cross_title_sources=True,
                    )
            except (ValueError, KeyError) as error:
                rejected += 1
                code = _synthesis_rejection_code("intent", error)
                rejection_codes[code] = rejection_codes.get(code, 0) + 1
                continue
            opportunity_id = self._uuid_factory()
            dossier_id = self._uuid_factory()
            concept_ids = {
                item.concept_key: self._uuid_factory() for item in concept_drafts
            }
            selected_concept_id = concept_ids[recommended_concept_key]
            request_id = self._uuid_factory()
            try:
                dossier = _canonicalize_fandom_story_dossier(
                    recommendation.fandom_story_dossier,
                    opportunity=recommendation.opportunity,
                    dossier_id=dossier_id,
                    opportunity_id=opportunity_id,
                    evidence_index=evidence_index,
                    allowed_claim_ids=allowed_claim_ids,
                )
                footage = canonicalize_footage_request(
                    draft=footage_draft,
                    footage_request_id=request_id,
                    opportunity_id=opportunity_id,
                    concept_id=selected_concept_id,
                    evidence_index=evidence_index,
                    allowed_claim_ids=allowed_claim_ids,
                    uuid_factory=self._uuid_factory,
                )
            except (ValueError, KeyError) as error:
                rejected += 1
                code = _synthesis_rejection_code(
                    "dossier" if "dossier" in str(error).casefold() else "footage",
                    error,
                )
                rejection_codes[code] = rejection_codes.get(code, 0) + 1
                continue
            try:
                opportunity = build_trusted_opportunity(
                    draft=recommendation.opportunity,
                    opportunity_id=opportunity_id,
                    footage_request_id=request_id,
                    evidence_index=evidence_index,
                    allowed_claim_ids=allowed_claim_ids,
                    now=generated_at,
                    freshness_days=intent.freshness_days,
                    footage_actionability=_footage_actionability(footage_draft),
                )
                quality_score, short_form_inference = score_opportunity_quality(
                    intent=intent,
                    opportunity=opportunity,
                    footage=footage,
                    sources=sources,
                    claims=claims,
                )
                concepts, recommended_concept_id = _canonicalize_editorial_concepts(
                    concept_drafts,
                    recommended_concept_key=recommended_concept_key,
                    opportunity_id=opportunity_id,
                    selected_footage=footage,
                    evidence_index=evidence_index,
                    allowed_claim_ids=allowed_claim_ids,
                    evidence_quality=quality_score.evidence_quality,
                    dossier=dossier,
                    concept_ids=concept_ids,
                    uuid_factory=self._uuid_factory,
                )
                if not concepts:
                    raise ValueError("concept:missing-specific-editorial-angle")
                passes_quality, quality_rejection = opportunity_passes_m11_quality_gate(
                    intent,
                    quality_score,
                )
                if not passes_quality:
                    raise ValueError(quality_rejection or "quality:unknown")
                opportunity = opportunity.model_copy(
                    update={
                        "dossier_id": dossier_id,
                        "quality_score": quality_score,
                        "short_form_edit_potential": short_form_inference,
                        "recommended_concept_id": recommended_concept_id,
                    }
                )
                canonical_pairs.append((opportunity, footage))
                dossiers_by_opportunity[opportunity_id] = dossier
                concepts_by_opportunity[opportunity_id] = concepts
            except (ValueError, KeyError) as error:
                rejected += 1
                code = _synthesis_rejection_code(
                    "concept" if str(error).startswith(("concept:", "quality:")) else "opportunity",
                    error,
                )
                rejection_codes[code] = rejection_codes.get(code, 0) + 1
        canonical_pairs.sort(key=_opportunity_sort_key)
        canonical_pairs = canonical_pairs[: intent.max_results]
        if rejected:
            bounded_codes = ", ".join(
                f"{code}={count}" for code, count in sorted(rejection_codes.items())
            )
            warnings.append(
                f"{rejected} synthesized recommendation(s) failed trusted evidence validation"
                + (f" ({bounded_codes})." if bounded_codes else ".")
            )
        # M1.1b has no generic scene-pack fallback. A title without a supported
        # dossier and specific concept remains an honest abstention.
        canonical_pairs.sort(key=_opportunity_sort_key)
        canonical_pairs = canonical_pairs[: intent.max_results]
        retained_opportunity_ids = {
            UUID(str(pair[0].opportunity_id)) for pair in canonical_pairs
        }
        concepts_by_opportunity = {
            key: value
            for key, value in concepts_by_opportunity.items()
            if key in retained_opportunity_ids
        }
        dossiers_by_opportunity = {
            key: value
            for key, value in dossiers_by_opportunity.items()
            if key in retained_opportunity_ids
        }
        final_dossiers = [
            dossiers_by_opportunity[UUID(str(opportunity.opportunity_id))]
            for opportunity, _ in canonical_pairs
        ]
        final_concepts = [
            concept
            for opportunity, _ in canonical_pairs
            for concept in concepts_by_opportunity.get(
                UUID(str(opportunity.opportunity_id)),
                [],
            )
        ]
        if not canonical_pairs:
            reason = (
                synthesis.draft.no_strong_opportunity_reason
                if synthesis.draft is not None
                else None
            )
            if synthesis_claims:
                reason = (
                    "This title appears current, but I could not yet find a specific "
                    "enough story or fandom angle to recommend a strong edit concept."
                )
            if recovery_attempted:
                evidence_coverage_warning = (
                    "The bounded recovery pass found evidence worth synthesis but no candidate "
                    "could support a validated FandomStoryDossier, coherent editorial concept, "
                    "and concept-specific footage request. Factual verification was not relaxed."
                )
                warnings.append(evidence_coverage_warning)
            result = _no_opportunity(
                intent,
                generated_at=generated_at,
                run_id=authoritative_run_id,
                message=reason or "No strong opportunity found under these constraints.",
                warnings=warnings,
            )
        else:
            has_low_confidence = any(
                pair[0].evidence_gate is EvidenceGate.LOW_CONFIDENCE
                for pair in canonical_pairs
            )
            if intent.spoiler_policy is SpoilerPolicy.AVOID:
                warnings.append(
                    "Spoiler-free mode limited footage requests to official promotional "
                    "material; exact episode-scene specificity may be unavailable."
                )
            result = ResearchResultV2(
                run_id=authoritative_run_id,
                status=ResearchResultStatus.OPPORTUNITIES,
                intent=intent,
                opportunities=[pair[0] for pair in canonical_pairs],
                fandom_story_dossiers=final_dossiers,
                footage_requests=[pair[1] for pair in canonical_pairs],
                editorial_concepts=final_concepts,
                message=(
                    "Some opportunities are explicitly low confidence because they did not meet "
                    "the normal official-primary-plus-two-signals gate; inspect each card's "
                    "caveat, cited evidence, and supplied local footage before proceeding."
                    if has_low_confidence
                    else "These opportunities passed the current evidence gate; inspect supplied "
                    "local footage before making final creative decisions."
                ),
                applied_exclusions=intent.exclusions,
                warnings=_dedupe(warnings),
                generated_at=generated_at,
            )
        combined_rejection_counts = dict(rejection_codes)
        deduplicated_count = len(
            {
                _normalized(pair[0].media_identity.show_or_title)
                for pair in canonical_pairs
            }
        )
        stage_counts = _stage_counts(
            batches=batches,
            normalized_claim_count=len(claims),
            gate_claims=synthesis_claims,
            deduplicated_opportunity_count=deduplicated_count,
            ranker_input_count=len(canonical_pairs),
            serialized_opportunity_count=len(result.opportunities),
            false_abstention_recovery_attempted=recovery_attempted,
            recovered_candidate_count=recovered_candidate_count,
            evidence_coverage_warning=evidence_coverage_warning,
            rejection_reason_counts=combined_rejection_counts,
            candidate_diagnostics=_build_candidate_diagnostics(
                batches=batches,
                sources=sources,
                claims=claims,
                intent=intent,
                now=generated_at,
                recovery_attempted=recovery_attempted,
                synthesis_titles={
                    title
                    for claim in synthesis_claims
                    if (title := _claim_show_or_title(claim)) is not None
                },
                final_opportunities=list(result.opportunities),
            ),
        )
        result = _attach_candidate_funnel(result, stage_counts)
        return ResearchWorkflowOutput(
            result=result,
            evidence_sources=tuple(sources),
            evidence_claims=tuple(claims),
            provider_batches=tuple(batches),
            synthesis=synthesis,
            stage_counts=stage_counts,
        )


def _provider_reusable_discussion_context(
    reusable_sources: tuple[EvidenceSourceRecordV2, ...],
    reusable_claims: tuple[EvidenceClaimRecordV2, ...],
    *,
    current_evidence: tuple[EvidenceCandidate, ...],
    generated_at: datetime,
    max_items: int,
) -> tuple[EvidenceCandidate, ...]:
    """Expose only current, title-bound cache rows for local scene recovery.

    The receiving verifier does not send these records to the model. It may use
    their source-owned URL/title only to prioritize one bounded public-page
    refresh. A current TVmaze identity from this run is mandatory, preserving
    the cross-intent reuse barrier.
    """

    if max_items <= 0 or not reusable_sources or not reusable_claims:
        return ()
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("reusable provider context time must be timezone aware")
    eligible_show_titles = tuple(
        dict.fromkeys(
            item.episode_locator.show_or_title
            for item in current_evidence
            if item.provider == "tvmaze"
            and item.claim_kind is EvidenceClaimKind.EPISODE_IDENTITY
            and item.verification is VerificationState.SECONDARY_CORROBORATED
            and item.episode_locator is not None
            and item.event_or_release_at is not None
            and item.event_or_release_at <= generated_at + timedelta(minutes=5)
        )
    )
    if not eligible_show_titles:
        return ()
    source_by_id = {source.source_id: source for source in reusable_sources}
    selected: list[EvidenceCandidate] = []
    for claim in reusable_claims:
        source = source_by_id.get(claim.source_id)
        source_at = (
            source.source_created_at or source.page_published_at
            if source is not None
            else None
        )
        deadlines = (
            source.refresh_due_at if source is not None else None,
            source.expires_at if source is not None else None,
            source.purge_due_at if source is not None else None,
        )
        if (
            source is None
            or source.provider != "openai"
            or source.source_type is not EvidenceSourceType.ARTICLE
            or source.policy_class != "openai-web-evidence-v1"
            or claim.claim_kind is not EvidenceClaimKind.VIEWER_DISCUSSION
            or claim.verification is not VerificationState.SECONDARY_CORROBORATED
            or not claim.supports_why_now
            or source_at is None
            or source.retrieved_at > generated_at + timedelta(minutes=5)
            or any(value is None or value <= generated_at for value in deadlines)
            or (
                source.deletion_required_at is not None
                and source.deletion_required_at <= generated_at
            )
            or not any(
                source_record_binds_tvmaze_show(
                    provider=source.provider,
                    provider_record_id=source.provider_record_id,
                    canonical_url=str(source.canonical_url),
                    show_or_title=show_or_title,
                )
                for show_or_title in eligible_show_titles
            )
        ):
            continue
        selected.append(
            EvidenceCandidate(
                provider=source.provider,
                provider_record_id=source.provider_record_id,
                source_type=source.source_type,
                canonical_url=str(source.canonical_url),
                title=source.title,
                author_or_channel=source.author_or_channel,
                excerpt_type=ExcerptType.PARAPHRASE,
                excerpt=claim.text,
                verification=claim.verification,
                claim_kind=claim.claim_kind,
                supports_why_now=claim.supports_why_now,
                policy_class=source.policy_class,
                source_created_at=source.source_created_at,
                source_updated_at=source.source_updated_at,
                page_published_at=source.page_published_at,
                query=source.query,
                window_start=source.window_start,
                window_end=source.window_end,
                confidence=claim.confidence,
                citation_verified=True,
                adapter_source_title=source.title,
                adapter_source_published_at=source_at,
                content_binding_verified=True,
            )
        )
        # Cache rows are recovery hints, not evidence.  Keep the public-page
        # revalidation allowance bounded so stale cache entries cannot crowd
        # current hosted-search sources out of the verifier's page budget.
        if len(selected) >= min(max_items, 8):
            break
    return tuple(selected)


def _merge_reusable_evidence(
    fresh_sources: list[EvidenceSourceRecordV2],
    fresh_claims: list[EvidenceClaimRecordV2],
    reusable_sources: tuple[EvidenceSourceRecordV2, ...],
    reusable_claims: tuple[EvidenceClaimRecordV2, ...],
    *,
    generated_at: datetime,
) -> tuple[list[EvidenceSourceRecordV2], list[EvidenceClaimRecordV2], int]:
    """Never promote a durable discussion row without live page validation.

    Rust still selects bounded, policy-current rows and the verifier receives
    them as public-page fetch hints.  Only evidence freshly returned by that
    verifier may enter this run.  This closes the gap where a previously
    accepted but later-disproven page could satisfy the owner-mix gate merely
    because its local TTL had not expired.
    """

    if not reusable_sources and not reusable_claims:
        return fresh_sources, fresh_claims, 0
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("reusable evidence evaluation time must be timezone aware")
    if len(reusable_sources) > 64 or len(reusable_claims) > 128:
        raise ValueError("reusable evidence exceeded its bounded contract")

    return fresh_sources, fresh_claims, 0


def _no_opportunity(
    intent: ResearchIntentV2,
    *,
    generated_at: datetime,
    run_id: UUID,
    message: str,
    warnings: list[str],
) -> ResearchResultV2:
    return ResearchResultV2(
        run_id=run_id,
        status=ResearchResultStatus.NO_STRONG_OPPORTUNITY,
        intent=intent,
        opportunities=[],
        footage_requests=[],
        message=_sanitize_result_diagnostic(message, max_length=2_000),
        applied_exclusions=intent.exclusions,
        warnings=_dedupe(warnings),
        generated_at=generated_at,
    )


def _apply_exclusions(
    intent: ResearchIntentV2,
    sources: list[EvidenceSourceRecordV2],
    claims: list[EvidenceClaimRecordV2],
) -> tuple[list[EvidenceSourceRecordV2], list[EvidenceClaimRecordV2]]:
    allowed_source_ids = {
        UUID(str(source.source_id))
        for source in sources
        if not violates_exclusions(
            " ".join(filter(None, [source.title, source.author_or_channel or ""])), intent
        )
    }
    filtered_claims = [
        claim
        for claim in claims
        if UUID(str(claim.source_id)) in allowed_source_ids
        and not violates_exclusions(_claim_search_text(claim), intent)
    ]
    retained_ids = {UUID(str(claim.source_id)) for claim in filtered_claims}
    return (
        [source for source in sources if UUID(str(source.source_id)) in retained_ids],
        filtered_claims,
    )


def _claim_search_text(claim: EvidenceClaimRecordV2) -> str:
    values = [claim.text]
    for fact in (
        claim.episode_locator,
        claim.quote_fact,
        claim.why_now_event,
        claim.scene_fact,
        claim.cast_fact,
    ):
        if fact is not None:
            values.append(json.dumps(fact.model_dump(mode="json"), ensure_ascii=False))
    return " ".join(values)


def _requested_audience_has_minimum_support(
    intent: ResearchIntentV2,
    show_or_title: str,
    claims: list[EvidenceClaimRecordV2],
    source_by_id: dict[UUID, EvidenceSourceRecordV2],
    *,
    relaxed_soft_preferences: bool = False,
) -> bool:
    """Apply a minimum evidence floor to explicit audience requests.

    Audience facets remain soft ranking preferences, not genre stereotypes. A
    direct audience statement is enough; otherwise two distinct affinity cues
    are required. A lone romance/action label therefore cannot establish a
    gender-skewed audience, and model-authored opportunity prose is ignored.
    """

    facet_ids = {
        item.facet_id
        for item in (
            intent.interpretation.facets
            if intent.interpretation is not None
            else []
        )
    }
    requested = facet_ids & {
        "female_skewing_fandom",
        "male_skewing_fandom",
        "queer_fandom",
    }
    if not requested:
        return True
    normalized_title = _normalized(show_or_title)
    relevant_text: list[str] = []
    for claim in claims:
        source = source_by_id.get(UUID(str(claim.source_id)))
        if source is None:
            continue
        claim_title = _normalized(_claim_show_or_title(claim) or "")
        if claim_title != normalized_title and not _source_matches_show(
            source, show_or_title
        ):
            continue
        relevant_text.append(f"{source.title} {claim.text}")
    corpus = " ".join(relevant_text)
    if "female_skewing_fandom" in requested:
        if _FEMALE_AUDIENCE_DIRECT.search(corpus):
            return True
        cues = {
            _normalized(match.group(0))
            for match in _FEMALE_AFFINITY_CUE.finditer(corpus)
        }
        return len(cues) >= (1 if relaxed_soft_preferences else 2)
    if "male_skewing_fandom" in requested:
        if _MALE_AUDIENCE_DIRECT.search(corpus):
            return True
        cues = {
            _normalized(match.group(0))
            for match in _MALE_AFFINITY_CUE.finditer(corpus)
        }
        return len(cues) >= (1 if relaxed_soft_preferences else 2)
    return bool(_QUEER_AUDIENCE_DIRECT.search(corpus))


def _could_support_recommendation(
    sources: list[EvidenceSourceRecordV2],
    claims: list[EvidenceClaimRecordV2],
    now: datetime,
    intent: ResearchIntentV2,
    *,
    relaxed_soft_preferences: bool = False,
) -> bool:
    cutoff = now - timedelta(days=intent.freshness_days)
    source_by_id = {UUID(str(item.source_id)): item for item in sources}
    primary = [
        (
            claim,
            source_by_id[UUID(str(claim.source_id))],
        )
        for claim in claims
        if claim.verification is VerificationState.PRIMARY_VERIFIED
        and claim.claim_kind in {EvidenceClaimKind.WHY_NOW, EvidenceClaimKind.OFFICIAL_CLIP}
        and claim.supports_why_now
        and claim.event_or_release_at is not None
        and cutoff <= claim.event_or_release_at <= now
    ]
    signals = [
        (claim, source_by_id[UUID(str(claim.source_id))])
        for claim in claims
        if claim.verification is VerificationState.SECONDARY_CORROBORATED
        and claim.claim_kind is EvidenceClaimKind.VIEWER_DISCUSSION
        and claim.supports_why_now
        and (
            source_by_id[UUID(str(claim.source_id))].source_created_at
            or source_by_id[UUID(str(claim.source_id))].page_published_at
        ) is not None
        and cutoff
        <= (
            source_by_id[UUID(str(claim.source_id))].source_created_at
            or source_by_id[UUID(str(claim.source_id))].page_published_at
        )
        <= now
    ]

    for primary_claim, primary_source in primary:
        identity = primary_claim.why_now_event.media_identity if primary_claim.why_now_event else None
        if identity is None or identity.media_kind not in intent.media_kinds:
            continue
        relevant_signals = [
            (claim, source)
            for claim, source in signals
            if _source_matches_show(source, identity.show_or_title)
        ]
        if not _requested_audience_has_minimum_support(
            intent,
            identity.show_or_title,
            [primary_claim, *(claim for claim, _ in relevant_signals)],
            source_by_id,
            relaxed_soft_preferences=relaxed_soft_preferences,
        ):
            continue
        relevant_signal_groups = {
            source.independence_group for _, source in relevant_signals
        }
        groups = {primary_source.independence_group, *relevant_signal_groups}
        # The normal gate remains two independent discussion sources. One
        # genuinely current and media-bound signal may still justify paying for
        # synthesis of an explicitly LOW_CONFIDENCE, fully evidence-bound card.
        # No primary, no current signal, or circular sourcing remains a no-op.
        if relevant_signal_groups and len(groups) >= 2:
            return True
    metadata = [
        (claim, source_by_id[UUID(str(claim.source_id))])
        for claim in claims
        if claim.claim_kind is EvidenceClaimKind.EPISODE_IDENTITY
        and claim.verification is VerificationState.SECONDARY_CORROBORATED
        and not claim.supports_why_now
        and claim.episode_locator is not None
        and claim.event_or_release_at is not None
        and cutoff <= claim.event_or_release_at <= now + timedelta(minutes=5)
        and source_by_id[UUID(str(claim.source_id))].provider == "tvmaze"
        and source_by_id[UUID(str(claim.source_id))].policy_class
        == "tvmaze-metadata-v1"
    ]
    for metadata_claim, metadata_source in metadata:
        assert metadata_claim.episode_locator is not None
        relevant_signals = [
            (claim, source)
            for claim, source in signals
            if _source_matches_show(
                source, metadata_claim.episode_locator.show_or_title
            )
        ]
        if not _requested_audience_has_minimum_support(
            intent,
            metadata_claim.episode_locator.show_or_title,
            [metadata_claim, *(claim for claim, _ in relevant_signals)],
            source_by_id,
            relaxed_soft_preferences=relaxed_soft_preferences,
        ):
            continue
        relevant_signal_groups = {
            source.independence_group for _, source in relevant_signals
        }
        groups = {metadata_source.independence_group, *relevant_signal_groups}
        # Metadata is never promoted to an official primary. Two independent,
        # current, title-bound discussions may justify exactly one bounded
        # synthesis pass for an explicitly low-confidence scene-pack request.
        if len(relevant_signal_groups) >= 2 and len(groups) >= 3:
            return True
    return False


def _source_matches_show(
    source: EvidenceSourceRecordV2, show_or_title: str
) -> bool:
    media = f" {_normalized(show_or_title)} "
    return bool(media.strip()) and (
        media in f" {_normalized(source.title)} "
        or source_record_binds_media_title(
            provider=source.provider,
            provider_record_id=source.provider_record_id,
            canonical_url=str(source.canonical_url),
            show_or_title=show_or_title,
        )
    )


def _claim_show_or_title(claim: EvidenceClaimRecordV2) -> str | None:
    if claim.why_now_event is not None:
        return claim.why_now_event.media_identity.show_or_title
    if claim.episode_locator is not None:
        return claim.episode_locator.show_or_title
    if claim.quote_fact is not None:
        return claim.quote_fact.media_identity.show_or_title
    if claim.scene_fact is not None:
        return claim.scene_fact.show_or_title
    if claim.cast_fact is not None:
        return claim.cast_fact.show_or_title
    return None


def _build_candidate_diagnostics(
    *,
    batches: list[ProviderBatch],
    sources: list[EvidenceSourceRecordV2],
    claims: list[EvidenceClaimRecordV2],
    intent: ResearchIntentV2,
    now: datetime,
    recovery_attempted: bool,
    synthesis_titles: set[str] | None = None,
    final_opportunities: list | None = None,
) -> list[CandidateDiagnosticV1]:
    """Explain every bounded deep-research title without retaining web payloads."""

    trace_funnel = next(
        (
            batch.candidate_funnel
            for batch in batches
            if batch.provider in {"openai", "xai"}
            and batch.candidate_funnel.candidate_traces
        ),
        None,
    ) or next(
        (
            batch.candidate_funnel
            for batch in batches
            if batch.candidate_funnel.candidate_traces
        ),
        None,
    )
    if trace_funnel is None:
        return []
    source_by_id = {UUID(str(item.source_id)): item for item in sources}
    cutoff = now - timedelta(days=intent.freshness_days)
    selected_titles = {_normalized(value) for value in (synthesis_titles or set())}
    final_by_title = {
        _normalized(item.media_identity.show_or_title): item
        for item in (final_opportunities or [])
    }
    facet_ids = {
        item.facet_id
        for item in (
            intent.interpretation.facets if intent.interpretation is not None else []
        )
    }
    audience_requested = bool(
        facet_ids & {"female_skewing_fandom", "male_skewing_fandom", "queer_fandom"}
    )
    diagnostics: list[CandidateDiagnosticV1] = []
    ranking_metrics = (
        "intent_fit",
        "audience_fit",
        "freshness",
        "fandom_velocity",
        "short_form_edit_potential",
        "relationship_or_character_salience",
        "footage_actionability",
        "evidence_quality",
        "source_diversity",
        "uncertainty_penalty",
        "total",
    )
    metric_thresholds = {
        "audience_fit": 0.40,
        "short_form_edit_potential": 0.35,
        "footage_actionability": 0.35,
    }

    for trace in trace_funnel.candidate_traces[:12]:
        normalized_title = _normalized(trace.title)
        relevant: list[tuple[EvidenceClaimRecordV2, EvidenceSourceRecordV2]] = []
        for claim in claims:
            source = source_by_id.get(UUID(str(claim.source_id)))
            if source is None:
                continue
            claim_title = _claim_show_or_title(claim)
            if (
                claim_title is not None
                and _normalized(claim_title) == normalized_title
            ) or (
                claim_title is None and _source_matches_show(source, trace.title)
            ):
                relevant.append((claim, source))

        current_identities = [
            (claim, source)
            for claim, source in relevant
            if (
                claim.verification is VerificationState.PRIMARY_VERIFIED
                and claim.claim_kind
                in {EvidenceClaimKind.WHY_NOW, EvidenceClaimKind.OFFICIAL_CLIP}
                and claim.supports_why_now
                and claim.event_or_release_at is not None
                and cutoff <= claim.event_or_release_at <= now + timedelta(minutes=5)
            )
            or (
                claim.claim_kind is EvidenceClaimKind.EPISODE_IDENTITY
                and claim.verification is VerificationState.SECONDARY_CORROBORATED
                and claim.episode_locator is not None
                and claim.event_or_release_at is not None
                and cutoff <= claim.event_or_release_at <= now + timedelta(minutes=5)
            )
        ]
        current_signals = [
            (claim, source)
            for claim, source in relevant
            if claim.claim_kind is EvidenceClaimKind.VIEWER_DISCUSSION
            and claim.verification is VerificationState.SECONDARY_CORROBORATED
            and claim.supports_why_now
            and (source.source_created_at or source.page_published_at) is not None
            and cutoff
            <= (source.source_created_at or source.page_published_at)
            <= now + timedelta(minutes=5)
        ]
        signal_groups = {source.independence_group for _, source in current_signals}
        has_primary = any(
            claim.verification is VerificationState.PRIMARY_VERIFIED
            and claim.claim_kind
            in {EvidenceClaimKind.WHY_NOW, EvidenceClaimKind.OFFICIAL_CLIP}
            for claim, _ in current_identities
        )
        required_signal_groups = 1 if has_primary else 2
        evidence_claims = [claim for claim, _ in relevant]
        strict_audience = (
            _requested_audience_has_minimum_support(
                intent,
                trace.title,
                evidence_claims,
                source_by_id,
            )
            if evidence_claims
            else not audience_requested
        )
        recovery_audience = (
            _requested_audience_has_minimum_support(
                intent,
                trace.title,
                evidence_claims,
                source_by_id,
                relaxed_soft_preferences=True,
            )
            if evidence_claims
            else not audience_requested
        )
        effective_audience = strict_audience or (
            recovery_attempted and recovery_audience
        )
        corpus = " ".join(
            [
                *(claim.text for claim, _ in relevant),
                *(source.title for _, source in relevant),
            ]
        )
        audience_pattern = (
            _FEMALE_AUDIENCE_DIRECT
            if "female_skewing_fandom" in facet_ids
            else _MALE_AUDIENCE_DIRECT
            if "male_skewing_fandom" in facet_ids
            else _QUEER_AUDIENCE_DIRECT
        )
        affinity_pattern = (
            _FEMALE_AFFINITY_CUE
            if "female_skewing_fandom" in facet_ids
            else _MALE_AFFINITY_CUE
            if "male_skewing_fandom" in facet_ids
            else _QUEER_AUDIENCE_DIRECT
        )
        direct_audience = bool(audience_pattern.search(corpus)) if audience_requested else True
        affinity_cues = {
            match.group(0).casefold() for match in affinity_pattern.finditer(corpus)
        } if audience_requested else {"general-audience"}
        audience_units = 2 if direct_audience else min(2, len(affinity_cues))
        audience_threshold = 1 if recovery_attempted else 2

        current_hook = current_identities[0][0].text if current_identities else None
        fandom_copy = list(
            dict.fromkeys(claim.text for claim, _ in current_signals)
        )[:12]
        audience_copy = list(
            dict.fromkeys(
                claim.text
                for claim, source in current_signals
                if audience_pattern.search(f"{claim.text} {source.title}")
                or affinity_pattern.search(f"{claim.text} {source.title}")
            )
        )[:12]
        story_copy = list(
            dict.fromkeys(
                claim.text
                for claim, _ in relevant
                if claim.claim_kind
                in {
                    EvidenceClaimKind.EPISODE_IDENTITY,
                    EvidenceClaimKind.QUOTE,
                    EvidenceClaimKind.SCENE_CONTEXT,
                    EvidenceClaimKind.CAST_IDENTITY,
                }
            )
        )[:12]
        source_categories = list(
            dict.fromkeys(
                f"{source.provider}:{source.source_type.value}:{claim.claim_kind.value}"
                for claim, source in relevant
            )
        )[:20]
        evidence_references = list(
            dict.fromkeys(claim.claim_id for claim, _ in relevant)
        )[:40]

        final = final_by_title.get(normalized_title)
        if final is not None:
            gate = "SUPPORTED"
            failure_class = CandidateFailureClass.SUPPORTED
        elif not relevant:
            gate = "RETRIEVAL:NO_TITLE_BOUND_EVIDENCE"
            failure_class = CandidateFailureClass.RETRIEVAL_RELATED
        elif not current_identities:
            gate = "EVIDENCE:NO_CURRENT_HOOK"
            failure_class = CandidateFailureClass.EVIDENCE_RELATED
        elif not current_signals:
            gate = "RETRIEVAL:NO_USABLE_CURRENT_FANDOM_EVIDENCE"
            failure_class = CandidateFailureClass.RETRIEVAL_RELATED
        elif not effective_audience:
            gate = "EVIDENCE:REQUESTED_AUDIENCE_FIT_FLOOR"
            failure_class = CandidateFailureClass.EVIDENCE_RELATED
        elif len(signal_groups) < required_signal_groups:
            gate = "EVIDENCE:CURRENT_FANDOM_SOURCE_FLOOR"
            failure_class = CandidateFailureClass.EVIDENCE_RELATED
        elif normalized_title in selected_titles:
            gate = "THRESHOLD:NO_SUPPORTED_EDITORIAL_CONCEPT"
            failure_class = CandidateFailureClass.THRESHOLD_RELATED
        else:
            gate = "EVIDENCE:NOT_SELECTED_FOR_SYNTHESIS"
            failure_class = CandidateFailureClass.EVIDENCE_RELATED

        scores = [
            CandidateScoreTraceV1(
                metric="current_event_evidence",
                count_value=len(current_identities),
                count_threshold=1,
                status=(
                    CandidateScoreStatus.PASSED
                    if current_identities
                    else CandidateScoreStatus.FAILED
                ),
                note="A current title-bound official hook or exact episode identity is required.",
            ),
            CandidateScoreTraceV1(
                metric="current_fandom_independent_sources",
                count_value=len(signal_groups),
                count_threshold=required_signal_groups,
                status=(
                    CandidateScoreStatus.PASSED
                    if len(signal_groups) >= required_signal_groups
                    else CandidateScoreStatus.FAILED
                ),
                note=(
                    "One credible current fandom source can support a low-confidence card beside a strong official story source; metadata-only identity requires two."
                ),
            ),
            CandidateScoreTraceV1(
                metric="requested_audience_support_units",
                count_value=audience_units,
                count_threshold=audience_threshold,
                status=(
                    CandidateScoreStatus.PASSED
                    if effective_audience
                    else CandidateScoreStatus.FAILED
                ),
                note=(
                    "Audience intent is a soft evidence prior, not a demographic stereotype; recovery may reduce two affinity cues to one without relaxing facts."
                ),
            ),
        ]
        quality = getattr(final, "quality_score", None) if final is not None else None
        for metric in ranking_metrics:
            value = getattr(quality, metric) if quality is not None else None
            threshold = metric_thresholds.get(metric)
            if value is None:
                status = CandidateScoreStatus.NOT_COMPUTED
                note = "Not computed because the candidate did not reach a validated opportunity and concept-specific footage request."
            elif threshold is None:
                status = CandidateScoreStatus.INFORMATIONAL
                note = "Recorded ranking component; it is not a standalone universal gate."
            else:
                status = (
                    CandidateScoreStatus.PASSED
                    if value >= threshold
                    else CandidateScoreStatus.FAILED
                )
                note = "Recorded M1.1 quality-gate component."
            scores.append(
                CandidateScoreTraceV1(
                    metric=metric,
                    value=value,
                    threshold=threshold,
                    status=status,
                    note=note,
                )
            )
        scores.extend(
            [
                CandidateScoreTraceV1(
                    metric="concept_specificity",
                    threshold=0.50,
                    status=CandidateScoreStatus.NOT_COMPUTED,
                    note="Computed only after a dossier-backed editorial concept exists.",
                ),
                CandidateScoreTraceV1(
                    metric="editorial_concept_total",
                    threshold=0.45,
                    status=CandidateScoreStatus.NOT_COMPUTED,
                    note="Computed only after concept and footage validation.",
                ),
            ]
        )
        if final is not None and final.short_form_edit_potential is not None:
            short_form_inference = (
                f"{final.short_form_edit_potential.band.value}: "
                f"{final.short_form_edit_potential.explanation}"
            )
        elif current_signals and story_copy:
            short_form_inference = (
                "PROMISING SIGNALS, NOT SCORED: current fandom plus story-level evidence was found; "
                "the full inferred metric awaits a supported concept. Direct TikTok data was not used."
            )
        elif current_signals:
            short_form_inference = (
                "LIMITED SIGNALS, NOT SCORED: current fandom evidence exists but no actionable "
                "story evidence survived. Direct TikTok data was not used."
            )
        else:
            short_form_inference = (
                "INSUFFICIENT EVIDENCE, NOT SCORED: no usable current fandom signal survived. "
                "Direct TikTok data was not used."
            )

        diagnostics.append(
            CandidateDiagnosticV1(
                candidate_name=trace.candidate_name,
                title=trace.title,
                shortlist_rank=trace.shortlist_rank,
                shortlist_reason=trace.shortlist_reason,
                current_hook=current_hook,
                audience_fit_evidence=audience_copy,
                fandom_evidence=fandom_copy,
                story_or_episode_evidence=story_copy,
                source_categories=source_categories,
                evidence_references=evidence_references,
                inferred_short_form_edit_potential=short_form_inference,
                scores_and_thresholds=scores,
                exact_rejection_gate=gate,
                failure_class=failure_class,
            )
        )
    return diagnostics


def _select_synthesis_evidence(
    intent: ResearchIntentV2,
    sources: list[EvidenceSourceRecordV2],
    claims: list[EvidenceClaimRecordV2],
    *,
    now: datetime,
    relaxed_soft_preferences: bool = False,
) -> tuple[list[EvidenceSourceRecordV2], list[EvidenceClaimRecordV2]]:
    """Select a compact, gate-capable allow-list for paid synthesis.

    Discovery and persisted provenance remain complete. Synthesis receives only
    the newest identity candidates that can actually pass a trusted gate, their
    current discussion signals, and a bounded amount of exact supporting
    context. This avoids spending the input budget on unrelated metadata rows.
    """

    cutoff = now - timedelta(days=intent.freshness_days)
    source_by_id = {UUID(str(item.source_id)): item for item in sources}
    current_signals = [
        claim
        for claim in claims
        if claim.claim_kind is EvidenceClaimKind.VIEWER_DISCUSSION
        and claim.verification is VerificationState.SECONDARY_CORROBORATED
        and claim.supports_why_now
        and (
            source_by_id[UUID(str(claim.source_id))].source_created_at
            or source_by_id[UUID(str(claim.source_id))].page_published_at
        ) is not None
        and cutoff
        <= (
            source_by_id[UUID(str(claim.source_id))].source_created_at
            or source_by_id[UUID(str(claim.source_id))].page_published_at
        )
        <= now
    ]

    candidates: list[
        tuple[datetime, int, str, EvidenceClaimRecordV2, list[EvidenceClaimRecordV2]]
    ] = []
    for identity_claim in claims:
        show_or_title: str | None = None
        identity_source = source_by_id[UUID(str(identity_claim.source_id))]
        required_signal_groups = 0
        if (
            identity_claim.verification is VerificationState.PRIMARY_VERIFIED
            and identity_claim.claim_kind
            in {EvidenceClaimKind.WHY_NOW, EvidenceClaimKind.OFFICIAL_CLIP}
            and identity_claim.supports_why_now
            and identity_claim.why_now_event is not None
            and identity_claim.why_now_event.media_identity.media_kind
            in intent.media_kinds
            and identity_claim.event_or_release_at is not None
            and cutoff <= identity_claim.event_or_release_at <= now
        ):
            show_or_title = identity_claim.why_now_event.media_identity.show_or_title
            required_signal_groups = 1
        elif (
            identity_claim.claim_kind is EvidenceClaimKind.EPISODE_IDENTITY
            and identity_claim.verification is VerificationState.SECONDARY_CORROBORATED
            and not identity_claim.supports_why_now
            and identity_claim.episode_locator is not None
            and identity_claim.event_or_release_at is not None
            and cutoff
            <= identity_claim.event_or_release_at
            <= now + timedelta(minutes=5)
            and identity_source.provider == "tvmaze"
            and identity_source.policy_class == "tvmaze-metadata-v1"
        ):
            show_or_title = identity_claim.episode_locator.show_or_title
            required_signal_groups = 2
        if show_or_title is None or identity_claim.event_or_release_at is None:
            continue
        relevant_signals = [
            signal
            for signal in current_signals
            if _source_matches_show(
                source_by_id[UUID(str(signal.source_id))], show_or_title
            )
        ]
        if not _requested_audience_has_minimum_support(
            intent,
            show_or_title,
            [identity_claim, *relevant_signals],
            source_by_id,
            relaxed_soft_preferences=relaxed_soft_preferences,
        ):
            continue
        signal_groups = {
            source_by_id[UUID(str(signal.source_id))].independence_group
            for signal in relevant_signals
        }
        if len(signal_groups) < required_signal_groups:
            continue
        all_groups = {identity_source.independence_group, *signal_groups}
        if len(all_groups) < required_signal_groups + 1:
            continue
        candidates.append(
            (
                identity_claim.event_or_release_at,
                len(signal_groups),
                show_or_title,
                identity_claim,
                relevant_signals,
            )
        )

    candidates.sort(key=lambda item: (-item[0].timestamp(), -item[1], _normalized(item[2])))
    selected: list[
        tuple[str, EvidenceClaimRecordV2, list[EvidenceClaimRecordV2]]
    ] = []
    seen_titles: set[str] = set()
    for _, _, show_or_title, identity_claim, relevant_signals in candidates:
        normalized_title = _normalized(show_or_title)
        if normalized_title in seen_titles:
            continue
        seen_titles.add(normalized_title)
        selected.append((show_or_title, identity_claim, relevant_signals))
        if len(selected) >= intent.max_results:
            break

    selected_claim_ids: set[UUID] = set()
    for show_or_title, identity_claim, relevant_signals in selected:
        selected_claim_ids.add(UUID(str(identity_claim.claim_id)))
        ordered_signals = sorted(
            relevant_signals,
            key=lambda claim: (
                -(
                    source_by_id[UUID(str(claim.source_id))].source_created_at
                    or source_by_id[UUID(str(claim.source_id))].page_published_at
                    or cutoff
                ).timestamp(),
                source_by_id[UUID(str(claim.source_id))].independence_group,
            ),
        )
        selected_signals: list[EvidenceClaimRecordV2] = []
        signal_groups: set[str] = set()
        for signal in ordered_signals:
            group = source_by_id[UUID(str(signal.source_id))].independence_group
            if group in signal_groups:
                continue
            signal_groups.add(group)
            selected_signals.append(signal)
            if len(selected_signals) >= 4:
                break
        if len(selected_signals) < 4:
            selected_ids = {UUID(str(signal.claim_id)) for signal in selected_signals}
            selected_signals.extend(
                signal
                for signal in ordered_signals
                if UUID(str(signal.claim_id)) not in selected_ids
            )
            selected_signals = selected_signals[:4]
        selected_claim_ids.update(
            UUID(str(signal.claim_id)) for signal in selected_signals
        )

        same_show = [
            claim
            for claim in claims
            if (
                _normalized(_claim_show_or_title(claim) or "")
                == _normalized(show_or_title)
                or (
                    _claim_show_or_title(claim) is None
                    and _source_matches_show(
                        source_by_id[UUID(str(claim.source_id))], show_or_title
                    )
                )
            )
            and UUID(str(claim.claim_id)) not in selected_claim_ids
            and claim.verification
            not in {VerificationState.STALE, VerificationState.RETRACTED}
        ]
        cast_claims = sorted(
            (claim for claim in same_show if claim.claim_kind is EvidenceClaimKind.CAST_IDENTITY),
            key=lambda claim: (claim.cast_fact.character_name.casefold(), claim.text.casefold())
            if claim.cast_fact is not None
            else ("", claim.text.casefold()),
        )[:6]
        supporting_claims = sorted(
            (claim for claim in same_show if claim.claim_kind is not EvidenceClaimKind.CAST_IDENTITY),
            key=lambda claim: (claim.claim_kind.value, claim.text.casefold()),
        )[:10]
        selected_claim_ids.update(
            UUID(str(claim.claim_id)) for claim in [*cast_claims, *supporting_claims]
        )

    selected_claims = [
        claim
        for claim in claims
        if UUID(str(claim.claim_id)) in selected_claim_ids
    ]
    selected_source_ids = {UUID(str(claim.source_id)) for claim in selected_claims}
    selected_sources = [
        source
        for source in sources
        if UUID(str(source.source_id)) in selected_source_ids
    ]
    return selected_sources, selected_claims


def _synthesis_rejection_code(stage: str, error: Exception) -> str:
    """Reduce local validation failures to bounded, value-free diagnostics."""

    message = str(error)
    known = (
        ("concept:missing-specific-editorial-angle", "missing-editorial-concept"),
        ("concept:missing-specific-intro", "missing-concept-intro"),
        ("concept:quality-gate", "concept-quality"),
        ("quality:audience-fit", "audience-fit"),
        ("quality:short-form-edit-potential", "short-form-edit-potential"),
        ("quality:footage-actionability", "footage-actionability"),
        ("unsupported franchise speculation", "unsupported-franchise-connection"),
        ("concept asserted an unsupported canonical/franchise connection", "unsupported-franchise-connection"),
        ("concept asserted an unsupported quote", "unsupported-concept-quote"),
        ("concept asserted an unsupported episode locator", "unsupported-concept-episode"),
        ("LIKELY_INFERRED source needs relevant identity and moment evidence", "inferred-source-support"),
        ("STRONGLY_SUPPORTED source needs asset and exact-scene evidence", "supported-source-evidence"),
        ("VERIFIED source needs authoritative asset and exact-scene evidence", "verified-source-evidence"),
        ("scene-pack availability cannot be promoted above LIKELY_INFERRED", "scene-pack-certainty"),
        ("requested source cites a claim outside the request allow-list", "source-claim-allow-list"),
        ("inferred/unknown intro lead needs matching moment evidence", "intro-moment-support"),
        ("verified/supported intro lead needs a matching scene fact", "intro-scene-support"),
        ("opportunity focus named an unsupported character", "focus-character-support"),
        ("opportunity focus topic is unsupported by selected evidence", "focus-topic-support"),
        ("low-confidence opportunity requires either one current primary", "opportunity-gate"),
        ("provider selected a claim outside the request allow-list", "opportunity-claim-allow-list"),
        ("provider cannot change a claim's why-now support", "why-now-role-mismatch"),
        ("footage request belongs to a different title", "footage-title-mismatch"),
        ("footage request topic is outside", "footage-topic-mismatch"),
        ("opportunity focus topic is absent", "footage-focus-missing"),
        ("opportunity focus characters are absent", "footage-focus-characters-missing"),
        ("footage request named a character outside", "footage-character-mismatch"),
        ("synthesized media kind is outside", "media-kind-mismatch"),
        ("synthesized recommendation violates an explicit exclusion", "exclusion"),
        (
            "opportunity evidence does not support a required audience focus",
            "required-audience-focus",
        ),
        ("spoiler-avoid intent permits official promotional footage only", "spoiler-policy"),
    )
    code = next((value for prefix, value in known if message.startswith(prefix)), "other-local-validation")
    return f"{stage}:{code}"


def _is_omittable_intro_lead_error(error: Exception) -> bool:
    message = str(error)
    return message.startswith(
        "inferred/unknown intro lead needs matching moment evidence"
    ) or message.startswith(
        "verified/supported intro lead needs a matching scene fact"
    )


def _editorial_concepts_required(intent: ResearchIntentV2) -> bool:
    interpretation = intent.interpretation
    if interpretation is None:
        return False
    return interpretation.broad_query or any(
        item.category.value != "HARD_CONSTRAINT"
        for item in interpretation.facets
    )


def _derive_evidence_bound_concept(
    opportunity: TrendOpportunityDraftV2,
    footage: FootageRequestDraftV2,
) -> tuple[FootageRequestDraftV2, EditorialConceptDraftV1] | None:
    """Upgrade a specific legacy M1 pair without adding a factual claim.

    The r73 synthesis contract exposed one opportunity and one footage request.
    M1.1 asks the synthesis model for first-class concept routes, but replay
    fixtures and an in-flight older response may still use the earlier shape.
    This bounded bridge is permitted only when the request already names an
    evidence-linked source moment. It never invents a quote, episode, character,
    franchise link, or availability claim, and generic title-only packs still
    fail closed.
    """

    intro_leads = list(footage.intro_leads)
    if not intro_leads:
        source = next(
            (
                item
                for item in footage.required_sources
                if item.verification_level
                is not FootageVerificationLevel.UNKNOWN
                and item.asset_kind
                in {
                    SourceAcquisitionKind.EPISODE,
                    SourceAcquisitionKind.OFFICIAL_TRAILER,
                    SourceAcquisitionKind.OFFICIAL_CLIP,
                    SourceAcquisitionKind.INDIVIDUAL_SCENES,
                }
                if item.scene_or_moment.strip()
                and item.supporting_claim_ids
                and len(item.scene_or_moment.split()) >= 4
                and not re.match(
                    r"^(?:any\s+relevant|any\s+scenes?|generic|clips?\s+from)",
                    item.scene_or_moment.strip(),
                    re.IGNORECASE,
                )
            ),
            None,
        )
        if source is None:
            return None
        intro_leads = [
            IntroMaterialLeadDraftV2(
                source_key=source.source_key,
                moment_description=source.scene_or_moment,
                why_it_might_lead_into_montage=(
                    "This evidence-linked current moment establishes the exact "
                    "subject that the proposed montage would explore; timing and "
                    "usable reactions still require later footage inspection."
                ),
                verification_level=source.verification_level,
                supporting_claim_ids=list(source.supporting_claim_ids),
            )
        ]
        footage = footage.model_copy(update={"intro_leads": intro_leads})

    subject = (
        " and ".join(opportunity.focus.characters)
        if opportunity.focus.characters
        else opportunity.focus.relationship_or_topic
    )
    uncertainties = list(opportunity.caveats)
    if all(lead.quote is None for lead in intro_leads):
        uncertainties.append(
            "Exact dialogue is not yet verified; provide the requested episode, trailer, "
            "or scene pack so later footage analysis can inspect the proposed moment."
        )
    # These beats reorganize already-present synthesis copy. They describe
    # semantic footage needs, not claims that a supplied file contains a shot.
    montage_arc = [
        f"Current setup — {opportunity.why_now}",
        f"Fan-recognized subject — {opportunity.what_viewers_are_discussing}",
        f"Emotional payoff to test in supplied footage — {opportunity.emotional_edit_direction}",
    ]
    concept = EditorialConceptDraftV1(
        concept_key="evidence_bound_current_arc",
        title=opportunity.title,
        central_subject=subject,
        central_relationship=opportunity.focus.relationship_or_topic,
        core_emotion=opportunity.emotional_edit_direction[:500],
        viewer_hook=opportunity.creative_hook,
        why_fans_may_care=opportunity.what_viewers_are_discussing,
        current_event=opportunity.why_now,
        legacy_or_contextual_connection=(
            "No canonical legacy connection is asserted by this evidence packet; "
            "the concept stays within the supported current-title context."
        ),
        legacy_connection_type=LegacyConnectionType.NONE,
        intro_leads=intro_leads,
        song_handoff_idea=(
            "End the evidence-linked intro lead on its unresolved emotional question, "
            "then hand off into the first montage beat; exact timing awaits footage analysis."
        ),
        montage_arc=montage_arc,
        ending_or_payoff=(
            "Return to the current-event subject and test the proposed emotional payoff "
            "against the supplied footage rather than assuming a usable final reaction."
        ),
        evidence=list(opportunity.evidence),
        verification_status=min(
            (lead.verification_level for lead in intro_leads),
            key=lambda value: {
                FootageVerificationLevel.UNKNOWN: 0,
                FootageVerificationLevel.LIKELY_INFERRED: 1,
                FootageVerificationLevel.STRONGLY_SUPPORTED: 2,
                FootageVerificationLevel.VERIFIED: 3,
            }[value],
        ),
        creative_strength=opportunity.confidence,
        footage_feasibility=(0.78 if footage.required_sources else 0.30),
        known_uncertainties=list(dict.fromkeys(uncertainties))[:20],
        footage_request=footage,
    )
    return footage, concept


def _opportunity_sort_key(pair) -> tuple[float, float, str]:
    opportunity = pair[0]
    quality_total = (
        opportunity.quality_score.total
        if opportunity.quality_score is not None
        else opportunity.score.total
    )
    # Quality score is authoritative for M1.1. The legacy score remains a
    # deterministic tie-breaker and a compatibility diagnostic only.
    return (-quality_total, -opportunity.score.total, opportunity.title.casefold())


def _canonicalize_fandom_story_dossier(
    draft: FandomStoryDossierDraftV1,
    *,
    opportunity: TrendOpportunityDraftV2,
    dossier_id: UUID,
    opportunity_id: UUID,
    evidence_index: EvidenceIndex,
    allowed_claim_ids: set[UUID],
) -> FandomStoryDossierV1:
    if _normalized(draft.show_or_title) != _normalized(
        opportunity.media_identity.show_or_title
    ):
        raise ValueError("dossier title must match its opportunity")
    trusted: list[TrustedOpportunityEvidenceReferenceV2] = []
    joined: dict[UUID, tuple[EvidenceClaimRecordV2, EvidenceSourceRecordV2]] = {}
    for selection in draft.evidence:
        claim_id = UUID(str(selection.claim_id))
        if claim_id not in allowed_claim_ids:
            raise ValueError("dossier selected a claim outside the request allow-list")
        claim, source = evidence_index.joined(claim_id)
        if selection.supports_why_now != claim.supports_why_now:
            raise ValueError("dossier cannot change a claim's why-now support")
        joined[claim_id] = (claim, source)
        trusted.append(
            TrustedOpportunityEvidenceReferenceV2(
                claim_id=selection.claim_id,
                role=selection.role,
                supports_why_now=claim.supports_why_now,
                independence_group=source.independence_group,
            )
        )
    opportunity_ids = {UUID(str(item.claim_id)) for item in opportunity.evidence}
    if not opportunity_ids.issubset(joined):
        raise ValueError("dossier must retain every opportunity evidence claim")

    def selected_pairs(values) -> list[tuple[EvidenceClaimRecordV2, EvidenceSourceRecordV2]]:
        return [joined[UUID(str(value))] for value in values]

    def validate_status(label: str, status: FootageVerificationLevel, values) -> None:
        pairs = selected_pairs(values)
        states = {claim.verification for claim, _ in pairs}
        if status is FootageVerificationLevel.VERIFIED and VerificationState.PRIMARY_VERIFIED not in states:
            raise ValueError(f"dossier {label} cannot be VERIFIED without primary evidence")
        if status is FootageVerificationLevel.STRONGLY_SUPPORTED and not states & {
            VerificationState.PRIMARY_VERIFIED,
            VerificationState.SECONDARY_CORROBORATED,
        }:
            raise ValueError(f"dossier {label} lacks corroborated evidence")
        if states & {VerificationState.STALE, VerificationState.RETRACTED}:
            raise ValueError(f"dossier {label} cites stale or retracted evidence")

    validate_status(
        "current hook",
        draft.current_event_or_hook.verification_status,
        draft.current_event_or_hook.supporting_claim_ids,
    )
    hook_pairs = selected_pairs(draft.current_event_or_hook.supporting_claim_ids)
    if not any(
        claim.supports_why_now
        or (
            claim.claim_kind is EvidenceClaimKind.EPISODE_IDENTITY
            and claim.event_or_release_at is not None
        )
        for claim, _ in hook_pairs
    ):
        raise ValueError("dossier current hook needs a dated current-event claim")

    validate_status(
        "current source",
        draft.current_source.verification_status,
        draft.current_source.supporting_claim_ids,
    )
    source_pairs = selected_pairs(draft.current_source.supporting_claim_ids)
    if not any(
        _normalized(draft.current_source.source_title) in _normalized(source.title)
        or _normalized(source.title) in _normalized(draft.current_source.source_title)
        for _, source in source_pairs
    ):
        raise ValueError("dossier current source title is not evidence-bound")
    if draft.current_source.source_kind.value == "EPISODE" and not any(
        claim.episode_locator is not None
        and _normalized(claim.episode_locator.show_or_title)
        == _normalized(draft.current_source.show_or_title)
        and claim.episode_locator.season_number == draft.current_source.season_number
        and claim.episode_locator.episode_number == draft.current_source.episode_number
        and (
            draft.current_source.episode_title is None
            or _normalized(claim.episode_locator.episode_title)
            == _normalized(draft.current_source.episode_title)
        )
        for claim, _ in source_pairs
    ):
        raise ValueError("dossier episode source lacks its exact locator evidence")

    for character in draft.named_characters:
        validate_status(
            f"character {character.character_name}",
            character.verification_status,
            character.supporting_claim_ids,
        )
        if not any(
            (
                claim.cast_fact is not None
                and _normalized(claim.cast_fact.character_name)
                == _normalized(character.character_name)
                and _normalized(claim.cast_fact.show_or_title)
                == _normalized(character.show_or_title)
            )
            or (
                claim.scene_fact is not None
                and _normalized(claim.scene_fact.show_or_title)
                == _normalized(character.show_or_title)
                and any(
                    _normalized(value) == _normalized(character.character_name)
                    for value in claim.scene_fact.characters
                )
            )
            for claim, _ in selected_pairs(character.supporting_claim_ids)
        ):
            raise ValueError("dossier named character lacks exact identity evidence")

    fact_groups = (
        ([draft.central_relationship] if draft.central_relationship is not None else []),
        draft.relationship_or_character_history,
        draft.why_fans_currently_care,
        draft.audience_and_fandom_evidence,
    )
    for label, facts in zip(
        ("central relationship", "history", "fan interest", "audience/fandom"),
        fact_groups,
        strict=True,
    ):
        for fact in facts:
            validate_status(label, fact.verification_status, fact.supporting_claim_ids)
    for fact in (*draft.why_fans_currently_care, *draft.audience_and_fandom_evidence):
        if not any(
            claim.claim_kind is EvidenceClaimKind.VIEWER_DISCUSSION
            for claim, _ in selected_pairs(fact.supporting_claim_ids)
        ):
            raise ValueError("dossier fandom-interest facts require a current discussion claim")

    if draft.exact_or_likely_quote is not None:
        quote_lead = draft.exact_or_likely_quote
        validate_status(
            "quote",
            quote_lead.verification_status,
            quote_lead.supporting_claim_ids,
        )
        quote_claim, _ = joined[UUID(str(quote_lead.quote.claim_id))]
        if quote_lead.quote.status.value == "VERIFIED":
            if (
                quote_claim.quote_fact is None
                or quote_claim.verification is not VerificationState.PRIMARY_VERIFIED
                or _normalized(quote_claim.quote_fact.exact_text)
                != _normalized(quote_lead.quote.text)
            ):
                raise ValueError("dossier verified quote lacks authoritative exact evidence")

    for connection in draft.franchise_connections:
        validate_status(
            "franchise connection",
            connection.verification_status,
            connection.supporting_claim_ids,
        )
        connection_pairs = selected_pairs(connection.supporting_claim_ids)
        corpus = _normalized(
            " ".join(
                [
                    *(claim.text for claim, _ in connection_pairs),
                    *(source.title for _, source in connection_pairs),
                    *(
                        json.dumps(fact.model_dump(mode="json"), ensure_ascii=False)
                        for claim, _ in connection_pairs
                        for fact in (
                            claim.episode_locator,
                            claim.quote_fact,
                            claim.why_now_event,
                            claim.scene_fact,
                            claim.cast_fact,
                        )
                        if fact is not None
                    ),
                ]
            )
        )
        if _normalized(connection.connected_title) not in corpus:
            raise ValueError("dossier franchise connection lacks the connected title in evidence")
        if connection.connection_type in {
            LegacyConnectionType.SAME_CHARACTER,
            LegacyConnectionType.SAME_CANONICAL_UNIVERSE,
            LegacyConnectionType.EXPLICIT_CALLBACK,
        } and not re.search(
            r"\b(?:spinoff|spin\s*off|sequel|prequel|same\s+universe|returns?|"
            r"returning|reunion|callback|continuation|parent\s+series|repris(?:e|es|ing))\b",
            corpus,
            re.IGNORECASE,
        ):
            raise ValueError("dossier asserted an unsupported canonical connection")

    values = draft.model_dump(mode="python", exclude={"evidence"})
    return FandomStoryDossierV1(
        **values,
        dossier_id=dossier_id,
        opportunity_id=opportunity_id,
        evidence=trusted,
    )


def _validate_editorial_concept_against_dossier(
    draft: EditorialConceptDraftV1,
    dossier: FandomStoryDossierV1,
) -> None:
    if draft.dossier_key != dossier.dossier_key:
        raise ValueError("concept does not reference its fandom/story dossier")
    dossier_claim_ids = {UUID(str(item.claim_id)) for item in dossier.evidence}
    concept_claim_ids = {UUID(str(item.claim_id)) for item in draft.evidence}
    if not concept_claim_ids.issubset(dossier_claim_ids):
        raise ValueError("concept selected evidence outside its dossier")
    dossier_copy = " ".join(
        [
            dossier.show_or_title,
            dossier.current_event_or_hook.text,
            dossier.current_source.source_title,
            *(item.character_name for item in dossier.named_characters),
            dossier.central_relationship.text
            if dossier.central_relationship is not None
            else "",
            *(item.text for item in dossier.relationship_or_character_history),
            *(item.text for item in dossier.why_fans_currently_care),
            *(item.text for item in dossier.audience_and_fandom_evidence),
            *(item.description for item in dossier.franchise_connections),
        ]
    )
    anchor_tokens = {
        token
        for token in _normalized(dossier_copy).split()
        if len(token) >= 4
        and token
        not in {"this", "that", "with", "from", "current", "episode", "series"}
    }
    concept_tokens = set(
        _normalized(
            " ".join(
                [
                    draft.central_subject,
                    draft.central_relationship or "",
                    draft.current_event,
                    draft.viewer_hook,
                    draft.why_fans_may_care,
                    *draft.montage_arc,
                    draft.ending_or_payoff,
                ]
            )
        ).split()
    )
    if len(anchor_tokens & concept_tokens) < 2:
        raise ValueError("concept story is not anchored in its dossier")
    if draft.legacy_connection_type is not LegacyConnectionType.NONE and not any(
        item.connection_type is draft.legacy_connection_type
        for item in dossier.franchise_connections
    ):
        raise ValueError("concept legacy route is absent from its dossier")
    allowed_titles = {
        _normalized(dossier.show_or_title),
        *(_normalized(item.connected_title) for item in dossier.franchise_connections),
    }
    allowed_characters = {
        _normalized(item.character_name) for item in dossier.named_characters
    } | {
        _normalized(character)
        for item in dossier.franchise_connections
        for character in item.characters
    }
    for source in (
        *draft.footage_request.required_sources,
        *draft.footage_request.optional_sources,
        *draft.footage_request.alternative_sources,
    ):
        if _normalized(source.show_or_title) not in allowed_titles:
            raise ValueError("concept footage title is absent from its dossier")
        if any(_normalized(value) not in allowed_characters for value in source.characters):
            raise ValueError("concept footage names a character absent from its dossier")


def _canonicalize_editorial_concepts(
    drafts: list[EditorialConceptDraftV1],
    *,
    recommended_concept_key: str,
    opportunity_id: UUID,
    selected_footage,
    evidence_index: EvidenceIndex,
    allowed_claim_ids: set[UUID],
    evidence_quality: float,
    dossier: FandomStoryDossierV1,
    concept_ids: dict[str, UUID],
    uuid_factory: Callable[[], UUID],
) -> tuple[list[EditorialConceptV1], UUID]:
    if not drafts:
        raise ValueError("concept drafts are required")
    if set(concept_ids) != {item.concept_key for item in drafts}:
        raise ValueError("concept ID allocation does not match concept drafts")
    canonical: list[EditorialConceptV1] = []
    selected_id: UUID | None = None
    for draft in drafts:
        _validate_editorial_concept_against_dossier(draft, dossier)
        trusted_evidence: list[TrustedOpportunityEvidenceReferenceV2] = []
        selected_claims: list[EvidenceClaimRecordV2] = []
        selected_sources: list[EvidenceSourceRecordV2] = []
        for selection in draft.evidence:
            claim_id = UUID(str(selection.claim_id))
            if claim_id not in allowed_claim_ids:
                raise ValueError("concept selected a claim outside the request allow-list")
            claim, source = evidence_index.joined(claim_id)
            if selection.supports_why_now != claim.supports_why_now:
                raise ValueError("concept cannot change a claim's why-now support")
            selected_claims.append(claim)
            selected_sources.append(source)
            trusted_evidence.append(
                TrustedOpportunityEvidenceReferenceV2(
                    claim_id=selection.claim_id,
                    role=selection.role,
                    supports_why_now=claim.supports_why_now,
                    independence_group=source.independence_group,
                )
            )
        _validate_editorial_concept_copy(
            draft,
            claims=selected_claims,
            sources=selected_sources,
        )
        is_selected = draft.concept_key == recommended_concept_key
        concept_id = concept_ids[draft.concept_key]
        footage = (
            selected_footage
            if is_selected
            else canonicalize_footage_request(
                draft=draft.footage_request,
                footage_request_id=uuid_factory(),
                opportunity_id=opportunity_id,
                concept_id=concept_id,
                evidence_index=evidence_index,
                allowed_claim_ids=allowed_claim_ids,
                uuid_factory=uuid_factory,
            )
        )
        if not footage.intro_leads:
            raise ValueError("concept:missing-specific-intro")
        if draft.verification_status is FootageVerificationLevel.VERIFIED and any(
            item.verification_level is not FootageVerificationLevel.VERIFIED
            for item in footage.intro_leads
        ):
            raise ValueError("concept cannot claim VERIFIED with an unverified intro")
        score = score_editorial_concept(
            draft=draft,
            footage=footage,
            evidence_quality=evidence_quality,
        )
        if score.concept_specificity < 0.50 or score.total < 0.45:
            raise ValueError("concept:quality-gate")
        if footage.concept_id != concept_id:
            raise ValueError("concept footage request lost its concept identity")
        canonical.append(
            EditorialConceptV1(
                concept_id=concept_id,
                opportunity_id=opportunity_id,
                dossier_id=dossier.dossier_id,
                concept_key=draft.concept_key,
                title=draft.title,
                central_subject=draft.central_subject,
                central_relationship=draft.central_relationship,
                core_emotion=draft.core_emotion,
                viewer_hook=draft.viewer_hook,
                why_fans_may_care=draft.why_fans_may_care,
                current_event=draft.current_event,
                legacy_or_contextual_connection=draft.legacy_or_contextual_connection,
                legacy_connection_type=draft.legacy_connection_type,
                intro_leads=footage.intro_leads,
                song_handoff_idea=draft.song_handoff_idea,
                montage_arc=draft.montage_arc,
                ending_or_payoff=draft.ending_or_payoff,
                evidence=trusted_evidence,
                verification_status=draft.verification_status,
                score=score,
                known_uncertainties=draft.known_uncertainties,
                footage_request=footage,
            )
        )
        if is_selected:
            selected_id = concept_id
    if selected_id is None:
        raise ValueError("recommended concept did not survive validation")
    canonical.sort(
        key=lambda item: (
            item.concept_id != selected_id,
            -item.score.total,
            item.title.casefold(),
        )
    )
    return canonical[:4], selected_id


def _validate_editorial_concept_copy(
    draft: EditorialConceptDraftV1,
    *,
    claims: list[EvidenceClaimRecordV2],
    sources: list[EvidenceSourceRecordV2],
) -> None:
    corpus = " ".join(
        [
            *(item.text for item in claims),
            *(item.title for item in sources),
            *(
                json.dumps(fact.model_dump(mode="json"), ensure_ascii=False)
                for item in claims
                for fact in (
                    item.episode_locator,
                    item.quote_fact,
                    item.why_now_event,
                    item.scene_fact,
                    item.cast_fact,
                )
                if fact is not None
            ),
        ]
    )
    normalized_corpus = _normalized(corpus)
    concept_copy = " ".join(
        (
            draft.title,
            draft.central_subject,
            draft.central_relationship or "",
            draft.viewer_hook,
            draft.why_fans_may_care,
            draft.current_event,
            draft.legacy_or_contextual_connection,
            draft.song_handoff_idea,
            *draft.montage_arc,
            draft.ending_or_payoff,
            *draft.known_uncertainties,
        )
    )
    for quoted in re.findall(r'["“]([^"”]{4,})["”]', concept_copy):
        if _normalized(quoted) not in normalized_corpus:
            raise ValueError("concept asserted an unsupported quote")
    allowed_episode_labels: set[str] = set()
    for claim in claims:
        locators = [claim.episode_locator]
        if claim.quote_fact is not None:
            locators.append(claim.quote_fact.episode_locator)
        if claim.scene_fact is not None:
            locators.append(claim.scene_fact.episode_locator)
        for locator in locators:
            if locator is None:
                continue
            allowed_episode_labels.update(
                {
                    f"s{locator.season_number}e{locator.episode_number}",
                    f"s{locator.season_number:02d}e{locator.episode_number:02d}",
                    f"season {locator.season_number} episode {locator.episode_number}",
                }
            )
    episode_mentions = {
        match.group(0).casefold()
        for match in re.finditer(
            r"\bs\d{1,4}e\d{1,4}\b|\bseason\s+\d{1,4}\s+episode\s+\d{1,4}\b",
            concept_copy,
            re.IGNORECASE,
        )
    }
    if not episode_mentions.issubset(allowed_episode_labels):
        raise ValueError("concept asserted an unsupported episode locator")
    connection = draft.legacy_connection_type.value
    if connection == "UNSUPPORTED_SPECULATION":
        raise ValueError("unsupported franchise speculation cannot become a concept")
    if connection in {
        "SAME_CHARACTER",
        "SAME_CANONICAL_UNIVERSE",
        "EXPLICIT_CALLBACK",
    } and not re.search(
        r"\b(?:spinoff|spin[\s-]?off|sequel|prequel|same\s+universe|returns?|"
        r"returning|reunion|callback|continuation|parent\s+series|repris(?:e|es|ing))\b",
        corpus,
        re.IGNORECASE,
    ):
        raise ValueError("concept asserted an unsupported canonical/franchise connection")


def _deterministic_primary_scene_pack_fallback(
    intent: ResearchIntentV2,
    sources: list[EvidenceSourceRecordV2],
    claims: list[EvidenceClaimRecordV2],
    *,
    now: datetime,
) -> tuple[TrendOpportunityDraftV2, FootageRequestDraftV2] | None:
    """Build a broad M1 request only after the normal primary evidence gate passes.

    This path removes, rather than invents, rejected model specificity.  It is
    limited to film/trailer/official-clip identities with one exact current
    primary and two independently owned current title-bound discussion pages.
    Every requested source remains UNKNOWN because this evidence does not prove
    a scene, quote, speaker, or footage location.
    """

    supported_kinds = {MediaKind.FILM, MediaKind.TRAILER, MediaKind.OFFICIAL_CLIP}
    if not (set(intent.media_kinds) & supported_kinds):
        return None
    cutoff = now - timedelta(days=intent.freshness_days)
    source_by_id = {UUID(str(item.source_id)): item for item in sources}
    current_signals = [
        claim
        for claim in claims
        if claim.claim_kind is EvidenceClaimKind.VIEWER_DISCUSSION
        and claim.verification is VerificationState.SECONDARY_CORROBORATED
        and claim.supports_why_now
        and (source := source_by_id.get(UUID(str(claim.source_id)))) is not None
        and (discussion_at := source.source_created_at or source.page_published_at)
        is not None
        and cutoff <= discussion_at <= now + timedelta(minutes=5)
    ]
    candidates: list[
        tuple[
            datetime,
            int,
            str,
            EvidenceClaimRecordV2,
            EvidenceSourceRecordV2,
            list[EvidenceClaimRecordV2],
        ]
    ] = []
    for primary in claims:
        primary_source = source_by_id.get(UUID(str(primary.source_id)))
        event = primary.why_now_event
        if (
            primary_source is None
            or primary.verification is not VerificationState.PRIMARY_VERIFIED
            or primary.claim_kind not in {EvidenceClaimKind.WHY_NOW, EvidenceClaimKind.OFFICIAL_CLIP}
            or not primary.supports_why_now
            or primary.event_or_release_at is None
            or event is None
            or event.media_identity.media_kind not in supported_kinds
            or event.media_identity.media_kind not in intent.media_kinds
            or not (cutoff <= primary.event_or_release_at <= now + timedelta(minutes=5))
        ):
            continue
        show_or_title = event.media_identity.show_or_title
        relevant = [
            claim
            for claim in current_signals
            if _source_matches_show(
                source_by_id[UUID(str(claim.source_id))], show_or_title
            )
        ]
        signal_groups = {
            source_by_id[UUID(str(claim.source_id))].independence_group
            for claim in relevant
        }
        all_groups = {primary_source.independence_group, *signal_groups}
        if len(relevant) < 2 or len(signal_groups) < 2 or len(all_groups) < 3:
            continue
        candidates.append(
            (
                primary.event_or_release_at,
                len(signal_groups),
                show_or_title,
                primary,
                primary_source,
                relevant,
            )
        )
    if not candidates:
        return None

    candidates.sort(
        key=lambda item: (-item[0].timestamp(), -item[1], _normalized(item[2]))
    )
    _, _, show_or_title, primary, _, relevant = candidates[0]
    assert primary.why_now_event is not None
    ordered_signals = sorted(
        relevant,
        key=lambda claim: (
            -(
                source_by_id[UUID(str(claim.source_id))].source_created_at
                or source_by_id[UUID(str(claim.source_id))].page_published_at
                or cutoff
            ).timestamp(),
            source_by_id[UUID(str(claim.source_id))].independence_group,
            claim.text.casefold(),
        ),
    )
    selected_signals: list[EvidenceClaimRecordV2] = []
    selected_groups: set[str] = set()
    for signal in ordered_signals:
        group = source_by_id[UUID(str(signal.source_id))].independence_group
        if group in selected_groups:
            continue
        selected_groups.add(group)
        selected_signals.append(signal)
        if len(selected_signals) == 4:
            break
    if len(selected_signals) < 2 or len(selected_groups) < 2:
        return None

    media_kind = primary.why_now_event.media_identity.media_kind
    identity = primary.why_now_event.media_identity
    focus = {
        MediaKind.FILM: "current release discussion",
        MediaKind.TRAILER: "current trailer discussion",
        MediaKind.OFFICIAL_CLIP: "current official clip discussion",
    }[media_kind]
    evidence = [
        OpportunityEvidenceSelectionV2(
            claim_id=primary.claim_id,
            role=EvidenceRole.PRIMARY_WHY_NOW,
            supports_why_now=True,
        ),
        *[
            OpportunityEvidenceSelectionV2(
                claim_id=claim.claim_id,
                role=EvidenceRole.QUALITATIVE_SIGNAL,
                supports_why_now=True,
            )
            for claim in selected_signals
        ],
    ]
    opportunity = TrendOpportunityDraftV2(
        media_kind=media_kind,
        media_identity=identity,
        title=f"{show_or_title}: {focus}"[:500],
        focus=OpportunityFocus(characters=[], relationship_or_topic=focus),
        why_now=primary.text,
        what_viewers_are_discussing="; ".join(
            claim.text for claim in selected_signals
        )[:2_000],
        creative_hook=(
            f"Inspect supplied {show_or_title} material against the current cited discussions."
        ),
        emotional_edit_direction=(
            "Use the verified current event as context, then let supplied local footage establish "
            "the actual emotional setup, montage, and payoff."
        ),
        evidence=evidence,
        confidence=0.7,
        caveats=[
            "No exact scene, quote, speaker, or footage location was verified; request broad local footage."
        ],
    )
    supporting_ids = [primary.claim_id, *[claim.claim_id for claim in selected_signals]]
    required_key = "current_scene_pack"
    required = RequestedSourceDraftV2(
        source_key=required_key,
        priority=1,
        acquisition_effort=2,
        asset_kind=SourceAcquisitionKind.SCENE_PACK,
        show_or_title=show_or_title,
        characters=[],
        relationship_or_topic=focus,
        scene_or_moment=f"Any relevant {focus} material; the exact scene is unknown.",
        purposes=[SourcePurpose.INTRO, SourcePurpose.MONTAGE, SourcePurpose.PAYOFF],
        verification_level=FootageVerificationLevel.UNKNOWN,
        source_quality_summary="The exact scene and source location are unverified.",
        supporting_claim_ids=supporting_ids,
        quote=None,
        why_it_matters_emotionally=(
            "This is a broad inspection target; no specific emotional beat is asserted."
        ),
        search_queries=[f"{show_or_title} {focus} scene pack"[:500]],
    )
    optional_sources: list[RequestedSourceDraftV2] = []
    alternative_sources: list[RequestedSourceDraftV2] = []
    if intent.spoiler_policy is not SpoilerPolicy.AVOID:
        optional_sources.append(
            RequestedSourceDraftV2(
                source_key="official_trailer_optional",
                priority=1,
                acquisition_effort=1,
                asset_kind=SourceAcquisitionKind.OFFICIAL_TRAILER,
                show_or_title=show_or_title,
                characters=[],
                relationship_or_topic=focus,
                scene_or_moment=f"Any relevant {focus} material; the exact moment is unknown.",
                purposes=[SourcePurpose.INTRO, SourcePurpose.OPTIONAL_CALLBACK],
                verification_level=FootageVerificationLevel.UNKNOWN,
                source_quality_summary="Trailer availability and exact moments are unverified.",
                supporting_claim_ids=supporting_ids,
                quote=None,
                why_it_matters_emotionally=(
                    "This optional promotional source may add context after local inspection."
                ),
                search_queries=[f"{show_or_title} official trailer"[:500]],
            )
        )
        alternative_sources.append(
            RequestedSourceDraftV2(
                source_key="individual_scenes_alternative",
                priority=1,
                acquisition_effort=2,
                asset_kind=SourceAcquisitionKind.INDIVIDUAL_SCENES,
                show_or_title=show_or_title,
                characters=[],
                relationship_or_topic=focus,
                scene_or_moment=f"Any relevant {focus} material; the exact scenes are unknown.",
                purposes=[SourcePurpose.INTRO, SourcePurpose.MONTAGE, SourcePurpose.PAYOFF],
                verification_level=FootageVerificationLevel.UNKNOWN,
                source_quality_summary="Exact scenes and source locations are unverified.",
                supporting_claim_ids=supporting_ids,
                quote=None,
                why_it_matters_emotionally=(
                    "This alternative keeps the request narrow while leaving exact beats unasserted."
                ),
                search_queries=[f"{show_or_title} {focus} scenes"[:500]],
                replaces_required_source_keys=[required_key],
            )
        )
    footage = FootageRequestDraftV2(
        summary="Broad evidence-bound source request with no invented scene specificity.",
        natural_request=NaturalFootageRequestV2(
            best=f"Give me a {show_or_title} scene pack focused on {focus}.",
            minimum=f"A focused {show_or_title} scene pack is the smallest useful set.",
            alternative=(
                f"If that is easier, give me individual {show_or_title} scenes focused on {focus}."
                if alternative_sources
                else None
            ),
            optional_improvement=(
                f"If you have it, an official {show_or_title} trailer would add context."
                if optional_sources
                else None
            ),
        ),
        required_sources=[required],
        optional_sources=optional_sources,
        alternative_sources=alternative_sources,
        minimum_useful_source_keys=[required_key],
        smallest_useful_set_reason=(
            "One focused scene pack is useful without requesting a whole film or asserting an unverified scene."
        ),
        intro_leads=[],
        search_queries=[f"{show_or_title} {focus} scene pack"[:500]],
        warnings=[
            "The current evidence does not verify a scene, quote, speaker, or footage location."
        ],
    )
    return opportunity, footage


def _best_metadata_episode_scene_lead(
    *,
    show_or_title: str,
    locator,
    selected_signals: list[EvidenceClaimRecordV2],
    claims: list[EvidenceClaimRecordV2],
    source_by_id: dict[UUID, EvidenceSourceRecordV2],
    cutoff: datetime,
    now: datetime,
) -> EvidenceClaimRecordV2 | None:
    """Choose a scene lead only from a qualified current discussion source."""

    signal_source_ids = {
        UUID(str(claim.source_id)) for claim in selected_signals
    }
    candidates: list[tuple[int, EvidenceClaimRecordV2]] = []
    for claim in claims:
        fact = claim.scene_fact
        source = source_by_id.get(UUID(str(claim.source_id)))
        fact_locator = fact.episode_locator if fact is not None else None
        if (
            fact is None
            or fact_locator is None
            or source is None
            or UUID(str(claim.source_id)) not in signal_source_ids
            or claim.claim_kind is not EvidenceClaimKind.SCENE_CONTEXT
            or claim.verification
            in {VerificationState.STALE, VerificationState.RETRACTED}
            or _normalized(fact.show_or_title) != _normalized(show_or_title)
            or _normalized(fact_locator.show_or_title) != _normalized(locator.show_or_title)
            or fact_locator.season_number != locator.season_number
            or fact_locator.episode_number != locator.episode_number
            or (
                locator.episode_title is not None
                and fact_locator.episode_title is not None
                and _normalized(fact_locator.episode_title)
                != _normalized(locator.episode_title)
            )
            or (
                source.source_created_at or source.page_published_at
            )
            is None
        ):
            continue
        source_at = source.source_created_at or source.page_published_at
        assert source_at is not None
        if not cutoff <= source_at <= now + timedelta(minutes=5):
            continue
        description = _normalized(fact.description)
        specificity = (
            (20 if fact.characters else 0)
            + sum(
                5
                for token in (
                    "ending",
                    "death",
                    "kiss",
                    "breakup",
                    "proposal",
                    "confession",
                    "reunion",
                    "confrontation",
                    "betrayal",
                    "rescue",
                    "escape",
                    "twist",
                    "reveal",
                    "timeline",
                )
                if token in description
            )
        )
        candidates.append((specificity, claim))
    if not candidates:
        return None
    candidates.sort(
        key=lambda item: (-item[0], item[1].text.casefold())
    )
    return candidates[0][1]


def _scene_character_cast_support(
    scene_claim: EvidenceClaimRecordV2,
    claims: list[EvidenceClaimRecordV2],
    *,
    source_by_id: dict[UUID, EvidenceSourceRecordV2],
) -> tuple[list[str], list[EvidenceClaimRecordV2]]:
    """Retain scene characters only when trusted TVmaze cast facts map them."""

    fact = scene_claim.scene_fact
    if fact is None:
        return [], []
    selected_characters: list[str] = []
    selected_claims: list[EvidenceClaimRecordV2] = []
    for character in fact.characters[:2]:
        normalized_character = _normalized(character)
        match = next(
            (
                claim
                for claim in claims
                if claim.cast_fact is not None
                and (source := source_by_id.get(UUID(str(claim.source_id))))
                is not None
                and claim.claim_kind is EvidenceClaimKind.CAST_IDENTITY
                and claim.verification
                is VerificationState.SECONDARY_CORROBORATED
                and source.provider == "tvmaze"
                and source.policy_class == "tvmaze-metadata-v1"
                and _normalized(claim.cast_fact.show_or_title)
                == _normalized(fact.show_or_title)
                and normalized_character
                in {
                    _normalized(value)
                    for value in re.split(
                        r"\s*/\s*|\s*\|\s*",
                        claim.cast_fact.character_name,
                    )
                }
            ),
            None,
        )
        if match is not None:
            selected_characters.append(character)
            selected_claims.append(match)
    return selected_characters, selected_claims


def _deterministic_metadata_scene_pack_fallback(
    intent: ResearchIntentV2,
    sources: list[EvidenceSourceRecordV2],
    claims: list[EvidenceClaimRecordV2],
    *,
    now: datetime,
    excluded_titles: frozenset[str] = frozenset(),
) -> tuple[TrendOpportunityDraftV2, FootageRequestDraftV2] | None:
    """Build the narrow approved TV metadata fallback without creative invention.

    It requires exact current TVmaze episode identity plus two current,
    independently owned, title-bound discussion sources. A distinct, bounded
    SCENE_CONTEXT claim from one of those same sources may produce a
    LIKELY_INFERRED individual-scene request. Without that structured claim the
    footage request remains a broad UNKNOWN scene pack; metadata alone cannot
    place a discussion, scene, quote, or speaker inside the episode.
    """

    if MediaKind.TV_EPISODE not in intent.media_kinds:
        return None
    cutoff = now - timedelta(days=intent.freshness_days)
    source_by_id = {UUID(str(item.source_id)): item for item in sources}
    current_signals = [
        claim
        for claim in claims
        if claim.claim_kind is EvidenceClaimKind.VIEWER_DISCUSSION
        and claim.verification is VerificationState.SECONDARY_CORROBORATED
        and claim.supports_why_now
        and (source := source_by_id.get(UUID(str(claim.source_id)))) is not None
        and (discussion_at := source.source_created_at or source.page_published_at)
        is not None
        and cutoff <= discussion_at <= now + timedelta(minutes=5)
    ]
    candidates: list[
        tuple[
            datetime,
            int,
            str,
            EvidenceClaimRecordV2,
            EvidenceSourceRecordV2,
            list[EvidenceClaimRecordV2],
        ]
    ] = []
    for metadata_claim in claims:
        metadata_source = source_by_id.get(UUID(str(metadata_claim.source_id)))
        locator = metadata_claim.episode_locator
        if (
            metadata_source is None
            or metadata_source.provider != "tvmaze"
            or metadata_source.policy_class != "tvmaze-metadata-v1"
            or metadata_claim.claim_kind is not EvidenceClaimKind.EPISODE_IDENTITY
            or metadata_claim.verification
            is not VerificationState.SECONDARY_CORROBORATED
            or metadata_claim.supports_why_now
            or locator is None
            or metadata_claim.event_or_release_at is None
            or not (
                cutoff
                <= metadata_claim.event_or_release_at
                <= now + timedelta(minutes=5)
            )
            or _normalized(locator.show_or_title) in excluded_titles
        ):
            continue
        relevant = [
            claim
            for claim in current_signals
            if _source_matches_show(
                source_by_id[UUID(str(claim.source_id))], locator.show_or_title
            )
        ]
        signal_groups = {
            source_by_id[UUID(str(claim.source_id))].independence_group
            for claim in relevant
        }
        all_groups = {metadata_source.independence_group, *signal_groups}
        if len(signal_groups) < 2 or len(all_groups) < 3:
            continue
        candidates.append(
            (
                metadata_claim.event_or_release_at,
                len(signal_groups),
                locator.show_or_title,
                metadata_claim,
                metadata_source,
                relevant,
            )
        )
    if not candidates:
        return None

    candidates.sort(
        key=lambda item: (-item[0].timestamp(), -item[1], _normalized(item[2]))
    )
    _, _, show_or_title, metadata_claim, metadata_source, relevant = candidates[0]
    assert metadata_claim.episode_locator is not None

    ordered_signals = sorted(
        relevant,
        key=lambda claim: (
            -(
                source_by_id[UUID(str(claim.source_id))].source_created_at
                or source_by_id[UUID(str(claim.source_id))].page_published_at
                or cutoff
            ).timestamp(),
            source_by_id[UUID(str(claim.source_id))].independence_group,
            claim.text.casefold(),
        ),
    )
    selected_signals: list[EvidenceClaimRecordV2] = []
    selected_groups: set[str] = set()
    for signal in ordered_signals:
        group = source_by_id[UUID(str(signal.source_id))].independence_group
        if group in selected_groups:
            continue
        selected_groups.add(group)
        selected_signals.append(signal)
        if len(selected_signals) == 4:
            break
    if len(selected_groups) < 2:
        return None

    locator = metadata_claim.episode_locator
    scene_claim = _best_metadata_episode_scene_lead(
        show_or_title=show_or_title,
        locator=locator,
        selected_signals=selected_signals,
        claims=claims,
        source_by_id=source_by_id,
        cutoff=cutoff,
        now=now,
    )
    if scene_claim is not None and scene_claim.scene_fact is not None:
        scene_fact = scene_claim.scene_fact
        scene_characters, scene_cast_claims = _scene_character_cast_support(
            scene_claim,
            claims,
            source_by_id=source_by_id,
        )
        focus = scene_fact.relationship_or_topic or scene_fact.description
        identity = MediaIdentityV2(
            media_kind=MediaKind.TV_EPISODE,
            show_or_title=locator.show_or_title,
            season_number=locator.season_number,
            episode_number=locator.episode_number,
            episode_title=locator.episode_title,
        )
        evidence = [
            OpportunityEvidenceSelectionV2(
                claim_id=metadata_claim.claim_id,
                role=EvidenceRole.CONTEXT,
                supports_why_now=False,
            ),
            *[
                OpportunityEvidenceSelectionV2(
                    claim_id=claim.claim_id,
                    role=EvidenceRole.QUALITATIVE_SIGNAL,
                    supports_why_now=True,
                )
                for claim in selected_signals
            ],
            OpportunityEvidenceSelectionV2(
                claim_id=scene_claim.claim_id,
                role=EvidenceRole.CONTEXT,
                supports_why_now=False,
            ),
            *[
                OpportunityEvidenceSelectionV2(
                    claim_id=claim.claim_id,
                    role=EvidenceRole.CONTEXT,
                    supports_why_now=False,
                )
                for claim in scene_cast_claims
            ],
        ]
        opportunity = TrendOpportunityDraftV2(
            media_kind=MediaKind.TV_EPISODE,
            media_identity=identity,
            title=f"{show_or_title}: {focus}"[:500],
            focus=OpportunityFocus(
                characters=scene_characters,
                relationship_or_topic=focus,
            ),
            why_now=metadata_claim.text,
            what_viewers_are_discussing="; ".join(
                claim.text for claim in selected_signals
            )[:2_000],
            creative_hook=(
                f"Inspect supplied footage around this provisional source-bound scene lead: {scene_fact.description}."
            ),
            emotional_edit_direction=(
                "Use the lead as an intro or payoff inspection target, but let supplied local footage confirm the exact action, timing, and emotional beat."
            ),
            evidence=evidence,
            confidence=0.58,
            caveats=[
                "The exact episode identity is current metadata; the scene selector is LIKELY / INFERRED from a current episode-bound article, not verified footage."
            ],
        )
        source_key = "episode_scene_lead"
        query = (
            f"{show_or_title} season {locator.season_number} episode "
            f"{locator.episode_number} {focus} scenes"
        )[:500]
        supporting_ids = [
            metadata_claim.claim_id,
            *[claim.claim_id for claim in selected_signals],
            scene_claim.claim_id,
            *[claim.claim_id for claim in scene_cast_claims],
        ]
        requested_source = RequestedSourceDraftV2(
            source_key=source_key,
            priority=1,
            acquisition_effort=2,
            asset_kind=SourceAcquisitionKind.INDIVIDUAL_SCENES,
            show_or_title=show_or_title,
            characters=scene_characters,
            relationship_or_topic=focus,
            scene_or_moment=scene_fact.description,
            purposes=[
                SourcePurpose.INTRO,
                SourcePurpose.MONTAGE,
                SourcePurpose.PAYOFF,
            ],
            verification_level=FootageVerificationLevel.LIKELY_INFERRED,
            source_quality_summary=(
                "A current exact-episode article supports this provisional scene selector; supplied local footage must confirm it."
            ),
            supporting_claim_ids=supporting_ids,
            quote=None,
            why_it_matters_emotionally=(
                "This is a bounded scene-level inspection target rather than a whole episode or generic show pack."
            ),
            search_queries=[query],
        )
        official_video_sources = _official_video_source_drafts(
            show_or_title,
            claims,
            source_by_id=source_by_id,
        )
        footage = FootageRequestDraftV2(
            summary="Scene-level request derived from qualified current evidence.",
            natural_request=render_natural_request(
                required_sources=[requested_source],
                optional_sources=official_video_sources,
                alternative_sources=[],
            ),
            required_sources=[requested_source],
            optional_sources=official_video_sources,
            alternative_sources=[],
            minimum_useful_source_keys=[source_key],
            smallest_useful_set_reason=(
                "One evidence-bound scene target is smaller and more actionable than a whole episode or generic scene pack."
            ),
            intro_leads=[
                IntroMaterialLeadDraftV2(
                    source_key=source_key,
                    moment_description=scene_fact.description,
                    why_it_might_lead_into_montage=(
                        "This provisional scene-level beat may establish context before a montage if the supplied footage confirms it."
                    ),
                    verification_level=FootageVerificationLevel.LIKELY_INFERRED,
                    supporting_claim_ids=[scene_claim.claim_id],
                )
            ],
            search_queries=[query],
            warnings=[
                "The scene selector is provisional; no exact outcome, quote, speaker, timestamp, or footage location is asserted."
            ],
        )
        return opportunity, footage

    focus_characters, focus_claims = _fallback_character_focus(
        show_or_title,
        selected_signals,
        claims,
        source_by_id=source_by_id,
    )
    focus = (
        _join_character_focus(focus_characters)
        if focus_characters
        else _fallback_focus_label(
            show_or_title,
            selected_signals,
            source_by_id=source_by_id,
        )
    )
    identity = MediaIdentityV2(
        media_kind=MediaKind.TV_EPISODE,
        show_or_title=locator.show_or_title,
        season_number=locator.season_number,
        episode_number=locator.episode_number,
        episode_title=locator.episode_title,
    )
    evidence = [
        OpportunityEvidenceSelectionV2(
            claim_id=metadata_claim.claim_id,
            role=EvidenceRole.CONTEXT,
            supports_why_now=False,
        ),
        *[
            OpportunityEvidenceSelectionV2(
                claim_id=claim.claim_id,
                role=EvidenceRole.QUALITATIVE_SIGNAL,
                supports_why_now=True,
            )
            for claim in selected_signals
        ],
        *[
            OpportunityEvidenceSelectionV2(
                claim_id=claim.claim_id,
                role=EvidenceRole.CONTEXT,
                supports_why_now=False,
            )
            for claim in focus_claims
        ],
    ]
    opportunity = TrendOpportunityDraftV2(
        media_kind=MediaKind.TV_EPISODE,
        media_identity=identity,
        title=f"{show_or_title}: {focus}"[:500],
        focus=OpportunityFocus(
            characters=focus_characters,
            relationship_or_topic=focus,
        ),
        why_now=metadata_claim.text,
        what_viewers_are_discussing="; ".join(
            claim.text for claim in selected_signals
        )[:2_000],
        creative_hook=(
            f"Inspect a supplied {show_or_title} scene pack for material connected to {focus}."
        ),
        emotional_edit_direction=(
            "Treat the episode listing only as a timing lead and let later local-footage "
            "analysis decide the actual setup, montage, and payoff."
        ),
        evidence=evidence,
        confidence=0.6,
        caveats=[
            "No official why-now proof or exact scene was verified; request broad local footage."
        ],
    )
    source_key = "current_scene_pack"
    query = f"{show_or_title} {focus} scene pack"[:500]
    supporting_ids = [
        metadata_claim.claim_id,
        *[claim.claim_id for claim in selected_signals],
        *[claim.claim_id for claim in focus_claims],
    ]
    requested_source = RequestedSourceDraftV2(
        source_key=source_key,
        priority=1,
        acquisition_effort=2,
        asset_kind=SourceAcquisitionKind.SCENE_PACK,
        show_or_title=show_or_title,
        characters=focus_characters,
        relationship_or_topic=focus,
        scene_or_moment=(
            f"Any relevant {focus} material; the exact scene is unknown."
        ),
        purposes=[SourcePurpose.INTRO, SourcePurpose.MONTAGE, SourcePurpose.PAYOFF],
        verification_level=FootageVerificationLevel.UNKNOWN,
        source_quality_summary=(
            "Exact current episode metadata and independent discussion sources support "
            "the topic, but not a particular scene."
        ),
        supporting_claim_ids=supporting_ids,
        quote=None,
        why_it_matters_emotionally=(
            "This broad scene pack is an inspection target; no exact emotional beat is asserted."
        ),
        search_queries=[query],
    )
    official_video_sources = _official_video_source_drafts(
        show_or_title,
        claims,
        source_by_id=source_by_id,
    )
    footage = FootageRequestDraftV2(
        summary="Broad scene-pack request derived only from qualified current evidence.",
        natural_request=render_natural_request(
            required_sources=[requested_source],
            optional_sources=official_video_sources,
            alternative_sources=[],
        ),
        required_sources=[requested_source],
        optional_sources=official_video_sources,
        alternative_sources=[],
        minimum_useful_source_keys=[source_key],
        smallest_useful_set_reason=(
            "One focused scene pack avoids requesting an unverified episode scene or a whole season."
        ),
        intro_leads=[],
        search_queries=[query],
        warnings=[
            "The current evidence does not verify a specific scene, quote, speaker, or intro moment."
        ],
    )
    return opportunity, footage


def _official_video_source_drafts(
    show_or_title: str,
    claims: list[EvidenceClaimRecordV2],
    *,
    source_by_id: dict[UUID, EvidenceSourceRecordV2],
) -> list[RequestedSourceDraftV2]:
    """Expose reviewed official-video links as honest optional source leads.

    The YouTube adapter verifies channel identity, exact title binding, upload
    date, and canonical URL.  A source-owned scene label can therefore be
    VERIFIED as a discovery label; it does not claim that M1 watched or
    downloaded the video.  Generic trailers/clips remain UNKNOWN at the scene
    level while still carrying their clickable authoritative source record.
    """

    eligible: list[
        tuple[datetime, EvidenceClaimRecordV2, EvidenceSourceRecordV2]
    ] = []
    for claim in claims:
        source = source_by_id.get(UUID(str(claim.source_id)))
        event = claim.why_now_event
        if (
            source is None
            or source.provider != "youtube"
            or source.policy_class != "youtube-public-metadata-v1"
            or claim.claim_kind is not EvidenceClaimKind.OFFICIAL_CLIP
            or claim.verification is not VerificationState.PRIMARY_VERIFIED
            or event is None
            or _normalized(event.media_identity.show_or_title)
            != _normalized(show_or_title)
            or event.media_identity.media_kind
            not in {MediaKind.OFFICIAL_CLIP, MediaKind.TRAILER}
        ):
            continue
        published_at = (
            source.source_created_at
            or source.page_published_at
            or claim.event_or_release_at
        )
        if published_at is None:
            continue
        eligible.append((published_at, claim, source))

    drafts: list[RequestedSourceDraftV2] = []
    for priority, (_, claim, source) in enumerate(
        sorted(
            eligible,
            key=lambda item: (-item[0].timestamp(), item[2].title.casefold()),
        )[:3],
        start=1,
    ):
        assert claim.why_now_event is not None
        scene = claim.scene_fact
        is_trailer = (
            claim.why_now_event.media_identity.media_kind is MediaKind.TRAILER
        )
        asset_kind = (
            SourceAcquisitionKind.OFFICIAL_TRAILER
            if is_trailer
            else SourceAcquisitionKind.OFFICIAL_CLIP
        )
        focus = (
            scene.relationship_or_topic or scene.description
            if scene is not None
            else "official promotional footage"
        )
        scene_or_moment = (
            scene.description
            if scene is not None
            else "Any relevant official promotional material; the exact scene is unknown."
        )
        verification = (
            FootageVerificationLevel.VERIFIED
            if scene is not None
            else FootageVerificationLevel.UNKNOWN
        )
        drafts.append(
            RequestedSourceDraftV2(
                source_key=f"official_video_{priority}",
                priority=priority,
                acquisition_effort=1,
                asset_kind=asset_kind,
                show_or_title=show_or_title,
                characters=list(scene.characters) if scene is not None else [],
                # This optional hosted upload may provide a different scene
                # option from the opportunity's primary creative topic. Keep
                # the source-owned label in the independently verified moment
                # field without letting it rewrite that opportunity focus.
                relationship_or_topic=None,
                scene_or_moment=scene_or_moment,
                purposes=[SourcePurpose.INTRO, SourcePurpose.MONTAGE],
                verification_level=verification,
                source_quality_summary=(
                    "Reviewed official-channel metadata verifies this exact video link and source-owned scene label."
                    if scene is not None
                    else "Reviewed official-channel metadata verifies this exact promotional-video link, but not a specific scene."
                ),
                supporting_claim_ids=[claim.claim_id],
                quote=None,
                why_it_matters_emotionally=(
                    "Use the official hosted video as a quick preview and acquisition lead; confirm rights and the actual emotional beat before editing."
                ),
                search_queries=[f"{show_or_title} {focus} official video"[:500]],
            )
        )
    return drafts


def _attach_official_video_sources(
    footage: FootageRequestDraftV2,
    *,
    show_or_title: str,
    claims: list[EvidenceClaimRecordV2],
    source_by_id: dict[UUID, EvidenceSourceRecordV2],
) -> FootageRequestDraftV2:
    """Attach locally verified official-video leads to any valid synthesis draft.

    The model is not trusted to notice or reproduce source links. The host adds
    only normalized YouTube claims already present in the synthesis allow-list,
    preserves model-authored optional sources, and deterministically resolves
    source-key and priority constraints.
    """

    discovered = _official_video_source_drafts(
        show_or_title,
        claims,
        source_by_id=source_by_id,
    )
    if not discovered:
        return footage
    existing_claim_ids = {
        UUID(str(claim_id))
        for source in footage.optional_sources
        for claim_id in source.supporting_claim_ids
    }
    existing_keys = {
        source.source_key
        for source in [
            *footage.required_sources,
            *footage.optional_sources,
            *footage.alternative_sources,
        ]
    }
    additions: list[RequestedSourceDraftV2] = []
    for source in discovered:
        claim_ids = {UUID(str(value)) for value in source.supporting_claim_ids}
        if claim_ids and claim_ids.issubset(existing_claim_ids):
            continue
        suffix = len(additions) + 1
        source_key = f"host_official_video_{suffix}"
        while source_key in existing_keys:
            suffix += 1
            source_key = f"host_official_video_{suffix}"
        existing_keys.add(source_key)
        additions.append(
            source.model_copy(
                update={
                    "source_key": source_key,
                    "priority": len(footage.optional_sources) + len(additions) + 1,
                }
            )
        )
        existing_claim_ids.update(claim_ids)
        if len(footage.optional_sources) + len(additions) >= 30:
            break
    if not additions:
        return footage
    natural_request = footage.natural_request
    if natural_request.optional_improvement is None:
        natural_request = natural_request.model_copy(
            update={
                "optional_improvement": (
                    "If useful, review the linked official hosted video as a quick "
                    "preview and acquisition lead; confirm rights before editing."
                )
            }
        )
    return footage.model_copy(
        update={
            "natural_request": natural_request,
            "optional_sources": [*footage.optional_sources, *additions],
        }
    )


def _fallback_focus_label(
    show_or_title: str,
    signals: list[EvidenceClaimRecordV2],
    *,
    source_by_id: dict[UUID, EvidenceSourceRecordV2],
) -> str:
    """Choose a concise category, never article-headline prose, from a title."""

    direct = [
        claim
        for claim in signals
        if _normalized(show_or_title)
        in _normalized(source_by_id[UUID(str(claim.source_id))].title)
    ]
    pool = direct or signals
    editorial_terms = re.compile(
        r"\b(?:relationship|romance|romantic|love|couple|triangle|ending|finale|choice|"
        r"detective|mystery|crime|performance|starring|cast|actor|nostalgia|reunion|legacy)\b",
        re.IGNORECASE,
    )
    selected = sorted(
        pool,
        key=lambda claim: (
            0 if editorial_terms.search(claim.text) else 1,
            len(claim.text),
            claim.text.casefold(),
        ),
    )[0]
    value = " ".join(
        (
            selected.text,
            source_by_id[UUID(str(selected.source_id))].title,
        )
    )
    categories = (
        (r"\b(?:relationship|romance|romantic|love|couple|triangle)\b", "current relationship discussion"),
        (r"\b(?:ending|finale|choice)\b", "current ending discussion"),
        (r"\b(?:detective|mystery|crime|case)\b", "current mystery discussion"),
        (r"\b(?:nostalgia|nostalgic|reunion|legacy)\b", "current nostalgia discussion"),
        (r"\b(?:performance|starring|cast|actor)\b", "current character discussion"),
    )
    for pattern, label in categories:
        if re.search(pattern, value, flags=re.IGNORECASE):
            return label
    return "current character discussion"


def _fallback_character_focus(
    show_or_title: str,
    signals: list[EvidenceClaimRecordV2],
    claims: list[EvidenceClaimRecordV2],
    *,
    source_by_id: dict[UUID, EvidenceSourceRecordV2],
) -> tuple[list[str], list[EvidenceClaimRecordV2]]:
    """Map discussion-mentioned performers/characters through trusted cast facts.

    A publisher headline may name an actor without naming the character.  The
    title-bound discussion establishes relevance, while an exact TVmaze cast
    fact supplies the actor-to-character mapping.  This deterministic join can
    request a character scene pack, but it never claims that a particular scene
    exists or that the character appears in the current episode.
    """

    mention_corpus = " ".join(
        value
        for signal in signals
        for value in (
            signal.text,
            source_by_id[UUID(str(signal.source_id))].title,
        )
    )
    normalized_corpus = f" {_normalized_words(mention_corpus)} "
    candidates: list[tuple[int, str, EvidenceClaimRecordV2]] = []
    for claim in claims:
        fact = claim.cast_fact
        source = source_by_id.get(UUID(str(claim.source_id)))
        if (
            fact is None
            or source is None
            or claim.claim_kind is not EvidenceClaimKind.CAST_IDENTITY
            or claim.verification is not VerificationState.SECONDARY_CORROBORATED
            or claim.supports_why_now
            or source.provider != "tvmaze"
            or source.policy_class != "tvmaze-metadata-v1"
            or _normalized(fact.show_or_title) != _normalized(show_or_title)
        ):
            continue
        positions = [
            normalized_corpus.find(f" {_normalized_words(value)} ")
            for value in (fact.character_name, fact.performer_name)
            if _normalized_words(value)
        ]
        positions = [position for position in positions if position >= 0]
        if not positions:
            continue
        character = re.split(r"\s*/\s*", fact.character_name, maxsplit=1)[0].strip()
        if character:
            candidates.append((min(positions), character, claim))

    characters: list[str] = []
    matched_claims: list[EvidenceClaimRecordV2] = []
    seen: set[str] = set()
    for _, character, claim in sorted(
        candidates,
        key=lambda item: (item[0], _normalized(item[1]), str(item[2].claim_id)),
    ):
        key = _normalized(character)
        if key in seen:
            continue
        seen.add(key)
        characters.append(character)
        matched_claims.append(claim)
        if len(characters) == 2:
            break
    return characters, matched_claims


def _join_character_focus(characters: list[str]) -> str:
    if len(characters) == 1:
        return characters[0]
    if len(characters) == 2:
        return f"{characters[0]} and {characters[1]}"
    return ", ".join(characters)


def _normalized_words(value: str) -> str:
    return " ".join(
        re.sub(
            r"[^a-z0-9]+",
            " ",
            unicodedata.normalize("NFKC", value).casefold(),
        ).split()
    )


def _validate_pair_against_intent(
    intent: ResearchIntentV2,
    opportunity: TrendOpportunityDraftV2,
    footage: FootageRequestDraftV2,
    *,
    evidence_index: EvidenceIndex | None = None,
    allow_cross_title_sources: bool = False,
) -> None:
    if opportunity.media_kind not in intent.media_kinds:
        raise ValueError("synthesized media kind is outside the intent")
    displayed = json.dumps(
        {
            "opportunity": opportunity.model_dump(mode="json"),
            "footage": footage.model_dump(mode="json"),
        },
        ensure_ascii=False,
    )
    if violates_exclusions(displayed, intent):
        raise ValueError("synthesized recommendation violates an explicit exclusion")
    if evidence_index is not None:
        selected_claims = [
            evidence_index.joined(UUID(str(item.claim_id)))[0]
            for item in opportunity.evidence
        ]
        if not _requested_audience_has_minimum_support(
            intent,
            opportunity.media_identity.show_or_title,
            selected_claims,
            evidence_index.sources,
        ):
            raise ValueError(
                "opportunity evidence does not meet the requested audience-fit evidence floor"
            )
    source_title = _normalized(opportunity.media_identity.show_or_title)
    all_sources = [
        *footage.required_sources,
        *footage.optional_sources,
        *footage.alternative_sources,
    ]
    cross_title_sources = [
        item
        for item in all_sources
        if _normalized(item.show_or_title) != source_title
    ]
    if cross_title_sources and not allow_cross_title_sources:
        raise ValueError("footage request belongs to a different title than its opportunity")
    if cross_title_sources and any(
        item.verification_level is FootageVerificationLevel.UNKNOWN
        or not item.supporting_claim_ids
        for item in cross_title_sources
    ):
        raise ValueError(
            "cross-title concept footage requires evidence-bound source identities"
        )
    requested_characters = {
        _normalized(character)
        for item in all_sources
        for character in item.characters
    }
    if any(
        _normalized(character) not in requested_characters
        for character in opportunity.focus.characters
    ):
        raise ValueError("opportunity focus characters are absent from its footage request")
    focus_characters = {
        _normalized(character) for character in opportunity.focus.characters
    }
    if any(
        not {_normalized(character) for character in item.characters}.issubset(
            focus_characters
        )
        for item in all_sources
    ):
        raise ValueError("footage request named a character outside the supported focus")
    topic_tokens = {
        token
        for token in re.sub(
            r"[^a-z0-9]+", " ", opportunity.focus.relationship_or_topic.casefold()
        ).split()
        if len(token) >= 4
        and token not in {"relationship", "character", "central", "story", "edit"}
    }
    footage_topic = _normalized(
        " ".join(
            value
            for item in all_sources
            for value in (item.relationship_or_topic or "", item.scene_or_moment)
        )
    )
    if topic_tokens and not any(token in footage_topic.split() for token in topic_tokens):
        raise ValueError("opportunity focus topic is absent from its footage request")
    for item in all_sources:
        if item.relationship_or_topic is None:
            continue
        item_tokens = {
            token
            for token in re.sub(
                r"[^a-z0-9]+", " ", item.relationship_or_topic.casefold()
            ).split()
            if len(token) >= 4
        }
        if item_tokens and topic_tokens and not (item_tokens & topic_tokens):
            raise ValueError("footage request topic is outside the supported opportunity focus")
    if intent.spoiler_policy is SpoilerPolicy.AVOID and any(
        item.asset_kind
        not in {SourceAcquisitionKind.OFFICIAL_TRAILER, SourceAcquisitionKind.OFFICIAL_CLIP}
        for item in all_sources
    ):
        raise ValueError("spoiler-avoid intent permits official promotional footage only")


def _normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _footage_actionability(footage: FootageRequestDraftV2) -> float:
    required_effort = sum(item.acquisition_effort for item in footage.required_sources)
    required_count = len(footage.required_sources)
    score = 1.0 - 0.08 * max(0, required_count - 1) - 0.04 * max(
        0, required_effort - required_count
    )
    if footage.alternative_sources and min(
        item.acquisition_effort for item in footage.alternative_sources
    ) < required_effort:
        score += 0.05
    return max(0.0, min(1.0, score))


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        sanitized = _sanitize_result_diagnostic(value, max_length=500)
        key = sanitized.casefold()
        if key not in seen:
            result.append(sanitized)
            seen.add(key)
    return result[:30]


_RESULT_DIAGNOSTIC_POLICY_COLLISION = re.compile(
    r"(?:yt-dlp|yt dlp|m3u8|manifest|torrent|download|\brip\b|ripping|ripped|"
    r"bypass|defeat|circumvent|drm|paywall|cookie|auth token|"
    r"authorization header|viral|% chance)",
    re.IGNORECASE,
)


def _sanitize_result_diagnostic(value: str, *, max_length: int) -> str:
    """Keep trusted diagnostics useful without crossing the UI policy boundary.

    Adapter diagnostics can contain a reviewed page's public path. A path segment
    such as ``/manifest`` or ``/download`` is not an acquisition instruction, but
    Rust deliberately rejects those terms anywhere in user-visible result copy.
    Redact only the colliding token while preserving the bounded diagnostic.
    """

    normalized = " ".join(unicodedata.normalize("NFKC", value).split())
    sanitized = _RESULT_DIAGNOSTIC_POLICY_COLLISION.sub(
        "[policy-sensitive term omitted]", normalized
    )
    sanitized = sanitized[:max_length].rstrip()
    return sanitized or "A provider diagnostic was omitted at the trusted boundary."
