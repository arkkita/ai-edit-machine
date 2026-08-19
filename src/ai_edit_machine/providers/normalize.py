"""Convert provider candidates into trusted, joinable evidence records."""

from __future__ import annotations

import hashlib
import json
import re
from difflib import SequenceMatcher
from datetime import datetime, timezone
from urllib.parse import urlsplit
from uuid import uuid4

from ..contracts import EvidenceSourceType, VerificationState
from ..m1_contracts import (
    EvidenceClaimKind,
    EvidenceClaimRecordV2,
    EvidenceSourceRecordV2,
)
from ..research.policy import PolicyRule, deadlines_for
from ..research.source_ownership import known_publisher_owner
from ..research.urls import canonical_host, canonicalize_public_url
from .base import EvidenceCandidate, ProviderBatch, ProviderRunOutcome


def _content_hash(payload: object) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _independence_group(
    candidate: EvidenceCandidate,
    canonical_url: str,
    *,
    copy_group: str | None,
) -> str:
    parts = urlsplit(canonical_url)
    host = parts.hostname.casefold() if parts.hostname else "unknown"
    path_parts = [part for part in parts.path.split("/") if part]
    if candidate.provider == "tvmaze":
        return "publisher:tvmaze"
    if candidate.provider == "youtube":
        if not candidate.adapter_origin_id or not candidate.adapter_origin_id.startswith(
            "youtube-channel:"
        ):
            raise ValueError("YouTube evidence is missing trusted channel origin")
        return candidate.adapter_origin_id.casefold()[:128]
    if copy_group is not None:
        return copy_group
    if host in {"x.com", "twitter.com"} and path_parts:
        return f"x-author:{path_parts[0].casefold()}"[:128]
    owner = known_publisher_owner(host)
    if owner is not None:
        return owner
    # Unknown ownership/lineage is deliberately one conservative group; it
    # cannot manufacture two independent signals merely by changing domains.
    return "publisher:unverified-web"


def _copy_groups(
    grouped: dict[tuple[str, str], list[EvidenceCandidate]],
) -> dict[tuple[str, str], str]:
    qualitative: list[tuple[tuple[str, str], str]] = []
    for key, candidates in grouped.items():
        excerpts = [
            re.sub(r"[^a-z0-9]+", " ", item.excerpt.casefold()).strip()
            for item in candidates
            if item.claim_kind is EvidenceClaimKind.VIEWER_DISCUSSION
        ]
        if excerpts:
            qualitative.append((key, max(excerpts, key=len)))
    parents = list(range(len(qualitative)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parents[max(left_root, right_root)] = min(left_root, right_root)

    for left in range(len(qualitative)):
        for right in range(left + 1, len(qualitative)):
            left_text, right_text = qualitative[left][1], qualitative[right][1]
            if min(len(left_text), len(right_text)) < 40:
                continue
            if SequenceMatcher(None, left_text, right_text).ratio() >= 0.9:
                union(left, right)
    members: dict[int, list[int]] = {}
    for index in range(len(qualitative)):
        members.setdefault(find(index), []).append(index)
    result: dict[tuple[str, str], str] = {}
    for indices in members.values():
        if len(indices) < 2:
            continue
        fingerprint = hashlib.sha256(
            "\n".join(sorted(qualitative[index][1] for index in indices)).encode("utf-8")
        ).hexdigest()[:24]
        for index in indices:
            result[qualitative[index][0]] = f"copy-cluster:{fingerprint}"
    return result


def _earliest(values: list[datetime | None]) -> datetime | None:
    present = [value for value in values if value is not None]
    return min(present) if present else None


def _latest(values: list[datetime | None]) -> datetime | None:
    present = [value for value in values if value is not None]
    return max(present) if present else None


def _normalized_text(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())


def normalize_batches(
    batches: list[ProviderBatch],
    *,
    retrieved_at: datetime,
    official_hosts: set[str],
    policy_rules: dict[str, PolicyRule] | None = None,
    uuid_factory=uuid4,
) -> tuple[list[EvidenceSourceRecordV2], list[EvidenceClaimRecordV2]]:
    """Normalize once per source URL while retaining every distinct claim."""

    if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
        raise ValueError("retrieved_at must be timezone aware")
    retrieved_at = retrieved_at.astimezone(timezone.utc)
    official = {value.casefold().strip(" .") for value in official_hosts}
    for batch in batches:
        if batch.provider == "tvmaze" and batch.outcome is ProviderRunOutcome.SUCCESS:
            official.update(value.casefold().strip(" .") for value in batch.trusted_official_hosts)
    grouped: dict[tuple[str, str], list[EvidenceCandidate]] = {}
    for batch in batches:
        if batch.outcome is not ProviderRunOutcome.SUCCESS:
            continue
        for candidate in batch.evidence:
            if candidate.provider != batch.provider:
                raise ValueError("provider batch cannot contain another provider's evidence")
            canonical_url = canonicalize_public_url(candidate.canonical_url)
            if candidate.provider in {"openai", "xai"} and not candidate.citation_verified:
                raise ValueError("model-authored URL was not present in provider tool sources")
            grouped.setdefault((candidate.provider, canonical_url), []).append(candidate)

    sources: list[EvidenceSourceRecordV2] = []
    claims: list[EvidenceClaimRecordV2] = []
    seen_claim_hashes: set[str] = set()
    copy_groups = _copy_groups(grouped)
    for (provider, canonical_url), candidates in sorted(grouped.items()):
        candidates.sort(
            key=lambda item: (
                item.provider_record_id or "",
                item.claim_kind.value,
                item.excerpt,
            )
        )
        base = candidates[0]
        if any(
            item.source_type is not base.source_type
            or item.policy_class != base.policy_class
            or item.adapter_origin_id != base.adapter_origin_id
            for item in candidates[1:]
        ):
            raise ValueError("one canonical source has inconsistent trusted adapter metadata")
        record_ids = {
            item.provider_record_id for item in candidates if item.provider_record_id is not None
        }
        if len(record_ids) > 1:
            raise ValueError("one canonical source has conflicting provider record IDs")
        host = canonical_host(canonical_url)
        trusted_official_host = any(
            host == value or host.endswith(f".{value}") for value in official
        )
        source_created_at = _earliest([item.source_created_at for item in candidates])
        source_updated_at = _latest([item.source_updated_at for item in candidates])
        page_published_at = _earliest([item.page_published_at for item in candidates])
        window_start = _earliest([item.window_start for item in candidates])
        window_end = _latest([item.window_end for item in candidates])
        title = max((item.title for item in candidates), key=lambda value: (len(value), value))
        author = max(
            (item.author_or_channel for item in candidates if item.author_or_channel),
            key=lambda value: (len(value), value),
            default=None,
        )
        deadlines = deadlines_for(base.policy_class, retrieved_at, policy_rules)
        source_id = uuid_factory()
        source_hash = _content_hash(
            {
                "provider": provider,
                "canonical_url": canonical_url,
                "title": title,
                "author_or_channel": author,
                "source_created_at": source_created_at.isoformat() if source_created_at else None,
                "page_published_at": page_published_at.isoformat() if page_published_at else None,
            }
        )
        sources.append(
            EvidenceSourceRecordV2(
                source_id=source_id,
                provider=provider,
                provider_record_id=base.provider_record_id,
                source_type=base.source_type,
                canonical_url=canonical_url,
                title=title,
                author_or_channel=author,
                source_created_at=source_created_at,
                source_updated_at=source_updated_at,
                page_published_at=page_published_at,
                retrieved_at=retrieved_at,
                query=base.query,
                window_start=window_start,
                window_end=window_end,
                policy_class=base.policy_class,
                refresh_due_at=deadlines.refresh_due_at,
                purge_due_at=deadlines.purge_due_at,
                expires_at=deadlines.expires_at,
                deletion_required_at=deadlines.deletion_required_at,
                content_sha256=source_hash,
                independence_group=_independence_group(
                    base,
                    canonical_url,
                    copy_group=copy_groups.get((provider, canonical_url)),
                ),
            )
        )
        for candidate in candidates:
            verification = candidate.verification
            if provider == "openai":
                content_bound_primary = (
                    candidate.content_binding_verified
                    and candidate.claim_kind
                    in {EvidenceClaimKind.QUOTE, EvidenceClaimKind.WHY_NOW}
                )
                may_be_primary = (
                    candidate.citation_verified
                    and trusted_official_host
                    and candidate.source_type
                    in {EvidenceSourceType.PRIMARY_RELEASE, EvidenceSourceType.OFFICIAL_CLIP}
                    and content_bound_primary
                )
                if candidate.claim_kind is EvidenceClaimKind.VIEWER_DISCUSSION:
                    # A response-wide citation URL is not a fact binding. The
                    # adapter must have matched this particular minimal excerpt
                    # to sanitized visible text on the particular cited page.
                    verification = (
                        VerificationState.SECONDARY_CORROBORATED
                        if candidate.content_binding_verified
                        and verification
                        not in {
                            VerificationState.LEAD_ONLY,
                            VerificationState.STALE,
                            VerificationState.RETRACTED,
                        }
                        else VerificationState.LEAD_ONLY
                    )
                elif candidate.claim_kind is EvidenceClaimKind.QUOTE:
                    verification = (
                        VerificationState.PRIMARY_VERIFIED
                        if may_be_primary
                        else VerificationState.LEAD_ONLY
                    )
                elif candidate.claim_kind in {
                    EvidenceClaimKind.SCENE_CONTEXT,
                    EvidenceClaimKind.CAST_IDENTITY,
                    EvidenceClaimKind.OFFICIAL_CLIP,
                }:
                    verification = VerificationState.LEAD_ONLY
                elif candidate.claim_kind in {
                    EvidenceClaimKind.EPISODE_IDENTITY,
                    EvidenceClaimKind.WHY_NOW,
                } and not content_bound_primary:
                    verification = VerificationState.LEAD_ONLY
                elif verification not in {
                    VerificationState.LEAD_ONLY,
                    VerificationState.STALE,
                    VerificationState.RETRACTED,
                }:
                    verification = (
                        VerificationState.PRIMARY_VERIFIED
                        if may_be_primary
                        else VerificationState.SECONDARY_CORROBORATED
                    )
            elif provider == "xai":
                # URL/date tool metadata does not bind the model-authored
                # excerpt to that particular X post. Keep it a lead until a
                # live-tested per-post content verifier is introduced.
                verification = VerificationState.LEAD_ONLY
            claim_hash = _content_hash(
                {
                    "source_sha256": source_hash,
                    "claim_kind": candidate.claim_kind.value,
                    "excerpt_type": candidate.excerpt_type.value,
                    "excerpt": candidate.excerpt,
                    "event_or_release_at": (
                        candidate.event_or_release_at.isoformat()
                        if candidate.event_or_release_at
                        else None
                    ),
                    "episode_locator": (
                        candidate.episode_locator.model_dump(mode="json")
                        if candidate.episode_locator
                        else None
                    ),
                    "quote_fact": (
                        candidate.quote_fact.model_dump(mode="json")
                        if candidate.quote_fact
                        else None
                    ),
                    "why_now_event": (
                        candidate.why_now_event.model_dump(mode="json")
                        if candidate.why_now_event
                        else None
                    ),
                    "scene_fact": (
                        candidate.scene_fact.model_dump(mode="json")
                        if candidate.scene_fact
                        else None
                    ),
                    "cast_fact": (
                        candidate.cast_fact.model_dump(mode="json")
                        if candidate.cast_fact
                        else None
                    ),
                }
            )
            if claim_hash in seen_claim_hashes:
                continue
            seen_claim_hashes.add(claim_hash)
            claims.append(
                EvidenceClaimRecordV2(
                    claim_id=uuid_factory(),
                    source_id=source_id,
                    claim_kind=candidate.claim_kind,
                    excerpt_type=candidate.excerpt_type,
                    text=candidate.excerpt,
                    verification=verification,
                    episode_locator=candidate.episode_locator,
                    quote_fact=candidate.quote_fact,
                    why_now_event=candidate.why_now_event,
                    scene_fact=candidate.scene_fact,
                    cast_fact=candidate.cast_fact,
                    event_or_release_at=candidate.event_or_release_at,
                    confidence=candidate.confidence,
                    supports_why_now=(
                        candidate.supports_why_now
                        and verification is not VerificationState.LEAD_ONLY
                    ),
                    content_sha256=claim_hash,
                )
            )
    return sources, claims
