"""TVmaze broadcast/web release, episode, cast, and official-site metadata."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
import html
import re
from urllib.parse import urlencode

from ..contracts import EvidenceSourceType, ExcerptType, MediaKind, VerificationState
from ..m1_contracts import (
    CastIdentityFactV2,
    EpisodeLocatorFactV2,
    EvidenceClaimKind,
    MAX_SEASON_NUMBER,
    ResearchIntentV2,
)
from ..research.intent import preferred_freshness_days, violates_exclusions
from ..research.urls import canonical_host
from .base import (
    EMPTY_PROVIDER_RESEARCH_CONTEXT,
    CallAuthorization,
    CallMeter,
    CancellationToken,
    EvidenceCandidate,
    MAX_M11_TVMAZE_DISCOVERY_SHOWS,
    MAX_TVMAZE_CAST_SHOWS,
    MAX_TVMAZE_DISCOVERY_SHOWS,
    ProviderCandidateFunnel,
    ProviderCandidateTrace,
    ProviderBatch,
    ProviderLimitError,
    ProviderResearchContext,
    ProviderUsage,
)
from .transport import JsonTransport, UrllibJsonTransport


_FOCUS_GENRES: dict[str, frozenset[str]] = {
    "action": frozenset({"action"}),
    "adventure": frozenset({"adventure"}),
    "anime": frozenset({"anime"}),
    "comedy": frozenset({"comedy"}),
    "crime": frozenset({"crime"}),
    "documentary": frozenset({"documentary"}),
    "drama": frozenset({"drama"}),
    "family": frozenset({"family"}),
    "fantasy": frozenset({"fantasy"}),
    "horror": frozenset({"horror"}),
    "mystery": frozenset({"mystery"}),
    "romance": frozenset({"romance"}),
    "romantic": frozenset({"romance"}),
    "science fiction": frozenset({"science fiction"}),
    "sci fi": frozenset({"science fiction"}),
    "scifi": frozenset({"science fiction"}),
    "thriller": frozenset({"thriller"}),
}
_FEMALE_CENTERED_FOCUS = "female centered"
_FEMALE_CENTERED_NOUN = re.compile(
    r"\b(?:girl|girls|woman|women|female|sister|sisters|daughter|daughters|"
    r"mother|mothers|wife|wives|girlfriend|girlfriends)\b",
    re.IGNORECASE,
)
_FEMALE_CENTERED_PRONOUN = re.compile(r"\b(?:she|her|hers)\b", re.IGNORECASE)


class TVmazeProvider:
    name = "tvmaze"
    operation = "research.metadata"
    endpoint = "https://api.tvmaze.com/schedule"
    web_endpoint = "https://api.tvmaze.com/schedule/web"

    def __init__(
        self,
        *,
        policy_class: str = "tvmaze-metadata-v1",
        transport: JsonTransport | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        # One HTTP attempt keeps capability/request accounting exact. The
        # transport's retry implementation is tested separately and can only be
        # enabled when Rust reserves attempts rather than logical calls.
        self._transport = transport or UrllibJsonTransport(max_attempts=1)
        if not policy_class:
            raise ValueError("TVmaze policy class cannot be empty")
        self._policy_class = policy_class
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def collect(
        self,
        intent: ResearchIntentV2,
        *,
        authorization: CallAuthorization,
        cancellation: CancellationToken,
        context: ProviderResearchContext = EMPTY_PROVIDER_RESEARCH_CONTEXT,
    ) -> ProviderBatch:
        del context
        meter = CallMeter(authorization)
        if not any(
            media_kind in {MediaKind.TV_EPISODE, MediaKind.TV_SERIES}
            for media_kind in intent.media_kinds
        ):
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
                    "TVmaze was skipped because this request contains no television media kind.",
                ),
            )
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("TVmaze clock must return a timezone-aware datetime")
        now = now.astimezone(timezone.utc)
        freshness_cutoff = now - timedelta(days=intent.freshness_days)
        # TVmaze exposes calendar-day schedules while the research contract
        # defines freshness as a rolling duration. Querying only N calendar
        # dates drops the oldest partial day (for example, an episode from 71
        # hours ago during a three-day request). Include that boundary date,
        # then enforce the exact rolling cutoff on every returned airstamp.
        day_count = min(intent.freshness_days, 14) + 1
        schedule_requests: list[tuple[str, dict[str, str]]] = []
        for offset in range(day_count):
            day = (now - timedelta(days=offset)).date().isoformat()
            schedule_requests.append((self.endpoint, {"country": intent.region, "date": day}))
            schedule_requests.append((self.web_endpoint, {"date": day}))
        # Schedule responses already contain every episode candidate.  Cast
        # enrichment is the only per-show request and remains separately
        # bounded; output-card count must not collapse discovery to five rows.
        worst_case_requests = len(schedule_requests) + MAX_TVMAZE_CAST_SHOWS
        if authorization.max_requests < worst_case_requests:
            raise ProviderLimitError(
                f"TVmaze capability allows {authorization.max_requests} requests but "
                f"{worst_case_requests} are required for complete bounded schedule/cast coverage"
            )

        candidates: list[EvidenceCandidate] = []
        episode_candidates_by_show: dict[int, list[EvidenceCandidate]] = {}
        seen_episode_ids: set[str] = set()
        show_names: dict[int, str] = {}
        show_official_hosts: dict[int, str] = {}
        show_region_affinity: dict[int, int] = {}
        show_focus_affinity: dict[int, int] = {}
        show_creative_affinity: dict[int, int] = {}
        show_episode_title_affinity: dict[int, int] = {}
        show_provider_weight: dict[int, int] = {}
        raw_release_keys: set[str] = set()
        fresh_release_keys: set[str] = set()
        exclusion_survivor_keys: set[str] = set()
        audience_survivor_keys: set[str] = set()
        for endpoint, params in schedule_requests:
            cancellation.raise_if_cancelled()
            meter.begin_request(provider=self.name, operation=self.operation)
            response = self._transport.request_json(
                method="GET",
                url=f"{endpoint}?{urlencode(params)}",
                headers={"User-Agent": "AIEditMachine/0.1 (TVmaze attribution in UI)"},
                body=None,
                timeout_seconds=15,
                max_response_bytes=2 * 1024 * 1024,
                allowed_hosts=frozenset({"api.tvmaze.com"}),
            )
            if not isinstance(response.payload, list):
                continue
            for row in response.payload:
                if not isinstance(row, dict):
                    continue
                embedded = row.get("_embedded")
                show = row.get("show")
                if not isinstance(show, dict) and isinstance(embedded, dict):
                    show = embedded.get("show")
                if not isinstance(show, dict):
                    continue
                show_name = str(show.get("name") or "").strip()
                episode_name = str(row.get("name") or "").strip()
                if (
                    not show_name
                    or not episode_name
                ):
                    continue
                show_id = show.get("id")
                if not isinstance(show_id, int):
                    continue
                season, number = row.get("season"), row.get("number")
                if (
                    not isinstance(season, int)
                    or not 0 <= season <= MAX_SEASON_NUMBER
                    or not isinstance(number, int)
                    or not 1 <= number <= 9_999
                ):
                    continue
                canonical_url = row.get("url")
                if not isinstance(canonical_url, str) or not canonical_url.startswith("https://"):
                    continue
                record_id = row.get("id")
                record_key = str(record_id) if record_id is not None else canonical_url
                raw_release_keys.add(record_key)
                event_at = _aware_datetime(row.get("airstamp"))
                # A calendar-day schedule endpoint includes episodes that have
                # not aired yet.  M1 freshness means already-released material;
                # future rows cannot support a "new episode from the last N
                # days" request and would later fail the evidence gate anyway.
                if (
                    event_at is None
                    or event_at < freshness_cutoff
                    or event_at > now + timedelta(minutes=5)
                ):
                    continue
                fresh_release_keys.add(record_key)
                if _show_is_excluded(show, show_name, intent):
                    continue
                exclusion_survivor_keys.add(record_key)
                if not _show_matches_focus(show, show_name, intent):
                    continue
                audience_survivor_keys.add(record_key)
                if record_key in seen_episode_ids:
                    continue
                seen_episode_ids.add(record_key)
                try:
                    locator = EpisodeLocatorFactV2(
                        show_or_title=show_name,
                        season_number=season,
                        episode_number=number,
                        episode_title=episode_name,
                    )
                except (TypeError, ValueError):
                    # Public metadata is untrusted input.  One out-of-contract
                    # row must not abort an otherwise usable bounded schedule.
                    continue
                candidate = EvidenceCandidate(
                        provider=self.name,
                        provider_record_id=str(record_id) if record_id is not None else None,
                        source_type=EvidenceSourceType.METADATA,
                        canonical_url=canonical_url,
                        title=f"{show_name} — S{season:02d}E{number:02d}: {episode_name}",
                        author_or_channel="TVmaze",
                        excerpt_type=ExcerptType.PARAPHRASE,
                        excerpt=f"TVmaze lists {episode_name} as Season {season} Episode {number}.",
                        verification=VerificationState.SECONDARY_CORROBORATED,
                        claim_kind=EvidenceClaimKind.EPISODE_IDENTITY,
                        supports_why_now=False,
                        policy_class=self._policy_class,
                        event_or_release_at=event_at,
                        query=intent.query,
                        window_start=freshness_cutoff,
                        window_end=now,
                        confidence=0.9,
                        citation_verified=True,
                        episode_locator=locator,
                    )
                show_names[show_id] = show_name
                show_region_affinity[show_id] = max(
                    show_region_affinity.get(show_id, 0),
                    _region_affinity(
                        show,
                        intent,
                        country_schedule=endpoint == self.endpoint,
                    ),
                )
                show_focus_affinity[show_id] = max(
                    show_focus_affinity.get(show_id, 0),
                    _focus_affinity(show, show_name, intent),
                )
                show_creative_affinity[show_id] = max(
                    show_creative_affinity.get(show_id, 0),
                    _creative_edit_metadata_affinity(show, intent),
                )
                show_episode_title_affinity[show_id] = max(
                    show_episode_title_affinity.get(show_id, 0),
                    _episode_title_affinity(episode_name),
                )
                show_provider_weight[show_id] = max(
                    show_provider_weight.get(show_id, 0),
                    _provider_weight(show),
                )
                official_site = show.get("officialSite")
                if isinstance(official_site, str):
                    try:
                        show_official_hosts[show_id] = canonical_host(official_site)
                    except ValueError:
                        pass
                episode_candidates_by_show.setdefault(show_id, []).append(candidate)

        ranked_show_ids = sorted(
            episode_candidates_by_show,
            key=lambda show_id: (
                # An explicit title request remains stronger than a default
                # market preference. Genre-only prompts, however, must not let
                # an obscure global dual-genre row crowd every requested-market
                # candidate out of the verifier slate.
                int(show_focus_affinity[show_id] >= 4),
                show_creative_affinity[show_id],
                show_episode_title_affinity[show_id],
                show_focus_affinity[show_id],
                # TVmaze's bounded weight is a discovery/evidenceability hint,
                # not evidence or an opportunity score. Use a coarse band so
                # tiny provider-order differences cannot erase market affinity.
                show_provider_weight[show_id] // 10,
                show_region_affinity[show_id],
                int(show_id in show_official_hosts),
                show_provider_weight[show_id],
                max(
                    _candidate_recency_key(item)
                    for item in episode_candidates_by_show[show_id]
                ),
                show_names[show_id].casefold(),
                show_id,
            ),
            reverse=True,
        )
        female_audience_prior = _FEMALE_CENTERED_FOCUS in {
            _normalized_label(value) for value in intent.focus_terms
        }
        discovery_show_limit = (
            MAX_M11_TVMAZE_DISCOVERY_SHOWS
            if _has_editability_intent(intent)
            and intent.interpretation is not None
            and intent.interpretation.broad_query
            else MAX_TVMAZE_DISCOVERY_SHOWS
        )
        if female_audience_prior and _has_editability_intent(intent):
            # Six audience-prioritized slots plus two broad scripted/editable
            # slots feed the eight-title deep verifier. This keeps the exact
            # audience request influential without making gender a genre
            # exclusion or hiding a male-led title with a strong fandom.
            selected_show_ids = list(ranked_show_ids[:6])
            broad_ranked = sorted(
                episode_candidates_by_show,
                key=lambda show_id: (
                    show_creative_affinity[show_id],
                    show_provider_weight[show_id] // 10,
                    show_region_affinity[show_id],
                    int(show_id in show_official_hosts),
                    show_provider_weight[show_id],
                    max(
                        _candidate_recency_key(item)
                        for item in episode_candidates_by_show[show_id]
                    ),
                    show_names[show_id].casefold(),
                    show_id,
                ),
                reverse=True,
            )
            for show_id in broad_ranked:
                if show_id not in selected_show_ids:
                    selected_show_ids.append(show_id)
                if len(selected_show_ids) >= 8:
                    break
            for show_id in ranked_show_ids:
                if show_id not in selected_show_ids:
                    selected_show_ids.append(show_id)
                if len(selected_show_ids) >= discovery_show_limit:
                    break
        else:
            selected_show_ids = ranked_show_ids[:discovery_show_limit]
        # Every selected episode is useful as an immutable verifier target.
        # Cast enrichment is helpful but more expensive, so only the strongest
        # bounded subset receives the additional per-show request below.
        for show_id in selected_show_ids:
            candidates.append(
                max(
                    episode_candidates_by_show[show_id],
                    key=lambda item: (
                        _candidate_recency_key(item),
                        item.canonical_url,
                    ),
                )
            )

        trusted_official_hosts = {
            show_official_hosts[show_id]
            for show_id in selected_show_ids
            if show_id in show_official_hosts
        }

        for show_id in selected_show_ids[:MAX_TVMAZE_CAST_SHOWS]:
            show_name = show_names[show_id]
            cast_source_url = f"https://api.tvmaze.com/shows/{show_id}/cast"
            cast_source_id = _cast_provider_record_id(show_id=show_id)
            cancellation.raise_if_cancelled()
            meter.begin_request(provider=self.name, operation=self.operation)
            response = self._transport.request_json(
                method="GET",
                url=cast_source_url,
                headers={"User-Agent": "AIEditMachine/0.1 (TVmaze attribution in UI)"},
                body=None,
                timeout_seconds=15,
                max_response_bytes=2 * 1024 * 1024,
                allowed_hosts=frozenset({"api.tvmaze.com"}),
            )
            if not isinstance(response.payload, list):
                continue
            for row in response.payload[:10]:
                if not isinstance(row, dict):
                    continue
                person, character = row.get("person"), row.get("character")
                if not isinstance(person, dict) or not isinstance(character, dict):
                    continue
                person_id = person.get("id")
                performer_name = str(person.get("name") or "").strip()
                character_name = str(character.get("name") or "").strip()
                if (
                    isinstance(person_id, bool)
                    or not isinstance(person_id, int)
                    or person_id <= 0
                    or not performer_name
                    or not character_name
                ):
                    continue
                try:
                    cast_fact = CastIdentityFactV2(
                        show_or_title=show_name,
                        character_name=character_name,
                        performer_name=performer_name,
                    )
                except (TypeError, ValueError):
                    continue
                candidates.append(
                    EvidenceCandidate(
                        provider=self.name,
                        # This source is the show-level cast response for one of the selected
                        # shows.  The cast appearance—not the person page alone—
                        # is represented by a distinct claim within that shared show source.
                        provider_record_id=cast_source_id,
                        source_type=EvidenceSourceType.METADATA,
                        canonical_url=cast_source_url,
                        title=f"{show_name} cast listing",
                        author_or_channel="TVmaze",
                        excerpt_type=ExcerptType.PARAPHRASE,
                        excerpt=f"TVmaze lists {performer_name} as {character_name} in {show_name}.",
                        verification=VerificationState.SECONDARY_CORROBORATED,
                        claim_kind=EvidenceClaimKind.CAST_IDENTITY,
                        supports_why_now=False,
                        policy_class=self._policy_class,
                        query=intent.query,
                        window_start=freshness_cutoff,
                        window_end=now,
                        confidence=0.9,
                        citation_verified=True,
                        cast_fact=cast_fact,
                    )
                )

        warnings: list[str] = []
        preferred_days = preferred_freshness_days(intent.query)
        if preferred_days is not None and intent.freshness_days > preferred_days:
            warnings.append(
                f"The requested {preferred_days}-day timing was treated as a preference; "
                f"discovery used a bounded {intent.freshness_days}-day fallback window and "
                "still ranks newer releases first."
            )
        if intent.freshness_days > 14:
            warnings.append(
                "TVmaze schedule coverage is bounded to the newest fourteen days; older parts of "
                "the requested window require other evidence providers."
            )
        if len(episode_candidates_by_show) > discovery_show_limit:
            warnings.append(
                f"TVmaze found {len(episode_candidates_by_show)} matching current shows; "
                f"the {discovery_show_limit} strongest metadata candidates were sent "
                "to evidence verification."
            )
        if female_audience_prior and _has_editability_intent(intent):
            warnings.append(
                "TVmaze used female-audience intent as a soft priority for six deep-search "
                "slots and preserved two broad scripted/editable slots; no genre was "
                "hard-excluded by audience intent."
            )
        return ProviderBatch(
            provider=self.name,
            evidence=tuple(candidates),
            usage=ProviderUsage(
                request_count=meter.requests_used,
                input_tokens=0,
                cached_input_tokens=0,
                output_tokens=0,
                reasoning_tokens=0,
                quota_units=meter.requests_used,
                quota_unit_name="tvmaze_request" if meter.requests_used else None,
            ),
            warnings=tuple(warnings),
            attributions=("TV metadata: TVmaze (CC BY-SA) — https://www.tvmaze.com/api",),
            trusted_official_hosts=tuple(sorted(trusted_official_hosts)),
            candidate_funnel=ProviderCandidateFunnel(
                raw_release_candidates=len(raw_release_keys),
                candidates_after_freshness=len(fresh_release_keys),
                candidates_after_hard_exclusions=len(exclusion_survivor_keys),
                candidates_after_audience_fit_screening=len(audience_survivor_keys),
                candidates_selected_for_social_research=len(selected_show_ids),
                candidate_traces=tuple(
                    ProviderCandidateTrace(
                        candidate_name=(
                            f"{show_names[show_id]} — "
                            f"S{candidate.episode_locator.season_number:02d}"
                            f"E{candidate.episode_locator.episode_number:02d} "
                            f"{candidate.episode_locator.episode_title or ''}"
                        ).strip(),
                        title=show_names[show_id],
                        shortlist_rank=index,
                        shortlist_reason=(
                            "Selected by the female-audience soft-prior plus editability metadata ordering."
                            if female_audience_prior and _has_editability_intent(intent) and index <= 6
                            else "Selected by the broad scripted/editability metadata ordering; audience intent was not a hard genre filter."
                            if female_audience_prior and _has_editability_intent(intent)
                            else "Selected by deterministic metadata relevance, market, recency, and evidenceability ordering."
                        ),
                        season_number=candidate.episode_locator.season_number,
                        episode_number=candidate.episode_locator.episode_number,
                        episode_title=candidate.episode_locator.episode_title,
                    )
                    for index, show_id in enumerate(selected_show_ids, start=1)
                    for candidate in [
                        max(
                            episode_candidates_by_show[show_id],
                            key=lambda item: (
                                _candidate_recency_key(item),
                                item.canonical_url,
                            ),
                        )
                    ]
                    if candidate.episode_locator is not None
                ),
            ),
        )


def _show_is_excluded(show: dict[str, object], show_name: str, intent: ResearchIntentV2) -> bool:
    genres = [str(value) for value in show.get("genres", []) if value] if isinstance(
        show.get("genres"), list
    ) else []
    show_type = str(show.get("type") or "")
    language = str(show.get("language") or "")
    network = show.get("network") or show.get("webChannel")
    country_name = ""
    country_code = ""
    if isinstance(network, dict) and isinstance(network.get("country"), dict):
        country = network["country"]
        country_name = str(country.get("name") or "")
        country_code = str(country.get("code") or "")
    trusted_classes: list[str] = []
    if language.casefold() == "korean" or country_code.casefold() == "kr" or country_name.casefold() == "south korea":
        trusted_classes.append("Korean drama")
    if show_type.casefold() == "reality":
        trusted_classes.append("reality TV")
    if show_type.casefold() in {"game show", "competition"} or any(
        value.casefold() in {"game show", "competition"} for value in genres
    ):
        trusted_classes.append("competition shows")
    return violates_exclusions(
        " ".join([show_name, show_type, language, country_name, country_code, *genres, *trusted_classes]),
        intent,
    )


def _show_matches_focus(
    show: dict[str, object], show_name: str, intent: ResearchIntentV2
) -> bool:
    """Use only trusted title/genre metadata for recognized genre narrowing.

    Character, relationship, and free-form topic terms often do not appear in
    TVmaze's show-level fields.  When no recognized genre is present, retain
    broad metadata coverage and leave semantic relevance to the evidence gate.
    """

    return _focus_affinity(show, show_name, intent) > 0


def _focus_affinity(
    show: dict[str, object], show_name: str, intent: ResearchIntentV2
) -> int:
    """Rank exact title/multi-genre matches without making them evidence.

    This score is only a bounded discovery-order hint.  It never enters the
    opportunity score or promotes TVmaze metadata through the evidence gate.
    """

    normalized_title = _normalized_label(show_name)
    normalized_focus = [_normalized_label(value) for value in intent.focus_terms]
    genre_labels = frozenset(
        {*_FOCUS_GENRES, "romcom", "rom com", _FEMALE_CENTERED_FOCUS}
    )
    title_score = 4 if any(
        value and value not in genre_labels and value in normalized_title
        for value in normalized_focus
    ) else 0
    genres = _trusted_metadata_topics(show, show_name)
    female_centered_requested = _FEMALE_CENTERED_FOCUS in normalized_focus
    female_centered_score = _female_centered_metadata_affinity(show, show_name)
    # Audience intent is a soft discovery prior, never a genre stereotype or
    # hard metadata exclusion. A male-led comedy or science-fiction title can
    # still qualify later when current fandom, shipping, character, or edit
    # evidence supports it. Unknown TVmaze summaries therefore remain in the
    # recall pool but receive no audience-prior boost.
    recognized: set[frozenset[str]] = set()
    for value in normalized_focus:
        if value in _FOCUS_GENRES:
            recognized.add(_FOCUS_GENRES[value])
        elif value in {"romcom", "rom com"}:
            recognized.add(frozenset({"romance", "comedy"}))
    if not recognized:
        return max(1, title_score) + female_centered_score
    # Slash-separated or repeated genre terms are alternatives in the user's
    # natural prompt, not an instruction to triple-rank the same Romance label.
    # A standalone "romcom" still requires both Romance and Comedy because its
    # only recognized group contains both values.
    # Reward the most specific satisfied genre expression once. For example,
    # ``romance/romcom`` ranks a true Comedy+Romance show above a generic
    # Romance drama, while repeated Romance aliases cannot stack points.
    genre_specificity = max(
        (len(required) for required in recognized if required.issubset(genres)),
        default=0,
    )
    return title_score + genre_specificity + female_centered_score


def _female_centered_metadata_affinity(
    show: dict[str, object], show_name: str
) -> int:
    """Return a bounded discovery hint from TVmaze-owned title/summary text.

    The score describes a female-centered premise, not a claim about what all
    girls or women should enjoy.  Explicit nouns are strongest; repeated
    source-owned feminine pronouns are a narrower fallback for summaries that
    introduce a named protagonist without saying "girl" or "woman".
    """

    summary = show.get("summary")
    summary_text = str(summary) if isinstance(summary, str) else ""
    visible = html.unescape(re.sub(r"<[^>]*>", " ", summary_text))
    searchable = f"{show_name} {visible}"
    if _FEMALE_CENTERED_NOUN.search(searchable):
        return 3
    if len(_FEMALE_CENTERED_PRONOUN.findall(visible)) >= 2:
        return 2
    return 0


def _has_editability_intent(intent: ResearchIntentV2) -> bool:
    interpretation = intent.interpretation
    if interpretation is None:
        return False
    return any(
        facet.facet_id
        in {
            "short_form_edit_potential",
            "active_fan_edit_culture",
            "character_edit",
            "relationship_edit",
            "heartbreaking_edit",
            "aggressive_edit",
        }
        for facet in interpretation.facets
    )


def _creative_edit_metadata_affinity(
    show: dict[str, object], intent: ResearchIntentV2
) -> int:
    """Prefer story-bearing candidates only when the request asks for an edit.

    This is a recall-order hint from TVmaze-owned type/genre metadata. It does
    not establish audience fit, fandom activity, a relationship, or a usable
    concept, and it never removes documentary/reality/news candidates.
    """

    if not _has_editability_intent(intent):
        return 0
    show_type = _normalized_label(str(show.get("type") or ""))
    topics = _trusted_metadata_topics(show, str(show.get("name") or ""))
    type_score = {
        "scripted": 4,
        "animation": 3,
        "reality": 1,
        "documentary": 0,
        "news": 0,
        "sports": 0,
        "talk show": 0,
        "game show": 0,
    }.get(show_type, 1)
    narrative_topics = {
        "action",
        "adventure",
        "comedy",
        "crime",
        "drama",
        "fantasy",
        "horror",
        "mystery",
        "romance",
        "science fiction",
        "thriller",
    }
    return type_score + min(2, len(topics & narrative_topics))


def _trusted_metadata_topics(show: dict[str, object], show_name: str) -> set[str]:
    """Recover coarse genre topics from TVmaze-owned title/summary metadata.

    TVmaze occasionally labels an overt romance only as ``Drama``. Its public
    show summary is still trusted metadata, so bounded token matching can keep
    that show in discovery without treating the summary as instructions or as
    evidence for a final opportunity.
    """

    raw_genres = show.get("genres")
    topics = {
        _normalized_label(str(value))
        for value in raw_genres
        if value
    } if isinstance(raw_genres, list) else set()
    summary = show.get("summary")
    summary_text = str(summary) if isinstance(summary, str) else ""
    visible = html.unescape(re.sub(r"<[^>]*>", " ", summary_text))
    searchable = f" {_normalized_label(f'{show_name} {visible}')} "
    canonical_topics = {
        topic
        for values in _FOCUS_GENRES.values()
        for topic in values
    }
    for topic in canonical_topics:
        if f" {topic} " in searchable:
            topics.add(topic)
    if re.search(r"\b(?:romance|romances|romantic|love\s+triangle)\b", searchable):
        topics.add("romance")
    if re.search(r"\b(?:comedy|comedic|comic|funny|humou?r)\b", searchable):
        topics.add("comedy")
    return topics


_GENERIC_EPISODE_TITLE = re.compile(
    r"^(?:episode|ep\.?|chapter|part|folge|seria|bölüm)\s*#?\s*\d+\b",
    re.IGNORECASE,
)


def _episode_title_affinity(value: str) -> int:
    """Prefer searchable named episodes over opaque sequence labels."""

    return 0 if _GENERIC_EPISODE_TITLE.match(value.strip()) else 1


def _provider_weight(show: dict[str, object]) -> int:
    """Use TVmaze's bounded metadata weight only as a discovery tie-breaker."""

    value = show.get("weight")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return max(0, min(int(value), 1_000))


def _region_affinity(
    show: dict[str, object],
    intent: ResearchIntentV2,
    *,
    country_schedule: bool,
) -> int:
    """Prefer the requested market without erasing global streaming candidates."""

    country_codes: set[str] = set()
    for field in ("network", "webChannel"):
        channel = show.get(field)
        if not isinstance(channel, dict):
            continue
        country = channel.get("country")
        if not isinstance(country, dict):
            continue
        code = str(country.get("code") or "").upper()
        if code:
            country_codes.add(code)
    if intent.region.upper() in country_codes:
        return 3
    if country_schedule:
        return 2
    if not country_codes:
        return 1
    return 0


def _normalized_label(value: str) -> str:
    return " ".join(
        value.casefold().replace("-", " ").replace("_", " ").split()
    )


def _cast_provider_record_id(
    *,
    show_id: int,
) -> str:
    """Return the stable identity of one TVmaze show-cast source."""

    if isinstance(show_id, bool) or not isinstance(show_id, int) or show_id <= 0:
        raise ValueError("TVmaze show ID must be a positive integer")
    return f"show-cast:{show_id}"


def _aware_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _candidate_recency_key(candidate: EvidenceCandidate) -> datetime:
    return candidate.event_or_release_at or datetime.min.replace(tzinfo=timezone.utc)
