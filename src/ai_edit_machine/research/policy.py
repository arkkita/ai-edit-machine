"""Provider policy deadlines used by normalized evidence and cache entries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True, slots=True)
class PolicyRule:
    policy_class: str
    cache_ttl: timedelta
    refresh_after: timedelta | None
    purge_after: timedelta
    deletion_after: timedelta | None = None


POLICY_RULES: dict[str, PolicyRule] = {
    "tvmaze-metadata-v1": PolicyRule(
        policy_class="tvmaze-metadata-v1",
        cache_ttl=timedelta(hours=24),
        refresh_after=timedelta(hours=24),
        purge_after=timedelta(days=30),
    ),
    "youtube-public-metadata-v1": PolicyRule(
        policy_class="youtube-public-metadata-v1",
        cache_ttl=timedelta(hours=6),
        refresh_after=timedelta(days=29),
        purge_after=timedelta(days=30),
        deletion_after=timedelta(days=30),
    ),
    "openai-web-evidence-v1": PolicyRule(
        policy_class="openai-web-evidence-v1",
        cache_ttl=timedelta(hours=12),
        refresh_after=timedelta(hours=12),
        purge_after=timedelta(days=30),
    ),
    "xai-search-lead-v1": PolicyRule(
        policy_class="xai-search-lead-v1",
        cache_ttl=timedelta(hours=6),
        refresh_after=timedelta(hours=6),
        purge_after=timedelta(days=30),
    ),
}


@dataclass(frozen=True, slots=True)
class PolicyDeadlines:
    expires_at: datetime
    refresh_due_at: datetime | None
    purge_due_at: datetime
    deletion_required_at: datetime | None


def deadlines_for(
    policy_class: str,
    retrieved_at: datetime,
    rules: dict[str, PolicyRule] | None = None,
) -> PolicyDeadlines:
    if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
        raise ValueError("retrieved_at must be timezone aware")
    try:
        rule = (rules or POLICY_RULES)[policy_class]
    except KeyError as error:
        raise ValueError(f"unknown policy class: {policy_class}") from error
    return PolicyDeadlines(
        expires_at=retrieved_at + rule.cache_ttl,
        refresh_due_at=(
            retrieved_at + rule.refresh_after
            if rule.refresh_after is not None
            else None
        ),
        purge_due_at=retrieved_at + rule.purge_after,
        deletion_required_at=(
            retrieved_at + rule.deletion_after
            if rule.deletion_after is not None
            else None
        ),
    )
