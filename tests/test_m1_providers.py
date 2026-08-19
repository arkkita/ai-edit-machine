from __future__ import annotations

import io
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlsplit
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ai_edit_machine.contracts import (  # noqa: E402
    EvidenceSourceType,
    ExcerptType,
    MediaKind,
    VerificationState,
)
from ai_edit_machine.m1_contracts import (  # noqa: E402
    CastIdentityFactV2,
    EpisodeLocatorFactV2,
    EvidenceClaimKind,
    MediaIdentityV2,
    WhyNowEventFactV2,
    WhyNowEventKind,
)
from ai_edit_machine.providers.base import (  # noqa: E402
    bounded_tool_call_detail,
    CallAuthorization,
    CancellationToken,
    EvidenceCandidate,
    ProviderBatch,
    ProviderDisabledError,
    ProviderError,
    ProviderRunOutcome,
    ProviderResearchContext,
    SecretCredential,
)
from ai_edit_machine.provider_schema import lower_provider_schema  # noqa: E402
from ai_edit_machine.providers.openai_web import OpenAIWebVerifier  # noqa: E402
from ai_edit_machine.providers.openai_web import (  # noqa: E402
    _candidate_search_query,
    _coverage_ranked_tv_seeds,
    _EvidenceBatchPayload,
    _EvidencePayload,
    _extract_tool_source_seed_hints,
    _independent_followup_seeds,
    _parse_page,
    _page_binds_claim,
    _prioritize_source_recovery,
    _staged_film_discussion_partitions,
    _staged_film_precision_retry_partitions,
    _tv_coverage_discovery_query,
    _tv_precision_retry_query,
    _tv_precision_slate_retry_query,
    _TrustedTVmazeEpisodeSeed,
    _trusted_tvmaze_episode_seeds,
    _tool_source_discussion_candidate,
    _unique_seed_for_parsed_page,
)
from ai_edit_machine.providers.openai_synthesis import (  # noqa: E402
    _canonicalize_nonfactual_source_keys,
    OpenAIResearchSynthesizer,
)
from ai_edit_machine.providers.normalize import normalize_batches  # noqa: E402
from ai_edit_machine.providers.token_budget import REQUEST_TOKEN_OVERHEAD  # noqa: E402
from ai_edit_machine.providers.transport import (  # noqa: E402
    FakeJsonTransport,
    FakeTextTransport,
    JsonResponse,
    UrllibJsonTransport,
    UrllibTextTransport,
)
from ai_edit_machine.providers.tvmaze import (  # noqa: E402
    _cast_provider_record_id,
    TVmazeProvider,
)
from ai_edit_machine.providers.xai_search import (  # noqa: E402
    XAIInvocationCapProof,
    XAISearchProvider,
    xai_request_policy_fingerprint,
)
from ai_edit_machine.providers.youtube import YouTubeOfficialProvider  # noqa: E402
from ai_edit_machine.research.intent import intent_from_query  # noqa: E402
from ai_edit_machine.research.source_ownership import (  # noqa: E402
    known_publisher_owner,
    reviewed_publisher_domains,
    source_record_binds_media_title,
    source_record_binds_tvmaze_show,
    tvmaze_show_source_binding,
)
from ai_edit_machine.research.urls import canonicalize_public_url  # noqa: E402
from ai_edit_machine.research.workflow import _could_support_recommendation  # noqa: E402


NOW = datetime.now(timezone.utc)


def _authorization(
    provider: str,
    operation: str,
    *,
    model: str | None = None,
    max_requests: int = 4,
    max_tool_calls: int = 2,
    privacy: str = "store_false",
    max_input_tokens: int | None = None,
    max_output_tokens: int = 2_000,
    allow_one_repair: bool = False,
) -> CallAuthorization:
    return CallAuthorization(
        job_id=uuid4(),
        reservation_id=uuid4(),
        provider=provider,
        operation=operation,
        configured_model=model,
        allowed_resolved_models=(model,) if model else (),
        max_requests=max_requests,
        max_tool_calls=max_tool_calls,
        max_input_tokens=(
            max_input_tokens
            if max_input_tokens is not None
            else (60_000 if operation == "research.synthesize" else 30_000)
        ),
        max_output_tokens=max_output_tokens,
        allow_one_repair=allow_one_repair,
        privacy_mode=privacy,
        live_calls_enabled=True,
    )


def _film_partition_payloads(
    sources_by_owner: dict[str, str], *, id_prefix: str
) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    for index, (owner, _) in enumerate(_film_discussion_plan()):
        source = sources_by_owner.get(owner)
        payload = _openai_payload(
            evidence=[], sources=[] if source is None else [{"url": source}]
        )
        payload["id"] = f"{id_prefix}_{index}"
        payloads.append(payload)
    return payloads


def _film_discussion_plan() -> tuple[tuple[str, tuple[str, ...]], ...]:
    return (
        *_staged_film_discussion_partitions(),
        *_staged_film_precision_retry_partitions(),
    )


class ProviderTests(unittest.TestCase):
    def test_openai_query_scoped_sources_bind_only_as_fetch_hints(self) -> None:
        sterling = _TrustedTVmazeEpisodeSeed(
            show_or_title="Sterling Point",
            season_number=1,
            episode_number=8,
            episode_title="I'm the Kid",
            event_or_release_at=NOW - timedelta(days=8),
            characters=("Annie", "Ellis"),
        )
        other = _TrustedTVmazeEpisodeSeed(
            show_or_title="Other Show",
            season_number=1,
            episode_number=2,
            episode_title="The Turn",
            event_or_release_at=NOW - timedelta(days=1),
            characters=(),
        )
        url = "https://www.cinemablend.com/streaming-news/sterling-point-love-triangle"
        payload = {
            "output": [
                {
                    "type": "web_search_call",
                    "action": {
                        "query": "Sterling Point romance reactions August 2026",
                        "sources": [{"url": url}],
                    },
                }
            ]
        }

        hints = _extract_tool_source_seed_hints(
            payload,
            tool_type="web_search_call",
            seeds=(other, sterling),
        )

        self.assertEqual(hints[canonicalize_public_url(url)], sterling)
        page = _parse_page(
            "<title>Una nueva serie romántica</title>"
            "<body>Sterling Point follows Annie and Ellis. "
            "The latest Sterling Point episode turns on their choice.</body>"
        )
        self.assertEqual(_unique_seed_for_parsed_page(page, (other, sterling)), sterling)
        incidental = _parse_page(
            "<title>How to Catch a Dirtbag</title>"
            "<body>An unrelated article. Related coverage: Sterling Point.</body>"
        )
        self.assertIsNone(
            _unique_seed_for_parsed_page(incidental, (other, sterling))
        )
        candidate = _tool_source_discussion_candidate(
            canonical=url,
            title="Una nueva serie romantica",
            published_at=NOW,
            seed=sterling,
            intent=intent_from_query("romance TV from the last three days"),
            cutoff=NOW - timedelta(days=3),
            now=NOW,
            policy_class="openai-web-evidence-v1",
        )
        self.assertEqual(
            candidate.provider_record_id,
            tvmaze_show_source_binding("Sterling Point", canonicalize_public_url(url)),
        )
        self.assertNotEqual(
            candidate.provider_record_id,
            tvmaze_show_source_binding(
                "Sterling Point",
                "https://variety.com/streaming/sterling-point-love-triangle",
            ),
        )
        self.assertIsNone(candidate.episode_locator)
        self.assertIsNone(candidate.quote_fact)
        self.assertIsNone(candidate.scene_fact)

    def test_openai_incidental_fightland_body_mention_cannot_bind_discussion(self) -> None:
        """Regress packaged r52 job ea5a7eda's unrelated accepted article."""

        fightland = _TrustedTVmazeEpisodeSeed(
            show_or_title="Fightland",
            season_number=1,
            episode_number=6,
            episode_title="Heavyweight",
            event_or_release_at=NOW,
            characters=("Tommy Gibbons", "Lucia Gibbons"),
        )
        unrelated = _parse_page(
            "<title>How to Catch a Dirtbag</title>"
            "<body>An unrelated investigative series article. "
            "More TV coverage: Fightland.</body>"
        )
        collision = _parse_page(
            "<title>A roundup of combat shows</title>"
            "<body>Fightland appears in one related-story rail. "
            "Another footer link also says Fightland.</body>"
        )
        supported = _parse_page(
            "<title>Una serie de boxeo que merece atención</title>"
            "<body>Fightland follows Tommy Gibbons through the current story. "
            "The latest Fightland discussion focuses on that choice.</body>"
        )

        self.assertIsNone(_unique_seed_for_parsed_page(unrelated, (fightland,)))
        self.assertIsNone(_unique_seed_for_parsed_page(collision, (fightland,)))
        self.assertEqual(
            _unique_seed_for_parsed_page(supported, (fightland,)), fightland
        )

    def test_live_r69_role_prefixed_character_joins_exact_tvmaze_performer(self) -> None:
        """Regress r69's rejection of the current Future-owned Furious page."""

        seeds = _trusted_tvmaze_episode_seeds(
            _live_r57_tvmaze_context(),
            intent=intent_from_query(
                "a good show for girls thatll get views on tiktok"
            ),
            now=NOW,
        )
        furious = next(seed for seed in seeds if seed.show_or_title == "Furious")
        live_shaped_page = _parse_page(
            "<title>What to watch: The 3 best new shows to binge on Hulu right now</title>"
            "<body>First up is Furious, starring Emmy Rossum as FBI agent Alice Black. "
            "The current Furious story follows her pursuit of a serial killer.</body>"
        )
        wrong_cast = _parse_page(
            "<title>Three unrelated action releases</title>"
            "<body>Furious is listed in a related rail. Another footer says Furious, "
            "but the article discusses an unrelated cast.</body>"
        )

        self.assertEqual(furious.characters, ("Special Agent Alice Black",))
        self.assertEqual(furious.performers, ("Emmy Rossum",))
        self.assertEqual(
            _unique_seed_for_parsed_page(live_shaped_page, seeds),
            furious,
        )
        self.assertIsNone(_unique_seed_for_parsed_page(wrong_cast, seeds))

    def test_openai_page_recovery_prefers_gate_capable_publisher_mix(self) -> None:
        paris = _TrustedTVmazeEpisodeSeed(
            show_or_title="Paris is Always a Good Idea",
            season_number=1,
            episode_number=4,
            episode_title="Knightly",
            event_or_release_at=NOW - timedelta(days=1),
            characters=(),
        )
        walter = _TrustedTVmazeEpisodeSeed(
            show_or_title="My Life With the Walter Boys",
            season_number=3,
            episode_number=10,
            episode_title="The Beautiful and the Damned",
            event_or_release_at=NOW - timedelta(days=9),
            characters=("Jackie", "Cole"),
        )
        unresolved = [
            (1, 0, "VIEWER_DISCUSSION", "https://www.cinemablend.com/paris-current", None, paris, None),
            (1, 1, "VIEWER_DISCUSSION", "https://www.tomsguide.com/walter-review", None, walter, None),
            (1, 2, "VIEWER_DISCUSSION", "https://www.techradar.com/walter-ending", None, walter, None),
            (1, 3, "VIEWER_DISCUSSION", "https://los40.com/walter-season-three", None, walter, None),
        ]

        ordered = _prioritize_source_recovery(
            unresolved,
            seeds=(paris, walter),
            official_domains=(),
            intent=intent_from_query(
                "romance TV, preferably from the last three days"
            ),
            now=NOW,
        )

        self.assertEqual([item[5] for item in ordered], [walter, paris, walter, walter])
        self.assertEqual(
            {known_publisher_owner("www.cinemablend.com"), known_publisher_owner("tomsguide.com")},
            {"owner:future-plc"},
        )
        self.assertEqual(known_publisher_owner("los40.com"), "owner:prisa-media")
        self.assertEqual(
            known_publisher_owner("www.thedailybeast.com"), "owner:iac"
        )
        domains = reviewed_publisher_domains()
        self.assertEqual(domains, tuple(sorted(set(domains))))
        self.assertTrue(
            {
                "tomsguide.com",
                "techradar.com",
                "los40.com",
                "thedailybeast.com",
            }.issubset(domains)
        )

    def test_openai_page_recovery_prioritizes_current_roundups_before_stale_exact_pages(self) -> None:
        """Regress packaged r53 job a7f0fa06's exhausted page allocation."""

        furious = _TrustedTVmazeEpisodeSeed(
            show_or_title="Furious",
            season_number=1,
            episode_number=4,
            episode_title="Fault Lines",
            event_or_release_at=NOW - timedelta(days=2),
            characters=("Alicia Torres", "Maya Torres"),
        )
        current_future = "https://www.tomsguide.com/entertainment/current-tv-roundup"
        current_prisa = "https://elpais.com/television/series/current-tv-column.html"
        stale_exact = "https://www.tomsguide.com/entertainment/furious-review"
        unresolved = [
            (
                0,
                0,
                "VIEWER_DISCUSSION",
                stale_exact,
                "Furious review",
                furious,
                NOW - timedelta(days=30),
            ),
            (
                1,
                1,
                "VIEWER_DISCUSSION",
                current_future,
                "Three shows to watch this weekend",
                furious,
                NOW - timedelta(hours=4),
            ),
            (
                1,
                2,
                "VIEWER_DISCUSSION",
                current_prisa,
                "La televisión de esta semana",
                furious,
                NOW - timedelta(hours=2),
            ),
        ]

        ordered = _prioritize_source_recovery(
            unresolved,
            seeds=(furious,),
            official_domains=(),
            intent=intent_from_query(
                "a good show for girls that'll get views on tiktok"
            ),
            now=NOW,
        )

        self.assertEqual(
            [item[3] for item in ordered],
            [current_future, current_prisa, stale_exact],
        )

    def test_r66_owner_completion_hints_precede_second_round_recovery(self) -> None:
        """Keep every live-sized missing-owner hint ahead of ordinary round two."""

        furious = _TrustedTVmazeEpisodeSeed(
            show_or_title="Furious",
            season_number=1,
            episode_number=6,
            episode_title="They Make a Noise Like Feathers",
            event_or_release_at=NOW - timedelta(days=1),
            characters=("Alice Black",),
        )
        precision = [
            (
                -2,
                index,
                "VIEWER_DISCUSSION",
                f"https://www.tomsguide.com/television/r66-future-{index}",
                "Current television coverage",
                furious,
                NOW,
            )
            for index in range(12)
        ] + [
            (
                -2,
                12 + index,
                "VIEWER_DISCUSSION",
                f"https://elpais.com/television/r66-prisa-{index}",
                "Current television coverage",
                furious,
                NOW,
            )
            for index in range(13)
        ]
        ordinary_urls = (
            "https://variety.com/television/furious-current",
            "https://deadline.com/television/furious-current",
        )
        ordinary = [
            (
                1,
                100 + index,
                "VIEWER_DISCUSSION",
                url,
                "Furious current discussion",
                furious,
                NOW,
            )
            for index, url in enumerate(ordinary_urls)
        ]

        ordered = _prioritize_source_recovery(
            [*precision, *ordinary],
            seeds=(furious,),
            official_domains=(),
            intent=intent_from_query(
                "a good show for girls thatll get views on tiktok"
            ),
            now=NOW,
        )
        ordered_urls = [item[3] for item in ordered]

        self.assertLess(
            max(ordered_urls.index(item[3]) for item in precision),
            ordered_urls.index(ordinary_urls[1]),
        )

    def test_openai_independent_followup_targets_only_bounded_fallback_slate(self) -> None:
        seeds = tuple(
            _TrustedTVmazeEpisodeSeed(
                show_or_title=f"Candidate {index}",
                season_number=1,
                episode_number=index,
                episode_title=f"Episode {index}",
                event_or_release_at=NOW - timedelta(days=age_days),
                characters=(),
            )
            for index, age_days in enumerate((1, 2, 3, 4, 5, 6, 7, 8), start=1)
        )

        selected = _independent_followup_seeds(
            seeds,
            intent=intent_from_query(
                "romance TV, preferably from the last three days"
            ),
            now=NOW,
        )

        self.assertEqual(
            [seed.show_or_title for seed in selected],
            ["Candidate 4", "Candidate 5", "Candidate 6", "Candidate 7"],
        )

    def test_openai_page_recovery_budget_cannot_be_monopolized_by_one_show(self) -> None:
        seeds = tuple(
            _TrustedTVmazeEpisodeSeed(
                show_or_title=f"Candidate {index}",
                season_number=1,
                episode_number=index,
                episode_title=f"Episode {index}",
                event_or_release_at=NOW - timedelta(days=index),
                characters=(),
            )
            for index in range(1, 9)
        )
        unresolved = [
            (
                1,
                source_order,
                "VIEWER_DISCUSSION",
                f"https://publisher-{source_order}.example/candidate-{seed_index}",
                None,
                seed,
                None,
            )
            for source_order, (seed_index, seed) in enumerate(
                (
                    (seed_index, seed)
                    for seed_index, seed in enumerate(seeds, start=1)
                    for _ in range(2)
                )
            )
        ]

        ordered = _prioritize_source_recovery(
            unresolved,
            seeds=seeds,
            official_domains=(),
            intent=intent_from_query("romance TV from the last fourteen days"),
            now=NOW,
        )

        first_twelve = [item[5] for item in ordered[:12]]
        self.assertEqual(set(first_twelve[:8]), set(seeds))
        self.assertTrue(all(first_twelve.count(seed) <= 2 for seed in seeds))

    def test_openai_page_parser_ignores_meta_without_an_identity_key(self) -> None:
        page = _parse_page(
            "<html><head><meta charset='utf-8'><meta content='not metadata'>"
            "<meta property='og:title' content='Example Show reaction'>"
            "<meta property='article:published_time' content='2026-08-15T10:00:00Z'>"
            "</head><body>Example Show</body></html>"
        )

        self.assertEqual(page.title, "Example Show reaction")
        self.assertEqual(
            page.published_at,
            datetime(2026, 8, 15, 10, 0, tzinfo=timezone.utc),
        )

    def test_openai_schema_uses_only_documented_string_constraints(self) -> None:
        canonical = _EvidenceBatchPayload.model_json_schema(mode="validation")
        self.assertIn("minLength", json.dumps(canonical, separators=(",", ":")))
        lowered = lower_provider_schema(canonical, "openai")
        rendered = json.dumps(lowered, separators=(",", ":"))
        self.assertNotIn("minLength", rendered)
        self.assertNotIn("maxLength", rendered)
        evidence_schema = lowered["$defs"]["_EvidencePayload"]
        # ``title`` is both a JSON Schema annotation keyword and an actual M1
        # evidence field. The annotation must be removed without deleting the
        # property from the strict output contract.
        self.assertNotIn("title", evidence_schema)
        self.assertIn("title", evidence_schema["properties"])
        self.assertIn("title", evidence_schema["required"])
        collision_schema = {
            "title": "schema annotation",
            "type": "object",
            "properties": {
                keyword: {"title": "field annotation", "type": "string"}
                for keyword in ("title", "format", "default", "examples")
            },
        }
        lowered_collision = lower_provider_schema(collision_schema, "openai")
        self.assertNotIn("title", lowered_collision)
        self.assertEqual(
            set(lowered_collision["properties"]),
            {"title", "format", "default", "examples"},
        )
        self.assertEqual(
            set(lowered_collision["required"]),
            {"title", "format", "default", "examples"},
        )
        # Canonical validation still owns length limits after provider output.
        with self.assertRaises(Exception):
            _EvidencePayload.model_validate(
                {
                    "source_type": "ARTICLE",
                    "canonical_url": "https://example.com/current-discussion",
                    "title": "",
                    "excerpt_type": "PARAPHRASE",
                    "excerpt": "A bounded discussion signal.",
                    "verification": "SECONDARY_CORROBORATED",
                    "claim_kind": "VIEWER_DISCUSSION",
                    "supports_why_now": True,
                    "confidence": 0.5,
                },
                strict=True,
            )

    def test_tvmaze_match_cannot_promote_unbound_official_why_now_page(self) -> None:
        locator = EpisodeLocatorFactV2(
            show_or_title="Example Show",
            season_number=1,
            episode_number=2,
            episode_title="Turning Point",
        )
        identity = MediaIdentityV2(
            media_kind=MediaKind.TV_EPISODE,
            show_or_title="Example Show",
            season_number=1,
            episode_number=2,
            episode_title="Turning Point",
        )
        tvmaze = EvidenceCandidate(
            provider="tvmaze",
            provider_record_id="episode-12",
            source_type=EvidenceSourceType.METADATA,
            canonical_url="https://www.tvmaze.com/episodes/12",
            title="Example Show S01E02 Turning Point",
            author_or_channel="TVmaze",
            excerpt_type=ExcerptType.PARAPHRASE,
            excerpt="TVmaze lists Example Show Season 1 Episode 2.",
            verification=VerificationState.SECONDARY_CORROBORATED,
            claim_kind=EvidenceClaimKind.EPISODE_IDENTITY,
            supports_why_now=False,
            policy_class="tvmaze-metadata-v1",
            event_or_release_at=NOW,
            episode_locator=locator,
        )
        unbound_official = EvidenceCandidate(
            provider="openai",
            provider_record_id="official-old-page",
            source_type=EvidenceSourceType.PRIMARY_RELEASE,
            canonical_url="https://official.example/show/s1e2",
            title="Example Show S01E02 Turning Point",
            author_or_channel="Official Network",
            excerpt_type=ExcerptType.PARAPHRASE,
            excerpt="Model claims this episode was released today.",
            verification=VerificationState.PRIMARY_VERIFIED,
            claim_kind=EvidenceClaimKind.WHY_NOW,
            supports_why_now=True,
            policy_class="openai-web-evidence-v1",
            event_or_release_at=NOW,
            citation_verified=True,
            content_binding_verified=False,
            adapter_source_title="Example Show S01E02 Turning Point",
            episode_locator=locator,
            why_now_event=WhyNowEventFactV2(
                event_kind=WhyNowEventKind.EPISODE_RELEASE,
                media_identity=identity,
            ),
        )
        _, claims = normalize_batches(
            [
                ProviderBatch(provider="tvmaze", evidence=(tvmaze,)),
                ProviderBatch(provider="openai", evidence=(unbound_official,)),
            ],
            retrieved_at=NOW,
            official_hosts={"official.example"},
        )
        why_now = next(
            claim for claim in claims if claim.claim_kind is EvidenceClaimKind.WHY_NOW
        )
        self.assertEqual(why_now.verification, VerificationState.LEAD_ONLY)

    def test_quote_binding_rejects_multi_episode_hub(self) -> None:
        item = _EvidencePayload.model_validate_json(
            json.dumps(
                {
                    "source_type": "PRIMARY_RELEASE",
                    "canonical_url": "https://example.com/show-hub",
                    "title": "Show hub",
                    "excerpt_type": "SHORT_QUOTE",
                    "excerpt": "I still choose you",
                    "verification": "PRIMARY_VERIFIED",
                    "claim_kind": "QUOTE",
                    "supports_why_now": False,
                    "quote_fact": {
                        "exact_text": "I still choose you",
                        "speaker": "Alex",
                        "media_identity": {
                            "media_kind": "TV_EPISODE",
                            "show_or_title": "Example Show",
                            "season_number": 1,
                            "episode_number": 2,
                            "episode_title": "Turning Point",
                        },
                        "episode_locator": {
                            "show_or_title": "Example Show",
                            "season_number": 1,
                            "episode_number": 2,
                            "episode_title": "Turning Point",
                        },
                    },
                    "confidence": 0.9,
                }
            ),
            strict=True,
        )
        nodes = [
            {
                "@type": "TVEpisode",
                "partOfSeries": {"name": "Example Show"},
                "partOfSeason": {"seasonNumber": 1},
                "episodeNumber": number,
            }
            for number in (2, 3)
        ]
        html = (
            '<script type="application/ld+json">'
            + json.dumps(nodes)
            + "</script><body>Alex: I still choose you.</body>"
        )
        self.assertFalse(_page_binds_claim(item, html))

    def test_openai_refusal_preserves_billable_usage_and_tool_details(self) -> None:
        payload = {
            "id": "resp_1",
            "model": "gpt-5.6-luna",
            "status": "completed",
            "usage": {
                "input_tokens": 100,
                "input_tokens_details": {"cached_tokens": 25},
                "output_tokens": 12,
                "output_tokens_details": {"reasoning_tokens": 3},
            },
            "output": [
                {"type": "web_search_call", "id": "search_1", "action": {"sources": []}},
                {
                    "type": "message",
                    "content": [{"type": "refusal", "refusal": "I cannot help."}],
                },
            ],
        }
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=(),
            transport=FakeJsonTransport([JsonResponse(200, {}, payload)]),
        )
        result = provider.collect(
            intent_from_query("current TV episode"),
            authorization=_authorization(
                "openai", "research.web_verify", model="gpt-5.6-luna"
            ),
            cancellation=CancellationToken(),
        )
        self.assertEqual(result.outcome, ProviderRunOutcome.REFUSAL)
        self.assertEqual(result.usage.request_count, 1)
        self.assertEqual(result.usage.cached_input_tokens, 25)
        self.assertEqual(result.usage.reasoning_tokens, 3)
        self.assertEqual(
            result.usage.tool_call_details,
            (bounded_tool_call_detail("web_search_call", "search_1"),),
        )

    def test_openai_web_context_usage_has_a_separate_conservative_ceiling(self) -> None:
        payload = {
            "id": "resp_context_accounting",
            "model": "gpt-5.6-luna",
            "status": "completed",
            "usage": {
                "input_tokens": 46_828,
                "input_tokens_details": {"cached_tokens": 5_484},
                "output_tokens": 2_408,
                "output_tokens_details": {"reasoning_tokens": 1_182},
            },
            "output": [
                {
                    "type": "web_search_call",
                    "id": f"search_{index}",
                    "action": {"sources": []},
                }
                for index in range(5)
            ]
            + [
                {
                    "type": "message",
                    "content": [{"type": "refusal", "refusal": "bounded fixture"}],
                }
            ],
        }
        transport = FakeJsonTransport([JsonResponse(200, {}, payload)])
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=(),
            search_context_size="low",
            request_body_max_input_tokens=30_000,
            request_max_tool_calls=4,
            transport=transport,
        )

        result = provider.collect(
            intent_from_query("current TV episode"),
            authorization=_authorization(
                "openai",
                "research.web_verify",
                model="gpt-5.6-luna",
                max_tool_calls=6,
                max_input_tokens=120_000,
                max_output_tokens=6_000,
            ),
            cancellation=CancellationToken(),
            context=_trusted_tvmaze_context(),
        )

        self.assertEqual(result.outcome, ProviderRunOutcome.REFUSAL)
        self.assertEqual(result.usage.input_tokens, 46_828)
        self.assertEqual(result.usage.tool_calls, 5)
        body = transport.requests[0]["body"]
        self.assertEqual(body["max_tool_calls"], 4)
        self.assertEqual(body["tools"][0]["search_context_size"], "low")
        self.assertIn("at least two independent current discussion sources", body["instructions"])
        self.assertIn("one separate query for every supplied candidate", body["instructions"])
        self.assertIn("M1_SOURCE_LEADS_V2", body["instructions"])
        self.assertIn("claim-local URL citation", body["instructions"])
        self.assertNotIn("text", body)

    def test_openai_request_body_ceiling_remains_tighter_than_billed_usage(self) -> None:
        transport = FakeJsonTransport([])
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=(),
            request_body_max_input_tokens=1,
            transport=transport,
        )

        result = provider.collect(
            intent_from_query("current TV episode"),
            authorization=_authorization(
                "openai",
                "research.web_verify",
                model="gpt-5.6-luna",
                max_tool_calls=6,
                max_input_tokens=120_000,
                max_output_tokens=6_000,
            ),
            cancellation=CancellationToken(),
        )

        self.assertEqual(result.outcome, ProviderRunOutcome.ERROR)
        self.assertEqual(result.usage.request_count, 0)
        self.assertEqual(transport.requests, [])

    def test_openai_hashes_unbounded_opaque_tool_ids_into_protocol_safe_details(self) -> None:
        opaque_id = "provider\nopaque:" + ("x" * 2_000)
        payload = {
            "id": "resp_opaque_tool",
            "model": "gpt-5.6-luna",
            "status": "completed",
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "output": [
                {"type": "web_search_call", "id": opaque_id, "action": {"sources": []}},
                {
                    "type": "message",
                    "content": [{"type": "refusal", "refusal": "I cannot help."}],
                },
            ],
        }
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=(),
            transport=FakeJsonTransport([JsonResponse(200, {}, payload)]),
        )
        result = provider.collect(
            intent_from_query("current TV episode"),
            authorization=_authorization(
                "openai", "research.web_verify", model="gpt-5.6-luna"
            ),
            cancellation=CancellationToken(),
        )
        detail = result.usage.tool_call_details[0]
        self.assertEqual(detail, bounded_tool_call_detail("web_search_call", opaque_id))
        self.assertLessEqual(len(detail), 256)
        self.assertTrue(detail.isascii())
        self.assertNotIn("\n", detail)

    def test_openai_strict_output_failure_preserves_returned_usage(self) -> None:
        payload = {
            "id": "resp_invalid_evidence",
            "model": "gpt-5.6-luna",
            "status": "completed",
            "usage": {
                "input_tokens": 321,
                "input_tokens_details": {"cached_tokens": 21},
                "output_tokens": 45,
                "output_tokens_details": {"reasoning_tokens": 7},
            },
            "output": [
                {
                    "type": "web_search_call",
                    "id": "search_invalid_evidence",
                    "action": {"sources": []},
                },
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "{}"}],
                },
            ],
        }
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=(),
            transport=FakeJsonTransport([JsonResponse(200, {}, payload)]),
        )

        result = provider.collect(
            intent_from_query("current TV episode"),
            authorization=_authorization(
                "openai", "research.web_verify", model="gpt-5.6-luna"
            ),
            cancellation=CancellationToken(),
        )

        self.assertEqual(result.outcome, ProviderRunOutcome.ERROR)
        self.assertEqual(
            result.error,
            "OpenAI structured evidence contract rejected [evidence:missing]",
        )
        self.assertNotIn("resp_invalid_evidence", result.error or "")
        self.assertNotIn("search_invalid_evidence", result.error or "")
        self.assertEqual(result.usage.provider_request_id, "resp_invalid_evidence")
        self.assertEqual(result.usage.request_count, 1)
        self.assertEqual(result.usage.input_tokens, 321)
        self.assertEqual(result.usage.cached_input_tokens, 21)
        self.assertEqual(result.usage.output_tokens, 45)
        self.assertEqual(result.usage.reasoning_tokens, 7)
        self.assertEqual(result.usage.tool_calls, 1)
        self.assertEqual(
            result.usage.tool_call_details,
            (
                bounded_tool_call_detail(
                    "web_search_call", "search_invalid_evidence"
                ),
            ),
        )

    def test_openai_omits_one_invalid_leaf_without_discarding_valid_evidence(self) -> None:
        url = "https://variety.com/example-current-discussion"
        excerpt = (
            "Example Show viewers are discussing the new romantic reversal and its payoff."
        )
        valid = {
            "source_type": "ARTICLE",
            "canonical_url": url,
            "title": "Example Show current discussion",
            "excerpt_type": "PARAPHRASE",
            "excerpt": excerpt,
            "verification": "SECONDARY_CORROBORATED",
            "claim_kind": "VIEWER_DISCUSSION",
            "supports_why_now": True,
            "source_created_at": NOW.isoformat(),
            "page_published_at": NOW.isoformat(),
            "confidence": 0.8,
        }
        payload = _openai_payload(
            evidence=[{"title": "PRIVATE RAW VALUE MUST NOT LEAK"}, valid],
            sources=[
                {
                    "url": url,
                    "title": "Example Show current discussion",
                    "published_at": NOW.isoformat(),
                }
            ],
        )
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=(),
            transport=FakeJsonTransport([JsonResponse(200, {}, payload)]),
            page_transport=FakeTextTransport([f"<body>{excerpt}</body>"]),
        )

        result = provider.collect(
            intent_from_query("Example Show current discussion"),
            authorization=_authorization(
                "openai", "research.web_verify", model="gpt-5.6-luna"
            ),
            cancellation=CancellationToken(),
        )

        self.assertEqual(result.outcome, ProviderRunOutcome.SUCCESS)
        self.assertEqual(len(result.evidence), 1)
        self.assertTrue(any("invalid structured evidence item" in item for item in result.warnings))
        self.assertNotIn("PRIVATE RAW VALUE", " ".join(result.warnings))

    def test_openai_ignores_malformed_model_dates_and_uses_tool_publication_time(self) -> None:
        old = NOW - timedelta(days=120)
        evidence = {
            "source_type": "ARTICLE",
            "canonical_url": "https://variety.com/example-film-discussion",
            "title": "model title",
            "excerpt_type": "PARAPHRASE",
            "excerpt": "Example Film discussion",
            "verification": "SECONDARY_CORROBORATED",
            "claim_kind": "VIEWER_DISCUSSION",
            "supports_why_now": True,
            "source_created_at": "",
            "page_published_at": "August 15, 2026",
            "event_or_release_at": NOW.isoformat(),
            "confidence": 0.7,
        }
        payload = _openai_payload(
            evidence=[evidence],
            sources=[
                {
                    "url": evidence["canonical_url"],
                    "title": "Example Film discussion",
                    "published_at": old.isoformat(),
                }
            ],
        )
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=(),
            transport=FakeJsonTransport([JsonResponse(200, {}, payload)]),
            page_transport=FakeTextTransport(
                ["<body>Example Film discussion</body>"]
            ),
        )
        result = provider.collect(
            intent_from_query("Example Film current discussion"),
            authorization=_authorization(
                "openai", "research.web_verify", model="gpt-5.6-luna"
            ),
            cancellation=CancellationToken(),
        )
        self.assertEqual(len(result.evidence), 1)
        self.assertEqual(result.evidence[0].source_created_at, old)
        self.assertEqual(result.evidence[0].page_published_at, old)
        self.assertFalse(
            any("invalid structured evidence item" in warning for warning in result.warnings)
        )

    def test_openai_discussion_uses_per_url_title_metadata_not_model_paraphrase(self) -> None:
        urls = (
            "https://variety.com/example-film-one",
            "https://thewrap.com/example-film-two",
        )
        excerpts = (
            "Example Film viewers emphasize the quiet promise in the new trailer.",
            "Example Film discussion centers on the relationship reversal and payoff.",
        )
        evidence = [
            {
                "source_type": "ARTICLE",
                "canonical_url": url,
                "title": "model title",
                "excerpt_type": "PARAPHRASE",
                "excerpt": excerpt,
                "verification": "SECONDARY_CORROBORATED",
                "claim_kind": "VIEWER_DISCUSSION",
                "supports_why_now": True,
                "confidence": 0.7,
            }
            for url, excerpt in zip(urls, excerpts, strict=True)
        ]
        payload = _openai_payload(
            evidence=evidence,
            sources=[
                {"url": url, "title": f"Example Film discussion {index}", "published_at": NOW.isoformat()}
                for index, url in enumerate(urls)
            ],
        )
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=(),
            transport=FakeJsonTransport([JsonResponse(200, {}, payload)]),
            # These bodies deliberately contain the other row's prose.  The
            # adapter must not retain either model paraphrase or spend a page
            # fetch when the cited URL already has a title and publication date.
            page_transport=FakeTextTransport(
                [f"<body>{excerpts[1]}</body>", f"<body>{excerpts[0]}</body>"]
            ),
        )
        batch = provider.collect(
            intent_from_query("Example Film current discussion"),
            authorization=_authorization(
                "openai", "research.web_verify", model="gpt-5.6-luna", max_requests=3
            ),
            cancellation=CancellationToken(),
        )
        self.assertEqual(batch.usage.request_count, 1)
        self.assertEqual(len(batch.evidence), 2)
        self.assertEqual(
            {item.excerpt for item in batch.evidence},
            {
                "Current cited-source title: Example Film discussion 0",
                "Current cited-source title: Example Film discussion 1",
            },
        )
        self.assertTrue(all(excerpt not in {item.excerpt for item in batch.evidence} for excerpt in excerpts))
        _, claims = normalize_batches([batch], retrieved_at=NOW, official_hosts=set())
        self.assertEqual(len(claims), 2)
        self.assertTrue(
            all(claim.verification.value == "SECONDARY_CORROBORATED" for claim in claims)
        )

    def test_openai_discussion_fetches_page_metadata_not_model_paraphrase(self) -> None:
        url = "https://variety.com/example-show-current"
        model_excerpt = "Invented prose that the cited page never said."
        evidence = {
            "source_type": "ARTICLE",
            "canonical_url": url,
            "title": "model title is ignored",
            "excerpt_type": "PARAPHRASE",
            "excerpt": model_excerpt,
            "verification": "SECONDARY_CORROBORATED",
            "claim_kind": "VIEWER_DISCUSSION",
            "supports_why_now": True,
            "confidence": 0.99,
        }
        payload = _openai_payload(evidence=[evidence], sources=[{"url": url}])
        page_title = "Example Show Alex and Jamie relationship discussion"
        html = (
            f'<meta property="og:title" content="{page_title}">'
            f'<meta property="article:published_time" content="{NOW.isoformat()}">'
            "<body>The article body does not contain the model paraphrase.</body>"
        )
        page_transport = FakeTextTransport([html])
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=(),
            transport=FakeJsonTransport([JsonResponse(200, {}, payload)]),
            page_transport=page_transport,
        )

        batch = provider.collect(
            intent_from_query("Example Show Alex Jamie relationship"),
            authorization=_authorization(
                "openai", "research.web_verify", model="gpt-5.6-luna", max_requests=2
            ),
            cancellation=CancellationToken(),
        )

        self.assertEqual(batch.usage.request_count, 2)
        self.assertEqual(len(page_transport.requests), 1)
        self.assertEqual(len(batch.evidence), 1)
        self.assertEqual(batch.evidence[0].title, page_title)
        self.assertEqual(
            batch.evidence[0].excerpt,
            f"Current cited-source title: {page_title}",
        )
        self.assertNotIn(model_excerpt, batch.evidence[0].excerpt)
        self.assertEqual(batch.evidence[0].verification.value, "SECONDARY_CORROBORATED")

    def test_openai_visible_official_episode_page_binds_exact_identity_and_date(self) -> None:
        url = "https://example.com/example-show/season-1/episode-2"
        evidence = {
            "provider_record_id": "untrusted-model-shared-id",
            "source_type": "PRIMARY_RELEASE",
            "canonical_url": url,
            "title": "model title",
            "excerpt_type": "PARAPHRASE",
            "excerpt": "Model prose is replaced after binding.",
            "verification": "PRIMARY_VERIFIED",
            "claim_kind": "WHY_NOW",
            "supports_why_now": True,
            "episode_locator": {
                "show_or_title": "Example Show",
                "season_number": 1,
                "episode_number": 2,
                "episode_title": "Turning Point",
            },
            "why_now_event": {
                "event_kind": "EPISODE_RELEASE",
                "media_identity": {
                    "media_kind": "TV_EPISODE",
                    "show_or_title": "Example Show",
                    "season_number": 1,
                    "episode_number": 2,
                    "episode_title": "Turning Point",
                },
            },
            "event_or_release_at": NOW.date().isoformat(),
            "confidence": 0.9,
        }
        payload = _openai_payload(evidence=[evidence], sources=[{"url": url}])
        readable_date = f"{NOW.strftime('%B')} {NOW.day}, {NOW.year}"
        html = (
            "<title>Example Show - Season 1 Episode 2 - Turning Point</title>"
            f"<body>Stream the episode on {readable_date}.</body>"
        )
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=("example.com",),
            transport=FakeJsonTransport([JsonResponse(200, {}, payload)]),
            page_transport=FakeTextTransport([html]),
        )

        batch = provider.collect(
            intent_from_query("Example Show current episode"),
            authorization=_authorization(
                "openai", "research.web_verify", model="gpt-5.6-luna", max_requests=2
            ),
            cancellation=CancellationToken(),
            context=_trusted_tvmaze_context(),
        )
        _, claims = normalize_batches(
            [batch], retrieved_at=NOW, official_hosts={"example.com"}
        )
        self.assertEqual(len(claims), 1)
        self.assertIsNone(batch.evidence[0].provider_record_id)
        self.assertEqual(claims[0].verification.value, "PRIMARY_VERIFIED")
        self.assertEqual(claims[0].episode_locator.episode_number, 2)
        self.assertNotIn("Model prose", claims[0].text)
        wrong_episode_html = (
            "<title>Example Show - Season 1 Episode 3 - Turning Point</title>"
            f"<body>Stream the episode on {readable_date}.</body>"
        )
        parsed_evidence = _EvidencePayload.model_validate_json(
            json.dumps({**evidence, "event_or_release_at": NOW.isoformat()}),
            strict=True,
        )
        self.assertFalse(_page_binds_claim(parsed_evidence, wrong_episode_html))

    def test_openai_claim_local_citation_and_tvmaze_seed_bind_official_episode(self) -> None:
        url = "https://example.com/example-show/turning-point"
        evidence = {
            "source_type": "ARTICLE",
            "canonical_url": url,
            "title": "untrusted model title",
            "excerpt_type": "PARAPHRASE",
            "excerpt": "Example Show released Turning Point as Season 1 Episode 2 today.",
            "verification": "PRIMARY_VERIFIED",
            "claim_kind": "WHY_NOW",
            "supports_why_now": True,
            "episode_locator": {
                "show_or_title": "Example Show",
                "season_number": 1,
                "episode_number": 2,
                "episode_title": "Turning Point",
            },
            "why_now_event": {
                "event_kind": "EPISODE_RELEASE",
                "media_identity": {
                    "media_kind": "TV_EPISODE",
                    "show_or_title": "Example Show",
                    "season_number": 1,
                    "episode_number": 2,
                    "episode_title": "Turning Point",
                },
            },
            "event_or_release_at": NOW.isoformat(),
            "confidence": 0.9,
        }
        payload = _openai_payload(evidence=[evidence], sources=[{"url": url}])
        _attach_excerpt_citation(
            payload,
            excerpt=evidence["excerpt"],
            url=url,
            title="Example Show — Turning Point",
        )
        page_transport = FakeTextTransport([])
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=(),
            transport=FakeJsonTransport([JsonResponse(200, {}, payload)]),
            page_transport=page_transport,
        )

        batch = provider.collect(
            intent_from_query("Example Show current episode"),
            authorization=_authorization(
                "openai", "research.web_verify", model="gpt-5.6-luna", max_requests=1
            ),
            cancellation=CancellationToken(),
            context=_trusted_tvmaze_context(),
        )
        _, claims = normalize_batches(
            [batch], retrieved_at=NOW, official_hosts={"example.com"}
        )

        self.assertEqual(batch.usage.request_count, 1)
        self.assertEqual(page_transport.requests, [])
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0].verification, VerificationState.PRIMARY_VERIFIED)
        self.assertEqual(claims[0].episode_locator.episode_number, 2)
        self.assertEqual(batch.evidence[0].source_type, EvidenceSourceType.PRIMARY_RELEASE)
        self.assertNotIn("untrusted model title", batch.evidence[0].title)

    def test_openai_claim_local_citation_binds_current_discussion_metadata(self) -> None:
        url = "https://variety.com/example-show-alex-jamie"
        evidence = {
            "source_type": "ARTICLE",
            "canonical_url": url,
            "title": "untrusted model title",
            "excerpt_type": "PARAPHRASE",
            "excerpt": "Viewers are discussing Alex and Jamie after the current episode.",
            "verification": "SECONDARY_CORROBORATED",
            "claim_kind": "VIEWER_DISCUSSION",
            "supports_why_now": True,
            "source_created_at": NOW.isoformat(),
            "page_published_at": NOW.isoformat(),
            "confidence": 0.8,
        }
        payload = _openai_payload(evidence=[evidence], sources=[{"url": url}])
        source_title = "Example Show: viewers discuss Alex and Jamie"
        _attach_excerpt_citation(
            payload,
            excerpt=evidence["excerpt"],
            url=url,
            title=source_title,
        )
        page_transport = FakeTextTransport([])
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=(),
            transport=FakeJsonTransport([JsonResponse(200, {}, payload)]),
            page_transport=page_transport,
        )

        batch = provider.collect(
            intent_from_query("Example Show Alex Jamie relationship from the last three days"),
            authorization=_authorization(
                "openai", "research.web_verify", model="gpt-5.6-luna", max_requests=1
            ),
            cancellation=CancellationToken(),
        )

        self.assertEqual(page_transport.requests, [])
        self.assertEqual(len(batch.evidence), 1)
        self.assertEqual(batch.evidence[0].title, source_title)
        self.assertEqual(
            batch.evidence[0].verification,
            VerificationState.SECONDARY_CORROBORATED,
        )
        self.assertEqual(batch.evidence[0].source_created_at, NOW)
        self.assertNotIn(evidence["excerpt"], batch.evidence[0].excerpt)

    def test_openai_response_wide_or_swapped_citation_cannot_bind_claim(self) -> None:
        first_url = "https://variety.com/example-show-first"
        second_url = "https://thewrap.com/example-show-second"
        first = {
            "source_type": "ARTICLE",
            "canonical_url": first_url,
            "title": "first model title",
            "excerpt_type": "PARAPHRASE",
            "excerpt": "First current discussion claim.",
            "verification": "SECONDARY_CORROBORATED",
            "claim_kind": "VIEWER_DISCUSSION",
            "supports_why_now": True,
            "source_created_at": NOW.isoformat(),
            "confidence": 0.7,
        }
        second = {
            **first,
            "canonical_url": second_url,
            "title": "second model title",
            "excerpt": "Second current discussion claim.",
        }
        payload = _openai_payload(
            evidence=[first, second],
            sources=[{"url": first_url}, {"url": second_url}],
        )
        _attach_excerpt_citation(
            payload,
            excerpt=first["excerpt"],
            url=second_url,
            title="Example Show second source",
        )
        _attach_excerpt_citation(
            payload,
            excerpt=second["excerpt"],
            url=first_url,
            title="Example Show first source",
        )
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=(),
            transport=FakeJsonTransport([JsonResponse(200, {}, payload)]),
            page_transport=FakeTextTransport([]),
        )

        batch = provider.collect(
            intent_from_query("Example Show current discussion"),
            authorization=_authorization(
                "openai", "research.web_verify", model="gpt-5.6-luna", max_requests=1
            ),
            cancellation=CancellationToken(),
        )

        self.assertEqual(batch.evidence, ())
        self.assertTrue(
            any("verification budget was exhausted" in warning for warning in batch.warnings)
        )

    def test_openai_citation_line_protocol_yields_seed_bound_gate_evidence(self) -> None:
        payload = _openai_cited_line_payload(
            [
                (
                    "WHY_NOW\t1",
                    "https://example.com/example-show/turning-point",
                    "Example Show — Turning Point",
                ),
                (
                    "VIEWER_DISCUSSION\t1",
                    "https://variety.com/example-show-alex-jamie",
                    "Example Show fans discuss Alex and Jamie",
                ),
                (
                    "VIEWER_DISCUSSION\t1",
                    "https://thewrap.com/example-show-relationship",
                    "Example Show relationship becomes the talking point",
                ),
            ]
        )
        output = payload["output"]
        assert isinstance(output, list)
        sources = output[0]["action"]["sources"]
        assert isinstance(sources, list)
        for source in sources[1:]:
            source["published_at"] = (NOW - timedelta(hours=1)).isoformat()
        readable_date = f"{NOW.strftime('%B')} {NOW.day}, {NOW.year}"
        page_transport = FakeTextTransport(
            [
                "<title>Example Show - Season 1 Episode 2 - Turning Point</title>"
                f"<body>Available {readable_date}.</body>"
            ]
        )
        transport = FakeJsonTransport([JsonResponse(200, {}, payload)])
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=(),
            transport=transport,
            page_transport=page_transport,
        )

        batch = provider.collect(
            intent_from_query("Example Show Alex Jamie romance from the last three days"),
            authorization=_authorization(
                "openai", "research.web_verify", model="gpt-5.6-luna", max_requests=2
            ),
            cancellation=CancellationToken(),
            context=_trusted_tvmaze_context(),
        )
        _, claims = normalize_batches(
            [batch], retrieved_at=NOW, official_hosts={"example.com"}
        )

        self.assertNotIn("text", transport.requests[0]["body"])
        self.assertEqual(batch.usage.request_count, 2)
        self.assertEqual(len(page_transport.requests), 1)
        self.assertEqual(len(batch.evidence), 3)
        self.assertEqual(
            sum(claim.verification is VerificationState.PRIMARY_VERIFIED for claim in claims),
            1,
        )
        self.assertEqual(
            sum(
                claim.verification is VerificationState.SECONDARY_CORROBORATED
                and claim.claim_kind is EvidenceClaimKind.VIEWER_DISCUSSION
                for claim in claims
            ),
            2,
        )

    def test_openai_citation_line_accepts_exact_deterministic_seed_aliases(self) -> None:
        payload = _openai_cited_line_payload(
            [
                (
                    "WHY_NOW\tcandidate 1",
                    "https://example.com/example-show/turning-point",
                    "Example Show - Turning Point",
                ),
                (
                    "VIEWER_DISCUSSION\tExample Show",
                    "https://variety.com/example-show-alex-jamie",
                    "Example Show fans discuss Alex and Jamie",
                ),
                (
                    "VIEWER_DISCUSSION\tcandidate #1",
                    "https://thewrap.com/example-show-relationship",
                    "Example Show relationship becomes the talking point",
                ),
            ]
        )
        output = payload["output"]
        assert isinstance(output, list)
        sources = output[0]["action"]["sources"]
        assert isinstance(sources, list)
        for source in sources[1:]:
            source["published_at"] = (NOW - timedelta(hours=1)).isoformat()
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=(),
            transport=FakeJsonTransport([JsonResponse(200, {}, payload)]),
            page_transport=FakeTextTransport(
                [
                    "<title>Example Show - Season 1 Episode 2 - Turning Point</title>"
                    f'<meta property="article:published_time" content="{NOW.isoformat()}">'
                ]
            ),
        )

        batch = provider.collect(
            intent_from_query("Example Show Alex Jamie romance from the last three days"),
            authorization=_authorization(
                "openai", "research.web_verify", model="gpt-5.6-luna", max_requests=2
            ),
            cancellation=CancellationToken(),
            context=_trusted_tvmaze_context(),
        )

        self.assertEqual(len(batch.evidence), 3)
        self.assertFalse(any("unknown candidate selector" in item for item in batch.warnings))

    def test_openai_citation_identity_recovers_a_placeholder_selector(self) -> None:
        date_path = f"{NOW.year}/{NOW.month:02d}/{NOW.day:02d}"
        payload = _openai_cited_line_payload(
            [
                (
                    "VIEWER_DISCUSSION\tcandidate-number",
                    f"https://variety.com/{date_path}/tv/example-show-romance/",
                    "Example Show fans discuss Alex and Jamie",
                ),
                (
                    "VIEWER_DISCUSSION\tselected-candidate",
                    f"https://thewrap.com/{date_path}/example-show-relationship/",
                    "Example Show relationship becomes the talking point",
                ),
            ]
        )
        page_transport = FakeTextTransport([])
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=(),
            transport=FakeJsonTransport([JsonResponse(200, {}, payload)]),
            page_transport=page_transport,
        )

        batch = provider.collect(
            intent_from_query("Example Show Alex Jamie romance from the last three days"),
            authorization=_authorization(
                "openai", "research.web_verify", model="gpt-5.6-luna", max_requests=1
            ),
            cancellation=CancellationToken(),
            context=_trusted_tvmaze_context(),
        )

        self.assertEqual(page_transport.requests, [])
        self.assertEqual(len(batch.evidence), 2)
        self.assertTrue(
            all(
                item.claim_kind is EvidenceClaimKind.VIEWER_DISCUSSION
                and item.verification is VerificationState.SECONDARY_CORROBORATED
                and item.content_binding_verified
                for item in batch.evidence
            )
        )
        self.assertFalse(any("unknown candidate selector" in item for item in batch.warnings))

    def test_openai_rejects_selector_that_conflicts_with_citation_identity(self) -> None:
        base_context = _trusted_tvmaze_context()
        other_locator = EpisodeLocatorFactV2(
            show_or_title="Other Show",
            season_number=2,
            episode_number=3,
            episode_title="Crossed Wires",
        )
        other_episode = EvidenceCandidate(
            provider="tvmaze",
            provider_record_id="episode:3",
            source_type=EvidenceSourceType.METADATA,
            canonical_url="https://www.tvmaze.com/episodes/3/crossed-wires",
            title="Other Show - S02E03: Crossed Wires",
            author_or_channel="TVmaze",
            excerpt_type=ExcerptType.PARAPHRASE,
            excerpt="TVmaze lists Crossed Wires as Season 2 Episode 3.",
            verification=VerificationState.SECONDARY_CORROBORATED,
            claim_kind=EvidenceClaimKind.EPISODE_IDENTITY,
            supports_why_now=False,
            policy_class="tvmaze-metadata-v1",
            event_or_release_at=NOW,
            citation_verified=True,
            episode_locator=other_locator,
        )
        context = ProviderResearchContext(
            prior_evidence=(*base_context.prior_evidence, other_episode),
            trusted_official_hosts=base_context.trusted_official_hosts,
        )
        payload = _openai_cited_line_payload(
            [
                (
                    "VIEWER_DISCUSSION\t1",
                    "https://variety.com/tv/other-show-romance/",
                    "Other Show relationship becomes the talking point",
                )
            ]
        )
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=(),
            transport=FakeJsonTransport([JsonResponse(200, {}, payload)]),
            page_transport=FakeTextTransport([]),
        )

        batch = provider.collect(
            intent_from_query("romance from the last three days"),
            authorization=_authorization(
                "openai", "research.web_verify", model="gpt-5.6-luna", max_requests=1
            ),
            cancellation=CancellationToken(),
            context=context,
        )

        self.assertEqual(batch.evidence, ())
        self.assertTrue(any("conflicted" in item for item in batch.warnings))

    def test_openai_uses_one_required_search_per_candidate_when_authorized(self) -> None:
        base_context = _trusted_tvmaze_context()
        other_locator = EpisodeLocatorFactV2(
            show_or_title="Other Show",
            season_number=2,
            episode_number=3,
            episode_title="Crossed Wires",
        )
        other_episode = EvidenceCandidate(
            provider="tvmaze",
            provider_record_id="episode:3",
            source_type=EvidenceSourceType.METADATA,
            canonical_url="https://www.tvmaze.com/episodes/3/crossed-wires",
            title="Other Show - S02E03: Crossed Wires",
            author_or_channel="TVmaze",
            excerpt_type=ExcerptType.PARAPHRASE,
            excerpt="TVmaze lists Crossed Wires as Season 2 Episode 3.",
            verification=VerificationState.SECONDARY_CORROBORATED,
            claim_kind=EvidenceClaimKind.EPISODE_IDENTITY,
            supports_why_now=False,
            policy_class="tvmaze-metadata-v1",
            event_or_release_at=NOW,
            citation_verified=True,
            episode_locator=other_locator,
        )
        context = ProviderResearchContext(
            prior_evidence=(*base_context.prior_evidence, other_episode),
            trusted_official_hosts=base_context.trusted_official_hosts,
        )
        example = _openai_cited_line_payload([])
        example["id"] = "resp_example"
        example_output = example["output"]
        assert isinstance(example_output, list)
        example_action = example_output[0]["action"]
        assert isinstance(example_action, dict)
        example_action["sources"] = [
            {"url": "https://example.net/generic-streaming-roundup"},
            {
                "url": "https://variety.com/example-show-relationship",
                "title": "Example Show relationship discussion",
            }
        ]
        example_message = example_output[1]
        assert isinstance(example_message, dict)
        example_content = example_message["content"]
        assert isinstance(example_content, list)
        example_content[0]["text"] = "Current relationship coverage."
        example_content[0]["annotations"] = [
            {
                "type": "url_citation",
                "start_index": 0,
                "end_index": 29,
                "url": "https://variety.com/example-show-relationship",
                "title": "Example Show relationship discussion",
            }
        ]

        other = _openai_cited_line_payload([])
        other["id"] = "resp_other"
        other_output = other["output"]
        assert isinstance(other_output, list)
        other_output[0]["id"] = "search_other"
        other_action = other_output[0]["action"]
        assert isinstance(other_action, dict)
        other_action["sources"] = [
            {"url": "https://example.org/generic-tv-calendar"},
            {
                "url": "https://thewrap.com/other-show-romance",
                "title": "Other Show romance discussion",
            }
        ]
        other_message = other_output[1]
        assert isinstance(other_message, dict)
        other_content = other_message["content"]
        assert isinstance(other_content, list)
        other_content[0]["text"] = "Current romance coverage."
        other_content[0]["annotations"] = [
            {
                "type": "url_citation",
                "start_index": 0,
                "end_index": 25,
                "url": "https://thewrap.com/other-show-romance",
                "title": "Other Show romance discussion",
            }
        ]
        transport = FakeJsonTransport(
            [JsonResponse(200, {}, example), JsonResponse(200, {}, other)]
        )
        page_transport = FakeTextTransport(
            [
                "<title>Example Show relationship discussion</title>"
                f'<meta property="article:published_time" content="{NOW.isoformat()}">',
                "<title>Other Show romance discussion</title>"
                f'<meta property="article:published_time" content="{NOW.isoformat()}">',
            ]
        )
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=(),
            request_max_tool_calls=2,
            transport=transport,
            page_transport=page_transport,
        )

        batch = provider.collect(
            intent_from_query("romance from the last three days"),
            authorization=_authorization(
                "openai",
                "research.web_verify",
                model="gpt-5.6-luna",
                max_requests=4,
                max_tool_calls=2,
            ),
            cancellation=CancellationToken(),
            context=context,
        )

        self.assertEqual(len(transport.requests), 2)
        self.assertTrue(
            all(request["body"]["tool_choice"] == "required" for request in transport.requests)
        )
        requested_titles = {
            json.loads(request["body"]["input"])[
                "trusted_tvmaze_episode_candidate"
            ]["show_or_title"]
            for request in transport.requests
        }
        self.assertEqual(requested_titles, {"Example Show", "Other Show"})
        for request in transport.requests:
            request_body = request["body"]
            request_input = json.loads(request_body["input"])
            query = request_input["host_search_query"]
            candidate = request_input["trusted_tvmaze_episode_candidate"]
            self.assertIn(f'"{candidate["show_or_title"]}"', query)
            self.assertIn(" TV ", query)
            self.assertIn("after:", query)
            self.assertNotIn(f'season {candidate["season_number"]}', query)
            allowed_domains = request_body["tools"][0]["filters"]["allowed_domains"]
            self.assertIn("example.com", allowed_domains)
            self.assertIn("tomsguide.com", allowed_domains)
            self.assertIn("techradar.com", allowed_domains)
            self.assertIn("los40.com", allowed_domains)
            self.assertNotIn("reddit.com", allowed_domains)
        self.assertEqual(batch.usage.request_count, 4)
        self.assertEqual(batch.usage.tool_calls, 2)
        self.assertEqual(batch.usage.input_tokens, 200)
        self.assertEqual(batch.usage.output_tokens, 60)
        self.assertEqual(len(batch.evidence), 2)
        self.assertEqual(
            [request["url"] for request in page_transport.requests],
            [
                "https://variety.com/example-show-relationship",
                "https://thewrap.com/other-show-romance",
            ],
        )
        self.assertTrue(any("one required hosted search" in item for item in batch.warnings))

    def test_openai_multi_result_tv_search_is_owner_partitioned_per_title(self) -> None:
        base_context = _trusted_tvmaze_context()
        other_locator = EpisodeLocatorFactV2(
            show_or_title="Other Show",
            season_number=2,
            episode_number=3,
            episode_title="Crossed Wires",
        )
        other_episode = EvidenceCandidate(
            provider="tvmaze",
            provider_record_id="episode:3",
            source_type=EvidenceSourceType.METADATA,
            canonical_url="https://www.tvmaze.com/episodes/3/crossed-wires",
            title="Other Show - S02E03: Crossed Wires",
            author_or_channel="TVmaze",
            excerpt_type=ExcerptType.PARAPHRASE,
            excerpt="TVmaze lists Crossed Wires as Season 2 Episode 3.",
            verification=VerificationState.SECONDARY_CORROBORATED,
            claim_kind=EvidenceClaimKind.EPISODE_IDENTITY,
            supports_why_now=False,
            policy_class="tvmaze-metadata-v1",
            event_or_release_at=NOW,
            citation_verified=True,
            episode_locator=other_locator,
        )
        context = ProviderResearchContext(
            prior_evidence=(*base_context.prior_evidence, other_episode),
            trusted_official_hosts=base_context.trusted_official_hosts,
        )
        responses = []
        for index in range(4):
            payload = _openai_cited_line_payload([])
            payload["id"] = f"resp_partition_{index}"
            output = payload["output"]
            assert isinstance(output, list)
            output[0]["id"] = f"search_partition_{index}"
            responses.append(JsonResponse(200, {}, payload))
        transport = FakeJsonTransport(responses)
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=("example.com",),
            request_max_tool_calls=4,
            transport=transport,
            page_transport=FakeTextTransport([]),
        )

        batch = provider.collect(
            intent_from_query(
                "a good show for girls that'll get views on tiktok"
            ),
            authorization=_authorization(
                "openai",
                "research.web_verify",
                model="gpt-5.6-luna",
                max_requests=6,
                max_tool_calls=4,
                max_output_tokens=2_000,
            ),
            cancellation=CancellationToken(),
            context=context,
        )

        self.assertEqual(len(transport.requests), 4)
        inputs = [request["body"]["input"] for request in transport.requests]
        self.assertEqual(
            [
                isinstance(item, str)
                and item.startswith(f'"{title}" current TV shows after:')
                for item, title in zip(
                    inputs,
                    ["Example Show", "Example Show", "Other Show", "Other Show"],
                    strict=True,
                )
            ],
            [True, True, True, True],
        )
        self.assertTrue(
            all(
                request["body"].get("reasoning") == {"effort": "none"}
                for request in transport.requests
            )
        )
        future_domains = transport.requests[0]["body"]["tools"][0]["filters"]["allowed_domains"]
        independent_domains = transport.requests[1]["body"]["tools"][0]["filters"]["allowed_domains"]
        self.assertIn("tomsguide.com", future_domains)
        self.assertNotIn("variety.com", future_domains)
        self.assertIn("variety.com", independent_domains)
        self.assertNotIn("tomsguide.com", independent_domains)
        self.assertEqual(batch.usage.tool_calls, 4)
        self.assertTrue(
            any("two publisher-owner-partitioned" in warning for warning in batch.warnings)
        )

    def test_query_scoped_current_roundups_require_page_binding_but_may_use_hosted_date(self) -> None:
        """Regress r54: current generic headlines were dropped or dated stale."""

        context = _eight_seed_tvmaze_context()
        current_urls = (
            "https://www.tomsguide.com/entertainment/current-tv-roundup",
            "https://elpais.com/television/series/current-tv-column.html",
        )
        responses: list[JsonResponse] = []
        for index in range(4):
            payload = _openai_cited_line_payload([])
            payload["id"] = f"resp_roundup_date_{index}"
            output = payload["output"]
            assert isinstance(output, list)
            output[0]["id"] = f"search_roundup_date_{index}"
            if index < 2:
                action = output[0]["action"]
                assert isinstance(action, dict)
                action["sources"] = [
                    {
                        "url": current_urls[index],
                        "title": "Three television shows to watch this week",
                        "published_at": (
                            NOW - timedelta(hours=index + 1)
                        ).isoformat(),
                    }
                ]
            responses.append(JsonResponse(200, {}, payload))

        transport = FakeJsonTransport(responses)
        page_transport = FakeTextTransport(
            [
                "<title>Three television shows to watch this week</title>"
                "<body>Example Show is the current standout. The article returns "
                "to Example Show for its relationship turn.</body>",
                "<title>La televisión de esta semana</title>"
                "<body>Example Show centers the current discussion. Example Show "
                "also supplies the strongest character turn.</body>",
            ]
        )
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=("example.com",),
            request_max_tool_calls=4,
            transport=transport,
            page_transport=page_transport,
        )

        batch = provider.collect(
            intent_from_query("a good show for girls that'll get views on tiktok"),
            authorization=_authorization(
                "openai",
                "research.web_verify",
                model="gpt-5.6-luna",
                max_requests=6,
                max_tool_calls=4,
                max_output_tokens=2_000,
            ),
            cancellation=CancellationToken(),
            context=context,
        )

        self.assertEqual(
            [request["url"] for request in page_transport.requests],
            list(current_urls),
        )
        discussions = [
            item
            for item in batch.evidence
            if item.claim_kind is EvidenceClaimKind.VIEWER_DISCUSSION
        ]
        self.assertEqual(len(discussions), 2)
        self.assertEqual(
            {item.canonical_url for item in discussions},
            {canonicalize_public_url(url) for url in current_urls},
        )
        self.assertTrue(
            all(item.adapter_source_published_at is not None for item in discussions)
        )
        self.assertTrue(
            all(
                source_record_binds_tvmaze_show(
                    provider=item.provider,
                    provider_record_id=item.provider_record_id,
                    canonical_url=item.canonical_url,
                    show_or_title="Example Show",
                )
                for item in discussions
            )
        )

    def test_tv_discovery_roundups_survive_zero_selector_lines_after_public_binding(self) -> None:
        """Regress live r55: two discovery searches returned zero selectors."""

        context = _eight_seed_tvmaze_context()
        current_urls = (
            "https://www.tomsguide.com/entertainment/current-tv-roundup",
            "https://elpais.com/television/series/current-tv-column.html",
        )
        responses: list[JsonResponse] = []
        for index, current_url in enumerate(current_urls):
            payload = _openai_tv_selector_payload([])
            payload["id"] = f"resp_r55_discovery_{index}"
            output = payload["output"]
            assert isinstance(output, list)
            search = output[0]
            assert isinstance(search, dict)
            search["id"] = f"search_r55_discovery_{index}"
            action = search["action"]
            assert isinstance(action, dict)
            action["sources"] = [
                {
                    "url": current_url,
                    "title": "Three television shows to watch this week",
                    "published_at": (
                        NOW - timedelta(hours=index + 1)
                    ).isoformat(),
                }
            ]
            responses.append(JsonResponse(200, {}, payload))

        for index in range(11):
            payload = _openai_cited_line_payload([])
            payload["id"] = f"resp_r55_exact_or_retry_{index}"
            output = payload["output"]
            assert isinstance(output, list)
            search = output[0]
            assert isinstance(search, dict)
            search["id"] = f"search_r55_exact_or_retry_{index}"
            responses.append(JsonResponse(200, {}, payload))

        page_transport = FakeTextTransport(
            [
                "<title>Three television shows to watch this week</title>"
                "<body>Example Show is the current standout. The article returns "
                "to Example Show for its relationship turn.</body>",
                "<title>La televisión de esta semana</title>"
                "<body>Example Show centers the current discussion. Example Show "
                "also supplies the strongest character turn.</body>",
            ]
        )
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=("example.com",),
            request_body_max_input_tokens=120_000,
            request_max_tool_calls=13,
            transport=FakeJsonTransport(responses),
            page_transport=page_transport,
        )

        batch = provider.collect(
            intent_from_query(
                "a good show for girls that'll get views on tiktok"
            ),
            authorization=_authorization(
                "openai",
                "research.web_verify",
                model="gpt-5.6-luna",
                max_requests=40,
                max_tool_calls=13,
                max_input_tokens=180_000,
                max_output_tokens=32_000,
            ),
            cancellation=CancellationToken(),
            context=context,
        )

        self.assertEqual(len(responses), 13)
        self.assertEqual(
            [request["url"] for request in page_transport.requests],
            list(current_urls),
        )
        discussions = [
            item
            for item in batch.evidence
            if item.claim_kind is EvidenceClaimKind.VIEWER_DISCUSSION
        ]
        self.assertEqual(len(discussions), 2)
        self.assertEqual(
            {
                known_publisher_owner(urlsplit(item.canonical_url).hostname or "")
                for item in discussions
            },
            {"owner:future-plc", "owner:prisa-media"},
        )
        self.assertTrue(
            all(
                source_record_binds_tvmaze_show(
                    provider=item.provider,
                    provider_record_id=item.provider_record_id,
                    canonical_url=item.canonical_url,
                    show_or_title="Example Show",
                )
                for item in discussions
            )
        )
        self.assertTrue(
            any(
                "retained 0 citation-bound selector(s)" in warning
                and "carried 2 reviewed tool-source page hint(s)" in warning
                for warning in batch.warnings
            )
        )

    def test_live_r56_zero_discovery_exact_title_lane_recovers_current_owner_pair(self) -> None:
        """Regress live r56: zero discovery sources must not hide exact coverage."""

        context = _eight_seed_tvmaze_context()
        current_urls = (
            "https://www.tomsguide.com/entertainment/example-show-current",
            "https://elpais.com/television/series/2026/08/18/example-show-current.html",
        )
        responses: list[JsonResponse] = []
        for index in range(2):
            payload = _openai_tv_selector_payload([])
            payload["id"] = f"resp_r56_empty_discovery_{index}"
            output = payload["output"]
            assert isinstance(output, list)
            output[0]["id"] = f"search_r56_empty_discovery_{index}"
            responses.append(JsonResponse(200, {}, payload))

        for index in range(11):
            payload = _openai_cited_line_payload([])
            payload["id"] = f"resp_r56_exact_or_retry_{index}"
            output = payload["output"]
            assert isinstance(output, list)
            search = output[0]
            assert isinstance(search, dict)
            search["id"] = f"search_r56_exact_or_retry_{index}"
            if index < 2:
                action = search["action"]
                assert isinstance(action, dict)
                action["sources"] = [
                    {
                        "url": current_urls[index],
                        "title": "Three television shows to watch this week",
                    }
                ]
            responses.append(JsonResponse(200, {}, payload))

        page_transport = FakeTextTransport(
            [
                "<title>Three television shows to watch this week</title>"
                f'<meta property="article:published_time" content="{NOW.isoformat()}">'
                "<body>Example Show is the current standout. The article returns "
                "to Example Show for its relationship turn.</body>",
                "<title>La television de esta semana</title>"
                f'<meta property="article:published_time" content="{NOW.isoformat()}">'
                "<body>Example Show centers the current discussion. Example Show "
                "also supplies the strongest character turn.</body>",
            ]
        )
        transport = FakeJsonTransport(responses)
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=("example.com",),
            request_body_max_input_tokens=120_000,
            request_max_tool_calls=13,
            transport=transport,
            page_transport=page_transport,
        )

        batch = provider.collect(
            intent_from_query(
                "a good show for girls thatll get views on tiktok"
            ),
            authorization=_authorization(
                "openai",
                "research.web_verify",
                model="gpt-5.6-luna",
                max_requests=40,
                max_tool_calls=13,
                max_input_tokens=180_000,
                max_output_tokens=32_000,
            ),
            cancellation=CancellationToken(),
            context=context,
        )

        self.assertEqual(len(transport.requests), 13)
        discovery_queries = [
            json.loads(request["body"]["input"])["host_search_query"]
            for request in transport.requests[:2]
        ]
        self.assertTrue(all("after:" in query for query in discovery_queries))
        self.assertTrue(all("relationship" not in query for query in discovery_queries))
        exact_queries = [request["body"]["input"] for request in transport.requests[2:4]]
        self.assertTrue(
            all(
                isinstance(query, str)
                and query.startswith('"Example Show" current TV shows after:')
                for query in exact_queries
            )
        )
        self.assertTrue(all("season 1" not in query for query in exact_queries))
        self.assertTrue(all("female-centered" not in query for query in exact_queries))
        self.assertTrue(
            all(
                request["body"].get("reasoning") == {"effort": "none"}
                for request in transport.requests[2:12]
            )
        )
        retry_query = json.loads(transport.requests[12]["body"]["input"])[
            "host_search_query"
        ]
        self.assertTrue(retry_query.startswith('("Example Show" OR '))
        self.assertIn(" after:", retry_query)

        self.assertCountEqual(
            [request["url"] for request in page_transport.requests],
            list(current_urls),
        )
        discussions = [
            item
            for item in batch.evidence
            if item.claim_kind is EvidenceClaimKind.VIEWER_DISCUSSION
        ]
        self.assertEqual(len(discussions), 2)
        self.assertEqual(
            {
                known_publisher_owner(urlsplit(item.canonical_url).hostname or "")
                for item in discussions
            },
            {"owner:future-plc", "owner:prisa-media"},
        )
        self.assertTrue(
            any(
                "retained 0 citation-bound selector(s)" in warning
                and "carried 0 reviewed tool-source page hint(s)" in warning
                for warning in batch.warnings
            )
        )

    def test_live_r57_narrow_owner_retries_recover_furious_current_pair(self) -> None:
        """Regress r57: a broad retry missed two known current owner pages."""

        context = _live_r57_tvmaze_context()
        future_url = (
            "https://www.tomsguide.com/entertainment/hulu/"
            "3-new-hulu-shows-you-need-to-binge-watch-this-weekend-aug-14-16-2026"
        )
        prisa_url = (
            "https://elpais.com/television/series/2026-08-15/"
            "atreverse-a-ver-furious-diptico-del-dolor-y-la-ira-femeninos-en-la-era-epstein.html"
        )
        responses: list[JsonResponse] = []
        for index in range(2):
            payload = _openai_tv_selector_payload([])
            payload["id"] = f"resp_r57_empty_discovery_{index}"
            output = payload["output"]
            assert isinstance(output, list)
            output[0]["id"] = f"search_r57_empty_discovery_{index}"
            responses.append(JsonResponse(200, {}, payload))

        for index in range(10):
            payload = _openai_cited_line_payload([])
            payload["id"] = f"resp_r57_empty_exact_{index}"
            output = payload["output"]
            assert isinstance(output, list)
            output[0]["id"] = f"search_r57_empty_exact_{index}"
            responses.append(JsonResponse(200, {}, payload))

        for index, url in enumerate((future_url, prisa_url)):
            payload = _openai_cited_line_payload([])
            payload["id"] = f"resp_r57_narrow_retry_{index}"
            output = payload["output"]
            assert isinstance(output, list)
            search = output[0]
            assert isinstance(search, dict)
            search["id"] = f"search_r57_narrow_retry_{index}"
            action = search["action"]
            assert isinstance(action, dict)
            action["sources"] = [
                {
                    "url": url,
                    "title": "Current television coverage",
                }
            ]
            responses.append(JsonResponse(200, {}, payload))

        published = NOW.isoformat()
        transport = FakeJsonTransport(responses)
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=("example.com",),
            request_body_max_input_tokens=120_000,
            request_max_tool_calls=14,
            transport=transport,
            page_transport=FakeTextTransport(
                [
                    "<title>What to watch: The 3 best new shows to binge on Hulu right now</title>"
                    f'<meta property="article:published_time" content="{published}">'
                    "<body>Furious is one of this week's strongest shows. Furious centers "
                    "women's anger through Special Agent Alice Black and the consequences "
                    "around it.</body>",
                    "<title>Atrévase a ver ‘Furious’, díptico del dolor y la ira femeninos</title>"
                    f'<meta property="article:published_time" content="{published}">'
                    "<body>Furious centra la discusión actual. Furious vuelve sobre la ira "
                    "femenina y sus consecuencias.</body>",
                ]
            ),
        )

        batch = provider.collect(
            intent_from_query(
                "a good show for girls thatll get views on tiktok"
            ),
            authorization=_authorization(
                "openai",
                "research.web_verify",
                model="gpt-5.6-luna",
                max_requests=40,
                max_tool_calls=14,
                max_input_tokens=180_000,
                max_output_tokens=32_000,
            ),
            cancellation=CancellationToken(),
            context=context,
        )

        self.assertEqual(len(transport.requests), 14)
        retry_requests = transport.requests[-2:]
        retry_inputs = [request["body"]["input"] for request in retry_requests]
        self.assertTrue(
            all(
                isinstance(item, str)
                and item.startswith(
                    '"Furious" "Emmy Rossum" current TV shows after:'
                )
                and " OR " not in item
                for item in retry_inputs
            )
        )
        self.assertEqual(
            [request["body"].get("reasoning") for request in retry_requests],
            [{"effort": "none"}, {"effort": "none"}],
        )
        self.assertEqual(
            [
                request["body"]["tools"][0]["filters"]["allowed_domains"]
                for request in retry_requests
            ],
            [["tomsguide.com"], ["elpais.com", "los40.com"]],
        )
        self.assertTrue(all("girls" not in item for item in retry_inputs))
        discussions = [
            item
            for item in batch.evidence
            if item.claim_kind is EvidenceClaimKind.VIEWER_DISCUSSION
        ]
        self.assertEqual(len(discussions), 2, batch.warnings)
        self.assertEqual(
            {
                known_publisher_owner(urlsplit(item.canonical_url).hostname or "")
                for item in discussions
            },
            {"owner:future-plc", "owner:prisa-media"},
        )
        self.assertTrue(
            all(
                source_record_binds_tvmaze_show(
                    provider=item.provider,
                    provider_record_id=item.provider_record_id,
                    canonical_url=item.canonical_url,
                    show_or_title="Furious",
                )
                for item in discussions
            )
        )
        self.assertEqual(batch.usage.tool_calls, 14)
        self.assertTrue(
            any(
                "two narrow, independently owned publisher partitions"
                in warning
                and "exact-title current-coverage retry" in warning
                and "Furious" in warning
                for warning in batch.warnings
            )
        )

    def test_live_r63_failed_precision_pages_cannot_starve_verbatim_exact_pair(
        self,
    ) -> None:
        """Regress r63: 24 retry mismatches starved 104 ordinary sources."""

        context = _live_r57_tvmaze_context()
        future_url = (
            "https://www.tomsguide.com/entertainment/hulu/"
            "3-new-hulu-shows-you-need-to-binge-watch-this-weekend-aug-14-16-2026"
        )
        prisa_url = (
            "https://elpais.com/television/series/2026-08-15/"
            "atreverse-a-ver-furious-diptico-del-dolor-y-la-ira-femeninos-en-la-era-epstein.html"
        )
        responses: list[JsonResponse] = []
        published = NOW.isoformat()
        for index in range(2):
            payload = _openai_tv_selector_payload([])
            payload["id"] = f"resp_r59_empty_discovery_{index}"
            output = payload["output"]
            assert isinstance(output, list)
            output[0]["id"] = f"search_r59_empty_discovery_{index}"
            responses.append(JsonResponse(200, {}, payload))

        future_hosts = (
            "techradar.com",
            "cinemablend.com",
            "whattowatch.com",
            "gamesradar.com",
            "marieclaire.com",
            "tomsguide.com",
            "techradar.com",
            "cinemablend.com",
            "whowhatwear.com",
            "gamesradar.com",
        )
        independent_hosts = (
            "los40.com",
            "variety.com",
            "thewrap.com",
            "ew.com",
            "vulture.com",
            "vanityfair.com",
            "elle.com",
            "theguardian.com",
            "thedailybeast.com",
            "avclub.com",
            "deadline.com",
            "people.com",
        )
        for index in range(10):
            hosts = future_hosts if index % 2 == 0 else independent_hosts
            payload = _openai_cited_line_payload([])
            payload["id"] = f"resp_r59_noisy_exact_{index}"
            output = payload["output"]
            assert isinstance(output, list)
            search = output[0]
            assert isinstance(search, dict)
            search["id"] = f"search_r59_noisy_exact_{index}"
            action = search["action"]
            assert isinstance(action, dict)
            noisy_sources = [
                {
                    "url": f"https://www.{host}/television/noisy-{index}-{source_index}",
                    "title": "Generic current television coverage",
                }
                for source_index, host in enumerate(hosts)
            ]
            if index == 2:
                noisy_sources.insert(
                    0,
                    {
                        "url": future_url,
                        "title": "Current television coverage",
                        "published_at": published,
                    },
                )
            elif index == 3:
                noisy_sources.insert(
                    0,
                    {
                        "url": prisa_url,
                        "title": "Current television coverage",
                        "published_at": published,
                    },
                )
            # The last exact-title pair belongs to Paris in the live slate.
            # Current hosted dates made the old single-title allocator choose
            # Paris even though the two measurable narrow-owner pages were for
            # Furious. These opaque rows are not evidence and only reproduce
            # that stochastic allocation signal.
            if index >= 8:
                for source in noisy_sources:
                    source["published_at"] = published
            action["sources"] = noisy_sources
            responses.append(JsonResponse(200, {}, payload))

        for index in range(2):
            payload = _openai_cited_line_payload([])
            payload["id"] = f"resp_r63_noisy_precision_{index}"
            output = payload["output"]
            assert isinstance(output, list)
            search = output[0]
            assert isinstance(search, dict)
            search["id"] = f"search_r63_noisy_precision_{index}"
            action = search["action"]
            assert isinstance(action, dict)
            action["sources"] = [
                {
                    "url": (
                        f"https://www.tomsguide.com/television/precision-noise-{source_index}"
                        if index == 0
                        else f"https://elpais.com/television/precision-noise-{source_index}"
                    ),
                    "title": "Generic current television coverage",
                    "published_at": published,
                }
                for source_index in range(12)
            ]
            responses.append(JsonResponse(200, {}, payload))

        class RoutedPageTransport:
            def __init__(self) -> None:
                self.requests: list[dict[str, object]] = []

            def request_text(self, **kwargs: object) -> str:
                self.requests.append(dict(kwargs))
                url = kwargs.get("url")
                if url == future_url:
                    return (
                        "<title>What to watch: The 3 best new shows to binge on Hulu right now</title>"
                        f'<meta property="article:published_time" content="{published}">'
                        "<body>Furious is one of this week's strongest shows. Furious centers "
                        "women's anger through Special Agent Alice Black and its consequences.</body>"
                    )
                if url == prisa_url:
                    return (
                        "<title>Atrévase a ver ‘Furious’, díptico del dolor y la ira femeninos</title>"
                        f'<meta property="article:published_time" content="{published}">'
                        "<body>Furious centra la discusión actual. Furious vuelve sobre la ira "
                        "femenina y sus consecuencias.</body>"
                    )
                return (
                    "<title>Generic current television coverage</title>"
                    f'<meta property="article:published_time" content="{published}">'
                    "<body>This unrelated page contains no supplied television title.</body>"
                )

        page_transport = RoutedPageTransport()
        transport = FakeJsonTransport(responses)
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=("example.com",),
            request_body_max_input_tokens=120_000,
            request_max_tool_calls=14,
            transport=transport,
            page_transport=page_transport,
        )

        batch = provider.collect(
            intent_from_query(
                "a good show for girls thatll get views on tiktok"
            ),
            authorization=_authorization(
                "openai",
                "research.web_verify",
                model="gpt-5.6-luna",
                max_requests=40,
                max_tool_calls=14,
                max_input_tokens=130_000,
                max_output_tokens=12_000,
            ),
            cancellation=CancellationToken(),
            context=context,
        )

        fetched_urls = {str(request["url"]) for request in page_transport.requests}
        prepass_requests = transport.requests[:2]
        exact_requests = transport.requests[2:12]
        precision_requests = transport.requests[-2:]
        prepass_inputs = [request["body"]["input"] for request in prepass_requests]
        exact_inputs = [request["body"]["input"] for request in exact_requests]
        precision_inputs = [request["body"]["input"] for request in precision_requests]
        self.assertTrue(
            all(
                isinstance(item, str)
                and item.startswith(
                    '"Stuart Fails to Save the Universe" current TV shows after:'
                )
                and " OR " not in item
                and "girls" not in item
                for item in prepass_inputs
            )
        )
        self.assertTrue(
            all(
                isinstance(item, str)
                and " current TV shows after:" in item
                and "girls" not in item
                for item in exact_inputs
            )
        )
        self.assertTrue(
            all(
                isinstance(item, str) and item.startswith('"Furious" current TV shows after:')
                for item in exact_inputs[2:4]
            )
        )
        self.assertTrue(
            all(
                isinstance(item, str)
                and item.startswith(
                    '"Furious" "Emmy Rossum" current TV shows after:'
                )
                and " OR " not in item
                and "girls" not in item
                for item in precision_inputs
            )
        )
        self.assertTrue(
            all(
                request["body"].get("reasoning") == {"effort": "none"}
                for request in transport.requests
            )
        )
        self.assertIn(future_url, fetched_urls)
        self.assertIn(prisa_url, fetched_urls)
        self.assertEqual(len(page_transport.requests), 26)
        discussions = [
            item
            for item in batch.evidence
            if item.claim_kind is EvidenceClaimKind.VIEWER_DISCUSSION
        ]
        self.assertEqual(len(discussions), 2, batch.warnings)
        self.assertEqual(
            {
                known_publisher_owner(urlsplit(item.canonical_url).hostname or "")
                for item in discussions
            },
            {"owner:future-plc", "owner:prisa-media"},
        )
        self.assertTrue(
            any(
                "precision-retry validation consulted 24 hosted source URL(s)"
                in warning
                and "fetched 4, and accepted 0" in warning
                and "at most 4 were placed ahead" in warning
                for warning in batch.warnings
            ),
            batch.warnings,
        )

    def test_live_r64_r70_late_exact_hint_opens_owner_completion_within_capability(
        self,
    ) -> None:
        """Regress r64-r70: rank the late exact hint, then finish its other owner."""

        context = _live_r57_tvmaze_context()
        future_url = (
            "https://www.tomsguide.com/entertainment/hulu/"
            "3-new-hulu-shows-you-need-to-binge-watch-this-weekend-aug-14-16-2026"
        )
        prisa_url = (
            "https://elpais.com/television/series/2026-08-15/"
            "atreverse-a-ver-furious-diptico-del-dolor-y-la-ira-femeninos-en-la-era-epstein.html"
        )
        published = NOW.isoformat()
        responses: list[JsonResponse] = []

        for index in range(2):
            payload = _openai_tv_selector_payload([])
            payload["id"] = f"resp_r64_empty_prepass_{index}"
            output = payload["output"]
            assert isinstance(output, list)
            output[0]["id"] = f"search_r64_empty_prepass_{index}"
            responses.append(JsonResponse(200, {}, payload))

        rank_future = "https://www.tomsguide.com/television/furious-rank-hint"
        rank_prisa = "https://elpais.com/television/furious-rank-hint"
        for index in range(10):
            payload = _openai_cited_line_payload([])
            payload["id"] = f"resp_r64_exact_{index}"
            output = payload["output"]
            assert isinstance(output, list)
            search = output[0]
            assert isinstance(search, dict)
            search["id"] = f"search_r64_exact_{index}"
            action = search["action"]
            assert isinstance(action, dict)
            if index == 2:
                action["sources"] = [
                    {
                        "url": rank_future,
                        "title": "Current television coverage",
                        "published_at": published,
                    }
                ]
            elif index == 3:
                action["sources"] = [
                    {
                        "url": rank_prisa,
                        "title": "Current television coverage",
                        "published_at": published,
                    }
                ]
            responses.append(JsonResponse(200, {}, payload))

        future_sources = [
            {
                "url": (
                    future_url
                    if index == 11
                    else f"https://www.tomsguide.com/television/r64-future-noise-{index}"
                ),
                "title": "Current television coverage",
                "published_at": published,
            }
            for index in range(12)
        ]
        prisa_sources = [
            {
                "url": (
                    prisa_url
                    if index == 12
                    else f"https://elpais.com/television/r64-prisa-noise-{index}"
                ),
                "title": (
                    "Atrévase a ver ‘Furious’, díptico del dolor y la ira femeninos"
                    if index == 12
                    else "Generic current television coverage"
                ),
                **({} if index == 12 else {"published_at": published}),
            }
            for index in range(13)
        ]
        for index, sources in enumerate((future_sources, prisa_sources)):
            payload = _openai_cited_line_payload([])
            payload["id"] = f"resp_r64_precision_{index}"
            output = payload["output"]
            assert isinstance(output, list)
            search = output[0]
            assert isinstance(search, dict)
            search["id"] = f"search_r64_precision_{index}"
            action = search["action"]
            assert isinstance(action, dict)
            action["sources"] = sources
            responses.append(JsonResponse(200, {}, payload))

        # Live r67 reported these exact aggregate counters across its fourteen
        # hosted-search responses. The old 130k input capability failed closed
        # after the provider had already returned all searches even though the
        # fixed dollar reservation still covered the usage. Preserve those
        # measured counters while proving the reallocated capability can finish.
        measured_input = (9_945,) * 13 + (9_952,)
        measured_cached = (3_151,) * 13 + (3_157,)
        measured_output = (205,) * 13 + (207,)
        measured_reasoning = (72,) * 13 + (81,)
        for response, input_tokens, cached_tokens, output_tokens, reasoning_tokens in zip(
            responses,
            measured_input,
            measured_cached,
            measured_output,
            measured_reasoning,
            strict=True,
        ):
            payload = response.payload
            assert isinstance(payload, dict)
            payload["usage"] = {
                "input_tokens": input_tokens,
                "input_tokens_details": {"cached_tokens": cached_tokens},
                "output_tokens": output_tokens,
                "output_tokens_details": {"reasoning_tokens": reasoning_tokens},
            }

        class RoutedPageTransport:
            def __init__(self) -> None:
                self.requests: list[dict[str, object]] = []

            def request_text(self, **kwargs: object) -> str:
                self.requests.append(dict(kwargs))
                url = kwargs.get("url")
                if url == future_url:
                    return (
                        "<title>3 new Hulu shows you need to binge-watch this weekend</title>"
                        f'<meta property="article:published_time" content="{published}">'
                        "<body>Furious is one of this week's strongest shows. Emmy Rossum plays "
                        "FBI agent Alice Black, and the current Furious story centers women's "
                        "anger and its consequences.</body>"
                    )
                if url == prisa_url:
                    return (
                        "<title>Atrévase a ver ‘Furious’, díptico del dolor y la ira femeninos</title>"
                        f'<meta property="article:published_time" content="{published}">'
                        "<body>Furious centra la discusión actual. Furious vuelve sobre la ira "
                        "femenina y sus consecuencias.</body>"
                    )
                return (
                    "<title>Generic current television coverage</title>"
                    f'<meta property="article:published_time" content="{published}">'
                    "<body>This unrelated page contains no supplied television title.</body>"
                )

        page_transport = RoutedPageTransport()
        transport = FakeJsonTransport(responses)
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=("example.com",),
            request_body_max_input_tokens=120_000,
            request_max_tool_calls=14,
            transport=transport,
            page_transport=page_transport,
        )

        batch = provider.collect(
            intent_from_query(
                "a good show for girls thatll get views on tiktok"
            ),
            authorization=_authorization(
                "openai",
                "research.web_verify",
                model="gpt-5.6-luna",
                max_requests=40,
                max_tool_calls=14,
                max_input_tokens=170_000,
                max_output_tokens=5_333,
            ),
            cancellation=CancellationToken(),
            context=context,
        )

        fetched_urls = {str(request["url"]) for request in page_transport.requests}
        self.assertEqual(batch.outcome, ProviderRunOutcome.SUCCESS, batch.error)
        self.assertEqual(len(transport.requests), 14)
        self.assertEqual(
            batch.usage.request_count,
            len(transport.requests) + len(page_transport.requests),
        )
        self.assertEqual(batch.usage.tool_calls, 14)
        self.assertEqual(batch.usage.input_tokens, 139_237)
        self.assertEqual(batch.usage.cached_input_tokens, 44_120)
        self.assertEqual(batch.usage.output_tokens, 2_872)
        self.assertEqual(batch.usage.reasoning_tokens, 1_017)
        self.assertEqual(
            [request["body"]["max_output_tokens"] for request in transport.requests[:2]],
            [512, 512],
        )
        self.assertTrue(
            all(
                request["body"]["max_output_tokens"] == 1_500
                for request in transport.requests[2:]
            )
        )
        self.assertIn(future_url, fetched_urls)
        self.assertNotIn(
            "https://elpais.com/television/r64-prisa-noise-2",
            fetched_urls,
        )
        discussions = [
            item
            for item in batch.evidence
            if item.claim_kind is EvidenceClaimKind.VIEWER_DISCUSSION
        ]
        self.assertEqual(
            {item.canonical_url for item in discussions},
            {canonicalize_public_url(future_url), canonicalize_public_url(prisa_url)},
        )
        self.assertEqual(
            {
                known_publisher_owner(urlsplit(item.canonical_url).hostname or "")
                for item in discussions
            },
            {"owner:future-plc", "owner:prisa-media"},
        )
        self.assertTrue(
            any(
                "precision-retry validation consulted 25 hosted source URL(s)"
                in warning
                and "accepted 2" in warning
                and "owner-completion tranche through at most 32" in warning
                and "skipped" in warning
                and "same-owner" in warning
                for warning in batch.warnings
            ),
            batch.warnings,
        )

    def test_live_r68_response_output_exhaustion_rolls_unused_budget_forward(
        self,
    ) -> None:
        """Regress r68: request 6 needed 620 tokens while 3,823 remained."""

        context = _live_r57_tvmaze_context()
        responses: list[dict[str, object]] = []
        for index in range(14):
            payload = (
                _openai_tv_selector_payload([])
                if index < 2
                else _openai_cited_line_payload([])
            )
            payload["id"] = f"resp_r68_output_{index}"
            output = payload["output"]
            assert isinstance(output, list)
            search = output[0]
            assert isinstance(search, dict)
            search["id"] = f"search_r68_output_{index}"
            responses.append(payload)

        class MeasuredR68Transport:
            def __init__(self) -> None:
                self.requests: list[dict[str, object]] = []

            def request_json(self, **kwargs: object) -> JsonResponse:
                request = dict(kwargs)
                self.requests.append(request)
                index = len(self.requests) - 1
                body = request["body"]
                assert isinstance(body, dict)
                requested_output = body["max_output_tokens"]
                assert isinstance(requested_output, int)
                payload = responses[index]

                # The first five counters plus a 430-token incomplete sixth
                # response exactly reproduce the aggregate r68 failure:
                # 56,270 input; 26,610 cached; 1,510 output; 481 reasoning.
                if index < 5:
                    input_tokens = 9_378
                    cached_tokens = 4_435
                    output_tokens = 216
                    reasoning_tokens = 80
                elif index == 5:
                    input_tokens = 9_380
                    cached_tokens = 4_435
                    reasoning_tokens = 81
                    if requested_output < 620:
                        payload["status"] = "incomplete"
                        payload["incomplete_details"] = {
                            "reason": "max_output_tokens"
                        }
                        output_tokens = requested_output
                    else:
                        output_tokens = 620
                else:
                    input_tokens = 9_000
                    cached_tokens = 3_000
                    output_tokens = 180
                    reasoning_tokens = 50
                payload["usage"] = {
                    "input_tokens": input_tokens,
                    "input_tokens_details": {"cached_tokens": cached_tokens},
                    "output_tokens": output_tokens,
                    "output_tokens_details": {
                        "reasoning_tokens": reasoning_tokens
                    },
                }
                return JsonResponse(200, {}, payload)

        transport = MeasuredR68Transport()
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=("example.com",),
            request_body_max_input_tokens=120_000,
            request_max_tool_calls=14,
            transport=transport,
            page_transport=FakeTextTransport([]),
        )

        batch = provider.collect(
            intent_from_query(
                "a good show for girls thatll get views on tiktok"
            ),
            authorization=_authorization(
                "openai",
                "research.web_verify",
                model="gpt-5.6-luna",
                max_requests=40,
                max_tool_calls=14,
                max_input_tokens=170_000,
                max_output_tokens=5_333,
            ),
            cancellation=CancellationToken(),
            context=context,
        )

        self.assertEqual(batch.outcome, ProviderRunOutcome.SUCCESS, batch.incomplete)
        self.assertEqual(len(transport.requests), 14)
        self.assertEqual(
            transport.requests[5]["body"]["max_output_tokens"],
            1_500,
        )
        self.assertEqual(batch.usage.input_tokens, 128_270)
        self.assertEqual(batch.usage.cached_input_tokens, 50_610)
        self.assertEqual(batch.usage.output_tokens, 3_140)
        self.assertEqual(batch.usage.reasoning_tokens, 881)
        self.assertLessEqual(batch.usage.output_tokens or 0, 5_333)

    def test_staged_tv_roll_forward_never_authorizes_above_aggregate_output_cap(
        self,
    ) -> None:
        context = _live_r57_tvmaze_context()

        class FullOutputTransport:
            def __init__(self) -> None:
                self.requests: list[dict[str, object]] = []

            def request_json(self, **kwargs: object) -> JsonResponse:
                request = dict(kwargs)
                self.requests.append(request)
                index = len(self.requests) - 1
                body = request["body"]
                assert isinstance(body, dict)
                requested_output = body["max_output_tokens"]
                assert isinstance(requested_output, int)
                payload = (
                    _openai_tv_selector_payload([])
                    if index < 2
                    else _openai_cited_line_payload([])
                )
                payload["id"] = f"resp_full_output_{index}"
                output = payload["output"]
                assert isinstance(output, list)
                search = output[0]
                assert isinstance(search, dict)
                search["id"] = f"search_full_output_{index}"
                payload["usage"] = {
                    "input_tokens": 100,
                    "input_tokens_details": {"cached_tokens": 0},
                    "output_tokens": requested_output,
                    "output_tokens_details": {"reasoning_tokens": 0},
                }
                return JsonResponse(200, {}, payload)

        transport = FullOutputTransport()
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=("example.com",),
            request_body_max_input_tokens=120_000,
            request_max_tool_calls=14,
            transport=transport,
            page_transport=FakeTextTransport([]),
        )
        batch = provider.collect(
            intent_from_query(
                "a good show for girls thatll get views on tiktok"
            ),
            authorization=_authorization(
                "openai",
                "research.web_verify",
                model="gpt-5.6-luna",
                max_requests=40,
                max_tool_calls=14,
                max_input_tokens=170_000,
                max_output_tokens=5_333,
            ),
            cancellation=CancellationToken(),
            context=context,
        )

        requested = [
            request["body"]["max_output_tokens"]
            for request in transport.requests
        ]
        self.assertEqual(batch.outcome, ProviderRunOutcome.SUCCESS, batch.error)
        self.assertEqual(requested, [512, 512, 1_493, *([256] * 11)])
        self.assertEqual(sum(requested), 5_333)
        self.assertEqual(batch.usage.output_tokens, 5_333)

    def test_tv_coverage_discovery_promotes_later_evidence_rich_seed(self) -> None:
        context = _eight_seed_tvmaze_context()
        promoted_title = "Candidate Show 7"
        future_url = "https://www.tomsguide.com/entertainment/candidate-show-7-current"
        independent_url = "https://www.thewrap.com/candidate-show-7-current-review/"
        responses: list[JsonResponse] = [
            JsonResponse(
                200,
                {},
                _openai_tv_selector_payload(
                    [(promoted_title, future_url, "A current TV slate")]
                ),
            ),
            JsonResponse(
                200,
                {},
                _openai_tv_selector_payload(
                    [(promoted_title, independent_url, "A second current TV slate")]
                ),
            ),
        ]
        expected_exact_titles = [
            promoted_title,
            promoted_title,
            "Example Show",
            "Example Show",
            "Candidate Show 3",
            "Candidate Show 3",
            "Candidate Show 4",
            "Candidate Show 4",
            "Candidate Show 5",
            "Candidate Show 5",
        ]
        for index, title in enumerate(expected_exact_titles):
            payload = _openai_cited_line_payload([])
            payload["id"] = f"resp_tv_exact_{index}"
            output = payload["output"]
            assert isinstance(output, list)
            search = output[0]
            assert isinstance(search, dict)
            search["id"] = f"search_tv_exact_{index}"
            responses.append(JsonResponse(200, {}, payload))
        retry_payload = _openai_cited_line_payload([])
        retry_payload["id"] = "resp_tv_precision_retry"
        retry_output = retry_payload["output"]
        assert isinstance(retry_output, list)
        retry_output[0]["id"] = "search_tv_precision_retry"
        responses.append(JsonResponse(200, {}, retry_payload))

        transport = FakeJsonTransport(responses)
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=("example.com",),
            request_body_max_input_tokens=120_000,
            request_max_tool_calls=13,
            transport=transport,
            page_transport=FakeTextTransport(
                [
                    "<title>Candidate Show 7 current episode review</title>"
                    f'<meta property="article:published_time" content="{NOW.isoformat()}">'
                    "<body>Candidate Show 7 has a current character turn. "
                    "Candidate Show 7 gives that turn room to land.</body>",
                    "<title>Candidate Show 7 ending discussion</title>"
                    f'<meta property="article:published_time" content="{NOW.isoformat()}">'
                    "<body>Candidate Show 7 has an independent current discussion. "
                    "Candidate Show 7 is the exact reviewed title.</body>",
                ]
            ),
        )

        batch = provider.collect(
            intent_from_query("a good show for girls that'll get views on tiktok"),
            authorization=_authorization(
                "openai",
                "research.web_verify",
                model="gpt-5.6-luna",
                max_requests=42,
                max_tool_calls=13,
                max_input_tokens=180_000,
                max_output_tokens=32_000,
            ),
            cancellation=CancellationToken(),
            context=context,
        )

        self.assertEqual(len(transport.requests), 13)
        discovery_inputs = [
            json.loads(request["body"]["input"])
            for request in transport.requests[:2]
        ]
        self.assertTrue(
            all("trusted_tvmaze_show_titles" in item for item in discovery_inputs)
        )
        self.assertEqual(
            [item["search_pass"] for item in discovery_inputs],
            [
                "coverage_discovery:reviewed_future_publishers",
                "coverage_discovery:reviewed_non_future_publishers",
            ],
        )
        exact_inputs = [request["body"]["input"] for request in transport.requests[2:12]]
        self.assertTrue(
            all(
                isinstance(item, str)
                and item.startswith(f'"{title}" current TV shows after:')
                for item, title in zip(exact_inputs, expected_exact_titles, strict=True)
            )
        )
        self.assertTrue(
            all(
                request["body"].get("reasoning") == {"effort": "none"}
                for request in transport.requests[2:12]
            )
        )
        retry_input = json.loads(transport.requests[12]["body"]["input"])
        self.assertEqual(retry_input["search_pass"], "precision_current_slate_retry")
        self.assertIn(
            promoted_title,
            [
                candidate["show_or_title"]
                for candidate in retry_input["trusted_tvmaze_episode_candidates"]
            ],
        )
        self.assertNotIn("season 1", retry_input["host_search_query"])
        self.assertEqual(batch.usage.tool_calls, 13)
        discussions = [
            item
            for item in batch.evidence
            if item.claim_kind is EvidenceClaimKind.VIEWER_DISCUSSION
        ]
        self.assertEqual(len(discussions), 2)
        self.assertTrue(
            all(
                source_record_binds_tvmaze_show(
                    provider=item.provider,
                    provider_record_id=item.provider_record_id,
                    canonical_url=item.canonical_url,
                    show_or_title=promoted_title,
                )
                for item in discussions
            )
        )
        self.assertTrue(
            any(
                "TV coverage discovery searches" in warning
                and promoted_title in warning
                for warning in batch.warnings
            )
        )
        self.assertTrue(
            any(
                "less-constrained current-coverage sweep" in warning
                and promoted_title in warning
                for warning in batch.warnings
            )
        )

    def test_tv_precision_retry_targets_current_two_owner_coverage(self) -> None:
        """Regress r53: use the thirteenth tool call on measured current coverage."""

        context = _eight_seed_tvmaze_context()
        target_title = "Candidate Show 4"
        future_url = "https://www.tomsguide.com/entertainment/current-tv-roundup"
        prisa_url = "https://elpais.com/television/series/current-tv-column.html"
        responses: list[JsonResponse] = [
            JsonResponse(200, {}, _openai_tv_selector_payload([])),
            JsonResponse(200, {}, _openai_tv_selector_payload([])),
        ]
        exact_titles = [
            "Example Show",
            "Example Show",
            "Candidate Show 3",
            "Candidate Show 3",
            target_title,
            target_title,
            "Candidate Show 5",
            "Candidate Show 5",
            "Candidate Show 6",
            "Candidate Show 6",
        ]
        for index, title in enumerate(exact_titles):
            payload = _openai_cited_line_payload([])
            payload["id"] = f"resp_retry_rank_{index}"
            output = payload["output"]
            assert isinstance(output, list)
            output[0]["id"] = f"search_retry_rank_{index}"
            if title == target_title:
                action = output[0]["action"]
                assert isinstance(action, dict)
                action["sources"] = [
                    {
                        "url": future_url if index % 2 == 0 else prisa_url,
                        "title": "A current television roundup",
                        "published_at": (NOW - timedelta(hours=index)).isoformat(),
                    }
                ]
            responses.append(JsonResponse(200, {}, payload))

        retry = _openai_cited_line_payload([])
        retry["id"] = "resp_retry_selected"
        retry_output = retry["output"]
        assert isinstance(retry_output, list)
        retry_output[0]["id"] = "search_retry_selected"
        retry_action = retry_output[0]["action"]
        assert isinstance(retry_action, dict)
        retry_action["sources"] = [
            {
                "url": future_url,
                "title": f"{target_title} current review",
                "published_at": (NOW - timedelta(hours=2)).isoformat(),
            },
            {
                "url": prisa_url,
                "title": f"{target_title} current discussion",
                "published_at": (NOW - timedelta(hours=1)).isoformat(),
            },
        ]
        responses.append(JsonResponse(200, {}, retry))

        transport = FakeJsonTransport(responses)
        page_transport = FakeTextTransport([])
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=("example.com",),
            request_body_max_input_tokens=120_000,
            request_max_tool_calls=13,
            transport=transport,
            page_transport=page_transport,
        )

        batch = provider.collect(
            intent_from_query("a good show for girls that'll get views on tiktok"),
            authorization=_authorization(
                "openai",
                "research.web_verify",
                model="gpt-5.6-luna",
                max_requests=42,
                max_tool_calls=13,
                max_input_tokens=180_000,
                max_output_tokens=32_000,
            ),
            cancellation=CancellationToken(),
            context=context,
        )

        self.assertEqual(len(transport.requests), 13)
        retry_input = json.loads(transport.requests[-1]["body"]["input"])
        self.assertEqual(retry_input["search_pass"], "precision_current_slate_retry")
        self.assertIn(
            target_title,
            [
                candidate["show_or_title"]
                for candidate in retry_input["trusted_tvmaze_episode_candidates"]
            ],
        )
        self.assertEqual(page_transport.requests, [])
        discussions = [
            item
            for item in batch.evidence
            if item.claim_kind is EvidenceClaimKind.VIEWER_DISCUSSION
        ]
        self.assertEqual(
            {item.canonical_url for item in discussions},
            {canonicalize_public_url(future_url), canonicalize_public_url(prisa_url)},
        )
        self.assertEqual(
            {
                known_publisher_owner(urlsplit(item.canonical_url).hostname or "")
                for item in discussions
            },
            {"owner:future-plc", "owner:prisa-media"},
        )

    def test_tv_coverage_discovery_cannot_promote_unknown_model_title(self) -> None:
        intent = intent_from_query(
            "a good show for girls that'll get views on tiktok"
        )
        seeds = _trusted_tvmaze_episode_seeds(
            _eight_seed_tvmaze_context(), intent=intent, now=NOW
        )
        future = _openai_tv_selector_payload(
            [
                (
                    "Forged Unknown Show",
                    "https://www.tomsguide.com/entertainment/forged-unknown-show",
                    "Forged Unknown Show",
                )
            ]
        )
        independent = _openai_tv_selector_payload(
            [
                (
                    "Forged Unknown Show",
                    "https://www.thewrap.com/forged-unknown-show/",
                    "Forged Unknown Show",
                )
            ]
        )

        selected, accepted, fetch_hints = _coverage_ranked_tv_seeds(
            payloads=(future, independent),
            partition_domains=(("tomsguide.com",), ("thewrap.com",)),
            seeds=seeds,
            limit=5,
            cutoff=NOW - timedelta(days=intent.freshness_days),
            now=NOW,
        )

        self.assertEqual(accepted, 0)
        self.assertEqual(fetch_hints, ())
        self.assertEqual(selected, seeds[:5])
        self.assertNotIn(
            "Forged Unknown Show", [seed.show_or_title for seed in selected]
        )

    def test_tv_coverage_selector_accepts_cited_bullet_without_exact_protocol(self) -> None:
        intent = intent_from_query(
            "a good show for girls that'll get views on tiktok"
        )
        seeds = _trusted_tvmaze_episode_seeds(
            _eight_seed_tvmaze_context(), intent=intent, now=NOW
        )
        promoted = next(
            seed for seed in seeds if seed.show_or_title == "Candidate Show 7"
        )
        url = "https://www.tomsguide.com/entertainment/candidate-show-7-current"
        payload = _openai_tv_selector_payload(
            [(promoted.show_or_title, url, "Candidate Show 7 current coverage")]
        )
        output = payload["output"]
        assert isinstance(output, list)
        message = output[1]
        assert isinstance(message, dict)
        content = message["content"]
        assert isinstance(content, list)
        block = content[0]
        assert isinstance(block, dict)
        text = "Current coverage found:\n- **Candidate Show 7** has a timely review."
        start = text.index(promoted.show_or_title)
        block["text"] = text
        block["annotations"] = [
            {
                "type": "url_citation",
                "start_index": start,
                "end_index": start + len(promoted.show_or_title),
                "url": url,
                "title": "Candidate Show 7 current coverage",
            }
        ]

        selected, accepted, fetch_hints = _coverage_ranked_tv_seeds(
            payloads=(payload,),
            partition_domains=(("tomsguide.com",),),
            seeds=seeds,
            limit=5,
            cutoff=NOW - timedelta(days=intent.freshness_days),
            now=NOW,
        )

        self.assertEqual(selected[0], promoted)
        self.assertEqual(accepted, 1)
        self.assertEqual(fetch_hints, ((promoted, canonicalize_public_url(url)),))

    def test_candidate_search_query_is_host_generated_and_tv_specific(self) -> None:
        query = _candidate_search_query(
            _TrustedTVmazeEpisodeSeed(
                show_or_title='My "Brilliant" Career',
                season_number=1,
                episode_number=4,
                episode_title="A Chapter",
                event_or_release_at=NOW,
                characters=("Sybylla", "Harry"),
            ),
            intent=intent_from_query("romance/romcom TV from the last three days"),
            now=datetime(2026, 8, 16, tzinfo=timezone.utc),
        )

        self.assertEqual(
            query,
            '"My Brilliant Career" current TV shows after:2026-08-13',
        )

    def test_live_r63_tv_queries_keep_only_title_current_tv_and_cutoff(self) -> None:
        """Regress r63/r70 without restoring audience or character-query drift."""

        now = datetime(2026, 8, 18, tzinfo=timezone.utc)
        furious = _TrustedTVmazeEpisodeSeed(
            show_or_title="Furious",
            season_number=1,
            episode_number=6,
            episode_title="They Make a Noise Like Feathers",
            event_or_release_at=now - timedelta(hours=8),
            characters=("Special Agent Alice Black", "Catherine Grace"),
            performers=("Emmy Rossum",),
        )
        fightland = _TrustedTVmazeEpisodeSeed(
            show_or_title="Fightland",
            season_number=1,
            episode_number=3,
            episode_title="Round Three",
            event_or_release_at=now - timedelta(days=3),
            characters=("Ava", "Mia"),
        )
        intent = intent_from_query(
            "a good show for girls thatll get views on tiktok"
        )

        exact = _candidate_search_query(furious, intent=intent, now=now)
        retry = _tv_precision_retry_query(furious, intent=intent, now=now)
        slate_retry = _tv_precision_slate_retry_query(
            (furious, fightland), intent=intent, now=now
        )
        discovery = _tv_coverage_discovery_query(
            (furious, fightland), intent=intent, now=now
        )

        self.assertEqual(
            exact,
            '"Furious" current TV shows after:2026-08-04',
        )
        self.assertEqual(
            retry,
            '"Furious" "Emmy Rossum" current TV shows after:2026-08-04',
        )
        self.assertEqual(
            discovery,
            '("Furious" OR "Fightland") after:2026-08-04',
        )
        self.assertEqual(slate_retry, discovery)
        for query in (exact, retry, slate_retry, discovery):
            self.assertNotIn("female-centered", query)
            self.assertNotIn("season 1", query)
            self.assertNotIn("August 2026", query)
            self.assertNotIn("relationship", query)
            self.assertNotIn("Alice", query)
        self.assertNotIn("Emmy Rossum", exact)
        self.assertIn("Emmy Rossum", retry)

    def test_eight_allowlisted_candidate_requests_fit_production_body_cap(self) -> None:
        context = _eight_seed_tvmaze_context()
        responses: list[JsonResponse] = []
        for index in range(8):
            payload = _openai_cited_line_payload([])
            payload["id"] = f"resp_allowlist_{index}"
            output = payload["output"]
            assert isinstance(output, list)
            output[0]["id"] = f"search_allowlist_{index}"
            action = output[0]["action"]
            assert isinstance(action, dict)
            action["sources"] = []
            responses.append(JsonResponse(200, {}, payload))
        transport = FakeJsonTransport(responses)
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=(),
            request_max_tool_calls=8,
            transport=transport,
            page_transport=FakeTextTransport([]),
        )

        provider.collect(
            intent_from_query(
                "romance/romcom TV, preferably a new episode from the last three days, "
                "no K-drama, no reality TV"
            ),
            authorization=_authorization(
                "openai",
                "research.web_verify",
                model="gpt-5.6-luna",
                max_requests=40,
                max_tool_calls=8,
                max_input_tokens=180_000,
                max_output_tokens=16_000,
            ),
            cancellation=CancellationToken(),
            context=context,
        )

        conservative_units = sum(
            REQUEST_TOKEN_OVERHEAD
            + len(
                json.dumps(
                    request["body"],
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            )
            for request in transport.requests
        )
        self.assertEqual(len(transport.requests), 8)
        self.assertTrue(
            all(request["body"]["max_output_tokens"] == 2_000 for request in transport.requests)
        )
        self.assertGreater(conservative_units, 18_000)
        self.assertLessEqual(conservative_units, 60_000)

    def test_openai_no_evidence_line_recovers_current_tool_source_metadata(self) -> None:
        payload = _openai_cited_line_payload([])
        output = payload["output"]
        assert isinstance(output, list)
        action = output[0]["action"]
        assert isinstance(action, dict)
        action["sources"] = [
            {
                "url": "https://variety.com/example-show-relationship",
                "title": "Example Show Alex and Jamie relationship discussion",
                "published_at": (NOW - timedelta(hours=2)).isoformat(),
            },
            {
                "url": "https://thewrap.com/example-show-romance",
                "title": "Example Show romance becomes the talking point",
                "published_at": (NOW - timedelta(hours=1)).isoformat(),
            },
        ]
        message = output[1]
        assert isinstance(message, dict)
        content = message["content"]
        assert isinstance(content, list)
        content[0]["text"] = "M1_SOURCE_LEADS_V2\nNO_EVIDENCE"
        content[0]["annotations"] = []
        page_transport = FakeTextTransport([])
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=(),
            transport=FakeJsonTransport([JsonResponse(200, {}, payload)]),
            page_transport=page_transport,
        )

        batch = provider.collect(
            intent_from_query("Example Show Alex Jamie romance from the last three days"),
            authorization=_authorization(
                "openai", "research.web_verify", model="gpt-5.6-luna", max_requests=1
            ),
            cancellation=CancellationToken(),
            context=_trusted_tvmaze_context(),
        )

        self.assertEqual(page_transport.requests, [])
        self.assertEqual(batch.usage.request_count, 1)
        self.assertEqual(len(batch.evidence), 2)
        self.assertTrue(
            all(
                item.claim_kind is EvidenceClaimKind.VIEWER_DISCUSSION
                and item.verification is VerificationState.SECONDARY_CORROBORATED
                and item.content_binding_verified
                for item in batch.evidence
            )
        )
        self.assertTrue(any("retained 2" in item for item in batch.warnings))

    def test_openai_derives_bounded_character_scene_lead_from_exact_episode_page(self) -> None:
        """Regress the packaged Lanterns headline-only footage failure."""

        url = "https://techradar.com/streaming/example-show-episode-2-ending-explained"
        title = (
            "Example Show episode 2 ending explained: a bold dual-timeline choice"
        )
        payload = _openai_cited_line_payload([])
        output = payload["output"]
        assert isinstance(output, list)
        action = output[0]["action"]
        assert isinstance(action, dict)
        action["sources"] = [
            {
                "url": url,
                "title": title,
                "published_at": (NOW - timedelta(hours=1)).isoformat(),
            }
        ]
        message = output[1]
        assert isinstance(message, dict)
        content = message["content"]
        assert isinstance(content, list)
        content[0]["text"] = "M1_SOURCE_LEADS_V2\nNO_EVIDENCE"
        content[0]["annotations"] = []
        page_transport = FakeTextTransport(
            [
                f"<title>{title}</title>"
                f'<meta property="article:published_time" content="{NOW.isoformat()}">'
                "<body>The episode ends with a shocking moment. Alex appears dead after "
                "the final confrontation, while the second timeline changes how the scene "
                "is understood.</body>"
            ]
        )
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=(),
            transport=FakeJsonTransport([JsonResponse(200, {}, payload)]),
            page_transport=page_transport,
        )

        batch = provider.collect(
            intent_from_query("Example Show scenes from the last three days"),
            authorization=_authorization(
                "openai",
                "research.web_verify",
                model="gpt-5.6-luna",
                max_requests=6,
            ),
            cancellation=CancellationToken(),
            context=_trusted_tvmaze_context(),
        )

        self.assertEqual(batch.usage.request_count, 2)
        self.assertEqual([request["url"] for request in page_transport.requests], [url])
        self.assertEqual(
            [item.claim_kind for item in batch.evidence],
            [EvidenceClaimKind.VIEWER_DISCUSSION, EvidenceClaimKind.SCENE_CONTEXT],
        )
        scene = batch.evidence[1]
        self.assertEqual(scene.verification, VerificationState.LEAD_ONLY)
        self.assertFalse(scene.supports_why_now)
        self.assertIsNotNone(scene.scene_fact)
        assert scene.scene_fact is not None
        self.assertEqual(
            scene.scene_fact.description,
            "Season 1 Episode 2's ending around Alex's apparent death",
        )
        self.assertEqual(scene.scene_fact.characters, ["Alex"])
        self.assertEqual(scene.scene_fact.episode_locator.episode_number, 2)
        self.assertNotIn(title, scene.scene_fact.description)
        self.assertTrue(any("provisional LEAD_ONLY" in item for item in batch.warnings))

    def test_openai_freshly_revalidates_cached_episode_article_before_scene_upgrade(self) -> None:
        """Regress live r49: the useful Lanterns article arrived only from cache."""

        url = "https://techradar.com/streaming/example-show-episode-2-ending-explained"
        title = "Example Show episode 2 ending explained: a bold dual-timeline choice"
        cached_discussion = EvidenceCandidate(
            provider="openai",
            provider_record_id=tvmaze_show_source_binding("Example Show", url),
            source_type=EvidenceSourceType.ARTICLE,
            canonical_url=url,
            title=title,
            author_or_channel="TechRadar",
            excerpt_type=ExcerptType.PARAPHRASE,
            excerpt=f"Current cited-source title: {title}",
            verification=VerificationState.SECONDARY_CORROBORATED,
            claim_kind=EvidenceClaimKind.VIEWER_DISCUSSION,
            supports_why_now=True,
            policy_class="openai-web-evidence-v1",
            source_created_at=NOW - timedelta(hours=1),
            page_published_at=NOW - timedelta(hours=1),
            window_start=NOW - timedelta(days=3),
            window_end=NOW,
            citation_verified=True,
            adapter_source_title=title,
            adapter_source_published_at=NOW - timedelta(hours=1),
            content_binding_verified=True,
        )
        base_context = _trusted_tvmaze_context()
        context = ProviderResearchContext(
            prior_evidence=(*base_context.prior_evidence, cached_discussion),
            trusted_official_hosts=base_context.trusted_official_hosts,
        )
        payload = _openai_cited_line_payload([])
        output = payload["output"]
        assert isinstance(output, list)
        action = output[0]["action"]
        assert isinstance(action, dict)
        action["sources"] = []
        message = output[1]
        assert isinstance(message, dict)
        content = message["content"]
        assert isinstance(content, list)
        content[0]["text"] = "M1_SOURCE_LEADS_V2\nNO_EVIDENCE"
        content[0]["annotations"] = []
        page_transport = FakeTextTransport(
            [
                f"<title>{title}</title>"
                f'<meta property="article:published_time" content="{(NOW - timedelta(hours=1)).isoformat()}">'
                "<body>Example Show episode 2 ends across two timelines.</body>"
            ]
        )
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=(),
            transport=FakeJsonTransport([JsonResponse(200, {}, payload)]),
            page_transport=page_transport,
        )

        batch = provider.collect(
            intent_from_query("Example Show scenes from the last three days"),
            authorization=_authorization(
                "openai",
                "research.web_verify",
                model="gpt-5.6-luna",
                max_requests=2,
            ),
            cancellation=CancellationToken(),
            context=context,
        )

        self.assertEqual(batch.usage.request_count, 2)
        self.assertEqual([request["url"] for request in page_transport.requests], [url])
        self.assertEqual(
            [item.claim_kind for item in batch.evidence],
            [EvidenceClaimKind.VIEWER_DISCUSSION, EvidenceClaimKind.SCENE_CONTEXT],
        )
        self.assertEqual(
            batch.evidence[1].scene_fact.description,
            "Season 1 Episode 2's ending and dual-timeline storytelling choice",
        )
        self.assertTrue(
            any("freshly revalidated 1 reusable" in item for item in batch.warnings)
        )

    def test_openai_cached_false_discussion_cannot_reenter_without_passing_page_checks(self) -> None:
        """Regress r53: the cached r52 Fightland false positive was reused."""

        url = "https://www.tomsguide.com/entertainment/how-to-catch-a-dirtbag"
        cached_discussion = EvidenceCandidate(
            provider="openai",
            provider_record_id=tvmaze_show_source_binding("Example Show", url),
            source_type=EvidenceSourceType.ARTICLE,
            canonical_url=url,
            title="How to Catch a Dirtbag",
            author_or_channel="Tom's Guide",
            excerpt_type=ExcerptType.PARAPHRASE,
            excerpt="A previously cached discussion row.",
            verification=VerificationState.SECONDARY_CORROBORATED,
            claim_kind=EvidenceClaimKind.VIEWER_DISCUSSION,
            supports_why_now=True,
            policy_class="openai-web-evidence-v1",
            source_created_at=NOW - timedelta(hours=1),
            page_published_at=NOW - timedelta(hours=1),
            window_start=NOW - timedelta(days=3),
            window_end=NOW,
            citation_verified=True,
            adapter_source_title="How to Catch a Dirtbag",
            adapter_source_published_at=NOW - timedelta(hours=1),
            content_binding_verified=True,
        )
        base_context = _trusted_tvmaze_context()
        context = ProviderResearchContext(
            prior_evidence=(*base_context.prior_evidence, cached_discussion),
            trusted_official_hosts=base_context.trusted_official_hosts,
        )
        payload = _openai_cited_line_payload([])
        page_transport = FakeTextTransport(
            [
                "<title>How to Catch a Dirtbag</title>"
                f'<meta property="article:published_time" content="{NOW.isoformat()}">'
                "<body>An unrelated investigative series. Example Show appears "
                "once in a related-story rail.</body>"
            ]
        )
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=(),
            transport=FakeJsonTransport([JsonResponse(200, {}, payload)]),
            page_transport=page_transport,
        )

        batch = provider.collect(
            intent_from_query("Example Show from the last three days"),
            authorization=_authorization(
                "openai",
                "research.web_verify",
                model="gpt-5.6-luna",
                max_requests=2,
            ),
            cancellation=CancellationToken(),
            context=context,
        )

        self.assertEqual([request["url"] for request in page_transport.requests], [url])
        self.assertEqual(batch.evidence, ())
        self.assertFalse(
            any("freshly revalidated" in warning for warning in batch.warnings)
        )

    def test_openai_does_not_mint_scene_lead_without_exact_episode_binding(self) -> None:
        payload = _openai_cited_line_payload([])
        output = payload["output"]
        assert isinstance(output, list)
        action = output[0]["action"]
        assert isinstance(action, dict)
        action["sources"] = [
            {
                "url": "https://variety.com/example-show-review",
                "title": "Example Show review and ending discussion",
                "published_at": NOW.isoformat(),
            }
        ]
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=(),
            transport=FakeJsonTransport([JsonResponse(200, {}, payload)]),
            page_transport=FakeTextTransport([]),
        )

        batch = provider.collect(
            intent_from_query("Example Show scenes from the last three days"),
            authorization=_authorization(
                "openai", "research.web_verify", model="gpt-5.6-luna", max_requests=6
            ),
            cancellation=CancellationToken(),
            context=_trusted_tvmaze_context(),
        )

        self.assertEqual(
            [item.claim_kind for item in batch.evidence],
            [EvidenceClaimKind.VIEWER_DISCUSSION],
        )

    def test_openai_can_use_one_unambiguous_source_owned_url_date_for_discussion(self) -> None:
        payload = _openai_cited_line_payload([])
        output = payload["output"]
        assert isinstance(output, list)
        action = output[0]["action"]
        assert isinstance(action, dict)
        action["sources"] = [
            {
                "url": (
                    f"https://variety.com/{NOW.year}/{NOW.month:02d}/{NOW.day:02d}/"
                    "tv/news/example-show-romance/"
                ),
                "title": "Example Show relationship becomes the talking point",
            }
        ]
        message = output[1]
        assert isinstance(message, dict)
        content = message["content"]
        assert isinstance(content, list)
        content[0]["text"] = "M1_SOURCE_LEADS_V2\nNO_EVIDENCE"
        content[0]["annotations"] = []
        page_transport = FakeTextTransport([])
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=(),
            transport=FakeJsonTransport([JsonResponse(200, {}, payload)]),
            page_transport=page_transport,
        )

        batch = provider.collect(
            intent_from_query("Example Show romance from the last three days"),
            authorization=_authorization(
                "openai", "research.web_verify", model="gpt-5.6-luna", max_requests=1
            ),
            cancellation=CancellationToken(),
            context=_trusted_tvmaze_context(),
        )

        self.assertEqual(page_transport.requests, [])
        self.assertEqual(len(batch.evidence), 1)
        self.assertEqual(batch.evidence[0].page_published_at.date(), NOW.date())

    def test_openai_no_evidence_line_can_bind_exact_official_tool_source_page(self) -> None:
        payload = _openai_cited_line_payload([])
        output = payload["output"]
        assert isinstance(output, list)
        action = output[0]["action"]
        assert isinstance(action, dict)
        action["sources"] = [
            {
                "url": "https://example.com/example-show/turning-point",
                "title": "Example Show - Turning Point",
            }
        ]
        message = output[1]
        assert isinstance(message, dict)
        content = message["content"]
        assert isinstance(content, list)
        content[0]["text"] = "M1_SOURCE_LEADS_V2\nNO_EVIDENCE"
        content[0]["annotations"] = []
        readable_date = f"{NOW.strftime('%B')} {NOW.day}, {NOW.year}"
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=(),
            transport=FakeJsonTransport([JsonResponse(200, {}, payload)]),
            page_transport=FakeTextTransport(
                [
                    "<title>Example Show - Season 1 Episode 2 - Turning Point</title>"
                    f"<body>Available {readable_date}.</body>"
                ]
            ),
        )

        batch = provider.collect(
            intent_from_query("Example Show current episode"),
            authorization=_authorization(
                "openai", "research.web_verify", model="gpt-5.6-luna", max_requests=2
            ),
            cancellation=CancellationToken(),
            context=_trusted_tvmaze_context(),
        )

        self.assertEqual(batch.usage.request_count, 2)
        self.assertEqual(len(batch.evidence), 1)
        self.assertEqual(batch.evidence[0].claim_kind, EvidenceClaimKind.WHY_NOW)
        self.assertEqual(batch.evidence[0].episode_locator.season_number, 1)
        self.assertEqual(batch.evidence[0].episode_locator.episode_number, 2)

    def test_openai_url_only_tool_sources_are_fetched_and_bound(self) -> None:
        payload = _openai_cited_line_payload([])
        output = payload["output"]
        assert isinstance(output, list)
        action = output[0]["action"]
        assert isinstance(action, dict)
        action["sources"] = [
            {"url": "https://example.com/example-show/turning-point"},
            {"url": "https://variety.com/example-show-relationship"},
            {"url": "https://thewrap.com/example-show-romance"},
        ]
        message = output[1]
        assert isinstance(message, dict)
        content = message["content"]
        assert isinstance(content, list)
        content[0]["text"] = "M1_SOURCE_LEADS_V2\nNO_EVIDENCE"
        content[0]["annotations"] = []
        readable_date = f"{NOW.strftime('%B')} {NOW.day}, {NOW.year}"
        published = NOW.isoformat()
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=(),
            transport=FakeJsonTransport([JsonResponse(200, {}, payload)]),
            page_transport=FakeTextTransport(
                [
                    "<title>Example Show relationship discussion</title>"
                    f'<meta property="article:published_time" content="{published}">',
                    "<title>Example Show romance discussion</title>"
                    f'<meta property="article:published_time" content="{published}">',
                    "<title>Example Show - Season 1 Episode 2 - Turning Point</title>"
                    f"<body>Available {readable_date}.</body>",
                ]
            ),
        )

        batch = provider.collect(
            intent_from_query("Example Show romance from the last three days"),
            authorization=_authorization(
                "openai", "research.web_verify", model="gpt-5.6-luna", max_requests=6
            ),
            cancellation=CancellationToken(),
            context=_trusted_tvmaze_context(),
        )

        self.assertEqual(batch.usage.request_count, 4)
        self.assertEqual(len(batch.evidence), 3)
        self.assertEqual(
            [item.claim_kind for item in batch.evidence],
            [
                EvidenceClaimKind.VIEWER_DISCUSSION,
                EvidenceClaimKind.VIEWER_DISCUSSION,
                EvidenceClaimKind.WHY_NOW,
            ],
        )
        self.assertTrue(all(item.content_binding_verified for item in batch.evidence))
        self.assertFalse(any("source validation inspected" in item for item in batch.warnings))

    def test_openai_source_validation_reports_bounded_rejection_reasons(self) -> None:
        payload = _openai_cited_line_payload([])
        output = payload["output"]
        assert isinstance(output, list)
        action = output[0]["action"]
        assert isinstance(action, dict)
        action["sources"] = [
            {"url": "https://variety.com/example-show-undated"},
            {"url": "https://thewrap.com/example-show-current"},
        ]
        message = output[1]
        assert isinstance(message, dict)
        content = message["content"]
        assert isinstance(content, list)
        content[0]["text"] = "M1_SOURCE_LEADS_V2\nNO_EVIDENCE"
        content[0]["annotations"] = []
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=(),
            transport=FakeJsonTransport([JsonResponse(200, {}, payload)]),
            page_transport=FakeTextTransport(
                [
                    "<title>Example Show relationship discussion</title>",
                    "<title>A different show discussion</title>"
                    f'<meta property="article:published_time" content="{NOW.isoformat()}">',
                ]
            ),
        )

        batch = provider.collect(
            intent_from_query("Example Show romance from the last three days"),
            authorization=_authorization(
                "openai", "research.web_verify", model="gpt-5.6-luna", max_requests=3
            ),
            cancellation=CancellationToken(),
            context=_trusted_tvmaze_context(),
        )

        self.assertEqual(batch.evidence, ())
        summary = next(item for item in batch.warnings if "source validation inspected" in item)
        self.assertIn("1 discussion missing/stale date", summary)
        self.assertIn("1 discussion title mismatch", summary)

    def test_openai_preserves_hosted_source_order_inside_page_budget(self) -> None:
        payload = _openai_cited_line_payload([])
        output = payload["output"]
        assert isinstance(output, list)
        action = output[0]["action"]
        assert isinstance(action, dict)
        action["sources"] = [
            {"url": "https://z-news.example/example-show-current"},
            {"url": "https://a-news.example/other-show-current"},
        ]
        message = output[1]
        assert isinstance(message, dict)
        content = message["content"]
        assert isinstance(content, list)
        content[0]["text"] = "M1_SOURCE_LEADS_V2\nNO_EVIDENCE"
        content[0]["annotations"] = []
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=(),
            transport=FakeJsonTransport([JsonResponse(200, {}, payload)]),
            page_transport=FakeTextTransport(
                [
                    "<title>Example Show relationship discussion</title>"
                    f'<meta property="article:published_time" content="{NOW.isoformat()}">'
                ]
            ),
        )

        batch = provider.collect(
            intent_from_query("Example Show romance from the last three days"),
            authorization=_authorization(
                "openai", "research.web_verify", model="gpt-5.6-luna", max_requests=2
            ),
            cancellation=CancellationToken(),
            context=_trusted_tvmaze_context(),
        )

        self.assertEqual(len(batch.evidence), 1)
        self.assertEqual(
            batch.evidence[0].canonical_url,
            "https://z-news.example/example-show-current",
        )

    def test_openai_tool_source_fallback_omits_a_different_show(self) -> None:
        payload = _openai_cited_line_payload([])
        output = payload["output"]
        assert isinstance(output, list)
        action = output[0]["action"]
        assert isinstance(action, dict)
        action["sources"] = [
            {
                "url": "https://variety.com/other-show-romance",
                "title": "Other Show romance discussion",
                "published_at": NOW.isoformat(),
            }
        ]
        message = output[1]
        assert isinstance(message, dict)
        content = message["content"]
        assert isinstance(content, list)
        content[0]["text"] = "M1_SOURCE_LEADS_V2\nNO_EVIDENCE"
        content[0]["annotations"] = []
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=(),
            transport=FakeJsonTransport([JsonResponse(200, {}, payload)]),
            page_transport=FakeTextTransport([]),
        )

        batch = provider.collect(
            intent_from_query("Example Show romance from the last three days"),
            authorization=_authorization(
                "openai", "research.web_verify", model="gpt-5.6-luna", max_requests=1
            ),
            cancellation=CancellationToken(),
            context=_trusted_tvmaze_context(),
        )

        self.assertEqual(batch.evidence, ())

    def test_openai_citation_line_rejects_model_authored_dates(self) -> None:
        payload = _openai_cited_line_payload(
            [
                (
                    f"WHY_NOW\t1\t{NOW.isoformat()}",
                    "https://example.com/example-show/turning-point",
                    "Example Show - Turning Point",
                ),
                (
                    f"VIEWER_DISCUSSION\t1\t{NOW.isoformat()}",
                    "https://variety.com/example-show-current",
                    "Example Show relationship discussion",
                ),
                (
                    f"VIEWER_DISCUSSION\t1\t{NOW.isoformat()}",
                    "https://thewrap.com/example-show-current",
                    "Example Show romance discussion",
                ),
            ]
        )
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=(),
            transport=FakeJsonTransport([JsonResponse(200, {}, payload)]),
            page_transport=FakeTextTransport([]),
        )

        batch = provider.collect(
            intent_from_query(
                "romance/romcom TV, preferably a new episode from the last three days, "
                "no K-drama, no reality TV"
            ),
            authorization=_authorization(
                "openai", "research.web_verify", model="gpt-5.6-luna", max_requests=1
            ),
            cancellation=CancellationToken(),
            context=_trusted_tvmaze_context(),
        )

        self.assertEqual(batch.evidence, ())
        self.assertTrue(
            any("invalid cited source-lead" in warning for warning in batch.warnings)
        )

    def test_openai_citation_line_requires_one_claim_local_tool_source(self) -> None:
        payload = _openai_cited_line_payload(
            [
                (
                    "WHY_NOW\t1",
                    "https://example.com/example-show/turning-point",
                    "Example Show — Turning Point",
                ),
                (
                    "VIEWER_DISCUSSION\t1",
                    "https://variety.com/example-show-current",
                    "Example Show current discussion",
                ),
            ]
        )
        output = payload["output"]
        assert isinstance(output, list)
        action = output[0]["action"]
        assert isinstance(action, dict)
        sources = action["sources"]
        assert isinstance(sources, list)
        sources.pop()
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=(),
            transport=FakeJsonTransport([JsonResponse(200, {}, payload)]),
            page_transport=FakeTextTransport([]),
        )

        batch = provider.collect(
            intent_from_query("Example Show current episode"),
            authorization=_authorization(
                "openai", "research.web_verify", model="gpt-5.6-luna", max_requests=1
            ),
            cancellation=CancellationToken(),
            context=_trusted_tvmaze_context(),
        )

        self.assertEqual(batch.evidence, ())
        self.assertTrue(
            any("claim-local tool citation" in warning for warning in batch.warnings)
        )

    def test_openai_receives_bounded_immutable_tvmaze_episode_search_targets(self) -> None:
        transport = FakeJsonTransport(
            [JsonResponse(200, {}, _openai_payload(evidence=[], sources=[]))]
        )
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=("example.com",),
            transport=transport,
        )

        provider.collect(
            intent_from_query("romance TV from the last three days"),
            authorization=_authorization(
                "openai", "research.web_verify", model="gpt-5.6-luna"
            ),
            cancellation=CancellationToken(),
            context=_trusted_tvmaze_context(),
        )

        self.assertIn(
            "Return every individually qualifying line",
            transport.requests[0]["body"]["instructions"],
        )

        provider_input = json.loads(transport.requests[0]["body"]["input"])
        self.assertEqual(
            provider_input["trusted_tvmaze_episode_candidates"],
            [
                {
                    "candidate_number": 1,
                    "show_or_title": "Example Show",
                    "season_number": 1,
                    "episode_number": 2,
                    "episode_title": "Turning Point",
                    "event_or_release_at": NOW.astimezone(timezone.utc)
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "characters": ["Alex", "Jamie"],
                }
            ],
        )
        self.assertEqual(
            provider_input["trusted_official_hosts"], ["example.com"]
        )

    def test_openai_rejects_tv_why_now_that_alters_trusted_tvmaze_seed(self) -> None:
        url = "https://example.com/example-show/season-1/episode-9"
        altered = {
            "source_type": "PRIMARY_RELEASE",
            "canonical_url": url,
            "title": "Example Show Season 1 Episode 9",
            "excerpt_type": "PARAPHRASE",
            "excerpt": "Altered episode identity.",
            "verification": "PRIMARY_VERIFIED",
            "claim_kind": "WHY_NOW",
            "supports_why_now": True,
            "episode_locator": {
                "show_or_title": "Example Show",
                "season_number": 1,
                "episode_number": 9,
                "episode_title": "Invented Turn",
            },
            "why_now_event": {
                "event_kind": "EPISODE_RELEASE",
                "media_identity": {
                    "media_kind": "TV_EPISODE",
                    "show_or_title": "Example Show",
                    "season_number": 1,
                    "episode_number": 9,
                    "episode_title": "Invented Turn",
                },
            },
            "event_or_release_at": NOW.isoformat(),
            "confidence": 0.9,
        }
        page_transport = FakeTextTransport(
            ["<title>Example Show Season 1 Episode 9</title><body>unused</body>"]
        )
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=("example.com",),
            transport=FakeJsonTransport(
                [
                    JsonResponse(
                        200,
                        {},
                        _openai_payload(evidence=[altered], sources=[{"url": url}]),
                    )
                ]
            ),
            page_transport=page_transport,
        )

        batch = provider.collect(
            intent_from_query("romance TV from the last three days"),
            authorization=_authorization(
                "openai", "research.web_verify", model="gpt-5.6-luna"
            ),
            cancellation=CancellationToken(),
            context=_trusted_tvmaze_context(),
        )

        self.assertEqual(batch.evidence, ())
        self.assertEqual(batch.usage.request_count, 1)
        self.assertEqual(page_transport.requests, [])
        self.assertTrue(
            any("did not match a trusted TVmaze candidate" in item for item in batch.warnings)
        )

    def test_openai_page_budget_prioritizes_official_why_now_over_model_order(self) -> None:
        discussion_url = "https://variety.com/example-show-discussion"
        official_url = "https://example.com/example-show/s1e2"
        discussion = {
            "source_type": "ARTICLE",
            "canonical_url": discussion_url,
            "title": "model title",
            "excerpt_type": "PARAPHRASE",
            "excerpt": "Model discussion prose.",
            "verification": "SECONDARY_CORROBORATED",
            "claim_kind": "VIEWER_DISCUSSION",
            "supports_why_now": True,
            "confidence": 0.7,
        }
        official = {
            "source_type": "PRIMARY_RELEASE",
            "canonical_url": official_url,
            "title": "model title",
            "excerpt_type": "PARAPHRASE",
            "excerpt": "Model release prose.",
            "verification": "PRIMARY_VERIFIED",
            "claim_kind": "WHY_NOW",
            "supports_why_now": True,
            "episode_locator": {
                "show_or_title": "Example Show",
                "season_number": 1,
                "episode_number": 2,
                "episode_title": "Turning Point",
            },
            "why_now_event": {
                "event_kind": "EPISODE_RELEASE",
                "media_identity": {
                    "media_kind": "TV_EPISODE",
                    "show_or_title": "Example Show",
                    "season_number": 1,
                    "episode_number": 2,
                    "episode_title": "Turning Point",
                },
            },
            "event_or_release_at": NOW.date().isoformat(),
            "confidence": 0.9,
        }
        payload = _openai_payload(
            evidence=[discussion, official],
            sources=[{"url": discussion_url}, {"url": official_url}],
        )
        readable_date = f"{NOW.strftime('%B')} {NOW.day}, {NOW.year}"
        page_transport = FakeTextTransport(
            [
                "<title>Example Show - Season 1 Episode 2 - Turning Point</title>"
                f"<body>Available {readable_date}.</body>"
            ]
        )
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=("example.com",),
            transport=FakeJsonTransport([JsonResponse(200, {}, payload)]),
            page_transport=page_transport,
        )

        batch = provider.collect(
            intent_from_query("Example Show current episode"),
            authorization=_authorization(
                "openai", "research.web_verify", model="gpt-5.6-luna", max_requests=2
            ),
            cancellation=CancellationToken(),
        )

        self.assertEqual(batch.usage.request_count, 2)
        self.assertEqual(len(page_transport.requests), 1)
        self.assertEqual(len(batch.evidence), 1)
        self.assertEqual(batch.evidence[0].claim_kind.value, "WHY_NOW")
        self.assertTrue(any("budget was exhausted" in item for item in batch.warnings))

    def test_openai_omits_unbound_model_authored_quote_and_scene_leads(self) -> None:
        common = {
            "source_type": "ARTICLE",
            "canonical_url": "https://variety.com/example-show-recap",
            "title": "Example Show recap",
            "verification": "LEAD_ONLY",
            "supports_why_now": False,
            "confidence": 0.5,
        }
        evidence = [
            {
                **common,
                "excerpt_type": "SHORT_QUOTE",
                "excerpt": "A confession the page never contained",
                "claim_kind": "QUOTE",
                "quote_fact": {
                    "exact_text": "A confession the page never contained",
                    "speaker": "Alex",
                    "media_identity": {
                        "media_kind": "TV_EPISODE",
                        "show_or_title": "Example Show",
                        "season_number": 1,
                        "episode_number": 2,
                    },
                    "episode_locator": {
                        "show_or_title": "Example Show",
                        "season_number": 1,
                        "episode_number": 2,
                    },
                },
            },
            {
                **common,
                "excerpt_type": "PARAPHRASE",
                "excerpt": "Alex confesses on the beach.",
                "claim_kind": "SCENE_CONTEXT",
                "scene_fact": {
                    "show_or_title": "Example Show",
                    "description": "Alex confesses on the beach.",
                    "characters": ["Alex"],
                    "episode_locator": {
                        "show_or_title": "Example Show",
                        "season_number": 1,
                        "episode_number": 2,
                    },
                },
            },
        ]
        payload = _openai_payload(
            evidence=evidence,
            sources=[
                {
                    "url": common["canonical_url"],
                    "title": "Example Show recap",
                    "published_at": NOW.isoformat(),
                }
            ],
        )
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=(),
            transport=FakeJsonTransport([JsonResponse(200, {}, payload)]),
            page_transport=FakeTextTransport(
                ["<body>Example Show recap with no quoted dialogue or scene claim.</body>"]
            ),
        )
        result = provider.collect(
            intent_from_query("Example Show current discussion"),
            authorization=_authorization(
                "openai", "research.web_verify", model="gpt-5.6-luna", max_requests=2
            ),
            cancellation=CancellationToken(),
        )
        self.assertEqual(result.evidence, ())
        self.assertTrue(any("omitted" in warning for warning in result.warnings))

    def test_openai_quote_can_be_content_bound_only_on_cited_page(self) -> None:
        evidence = {
            "source_type": "PRIMARY_RELEASE",
            "canonical_url": "https://example.com/official-transcript",
            "title": "Official transcript",
            "excerpt_type": "SHORT_QUOTE",
            "excerpt": "I still choose you",
            "verification": "PRIMARY_VERIFIED",
            "claim_kind": "QUOTE",
            "supports_why_now": False,
            "quote_fact": {
                "exact_text": "I still choose you",
                "speaker": "Alex",
                "media_identity": {
                    "media_kind": "TV_EPISODE",
                    "show_or_title": "Example Show",
                    "season_number": 1,
                    "episode_number": 2,
                    "episode_title": "Turning Point",
                },
                "episode_locator": {
                    "show_or_title": "Example Show",
                    "season_number": 1,
                    "episode_number": 2,
                    "episode_title": "Turning Point",
                },
            },
            "confidence": 0.9,
        }
        payload = _openai_payload(
            evidence=[evidence],
            sources=[{"url": evidence["canonical_url"], "title": "Example Film transcript"}],
        )
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=("example.com",),
            transport=FakeJsonTransport([JsonResponse(200, {}, payload)]),
            page_transport=FakeTextTransport(
                [
                    '<html><script type="application/ld+json">'
                    + json.dumps(
                        {
                            "@type": "TVEpisode",
                            "partOfSeries": {"name": "Example Show"},
                            "partOfSeason": {"seasonNumber": 1},
                            "episodeNumber": 2,
                            "name": "Turning Point",
                        }
                    )
                    + "</script><body>Alex: I still choose you.</body></html>"
                ]
            ),
        )
        result = provider.collect(
            intent_from_query("Example Film quote"),
            authorization=_authorization(
                "openai",
                "research.web_verify",
                model="gpt-5.6-luna",
                max_requests=2,
            ),
            cancellation=CancellationToken(),
        )
        self.assertTrue(result.evidence[0].content_binding_verified)
        self.assertEqual(result.usage.request_count, 2)
        _, claims = normalize_batches(
            [result], retrieved_at=NOW, official_hosts={"example.com"}
        )
        self.assertEqual(claims[0].verification.value, "PRIMARY_VERIFIED")
        self.assertEqual(claims[0].quote_fact.episode_locator.episode_number, 2)

    def test_official_film_json_ld_can_supply_non_tv_primary(self) -> None:
        evidence = {
            "source_type": "PRIMARY_RELEASE",
            "canonical_url": "https://example.com/example-film",
            "title": "Example Film official release",
            "excerpt_type": "PARAPHRASE",
            "excerpt": "Example Film was released today.",
            "verification": "PRIMARY_VERIFIED",
            "claim_kind": "WHY_NOW",
            "supports_why_now": True,
            "why_now_event": {
                "event_kind": "FILM_RELEASE",
                "media_identity": {"media_kind": "FILM", "show_or_title": "Example Film"},
            },
            "source_created_at": "",
            "page_published_at": "not trusted model text",
            "event_or_release_at": NOW.date().isoformat(),
            "confidence": 0.9,
        }
        payload = _openai_payload(
            evidence=[evidence],
            sources=[{"url": evidence["canonical_url"], "title": "Example Film official release"}],
        )
        html = (
            '<script type="application/ld+json">'
            + json.dumps(
                {
                    "@type": "Movie",
                    "name": "Example Film",
                    "datePublished": NOW.date().isoformat(),
                }
            )
            + "</script>"
        )
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=("example.com",),
            transport=FakeJsonTransport([JsonResponse(200, {}, payload)]),
            page_transport=FakeTextTransport([html]),
        )
        batch = provider.collect(
            intent_from_query("Example Film current release"),
            authorization=_authorization(
                "openai", "research.web_verify", model="gpt-5.6-luna", max_requests=2
            ),
            cancellation=CancellationToken(),
        )
        _, claims = normalize_batches(
            [batch], retrieved_at=NOW, official_hosts={"example.com"}
        )
        self.assertEqual(claims[0].verification.value, "PRIMARY_VERIFIED")
        self.assertEqual(
            claims[0].text,
            f"Official page identifies Example Film with a film release dated {NOW.date().isoformat()}.",
        )
        self.assertNotIn("released today", claims[0].text.casefold())

    def test_film_search_is_host_staged_across_official_and_owner_partitions(self) -> None:
        official_url = "https://example.com/example-film"
        penske_url = "https://variety.com/2026/film/reviews/example-film-review"
        independent_url = "https://www.thewrap.com/example-film-review"
        official = {
            "source_type": "PRIMARY_RELEASE",
            "canonical_url": official_url,
            "title": "Example Film official release",
            "excerpt_type": "PARAPHRASE",
            "excerpt": "Example Film has a current official release.",
            "verification": "PRIMARY_VERIFIED",
            "claim_kind": "WHY_NOW",
            "supports_why_now": True,
            "why_now_event": {
                "event_kind": "FILM_RELEASE",
                "media_identity": {
                    "media_kind": "FILM",
                    "show_or_title": "Example Film",
                },
            },
            "event_or_release_at": NOW.isoformat(),
            "confidence": 0.9,
        }
        discovery = _openai_payload(
            evidence=[official], sources=[{"url": official_url}]
        )
        discovery["id"] = "resp_film_discovery"
        discussion_payloads = _film_partition_payloads(
            {
                "owner:penske-media": penske_url,
                "owner:thewrap": independent_url,
            },
            id_prefix="resp_film_partition",
        )
        transport = FakeJsonTransport(
            [
                JsonResponse(200, {}, discovery),
                *(JsonResponse(200, {}, payload) for payload in discussion_payloads),
            ]
        )
        published = NOW.isoformat()
        page_transport = FakeTextTransport(
            [
                '<script type="application/ld+json">'
                + json.dumps(
                    {
                        "@type": "Movie",
                        "name": "Example Film",
                        "datePublished": NOW.date().isoformat(),
                    }
                )
                + "</script>",
                "<title>Example Film review and relationship discussion</title>"
                f'<meta property="article:published_time" content="{published}">',
                "<title>Example Film review: its emotional ending</title>"
                f'<meta property="article:published_time" content="{published}">',
            ]
        )
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=("example.com",),
            request_body_max_input_tokens=120_000,
            request_max_tool_calls=13,
            transport=transport,
            page_transport=page_transport,
        )

        batch = provider.collect(
            intent_from_query("new movie or trailer"),
            authorization=_authorization(
                "openai",
                "research.web_verify",
                model="gpt-5.6-luna",
                max_requests=20,
                max_tool_calls=13,
                max_input_tokens=180_000,
                max_output_tokens=12_000,
            ),
            cancellation=CancellationToken(),
        )

        self.assertIsNone(batch.error, batch.error)
        partitions = _film_discussion_plan()
        self.assertEqual(len(transport.requests), 1 + len(partitions))
        self.assertTrue(
            all(request["body"]["tool_choice"] == "required" for request in transport.requests)
        )
        discovery_domains = transport.requests[0]["body"]["tools"][0]["filters"][
            "allowed_domains"
        ]
        self.assertEqual(discovery_domains, ["example.com"])
        for request, (owner, domains) in zip(
            transport.requests[1:], partitions, strict=True
        ):
            request_domains = request["body"]["tools"][0]["filters"][
                "allowed_domains"
            ]
            self.assertEqual(request_domains, list(domains))
            self.assertTrue(request_domains)
            self.assertTrue(
                all(known_publisher_owner(domain) == owner for domain in request_domains)
            )
            followup_input = json.loads(request["body"]["input"])
            self.assertEqual(followup_input["film_title_search_lead"], "Example Film")
            self.assertIn('"Example Film"', followup_input["host_search_query"])
            self.assertEqual(followup_input["publisher_partition"], owner)
        self.assertEqual(batch.usage.request_count, 1 + len(partitions) + 3)
        self.assertEqual(batch.usage.tool_calls, 1 + len(partitions))
        self.assertEqual(len(batch.evidence), 3)
        self.assertEqual(
            [item.claim_kind for item in batch.evidence],
            [
                EvidenceClaimKind.WHY_NOW,
                EvidenceClaimKind.VIEWER_DISCUSSION,
                EvidenceClaimKind.VIEWER_DISCUSSION,
            ],
        )
        owners = {
            known_publisher_owner(urlsplit(item.canonical_url).hostname or "")
            for item in batch.evidence[1:]
        }
        self.assertEqual(owners, {"owner:penske-media", "owner:thewrap"})

    def test_film_owner_partitions_recover_live_camp_rock_3_discussions(self) -> None:
        """Regress the packaged r38 broad-film discussion-coverage failure."""

        official_url = (
            "https://press.disneyplus.com/news/next-on-disney-plus-august-2026"
        )
        future_url = (
            "https://www.tomsguide.com/entertainment/disney-plus/just-watched-"
            "camp-rock-3-stream-these-3-disney-channel-classics-next-on-disney-and-hulu"
        )
        prisa_url = (
            "https://los40.com/2026/08/14/critica-de-camp-rock-3-una-carta-de-"
            "amor-al-legado-de-demi-lovato-y-los-jonas-brothers-que-rescata-la-"
            "esencia-del-campamento-mas-famoso-de-disney/"
        )
        released_at = NOW - timedelta(days=2)
        official = {
            "source_type": "PRIMARY_RELEASE",
            "canonical_url": official_url,
            "title": "Next on Disney+ and Hulu: August 2026",
            "excerpt_type": "PARAPHRASE",
            "excerpt": "Camp Rock 3 has a current official release.",
            "verification": "PRIMARY_VERIFIED",
            "claim_kind": "WHY_NOW",
            "supports_why_now": True,
            "why_now_event": {
                "event_kind": "FILM_RELEASE",
                "media_identity": {
                    "media_kind": "FILM",
                    "show_or_title": "Camp Rock 3",
                },
            },
            "event_or_release_at": released_at.isoformat(),
            "confidence": 0.9,
        }
        discovery = _openai_payload(
            evidence=[official], sources=[{"url": official_url}]
        )
        discovery["id"] = "resp_camp_rock_official"
        discussion_payloads = _film_partition_payloads(
            {
                "owner:future-plc": future_url,
                "owner:prisa-media": prisa_url,
            },
            id_prefix="resp_camp_rock_partition",
        )
        partitions = _film_discussion_plan()
        penske_index = next(
            index
            for index, (owner, _) in enumerate(partitions)
            if owner == "owner:penske-media"
        )
        penske_decoys = [
            "https://deadline.com/2026/08/not-camp-rock-"
            + ("x" * 170)
            + str(index)
            for index in range(4)
        ]
        penske_payload = _openai_payload(
            evidence=[], sources=[{"url": url} for url in penske_decoys]
        )
        penske_payload["id"] = "resp_camp_rock_partition_penske_decoys"
        discussion_payloads[penske_index] = penske_payload
        transport = FakeJsonTransport(
            [
                JsonResponse(200, {}, discovery),
                *(JsonResponse(200, {}, payload) for payload in discussion_payloads),
            ]
        )
        published = NOW.isoformat()
        page_transport = FakeTextTransport(
            [
                '<script type="application/ld+json">'
                + json.dumps(
                    {
                        "@type": "Movie",
                        "name": "Camp Rock 3",
                        "datePublished": released_at.date().isoformat(),
                    }
                )
                + "</script>",
                "<title>Just watched Camp Rock 3? Stream these Disney classics next</title>"
                f'<meta property="article:published_time" content="{published}">',
                *(
                    "<title>Different Film review and streaming guide</title>"
                    f'<meta property="article:published_time" '
                    f'content="{(NOW - timedelta(days=30)).isoformat()}">' 
                    for _ in penske_decoys
                ),
                "<title>Crítica de Camp Rock 3: una carta de amor a su legado</title>"
                f'<meta property="article:published_time" content="{published}">',
            ]
        )
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=("disneyplus.com",),
            request_body_max_input_tokens=120_000,
            request_max_tool_calls=13,
            transport=transport,
            page_transport=page_transport,
        )

        batch = provider.collect(
            intent_from_query("new movie or trailer"),
            authorization=_authorization(
                "openai",
                "research.web_verify",
                model="gpt-5.6-luna",
                max_requests=20,
                max_tool_calls=13,
                max_input_tokens=180_000,
                max_output_tokens=12_000,
            ),
            cancellation=CancellationToken(),
        )

        self.assertIsNone(batch.error, batch.error)
        self.assertEqual(len(transport.requests), 1 + len(partitions))
        self.assertEqual(len(page_transport.requests), 7)
        self.assertEqual(batch.usage.tool_calls, 1 + len(partitions))
        self.assertEqual(len(batch.evidence), 3)
        self.assertEqual(batch.evidence[0].canonical_url, official_url)
        self.assertEqual(
            {
                known_publisher_owner(urlsplit(item.canonical_url).hostname or "")
                for item in batch.evidence[1:]
            },
            {"owner:future-plc", "owner:prisa-media"},
        )
        self.assertTrue(
            any("stripped public host/path checks" in item for item in batch.warnings)
        )
        self.assertTrue(all(len(item) <= 500 for item in batch.warnings))

    def test_film_precision_retries_recover_after_all_owner_first_passes_fail(
        self,
    ) -> None:
        """Regress packaged r41 job 21fafa6e's retrieval allocation failure."""

        official_url = (
            "https://press.disneyplus.com/news/"
            "camp-rock-3-official-trailer-turns-up-the-music"
        )
        stale_future_url = (
            "https://www.tomsguide.com/entertainment/hulu/"
            "new-on-hulu-and-disney-in-august-2026"
        )
        future_url = (
            "https://www.tomsguide.com/entertainment/disney-plus/just-watched-"
            "camp-rock-3-stream-these-3-disney-channel-classics-next-on-disney-and-hulu"
        )
        prisa_url = (
            "https://los40.com/2026/08/14/critica-de-camp-rock-3-una-carta-de-"
            "amor-al-legado-de-demi-lovato-y-los-jonas-brothers/"
        )
        released_at = NOW - timedelta(days=2)
        official = {
            "source_type": "PRIMARY_RELEASE",
            "canonical_url": official_url,
            "title": "Official Trailer For Camp Rock 3 Turns Up The Music",
            "excerpt_type": "PARAPHRASE",
            "excerpt": "Camp Rock 3 has a current official release.",
            "verification": "PRIMARY_VERIFIED",
            "claim_kind": "WHY_NOW",
            "supports_why_now": True,
            "why_now_event": {
                "event_kind": "FILM_RELEASE",
                "media_identity": {
                    "media_kind": "FILM",
                    "show_or_title": "Camp Rock 3",
                },
            },
            "event_or_release_at": released_at.isoformat(),
            "confidence": 0.9,
        }
        discovery = _openai_payload(
            evidence=[official], sources=[{"url": official_url}]
        )
        discovery["id"] = "resp_r41_retry_official"
        base_count = len(_staged_film_discussion_partitions())
        discussion_payloads: list[dict[str, object]] = []
        for index, (owner, _) in enumerate(_film_discussion_plan()):
            source: str | None = None
            if index == 0:
                source = stale_future_url
            elif index == base_count and owner == "owner:future-plc":
                source = future_url
            elif index == base_count + 1 and owner == "owner:prisa-media":
                source = prisa_url
            payload = _openai_payload(
                evidence=[], sources=[] if source is None else [{"url": source}]
            )
            payload["id"] = f"resp_r41_retry_partition_{index}"
            discussion_payloads.append(payload)
        transport = FakeJsonTransport(
            [
                JsonResponse(200, {}, discovery),
                *(
                    JsonResponse(200, {}, payload)
                    for payload in discussion_payloads
                ),
            ]
        )
        published = NOW.isoformat()
        page_transport = FakeTextTransport(
            [
                '<script type="application/ld+json">'
                + json.dumps(
                    {
                        "@type": "Movie",
                        "name": "Camp Rock 3",
                        "datePublished": released_at.date().isoformat(),
                    }
                )
                + "</script>",
                "<title>Camp Rock 3 joins Hulu and Disney in August</title>"
                f'<meta property="article:published_time" content="'
                f'{(NOW - timedelta(days=30)).isoformat()}">',
                "<title>Just watched Camp Rock 3? Stream these classics next</title>"
                f'<meta property="article:published_time" content="{published}">',
                "<title>Crítica de Camp Rock 3: una carta de amor a su legado</title>"
                f'<meta property="article:published_time" content="{published}">',
            ]
        )
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=("disneyplus.com",),
            request_body_max_input_tokens=120_000,
            request_max_tool_calls=13,
            transport=transport,
            page_transport=page_transport,
        )

        batch = provider.collect(
            intent_from_query("new movie or trailer"),
            authorization=_authorization(
                "openai",
                "research.web_verify",
                model="gpt-5.6-luna",
                max_requests=20,
                max_tool_calls=13,
                max_input_tokens=180_000,
                max_output_tokens=12_000,
            ),
            cancellation=CancellationToken(),
        )

        plan = _film_discussion_plan()
        self.assertIsNone(batch.error, batch.error)
        self.assertEqual(len(transport.requests), 1 + len(plan))
        self.assertEqual(len(page_transport.requests), 4)
        self.assertEqual(batch.usage.tool_calls, 1 + len(plan))
        self.assertEqual(len(batch.evidence), 3)
        self.assertEqual(
            {
                known_publisher_owner(urlsplit(item.canonical_url).hostname or "")
                for item in batch.evidence[1:]
            },
            {"owner:future-plc", "owner:prisa-media"},
        )
        first_retry = transport.requests[1 + base_count]["body"]
        retry_input = json.loads(first_retry["input"])
        self.assertEqual(retry_input["host_search_query"], '"Camp Rock 3"')
        self.assertEqual(
            retry_input["search_pass"], "precision_exact_title_retry"
        )
        self.assertEqual(
            first_retry["tools"][0]["filters"]["allowed_domains"],
            ["tomsguide.com"],
        )
        self.assertTrue(any("stale date" in warning for warning in batch.warnings))

    def test_film_official_discovery_retries_before_title_scoped_searches(
        self,
    ) -> None:
        """Regress packaged r42 job c9f9e8b4's empty first discovery."""

        official_url = "https://example.com/news/example-film-release"
        future_url = "https://www.cinemablend.com/movies/example-film-review"
        prisa_url = "https://los40.com/2026/08/example-film-critica/"
        released_at = NOW - timedelta(days=1)
        first_empty = _openai_payload(evidence=[], sources=[])
        first_empty["id"] = "resp_official_retry_empty"
        official = {
            "source_type": "PRIMARY_RELEASE",
            "canonical_url": official_url,
            "title": "Example Film official release",
            "excerpt_type": "PARAPHRASE",
            "excerpt": "Example Film has a current official release.",
            "verification": "PRIMARY_VERIFIED",
            "claim_kind": "WHY_NOW",
            "supports_why_now": True,
            "why_now_event": {
                "event_kind": "FILM_RELEASE",
                "media_identity": {
                    "media_kind": "FILM",
                    "show_or_title": "Example Film",
                },
            },
            "event_or_release_at": released_at.isoformat(),
            "confidence": 0.9,
        }
        second_discovery = _openai_payload(
            evidence=[official], sources=[{"url": official_url}]
        )
        second_discovery["id"] = "resp_official_retry_success"
        # Two official attempts leave eleven of the thirteen hosted-tool
        # slots for discussion search.
        discussion_payloads = _film_partition_payloads(
            {
                "owner:future-plc": future_url,
                "owner:prisa-media": prisa_url,
            },
            id_prefix="resp_official_retry_partition",
        )[:11]
        transport = FakeJsonTransport(
            [
                JsonResponse(200, {}, first_empty),
                JsonResponse(200, {}, second_discovery),
                *(
                    JsonResponse(200, {}, payload)
                    for payload in discussion_payloads
                ),
            ]
        )
        published = NOW.isoformat()
        page_transport = FakeTextTransport(
            [
                '<script type="application/ld+json">'
                + json.dumps(
                    {
                        "@type": "Movie",
                        "name": "Example Film",
                        "datePublished": released_at.date().isoformat(),
                    }
                )
                + "</script>",
                "<title>Example Film review and emotional ending</title>"
                f'<meta property="article:published_time" content="{published}">',
                "<title>Crítica de Example Film y sus personajes</title>"
                f'<meta property="article:published_time" content="{published}">',
            ]
        )
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=("example.com",),
            request_body_max_input_tokens=120_000,
            request_max_tool_calls=13,
            transport=transport,
            page_transport=page_transport,
        )

        batch = provider.collect(
            intent_from_query("new movie or trailer"),
            authorization=_authorization(
                "openai",
                "research.web_verify",
                model="gpt-5.6-luna",
                max_requests=20,
                max_tool_calls=13,
                max_input_tokens=180_000,
                max_output_tokens=12_000,
            ),
            cancellation=CancellationToken(),
        )

        self.assertIsNone(batch.error, batch.error)
        self.assertEqual(len(transport.requests), 13)
        self.assertEqual(len(page_transport.requests), 3)
        self.assertEqual(batch.usage.tool_calls, 13)
        self.assertEqual(batch.usage.request_count, 16)
        self.assertEqual(len(batch.evidence), 3)
        first_input = json.loads(transport.requests[0]["body"]["input"])
        second_input = json.loads(transport.requests[1]["body"]["input"])
        self.assertEqual(first_input["official_search_pass"], 1)
        self.assertEqual(second_input["official_search_pass"], 2)
        self.assertNotEqual(
            first_input["host_search_query"], second_input["host_search_query"]
        )
        self.assertEqual(transport.requests[0]["body"]["max_output_tokens"], 1_500)
        self.assertEqual(transport.requests[1]["body"]["max_output_tokens"], 1_500)
        self.assertTrue(
            all(
                request["body"]["max_output_tokens"] == 818
                for request in transport.requests[2:]
            )
        )
        self.assertTrue(
            any("discovery pass 1" in warning for warning in batch.warnings)
        )

    def test_film_stage_recovers_dated_official_slate_and_indirect_headline(self) -> None:
        """Regress the packaged r36 `new movie or trailer` failure.

        The hosted discovery selected a generic Netflix watch page while its
        source list also contained a dated annual slate.  A current independent
        review named the exact film repeatedly in its public body but not in
        the headline.  Both are source-owned bindings; neither relies on model
        prose.
        """

        watch_url = "https://www.netflix.com/title/81914143"
        slate_url = "https://www.netflix.com/tudum/articles/new-movies-on-netflix-2026"
        future_url = (
            "https://www.cinemablend.com/streaming-news/"
            "last-house-reviews-netflix-greta-lee"
        )
        independent_url = (
            "https://www.thedailybeast.com/obsessed/"
            "the-last-house-netflixs-terrifying-new-thriller-traps-you-inside-forever/"
        )
        generic_decoys = [
            f"https://www.netflix.com/title/0000000{index}" for index in range(6)
        ]
        released_at = NOW - timedelta(days=8)
        official = {
            "source_type": "PRIMARY_RELEASE",
            "canonical_url": watch_url,
            "title": "Watch The Last House | Netflix Official Site",
            "excerpt_type": "PARAPHRASE",
            "excerpt": "The Last House has a current official release.",
            "verification": "PRIMARY_VERIFIED",
            "claim_kind": "WHY_NOW",
            "supports_why_now": True,
            "why_now_event": {
                "event_kind": "FILM_RELEASE",
                "media_identity": {
                    "media_kind": "FILM",
                    "show_or_title": "The Last House",
                },
            },
            "event_or_release_at": released_at.isoformat(),
            "confidence": 0.9,
        }
        discovery = _openai_payload(
            evidence=[official],
            sources=[
                {"url": watch_url},
                *({"url": url} for url in generic_decoys),
                {"url": slate_url},
            ],
        )
        discovery["id"] = "resp_live_failure_discovery"
        discussion_payloads = _film_partition_payloads(
            {
                "owner:future-plc": future_url,
                "owner:iac": independent_url,
            },
            id_prefix="resp_live_failure_partition",
        )
        transport = FakeJsonTransport(
            [
                JsonResponse(200, {}, discovery),
                *(JsonResponse(200, {}, payload) for payload in discussion_payloads),
            ]
        )
        month_day = f"{released_at.strftime('%B')} {released_at.day}"
        page_transport = FakeTextTransport(
            [
                "<title>Watch The Last House | Netflix Official Site</title>"
                '<meta property="article:published_time" content="2026-07-24T13:00:00Z">',
                "<title>New Movies on Netflix: The Ultimate Guide to What's Coming in "
                f"{released_at.year}</title><body>{month_day} The Last House is a new movie "
                "coming to Netflix.</body>",
                "<title>As The Last House Hits Netflix, Critics Weigh In On The "
                "Bewildering Sci-Fi Thriller</title>"
                f'<meta property="article:published_time" content="{NOW.isoformat()}">',
                "<title>Netflix's Terrifying New Thriller Traps You Inside Forever</title>"
                f'<meta property="article:published_time" content="{NOW.isoformat()}">'
                "<body>The Last House begins as a tense family drama. The Last House "
                "turns that emotional pressure into science-fiction horror.</body>",
            ]
        )
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=("netflix.com",),
            request_body_max_input_tokens=120_000,
            request_max_tool_calls=13,
            transport=transport,
            page_transport=page_transport,
        )

        batch = provider.collect(
            intent_from_query("new movie or trailer"),
            authorization=_authorization(
                "openai",
                "research.web_verify",
                model="gpt-5.6-luna",
                max_requests=20,
                max_tool_calls=13,
                max_input_tokens=180_000,
                max_output_tokens=12_000,
            ),
            cancellation=CancellationToken(),
        )

        partitions = _film_discussion_plan()
        self.assertEqual(len(transport.requests), 1 + len(partitions))
        self.assertEqual(len(page_transport.requests), 4)
        self.assertEqual(page_transport.requests[0]["url"], watch_url)
        self.assertEqual(page_transport.requests[1]["url"], slate_url)
        self.assertEqual(batch.usage.request_count, 1 + len(partitions) + 4)
        self.assertEqual(batch.usage.tool_calls, 1 + len(partitions))
        self.assertEqual(len(batch.evidence), 3)
        self.assertEqual(batch.evidence[0].canonical_url, slate_url)
        self.assertEqual(
            [item.claim_kind for item in batch.evidence],
            [
                EvidenceClaimKind.WHY_NOW,
                EvidenceClaimKind.VIEWER_DISCUSSION,
                EvidenceClaimKind.VIEWER_DISCUSSION,
            ],
        )
        self.assertEqual(
            {
                known_publisher_owner(urlsplit(item.canonical_url).hostname or "")
                for item in batch.evidence[1:]
            },
            {"owner:future-plc", "owner:iac"},
        )
        self.assertTrue(
            any(
                "1 official title/date mismatch" in warning
                for warning in batch.warnings
            )
        )
        sources, claims = normalize_batches(
            [batch], retrieved_at=NOW, official_hosts={"netflix.com"}
        )
        daily_source = next(
            source
            for source in sources
            if str(source.canonical_url) == independent_url
        )
        self.assertTrue(
            source_record_binds_media_title(
                provider=daily_source.provider,
                provider_record_id=daily_source.provider_record_id,
                canonical_url=str(daily_source.canonical_url),
                show_or_title="The Last House",
            )
        )
        primary_and_daily = [
            source
            for source in sources
            if str(source.canonical_url) in {slate_url, independent_url}
        ]
        selected_source_ids = {source.source_id for source in primary_and_daily}
        self.assertTrue(
            _could_support_recommendation(
                primary_and_daily,
                [claim for claim in claims if claim.source_id in selected_source_ids],
                NOW + timedelta(seconds=1),
                intent_from_query("new movie or trailer"),
            )
        )

    def test_film_stage_accepts_title_article_month_day_with_source_owned_year(self) -> None:
        """Regress the r37 six-page official title/date rejection.

        A title-specific official article owns the exact title, its metadata
        owns the event year, and its nearby prose owns the release month/day.
        The event year need not be redundantly printed beside the month/day.
        """

        official_url = "https://www.netflix.com/tudum/articles/the-last-house-release-date"
        future_url = "https://www.cinemablend.com/movies/the-last-house-review"
        independent_url = "https://www.thewrap.com/the-last-house-review"
        released_at = NOW - timedelta(days=8)
        official = {
            "source_type": "PRIMARY_RELEASE",
            "canonical_url": official_url,
            "title": "The Last House Release Date, Cast, Plot and Photos",
            "excerpt_type": "PARAPHRASE",
            "excerpt": "The Last House has a current official release.",
            "verification": "PRIMARY_VERIFIED",
            "claim_kind": "WHY_NOW",
            "supports_why_now": True,
            "why_now_event": {
                "event_kind": "FILM_RELEASE",
                "media_identity": {
                    "media_kind": "FILM",
                    "show_or_title": "The Last House",
                },
            },
            "event_or_release_at": released_at.isoformat(),
            "confidence": 0.9,
        }
        discovery = _openai_payload(
            evidence=[official], sources=[{"url": official_url}]
        )
        discussion_payloads = _film_partition_payloads(
            {
                "owner:future-plc": future_url,
                "owner:thewrap": independent_url,
            },
            id_prefix="resp_title_article_partition",
        )
        transport = FakeJsonTransport(
            [
                JsonResponse(200, {}, discovery),
                *(JsonResponse(200, {}, payload) for payload in discussion_payloads),
            ]
        )
        month_day = f"{released_at.strftime('%B')} {released_at.day}"
        article_published = released_at - timedelta(days=45)
        page_transport = FakeTextTransport(
            [
                "<title>The Last House Release Date, Cast, Plot and Photos</title>"
                f'<meta property="article:published_time" content="{article_published.isoformat()}">'
                f"<body>The Last House is coming {month_day} and will be streaming only here.</body>",
                "<title>The Last House review: a claustrophobic family thriller</title>"
                f'<meta property="article:published_time" content="{NOW.isoformat()}">',
                "<title>The Last House review: an emotional pressure cooker</title>"
                f'<meta property="article:published_time" content="{NOW.isoformat()}">',
            ]
        )
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=("netflix.com",),
            request_body_max_input_tokens=120_000,
            request_max_tool_calls=13,
            transport=transport,
            page_transport=page_transport,
        )

        batch = provider.collect(
            intent_from_query("new movie or trailer"),
            authorization=_authorization(
                "openai",
                "research.web_verify",
                model="gpt-5.6-luna",
                max_requests=20,
                max_tool_calls=13,
                max_input_tokens=180_000,
                max_output_tokens=12_000,
            ),
            cancellation=CancellationToken(),
        )

        partitions = _film_discussion_plan()
        self.assertEqual(len(transport.requests), 1 + len(partitions))
        self.assertEqual(len(page_transport.requests), 3)
        self.assertEqual(batch.usage.request_count, 1 + len(partitions) + 3)
        self.assertEqual(len(batch.evidence), 3)
        self.assertEqual(batch.evidence[0].canonical_url, official_url)
        self.assertEqual(
            batch.evidence[0].verification,
            VerificationState.PRIMARY_VERIFIED,
        )

    def test_film_title_article_does_not_borrow_model_authored_year(self) -> None:
        official_url = "https://example.com/news/example-film-release-date"
        official = {
            "source_type": "PRIMARY_RELEASE",
            "canonical_url": official_url,
            "title": "Example Film release date",
            "excerpt_type": "PARAPHRASE",
            "excerpt": "Example Film has a current official release.",
            "verification": "PRIMARY_VERIFIED",
            "claim_kind": "WHY_NOW",
            "supports_why_now": True,
            "why_now_event": {
                "event_kind": "FILM_RELEASE",
                "media_identity": {
                    "media_kind": "FILM",
                    "show_or_title": "Example Film",
                },
            },
            "event_or_release_at": NOW.isoformat(),
            "confidence": 0.9,
        }
        discovery = _openai_payload(
            evidence=[official], sources=[{"url": official_url}]
        )
        wrong_year = NOW.replace(year=NOW.year - 1).isoformat()
        page = (
            "<title>Example Film release date</title>"
            f'<meta property="article:published_time" content="{wrong_year}">'
            f"<body>Example Film is coming {NOW.strftime('%B')} {NOW.day}.</body>"
        )
        empty_retries = [
            _openai_payload(evidence=[], sources=[]),
            _openai_payload(evidence=[], sources=[]),
        ]
        transport = FakeJsonTransport(
            [
                JsonResponse(200, {}, discovery),
                *(JsonResponse(200, {}, payload) for payload in empty_retries),
            ]
        )
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=("example.com",),
            request_body_max_input_tokens=120_000,
            request_max_tool_calls=13,
            transport=transport,
            page_transport=FakeTextTransport([page]),
        )

        batch = provider.collect(
            intent_from_query("new movie or trailer"),
            authorization=_authorization(
                "openai",
                "research.web_verify",
                model="gpt-5.6-luna",
                max_requests=20,
                max_tool_calls=13,
                max_input_tokens=180_000,
                max_output_tokens=12_000,
            ),
            cancellation=CancellationToken(),
        )

        self.assertEqual(batch.evidence, ())
        self.assertEqual(len(transport.requests), 3)
        self.assertEqual(batch.usage.request_count, 4)
        self.assertEqual(batch.usage.tool_calls, 3)
        self.assertTrue(
            any("1 official title/date mismatch" in warning for warning in batch.warnings)
        )

    def test_film_staged_search_does_not_promote_a_forged_official_lead(self) -> None:
        official_url = "https://example.com/example-film"
        official = {
            "source_type": "PRIMARY_RELEASE",
            "canonical_url": official_url,
            "title": "Example Film official release",
            "excerpt_type": "PARAPHRASE",
            "excerpt": "Example Film has a current official release.",
            "verification": "PRIMARY_VERIFIED",
            "claim_kind": "WHY_NOW",
            "supports_why_now": True,
            "why_now_event": {
                "event_kind": "FILM_RELEASE",
                "media_identity": {
                    "media_kind": "FILM",
                    "show_or_title": "Example Film",
                },
            },
            "event_or_release_at": NOW.isoformat(),
            "confidence": 0.9,
        }
        responses = [
            _openai_payload(evidence=[official], sources=[{"url": official_url}]),
            _openai_payload(
                evidence=[],
                sources=[{"url": "https://www.cinemablend.com/movies/example-film-review"}],
            ),
            _openai_payload(
                evidence=[],
                sources=[{"url": "https://www.thewrap.com/example-film-review"}],
            ),
        ]
        for index, payload in enumerate(responses):
            payload["id"] = f"resp_forged_{index}"
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=("example.com",),
            request_body_max_input_tokens=120_000,
            request_max_tool_calls=13,
            transport=FakeJsonTransport(
                [JsonResponse(200, {}, payload) for payload in responses]
            ),
            page_transport=FakeTextTransport(
                [
                    '<script type="application/ld+json">'
                    + json.dumps(
                        {
                            "@type": "Movie",
                            "name": "Different Film",
                            "datePublished": NOW.date().isoformat(),
                        }
                    )
                    + "</script>",
                ]
            ),
        )

        batch = provider.collect(
            intent_from_query("new movie or trailer"),
            authorization=_authorization(
                "openai",
                "research.web_verify",
                model="gpt-5.6-luna",
                max_requests=20,
                max_tool_calls=13,
                max_input_tokens=180_000,
                max_output_tokens=12_000,
            ),
            cancellation=CancellationToken(),
        )

        self.assertFalse(
            any(item.claim_kind is EvidenceClaimKind.WHY_NOW for item in batch.evidence)
        )
        self.assertEqual(batch.evidence, ())
        self.assertEqual(len(provider._transport.requests), 3)
        self.assertEqual(batch.usage.request_count, 4)
        self.assertEqual(batch.usage.tool_calls, 3)
        self.assertTrue(
            any(
                "staged official validation accepted no primary" in warning
                for warning in batch.warnings
            )
        )
        diagnostic = next(
            warning
            for warning in batch.warnings
            if "staged official public lead was" in warning
        )
        self.assertIn("Example Film (FILM, FILM_RELEASE", diagnostic)
        self.assertIn("example.com/example-film=official title/date mismatch", diagnostic)

    def test_openai_still_omits_ambiguous_event_date_text(self) -> None:
        evidence = {
            "source_type": "PRIMARY_RELEASE",
            "canonical_url": "https://example.com/example-film",
            "title": "Example Film official release",
            "excerpt_type": "PARAPHRASE",
            "excerpt": "Example Film was released today.",
            "verification": "PRIMARY_VERIFIED",
            "claim_kind": "WHY_NOW",
            "supports_why_now": True,
            "why_now_event": {
                "event_kind": "FILM_RELEASE",
                "media_identity": {"media_kind": "FILM", "show_or_title": "Example Film"},
            },
            "source_created_at": "",
            "event_or_release_at": "today",
            "confidence": 0.9,
        }
        payload = _openai_payload(
            evidence=[evidence],
            sources=[{"url": evidence["canonical_url"], "title": "Example Film"}],
        )
        provider = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=("example.com",),
            transport=FakeJsonTransport([JsonResponse(200, {}, payload)]),
        )

        batch = provider.collect(
            intent_from_query("Example Film current release"),
            authorization=_authorization(
                "openai", "research.web_verify", model="gpt-5.6-luna"
            ),
            cancellation=CancellationToken(),
        )

        self.assertEqual(batch.evidence, ())
        self.assertTrue(
            any("event_or_release_at:datetime_parsing" in item for item in batch.warnings)
        )

    def test_tvmaze_preflights_schedule_and_cast_before_first_request(self) -> None:
        transport = FakeJsonTransport([JsonResponse(200, {}, [])])
        provider = TVmazeProvider(transport=transport)
        with self.assertRaisesRegex(Exception, "complete bounded"):
            provider.collect(
                intent_from_query("Find one TV episode from the last one day"),
                authorization=_authorization(
                    "tvmaze", "research.metadata", max_requests=2
                ),
                cancellation=CancellationToken(),
            )
        self.assertEqual(transport.requests, [])

    def test_tvmaze_skips_film_and_trailer_intent_without_network(self) -> None:
        transport = FakeJsonTransport([])
        result = TVmazeProvider(transport=transport).collect(
            intent_from_query("trailers and new movies"),
            authorization=_authorization(
                "tvmaze", "research.metadata", max_requests=40
            ),
            cancellation=CancellationToken(),
        )

        self.assertEqual(result.evidence, ())
        self.assertEqual(result.usage.request_count, 0)
        self.assertEqual(transport.requests, [])
        self.assertIn("no television media kind", result.warnings[0])

    def test_tvmaze_covers_broadcast_web_cast_and_official_host(self) -> None:
        episode = {
            "id": 10,
            "name": "Turning Point",
            "season": 1,
            "number": 2,
            "airstamp": NOW.isoformat(),
            "url": "https://www.tvmaze.com/episodes/10/turning-point",
            "show": {
                "id": 5,
                "name": "Example Show",
                "type": "Scripted",
                "language": "English",
                "genres": ["Romance"],
                "officialSite": "https://example.com/show",
            },
        }
        cast = [
            {
                "person": {"id": 1, "name": "Actor One", "url": "https://www.tvmaze.com/people/1"},
                "character": {"name": "Alex"},
            },
            {
                "person": {"id": 2, "name": "Actor Two", "url": "https://www.tvmaze.com/people/2"},
                "character": {"name": "Jamie"},
            },
        ]
        transport = FakeJsonTransport(
            [
                JsonResponse(200, {}, [episode]),
                JsonResponse(200, {}, [episode]),
                JsonResponse(200, {}, []),
                JsonResponse(200, {}, []),
                JsonResponse(200, {}, cast),
            ]
        )
        result = TVmazeProvider(transport=transport).collect(
            intent_from_query("Find one romance TV episode from the last one day"),
            authorization=_authorization(
                "tvmaze", "research.metadata", max_requests=12
            ),
            cancellation=CancellationToken(),
        )
        self.assertEqual(result.usage.request_count, 5)
        self.assertEqual(len(result.evidence), 3)
        self.assertEqual(result.trusted_official_hosts, ("example.com",))
        self.assertIn("CC BY-SA", result.attributions[0])
        self.assertEqual(
            result.evidence[1].provider_record_id,
            _cast_provider_record_id(show_id=5),
        )
        self.assertEqual(
            result.evidence[2].provider_record_id,
            _cast_provider_record_id(show_id=5),
        )
        self.assertEqual(
            {item.canonical_url for item in result.evidence[1:]},
            {"https://api.tvmaze.com/shows/5/cast"},
        )
        sources, claims = normalize_batches(
            [result], retrieved_at=NOW, official_hosts=set()
        )
        self.assertEqual(len(sources), 2)
        self.assertEqual(len(claims), 3)

    def test_tvmaze_cast_source_identity_is_show_specific(self) -> None:
        sterling = _cast_provider_record_id(show_id=101)
        walking_dead = _cast_provider_record_id(show_id=202)

        self.assertNotEqual(sterling, walking_dead)
        self.assertEqual(sterling, _cast_provider_record_id(show_id=101))
        with self.assertRaises(ValueError):
            _cast_provider_record_id(show_id=0)

    def test_tvmaze_female_audience_filter_excludes_unaligned_high_weight_show(self) -> None:
        def episode(
            *,
            record_id: int,
            show_id: int,
            show_name: str,
            weight: int,
            summary: str,
        ) -> dict[str, object]:
            return {
                "id": record_id,
                "name": "Turning Point",
                "season": 1,
                "number": record_id,
                "airstamp": (NOW - timedelta(hours=2)).isoformat(),
                "url": f"https://www.tvmaze.com/episodes/{record_id}/turning-point",
                "show": {
                    "id": show_id,
                    "name": show_name,
                    "type": "Scripted",
                    "language": "English",
                    "genres": ["Drama"],
                    "weight": weight,
                    "summary": summary,
                    "officialSite": f"https://show{show_id}.example/show",
                    "webChannel": {"country": {"code": "US"}},
                },
            }

        lanterns = episode(
            record_id=1,
            show_id=1,
            show_name="Lanterns",
            weight=100,
            summary=(
                "New recruit John Stewart and legend Hal Jordan investigate a dark mystery."
            ),
        )
        aligned = episode(
            record_id=2,
            show_id=2,
            show_name="Second Chances",
            weight=60,
            summary=(
                "After losing her old life, a teenager and her sisters rebuild together."
            ),
        )
        transport = FakeJsonTransport(
            [
                JsonResponse(200, {}, [lanterns, aligned]),
                JsonResponse(200, {}, []),
                JsonResponse(200, {}, []),
                JsonResponse(200, {}, []),
                JsonResponse(200, {}, []),
            ]
        )
        intent = intent_from_query(
            "a good show for girls that'll get views on tiktok"
        ).model_copy(update={"freshness_days": 1})

        batch = TVmazeProvider(transport=transport, clock=lambda: NOW).collect(
            intent,
            authorization=_authorization(
                "tvmaze", "research.metadata", max_requests=12
            ),
            cancellation=CancellationToken(),
        )

        locators = [
            item.episode_locator
            for item in batch.evidence
            if item.claim_kind is EvidenceClaimKind.EPISODE_IDENTITY
        ]
        self.assertEqual(intent.focus_terms, ["female-centered"])
        self.assertEqual(
            [locator.show_or_title for locator in locators if locator is not None],
            ["Second Chances"],
        )

    def test_tvmaze_does_not_seed_episodes_that_have_not_aired(self) -> None:
        future = {
            "id": 10,
            "name": "Tomorrow's Episode",
            "season": 1,
            "number": 3,
            "airstamp": (NOW + timedelta(hours=2)).isoformat(),
            "url": "https://www.tvmaze.com/episodes/10/tomorrows-episode",
            "show": {
                "id": 5,
                "name": "Example Show",
                "type": "Scripted",
                "language": "English",
                "genres": ["Romance"],
                "officialSite": "https://example.com/show",
            },
        }
        result = TVmazeProvider(
            transport=FakeJsonTransport(
                [
                    JsonResponse(200, {}, [future]),
                    JsonResponse(200, {}, [future]),
                    JsonResponse(200, {}, []),
                    JsonResponse(200, {}, []),
                ]
            )
        ).collect(
            intent_from_query("Find one romance TV episode from the last one day"),
            authorization=_authorization(
                "tvmaze", "research.metadata", max_requests=12
            ),
            cancellation=CancellationToken(),
        )
        self.assertEqual(result.evidence, ())
        self.assertEqual(result.usage.request_count, 4)

    def test_tvmaze_queries_and_filters_the_oldest_partial_calendar_day(self) -> None:
        fixed_now = datetime(2026, 8, 16, 8, 30, tzinfo=timezone.utc)

        def episode(record_id: int, airstamp: datetime) -> dict[str, object]:
            return {
                "id": record_id,
                "name": "Knightly",
                "season": 1,
                "number": 4,
                "airstamp": airstamp.isoformat(),
                "url": f"https://www.tvmaze.com/episodes/{record_id}/knightly",
                "show": {
                    "id": 93184,
                    "name": "Paris is Always a Good Idea",
                    "type": "Scripted",
                    "language": "English",
                    "genres": ["Drama", "Romance"],
                    "weight": 96,
                    "officialSite": "https://www.hallmarkchannel.com/paris",
                    "webChannel": {"country": {"code": "US"}},
                },
            }

        within_window = episode(3678550, fixed_now - timedelta(hours=68, minutes=30))
        outside_window = episode(3678549, fixed_now - timedelta(hours=72, minutes=30))
        transport = FakeJsonTransport(
            [
                *[JsonResponse(200, {}, []) for _ in range(7)],
                JsonResponse(200, {}, [within_window, outside_window]),
                JsonResponse(200, {}, []),
            ]
        )
        result = TVmazeProvider(transport=transport, clock=lambda: fixed_now).collect(
            intent_from_query("romance TV from the last three days"),
            authorization=_authorization(
                "tvmaze", "research.metadata", max_requests=16
            ),
            cancellation=CancellationToken(),
        )

        locators = [item.episode_locator for item in result.evidence if item.episode_locator]
        self.assertEqual(len(locators), 1)
        self.assertEqual(locators[0].show_or_title, "Paris is Always a Good Idea")
        schedule_urls = [item["url"] for item in transport.requests[:8]]
        self.assertTrue(any("date=2026-08-13" in url for url in schedule_urls))

    def test_tvmaze_prefers_requested_region_over_newer_global_web_row(self) -> None:
        def episode(
            *, record_id: int, show_id: int, show_name: str, hours_ago: int, country: str
        ) -> dict[str, object]:
            return {
                "id": record_id,
                "name": "Turning Point",
                "season": 1,
                "number": 2,
                "airstamp": (NOW - timedelta(hours=hours_ago)).isoformat(),
                "url": f"https://www.tvmaze.com/episodes/{record_id}/turning-point",
                "show": {
                    "id": show_id,
                    "name": show_name,
                    "type": "Scripted",
                    "language": "English",
                    "genres": ["Romance"],
                    "officialSite": f"https://example{show_id}.com/show",
                    "webChannel": {"country": {"code": country}},
                },
            }

        us_episode = episode(
            record_id=10,
            show_id=5,
            show_name="Regional Romance",
            hours_ago=12,
            country="US",
        )
        global_episode = episode(
            record_id=20,
            show_id=6,
            show_name="Newer Global Romance",
            hours_ago=1,
            country="CN",
        )
        intent = intent_from_query(
            "Find one romance TV episode from the last one day"
        ).model_copy(update={"max_results": 2})
        result = TVmazeProvider(
            transport=FakeJsonTransport(
                [
                    JsonResponse(200, {}, [us_episode]),
                    JsonResponse(200, {}, [global_episode]),
                    JsonResponse(200, {}, []),
                    JsonResponse(200, {}, []),
                    JsonResponse(200, {}, []),
                    JsonResponse(200, {}, []),
                ]
            )
        ).collect(
            intent,
            authorization=_authorization(
                "tvmaze", "research.metadata", max_requests=12
            ),
            cancellation=CancellationToken(),
        )
        self.assertEqual(len(result.evidence), 2)
        self.assertEqual(
            result.evidence[0].episode_locator.show_or_title,
            "Regional Romance",
        )
        seeds = _trusted_tvmaze_episode_seeds(
            ProviderResearchContext(prior_evidence=result.evidence),
            intent=intent,
            now=NOW,
        )
        self.assertEqual(seeds[0].show_or_title, "Regional Romance")

    def test_tvmaze_accepts_calendar_year_seasons_and_skips_invalid_rows(self) -> None:
        def episode(record_id: int, season: int, name: str) -> dict[str, object]:
            return {
                "id": record_id,
                "name": name,
                "season": season,
                "number": 158,
                "airstamp": NOW.isoformat(),
                "url": f"https://www.tvmaze.com/episodes/{record_id}/episode-158",
                "show": {
                    "id": 5,
                    "name": "Example Daily Drama",
                    "type": "Scripted",
                    "language": "English",
                    "genres": ["Romance"],
                    "officialSite": "https://example.com/daily-drama",
                },
            }

        transport = FakeJsonTransport(
            [
                JsonResponse(
                    200,
                    {},
                    [
                        episode(20, 2026, "A Calendar-Year Episode"),
                        {
                            **episode(19, 2026, "An Older Calendar-Year Episode"),
                            "airstamp": (NOW - timedelta(days=1)).isoformat(),
                        },
                        episode(21, 10_000, "Outside The Bounded Contract"),
                        {
                            **episode(22, 2026, "Unrelated News Episode"),
                            "show": {
                                "id": 7,
                                "name": "Example Nightly News",
                                "type": "News",
                                "language": "English",
                                "genres": ["News"],
                                "officialSite": "https://example.com/news",
                            },
                        },
                    ],
                ),
                JsonResponse(200, {}, []),
                JsonResponse(200, {}, []),
                JsonResponse(200, {}, []),
                JsonResponse(200, {}, []),
            ]
        )
        result = TVmazeProvider(transport=transport).collect(
            intent_from_query("Find one romance TV episode from the last one day"),
            authorization=_authorization(
                "tvmaze", "research.metadata", max_requests=12
            ),
            cancellation=CancellationToken(),
        )
        locators = [item.episode_locator for item in result.evidence if item.episode_locator]
        self.assertEqual(result.usage.request_count, 5)
        self.assertEqual(len(locators), 1)
        self.assertEqual(locators[0].season_number, 2026)
        self.assertEqual(locators[0].episode_number, 158)
        self.assertEqual(locators[0].episode_title, "A Calendar-Year Episode")

    def test_tvmaze_broad_romcom_prompt_keeps_ranked_discovery_pool(self) -> None:
        def episode(
            *,
            record_id: int,
            show_id: int,
            show_name: str,
            episode_name: str,
            genres: list[str],
            country: str,
            weight: int,
            summary: str | None = None,
        ) -> dict[str, object]:
            return {
                "id": record_id,
                "name": episode_name,
                "season": 1,
                "number": record_id,
                "airstamp": (NOW - timedelta(hours=record_id)).isoformat(),
                "url": f"https://www.tvmaze.com/episodes/{record_id}/episode",
                "show": {
                    "id": show_id,
                    "name": show_name,
                    "type": "Scripted",
                    "language": "English",
                    "genres": genres,
                    "weight": weight,
                    "summary": summary,
                    "officialSite": f"https://show{show_id}.example/show",
                    "webChannel": {"country": {"code": country}},
                },
            }

        generic_us_soap = episode(
            record_id=1,
            show_id=1,
            show_name="Daily Hearts",
            episode_name="Episode 240",
            genres=["Drama", "Romance"],
            country="US",
            weight=95,
        )
        exact_global_romcom = episode(
            record_id=2,
            show_id=2,
            show_name="Second Chances",
            episode_name="The Almost Kiss",
            genres=["Comedy", "Romance"],
            country="TH",
            weight=70,
        )
        named_us_romance = episode(
            record_id=3,
            show_id=3,
            show_name="Summer Letters",
            episode_name="What We Never Said",
            genres=["Drama", "Romance"],
            country="US",
            weight=80,
        )
        summary_only_romance = episode(
            record_id=17,
            show_id=17,
            show_name="Island Inheritance",
            episode_name="The Choice",
            genres=["Drama"],
            country="US",
            weight=99,
            summary="<p>Annie finds new friends, a budding romance, and family secrets.</p>",
        )
        filler_rows = [
            episode(
                record_id=index,
                show_id=index,
                show_name=f"Filler Romance {index}",
                episode_name=f"Episode {index}",
                genres=["Drama", "Romance"],
                country="US",
                weight=100 - index,
            )
            for index in range(4, 17)
        ]
        transport = FakeJsonTransport(
            [
                JsonResponse(
                    200,
                    {},
                    [generic_us_soap, summary_only_romance, *filler_rows[:6]],
                ),
                JsonResponse(200, {}, [exact_global_romcom, named_us_romance, *filler_rows[6:]]),
                *[JsonResponse(200, {}, []) for _ in range(36)],
            ]
        )
        intent = intent_from_query(
            "romance/romcom TV, preferably a new episode from the last three days, "
            "no K-drama, no reality TV"
        ).model_copy(update={"max_results": 1})

        batch = TVmazeProvider(transport=transport).collect(
            intent,
            authorization=_authorization(
                "tvmaze", "research.metadata", max_requests=38
            ),
            cancellation=CancellationToken(),
        )
        episode_rows = [
            item
            for item in batch.evidence
            if item.claim_kind is EvidenceClaimKind.EPISODE_IDENTITY
        ]
        seeds = _trusted_tvmaze_episode_seeds(
            ProviderResearchContext(prior_evidence=batch.evidence),
            intent=intent,
            now=NOW,
        )

        self.assertEqual(intent.freshness_days, 14)
        self.assertEqual(
            intent_from_query("romance TV from the last three days").freshness_days,
            3,
        )
        self.assertEqual(intent.exclusions, ["K-drama", "reality TV"])
        self.assertEqual(batch.usage.request_count, 38)
        self.assertEqual(len(episode_rows), 15)
        self.assertEqual(len(seeds), 15)
        self.assertEqual(seeds[0].show_or_title, "Second Chances")
        self.assertIn("Island Inheritance", {item.show_or_title for item in seeds})
        self.assertNotEqual(len(seeds), intent.max_results)
        self.assertTrue(any("17 matching current shows" in item for item in batch.warnings))
        self.assertTrue(any("3-day timing was treated as a preference" in item for item in batch.warnings))

    def test_youtube_skips_unstructured_upload_and_binds_official_trailer(self) -> None:
        payload = {
            "items": [
                {
                    "id": {"videoId": "bad"},
                    "snippet": {
                        "channelId": "studio",
                        "channelTitle": "Official Studio",
                        "title": "A random old interview",
                        "publishedAt": NOW.isoformat(),
                    },
                },
                {
                    "id": {"videoId": "good"},
                    "snippet": {
                        "channelId": "studio",
                        "channelTitle": "Official Studio",
                        "title": "Example Show | Official Trailer",
                        "publishedAt": NOW.isoformat(),
                    },
                },
            ]
        }
        provider = YouTubeOfficialProvider(
            credential=SecretCredential("secret"),
            official_channel_ids=("studio",),
            transport=FakeJsonTransport([JsonResponse(200, {}, payload)]),
            clock=lambda: NOW,
        )
        result = provider.collect(
            intent_from_query("Find one current TV episode"),
            authorization=_authorization(
                "youtube", "research.youtube", max_requests=1
            ),
            cancellation=CancellationToken(),
            context=_trusted_tvmaze_context(),
        )
        self.assertEqual(len(result.evidence), 1)
        self.assertEqual(
            result.evidence[0].why_now_event.media_identity.show_or_title,
            "Example Show",
        )
        self.assertEqual(result.usage.quota_units, 1)

    def test_youtube_exact_trusted_title_finds_specific_official_scene_link(self) -> None:
        payload = {
            "items": [
                {
                    "id": {"videoId": "scene-link"},
                    "snippet": {
                        "channelId": "studio",
                        "channelTitle": "Official Studio",
                        "title": "A Quiet Confession | Example Show | Official Studio",
                        "publishedAt": NOW.isoformat(),
                    },
                },
                {
                    "id": {"videoId": "interview"},
                    "snippet": {
                        "channelId": "studio",
                        "channelTitle": "Official Studio",
                        "title": "Example Show Cast Interview",
                        "publishedAt": NOW.isoformat(),
                    },
                },
                {
                    "id": {"videoId": "wrong-title"},
                    "snippet": {
                        "channelId": "studio",
                        "channelTitle": "Official Studio",
                        "title": "A Quiet Confession | Different Show",
                        "publishedAt": NOW.isoformat(),
                    },
                },
            ]
        }
        transport = FakeJsonTransport([JsonResponse(200, {}, payload)])
        provider = YouTubeOfficialProvider(
            credential=SecretCredential("secret"),
            official_channel_ids=("studio",),
            transport=transport,
            clock=lambda: NOW,
        )

        result = provider.collect(
            intent_from_query("Find one current TV episode"),
            authorization=_authorization(
                "youtube", "research.youtube", max_requests=1
            ),
            cancellation=CancellationToken(),
            context=_trusted_tvmaze_context(),
        )

        self.assertEqual(len(transport.requests), 1)
        self.assertNotIn("channelId=", transport.requests[0]["url"])
        self.assertIn("Example+Show", transport.requests[0]["url"])
        self.assertEqual(len(result.evidence), 1)
        evidence = result.evidence[0]
        self.assertEqual(
            evidence.canonical_url,
            "https://www.youtube.com/watch?v=scene-link",
        )
        self.assertEqual(
            evidence.scene_fact.description,
            "Official upload labeled “A Quiet Confession”",
        )
        self.assertEqual(
            evidence.why_now_event.media_identity.show_or_title,
            "Example Show",
        )
        self.assertTrue(
            any("not-a-clip-or-trailer" in warning for warning in result.warnings)
        )

    def test_youtube_metadata_failure_is_optional_and_usage_stays_complete(self) -> None:
        class FailingTransport:
            def request_json(self, **kwargs):
                del kwargs
                raise ProviderError("provider returned HTTP 403")

        provider = YouTubeOfficialProvider(
            credential=SecretCredential("secret"),
            official_channel_ids=("studio",),
            transport=FailingTransport(),
            clock=lambda: NOW,
        )

        result = provider.collect(
            intent_from_query("Find one current TV episode"),
            authorization=_authorization(
                "youtube", "research.youtube", max_requests=1
            ),
            cancellation=CancellationToken(),
            context=_trusted_tvmaze_context(),
        )

        self.assertEqual(result.outcome, ProviderRunOutcome.SUCCESS)
        self.assertEqual(result.evidence, ())
        self.assertEqual(result.usage.request_count, 1)
        self.assertEqual(result.usage.quota_units, 1)
        self.assertTrue(any("HTTP 403" in warning for warning in result.warnings))

    def test_xai_arbitrary_or_mismatched_proof_cannot_enable_search(self) -> None:
        proof = XAIInvocationCapProof(
            proof_id="proof",
            configured_model="grok-4.6",
            resolved_model="grok-4.6",
            request_policy_sha256="0" * 64,
            proof_record_sha256="1" * 64,
            max_turns=2,
            validated_at=NOW - timedelta(hours=1),
            expires_at=NOW + timedelta(hours=1),
            passed_adversarial_test=True,
        )
        provider = XAISearchProvider(
            credential=SecretCredential("secret"),
            model="grok-4.6",
            invocation_cap_proof=proof,
            zero_data_retention_required=True,
            enabled=True,
            transport=FakeJsonTransport([]),
        )
        with self.assertRaises(ProviderDisabledError):
            provider.collect(
                intent_from_query("TV discussion"),
                authorization=_authorization(
                    "xai",
                    "research.x_search",
                    model="grok-4.6",
                    privacy="zdr",
                ),
                cancellation=CancellationToken(),
            )

    def test_url_rejects_invalid_port_and_ipv4_mapped_loopback(self) -> None:
        with self.assertRaises(ValueError):
            canonicalize_public_url("https://example.com:bad/path")
        with self.assertRaises(ValueError):
            canonicalize_public_url("https://[::ffff:127.0.0.1]/")

    def test_transport_rejects_redirect_without_forwarding_credentials(self) -> None:
        class Opener:
            calls = 0

            def open(self, request, timeout):
                del timeout
                self.calls += 1
                self.request = request
                raise HTTPError(
                    request.full_url,
                    302,
                    "redirect",
                    {"Location": "https://evil.example/steal"},
                    io.BytesIO(),
                )

        opener = Opener()
        with patch("ai_edit_machine.providers.transport.build_opener", return_value=opener):
            with self.assertRaisesRegex(Exception, "redirect was rejected"):
                UrllibJsonTransport(max_attempts=1).request_json(
                    method="GET",
                    url="https://api.example.com/data",
                    headers={"Authorization": "Bearer secret"},
                    body=None,
                    timeout_seconds=2,
                    max_response_bytes=1000,
                    allowed_hosts=frozenset({"api.example.com"}),
                )
        self.assertEqual(opener.calls, 1)
        self.assertEqual(opener.request.full_url, "https://api.example.com/data")

    def test_provider_json_rejects_duplicate_and_nonfinite_values(self) -> None:
        class Response:
            status = 200
            headers = {}

            def __init__(self, payload: bytes) -> None:
                self.payload = payload

            def read(self, size: int) -> bytes:
                del size
                return self.payload

            def __enter__(self):
                return self

            def __exit__(self, *args):
                del args

        class Opener:
            def __init__(self, payload: bytes) -> None:
                self.payload = payload

            def open(self, request, timeout):
                del request, timeout
                return Response(self.payload)

        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}'):
            with self.subTest(raw=raw):
                with patch(
                    "ai_edit_machine.providers.transport.build_opener",
                    return_value=Opener(raw),
                ):
                    with self.assertRaisesRegex(ProviderError, "invalid JSON"):
                        UrllibJsonTransport(max_attempts=1).request_json(
                            method="GET",
                            url="https://api.example.com/data",
                            headers={},
                            body=None,
                            timeout_seconds=2,
                            max_response_bytes=1000,
                            allowed_hosts=frozenset({"api.example.com"}),
                        )

    def test_official_page_dns_is_global_pinned_and_default_port_only(self) -> None:
        transport = UrllibTextTransport()
        for address in ("127.0.0.1", "10.0.0.1", "100.64.0.1"):
            with self.subTest(address=address), patch(
                "ai_edit_machine.providers.transport.socket.getaddrinfo",
                return_value=[(2, 1, 6, "", (address, 443))],
            ):
                with self.assertRaisesRegex(ProviderError, "non-public"):
                    transport.request_text(
                        url="https://example.com/page",
                        timeout_seconds=2,
                        max_response_bytes=1000,
                        allowed_hosts=frozenset({"example.com"}),
                    )
        with self.assertRaisesRegex(ValueError, "default HTTPS port"):
            transport.request_text(
                url="https://example.com:8443/page",
                timeout_seconds=2,
                max_response_bytes=1000,
                allowed_hosts=frozenset({"example.com"}),
            )

        captured: dict[str, object] = {}

        class PageResponse:
            status = 200
            headers = {"Content-Type": "text/html; charset=utf-8"}

            def read(self, size: int) -> bytes:
                del size
                return b"<html>ok</html>"

        class Connection:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            def request(self, method, target, headers):
                captured.update({"method": method, "target": target, "headers": headers})

            def getresponse(self):
                return PageResponse()

            def close(self):
                pass

        with patch(
            "ai_edit_machine.providers.transport.socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("93.184.216.34", 443))],
        ) as resolver, patch(
            "ai_edit_machine.providers.transport._PinnedHttpsConnection",
            Connection,
        ):
            self.assertEqual(
                transport.request_text(
                    url="https://example.com/page",
                    timeout_seconds=2,
                    max_response_bytes=1000,
                    allowed_hosts=frozenset({"example.com"}),
                ),
                "<html>ok</html>",
            )
        self.assertEqual(resolver.call_count, 1)
        self.assertEqual(captured["pinned_ip"], "93.184.216.34")
        self.assertEqual(captured["hostname"], "example.com")

    def test_synthesis_repair_uses_only_remaining_aggregate_output_tokens(self) -> None:
        first = {
            "id": "resp_bad",
            "model": "gpt-5.6-luna",
            "status": "completed",
            "usage": {"input_tokens": 10, "output_tokens": 900},
            "output": [
                {"type": "message", "content": [{"type": "output_text", "text": "{"}]}
            ],
        }
        second = {
            "id": "resp_fixed",
            "model": "gpt-5.6-luna",
            "status": "completed",
            "usage": {"input_tokens": 20, "output_tokens": 100},
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(
                                {
                                    "schema_version": "2.0.0",
                                    "recommendations": [],
                                    "no_strong_opportunity_reason": "No strong opportunity.",
                                }
                            ),
                        }
                    ],
                }
            ],
        }
        transport = FakeJsonTransport(
            [JsonResponse(200, {}, first), JsonResponse(200, {}, second)]
        )
        provider = OpenAIResearchSynthesizer(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            transport=transport,
        )
        result = provider.synthesize(
            intent_from_query("current TV episode"),
            evidence_sources=[],
            evidence_claims=[],
            authorization=_authorization(
                "openai",
                "research.synthesize",
                model="gpt-5.6-luna",
                max_requests=2,
                max_tool_calls=0,
                max_output_tokens=1_000,
                allow_one_repair=True,
            ),
            cancellation=CancellationToken(),
        )
        self.assertEqual(result.outcome, ProviderRunOutcome.SUCCESS)
        self.assertEqual(transport.requests[0]["body"]["max_output_tokens"], 1_000)
        self.assertEqual(transport.requests[1]["body"]["max_output_tokens"], 100)
        self.assertEqual(result.usage.output_tokens, 1_000)

    def test_synthesis_explicitly_maps_canonical_claim_kinds_to_draft_roles(self) -> None:
        metadata = _trusted_tvmaze_context().prior_evidence[0]
        discussions = tuple(
            EvidenceCandidate(
                provider="openai",
                provider_record_id=tvmaze_show_source_binding("Example Show", url),
                source_type=EvidenceSourceType.ARTICLE,
                canonical_url=url,
                title=title,
                author_or_channel=owner,
                excerpt_type=ExcerptType.PARAPHRASE,
                excerpt=f"Current cited-source title: {title}",
                verification=VerificationState.SECONDARY_CORROBORATED,
                claim_kind=EvidenceClaimKind.VIEWER_DISCUSSION,
                supports_why_now=True,
                policy_class="openai-web-evidence-v1",
                source_created_at=NOW,
                citation_verified=True,
                content_binding_verified=True,
            )
            for url, title, owner in (
                (
                    "https://www.techradar.com/streaming/example-show-romance",
                    "Example Show romance turn has viewers talking",
                    "TechRadar",
                ),
                (
                    "https://los40.com/series/example-show-romance",
                    "El romance de Example Show cambia",
                    "LOS40",
                ),
            )
        )
        sources, claims = normalize_batches(
            [
                ProviderBatch(provider="tvmaze", evidence=(metadata,)),
                ProviderBatch(provider="openai", evidence=discussions),
            ],
            retrieved_at=NOW,
            official_hosts=set(),
        )
        self.assertEqual(
            [claim.claim_kind for claim in claims],
            [
                EvidenceClaimKind.VIEWER_DISCUSSION,
                EvidenceClaimKind.VIEWER_DISCUSSION,
                EvidenceClaimKind.EPISODE_IDENTITY,
            ],
        )
        self.assertEqual(
            [(source.provider, source.title, source.provider_record_id) for source in sources],
            [
                (
                    "openai",
                    "El romance de Example Show cambia",
                    tvmaze_show_source_binding(
                        "Example Show", "https://los40.com/series/example-show-romance"
                    ),
                ),
                (
                    "openai",
                    "Example Show romance turn has viewers talking",
                    tvmaze_show_source_binding(
                        "Example Show",
                        "https://www.techradar.com/streaming/example-show-romance",
                    ),
                ),
                (
                    "tvmaze",
                    "Example Show - S01E02: Turning Point",
                    "episode:2",
                ),
            ],
        )
        response = {
            "id": "resp_role_mapping",
            "model": "gpt-5.6-luna",
            "status": "completed",
            "usage": {"input_tokens": 100, "output_tokens": 20},
            "output": [{
                "type": "message",
                "content": [{
                    "type": "output_text",
                    "text": json.dumps({
                        "schema_version": "2.0.0",
                        "recommendations": [],
                        "no_strong_opportunity_reason": "Fixture only.",
                    }),
                }],
            }],
        }
        transport = FakeJsonTransport([JsonResponse(200, {}, response)])
        provider = OpenAIResearchSynthesizer(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            transport=transport,
        )

        provider.synthesize(
            intent_from_query("current romance TV episode"),
            evidence_sources=sources,
            evidence_claims=claims,
            authorization=_authorization(
                "openai",
                "research.synthesize",
                model="gpt-5.6-luna",
                max_requests=1,
                max_tool_calls=0,
                max_input_tokens=60_000,
            ),
            cancellation=CancellationToken(),
        )

        body = transport.requests[0]["body"]
        payload = json.loads(body["input"])
        self.assertTrue(
            payload["role_assignment_guide"]["claim_records_do_not_contain_roles"]
        )
        hints = payload["candidate_role_hints"]
        self.assertEqual(len(hints), 1)
        self.assertEqual(hints[0]["identity_required_role"], "CONTEXT")
        self.assertEqual(hints[0]["distinct_qualitative_signal_group_count"], 2)
        self.assertTrue(hints[0]["meets_synthesis_eligibility"])
        self.assertEqual(
            {item["required_role"] for item in hints[0]["qualitative_signals"]},
            {"QUALITATIVE_SIGNAL"},
            hints,
        )
        self.assertEqual(
            {item["independence_group"] for item in hints[0]["qualitative_signals"]},
            {"owner:future-plc", "owner:prisa-media"},
        )
        self.assertIn("Claim records intentionally do not contain", body["instructions"])
        self.assertIn("meets_synthesis_eligibility=true", body["instructions"])
        self.assertIn(
            "headline-level evidence, not a scene",
            body["instructions"],
        )
        self.assertIn(
            "SCENE_CONTEXT claim carries an episode_locator",
            body["instructions"],
        )
        self.assertIn(
            "prefer those exact character names",
            body["instructions"],
        )

    def test_synthesis_canonicalizes_only_duplicate_nonfactual_source_labels(self) -> None:
        raw = json.dumps(
            {
                "schema_version": "2.0.0",
                "recommendations": [
                    {
                        "opportunity": {
                            "media_kind": "TV_EPISODE",
                            "media_identity": {"show_or_title": "Keep this"},
                            "focus": {"relationship_or_topic": "Keep this focus"},
                            "title": "Guaranteed viral title",
                            "why_now": "viral now",
                            "what_viewers_are_discussing": "viral discussion",
                            "creative_hook": "viral hook",
                            "emotional_edit_direction": "viral direction",
                            "evidence": [{"claim_id": "keep-this-claim"}],
                            "confidence": 0.7,
                            "caveats": ["viral certainty"],
                        },
                        "footage_request": {
                            "required_sources": [{
                                "source_key": "walter_scenes",
                                "priority": 8,
                                "asset_kind": "SCENE_PACK",
                                "season_number": 3,
                                "episode_number": 10,
                                "episode_title": "The Beautiful and the Damned",
                                "purposes": ["MONTAGE", "INTRO", "MONTAGE"],
                                "supporting_claim_ids": ["claim-a", "claim-a"],
                            }],
                            "optional_sources": [{
                                "source_key": "walter_scenes",
                                "priority": 4,
                                "replaces_required_source_keys": ["wrong"],
                            }],
                            "alternative_sources": [{
                                "source_key": "walter_scenes",
                                "priority": 9,
                                "replaces_required_source_keys": [],
                            }],
                            "natural_request": {
                                "best": "",
                                "alternative": "",
                                "minimum": "",
                                "optional_improvement": "",
                            },
                            "minimum_useful_source_keys": ["wrong"],
                            "intro_leads": [{"source_key": "walter_scenes"}],
                            "search_queries": ["duplicate", "DUPLICATE"],
                        }
                    }
                ],
                "no_strong_opportunity_reason": None,
            }
        )

        canonical = json.loads(_canonicalize_nonfactual_source_keys(raw))
        opportunity = canonical["recommendations"][0]["opportunity"]
        self.assertNotIn("viral", json.dumps(opportunity).casefold())
        self.assertEqual(opportunity["media_identity"], {"show_or_title": "Keep this"})
        self.assertEqual(
            opportunity["focus"], {"relationship_or_topic": "Keep this focus"}
        )
        self.assertEqual(opportunity["evidence"], [{"claim_id": "keep-this-claim"}])
        self.assertEqual(opportunity["confidence"], 0.7)
        request = canonical["recommendations"][0]["footage_request"]
        self.assertEqual(
            request["required_sources"][0]["source_key"],
            "walter_scenes",
        )
        self.assertEqual(
            request["optional_sources"][0]["source_key"],
            "walter_scenes_optional_1",
        )
        self.assertEqual(
            request["alternative_sources"][0]["source_key"],
            "walter_scenes_alternative_1",
        )
        self.assertEqual(request["minimum_useful_source_keys"], ["walter_scenes"])
        self.assertEqual(request["intro_leads"][0]["source_key"], "walter_scenes")
        self.assertEqual(request["required_sources"][0]["priority"], 1)
        self.assertIsNone(request["required_sources"][0]["season_number"])
        self.assertIsNone(request["required_sources"][0]["episode_number"])
        self.assertIsNone(request["required_sources"][0]["episode_title"])
        self.assertEqual(request["optional_sources"][0]["priority"], 1)
        self.assertEqual(request["alternative_sources"][0]["priority"], 1)
        self.assertEqual(
            request["required_sources"][0]["purposes"], ["INTRO", "MONTAGE"]
        )
        self.assertEqual(
            request["required_sources"][0]["supporting_claim_ids"], ["claim-a"]
        )
        self.assertEqual(
            request["alternative_sources"][0]["replaces_required_source_keys"],
            ["walter_scenes"],
        )
        self.assertEqual(
            request["optional_sources"][0]["replaces_required_source_keys"], []
        )
        self.assertEqual(
            request["search_queries"], ["Pending validated discovery query."]
        )
        self.assertTrue(request["natural_request"]["best"])
        self.assertTrue(request["natural_request"]["minimum"])
        self.assertTrue(request["natural_request"]["alternative"])
        self.assertTrue(request["natural_request"]["optional_improvement"])

        ambiguous_required = json.dumps(
            {
                "recommendations": [
                    {
                        "footage_request": {
                            "required_sources": [
                                {"source_key": "same_key"},
                                {"source_key": "same_key"},
                            ],
                            "optional_sources": [{"source_key": "same_key"}],
                            "alternative_sources": [],
                        }
                    }
                ]
            }
        )
        self.assertEqual(
            _canonicalize_nonfactual_source_keys(ambiguous_required),
            ambiguous_required,
        )

    def test_synthesis_uses_bounded_repair_for_local_domain_violation(self) -> None:
        first = {
            "id": "resp_semantic_bad",
            "model": "gpt-5.6-luna",
            "status": "completed",
            "usage": {"input_tokens": 10, "output_tokens": 20},
            "output": [{
                "type": "message",
                "content": [{
                    "type": "output_text",
                    "text": json.dumps({
                        "schema_version": "2.0.0",
                        "recommendations": [],
                        "no_strong_opportunity_reason": None,
                    }),
                }],
            }],
        }
        second = {
            "id": "resp_semantic_fixed",
            "model": "gpt-5.6-luna",
            "status": "completed",
            "usage": {"input_tokens": 20, "output_tokens": 10},
            "output": [{
                "type": "message",
                "content": [{
                    "type": "output_text",
                    "text": json.dumps({
                        "schema_version": "2.0.0",
                        "recommendations": [],
                        "no_strong_opportunity_reason": "No supported recommendation remained.",
                    }),
                }],
            }],
        }
        transport = FakeJsonTransport([
            JsonResponse(200, {}, first),
            JsonResponse(200, {}, second),
        ])
        provider = OpenAIResearchSynthesizer(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            transport=transport,
        )
        result = provider.synthesize(
            intent_from_query("current TV episode"),
            evidence_sources=[],
            evidence_claims=[],
            authorization=_authorization(
                "openai",
                "research.synthesize",
                model="gpt-5.6-luna",
                max_requests=2,
                max_tool_calls=0,
                max_input_tokens=100_000,
                max_output_tokens=1_000,
                allow_one_repair=True,
            ),
            cancellation=CancellationToken(),
        )
        self.assertEqual(result.outcome, ProviderRunOutcome.SUCCESS)
        self.assertEqual(len(transport.requests), 2)
        repair_body = transport.requests[1]["body"]
        self.assertIn("strict local contract validation", repair_body["instructions"])
        repair_input = json.loads(repair_body["input"])
        self.assertEqual(len(repair_input["validation_issues"]), 1)
        self.assertIn("empty synthesis requires", repair_input["validation_issues"][0])
        self.assertEqual(repair_input["repair_context"]["allowed_source_ids"], [])
        self.assertEqual(repair_input["repair_context"]["allowed_claim_ids"], [])
        self.assertNotIn("sources", repair_input["repair_context"])
        self.assertNotIn("claims", repair_input["repair_context"])

    def test_synthesis_repair_propagates_missing_priced_usage(self) -> None:
        first = {
            "id": "resp_partial_usage",
            "model": "gpt-5.6-luna",
            "status": "completed",
            # A started paid response with no input-token counter must remain
            # unverified after repair rather than being treated as zero.
            "usage": {"output_tokens": 10},
            "output": [
                {"type": "message", "content": [{"type": "output_text", "text": "{"}]}
            ],
        }
        second = {
            "id": "resp_repaired",
            "model": "gpt-5.6-luna",
            "status": "completed",
            "usage": {"input_tokens": 20, "output_tokens": 5},
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(
                                {
                                    "schema_version": "2.0.0",
                                    "recommendations": [],
                                    "no_strong_opportunity_reason": "No strong opportunity.",
                                }
                            ),
                        }
                    ],
                }
            ],
        }
        provider = OpenAIResearchSynthesizer(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            transport=FakeJsonTransport(
                [JsonResponse(200, {}, first), JsonResponse(200, {}, second)]
            ),
        )
        result = provider.synthesize(
            intent_from_query("current TV episode"),
            evidence_sources=[],
            evidence_claims=[],
            authorization=_authorization(
                "openai",
                "research.synthesize",
                model="gpt-5.6-luna",
                max_requests=2,
                max_tool_calls=0,
                max_output_tokens=100,
                allow_one_repair=True,
            ),
            cancellation=CancellationToken(),
        )
        self.assertEqual(result.outcome, ProviderRunOutcome.SUCCESS)
        self.assertIsNone(result.usage.input_tokens)
        self.assertEqual(result.usage.output_tokens, 15)

    def test_paid_openai_requests_are_input_capped_before_post(self) -> None:
        web_transport = FakeJsonTransport([])
        verifier = OpenAIWebVerifier(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            official_domains=(),
            transport=web_transport,
        )
        web_result = verifier.collect(
            intent_from_query("current TV episode"),
            authorization=_authorization(
                "openai",
                "research.web_verify",
                model="gpt-5.6-luna",
                max_tool_calls=1,
                max_input_tokens=1,
            ),
            cancellation=CancellationToken(),
        )
        self.assertEqual(web_result.outcome, ProviderRunOutcome.ERROR)
        self.assertEqual(web_result.usage.request_count, 0)
        self.assertEqual(web_transport.requests, [])

        synthesis_transport = FakeJsonTransport([])
        synthesizer = OpenAIResearchSynthesizer(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            transport=synthesis_transport,
        )
        synthesis_result = synthesizer.synthesize(
            intent_from_query("current TV episode"),
            evidence_sources=[],
            evidence_claims=[],
            authorization=_authorization(
                "openai",
                "research.synthesize",
                model="gpt-5.6-luna",
                max_requests=2,
                max_tool_calls=0,
                max_input_tokens=1,
                allow_one_repair=True,
            ),
            cancellation=CancellationToken(),
        )
        self.assertEqual(synthesis_result.outcome, ProviderRunOutcome.ERROR)
        self.assertEqual(synthesis_result.usage.request_count, 0)
        self.assertEqual(synthesis_transport.requests, [])

    def test_synthesis_repair_cannot_exceed_aggregate_input_cap(self) -> None:
        malformed = {
            "id": "resp_bad_input_budget",
            "model": "gpt-5.6-luna",
            "status": "completed",
            "usage": {"input_tokens": 10, "output_tokens": 10},
            "output": [
                {"type": "message", "content": [{"type": "output_text", "text": "{"}]}
            ],
        }
        repaired = {
            "id": "resp_unused_repair",
            "model": "gpt-5.6-luna",
            "status": "completed",
            "usage": {"input_tokens": 20, "output_tokens": 5},
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(
                                {
                                    "schema_version": "2.0.0",
                                    "recommendations": [],
                                    "no_strong_opportunity_reason": "No strong opportunity.",
                                }
                            ),
                        }
                    ],
                }
            ],
        }
        probe_transport = FakeJsonTransport(
            [JsonResponse(200, {}, malformed), JsonResponse(200, {}, repaired)]
        )
        probe = OpenAIResearchSynthesizer(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            transport=probe_transport,
        )
        probe.synthesize(
            intent_from_query("current TV episode"),
            evidence_sources=[],
            evidence_claims=[],
            authorization=_authorization(
                "openai",
                "research.synthesize",
                model="gpt-5.6-luna",
                max_requests=2,
                max_tool_calls=0,
                max_input_tokens=1_000_000,
                allow_one_repair=True,
            ),
            cancellation=CancellationToken(),
        )
        first_bound = REQUEST_TOKEN_OVERHEAD + len(
            json.dumps(
                probe_transport.requests[0]["body"],
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        )
        limited_transport = FakeJsonTransport(
            [JsonResponse(200, {}, malformed), JsonResponse(200, {}, repaired)]
        )
        limited = OpenAIResearchSynthesizer(
            credential=SecretCredential("secret"),
            model="gpt-5.6-luna",
            transport=limited_transport,
        )
        result = limited.synthesize(
            intent_from_query("current TV episode"),
            evidence_sources=[],
            evidence_claims=[],
            authorization=_authorization(
                "openai",
                "research.synthesize",
                model="gpt-5.6-luna",
                max_requests=2,
                max_tool_calls=0,
                max_input_tokens=first_bound,
                allow_one_repair=True,
            ),
            cancellation=CancellationToken(),
        )
        self.assertEqual(result.outcome, ProviderRunOutcome.ERROR)
        self.assertEqual(len(limited_transport.requests), 1)
        self.assertEqual(result.usage.request_count, 1)
        self.assertEqual(result.usage.input_tokens, 10)


def _trusted_tvmaze_context() -> ProviderResearchContext:
    locator = EpisodeLocatorFactV2(
        show_or_title="Example Show",
        season_number=1,
        episode_number=2,
        episode_title="Turning Point",
    )
    episode = EvidenceCandidate(
        provider="tvmaze",
        provider_record_id="episode:2",
        source_type=EvidenceSourceType.METADATA,
        canonical_url="https://www.tvmaze.com/episodes/2/turning-point",
        title="Example Show - S01E02: Turning Point",
        author_or_channel="TVmaze",
        excerpt_type=ExcerptType.PARAPHRASE,
        excerpt="TVmaze lists Turning Point as Season 1 Episode 2.",
        verification=VerificationState.SECONDARY_CORROBORATED,
        claim_kind=EvidenceClaimKind.EPISODE_IDENTITY,
        supports_why_now=False,
        policy_class="tvmaze-metadata-v1",
        event_or_release_at=NOW,
        citation_verified=True,
        episode_locator=locator,
    )
    cast = tuple(
        EvidenceCandidate(
            provider="tvmaze",
            provider_record_id=f"person:{index}",
            source_type=EvidenceSourceType.METADATA,
            canonical_url=f"https://www.tvmaze.com/people/{index}/{character.casefold()}",
            title=f"Performer {index} as {character} in Example Show",
            author_or_channel="TVmaze",
            excerpt_type=ExcerptType.PARAPHRASE,
            excerpt=f"TVmaze lists Performer {index} as {character} in Example Show.",
            verification=VerificationState.SECONDARY_CORROBORATED,
            claim_kind=EvidenceClaimKind.CAST_IDENTITY,
            supports_why_now=False,
            policy_class="tvmaze-metadata-v1",
            citation_verified=True,
            cast_fact=CastIdentityFactV2(
                show_or_title="Example Show",
                character_name=character,
                performer_name=f"Performer {index}",
            ),
        )
        for index, character in enumerate(("Jamie", "Alex"), start=1)
    )
    return ProviderResearchContext(
        prior_evidence=(episode, *cast),
        trusted_official_hosts=("example.com",),
    )


def _eight_seed_tvmaze_context() -> ProviderResearchContext:
    base = _trusted_tvmaze_context()
    evidence = list(base.prior_evidence)
    for index in range(3, 10):
        locator = EpisodeLocatorFactV2(
            show_or_title=f"Candidate Show {index}",
            season_number=1,
            episode_number=index,
            episode_title=f"Episode {index}",
        )
        evidence.append(
            EvidenceCandidate(
                provider="tvmaze",
                provider_record_id=f"episode:{index}",
                source_type=EvidenceSourceType.METADATA,
                canonical_url=f"https://www.tvmaze.com/episodes/{index}",
                title=f"Candidate Show {index} - S01E{index:02d}: Episode {index}",
                author_or_channel="TVmaze",
                excerpt_type=ExcerptType.PARAPHRASE,
                excerpt=f"TVmaze lists Episode {index} as current.",
                verification=VerificationState.SECONDARY_CORROBORATED,
                claim_kind=EvidenceClaimKind.EPISODE_IDENTITY,
                supports_why_now=False,
                policy_class="tvmaze-metadata-v1",
                event_or_release_at=NOW - timedelta(hours=index),
                citation_verified=True,
                episode_locator=locator,
            )
        )
    return ProviderResearchContext(
        prior_evidence=tuple(evidence),
        trusted_official_hosts=base.trusted_official_hosts,
    )


def _live_r57_tvmaze_context() -> ProviderResearchContext:
    titles = (
        "Stuart Fails to Save the Universe",
        "Furious",
        "Fightland",
        "The Real Housewives: Ultimate Girls Trip",
        "Paris is Always a Good Idea",
        "Candidate Show 6",
        "Candidate Show 7",
        "Candidate Show 8",
    )
    evidence: list[EvidenceCandidate] = []
    for index, title in enumerate(titles, start=1):
        locator = EpisodeLocatorFactV2(
            show_or_title=title,
            season_number=1,
            episode_number=index,
            episode_title=f"Episode {index}",
        )
        evidence.append(
            EvidenceCandidate(
                provider="tvmaze",
                provider_record_id=f"episode:r57:{index}",
                source_type=EvidenceSourceType.METADATA,
                canonical_url=f"https://www.tvmaze.com/episodes/57{index}",
                title=f"{title} - S01E{index:02d}: Episode {index}",
                author_or_channel="TVmaze",
                excerpt_type=ExcerptType.PARAPHRASE,
                excerpt=f"TVmaze lists a current {title} episode.",
                verification=VerificationState.SECONDARY_CORROBORATED,
                claim_kind=EvidenceClaimKind.EPISODE_IDENTITY,
                supports_why_now=False,
                policy_class="tvmaze-metadata-v1",
                event_or_release_at=NOW - timedelta(hours=index),
                citation_verified=True,
                episode_locator=locator,
            )
        )
    evidence.append(
        EvidenceCandidate(
            provider="tvmaze",
            provider_record_id="person:r57:furious:alice-black",
            source_type=EvidenceSourceType.METADATA,
            canonical_url="https://api.tvmaze.com/shows/87753/cast",
            title="Furious cast listing",
            author_or_channel="TVmaze",
            excerpt_type=ExcerptType.PARAPHRASE,
            excerpt=(
                "TVmaze lists Emmy Rossum as Special Agent Alice Black in Furious."
            ),
            verification=VerificationState.SECONDARY_CORROBORATED,
            claim_kind=EvidenceClaimKind.CAST_IDENTITY,
            supports_why_now=False,
            policy_class="tvmaze-metadata-v1",
            citation_verified=True,
            cast_fact=CastIdentityFactV2(
                show_or_title="Furious",
                character_name="Special Agent Alice Black",
                performer_name="Emmy Rossum",
            ),
        )
    )
    return ProviderResearchContext(
        prior_evidence=tuple(evidence),
        trusted_official_hosts=("example.com",),
    )


def _openai_payload(*, evidence: list[dict[str, object]], sources: list[dict[str, object]]):
    return {
        "id": "resp_1",
        "model": "gpt-5.6-luna",
        "status": "completed",
        "usage": {"input_tokens": 100, "output_tokens": 30},
        "output": [
            {"type": "web_search_call", "id": "search_1", "action": {"sources": sources}},
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps({"evidence": evidence}, separators=(",", ":")),
                    }
                ],
            },
        ],
    }


def _attach_excerpt_citation(
    payload: dict[str, object], *, excerpt: object, url: str, title: str
) -> None:
    assert isinstance(excerpt, str)
    output = payload["output"]
    assert isinstance(output, list)
    message = output[-1]
    assert isinstance(message, dict)
    content = message["content"]
    assert isinstance(content, list)
    block = content[0]
    assert isinstance(block, dict)
    raw = block["text"]
    assert isinstance(raw, str)
    encoded = json.dumps(excerpt, ensure_ascii=False)
    start = raw.index(encoded) + 1
    end = start + len(encoded) - 2
    block.setdefault("annotations", []).append(
        {
            "type": "url_citation",
            "start_index": start,
            "end_index": end,
            "url": url,
            "title": title,
        }
    )


def _openai_cited_line_payload(
    records: list[tuple[str, str, str]],
) -> dict[str, object]:
    text = "\n".join(["M1_SOURCE_LEADS_V2", *(line for line, _, _ in records)])
    annotations = []
    sources = []
    search_from = len("M1_SOURCE_LEADS_V2\n")
    for line, url, title in records:
        start = text.index(line, search_from)
        end = start + len(line)
        search_from = end
        annotations.append(
            {
                "type": "url_citation",
                "start_index": start,
                "end_index": end,
                "url": url,
                "title": title,
            }
        )
        sources.append({"url": url, "title": title})
    return {
        "id": "resp_line",
        "model": "gpt-5.6-luna",
        "status": "completed",
        "usage": {"input_tokens": 100, "output_tokens": 30},
        "output": [
            {
                "type": "web_search_call",
                "id": "search_line",
                "action": {"sources": sources},
            },
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": text,
                        "annotations": annotations,
                    }
                ],
            },
        ],
    }


def _openai_tv_selector_payload(
    records: list[tuple[str, str, str]],
) -> dict[str, object]:
    lines = [
        "M1_TV_COVERAGE_SELECTORS_V1",
        *(f"CANDIDATE\t{title}" for title, _, _ in records),
    ]
    text = "\n".join(lines)
    annotations: list[dict[str, object]] = []
    sources: list[dict[str, object]] = []
    search_from = len(lines[0]) + 1
    for title, url, source_title in records:
        line = f"CANDIDATE\t{title}"
        start = text.index(line, search_from)
        end = start + len(line)
        search_from = end
        annotations.append(
            {
                "type": "url_citation",
                "start_index": start,
                "end_index": end,
                "url": url,
                "title": source_title,
            }
        )
        sources.append(
            {
                "url": url,
                "title": source_title,
                "published_at": NOW.isoformat(),
            }
        )
    return {
        "id": "resp_tv_selector",
        "model": "gpt-5.6-luna",
        "status": "completed",
        "usage": {"input_tokens": 100, "output_tokens": 30},
        "output": [
            {
                "type": "web_search_call",
                "id": "search_tv_selector",
                "action": {"sources": sources},
            },
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": text,
                        "annotations": annotations,
                    }
                ],
            },
        ],
    }


if __name__ == "__main__":
    unittest.main()
