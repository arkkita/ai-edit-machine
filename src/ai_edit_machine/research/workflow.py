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
    EvidenceClaimKind,
    EvidenceClaimRecordV2,
    EvidenceSourceRecordV2,
    FootageRequestDraftV2,
    FootageVerificationLevel,
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
from .source_ownership import (
    source_record_binds_media_title,
    source_record_binds_tvmaze_show,
)
from .synthesis import ResearchSynthesizer, SynthesisProviderResult


_FEMALE_CENTERED_FOCUS = "female-centered"
_FEMALE_CENTERED_EVIDENCE = re.compile(
    r"(?:\bfemale[\s-]*(?:centered|centred|focused|led)\b|"
    r"\b(?:girls?|women|woman)\b|\b(?:mother|daughter|sister)s?\b)",
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


@dataclass(frozen=True, slots=True)
class ResearchWorkflowOutput:
    result: ResearchResultV2
    evidence_sources: tuple[EvidenceSourceRecordV2, ...]
    evidence_claims: tuple[EvidenceClaimRecordV2, ...]
    provider_batches: tuple[ProviderBatch, ...]
    synthesis: SynthesisProviderResult | None
    stage_counts: ResearchStageCounts


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
        batches: list[ProviderBatch] = []
        warnings: list[str] = []
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
        if not _could_support_recommendation(
            sources, claims, generated_at, intent
        ):
            result = _no_opportunity(
                intent,
                generated_at=generated_at,
                run_id=authoritative_run_id,
                message="No strong opportunity found under these constraints.",
                warnings=warnings,
            )
            return ResearchWorkflowOutput(
                result=result,
                evidence_sources=tuple(sources),
                evidence_claims=tuple(claims),
                provider_batches=tuple(batches),
                synthesis=None,
                stage_counts=ResearchStageCounts(
                    parsed_results=sum(len(item.evidence) for item in batches),
                    normalized_evidence=len(claims),
                    evidence_surviving_gates=0,
                    ranked_opportunities=0,
                    opportunities_returned_to_ui=0,
                ),
            )

        synthesis_sources, synthesis_claims = _select_synthesis_evidence(
            intent,
            sources,
            claims,
            now=generated_at,
        )
        if not synthesis_sources or not synthesis_claims:
            warnings.append(
                "The trusted synthesis allow-list was empty after title, media-kind, "
                "freshness, and publisher-independence checks; paid synthesis was skipped."
            )
            result = _no_opportunity(
                intent,
                generated_at=generated_at,
                run_id=authoritative_run_id,
                message="No strong opportunity found under these constraints.",
                warnings=warnings,
            )
            return ResearchWorkflowOutput(
                result=result,
                evidence_sources=tuple(sources),
                evidence_claims=tuple(claims),
                provider_batches=tuple(batches),
                synthesis=None,
                stage_counts=ResearchStageCounts(
                    parsed_results=sum(len(item.evidence) for item in batches),
                    normalized_evidence=len(claims),
                    evidence_surviving_gates=0,
                    ranked_opportunities=0,
                    opportunities_returned_to_ui=0,
                ),
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
        rejected = 0
        rejection_codes: dict[str, int] = {}
        omitted_intro_leads = 0
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
            try:
                _validate_pair_against_intent(
                    intent,
                    recommendation.opportunity,
                    recommendation.footage_request,
                    evidence_index=evidence_index,
                )
            except (ValueError, KeyError) as error:
                rejected += 1
                code = _synthesis_rejection_code("intent", error)
                rejection_codes[code] = rejection_codes.get(code, 0) + 1
                continue
            footage_draft = _attach_official_video_sources(
                recommendation.footage_request,
                show_or_title=recommendation.opportunity.media_identity.show_or_title,
                claims=synthesis_claims,
                source_by_id=synthesis_source_by_id,
            )
            opportunity_id = self._uuid_factory()
            request_id = self._uuid_factory()
            try:
                footage = canonicalize_footage_request(
                    draft=footage_draft,
                    footage_request_id=request_id,
                    opportunity_id=opportunity_id,
                    evidence_index=evidence_index,
                    allowed_claim_ids=allowed_claim_ids,
                    uuid_factory=self._uuid_factory,
                )
            except (ValueError, KeyError) as error:
                if footage_draft.intro_leads and _is_omittable_intro_lead_error(error):
                    # Intro leads are optional leaves.  A model-authored lead that
                    # cannot bind to a scene/moment claim must not erase an otherwise
                    # evidence-valid opportunity and footage request.  Retry only by
                    # deleting those leaves; no fact, certainty, or source is added.
                    omitted_intro_leads += len(footage_draft.intro_leads)
                    footage_draft = footage_draft.model_copy(
                        update={"intro_leads": []}
                    )
                    try:
                        footage = canonicalize_footage_request(
                            draft=footage_draft,
                            footage_request_id=request_id,
                            opportunity_id=opportunity_id,
                            evidence_index=evidence_index,
                            allowed_claim_ids=allowed_claim_ids,
                            uuid_factory=self._uuid_factory,
                        )
                    except (ValueError, KeyError) as retry_error:
                        rejected += 1
                        code = _synthesis_rejection_code("footage", retry_error)
                        rejection_codes[code] = rejection_codes.get(code, 0) + 1
                        continue
                else:
                    rejected += 1
                    code = _synthesis_rejection_code("footage", error)
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
                canonical_pairs.append((opportunity, footage))
            except (ValueError, KeyError) as error:
                rejected += 1
                code = _synthesis_rejection_code("opportunity", error)
                rejection_codes[code] = rejection_codes.get(code, 0) + 1
        if omitted_intro_leads:
            warnings.append(
                f"Omitted {omitted_intro_leads} optional synthesized intro lead(s) because "
                "the selected evidence did not bind the proposed moment."
            )
        canonical_pairs.sort(
            key=lambda pair: (-pair[0].score.total, pair[0].title.casefold())
        )
        canonical_pairs = canonical_pairs[: intent.max_results]

        # A valid generic UNKNOWN scene pack must not hide a smaller scene
        # selector that the host has already bound to the exact TVmaze episode
        # and a qualified current discussion source.  Build the deterministic
        # LIKELY / INFERRED pair through the same validators and replace only a
        # same-title generic pair; no evidence or certainty is added here.
        upgrade_examined_titles: set[str] = set()
        while len(upgrade_examined_titles) < intent.max_results:
            metadata_scene_upgrade = _deterministic_metadata_scene_pack_fallback(
                intent,
                synthesis_sources,
                synthesis_claims,
                now=generated_at,
                excluded_titles=frozenset(upgrade_examined_titles),
            )
            if metadata_scene_upgrade is None:
                break
            upgrade_opportunity_draft, upgrade_footage_draft = metadata_scene_upgrade
            is_specific_upgrade = any(
                source.asset_kind is SourceAcquisitionKind.INDIVIDUAL_SCENES
                and source.verification_level
                is FootageVerificationLevel.LIKELY_INFERRED
                for source in upgrade_footage_draft.required_sources
            )
            upgrade_title = _normalized(
                upgrade_opportunity_draft.media_identity.show_or_title
            )
            upgrade_examined_titles.add(upgrade_title)
            same_title_pairs = [
                pair
                for pair in canonical_pairs
                if _normalized(pair[0].media_identity.show_or_title)
                == upgrade_title
            ]
            same_title_is_specific = any(
                source.asset_kind is SourceAcquisitionKind.INDIVIDUAL_SCENES
                and source.verification_level
                is not FootageVerificationLevel.UNKNOWN
                for _, footage in same_title_pairs
                for source in footage.required_sources
            )
            if is_specific_upgrade and not same_title_is_specific:
                try:
                    _validate_pair_against_intent(
                        intent,
                        upgrade_opportunity_draft,
                        upgrade_footage_draft,
                        evidence_index=evidence_index,
                    )
                    opportunity_id = self._uuid_factory()
                    request_id = self._uuid_factory()
                    upgrade_footage = canonicalize_footage_request(
                        draft=upgrade_footage_draft,
                        footage_request_id=request_id,
                        opportunity_id=opportunity_id,
                        evidence_index=evidence_index,
                        allowed_claim_ids=allowed_claim_ids,
                        uuid_factory=self._uuid_factory,
                    )
                    upgrade_opportunity = build_trusted_opportunity(
                        draft=upgrade_opportunity_draft,
                        opportunity_id=opportunity_id,
                        footage_request_id=request_id,
                        evidence_index=evidence_index,
                        allowed_claim_ids=allowed_claim_ids,
                        now=generated_at,
                        freshness_days=intent.freshness_days,
                        footage_actionability=_footage_actionability(
                            upgrade_footage_draft
                        ),
                    )
                    canonical_pairs = [
                        pair
                        for pair in canonical_pairs
                        if _normalized(pair[0].media_identity.show_or_title)
                        != upgrade_title
                    ]
                    canonical_pairs.append((upgrade_opportunity, upgrade_footage))
                    warnings.append(
                        "Replaced a generic same-title scene pack with a smaller LIKELY / INFERRED exact-episode scene request from the same qualified evidence."
                    )
                except (ValueError, KeyError):
                    warnings.append(
                        "A provisional exact-episode scene upgrade failed trusted local validation and was omitted."
                    )
                canonical_pairs.sort(
                    key=lambda pair: (-pair[0].score.total, pair[0].title.casefold())
                )
                canonical_pairs = canonical_pairs[: intent.max_results]
        if rejected:
            bounded_codes = ", ".join(
                f"{code}={count}" for code, count in sorted(rejection_codes.items())
            )
            warnings.append(
                f"{rejected} synthesized recommendation(s) failed trusted evidence validation"
                + (f" ({bounded_codes})." if bounded_codes else ".")
            )
        # Synthesis is allowed to phrase the creative direction, but it must
        # not collapse a multi-title evidence slate to one card. Fill any
        # missing, independently gate-qualified TV titles through the same
        # deterministic low-confidence builder and the same local validators.
        # No source, identity, scene, or certainty is introduced here.
        metadata_fallback_titles = {
            _normalized(pair[0].media_identity.show_or_title)
            for pair in canonical_pairs
        }
        metadata_fallback_added = 0
        metadata_fallback_rejections: dict[str, int] = {}
        while len(canonical_pairs) < intent.max_results:
            metadata_fallback = _deterministic_metadata_scene_pack_fallback(
                intent,
                synthesis_sources,
                synthesis_claims,
                now=generated_at,
                excluded_titles=frozenset(metadata_fallback_titles),
            )
            if metadata_fallback is None:
                break
            opportunity_draft, footage_draft = metadata_fallback
            fallback_title = _normalized(
                opportunity_draft.media_identity.show_or_title
            )
            metadata_fallback_titles.add(fallback_title)
            try:
                _validate_pair_against_intent(
                    intent,
                    opportunity_draft,
                    footage_draft,
                    evidence_index=evidence_index,
                )
                opportunity_id = self._uuid_factory()
                request_id = self._uuid_factory()
                footage = canonicalize_footage_request(
                    draft=footage_draft,
                    footage_request_id=request_id,
                    opportunity_id=opportunity_id,
                    evidence_index=evidence_index,
                    allowed_claim_ids=allowed_claim_ids,
                    uuid_factory=self._uuid_factory,
                )
                opportunity = build_trusted_opportunity(
                    draft=opportunity_draft,
                    opportunity_id=opportunity_id,
                    footage_request_id=request_id,
                    evidence_index=evidence_index,
                    allowed_claim_ids=allowed_claim_ids,
                    now=generated_at,
                    freshness_days=intent.freshness_days,
                    footage_actionability=_footage_actionability(footage_draft),
                )
                canonical_pairs.append((opportunity, footage))
                metadata_fallback_added += 1
            except (ValueError, KeyError) as error:
                code = _synthesis_rejection_code("metadata-fallback", error)
                metadata_fallback_rejections[code] = (
                    metadata_fallback_rejections.get(code, 0) + 1
                )
                continue
        if metadata_fallback_added:
            warnings.append(
                "Added a deterministic low-confidence scene-pack fallback for "
                f"{metadata_fallback_added} independently qualified distinct TV "
                "title(s) that synthesis omitted."
            )
        if metadata_fallback_rejections:
            warnings.append(
                "Deterministic distinct-title fallback rejected "
                + ", ".join(
                    f"{code}={count}"
                    for code, count in sorted(
                        metadata_fallback_rejections.items()
                    )
                )
                + "."
            )
        if not canonical_pairs:
            fallback = _deterministic_primary_scene_pack_fallback(
                intent,
                synthesis_sources,
                synthesis_claims,
                now=generated_at,
            )
            fallback_warning = (
                "Recommendation synthesis did not yield a trusted card; a deterministic "
                "passed-gate film/trailer scene-pack fallback was built from the same "
                "qualified primary evidence and independent current title-bound discussion sources."
            )
            if fallback is None:
                fallback = _deterministic_metadata_scene_pack_fallback(
                    intent,
                    synthesis_sources,
                    synthesis_claims,
                    now=generated_at,
                )
                fallback_warning = (
                    "Recommendation synthesis did not yield a trusted card; a deterministic "
                    "low-confidence scene-pack fallback was built from exact current TVmaze "
                    "episode metadata plus two independent current title-bound discussion sources."
                )
            if fallback is not None:
                opportunity_draft, footage_draft = fallback
                try:
                    _validate_pair_against_intent(
                        intent,
                        opportunity_draft,
                        footage_draft,
                        evidence_index=evidence_index,
                    )
                    opportunity_id = self._uuid_factory()
                    request_id = self._uuid_factory()
                    footage = canonicalize_footage_request(
                        draft=footage_draft,
                        footage_request_id=request_id,
                        opportunity_id=opportunity_id,
                        evidence_index=evidence_index,
                        allowed_claim_ids=allowed_claim_ids,
                        uuid_factory=self._uuid_factory,
                    )
                    opportunity = build_trusted_opportunity(
                        draft=opportunity_draft,
                        opportunity_id=opportunity_id,
                        footage_request_id=request_id,
                        evidence_index=evidence_index,
                        allowed_claim_ids=allowed_claim_ids,
                        now=generated_at,
                        freshness_days=intent.freshness_days,
                        footage_actionability=_footage_actionability(footage_draft),
                    )
                    canonical_pairs.append((opportunity, footage))
                    warnings.append(fallback_warning)
                except (ValueError, KeyError):
                    # The deterministic path is subject to the same evidence and intent
                    # validators as model output. Any mismatch remains an honest no-op.
                    pass
        canonical_pairs.sort(
            key=lambda pair: (-pair[0].score.total, pair[0].title.casefold())
        )
        canonical_pairs = canonical_pairs[: intent.max_results]
        if not canonical_pairs:
            reason = (
                synthesis.draft.no_strong_opportunity_reason
                if synthesis.draft is not None
                else None
            )
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
                footage_requests=[pair[1] for pair in canonical_pairs],
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
        return ResearchWorkflowOutput(
            result=result,
            evidence_sources=tuple(sources),
            evidence_claims=tuple(claims),
            provider_batches=tuple(batches),
            synthesis=synthesis,
            stage_counts=ResearchStageCounts(
                parsed_results=sum(len(item.evidence) for item in batches),
                normalized_evidence=len(claims),
                evidence_surviving_gates=len(synthesis_claims),
                ranked_opportunities=len(canonical_pairs),
                opportunities_returned_to_ui=len(result.opportunities),
            ),
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


def _required_focus_is_supported(
    intent: ResearchIntentV2,
    show_or_title: str,
    claims: list[EvidenceClaimRecordV2],
    source_by_id: dict[UUID, EvidenceSourceRecordV2],
) -> bool:
    """Require source-owned support for explicit audience-fit constraints.

    ``female-centered`` is a deterministic user constraint, not a genre guess or
    model-writable label.  A title can pass only when one of its selected,
    normalized evidence records explicitly carries a female-centered cue.  Cast
    names and the model's own opportunity prose never establish this property.
    """

    required = {_normalized(value) for value in intent.focus_terms}
    if _FEMALE_CENTERED_FOCUS not in required:
        return True
    normalized_title = _normalized(show_or_title)
    for claim in claims:
        source = source_by_id.get(UUID(str(claim.source_id)))
        if source is None:
            continue
        claim_title = _normalized(_claim_show_or_title(claim) or "")
        if claim_title != normalized_title and not _source_matches_show(
            source, show_or_title
        ):
            continue
        if _FEMALE_CENTERED_EVIDENCE.search(source.title):
            return True
    return False


def _could_support_recommendation(
    sources: list[EvidenceSourceRecordV2],
    claims: list[EvidenceClaimRecordV2],
    now: datetime,
    intent: ResearchIntentV2,
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
        if not _required_focus_is_supported(
            intent,
            identity.show_or_title,
            [primary_claim, *(claim for claim, _ in relevant_signals)],
            source_by_id,
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
        if not _required_focus_is_supported(
            intent,
            metadata_claim.episode_locator.show_or_title,
            [metadata_claim, *(claim for claim, _ in relevant_signals)],
            source_by_id,
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


def _select_synthesis_evidence(
    intent: ResearchIntentV2,
    sources: list[EvidenceSourceRecordV2],
    claims: list[EvidenceClaimRecordV2],
    *,
    now: datetime,
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
        if not _required_focus_is_supported(
            intent,
            show_or_title,
            [identity_claim, *relevant_signals],
            source_by_id,
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
        if not _required_focus_is_supported(
            intent,
            opportunity.media_identity.show_or_title,
            selected_claims,
            evidence_index.sources,
        ):
            raise ValueError(
                "opportunity evidence does not support a required audience focus"
            )
    source_title = _normalized(opportunity.media_identity.show_or_title)
    all_sources = [
        *footage.required_sources,
        *footage.optional_sources,
        *footage.alternative_sources,
    ]
    if any(_normalized(item.show_or_title) != source_title for item in all_sources):
        raise ValueError("footage request belongs to a different title than its opportunity")
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
