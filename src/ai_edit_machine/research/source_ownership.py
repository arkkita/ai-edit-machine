"""Reviewed publisher ownership used for conservative source independence.

Unknown web publishers deliberately remain one shared group.  The registry is
small and evidence-backed rather than guessing independence from hostnames.
"""

from __future__ import annotations

import hashlib
import re


_TRUSTED_PUBLISHER_OWNERS: dict[str, str] = {
    # Penske Media Corporation
    "variety.com": "owner:penske-media",
    "deadline.com": "owner:penske-media",
    "indiewire.com": "owner:penske-media",
    "tvline.com": "owner:penske-media",
    # Dotdash Meredith
    "people.com": "owner:dotdash-meredith",
    "ew.com": "owner:dotdash-meredith",
    # Vox Media / New York Magazine
    "vulture.com": "owner:vox-media",
    "nymag.com": "owner:vox-media",
    # Future plc
    "cinemablend.com": "owner:future-plc",
    "tomsguide.com": "owner:future-plc",
    "techradar.com": "owner:future-plc",
    "whowhatwear.com": "owner:future-plc",
    "marieclaire.com": "owner:future-plc",
    "gamesradar.com": "owner:future-plc",
    "whattowatch.com": "owner:future-plc",
    # Conde Nast
    "vanityfair.com": "owner:conde-nast",
    "teenvogue.com": "owner:conde-nast",
    "vogue.com": "owner:conde-nast",
    "wired.com": "owner:conde-nast",
    "glamour.com": "owner:conde-nast",
    # Hearst
    "elle.com": "owner:hearst",
    "cosmopolitan.com": "owner:hearst",
    "harpersbazaar.com": "owner:hearst",
    "esquire.com": "owner:hearst",
    "seventeen.com": "owner:hearst",
    "goodhousekeeping.com": "owner:hearst",
    "townandcountrymag.com": "owner:hearst",
    "sfchronicle.com": "owner:hearst",
    # PRISA Media
    "as.com": "owner:prisa-media",
    "los40.com": "owner:prisa-media",
    "elpais.com": "owner:prisa-media",
    # Independently reviewed publishers
    "thewrap.com": "owner:thewrap",
    "avclub.com": "owner:paste-media",
    "theguardian.com": "owner:guardian-media-group",
    # The publication's current first-party About page states that it is
    # majority owned by IAC. Keep this separate from every reviewed publisher
    # group above so it can contribute only one conservative owner signal.
    "thedailybeast.com": "owner:iac",
}


def known_publisher_owner(host: str) -> str | None:
    """Return a reviewed parent-owner group for one normalized DNS host."""

    normalized = host.casefold().strip(" .")
    for publisher_host, owner in _TRUSTED_PUBLISHER_OWNERS.items():
        if normalized == publisher_host or normalized.endswith(f".{publisher_host}"):
            return owner
    return None


def reviewed_publisher_domains() -> tuple[str, ...]:
    """Return the exact reviewed entertainment-publisher search allow-list.

    Hosted search may use these domains for discovery, but the ownership map
    and the direct-page verifier still determine evidence independence and
    eligibility.  Exposing a sorted immutable view keeps the provider adapter
    from maintaining a second, drifting publisher policy.
    """

    return tuple(sorted(_TRUSTED_PUBLISHER_OWNERS))


_TVMAZE_SHOW_BINDING_PREFIX = "tvmaze-show-title-sha256:v1:"
_MEDIA_TITLE_BINDING_PREFIX = "media-title-sha256:v1:"
_SOURCE_BINDING_SEPARATOR = ":source-sha256:v1:"


def _normalized_title_digest(show_or_title: str) -> str:
    normalized = " ".join(
        re.sub(r"[^a-z0-9]+", " ", show_or_title.casefold()).split()
    )
    if not normalized:
        raise ValueError("media title binding requires a nonempty normalized title")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def tvmaze_show_title_binding(show_or_title: str) -> str:
    """Return an opaque binding to one immutable TVmaze show title.

    The OpenAI adapter may attach this value to a validated discussion page
    only after trusted host-side logic has uniquely associated that page with
    one TVmaze discovery seed.  It records show-level association only: it is
    never evidence for an episode, scene, quote, speaker, or character fact.
    """

    return f"{_TVMAZE_SHOW_BINDING_PREFIX}{_normalized_title_digest(show_or_title)}"


def tvmaze_show_source_binding(show_or_title: str, canonical_url: str) -> str:
    """Bind one trusted show association to one individual source page.

    The page digest keeps two independent publishers for the same show from
    sharing a provider natural identity in the durable evidence store.
    """

    show_binding = tvmaze_show_title_binding(show_or_title)
    if not canonical_url:
        raise ValueError("source binding requires a canonical URL")
    source_digest = hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()
    return f"{show_binding}{_SOURCE_BINDING_SEPARATOR}{source_digest}"


def media_title_source_binding(show_or_title: str, canonical_url: str) -> str:
    """Bind one host-validated media-title association to one source page.

    Unlike the legacy TVmaze binding, this namespace may be emitted after a
    staged film/trailer primary establishes an exact title and the discussion
    page independently binds that same title. It establishes title relevance
    only—not a scene, quote, speaker, or release fact.
    """

    if not canonical_url:
        raise ValueError("source binding requires a canonical URL")
    title_digest = _normalized_title_digest(show_or_title)
    source_digest = hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()
    return (
        f"{_MEDIA_TITLE_BINDING_PREFIX}{title_digest}"
        f"{_SOURCE_BINDING_SEPARATOR}{source_digest}"
    )


def source_record_binds_tvmaze_show(
    *,
    provider: str,
    provider_record_id: str | None,
    canonical_url: str,
    show_or_title: str,
) -> bool:
    """Validate the exact trusted show-binding shape on a canonical source."""

    if provider != "openai" or provider_record_id is None:
        return False
    try:
        expected = tvmaze_show_title_binding(show_or_title)
    except ValueError:
        return False
    if provider_record_id == expected:
        # Retain read compatibility with evidence created before the source
        # identity suffix was added. New adapter output never emits this form.
        return True
    try:
        return provider_record_id == tvmaze_show_source_binding(
            show_or_title, canonical_url
        )
    except ValueError:
        return False


def source_record_binds_media_title(
    *,
    provider: str,
    provider_record_id: str | None,
    canonical_url: str,
    show_or_title: str,
) -> bool:
    """Validate a host-authored title binding, retaining legacy TV support."""

    if provider != "openai" or provider_record_id is None:
        return False
    try:
        expected = media_title_source_binding(show_or_title, canonical_url)
    except ValueError:
        return False
    return provider_record_id == expected or source_record_binds_tvmaze_show(
        provider=provider,
        provider_record_id=provider_record_id,
        canonical_url=canonical_url,
        show_or_title=show_or_title,
    )
