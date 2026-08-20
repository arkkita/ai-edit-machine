"""Create the development-only M1.1b candidate diagnosis from a replay fixture.

This script is deliberately offline.  It reads a sanitized live-run fixture and
does not read SQLite, credentials, or provider configuration; it makes no network
calls.  Missing historical instrumentation is reported as missing rather than
reconstructed as if it had been persisted by the live run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


REPORT_SCHEMA_VERSION = "m1.1b-candidate-diagnostic-v1"
RANKING_PROFILE_ID = "m1.1-intent-editorial-v1"

CANDIDATES: tuple[dict[str, Any], ...] = (
    {
        "rank": 1,
        "title": "Stuart Fails to Save the Universe",
        "slot": "female-audience-prior discovery slot 1 of 6",
    },
    {
        "rank": 2,
        "title": "Furious",
        "slot": "female-audience-prior discovery slot 2 of 6",
    },
    {
        "rank": 3,
        "title": "Fightland",
        "slot": "female-audience-prior discovery slot 3 of 6",
    },
    {
        "rank": 4,
        "title": "Paris is Always a Good Idea",
        "slot": "female-audience-prior discovery slot 4 of 6",
    },
    {
        "rank": 5,
        "title": "Las Azules",
        "slot": "female-audience-prior discovery slot 5 of 6",
    },
    {
        "rank": 6,
        "title": "My Brilliant Career",
        "slot": "female-audience-prior discovery slot 6 of 6",
    },
    {
        "rank": 7,
        "title": "The Librarians: The Next Chapter",
        "slot": "broad scripted/editable discovery slot 1 of 2",
    },
    {
        "rank": 8,
        "title": "Lanterns",
        "slot": "broad scripted/editable discovery slot 2 of 2",
    },
)

FEMALE_AUDIENCE_DIRECT = re.compile(
    r"\b(?:female[\s-]*(?:skewing\s+)?(?:audience|fandom|fans?|viewers?)|"
    r"(?:girls?|women)\s+(?:audience|fandom|fans?|viewers?|watchers?|discussion)|"
    r"popular\s+(?:among|with)\s+(?:girls?|women))\b",
    re.IGNORECASE,
)
FEMALE_AFFINITY_CUE = re.compile(
    r"\b(?:female[\s-]*(?:centered|centred|focused|led)|women\s+at\s+the\s+center|"
    r"cent(?:er|re)s?\s+(?:its\s+)?women|"
    r"heroines?|mother|daughter|sister|young[\s-]?adult|teen(?:age)?r?s?|romance|"
    r"romantic|romcom|ship(?:ping)?|couple|chemistry|kiss|confession|"
    r"relationship\s+fandom)\b",
    re.IGNORECASE,
)
EDITABILITY_SIGNAL = re.compile(
    r"\b(?:ship(?:ping)?|chemistry|kiss|confession|argument|reunion|reaction|"
    r"quote|dialogue|scene|clip|trailer|callback|parallel|friendship|rivalry|"
    r"breakup|betrayal|reveal|twist|character|relationship|fan\s+edit)\b",
    re.IGNORECASE,
)

THRESHOLDS = {
    "pre_synthesis_audience_evidence_floor": {
        "direct_statement_or_distinct_affinity_cues": 2,
        "description": (
            "A direct female-audience statement passes; otherwise two distinct "
            "female-affinity cues are required."
        ),
    },
    "pre_synthesis_primary_shape": {
        "current_official_primary": 1,
        "current_independent_signal_groups": 1,
        "total_independence_groups": 2,
    },
    "pre_synthesis_metadata_shape": {
        "current_exact_tvmaze_episode_identity": 1,
        "current_independent_signal_groups": 2,
        "total_independence_groups": 3,
    },
    "final_quality": {
        "audience_fit_minimum": 0.40,
        "short_form_edit_potential_minimum": 0.35,
        "footage_actionability_minimum": 0.35,
    },
    "editorial_concept": {
        "concept_specificity_minimum": 0.50,
        "concept_total_minimum": 0.45,
    },
}

NOT_COMPUTED = {
    "status": "NOT_COMPUTED",
    "reason": "Candidate was rejected before a canonical opportunity and footage request reached the final ranker.",
}


def _normalized(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())


def _structured_show(claim: dict[str, Any]) -> str | None:
    for name in ("episodeLocator", "castFact", "sceneFact"):
        value = claim.get(name)
        if isinstance(value, dict):
            show = value.get("showOrTitle")
            if isinstance(show, str):
                return show
    quote = claim.get("quoteFact")
    if isinstance(quote, dict):
        identity = quote.get("mediaIdentity")
        if isinstance(identity, dict) and isinstance(identity.get("showOrTitle"), str):
            return str(identity["showOrTitle"])
    why_now = claim.get("whyNowEvent")
    if isinstance(why_now, dict):
        identity = why_now.get("mediaIdentity")
        if isinstance(identity, dict) and isinstance(identity.get("showOrTitle"), str):
            return str(identity["showOrTitle"])
    return None


def _source_matches_title(source: dict[str, Any], title: str) -> bool:
    needle = f" {_normalized(title)} "
    haystack = f" {_normalized(str(source.get('title') or ''))} "
    if bool(needle.strip()) and needle in haystack:
        return True
    # The verifier persists a one-way, source-owned media binding when a cited
    # publisher headline does not repeat the show title. Recompute only the
    # non-secret normalized-title digest; do not guess from the article body.
    title_digest = hashlib.sha256(_normalized(title).encode("utf-8")).hexdigest()
    binding = f"tvmaze-show-title-sha256:v1:{title_digest}:"
    return binding in str(source.get("providerRecordId") or "")


def _round(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 4)


def _iso_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _current_hook(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    hooks: list[dict[str, Any]] = []
    for claim in claims:
        if claim.get("claimKind") not in {"EPISODE_IDENTITY", "OFFICIAL_CLIP", "WHY_NOW"}:
            continue
        hook: dict[str, Any] = {
            "claim_id": claim.get("claimId"),
            "claim_kind": claim.get("claimKind"),
            "verification": claim.get("verification"),
            "event_or_release_at": claim.get("eventOrReleaseAt"),
            "claim": claim.get("text"),
        }
        if claim.get("episodeLocator") is not None:
            hook["episode_locator"] = claim["episodeLocator"]
        if claim.get("sceneFact") is not None:
            hook["scene_fact"] = claim["sceneFact"]
        hooks.append(hook)
    return hooks


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# M1.1b offline candidate diagnosis — live regression run 5",
        "",
        f"Fixture: `{report['fixture']}`  ",
        f"Run ID: `{report['run_id']}`  ",
        f"Run timestamp: `{report['run_timestamp']}`  ",
        f"Fixture SHA-256: `{report['fixture_sha256']}`",
        "",
        "This report is a replay-only diagnosis. It made no provider call, did not read or change SQLite, and did not infer missing historical scores.",
        "",
        "## Verified first-loss point",
        "",
        report["root_cause"],
        "",
        "The live fixture retained no per-candidate TVmaze discovery-rank components. Those fields are therefore marked `NOT_RECORDED`; the selected order and slot family are known, but an exact historical numeric shortlist score cannot honestly be reconstructed.",
        "",
        "## Thresholds active in the run",
        "",
        "- Audience evidence floor: direct female-audience evidence, or at least 2 distinct affinity cues.",
        "- Official-primary evidence shape: 1 current official primary + 1 independent current signal, across at least 2 groups.",
        "- Metadata-only evidence shape: 1 exact current TVmaze episode + 2 current signal owner groups, across at least 3 groups.",
        "- Final ranker: audience fit ≥ 0.40; inferred short-form edit potential ≥ 0.35; footage actionability ≥ 0.35.",
        "- Concept gate: specificity ≥ 0.50 and total ≥ 0.45.",
        "",
        "## Candidate summary",
        "",
        "| # | Candidate | Discussion owners | Audience fit | Evidence shape | Exact first gate | Failure class |",
        "|---:|---|---:|---:|---|---|---|",
    ]
    for item in report["candidates"]:
        lines.append(
            "| {rank} | {title} | {owners} | {audience:.2f} | {shape} | {gate} | {failure} |".format(
                rank=item["shortlist_rank"],
                title=item["title"].replace("|", "\\|"),
                owners=item["scores"]["fandom_velocity"]["independent_signal_groups"],
                audience=item["scores"]["audience_fit"]["value"],
                shape="pass" if item["evidence_shape"]["would_pass_if_audience_supported"] else "fail",
                gate=item["exact_rejection_gate"],
                failure=item["failure_classification"],
            )
        )
    for item in report["candidates"]:
        lines.extend(
            [
                "",
                f"## {item['shortlist_rank']}. {item['title']}",
                "",
                f"- Why shortlisted: {item['why_it_entered_the_shortlist']}",
                f"- Current hook: {item['current_hook_summary']}",
                f"- Audience evidence: {item['audience_fit_evidence']['summary']}",
                f"- Fandom evidence: {item['fandom_evidence']['summary']}",
                f"- Story/episode evidence: {item['story_or_episode_evidence']['summary']}",
                f"- Inferred short-form signal: {item['scores']['short_form_edit_potential']['summary']}",
                f"- Source categories: {', '.join(item['source_categories'])}",
                f"- Exact rejection gate: `{item['exact_rejection_gate']}` ({item['failure_classification']})",
                f"- Additional blockers: {', '.join(item['additional_blockers']) or 'none recorded'}",
                "- Evidence references:",
            ]
        )
        for ref in item["evidence_references"]:
            lines.append(
                f"  - `{ref['source_id']}` / `{ref['source_type']}` / `{ref['independence_group']}` — {ref['title']}"
            )
        lines.extend(
            [
                "- Scores and thresholds:",
                f"  - audience_fit: {item['scores']['audience_fit']['value']:.2f} (final threshold 0.40; evidence floor pass={str(item['scores']['audience_fit']['evidence_floor_pass']).lower()})",
                f"  - freshness: {item['scores']['freshness']['value']:.4f} (diagnostic replay from the current hook and {item['scores']['freshness']['window_days']}-day window)",
                f"  - fandom_velocity: {item['scores']['fandom_velocity']['value']:.4f} ({item['scores']['fandom_velocity']['independent_signal_groups']} discussion owner group(s))",
                f"  - observed pre-concept short-form lower bound: {item['scores']['short_form_edit_potential']['observed_lower_bound']:.4f} (final threshold 0.35; not a virality probability)",
                f"  - observable source_diversity: {item['scores']['source_diversity']['value']:.4f} ({item['scores']['source_diversity']['independence_groups']} total groups)",
                "  - intent_fit, relationship/character salience, footage_actionability, evidence_quality, uncertainty_penalty, total, and every concept score: `NOT_COMPUTED` because no candidate reached synthesis/final ranking.",
            ]
        )
    lines.extend(
        [
            "",
            "## Diagnosis",
            "",
            "- Candidate recall was large (4,027 raw; 3,660 fresh and constraint-surviving), but semantic web expansion retained no citation-bound candidate selectors, so TVmaze metadata ordering chose all eight deep-research titles.",
            "- Five candidates had at least one current title-bound article; three had none. None had source-owned evidence satisfying the female-skewing audience floor.",
            "- Stuart and Lanterns had enough source-owner shape to reach synthesis if audience support existed. The other six also lacked the required evidence shape (or any current discussion at all).",
            "- No candidate reached opportunity scoring, editorial concept synthesis, footage generation, deduplication, or UI serialization. Therefore the zero-result run was not caused by a final rank threshold, schema serialization, Rust, or a frontend display cap.",
            "- The Stuart official Episode 4 preview verifies only a title-bound preview. The fixture does not verify a cameo, encounter, quote, parent-series relationship beat, or cross-series story bridge, so a Stuart concept or footage request would have been unsupported.",
            "",
        ]
    )
    return "\n".join(lines)


def build_report(fixture_path: Path) -> dict[str, Any]:
    raw = fixture_path.read_bytes()
    fixture = json.loads(raw)
    source_by_id = {item["sourceId"]: item for item in fixture["evidenceSources"]}
    generated_at = _iso_datetime(fixture["generatedAt"])
    freshness_days = int(fixture["normalizedIntent"]["freshnessDays"])
    candidates: list[dict[str, Any]] = []

    for seed in CANDIDATES:
        title = str(seed["title"])
        relevant_claims: list[dict[str, Any]] = []
        relevant_sources: dict[str, dict[str, Any]] = {}
        for claim in fixture["evidenceClaims"]:
            source = source_by_id.get(claim["sourceId"])
            if source is None:
                continue
            structured_show = _structured_show(claim)
            if (
                structured_show is not None
                and _normalized(structured_show) == _normalized(title)
            ) or _source_matches_title(source, title):
                relevant_claims.append(claim)
                relevant_sources[source["sourceId"]] = source

        current_discussions = [
            claim
            for claim in relevant_claims
            if claim.get("claimKind") == "VIEWER_DISCUSSION"
            and claim.get("supportsWhyNow") is True
        ]
        current_primaries = [
            claim
            for claim in relevant_claims
            if claim.get("claimKind") in {"WHY_NOW", "OFFICIAL_CLIP"}
            and claim.get("verification") == "PRIMARY_VERIFIED"
            and claim.get("supportsWhyNow") is True
        ]
        metadata_hooks = [
            claim
            for claim in relevant_claims
            if claim.get("claimKind") == "EPISODE_IDENTITY"
            and claim.get("episodeLocator") is not None
        ]
        cast_claims = [
            claim for claim in relevant_claims if claim.get("claimKind") == "CAST_IDENTITY"
        ]
        corpus = " ".join(
            f"{relevant_sources[claim['sourceId']].get('title', '')} {claim.get('text', '')}"
            for claim in relevant_claims
        )
        direct_audience = sorted(
            {match.group(0).casefold() for match in FEMALE_AUDIENCE_DIRECT.finditer(corpus)}
        )
        audience_cues = sorted(
            {_normalized(match.group(0)) for match in FEMALE_AFFINITY_CUE.finditer(corpus)}
        )
        audience_fit = 0.90 if direct_audience else 0.55 if len(audience_cues) >= 2 else 0.30 if len(audience_cues) == 1 else 0.05
        audience_floor_pass = bool(direct_audience) or len(audience_cues) >= 2

        signal_groups = {
            relevant_sources[claim["sourceId"]]["independenceGroup"]
            for claim in current_discussions
        }
        primary_groups = {
            relevant_sources[claim["sourceId"]]["independenceGroup"]
            for claim in current_primaries
        }
        metadata_groups = {
            relevant_sources[claim["sourceId"]]["independenceGroup"]
            for claim in metadata_hooks
        }
        evidence_shape_pass = (
            bool(primary_groups)
            and bool(signal_groups)
            and len(primary_groups | signal_groups) >= 2
        ) or (
            not primary_groups
            and bool(metadata_groups)
            and len(signal_groups) >= 2
            and len(metadata_groups | signal_groups) >= 3
        )

        hook_claims = current_primaries or metadata_hooks
        hook_times = [
            _iso_datetime(claim["eventOrReleaseAt"])
            for claim in hook_claims
            if isinstance(claim.get("eventOrReleaseAt"), str)
        ]
        freshness = 0.0
        if hook_times:
            latest = max(hook_times)
            age_seconds = max(0.0, (generated_at - latest).total_seconds())
            freshness = _round(1.0 - age_seconds / (freshness_days * 86_400))

        editability_hits = len(EDITABILITY_SIGNAL.findall(corpus))
        observable_short_form = _round(
            0.15 * min(editability_hits, 4)
            + (0.15 if len(signal_groups) >= 2 else 0.0)
        )
        all_groups = {
            source["independenceGroup"] for source in relevant_sources.values()
        }
        source_diversity = _round(len(all_groups) / 4.0)

        additional_blockers: list[str] = []
        if not current_discussions:
            additional_blockers.append("retrieval:no-current-title-bound-discussion")
        elif not evidence_shape_pass:
            additional_blockers.append("evidence:insufficient-independent-source-shape")
        additional_blockers.extend(
            [
                "concept:not-attempted",
                "footage:not-attempted",
            ]
        )
        failure_class = (
            "RETRIEVAL_RELATED" if not current_discussions else "EVIDENCE_RELATED"
        )
        episode_summary = "; ".join(
            str(claim.get("text") or "") for claim in metadata_hooks
        ) or "No exact current episode identity was retained."
        if current_primaries:
            primary_summary = "; ".join(
                str(claim.get("text") or "") for claim in current_primaries
            )
            current_hook_summary = f"{primary_summary} Supporting metadata: {episode_summary}"
        else:
            current_hook_summary = episode_summary
        fandom_titles = [
            relevant_sources[claim["sourceId"]]["title"] for claim in current_discussions
        ]
        cast_names = [
            f"{claim['castFact']['characterName']} ({claim['castFact']['performerName']})"
            for claim in cast_claims
            if isinstance(claim.get("castFact"), dict)
        ]

        candidates.append(
            {
                "shortlist_rank": seed["rank"],
                "title": title,
                "why_it_entered_the_shortlist": (
                    f"Selected as {seed['slot']} by the TVmaze discovery ordering over fresh "
                    "scripted/editable metadata. This was a discovery prior, not audience or "
                    "fandom proof. The historical fixture did not persist the numeric focus, "
                    "creative-affinity, episode-title, provider-weight, region, official-host, "
                    "or recency rank components."
                ),
                "shortlist_rank_components": {
                    name: {
                        "status": "NOT_RECORDED",
                        "reason": "The live fixture predates candidate-level funnel instrumentation.",
                    }
                    for name in (
                        "focus_affinity",
                        "creative_affinity",
                        "episode_title_affinity",
                        "provider_weight_band",
                        "region_affinity",
                        "official_host_affinity",
                        "provider_weight",
                        "recency_sort_key",
                    )
                },
                "current_hook_summary": current_hook_summary,
                "current_hook_found": _current_hook(relevant_claims),
                "audience_fit_evidence": {
                    "direct_statements": direct_audience,
                    "distinct_affinity_cues": audience_cues,
                    "summary": (
                        "No source-owned evidence of female-skewing fandom appeal was retained."
                        if not direct_audience and not audience_cues
                        else f"Direct statements: {direct_audience or 'none'}; cues: {audience_cues or 'none'}."
                    ),
                },
                "fandom_evidence": {
                    "current_discussion_source_titles": fandom_titles,
                    "independent_owner_groups": sorted(signal_groups),
                    "summary": (
                        f"{len(current_discussions)} current title-bound article signal(s) across "
                        f"{len(signal_groups)} owner group(s). These are qualitative coverage leads, "
                        "not a fandom census or direct TikTok data."
                        if current_discussions
                        else "No usable current title-bound discussion signal was retrieved."
                    ),
                },
                "story_or_episode_evidence": {
                    "episode_claims": [
                        {
                            "claim_id": claim["claimId"],
                            "text": claim["text"],
                            "event_or_release_at": claim.get("eventOrReleaseAt"),
                            "episode_locator": claim.get("episodeLocator"),
                        }
                        for claim in metadata_hooks
                    ],
                    "official_hook_claims": [
                        {
                            "claim_id": claim["claimId"],
                            "text": claim["text"],
                            "scene_fact": claim.get("sceneFact"),
                        }
                        for claim in current_primaries
                    ],
                    "named_cast": cast_names,
                    "summary": (
                        f"{episode_summary} {len(cast_names)} cast identity record(s) were retained. "
                        "No verified quote, relationship history, or episode-scene description was retained."
                    ),
                },
                "source_categories": sorted(
                    {f"{source['provider']}:{source['sourceType']}" for source in relevant_sources.values()}
                ),
                "evidence_references": [
                    {
                        "source_id": source["sourceId"],
                        "provider": source["provider"],
                        "source_type": source["sourceType"],
                        "independence_group": source["independenceGroup"],
                        "title": source["title"],
                        "canonical_url": source["canonicalUrl"],
                    }
                    for source in sorted(
                        relevant_sources.values(),
                        key=lambda item: (
                            item["provider"],
                            item["sourceType"],
                            item["title"],
                        ),
                    )
                ],
                "scores": {
                    "ranking_profile_id": RANKING_PROFILE_ID,
                    "intent_fit": NOT_COMPUTED,
                    "audience_fit": {
                        "value": audience_fit,
                        "threshold": 0.40,
                        "evidence_floor_pass": audience_floor_pass,
                    },
                    "freshness": {
                        "value": freshness,
                        "window_days": freshness_days,
                        "diagnostic_only": True,
                    },
                    "fandom_velocity": {
                        "value": _round(len(signal_groups) / 3.0),
                        "independent_signal_groups": len(signal_groups),
                    },
                    "short_form_edit_potential": {
                        "status": "PRE_CONCEPT_DIAGNOSTIC_ONLY",
                        "observed_lower_bound": observable_short_form,
                        "threshold": 0.35,
                        "editability_term_hits_in_retained_text": editability_hits,
                        "specific_intro_component": NOT_COMPUTED,
                        "named_character_focus_component": NOT_COMPUTED,
                        "direct_tiktok_data_used": False,
                        "summary": (
                            f"Observed evidence-only lower bound {observable_short_form:.2f}; insufficient "
                            "to label a supported edit concept. This is an inferred cross-platform "
                            "diagnostic, not a virality probability, and direct TikTok data was not used."
                        ),
                    },
                    "relationship_or_character_salience": NOT_COMPUTED,
                    "footage_actionability": NOT_COMPUTED,
                    "evidence_quality": NOT_COMPUTED,
                    "source_diversity": {
                        "value": source_diversity,
                        "independence_groups": len(all_groups),
                        "groups": sorted(all_groups),
                        "diagnostic_only": True,
                    },
                    "uncertainty_penalty": NOT_COMPUTED,
                    "total": NOT_COMPUTED,
                    "editorial_concept_scores": NOT_COMPUTED,
                },
                "evidence_shape": {
                    "official_primary_groups": sorted(primary_groups),
                    "metadata_groups": sorted(metadata_groups),
                    "current_discussion_groups": sorted(signal_groups),
                    "would_pass_if_audience_supported": evidence_shape_pass,
                },
                "exact_rejection_gate": "audience-fit:evidence-floor",
                "additional_blockers": additional_blockers,
                "failure_classification": failure_class,
            }
        )

    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "development_only": True,
        "offline_replay": True,
        "fixture": fixture_path.as_posix(),
        "fixture_sha256": hashlib.sha256(raw).hexdigest(),
        "run_id": fixture["jobId"],
        "run_timestamp": fixture["generatedAt"],
        "prompt": fixture["prompt"],
        "root_cause": (
            "All eight researched candidates were removed before synthesis at the "
            "female-audience evidence floor. Three candidates had no current discussion "
            "retrieval at all; five had current coverage but no source-owned evidence of "
            "female-skewing fandom appeal. No candidate reached the final ranker, so no "
            "final score, concept, footage request, schema serialization, Rust handoff, or "
            "UI display limit caused this run's zero results."
        ),
        "stage_counts": fixture["stageCounts"],
        "thresholds": THRESHOLDS,
        "candidates": candidates,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    args = parser.parse_args()

    report = build_report(args.fixture)
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    args.markdown_output.write_text(_markdown(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "json": str(args.json_output),
                "markdown": str(args.markdown_output),
                "candidateCount": len(report["candidates"]),
                "networkCalls": 0,
                "sqliteReads": 0,
                "sqliteWrites": 0,
                "paidCostUsd": 0,
            },
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
