"""Footage-request evidence validation, canonicalization, and natural copy."""

from __future__ import annotations

from collections.abc import Callable
import unicodedata
from uuid import UUID, uuid4

from ..contracts import ExcerptType, MediaKind, VerificationState
from ..m1_contracts import (
    EvidenceClaimKind,
    FootageQuoteStatus,
    FootageRequestDraftV2,
    FootageRequestV2,
    FootageVerificationLevel,
    IntroMaterialLeadDraftV2,
    IntroMaterialLeadV2,
    NaturalFootageRequestV2,
    RequestedSourceDraftV2,
    RequestedSourceV2,
    SourceAcquisitionKind,
)
from .evidence import EvidenceIndex
from .source_ownership import source_record_binds_media_title


def _episode_label(source: RequestedSourceDraftV2) -> str:
    if source.asset_kind is SourceAcquisitionKind.EPISODE:
        assert source.season_number is not None and source.episode_number is not None
        label = f"Season {source.season_number} Episode {source.episode_number}"
        episode = f'{label} ("{source.episode_title}")' if source.episode_title else label
        return f"{source.show_or_title} {episode}"
    if source.asset_kind is SourceAcquisitionKind.SCENE_PACK:
        focus = source.relationship_or_topic or " + ".join(source.characters)
        return f"a {focus} scene pack" if focus else f"a {source.show_or_title} scene pack"
    if source.asset_kind is SourceAcquisitionKind.OFFICIAL_TRAILER:
        return f"the official {source.show_or_title} trailer"
    if source.asset_kind is SourceAcquisitionKind.OFFICIAL_CLIP:
        return f"the official {source.show_or_title} clip"
    if source.asset_kind is SourceAcquisitionKind.INDIVIDUAL_SCENES:
        moment = source.scene_or_moment.rstrip(" .")
        return f"the {source.show_or_title} scenes covering {moment}"
    return f"the requested {source.show_or_title} scenes"


def _join_labels(labels: list[str]) -> str:
    if len(labels) == 1:
        return labels[0]
    if len(labels) == 2:
        return f"{labels[0]} and {labels[1]}"
    return f"{', '.join(labels[:-1])}, and {labels[-1]}"


def _join_alternatives(labels: list[str]) -> str:
    if len(labels) == 1:
        return labels[0]
    if len(labels) == 2:
        return f"{labels[0]} or {labels[1]}"
    return f"{', '.join(labels[:-1])}, or {labels[-1]}"


def render_natural_request(
    *,
    required_sources: list[RequestedSourceDraftV2],
    optional_sources: list[RequestedSourceDraftV2],
    alternative_sources: list[RequestedSourceDraftV2],
) -> NaturalFootageRequestV2:
    """Render conversational acquisition copy only from validated fields."""

    required = _join_labels([_episode_label(source) for source in required_sources])
    best = f"Give me {required}."
    minimum = f"The smallest useful set is {required}."
    alternative = None
    if alternative_sources:
        alternative = (
            f"If that is easier, give me "
            f"{_join_alternatives([_episode_label(source) for source in alternative_sources])}."
        )
    optional_improvement = None
    if optional_sources:
        optional_improvement = (
            f"If you have it, {_join_labels([_episode_label(source) for source in optional_sources])} "
            "would add another emotional option."
        )
    return NaturalFootageRequestV2(
        best=best,
        alternative=alternative,
        minimum=minimum,
        optional_improvement=optional_improvement,
    )


def _validate_quote_claim(
    *,
    quote: object,
    source: RequestedSourceDraftV2 | None,
    evidence_index: EvidenceIndex,
    allowed_claim_ids: set[UUID],
) -> None:
    from ..m1_contracts import FootageQuoteV2

    if not isinstance(quote, FootageQuoteV2):
        raise ValueError("quote object is incomplete")
    quote_claim_id = UUID(str(quote.claim_id))
    if quote_claim_id not in allowed_claim_ids:
        raise ValueError("quote claim is outside the request allow-list")
    claim, evidence_source = evidence_index.joined(quote_claim_id)
    if claim.verification in {VerificationState.STALE, VerificationState.RETRACTED}:
        raise ValueError("displayed quote/paraphrase evidence is stale or retracted")
    if quote.status is FootageQuoteStatus.VERIFIED:
        if (
            claim.claim_kind is not EvidenceClaimKind.QUOTE
            or claim.excerpt_type is not ExcerptType.SHORT_QUOTE
            or claim.verification is not VerificationState.PRIMARY_VERIFIED
            or claim.quote_fact is None
        ):
            raise ValueError("VERIFIED quote must join an authoritative short-quote claim")
        if _normalized(claim.quote_fact.exact_text) != _normalized(quote.text):
            raise ValueError("VERIFIED quote text does not match its authoritative claim")
        if _normalized(claim.quote_fact.speaker) != _normalized(quote.speaker or ""):
            raise ValueError("VERIFIED quote speaker does not match its authoritative claim")
        if quote.likely_context is not None and (
            claim.quote_fact.context is None
            or _normalized(claim.quote_fact.context) != _normalized(quote.likely_context)
        ):
            raise ValueError("VERIFIED quote context does not match its authoritative claim")
        if source is not None and source.asset_kind is SourceAcquisitionKind.EPISODE:
            locator = claim.quote_fact.episode_locator
            if locator is None or not _episode_locator_matches(source, locator):
                raise ValueError("VERIFIED quote is not bound to the requested episode")
        if source is not None and _normalized(
            claim.quote_fact.media_identity.show_or_title
        ) != _normalized(source.show_or_title):
            raise ValueError("VERIFIED quote belongs to a different title")
    else:
        expected_excerpt = (
            ExcerptType.PARAPHRASE
            if quote.status is FootageQuoteStatus.PARAPHRASE
            else ExcerptType.UNVERIFIED_QUOTE_LEAD
        )
        if claim.excerpt_type is not expected_excerpt or _normalized(claim.text) != _normalized(
            quote.text
        ):
            raise ValueError("displayed quote lead must exactly match its evidence record")
        if source is not None and source.asset_kind is SourceAcquisitionKind.EPISODE:
            # A show-level discussion may establish that a line is circulating,
            # but it cannot place that line in a particular episode.  M1's
            # viewer-discussion contract intentionally has no locator payload,
            # so uncertain quotes belong on a scene-pack/individual-scenes
            # request until a locator-bearing quote fact is available.
            if (
                claim.claim_kind is not EvidenceClaimKind.QUOTE
                or claim.quote_fact is None
                or claim.quote_fact.episode_locator is None
                or not _episode_locator_matches(
                    source, claim.quote_fact.episode_locator
                )
            ):
                raise ValueError(
                    "unverified quote lead is not bound to the requested episode"
                )
        if source is not None and not (
            _claim_relevant_to_inference(source, claim)
            or _normalized(source.show_or_title) in _normalized(evidence_source.title)
            or _normalized(source.show_or_title) in _normalized(claim.text)
        ):
            raise ValueError("displayed quote lead is not bound to the requested title")


def _normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()


def _evidence_source_binds_title(
    source: object, show_or_title: str
) -> bool:
    """Apply the same immutable title binding used by the opportunity gate.

    Staged film searches can validate a page body against an exact title even
    when a localized or list-style page title does not literally repeat that
    title.  The adapter records that binding in an opaque provider record ID.
    Footage inference must honor the same trusted binding rather than silently
    reverting to headline substring matching.
    """

    from ..m1_contracts import EvidenceSourceRecordV2

    if not isinstance(source, EvidenceSourceRecordV2):
        return False
    return (
        _normalized(show_or_title) in _normalized(source.title)
        or source_record_binds_media_title(
            provider=source.provider,
            provider_record_id=source.provider_record_id,
            canonical_url=str(source.canonical_url),
            show_or_title=show_or_title,
        )
    )


def _episode_locator_matches(source: RequestedSourceDraftV2, locator: object) -> bool:
    from ..m1_contracts import EpisodeLocatorFactV2

    if not isinstance(locator, EpisodeLocatorFactV2):
        return False
    if (
        _normalized(locator.show_or_title) != _normalized(source.show_or_title)
        or locator.season_number != source.season_number
        or locator.episode_number != source.episode_number
    ):
        return False
    if source.episode_title is not None:
        return locator.episode_title is not None and _normalized(locator.episode_title) == _normalized(
            source.episode_title
        )
    return True


def _episode_fact_matches(source: RequestedSourceDraftV2, claim: object) -> bool:
    from ..m1_contracts import EvidenceClaimRecordV2

    if not isinstance(claim, EvidenceClaimRecordV2) or claim.episode_locator is None:
        return False
    return _episode_locator_matches(source, claim.episode_locator)


def _scene_fact_matches(
    source: RequestedSourceDraftV2, claim: object, *, description: str
) -> bool:
    from ..m1_contracts import EvidenceClaimRecordV2

    if not isinstance(claim, EvidenceClaimRecordV2) or claim.scene_fact is None:
        return False
    fact = claim.scene_fact
    if _normalized(fact.show_or_title) != _normalized(source.show_or_title):
        return False
    if _normalized(fact.description) != _normalized(description):
        return False
    requested_characters = {_normalized(value) for value in source.characters}
    fact_characters = {_normalized(value) for value in fact.characters}
    if not requested_characters.issubset(fact_characters):
        return False
    if source.relationship_or_topic is not None and (
        fact.relationship_or_topic is None
        or _normalized(fact.relationship_or_topic)
        != _normalized(source.relationship_or_topic)
    ):
        return False
    if source.asset_kind is SourceAcquisitionKind.EPISODE:
        return fact.episode_locator is not None and _episode_locator_matches(
            source, fact.episode_locator
        )
    return True


def _claim_matches_source(source: RequestedSourceDraftV2, claim: object) -> bool:
    from ..m1_contracts import EvidenceClaimRecordV2

    if not isinstance(claim, EvidenceClaimRecordV2):
        return False
    if source.asset_kind is SourceAcquisitionKind.EPISODE:
        return _scene_fact_matches(source, claim, description=source.scene_or_moment)
    if source.asset_kind in {
        SourceAcquisitionKind.OFFICIAL_CLIP,
        SourceAcquisitionKind.OFFICIAL_TRAILER,
    }:
        if claim.why_now_event is None:
            return False
        identity = claim.why_now_event.media_identity
        expected_kind = (
            MediaKind.OFFICIAL_CLIP
            if source.asset_kind is SourceAcquisitionKind.OFFICIAL_CLIP
            else MediaKind.TRAILER
        )
        return (
            identity.media_kind is expected_kind
            and _normalized(identity.show_or_title) == _normalized(source.show_or_title)
            and _scene_fact_matches(source, claim, description=source.scene_or_moment)
        )
    if source.asset_kind is SourceAcquisitionKind.INDIVIDUAL_SCENES:
        return _scene_fact_matches(source, claim, description=source.scene_or_moment)
    # A scene-pack suggestion is an acquisition convenience, not a verified asset fact.
    return False


def _asset_identity_matches(source: RequestedSourceDraftV2, claim: object) -> bool:
    from ..m1_contracts import EvidenceClaimRecordV2

    if not isinstance(claim, EvidenceClaimRecordV2):
        return False
    if source.asset_kind is SourceAcquisitionKind.EPISODE:
        return _episode_fact_matches(source, claim)
    if source.asset_kind in {
        SourceAcquisitionKind.OFFICIAL_CLIP,
        SourceAcquisitionKind.OFFICIAL_TRAILER,
    }:
        if claim.why_now_event is None:
            return False
        expected = (
            MediaKind.OFFICIAL_CLIP
            if source.asset_kind is SourceAcquisitionKind.OFFICIAL_CLIP
            else MediaKind.TRAILER
        )
        identity = claim.why_now_event.media_identity
        return identity.media_kind is expected and _normalized(
            identity.show_or_title
        ) == _normalized(source.show_or_title)
    if source.asset_kind is SourceAcquisitionKind.INDIVIDUAL_SCENES:
        return _scene_fact_matches(source, claim, description=source.scene_or_moment)
    return False


def _claim_relevant_to_inference(source: RequestedSourceDraftV2, claim: object) -> bool:
    """Require immutable structured identity, never a merely nearby prose claim."""

    from ..m1_contracts import EvidenceClaimRecordV2

    if not isinstance(claim, EvidenceClaimRecordV2):
        return False
    if claim.verification in {VerificationState.STALE, VerificationState.RETRACTED}:
        return False
    if _claim_matches_source(source, claim):
        return True
    identities = []
    if claim.episode_locator is not None:
        identities.append(claim.episode_locator.show_or_title)
    if claim.quote_fact is not None:
        identities.append(claim.quote_fact.media_identity.show_or_title)
    if claim.scene_fact is not None:
        identities.append(claim.scene_fact.show_or_title)
    if claim.why_now_event is not None:
        identities.append(claim.why_now_event.media_identity.show_or_title)
    if claim.cast_fact is not None:
        identities.append(claim.cast_fact.show_or_title)
    return any(_normalized(value) == _normalized(source.show_or_title) for value in identities)


def _quote_context_matches_source(source: RequestedSourceDraftV2, claim: object) -> bool:
    from ..m1_contracts import EvidenceClaimRecordV2

    if not isinstance(claim, EvidenceClaimRecordV2) or claim.quote_fact is None:
        return False
    fact = claim.quote_fact
    if (
        _normalized(fact.media_identity.show_or_title) != _normalized(source.show_or_title)
        or fact.context is None
        or _normalized(fact.context) != _normalized(source.scene_or_moment)
    ):
        return False
    if source.asset_kind is SourceAcquisitionKind.EPISODE:
        return fact.episode_locator is not None and _episode_locator_matches(
            source, fact.episode_locator
        )
    return True


def _quality_summary(level: FootageVerificationLevel) -> str:
    return {
        FootageVerificationLevel.VERIFIED: "Verified against authoritative source evidence.",
        FootageVerificationLevel.STRONGLY_SUPPORTED: (
            "Strongly supported by relevant corroborated evidence; inspect the local footage "
            "before relying on the exact moment."
        ),
        FootageVerificationLevel.LIKELY_INFERRED: (
            "Likely or inferred from relevant evidence; the exact moment is not verified."
        ),
        FootageVerificationLevel.UNKNOWN: (
            "Unverified lead; the exact source location remains unknown."
        ),
    }[level]


def _focus_label(source: RequestedSourceDraftV2) -> str:
    value = source.relationship_or_topic or " + ".join(source.characters)
    return (value or source.show_or_title)[:300]


def _purpose_label(source: RequestedSourceDraftV2) -> str:
    labels = [purpose.value.replace("_", " ").casefold() for purpose in source.purposes]
    return _join_labels(labels)


def _source_emotional_rationale(source: RequestedSourceDraftV2) -> str:
    """Render factual-safe rationale only from already validated source fields."""

    focus = _focus_label(source)
    purposes = _purpose_label(source)
    if source.verification_level is FootageVerificationLevel.UNKNOWN:
        return (
            f"This is a broad inspection target for {focus} and the {purposes} roles. "
            "No specific emotional beat is asserted until the supplied local footage is inspected."
        )
    moment = source.scene_or_moment[:900]
    return (
        f"Evidence links this source to the {purposes} roles for {focus} through this "
        f"inspection target: {moment} Supplied local footage must confirm its emotional "
        "value before editing."
    )


def _intro_rationale(
    lead: IntroMaterialLeadDraftV2, source: RequestedSourceDraftV2
) -> str:
    """Render provisional intro reasoning without retaining model-authored facts."""

    focus = _focus_label(source)
    if lead.verification_level is FootageVerificationLevel.UNKNOWN:
        return (
            f"This broad lead may provide context for {focus} before the montage. "
            "No exact intro beat is asserted until the supplied local footage is inspected."
        )
    moment = lead.moment_description[:900]
    return (
        f"This evidence-bound lead could provide context for {focus} before the montage: "
        f"{moment} Supplied local footage must confirm the timing and emotional handoff."
    )


def _safe_search_queries(source: RequestedSourceDraftV2) -> list[str]:
    focus = source.relationship_or_topic or " ".join(source.characters)
    official_label = None
    label_prefix = "Official upload labeled “"
    if (
        source.verification_level is not FootageVerificationLevel.UNKNOWN
        and source.scene_or_moment.startswith(label_prefix)
        and source.scene_or_moment.endswith("”")
    ):
        official_label = source.scene_or_moment[len(label_prefix) : -1].strip()
    official_focus = official_label or focus
    if source.asset_kind is SourceAcquisitionKind.EPISODE:
        assert source.season_number is not None and source.episode_number is not None
        queries = [
            f"{source.show_or_title} season {source.season_number} episode "
            f"{source.episode_number} scenes"
        ]
    elif source.asset_kind is SourceAcquisitionKind.SCENE_PACK:
        queries = [f"{source.show_or_title} {focus or 'character'} scene pack"]
    elif source.asset_kind is SourceAcquisitionKind.OFFICIAL_TRAILER:
        queries = [
            *(
                [f'{source.show_or_title} "{official_focus}" official trailer']
                if official_focus
                and official_focus != "official promotional footage"
                else []
            ),
            f"{source.show_or_title} official trailer",
        ]
    elif source.asset_kind is SourceAcquisitionKind.OFFICIAL_CLIP:
        queries = [
            *(
                [f'{source.show_or_title} "{official_focus}" official clip']
                if official_focus
                and official_focus != "official promotional footage"
                else []
            ),
            f"{source.show_or_title} official clip",
        ]
    else:
        queries = [f"{source.show_or_title} {focus or 'character'} scenes"]
    if source.quote is not None:
        queries.append(f'"{source.quote.text}" {source.show_or_title}')
    return list(dict.fromkeys(queries))[:20]


def _safe_source(source: RequestedSourceDraftV2) -> RequestedSourceDraftV2:
    values = source.model_dump(mode="python")
    if source.verification_level is FootageVerificationLevel.UNKNOWN:
        focus = source.relationship_or_topic or " + ".join(source.characters)
        values["scene_or_moment"] = (
            f"Any relevant {focus or source.show_or_title} material; the exact scene is unknown."
        )
        values["why_it_matters_emotionally"] = (
            "This is an optional inspection target; no specific story beat is being asserted."
        )
    values["search_queries"] = _safe_search_queries(source)
    values["source_quality_summary"] = _quality_summary(source.verification_level)
    safe = RequestedSourceDraftV2(**values)
    rendered = safe.model_dump(mode="python")
    rendered["why_it_matters_emotionally"] = _source_emotional_rationale(safe)
    return RequestedSourceDraftV2(**rendered)


def _validate_source_evidence(
    source: RequestedSourceDraftV2,
    *,
    evidence_index: EvidenceIndex,
    allowed_claim_ids: set[UUID],
) -> None:
    claim_ids = {UUID(str(value)) for value in source.supporting_claim_ids}
    if not claim_ids.issubset(allowed_claim_ids):
        raise ValueError("requested source cites a claim outside the request allow-list")
    joined_pairs = [evidence_index.joined(value) for value in claim_ids]
    usable_joined_pairs = [
        pair
        for pair in joined_pairs
        if pair[0].verification
        not in {VerificationState.STALE, VerificationState.RETRACTED}
    ]
    joined = [pair[0] for pair in usable_joined_pairs]
    if source.asset_kind is SourceAcquisitionKind.SCENE_PACK and source.verification_level in {
        FootageVerificationLevel.VERIFIED,
        FootageVerificationLevel.STRONGLY_SUPPORTED,
    }:
        raise ValueError("scene-pack availability cannot be promoted above LIKELY_INFERRED")
    if source.asset_kind is SourceAcquisitionKind.EPISODE:
        if not any(
            claim.claim_kind
            in {
                EvidenceClaimKind.EPISODE_IDENTITY,
                EvidenceClaimKind.WHY_NOW,
                EvidenceClaimKind.OFFICIAL_CLIP,
            }
            and claim.verification
            in {
                VerificationState.PRIMARY_VERIFIED,
                VerificationState.SECONDARY_CORROBORATED,
            }
            and _episode_fact_matches(source, claim)
            for claim in joined
        ):
            raise ValueError("every exact episode locator requires matching structured evidence")
    if source.verification_level is FootageVerificationLevel.VERIFIED:
        has_identity = any(
            claim.verification is VerificationState.PRIMARY_VERIFIED
            and _asset_identity_matches(source, claim)
            for claim in joined
        )
        has_scene = any(
            claim.verification is VerificationState.PRIMARY_VERIFIED
            and _scene_fact_matches(source, claim, description=source.scene_or_moment)
            for claim in joined
        )
        if not has_identity or not has_scene:
            raise ValueError("VERIFIED source needs authoritative asset and exact-scene evidence")
    elif source.verification_level is FootageVerificationLevel.STRONGLY_SUPPORTED:
        supported_states = {
            VerificationState.PRIMARY_VERIFIED,
            VerificationState.SECONDARY_CORROBORATED,
        }
        has_identity = any(
            claim.verification in supported_states and _asset_identity_matches(source, claim)
            for claim in joined
        )
        has_scene = any(
            claim.verification
            in supported_states
            and _scene_fact_matches(source, claim, description=source.scene_or_moment)
            for claim in joined
        )
        if not has_identity or not has_scene:
            raise ValueError("STRONGLY_SUPPORTED source needs asset and exact-scene evidence")
    elif source.verification_level is FootageVerificationLevel.LIKELY_INFERRED:
        has_identity = any(_claim_relevant_to_inference(source, claim) for claim in joined)
        has_moment = any(
            _scene_fact_matches(source, claim, description=source.scene_or_moment)
            or _quote_context_matches_source(source, claim)
            or (
                claim.claim_kind is EvidenceClaimKind.OFFICIAL_CLIP
                and _asset_identity_matches(source, claim)
                and _normalized(claim.text) == _normalized(source.scene_or_moment)
            )
            or (
                source.asset_kind is not SourceAcquisitionKind.EPISODE
                and
                claim.claim_kind is EvidenceClaimKind.VIEWER_DISCUSSION
                and claim.excerpt_type
                in {ExcerptType.PARAPHRASE, ExcerptType.UNVERIFIED_QUOTE_LEAD}
                and _normalized(claim.text) == _normalized(source.scene_or_moment)
                and _evidence_source_binds_title(
                    evidence_source, source.show_or_title
                )
            )
            for claim, evidence_source in usable_joined_pairs
        )
        if not has_identity or not has_moment:
            raise ValueError(
                "LIKELY_INFERRED source needs relevant identity and moment evidence"
            )
    if source.quote:
        _validate_quote_claim(
            quote=source.quote,
            source=source,
            evidence_index=evidence_index,
            allowed_claim_ids=allowed_claim_ids,
        )


def canonicalize_footage_request(
    *,
    draft: FootageRequestDraftV2,
    footage_request_id: UUID,
    opportunity_id: UUID,
    evidence_index: EvidenceIndex,
    allowed_claim_ids: set[UUID],
    uuid_factory: Callable[[], UUID] = uuid4,
) -> FootageRequestV2:
    """Inject server IDs and replace model copy with deterministic natural copy."""

    all_drafts = [
        *draft.required_sources,
        *draft.optional_sources,
        *draft.alternative_sources,
    ]
    for source in all_drafts:
        _validate_source_evidence(
            source,
            evidence_index=evidence_index,
            allowed_claim_ids=allowed_claim_ids,
        )
    safe_drafts = [_safe_source(source) for source in all_drafts]
    safe_by_key = {source.source_key: source for source in safe_drafts}
    by_key: dict[str, RequestedSourceV2] = {}
    for source in safe_drafts:
        values = source.model_dump(mode="python")
        by_key[source.source_key] = RequestedSourceV2(
            **values, requested_source_id=uuid_factory()
        )
    canonical_intro: list[IntroMaterialLeadV2] = []
    for lead in draft.intro_leads:
        if not {UUID(str(value)) for value in lead.supporting_claim_ids}.issubset(
            allowed_claim_ids
        ):
            raise ValueError("intro lead cites a claim outside the request allow-list")
        source_draft = next(item for item in all_drafts if item.source_key == lead.source_key)
        lead_pairs = [
            evidence_index.joined(UUID(str(value))) for value in lead.supporting_claim_ids
        ]
        usable_lead_pairs = [
            pair
            for pair in lead_pairs
            if pair[0].verification
            not in {VerificationState.STALE, VerificationState.RETRACTED}
        ]
        lead_claims = [pair[0] for pair in usable_lead_pairs]
        if lead.verification_level in {
            FootageVerificationLevel.VERIFIED,
            FootageVerificationLevel.STRONGLY_SUPPORTED,
        }:
            required_state = (
                {VerificationState.PRIMARY_VERIFIED}
                if lead.verification_level is FootageVerificationLevel.VERIFIED
                else {
                    VerificationState.PRIMARY_VERIFIED,
                    VerificationState.SECONDARY_CORROBORATED,
                }
            )
            if not any(
                claim.verification in required_state
                and claim.claim_kind in {
                    EvidenceClaimKind.SCENE_CONTEXT,
                    EvidenceClaimKind.OFFICIAL_CLIP,
                }
                and _scene_fact_matches(
                    source_draft, claim, description=lead.moment_description
                )
                for claim in lead_claims
            ):
                raise ValueError("verified/supported intro lead needs a matching scene fact")
        else:
            if not any(
                _scene_fact_matches(
                    source_draft, claim, description=lead.moment_description
                )
                or _quote_context_matches_source(
                    source_draft, claim
                )
                or (
                    source_draft.asset_kind is not SourceAcquisitionKind.EPISODE
                    and
                    claim.claim_kind is EvidenceClaimKind.VIEWER_DISCUSSION
                    and claim.excerpt_type
                    in {ExcerptType.PARAPHRASE, ExcerptType.UNVERIFIED_QUOTE_LEAD}
                    and _normalized(claim.text) == _normalized(lead.moment_description)
                    and _evidence_source_binds_title(
                        evidence_source, source_draft.show_or_title
                    )
                )
                for claim, evidence_source in usable_lead_pairs
            ):
                raise ValueError("inferred/unknown intro lead needs matching moment evidence")
        if lead.quote:
            _validate_quote_claim(
                quote=lead.quote,
                source=source_draft,
                evidence_index=evidence_index,
                allowed_claim_ids=allowed_claim_ids,
            )
        canonical_intro.append(
            IntroMaterialLeadV2(
                **{
                    **lead.model_dump(mode="python"),
                    "why_it_might_lead_into_montage": _intro_rationale(
                        lead, safe_by_key[lead.source_key]
                    ),
                },
                intro_lead_id=uuid_factory(),
            )
        )
    natural_request = render_natural_request(
        required_sources=[safe_by_key[item.source_key] for item in draft.required_sources],
        optional_sources=[safe_by_key[item.source_key] for item in draft.optional_sources],
        alternative_sources=[safe_by_key[item.source_key] for item in draft.alternative_sources],
    )
    canonical_searches = list(
        dict.fromkeys(
            query
            for source in safe_drafts
            for query in source.search_queries
        )
    )[:30]
    unknown_warning = (
        "Unknown source suggestions are broad inspection targets, not verified scene claims."
        if any(
            source.verification_level is FootageVerificationLevel.UNKNOWN
            for source in safe_drafts
        )
        else None
    )
    return FootageRequestV2(
        footage_request_id=footage_request_id,
        opportunity_id=opportunity_id,
        summary="Smallest evidence-bound footage request for this research opportunity.",
        natural_request=natural_request,
        required_sources=[by_key[item.source_key] for item in draft.required_sources],
        optional_sources=[by_key[item.source_key] for item in draft.optional_sources],
        alternative_sources=[by_key[item.source_key] for item in draft.alternative_sources],
        minimum_useful_source_keys=draft.minimum_useful_source_keys,
        smallest_useful_set_reason=(
            "The required bucket is the smallest set supported by the current evidence; "
            "optional and alternative items are not prerequisites."
        ),
        intro_leads=canonical_intro,
        search_queries=canonical_searches,
        warnings=[unknown_warning] if unknown_warning is not None else [],
    )
