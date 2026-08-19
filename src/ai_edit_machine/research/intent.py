"""Deterministic preservation of explicit constraints around model parsing."""

from __future__ import annotations

import re
import unicodedata

from ..contracts import MediaKind, SpoilerPolicy
from ..m1_contracts import ResearchIntentV2


_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}
_FRESHNESS = re.compile(
    r"(?:last|past|within)\s+(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)\s+days?",
    re.IGNORECASE,
)
_PREFERRED_FRESHNESS = re.compile(
    r"\b(?:preferably|ideally|if\s+possible)\b[^,;.]{0,100}"
    r"\b(?:last|past|within)\s+"
    r"(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)\s+days?",
    re.IGNORECASE,
)
_PREFERENCE_FALLBACK_DAYS = 14
_EXCLUSION = re.compile(
    r"(?:^|[,;])\s*(?:no|without|exclude|excluding)\s+([^,;]+)", re.IGNORECASE
)
_MAX_AGE = re.compile(
    r"more\s+than\s+(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)\s+days?\s+ago",
    re.IGNORECASE,
)
_MAX_RESULTS = re.compile(
    r"(?:up\s+to|maximum|max)\s+(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)",
    re.IGNORECASE,
)
_FIND_COUNT = re.compile(
    r"\b(?:find|give\s+me|return|show\s+me)\s+(?:exactly\s+|up\s+to\s+)?"
    r"(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)\b",
    re.IGNORECASE,
)
_FOCUS_TERMS = (
    "romance",
    "romcom",
    "comedy",
    "drama",
    "fantasy",
    "horror",
    "thriller",
    "sci-fi",
    "action",
    "anime",
)
_FEMALE_CENTERED_FOCUS = "female-centered"
_FEMALE_AUDIENCE = re.compile(
    r"(?:\b(?:for|aimed\s+at|geared\s+(?:to|toward)|made\s+for)\s+"
    r"(?:girls?|women|female\s+(?:viewers?|audiences?))\b|"
    r"\b(?:girl|girls|woman|women|female)[\s-]*(?:focused|cent(?:er|re)d|led)\b)",
    re.IGNORECASE,
)
_REGIONS = {
    "us": "US",
    "u s": "US",
    "usa": "US",
    "united states": "US",
    "uk": "GB",
    "u k": "GB",
    "united kingdom": "GB",
    "canada": "CA",
    "australia": "AU",
}


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = " ".join(value.split()).strip(" .")
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def explicit_exclusions(query: str) -> list[str]:
    values: list[str] = []
    continuing = False
    for raw_clause in re.split(r"[,;]", query):
        clause = raw_clause.strip()
        marker = re.match(r"^(no|without|exclude|excluding)\s+(.+)$", clause, re.IGNORECASE)
        if marker:
            values.extend(re.split(r"\s+(?:and|or)\s+", marker.group(2), flags=re.IGNORECASE))
            continuing = marker.group(1).casefold() in {"without", "exclude", "excluding"}
        elif continuing:
            clause = re.sub(r"^and\s+", "", clause, flags=re.IGNORECASE)
            if not _MAX_AGE.search(clause) and not _FRESHNESS.search(clause):
                values.extend(re.split(r"\s+(?:and|or)\s+", clause, flags=re.IGNORECASE))
    return _dedupe(values)


def intent_from_query(query: str, *, region: str = "US") -> ResearchIntentV2:
    """Build a conservative local intent before an optional model refinement."""

    lowered = query.casefold()
    media_kinds: list[MediaKind] = []
    if "episode" in lowered:
        media_kinds.append(MediaKind.TV_EPISODE)
    elif any(token in lowered for token in ("tv", "show", "series")):
        media_kinds.append(MediaKind.TV_EPISODE)
    if any(token in lowered for token in ("film", "movie")):
        media_kinds.append(MediaKind.FILM)
    if "trailer" in lowered:
        media_kinds.append(MediaKind.TRAILER)
    if not media_kinds:
        if "relationship" in lowered:
            media_kinds = [MediaKind.TV_EPISODE]
        else:
            media_kinds = [MediaKind.TV_EPISODE, MediaKind.FILM, MediaKind.TRAILER]
    media_kinds = list(dict.fromkeys(media_kinds))
    freshness_match = _FRESHNESS.search(query)
    max_age_match = _MAX_AGE.search(query)
    if freshness_match:
        raw_freshness = freshness_match.group(1).casefold()
        freshness_days = int(raw_freshness) if raw_freshness.isdigit() else _NUMBER_WORDS[raw_freshness]
    else:
        freshness_days = 14
    # A stated preference is a ranking request, not permission to return an
    # empty result merely because the ideal window is sparse. Keep the
    # immutable original query for ranking and use one bounded fallback window
    # for evidence discovery. An explicit maximum-age clause below remains a
    # hard ceiling.
    if preferred_freshness_days(query) is not None:
        freshness_days = max(freshness_days, _PREFERENCE_FALLBACK_DAYS)
    if max_age_match:
        raw_age = max_age_match.group(1).casefold()
        maximum_age = int(raw_age) if raw_age.isdigit() else _NUMBER_WORDS[raw_age]
        freshness_days = min(freshness_days, maximum_age)
    exclusions = explicit_exclusions(query)
    focus_terms = [
        term
        for term in _FOCUS_TERMS
        if re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", lowered)
        and not any(term in exclusion.casefold() for exclusion in exclusions)
    ]
    # Preserve an explicit audience-fit request as a deterministic discovery
    # constraint.  This deliberately does not translate "for girls" into a
    # genre such as romance: doing so would be both lossy and stereotyped.
    if _FEMALE_AUDIENCE.search(query):
        focus_terms.append(_FEMALE_CENTERED_FOCUS)
    max_results_match = _MAX_RESULTS.search(query) or _FIND_COUNT.search(query)
    if max_results_match:
        raw_count = max_results_match.group(1).casefold()
        max_results = int(raw_count) if raw_count.isdigit() else _NUMBER_WORDS[raw_count]
    else:
        max_results = 5
    spoiler_policy = (
        SpoilerPolicy.AVOID
        if any(term in lowered for term in ("spoiler-free", "no spoilers", "avoid spoilers"))
        else (
            SpoilerPolicy.ALLOW
            if any(term in lowered for term in ("spoilers allowed", "allow spoilers", "full spoilers"))
            else SpoilerPolicy.CURRENT_EPISODE
        )
    )
    if spoiler_policy is SpoilerPolicy.AVOID and MediaKind.TV_EPISODE in media_kinds:
        media_kinds.append(MediaKind.TRAILER)
    parsed_region = region
    normalized_query = _search_normalize(query)
    for label, code in _REGIONS.items():
        if f" {label} " in f" {normalized_query} ":
            parsed_region = code
            break
    focus_terms.extend(_named_focus_terms(query))
    focus_terms = _dedupe(focus_terms)[:20]
    return ResearchIntentV2(
        query=query,
        media_kinds=media_kinds,
        focus_terms=focus_terms,
        region=parsed_region,
        freshness_days=max(1, min(freshness_days, 90)),
        spoiler_policy=spoiler_policy,
        exclusions=exclusions,
        max_results=max(1, min(max_results, 10)),
    )


def preferred_freshness_days(query: str) -> int | None:
    """Return the user's ideal age when it is explicitly non-mandatory."""

    match = _PREFERRED_FRESHNESS.search(query)
    if match is None:
        return None
    raw = match.group(1).casefold()
    return int(raw) if raw.isdigit() else _NUMBER_WORDS[raw]


def merge_provider_intent(
    local: ResearchIntentV2, provider: ResearchIntentV2
) -> ResearchIntentV2:
    """Allow semantic refinement without dropping explicit user exclusions."""

    merged_exclusions = _dedupe([*local.exclusions, *provider.exclusions])
    merged_focus = _dedupe([*local.focus_terms, *provider.focus_terms])
    return provider.model_copy(
        update={
            "query": local.query,
            "media_kinds": local.media_kinds,
            "focus_terms": merged_focus,
            "region": local.region,
            "freshness_days": local.freshness_days,
            "spoiler_policy": local.spoiler_policy,
            "exclusions": merged_exclusions,
            "max_results": local.max_results,
        }
    )


def violates_exclusions(text: str, intent: ResearchIntentV2) -> bool:
    normalized = f" {_search_normalize(text)} "
    aliases = {
        "k drama": {"k drama", "kdrama", "korean drama"},
        "reality tv": {"reality tv", "reality television", "reality series"},
        "competition shows": {
            "competition show",
            "competition shows",
            "competition series",
            "reality competition",
        },
        "true crime": {"true crime", "crime documentary", "crime docuseries"},
    }
    for exclusion in intent.exclusions:
        key = _search_normalize(exclusion)
        candidates = aliases.get(key, {key})
        if any(f" {candidate} " in normalized for candidate in candidates):
            return True
    return False


def _search_normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).casefold()
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return " ".join(normalized.split())


def _named_focus_terms(query: str) -> list[str]:
    names: list[str] = []
    patterns = (
        r"\b([A-Z][A-Za-z'’-]{1,40})\s*\+\s*([A-Z][A-Za-z'’-]{1,40})\b",
        r"\b([A-Z][A-Za-z'’-]{1,40})\s+and\s+([A-Z][A-Za-z'’-]{1,40})\s+"
        r"(?:relationship|romance|ship)\b",
        r"(?:relationship|romance|ship)\s+(?:between|for)\s+"
        r"([A-Z][A-Za-z'’-]{1,40})\s+and\s+([A-Z][A-Za-z'’-]{1,40})\b",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, query):
            names.extend(match.groups())
    return _dedupe(names)
