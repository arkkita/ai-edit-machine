"""Conservative canonicalization for public evidence and discovery links."""

from __future__ import annotations

import ipaddress
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


TRACKING_QUERY_KEYS = frozenset(
    {
        "fbclid",
        "gclid",
        "mc_cid",
        "mc_eid",
        "ref_src",
        "utm_campaign",
        "utm_content",
        "utm_medium",
        "utm_source",
        "utm_term",
    }
)


def canonicalize_public_url(value: str) -> str:
    """Return a stable HTTPS URL and reject local/credential-bearing targets."""

    parts = urlsplit(value.strip())
    if parts.scheme.casefold() != "https":
        raise ValueError("public evidence URLs must use HTTPS")
    if parts.username is not None or parts.password is not None:
        raise ValueError("public evidence URLs cannot contain credentials")
    if not parts.hostname:
        raise ValueError("public evidence URL must contain a hostname")
    host = parts.hostname.encode("idna").decode("ascii").casefold().rstrip(".")
    try:
        address = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        address = None
    if address is not None and (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
    ):
        raise ValueError("local or non-public evidence targets are forbidden")
    port = parts.port
    netloc = host if port in (None, 443) else f"{host}:{port}"
    path = parts.path or "/"
    query_items = [
        (key, item)
        for key, item in parse_qsl(parts.query, keep_blank_values=True)
        if key.casefold() not in TRACKING_QUERY_KEYS
    ]
    query = urlencode(sorted(query_items), doseq=True)
    return urlunsplit(("https", netloc, path, query, ""))


def canonical_host(value: str) -> str:
    canonical = urlsplit(canonicalize_public_url(value))
    assert canonical.hostname is not None
    return canonical.hostname.casefold()

