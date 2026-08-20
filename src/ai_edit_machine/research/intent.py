"""Deterministic preservation of explicit constraints around model parsing."""

from __future__ import annotations

import re
import unicodedata

from ..contracts import MediaKind, SpoilerPolicy
from ..m1_contracts import (
    IntentFacetCategory,
    IntentFacetSource,
    IntentFacetV1,
    IntentSearchQuestionV1,
    ResearchIntentV2,
    UserIntentInterpretationV1,
)


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
_MALE_AUDIENCE = re.compile(
    r"(?:\b(?:for|aimed\s+at|geared\s+(?:to|toward)|made\s+for)\s+"
    r"(?:boys?|men|male\s+(?:viewers?|audiences?))\b|"
    r"\b(?:boy|boys|man|men|male)[\s-]*(?:focused|cent(?:er|re)d|led)\b)",
    re.IGNORECASE,
)
_SHORT_FORM = re.compile(r"\b(?:tiktok|short[\s-]?form|reels?|shorts)\b", re.IGNORECASE)
_YOUNG_ADULT = re.compile(r"\b(?:young[\s-]?adult|\bya\b|teen(?:age)?r?s?)\b", re.IGNORECASE)
_QUEER_AUDIENCE = re.compile(r"\b(?:queer|lgbtq\+?|gay|lesbian|bisexual)\b", re.IGNORECASE)
_RELATIONSHIP = re.compile(r"\b(?:relationship|romance|romcom|ship(?:ping)?|couple)\b", re.IGNORECASE)
_CHARACTER_EDIT = re.compile(r"\b(?:character|character[\s-]?edit|evolution|arc)\b", re.IGNORECASE)
_AGGRESSIVE_EDIT = re.compile(r"\b(?:aggressive|hype|hard[\s-]?hitting|action)\s+(?:edit|montage)?\b", re.IGNORECASE)
_HEARTBREAKING = re.compile(r"\b(?:heartbreak(?:ing)?|emotionally\s+painful|devastating|sad)\b", re.IGNORECASE)
_NO_ROMANCE = re.compile(r"\b(?:no|not|without|exclude|excluding)\s+romance\b", re.IGNORECASE)
_NO_DEATH = re.compile(r"\b(?:no|not|without)\s+(?:a\s+)?death\b", re.IGNORECASE)
_POSITIVE_ROMANCE_REQUEST = re.compile(
    r"\b(?:want|find|show|give\s+me|looking\s+for)\b[^.;]{0,80}"
    r"\b(?:romance|romcom)\b",
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
    romance_contradiction = bool(
        _NO_ROMANCE.search(query) and _POSITIVE_ROMANCE_REQUEST.search(query)
    )
    if _NO_ROMANCE.search(query) and not romance_contradiction:
        exclusions = _dedupe([*exclusions, "romance"])
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
    interpretation = interpret_user_query(
        query,
        media_kinds=media_kinds,
        exclusions=exclusions,
        freshness_days=freshness_days,
    )
    return ResearchIntentV2(
        query=query,
        media_kinds=media_kinds,
        focus_terms=focus_terms,
        region=parsed_region,
        freshness_days=max(1, min(freshness_days, 90)),
        spoiler_policy=spoiler_policy,
        exclusions=exclusions,
        max_results=max(1, min(max_results, 10)),
        interpretation=interpretation,
    )


def interpret_user_query(
    query: str,
    *,
    media_kinds: list[MediaKind],
    exclusions: list[str],
    freshness_days: int,
) -> UserIntentInterpretationV1:
    """Translate vague language into editable, non-stereotyped research priors.

    Hard constraints are only explicit user instructions. Audience and platform
    language becomes a soft research/ranking prior that still requires current
    evidence; it never asserts that every member of an audience wants one genre.
    """

    lowered = query.casefold()
    facets: list[IntentFacetV1] = []

    def add(
        facet_id: str,
        category: IntentFacetCategory,
        label: str,
        source: IntentFacetSource,
        rationale: str,
        *,
        removable: bool = True,
    ) -> None:
        if any(item.facet_id == facet_id for item in facets):
            return
        facets.append(
            IntentFacetV1(
                facet_id=facet_id,
                category=category,
                label=label,
                source=source,
                removable=removable,
                rationale=rationale,
            )
        )

    if any(token in lowered for token in ("show", "series", "tv", "episode")) and not any(
        token in lowered for token in ("movie", "film")
    ):
        add(
            "tv_only",
            IntentFacetCategory.HARD_CONSTRAINT,
            "TV only",
            IntentFacetSource.EXPLICIT,
            "The request asks for shows or television rather than films.",
            removable=False,
        )
    explicit_days = _FRESHNESS.search(query) or _MAX_AGE.search(query)
    if explicit_days is not None:
        add(
            "freshness_window",
            IntentFacetCategory.HARD_CONSTRAINT,
            f"released within {freshness_days} days",
            IntentFacetSource.EXPLICIT,
            "The request states a concrete release-age boundary.",
            removable=False,
        )
    for index, exclusion in enumerate(exclusions[:10], start=1):
        add(
            f"exclude_{index}",
            IntentFacetCategory.HARD_CONSTRAINT,
            f"exclude {exclusion}",
            IntentFacetSource.EXPLICIT,
            "Explicit exclusions are preserved exactly through collection and ranking.",
            removable=False,
        )

    female_audience = _FEMALE_AUDIENCE.search(query) is not None
    male_audience = _MALE_AUDIENCE.search(query) is not None
    short_form = _SHORT_FORM.search(query) is not None
    if female_audience:
        add(
            "female_skewing_fandom",
            IntentFacetCategory.AUDIENCE,
            "female-skewing fandom",
            IntentFacetSource.EXPLICIT,
            "Use broad audience-fit evidence without assuming that all women prefer one genre.",
        )
    if male_audience:
        add(
            "male_skewing_fandom",
            IntentFacetCategory.AUDIENCE,
            "male-skewing fandom",
            IntentFacetSource.EXPLICIT,
            "Use broad audience-fit evidence without treating gender as a genre rule.",
        )
    if _YOUNG_ADULT.search(query):
        add(
            "young_adult_audience",
            IntentFacetCategory.AUDIENCE,
            "young-adult audience",
            IntentFacetSource.EXPLICIT,
            "The audience or story category is explicitly young-adult.",
        )
    if _QUEER_AUDIENCE.search(query):
        add(
            "queer_fandom",
            IntentFacetCategory.AUDIENCE,
            "queer fandom",
            IntentFacetSource.EXPLICIT,
            "The request explicitly names queer audience or story interest.",
        )
    if short_form:
        add(
            "short_form_edit_potential",
            IntentFacetCategory.PLATFORM_FIT,
            "TikTok-edit potential",
            IntentFacetSource.EXPLICIT,
            "Infer short-form editability from lawful cross-platform fandom and story signals.",
        )
        for facet_id, label, rationale in (
            (
                "active_fan_edit_culture",
                "active fan-edit culture",
                "Search for observable edit, clip, scene, and fandom discussion signals.",
            ),
            (
                "recognizable_characters_relationships",
                "recognizable characters or relationships",
                "Short edits need a subject viewers can recognize quickly.",
            ),
            (
                "emotionally_legible_scenes",
                "emotionally legible scenes",
                "Prioritize moments whose emotional question and payoff work in a short runtime.",
            ),
            (
                "visual_quote_moments",
                "strong visual or quote moments",
                "Look for lawful evidence of memorable visuals, dialogue, reactions, or callbacks.",
            ),
            (
                "current_or_upcoming_relevance",
                "current or upcoming TV",
                "Fresh episodes and trailers are useful only when paired with audience and edit signals.",
            ),
        ):
            add(
                facet_id,
                IntentFacetCategory.SOFT_PREFERENCE,
                label,
                IntentFacetSource.INFERRED_PRIOR,
                rationale,
            )
    no_romance = _NO_ROMANCE.search(query) is not None
    contradiction = bool(no_romance and _POSITIVE_ROMANCE_REQUEST.search(query))
    relationship_requested = bool(_RELATIONSHIP.search(query)) and (
        not no_romance or contradiction
    )
    if relationship_requested:
        add(
            "relationship_edit",
            IntentFacetCategory.CREATIVE_EDIT,
            "relationship-focused edit",
            IntentFacetSource.EXPLICIT,
            "The request explicitly names romance, shipping, a couple, or a relationship.",
        )
    elif female_audience and short_form:
        add(
            "relationship_or_character_salience",
            IntentFacetCategory.SOFT_PREFERENCE,
            "active character/relationship discussion",
            IntentFacetSource.INFERRED_PRIOR,
            "This is one useful discovery prior, not an assumption that romance is required.",
        )
    if _CHARACTER_EDIT.search(query):
        add(
            "character_edit",
            IntentFacetCategory.CREATIVE_EDIT,
            "character edit",
            IntentFacetSource.EXPLICIT,
            "The request asks for a character-centered editorial angle.",
        )
    if _AGGRESSIVE_EDIT.search(query):
        add(
            "aggressive_edit",
            IntentFacetCategory.CREATIVE_EDIT,
            "aggressive edit",
            IntentFacetSource.EXPLICIT,
            "The requested edit tone is aggressive or high-energy.",
        )
    if _HEARTBREAKING.search(query):
        add(
            "heartbreaking_edit",
            IntentFacetCategory.CREATIVE_EDIT,
            "emotionally painful edit",
            IntentFacetSource.EXPLICIT,
            "The requested emotional direction is painful or heartbreaking.",
        )
    if _NO_DEATH.search(query):
        add(
            "no_death",
            IntentFacetCategory.HARD_CONSTRAINT,
            "no death",
            IntentFacetSource.EXPLICIT,
            "The concept must not rely on a death beat.",
            removable=False,
        )
    if _NO_ROMANCE.search(query):
        add(
            "no_romance",
            IntentFacetCategory.HARD_CONSTRAINT,
            "not romance",
            IntentFacetSource.EXPLICIT,
            "Romance must not be the selected editorial angle.",
            removable=False,
        )

    questions = _semantic_search_questions(
        female_audience=female_audience,
        male_audience=male_audience,
        short_form=short_form,
        relationship=relationship_requested,
        character=_CHARACTER_EDIT.search(query) is not None,
        aggressive=_AGGRESSIVE_EDIT.search(query) is not None,
        heartbreaking=_HEARTBREAKING.search(query) is not None,
    )
    broad_query = len(query.split()) <= 12 and not exclusions and explicit_days is None
    return UserIntentInterpretationV1(
        facets=facets,
        search_questions=questions,
        broad_query=broad_query,
        clarification_needed=contradiction,
        clarification_reason=(
            "The request both asks for romance and excludes romance; choose which constraint should win."
            if contradiction
            else None
        ),
        direct_tiktok_data_used=False,
        short_form_inference_disclaimer=(
            "TikTok potential is inferred from cross-platform fandom and editability signals. Direct TikTok trend data was not used."
            if short_form
            else None
        ),
    )


def _semantic_search_questions(
    *,
    female_audience: bool,
    male_audience: bool,
    short_form: bool,
    relationship: bool,
    character: bool,
    aggressive: bool,
    heartbreaking: bool,
) -> list[IntentSearchQuestionV1]:
    values: list[tuple[str, str, str]] = []
    if female_audience and short_form:
        values.extend(
            (
                ("female_fandom_current", "newly airing TV shows with active female-skewing fandom discussion", "Find current titles with actual audience-fit signals."),
                ("ya_character_discussion", "recent romance, young-adult, female-led, or fantasy TV with strong character discussion", "Expand genres as non-exclusive priors and test them against evidence."),
                ("active_shipping", "new shows with active relationship or shipping discussion", "Find recognizable relationship subjects without assuming romance is mandatory."),
                ("fan_edit_scenes", "recent shows generating fan edits, scene discussion, or character clip activity", "Find observable short-form edit culture proxies."),
                ("emotional_moments", "new episodes with confessions, arguments, reunions, reactions, or memorable dialogue", "Find a specific emotional hook and possible payoff."),
                ("prerelease_fandom", "upcoming streaming TV with strong pre-release character or relationship fandom", "Include evidence-backed upcoming trailers when current episodes are sparse."),
                ("visual_cast_interest", "current series with visually recognizable casts, settings, or emotionally compelling character dynamics", "Find montage-friendly visual identity and fan recognition."),
                ("trailer_relationship_discourse", "new TV trailers generating character relationship discourse", "Find trailer-led concepts with an identifiable narrative question."),
                ("young_women_current_tv", "currently airing shows discussed by young women and female-skewing fandom communities", "Seek audience evidence without turning gender into a genre rule."),
                ("short_form_this_week", "TV shows with strong short-form edit potential this week based on fandom and scene signals", "Test currentness, fandom, editability, and footage feasibility together."),
            )
        )
    elif male_audience and aggressive:
        values.extend(
            (
                ("male_fandom_current", "current TV with active male-skewing fandom discussion", "Find audience fit from current evidence."),
                ("aggressive_action", "new TV episodes with confrontations, victories, rivalries, or high-energy action moments", "Find a coherent aggressive montage hook."),
                ("character_power_arc", "current character power shifts, rivalries, or underdog payoffs in TV", "Find character and payoff salience."),
                ("short_form_hype", "current TV with high-energy clip and short-form edit activity", "Find observable editability proxies."),
            )
        )
    else:
        values.extend(
            (
                ("current_story_hook", "current TV episodes or trailers with a specific discussed story hook", "Find a concrete why-now event."),
                ("character_relationship", "current TV with active character or relationship discussion", "Find a recognizable emotional subject."),
                ("editable_moments", "recent TV with memorable dialogue, reactions, confrontations, reveals, or visual parallels", "Find intro, montage, and payoff evidence."),
                ("footage_actionability", "current TV discussion that identifies useful episodes, scenes, official clips, or trailers", "Prefer concepts with a compact source set."),
            )
        )
    if character and not any(key == "character_evolution" for key, _, _ in values):
        values.append(("character_evolution", "current character development with earlier-season contrast or payoff", "Find a non-generic character-evolution arc."))
    if relationship and not any(key == "relationship_timeline" for key, _, _ in values):
        values.append(("relationship_timeline", "current relationship development that reframes earlier scenes", "Find a current-to-legacy relationship bridge."))
    if heartbreaking:
        values.append(("pain_without_death", "emotionally painful character conflict, separation, or disappointment without relying on death", "Find a supported painful arc that honors the exclusion."))
    if short_form and not female_audience:
        values.append(("short_form_proxy", "current TV with cross-platform fandom, memorable moments, and short-form edit potential", "Infer platform fit without claiming direct TikTok trend data."))
    return [
        IntentSearchQuestionV1(question_id=key, query=text, evidence_goal=goal)
        for key, text, goal in values[:20]
    ]


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
            "interpretation": local.interpretation,
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
