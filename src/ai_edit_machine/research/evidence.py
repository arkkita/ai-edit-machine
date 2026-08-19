"""Trusted evidence joins, independence checks, and explainable ranking."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID
import re

from ..contracts import EvidenceGate, EvidenceRole, VerificationState
from ..m1_contracts import (
    EvidenceClaimKind,
    EvidenceClaimRecordV2,
    EvidenceSourceRecordV2,
    OpportunityScoreV2,
    TrendOpportunityDraftV2,
    TrendOpportunityV2,
    TrustedOpportunityEvidenceReferenceV2,
)
from .source_ownership import source_record_binds_media_title


ACCEPTABLE_SUPPORT_STATES = frozenset(
    {
        VerificationState.PRIMARY_VERIFIED,
        VerificationState.SECONDARY_CORROBORATED,
    }
)


def _normalized(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())


@dataclass(frozen=True, slots=True)
class EvidenceIndex:
    sources: dict[UUID, EvidenceSourceRecordV2]
    claims: dict[UUID, EvidenceClaimRecordV2]

    @classmethod
    def build(
        cls,
        sources: list[EvidenceSourceRecordV2],
        claims: list[EvidenceClaimRecordV2],
    ) -> "EvidenceIndex":
        source_map = {UUID(str(source.source_id)): source for source in sources}
        claim_map = {UUID(str(claim.claim_id)): claim for claim in claims}
        if len(source_map) != len(sources):
            raise ValueError("evidence source IDs must be unique")
        if len(claim_map) != len(claims):
            raise ValueError("evidence claim IDs must be unique")
        missing = [
            claim.claim_id
            for claim in claims
            if UUID(str(claim.source_id)) not in source_map
        ]
        if missing:
            raise ValueError("every evidence claim must join to a known source")
        return cls(sources=source_map, claims=claim_map)

    def joined(
        self, claim_id: UUID
    ) -> tuple[EvidenceClaimRecordV2, EvidenceSourceRecordV2]:
        try:
            claim = self.claims[UUID(str(claim_id))]
            source = self.sources[UUID(str(claim.source_id))]
        except KeyError as error:
            raise ValueError("provider selected a claim outside the exact allow-list") from error
        return claim, source


def _usable(
    claim: EvidenceClaimRecordV2,
    source: EvidenceSourceRecordV2,
    *,
    now: datetime,
) -> bool:
    return (
        claim.verification in ACCEPTABLE_SUPPORT_STATES
        and (source.expires_at is None or source.expires_at > now)
        and (source.purge_due_at is None or source.purge_due_at > now)
        and (source.deletion_required_at is None or source.deletion_required_at > now)
    )


def _discussion_matches_opportunity(
    draft: TrendOpportunityDraftV2, source: EvidenceSourceRecordV2
) -> bool:
    title = " ".join(re.sub(r"[^a-z0-9]+", " ", source.title.casefold()).split())
    media = " ".join(
        re.sub(r"[^a-z0-9]+", " ", draft.media_identity.show_or_title.casefold()).split()
    )
    if not media:
        return False
    # The gate requires title-bound current discussions.  A page title may be
    # localized even when its fetched body uniquely names the immutable
    # TVmaze seed.  In that case the trusted adapter emits an opaque binding;
    # model output cannot author it.  Focus specificity is checked separately
    # across the selected evidence corpus, so every individual publisher title
    # does not need to repeat the same character names.
    return (
        f" {media} " in f" {title} "
        or source_record_binds_media_title(
            provider=source.provider,
            provider_record_id=source.provider_record_id,
            canonical_url=str(source.canonical_url),
            show_or_title=draft.media_identity.show_or_title,
        )
    )


def _current_tvmaze_episode_matches_opportunity(
    draft: TrendOpportunityDraftV2,
    claim: EvidenceClaimRecordV2,
    source: EvidenceSourceRecordV2,
    *,
    cutoff: datetime,
    now: datetime,
) -> bool:
    """Recognize one exact current metadata identity without promoting it.

    TVmaze is a secondary metadata source, not an official why-now proof. This
    predicate exists only for the explicitly LOW_CONFIDENCE fallback and keeps
    every episode field bound to the deterministic adapter record.
    """

    locator = claim.episode_locator
    identity = draft.media_identity
    event_at = claim.event_or_release_at
    return (
        source.provider == "tvmaze"
        and source.policy_class == "tvmaze-metadata-v1"
        and claim.claim_kind is EvidenceClaimKind.EPISODE_IDENTITY
        and claim.verification is VerificationState.SECONDARY_CORROBORATED
        and not claim.supports_why_now
        and locator is not None
        and identity.media_kind.value == "TV_EPISODE"
        and _normalized(locator.show_or_title)
        == _normalized(identity.show_or_title)
        and locator.season_number == identity.season_number
        and locator.episode_number == identity.episode_number
        and (
            identity.episode_title is None
            or (
                locator.episode_title is not None
                and _normalized(locator.episode_title)
                == _normalized(identity.episode_title)
            )
        )
        and event_at is not None
        and cutoff <= event_at <= now + timedelta(minutes=5)
    )


def _validate_precise_model_copy(
    draft: TrendOpportunityDraftV2,
    selected_claims: list[EvidenceClaimRecordV2],
) -> None:
    allowed_episode_labels: set[str] = set()
    evidence_text = " ".join(claim.text for claim in selected_claims).casefold()
    for claim in selected_claims:
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
    model_copy = " ".join(
        [draft.title, draft.creative_hook, draft.emotional_edit_direction, *draft.caveats]
    )
    normalized_copy = model_copy.casefold()
    episode_mentions = {
        match.group(0).casefold()
        for match in re.finditer(
            r"\bs\d{1,3}e\d{1,4}\b|\bseason\s+\d{1,3}\s+episode\s+\d{1,4}\b",
            normalized_copy,
            re.IGNORECASE,
        )
    }
    if not episode_mentions.issubset(allowed_episode_labels):
        raise ValueError("model copy asserted an unsupported episode locator")
    for quoted in re.findall(r"[\"“]([^\"”]{4,})[\"”]", model_copy):
        normalized_quote = " ".join(quoted.casefold().split())
        if normalized_quote not in " ".join(evidence_text.split()):
            raise ValueError("model copy asserted an unsupported quote")


def _validate_focus_support(
    draft: TrendOpportunityDraftV2,
    selected: list[tuple[EvidenceClaimRecordV2, EvidenceSourceRecordV2]],
    *,
    now: datetime,
) -> None:
    supported = [
        (claim, source)
        for claim, source in selected
        if _usable(claim, source, now=now)
    ]
    corpus_parts: list[str] = []
    for claim, source in supported:
        corpus_parts.extend((claim.text, source.title, source.author_or_channel or ""))
        for fact in (
            claim.episode_locator,
            claim.quote_fact,
            claim.why_now_event,
            claim.scene_fact,
            claim.cast_fact,
        ):
            if fact is not None:
                corpus_parts.append(str(fact.model_dump(mode="json")))
    corpus = " " + " ".join(
        re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()
        for value in corpus_parts
    ) + " "
    for character in draft.focus.characters:
        normalized = re.sub(r"[^a-z0-9]+", " ", character.casefold()).strip()
        if not normalized or f" {normalized} " not in corpus:
            raise ValueError("opportunity focus named an unsupported character")
    topic_tokens = {
        token
        for token in re.sub(
            r"[^a-z0-9]+", " ", draft.focus.relationship_or_topic.casefold()
        ).split()
        if len(token) >= 4
        and token
        not in {
            "relationship",
            "character",
            "characters",
            "central",
            "story",
            "edit",
            "montage",
        }
    }
    if topic_tokens and not any(f" {token} " in corpus for token in topic_tokens):
        raise ValueError("opportunity focus topic is unsupported by selected evidence")


def build_trusted_opportunity(
    *,
    draft: TrendOpportunityDraftV2,
    opportunity_id: UUID,
    footage_request_id: UUID,
    evidence_index: EvidenceIndex,
    allowed_claim_ids: set[UUID],
    now: datetime,
    freshness_days: int,
    footage_actionability: float,
) -> TrendOpportunityV2:
    """Join a provider draft to trusted evidence and recompute its gate/score."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone aware")
    if not 0.0 <= footage_actionability <= 1.0:
        raise ValueError("footage_actionability must be between zero and one")
    trusted: list[TrustedOpportunityEvidenceReferenceV2] = []
    selected_claims: list[EvidenceClaimRecordV2] = []
    selected_joined: list[tuple[EvidenceClaimRecordV2, EvidenceSourceRecordV2]] = []
    usable_primary: list[tuple[EvidenceClaimRecordV2, EvidenceSourceRecordV2]] = []
    usable_metadata: list[tuple[EvidenceClaimRecordV2, EvidenceSourceRecordV2]] = []
    usable_signals: list[tuple[EvidenceClaimRecordV2, EvidenceSourceRecordV2]] = []
    provisional_scene_leads: list[
        tuple[EvidenceClaimRecordV2, EvidenceSourceRecordV2]
    ] = []
    cutoff = now - timedelta(days=freshness_days)
    for selection in draft.evidence:
        claim_uuid = UUID(str(selection.claim_id))
        if claim_uuid not in allowed_claim_ids:
            raise ValueError("provider selected a claim outside the request allow-list")
        claim, source = evidence_index.joined(claim_uuid)
        selected_claims.append(claim)
        selected_joined.append((claim, source))
        if selection.supports_why_now != claim.supports_why_now:
            raise ValueError("provider cannot change a claim's why-now support")
        trusted.append(
            TrustedOpportunityEvidenceReferenceV2(
                claim_id=selection.claim_id,
                role=selection.role,
                supports_why_now=claim.supports_why_now,
                independence_group=source.independence_group,
            )
        )
        scene_fact = claim.scene_fact
        scene_locator = scene_fact.episode_locator if scene_fact is not None else None
        if (
            selection.role is EvidenceRole.CONTEXT
            and claim.claim_kind is EvidenceClaimKind.SCENE_CONTEXT
            and scene_fact is not None
            and claim.verification
            not in {VerificationState.STALE, VerificationState.RETRACTED}
            and (source.expires_at is None or source.expires_at > now)
            and (source.purge_due_at is None or source.purge_due_at > now)
            and (source.deletion_required_at is None or source.deletion_required_at > now)
            and _normalized(scene_fact.show_or_title)
            == _normalized(draft.media_identity.show_or_title)
            and (
                draft.media_identity.media_kind.value != "TV_EPISODE"
                or (
                    scene_locator is not None
                    and scene_locator.season_number
                    == draft.media_identity.season_number
                    and scene_locator.episode_number
                    == draft.media_identity.episode_number
                )
            )
            and (source.source_created_at or source.page_published_at) is not None
            and cutoff
            <= (source.source_created_at or source.page_published_at)
            <= now + timedelta(minutes=5)
        ):
            provisional_scene_leads.append((claim, source))
        if not _usable(claim, source, now=now):
            continue
        if selection.role is EvidenceRole.PRIMARY_WHY_NOW:
            is_direct_primary = (
                claim.verification is VerificationState.PRIMARY_VERIFIED
                and claim.claim_kind
                in {EvidenceClaimKind.WHY_NOW, EvidenceClaimKind.OFFICIAL_CLIP}
                and claim.supports_why_now
                and claim.event_or_release_at is not None
                and claim.why_now_event is not None
                and claim.why_now_event.media_identity == draft.media_identity
                and cutoff <= claim.event_or_release_at <= now + timedelta(minutes=5)
            )
            if is_direct_primary:
                usable_primary.append((claim, source))
        elif selection.role is EvidenceRole.CONTEXT and _current_tvmaze_episode_matches_opportunity(
            draft,
            claim,
            source,
            cutoff=cutoff,
            now=now,
        ):
            usable_metadata.append((claim, source))
        elif (
            selection.role is EvidenceRole.QUALITATIVE_SIGNAL
            and claim.claim_kind is EvidenceClaimKind.VIEWER_DISCUSSION
            and claim.supports_why_now
        ):
            discussion_at = source.source_created_at or source.page_published_at
            if (
                discussion_at is not None
                and cutoff <= discussion_at <= now + timedelta(minutes=5)
                and _discussion_matches_opportunity(draft, source)
            ):
                usable_signals.append((claim, source))

    primary_groups = {source.independence_group for _, source in usable_primary}
    metadata_groups = {source.independence_group for _, source in usable_metadata}
    signal_groups = {source.independence_group for _, source in usable_signals}
    all_groups = primary_groups | metadata_groups | signal_groups
    passed = (
        bool(usable_primary)
        and len(usable_signals) >= 2
        and len(signal_groups) >= 2
        and len(all_groups) >= 3
    )
    primary_low = (
        not passed
        and bool(usable_primary)
        and len(signal_groups) >= 1
        and len(primary_groups | signal_groups) >= 2
    )
    metadata_low = (
        not passed
        and not usable_primary
        and bool(usable_metadata)
        and len(usable_signals) >= 2
        and len(signal_groups) >= 2
        and len(metadata_groups | signal_groups) >= 3
    )
    if not passed and not primary_low and not metadata_low:
        raise ValueError(
            "low-confidence opportunity requires either one current primary plus an "
            "independent signal, or exact current TVmaze episode metadata plus two "
            "independent relevant signals"
        )
    evidence_gate = EvidenceGate.PASSED if passed else EvidenceGate.LOW_CONFIDENCE
    timing_evidence = usable_primary or usable_metadata
    if timing_evidence:
        latest = max(
            claim.event_or_release_at
            for claim, _ in timing_evidence
            if claim.event_or_release_at is not None
        )
        age_seconds = max(0.0, (now - latest).total_seconds())
        freshness = max(0.0, 1.0 - age_seconds / (freshness_days * 86_400))
    else:
        freshness = 0.0
    agreement = min(1.0, len(signal_groups) / 2.0)
    specificity = 1.0 if draft.focus.characters else (
        0.9 if provisional_scene_leads else 0.7
    )
    total = (freshness + agreement + specificity + footage_actionability) / 4.0
    score = OpportunityScoreV2(
        release_freshness=freshness,
        cross_source_agreement=agreement,
        scene_specificity=specificity,
        footage_actionability=footage_actionability,
        independent_source_count=len(all_groups),
        total=total,
    )
    _validate_focus_support(draft, selected_joined, now=now)
    primary_phrases = list(dict.fromkeys(claim.text for claim, _ in usable_primary))
    metadata_phrases = list(dict.fromkeys(claim.text for claim, _ in usable_metadata))
    if usable_primary:
        why_now_text = "Verified why-now evidence: " + "; ".join(primary_phrases)
    else:
        why_now_text = (
            "Current episode metadata (not an official why-now proof): "
            + "; ".join(metadata_phrases)
        )
    discussion_text = (
        "Current qualitative signals: "
        + "; ".join(dict.fromkeys(claim.text for claim, _ in usable_signals))
        if usable_signals
        else "No current independent qualitative signals passed the evidence gate."
    )
    focus_label = draft.focus.relationship_or_topic
    trusted_title = f"{draft.media_identity.show_or_title}: {focus_label}"[:500]
    signal_phrases = list(dict.fromkeys(claim.text for claim, _ in usable_signals))
    signal_summary = "; ".join(signal_phrases)
    scene_phrases = list(
        dict.fromkeys(
            claim.scene_fact.description
            for claim, _ in provisional_scene_leads
            if claim.scene_fact is not None
        )
    )
    scene_summary = "; ".join(scene_phrases)
    if scene_phrases:
        trusted_hook = (
            f"Start with this LIKELY / INFERRED exact-episode scene lead: {scene_summary}. "
            f"It is tied to the current discussion signals: {signal_summary}. The source does "
            "not verify the final outcome, timestamp, or footage location."
        )[:2_000]
    else:
        trusted_hook = (
            f"Investigate {focus_label} through the specific current signals: {signal_summary}. "
            "Treat these as evidence-led inspection targets, not final scene selections."
        )[:2_000]
    if metadata_low and scene_phrases:
        trusted_direction = (
            "Use the current episode metadata only to bind the identity and timing: "
            f"{'; '.join(metadata_phrases)} Inspect supplied local footage around the "
            f"provisional scene selector—{scene_summary}—for an intro, montage escalation, "
            "and payoff. Confirm the exact action and emotional beat locally before editing."
        )[:2_000]
    elif metadata_low:
        trusted_direction = (
            "Use the current episode metadata only as a timing lead, not proof of a specific "
            f"scene: {'; '.join(metadata_phrases)} Then inspect a supplied scene pack or other "
            f"lawfully obtained local footage for a montage and payoff shaped by: {signal_summary}. "
            "The later creative video analysis must confirm every exact visual moment."
        )[:2_000]
    else:
        trusted_direction = (
            f"Anchor the contextual setup in the verified current event: {'; '.join(primary_phrases)} "
            f"Then inspect the supplied footage for a montage and payoff shaped by: {signal_summary}. "
            "The later creative video analysis must confirm the exact visual moments."
        )[:2_000]
    caveats = [
        "Creative scene selection is provisional until the supplied local footage is inspected."
    ]
    if metadata_low:
        caveats.append(
            (
                "Low confidence: no official why-now proof was verified; this uses exact current "
                "TVmaze episode metadata plus two independent title-bound discussion sources. "
                "The displayed scene is a LIKELY / INFERRED source-bound inspection lead, not a "
                "verified outcome or footage location."
                if scene_phrases
                else
                "Low confidence: no official why-now proof was verified; this uses exact current "
                "TVmaze episode metadata plus two independent title-bound discussion sources. "
                "No discussion claim is treated as proof of a scene occurring in that episode."
            )
        )
    elif evidence_gate is EvidenceGate.LOW_CONFIDENCE:
        caveats.append(
            "Low confidence: this has one current independent qualitative signal; "
            "the normal evidence gate requires two."
        )
    return TrendOpportunityV2(
        opportunity_id=opportunity_id,
        footage_request_id=footage_request_id,
        media_kind=draft.media_kind,
        media_identity=draft.media_identity,
        title=trusted_title,
        focus=draft.focus,
        why_now=why_now_text[:2_000],
        what_viewers_are_discussing=discussion_text[:2_000],
        creative_hook=trusted_hook,
        emotional_edit_direction=trusted_direction,
        evidence=trusted,
        evidence_gate=evidence_gate,
        confidence=min(draft.confidence, total),
        score=score,
        caveats=list(dict.fromkeys(caveats)),
    )
