"""Official-channel YouTube metadata discovery; no media or transcript access."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
import re
from urllib.parse import urlencode

from ..contracts import EvidenceSourceType, ExcerptType, MediaKind, VerificationState
from ..m1_contracts import (
    EvidenceClaimKind,
    MediaIdentityV2,
    ResearchIntentV2,
    SceneMomentFactV2,
    WhyNowEventFactV2,
    WhyNowEventKind,
)
from ..research.intent import violates_exclusions
from .base import (
    EMPTY_PROVIDER_RESEARCH_CONTEXT,
    CallAuthorization,
    CallMeter,
    CancellationToken,
    EvidenceCandidate,
    ProviderBatch,
    ProviderError,
    ProviderLimitError,
    ProviderResearchContext,
    ProviderUsage,
    SecretCredential,
)
from .transport import JsonTransport, UrllibJsonTransport


class YouTubeOfficialProvider:
    name = "youtube"
    operation = "research.youtube"
    endpoint = "https://www.googleapis.com/youtube/v3/search"

    def __init__(
        self,
        *,
        credential: SecretCredential,
        official_channel_ids: tuple[str, ...],
        policy_class: str = "youtube-public-metadata-v1",
        transport: JsonTransport | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not official_channel_ids:
            raise ValueError("YouTube adapter requires configured official channel IDs")
        if len(set(official_channel_ids)) != len(official_channel_ids):
            raise ValueError("official YouTube channel IDs must be unique")
        self._credential = credential
        self._channel_ids = official_channel_ids
        if not policy_class:
            raise ValueError("YouTube policy class cannot be empty")
        self._policy_class = policy_class
        self._transport = transport or UrllibJsonTransport(max_attempts=1)
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def collect(
        self,
        intent: ResearchIntentV2,
        *,
        authorization: CallAuthorization,
        cancellation: CancellationToken,
        context: ProviderResearchContext = EMPTY_PROVIDER_RESEARCH_CONTEXT,
    ) -> ProviderBatch:
        meter = CallMeter(authorization)
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("YouTube clock must return a timezone-aware datetime")
        now = now.astimezone(timezone.utc)
        search_titles = _trusted_search_titles(
            context,
            intent=intent,
            now=now,
        )[: min(intent.max_results, 5)]
        if not search_titles:
            return ProviderBatch(
                provider=self.name,
                evidence=(),
                usage=ProviderUsage(
                    request_count=0,
                    input_tokens=0,
                    cached_input_tokens=0,
                    output_tokens=0,
                    reasoning_tokens=0,
                    quota_units=0,
                ),
                warnings=(
                    "YouTube official-video discovery was skipped because no current trusted title identity was available.",
                ),
            )
        if authorization.max_requests < len(search_titles):
            raise ProviderLimitError(
                "YouTube capability cannot cover every bounded trusted title"
            )
        cutoff = now - timedelta(days=intent.freshness_days)
        candidates: list[EvidenceCandidate] = []
        accepted_video_ids: set[str] = set()
        rejection_counts: dict[str, int] = {}
        collection_error: str | None = None

        def reject(reason: str) -> None:
            rejection_counts[reason] = rejection_counts.get(reason, 0) + 1

        for show_or_title in search_titles:
            cancellation.raise_if_cancelled()
            meter.begin_request(provider=self.name, operation=self.operation)
            params = {
                "part": "snippet",
                "type": "video",
                "maxResults": 10,
                "order": "date",
                "publishedAfter": cutoff.isoformat().replace("+00:00", "Z"),
                "q": f'"{_clean_query(show_or_title)}" official clip trailer scene'[:500],
            }
            try:
                response = self._transport.request_json(
                    method="GET",
                    url=f"{self.endpoint}?{urlencode(params)}",
                    headers={"X-Goog-Api-Key": self._credential.reveal_for_transport()},
                    body=None,
                    timeout_seconds=20,
                    max_response_bytes=2 * 1024 * 1024,
                    allowed_hosts=frozenset({"www.googleapis.com"}),
                )
            except ProviderError as error:
                # Official-video discovery is optional enrichment. Preserve
                # exact request accounting and the already-qualified research
                # slate when the metadata service/key/quota is unavailable;
                # never turn this into fabricated clip evidence.
                collection_error = str(error)[:300]
                break
            payload = response.payload
            if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
                continue
            for item in payload["items"]:
                if not isinstance(item, dict):
                    continue
                identity = item.get("id")
                snippet = item.get("snippet")
                if not isinstance(identity, dict) or not isinstance(snippet, dict):
                    continue
                video_id = identity.get("videoId")
                returned_channel_id = snippet.get("channelId")
                if (
                    not isinstance(video_id, str)
                    or not video_id
                    or video_id in accepted_video_ids
                    or returned_channel_id not in self._channel_ids
                ):
                    reject("unreviewed-or-duplicate-channel")
                    continue
                title = str(snippet.get("title") or "").strip()
                channel_title = str(snippet.get("channelTitle") or "").strip()
                published_at = _aware_datetime(snippet.get("publishedAt"))
                if not title or not channel_title or published_at is None:
                    reject("incomplete-metadata")
                    continue
                if violates_exclusions(f"{title} {channel_title}", intent):
                    reject("excluded")
                    continue
                if not _upload_title_binds_show(title, show_or_title):
                    reject("title-mismatch")
                    continue
                classified = _trusted_title_bound_upload(
                    title,
                    show_or_title=show_or_title,
                    channel_title=channel_title,
                )
                if classified is None:
                    reject("not-a-clip-or-trailer")
                    continue
                media_identity, event_kind, scene_fact = classified
                if not (cutoff <= published_at <= now):
                    reject("outside-freshness-window")
                    continue
                accepted_video_ids.add(video_id)
                candidates.append(
                    EvidenceCandidate(
                        provider=self.name,
                        provider_record_id=video_id,
                        source_type=EvidenceSourceType.OFFICIAL_CLIP,
                        canonical_url=f"https://www.youtube.com/watch?v={video_id}",
                        title=title,
                        author_or_channel=channel_title,
                        excerpt_type=ExcerptType.PARAPHRASE,
                        excerpt=(
                            f"Official channel {channel_title} published a title-bound "
                            f"video labeled: {title}."
                        ),
                        verification=VerificationState.PRIMARY_VERIFIED,
                        claim_kind=EvidenceClaimKind.OFFICIAL_CLIP,
                        supports_why_now=True,
                        policy_class=self._policy_class,
                        source_created_at=published_at,
                        page_published_at=published_at,
                        event_or_release_at=published_at,
                        query=intent.query,
                        window_start=cutoff,
                        window_end=now,
                        confidence=0.95,
                        adapter_origin_id=f"youtube-channel:{returned_channel_id}",
                        citation_verified=True,
                        why_now_event=WhyNowEventFactV2(
                            event_kind=event_kind,
                            media_identity=media_identity,
                        ),
                        scene_fact=scene_fact,
                    )
                )
        warnings = [
            "YouTube searched "
            f"{len(search_titles)} exact trusted title(s) and accepted only videos "
            "returned from the reviewed official-channel registry."
        ]
        if rejection_counts:
            warnings.append(
                "YouTube official-video validation omitted "
                + "; ".join(
                    f"{count} {reason}"
                    for reason, count in sorted(rejection_counts.items())
                )
                + "."
            )
        if collection_error is not None:
            warnings.append(
                "YouTube official-video discovery stopped after a bounded "
                f"metadata request failed: {collection_error}. The opportunity "
                "research remains usable, but no unverified video link was added."
            )
        request_count = meter.requests_used
        return ProviderBatch(
            provider=self.name,
            evidence=tuple(candidates),
            usage=ProviderUsage(
                request_count=request_count,
                input_tokens=0,
                cached_input_tokens=0,
                output_tokens=0,
                reasoning_tokens=0,
                # Since the June 2026 granular-quota transition, search.list
                # consumes one call from its own Search Queries bucket.
                quota_units=request_count,
                quota_unit_name="youtube_search_list_call",
            ),
            warnings=tuple(warnings),
        )


def _trusted_search_titles(
    context: ProviderResearchContext,
    *,
    intent: ResearchIntentV2,
    now: datetime,
) -> tuple[str, ...]:
    """Derive exact search selectors only from already trusted provider facts."""

    cutoff = now - timedelta(days=intent.freshness_days)
    titles: list[str] = []
    seen: set[str] = set()
    for candidate in context.prior_evidence:
        value: str | None = None
        if (
            candidate.provider == "tvmaze"
            and candidate.policy_class == "tvmaze-metadata-v1"
            and candidate.claim_kind is EvidenceClaimKind.EPISODE_IDENTITY
            and candidate.episode_locator is not None
            and candidate.citation_verified
            and candidate.event_or_release_at is not None
            and cutoff
            <= candidate.event_or_release_at
            <= now + timedelta(minutes=5)
            and MediaKind.TV_EPISODE in intent.media_kinds
        ):
            value = candidate.episode_locator.show_or_title
        elif (
            candidate.provider == "openai"
            and candidate.policy_class == "openai-web-evidence-v1"
            and candidate.claim_kind is EvidenceClaimKind.WHY_NOW
            and candidate.verification is VerificationState.PRIMARY_VERIFIED
            and candidate.why_now_event is not None
            and candidate.why_now_event.media_identity.media_kind in intent.media_kinds
            and candidate.content_binding_verified
            and candidate.citation_verified
            and candidate.event_or_release_at is not None
            and cutoff <= candidate.event_or_release_at <= now + timedelta(minutes=5)
        ):
            value = candidate.why_now_event.media_identity.show_or_title
        if value is None:
            continue
        key = _normalized_title(value)
        if key and key not in seen:
            seen.add(key)
            titles.append(value)
    return tuple(titles)


def _clean_query(value: str) -> str:
    return " ".join(value.replace('"', " ").split())


def _normalized_title(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())


def _upload_title_binds_show(upload_title: str, show_or_title: str) -> bool:
    expected = _normalized_title(show_or_title)
    actual = _normalized_title(upload_title)
    return bool(expected) and f" {expected} " in f" {actual} "


_TRAILER_TOKEN = re.compile(r"\b(?:teaser|trailer)\b", re.IGNORECASE)
_CLIP_TOKEN = re.compile(
    r"\b(?:clip|scene|sneak\s+peek|first\s+look|preview|opening|ending|finale)\b",
    re.IGNORECASE,
)
_NON_SCENE_PROMO = re.compile(
    r"\b(?:interview|featurette|behind\s+the\s+scenes|bloopers?|recap|explained|"
    r"cast\s+(?:game|reacts?)|soundtrack|music\s+video|podcast)\b",
    re.IGNORECASE,
)
_GENERIC_UPLOAD_LABEL = re.compile(
    r"^(?:official\s+)?(?:clip|scene|teaser|trailer|preview|first\s+look)$",
    re.IGNORECASE,
)


def _trusted_title_bound_upload(
    upload_title: str,
    *,
    show_or_title: str,
    channel_title: str,
) -> tuple[MediaIdentityV2, WhyNowEventKind, SceneMomentFactV2 | None] | None:
    """Classify one official-channel result without inspecting audiovisual media."""

    if _NON_SCENE_PROMO.search(upload_title):
        return None
    if _TRAILER_TOKEN.search(upload_title):
        return (
            MediaIdentityV2(
                media_kind=MediaKind.TRAILER,
                show_or_title=show_or_title,
            ),
            WhyNowEventKind.TRAILER_RELEASE,
            None,
        )
    label = _specific_upload_label(
        upload_title,
        show_or_title=show_or_title,
        channel_title=channel_title,
    )
    if not _CLIP_TOKEN.search(upload_title) and label is None:
        return None
    scene_fact = (
        SceneMomentFactV2(
            show_or_title=show_or_title,
            description=f'Official upload labeled “{label}”',
            relationship_or_topic=label,
        )
        if label is not None
        else None
    )
    return (
        MediaIdentityV2(
            media_kind=MediaKind.OFFICIAL_CLIP,
            show_or_title=show_or_title,
        ),
        WhyNowEventKind.OFFICIAL_CLIP_RELEASE,
        scene_fact,
    )


def _specific_upload_label(
    upload_title: str,
    *,
    show_or_title: str,
    channel_title: str,
) -> str | None:
    """Extract a source-owned scene label while dropping show/channel boilerplate."""

    parts = [
        " ".join(value.split()).strip(" -–—:|[]()")
        for value in re.split(r"\s*(?:\||—|–)\s*", upload_title)
    ]
    expected = _normalized_title(show_or_title)
    channel = _normalized_title(channel_title)
    candidates: list[str] = []
    for part in parts:
        normalized = _normalized_title(part)
        if not normalized or normalized in {expected, channel}:
            continue
        cleaned = re.sub(
            r"^(?:official\s+)?(?:clip|scene|preview|first\s+look)\s*[:\-]?\s*",
            "",
            part,
            flags=re.IGNORECASE,
        ).strip(" -–—:|[]()")
        # A common official format is "Show Title: scene label".
        if _normalized_title(cleaned).startswith(f"{expected} "):
            for separator in (":", " - "):
                if separator in cleaned:
                    prefix, suffix = cleaned.split(separator, 1)
                    if _normalized_title(prefix) == expected:
                        cleaned = suffix.strip()
                        break
        if (
            len(cleaned) < 4
            or len(cleaned) > 200
            or _GENERIC_UPLOAD_LABEL.fullmatch(cleaned)
            or _NON_SCENE_PROMO.search(cleaned)
            or _normalized_title(cleaned) in {expected, channel}
        ):
            continue
        candidates.append(cleaned)
    return candidates[0] if candidates else None


def _aware_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


_OFFICIAL_UPLOAD = re.compile(
    r"^(?P<title>.+?)\s*(?:\||—|–|:)\s*official\s+"
    r"(?P<kind>teaser\s+trailer|trailer|clip)\b",
    re.IGNORECASE,
)


def _trusted_upload_identity(
    upload_title: str,
) -> tuple[MediaIdentityV2 | None, WhyNowEventKind | None]:
    """Parse only a narrow conventional title emitted by an allow-listed channel."""

    match = _OFFICIAL_UPLOAD.search(upload_title.strip())
    if match is None:
        return None, None
    underlying_title = " ".join(match.group("title").split()).strip(" -–—:|")
    if not underlying_title:
        return None, None
    if "trailer" in match.group("kind").casefold():
        return (
            MediaIdentityV2(media_kind=MediaKind.TRAILER, show_or_title=underlying_title),
            WhyNowEventKind.TRAILER_RELEASE,
        )
    return (
        MediaIdentityV2(media_kind=MediaKind.OFFICIAL_CLIP, show_or_title=underlying_title),
        WhyNowEventKind.OFFICIAL_CLIP_RELEASE,
    )
