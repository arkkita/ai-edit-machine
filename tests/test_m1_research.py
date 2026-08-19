from __future__ import annotations

import json
import sys
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ai_edit_machine.contracts import (  # noqa: E402
    EvidenceGate,
    EvidenceRole,
    EvidenceSourceType,
    ExcerptType,
    MediaKind,
    OpportunityFocus,
    VerificationState,
)
from ai_edit_machine.m1_contracts import (  # noqa: E402
    CastIdentityFactV2,
    EpisodeLocatorFactV2,
    EvidenceClaimKind,
    EvidenceClaimRecordV2,
    EvidenceSourceRecordV2,
    FootageQuoteStatus,
    FootageQuoteV2,
    FootageRequestDraftV2,
    FootageVerificationLevel,
    IntroMaterialLeadDraftV2,
    MediaIdentityV2,
    NaturalFootageRequestV2,
    OpportunityEvidenceSelectionV2,
    QuoteFactV2,
    RequestedSourceDraftV2,
    ResearchSynthesisDraftV2,
    SceneMomentFactV2,
    SourceAcquisitionKind,
    SourcePurpose,
    SynthesisRecommendationDraftV2,
    TrendOpportunityDraftV2,
    WhyNowEventFactV2,
    WhyNowEventKind,
)
from ai_edit_machine.providers.base import (  # noqa: E402
    CallAuthorization,
    CancellationToken,
    EvidenceCandidate,
    ProviderBatch,
    ProviderResearchContext,
    ProviderRunOutcome,
)
from ai_edit_machine.providers.fake import FakeResearchProvider  # noqa: E402
from ai_edit_machine.providers.normalize import normalize_batches  # noqa: E402
from ai_edit_machine.research.cache import research_cache_key  # noqa: E402
from ai_edit_machine.research.evidence import EvidenceIndex  # noqa: E402
from ai_edit_machine.research.footage import canonicalize_footage_request  # noqa: E402
from ai_edit_machine.research.intent import intent_from_query, violates_exclusions  # noqa: E402
from ai_edit_machine.research.source_ownership import (  # noqa: E402
    media_title_source_binding,
    tvmaze_show_source_binding,
)
from ai_edit_machine.research.synthesis import SynthesisProviderResult  # noqa: E402
from ai_edit_machine.research.workflow import (  # noqa: E402
    ProviderPlan,
    ResearchWorkflow,
    _attach_official_video_sources,
    _merge_reusable_evidence,
    _official_video_source_drafts,
    _provider_reusable_discussion_context,
)


NOW = datetime(2026, 8, 15, 12, tzinfo=timezone.utc)


def _source(*, title: str = "Example Show evidence") -> EvidenceSourceRecordV2:
    return EvidenceSourceRecordV2(
        source_id=uuid4(),
        provider="fixture",
        source_type=EvidenceSourceType.METADATA,
        canonical_url="https://example.com/evidence",
        title=title,
        retrieved_at=NOW,
        query="fixture",
        policy_class="official-page-v1",
        content_sha256="1" * 64,
        independence_group="publisher:fixture",
    )


def _claim(source: EvidenceSourceRecordV2, **updates: object) -> EvidenceClaimRecordV2:
    values: dict[str, object] = {
        "claim_id": uuid4(),
        "source_id": source.source_id,
        "claim_kind": EvidenceClaimKind.EPISODE_IDENTITY,
        "excerpt_type": ExcerptType.PARAPHRASE,
        "text": "Example Show Season 1 Episode 2",
        "verification": VerificationState.SECONDARY_CORROBORATED,
        "episode_locator": EpisodeLocatorFactV2(
            show_or_title="Example Show",
            season_number=1,
            episode_number=2,
            episode_title="Turning Point",
        ),
        "confidence": 0.9,
        "supports_why_now": False,
        "content_sha256": "2" * 64,
    }
    values.update(updates)
    return EvidenceClaimRecordV2(**values)


def _requested_source(**updates: object) -> RequestedSourceDraftV2:
    values: dict[str, object] = {
        "source_key": "s1e2",
        "priority": 1,
        "acquisition_effort": 2,
        "asset_kind": SourceAcquisitionKind.EPISODE,
        "show_or_title": "Example Show",
        "season_number": 1,
        "episode_number": 2,
        "episode_title": "Turning Point",
        "characters": ["A", "B"],
        "relationship_or_topic": "A and B",
        "scene_or_moment": "A admits the relationship changed.",
        "purposes": [SourcePurpose.INTRO, SourcePurpose.MONTAGE],
        "verification_level": FootageVerificationLevel.LIKELY_INFERRED,
        "source_quality_summary": "Model-authored quality copy is ignored.",
        "supporting_claim_ids": [],
        "why_it_matters_emotionally": "It establishes the turn before the payoff.",
        "search_queries": ["Example Show S1E2 A B scene"],
    }
    values.update(updates)
    return RequestedSourceDraftV2(**values)


def _request(source: RequestedSourceDraftV2, **updates: object) -> FootageRequestDraftV2:
    values: dict[str, object] = {
        "summary": "A compact source request.",
        "natural_request": NaturalFootageRequestV2(
            best="Give me Example Show Season 1 Episode 2.",
            minimum="The smallest useful set is that episode.",
        ),
        "required_sources": [source],
        "minimum_useful_source_keys": [source.source_key],
        "smallest_useful_set_reason": "One episode contains the cited setup.",
        "search_queries": ["Example Show season 1 episode 2"],
    }
    values.update(updates)
    return FootageRequestDraftV2(**values)


class _DynamicTrailerSynthesizer:
    name = "openai"

    def synthesize(self, intent, *, evidence_sources, evidence_claims, authorization, cancellation):
        del evidence_sources, authorization
        cancellation.raise_if_cancelled()
        primary = next(
            claim
            for claim in evidence_claims
            if claim.verification is VerificationState.PRIMARY_VERIFIED
        )
        signals = [
            claim
            for claim in evidence_claims
            if claim.claim_kind is EvidenceClaimKind.VIEWER_DISCUSSION
        ]
        source = RequestedSourceDraftV2(
            source_key="official_trailer",
            priority=1,
            acquisition_effort=1,
            asset_kind=SourceAcquisitionKind.OFFICIAL_TRAILER,
            show_or_title="Example Film",
            characters=[],
            relationship_or_topic="the central relationship",
            scene_or_moment=primary.text,
            purposes=[SourcePurpose.INTRO, SourcePurpose.MONTAGE],
            verification_level=FootageVerificationLevel.LIKELY_INFERRED,
            source_quality_summary="Untrusted model copy.",
            supporting_claim_ids=[primary.claim_id],
            why_it_matters_emotionally="The official trailer supplies setup and payoff imagery.",
            search_queries=["Example Film official trailer"],
        )
        footage = _request(
            source,
            natural_request=NaturalFootageRequestV2(
                best="Give me the official Example Film trailer.",
                minimum="The official trailer is enough.",
            ),
            minimum_useful_source_keys=["official_trailer"],
            search_queries=["Example Film official trailer"],
        )
        opportunity = TrendOpportunityDraftV2(
            media_kind=MediaKind.TRAILER,
            media_identity=MediaIdentityV2(
                media_kind=MediaKind.TRAILER, show_or_title="Example Film"
            ),
            title="Example Film official-trailer relationship turn",
            focus=OpportunityFocus(characters=[], relationship_or_topic="central relationship"),
            why_now="A fresh official trailer establishes a current release moment.",
            what_viewers_are_discussing="Two independent current sources discuss the relationship turn.",
            creative_hook="Open on the official setup, then move into the emotional contrast.",
            emotional_edit_direction="Tender setup into a sharper payoff.",
            evidence=[
                OpportunityEvidenceSelectionV2(
                    claim_id=primary.claim_id,
                    role=EvidenceRole.PRIMARY_WHY_NOW,
                    supports_why_now=True,
                ),
                *[
                    OpportunityEvidenceSelectionV2(
                        claim_id=claim.claim_id,
                        role=EvidenceRole.QUALITATIVE_SIGNAL,
                        supports_why_now=True,
                    )
                    for claim in signals
                ],
            ],
            confidence=0.8,
        )
        return SynthesisProviderResult(
            provider=self.name,
            draft=ResearchSynthesisDraftV2(
                recommendations=[
                    SynthesisRecommendationDraftV2(
                        opportunity=opportunity, footage_request=footage
                    )
                ]
            ),
        )


class _MetadataLowSynthesizer:
    name = "openai"

    def __init__(self) -> None:
        self.seen_claims: tuple[EvidenceClaimRecordV2, ...] = ()

    def synthesize(self, intent, *, evidence_sources, evidence_claims, authorization, cancellation):
        del evidence_sources, authorization
        self.seen_claims = tuple(evidence_claims)
        cancellation.raise_if_cancelled()
        metadata = next(
            claim
            for claim in evidence_claims
            if claim.claim_kind is EvidenceClaimKind.EPISODE_IDENTITY
        )
        assert metadata.episode_locator is not None
        signals = [
            claim
            for claim in evidence_claims
            if claim.claim_kind is EvidenceClaimKind.VIEWER_DISCUSSION
        ]
        source = RequestedSourceDraftV2(
            source_key="relationship_pack",
            priority=1,
            acquisition_effort=2,
            asset_kind=SourceAcquisitionKind.SCENE_PACK,
            show_or_title=metadata.episode_locator.show_or_title,
            characters=[],
            relationship_or_topic="central relationship",
            scene_or_moment=signals[0].text,
            purposes=[SourcePurpose.INTRO, SourcePurpose.MONTAGE, SourcePurpose.PAYOFF],
            verification_level=FootageVerificationLevel.LIKELY_INFERRED,
            source_quality_summary="Untrusted model copy.",
            supporting_claim_ids=[metadata.claim_id, *[claim.claim_id for claim in signals]],
            why_it_matters_emotionally="Untrusted model rationale.",
            search_queries=["Example Show central relationship scene pack"],
        )
        footage = _request(
            source,
            natural_request=NaturalFootageRequestV2(
                best="Give me an Example Show central relationship scene pack.",
                minimum="The scene pack is enough.",
            ),
            minimum_useful_source_keys=[source.source_key],
            search_queries=["Example Show central relationship scene pack"],
        )
        opportunity = TrendOpportunityDraftV2(
            media_kind=MediaKind.TV_EPISODE,
            media_identity=MediaIdentityV2(
                media_kind=MediaKind.TV_EPISODE,
                show_or_title=metadata.episode_locator.show_or_title,
                season_number=metadata.episode_locator.season_number,
                episode_number=metadata.episode_locator.episode_number,
                episode_title=metadata.episode_locator.episode_title,
            ),
            title="Untrusted title",
            focus=OpportunityFocus(
                characters=[], relationship_or_topic="central relationship"
            ),
            why_now="Untrusted timing copy.",
            what_viewers_are_discussing="Untrusted discussion copy.",
            creative_hook="Untrusted creative copy.",
            emotional_edit_direction="Untrusted direction copy.",
            evidence=[
                OpportunityEvidenceSelectionV2(
                    claim_id=metadata.claim_id,
                    role=EvidenceRole.CONTEXT,
                    supports_why_now=False,
                ),
                *[
                    OpportunityEvidenceSelectionV2(
                        claim_id=claim.claim_id,
                        role=EvidenceRole.QUALITATIVE_SIGNAL,
                        supports_why_now=True,
                    )
                    for claim in signals
                ],
            ],
            confidence=0.7,
        )
        return SynthesisProviderResult(
            provider=self.name,
            draft=ResearchSynthesisDraftV2(
                recommendations=[
                    SynthesisRecommendationDraftV2(
                        opportunity=opportunity, footage_request=footage
                    )
                ]
            ),
        )


class M1ResearchTests(unittest.TestCase):

    def test_reusable_current_discussion_cannot_complete_owner_mix_without_live_revalidation(self) -> None:
        def discussion(host: str) -> EvidenceCandidate:
            canonical_url = f"https://{host}/example-show-current"
            return EvidenceCandidate(
                provider="openai",
                provider_record_id=tvmaze_show_source_binding(
                    "Example Show", canonical_url
                ),
                source_type=EvidenceSourceType.ARTICLE,
                canonical_url=canonical_url,
                title="Example Show relationship discussion",
                author_or_channel=host,
                excerpt_type=ExcerptType.PARAPHRASE,
                excerpt=f"Example Show relationship discussion at {host}",
                verification=VerificationState.SECONDARY_CORROBORATED,
                claim_kind=EvidenceClaimKind.VIEWER_DISCUSSION,
                supports_why_now=True,
                policy_class="openai-web-evidence-v1",
                source_created_at=NOW - timedelta(hours=2),
                page_published_at=NOW - timedelta(hours=2),
                window_start=NOW - timedelta(days=3),
                window_end=NOW,
                citation_verified=True,
                content_binding_verified=True,
            )

        fresh_sources, fresh_claims = normalize_batches(
            [ProviderBatch(provider="openai", evidence=(discussion("los40.com"),))],
            retrieved_at=NOW,
            official_hosts=set(),
        )
        metadata_source = EvidenceSourceRecordV2(
            source_id=uuid4(),
            provider="tvmaze",
            provider_record_id="episode:102",
            source_type=EvidenceSourceType.METADATA,
            canonical_url="https://www.tvmaze.com/episodes/102/turning-point",
            title="Example Show S01E02: Turning Point",
            author_or_channel="TVmaze",
            retrieved_at=NOW,
            query="romance TV",
            policy_class="tvmaze-metadata-v1",
            content_sha256="a" * 64,
            independence_group="tvmaze.example-show",
        )
        fresh_sources.append(metadata_source)
        fresh_claims.append(_claim(metadata_source))
        cached_sources, cached_claims = normalize_batches(
            [
                ProviderBatch(
                    provider="openai",
                    evidence=(discussion("los40.com"), discussion("techradar.com")),
                )
            ],
            retrieved_at=NOW - timedelta(hours=1),
            official_hosts=set(),
        )
        merged_sources, merged_claims, reused = _merge_reusable_evidence(
            fresh_sources,
            fresh_claims,
            tuple(cached_sources),
            tuple(cached_claims),
            generated_at=NOW,
        )
        self.assertEqual(reused, 0)
        self.assertEqual({source.independence_group for source in merged_sources}, {
            "owner:prisa-media",
            "tvmaze.example-show",
        })
        self.assertEqual(len(merged_claims), 2)

    def test_reusable_tv_discussion_is_not_carried_into_an_unrelated_run(self) -> None:
        canonical_url = "https://techradar.com/example-show-current"
        cached_sources, cached_claims = normalize_batches(
            [
                ProviderBatch(
                    provider="openai",
                    evidence=(
                        EvidenceCandidate(
                            provider="openai",
                            provider_record_id=tvmaze_show_source_binding(
                                "Example Show", canonical_url
                            ),
                            source_type=EvidenceSourceType.ARTICLE,
                            canonical_url=canonical_url,
                            title="Example Show relationship discussion",
                            author_or_channel="TechRadar",
                            excerpt_type=ExcerptType.PARAPHRASE,
                            excerpt="Example Show relationship discussion at TechRadar",
                            verification=VerificationState.SECONDARY_CORROBORATED,
                            claim_kind=EvidenceClaimKind.VIEWER_DISCUSSION,
                            supports_why_now=True,
                            policy_class="openai-web-evidence-v1",
                            source_created_at=NOW - timedelta(hours=2),
                            page_published_at=NOW - timedelta(hours=2),
                            window_start=NOW - timedelta(days=3),
                            window_end=NOW,
                            citation_verified=True,
                            content_binding_verified=True,
                        ),
                    ),
                )
            ],
            retrieved_at=NOW - timedelta(hours=1),
            official_hosts=set(),
        )

        sources, claims, reused = _merge_reusable_evidence(
            [],
            [],
            tuple(cached_sources),
            tuple(cached_claims),
            generated_at=NOW,
        )

        self.assertEqual((sources, claims, reused), ([], [], 0))

    def test_current_tv_identity_exposes_cached_discussion_only_for_local_page_refresh(self) -> None:
        url = "https://techradar.com/example-show-episode-2-ending-explained"
        cached_sources, cached_claims = normalize_batches(
            [
                ProviderBatch(
                    provider="openai",
                    evidence=(
                        EvidenceCandidate(
                            provider="openai",
                            provider_record_id=tvmaze_show_source_binding(
                                "Example Show", url
                            ),
                            source_type=EvidenceSourceType.ARTICLE,
                            canonical_url=url,
                            title="Example Show episode 2 ending explained",
                            author_or_channel="TechRadar",
                            excerpt_type=ExcerptType.PARAPHRASE,
                            excerpt="Current cited-source title: Example Show episode 2 ending explained",
                            verification=VerificationState.SECONDARY_CORROBORATED,
                            claim_kind=EvidenceClaimKind.VIEWER_DISCUSSION,
                            supports_why_now=True,
                            policy_class="openai-web-evidence-v1",
                            source_created_at=NOW - timedelta(hours=2),
                            page_published_at=NOW - timedelta(hours=2),
                            window_start=NOW - timedelta(days=3),
                            window_end=NOW,
                            citation_verified=True,
                            content_binding_verified=True,
                        ),
                    ),
                )
            ],
            retrieved_at=NOW - timedelta(hours=1),
            official_hosts=set(),
        )
        locator = EpisodeLocatorFactV2(
            show_or_title="Example Show",
            season_number=1,
            episode_number=2,
            episode_title="Turning Point",
        )
        current_identity = EvidenceCandidate(
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

        selected = _provider_reusable_discussion_context(
            tuple(cached_sources),
            tuple(cached_claims),
            current_evidence=(current_identity,),
            generated_at=NOW,
            max_items=8,
        )
        unrelated = _provider_reusable_discussion_context(
            tuple(cached_sources),
            tuple(cached_claims),
            current_evidence=(),
            generated_at=NOW,
            max_items=8,
        )

        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].canonical_url, url)
        self.assertEqual(selected[0].claim_kind, EvidenceClaimKind.VIEWER_DISCUSSION)
        self.assertEqual(unrelated, ())

    def test_all_dated_corpus_intent_expectations(self) -> None:
        corpus = json.loads((ROOT / "evals" / "2026-08-15" / "corpus.json").read_text("utf-8"))
        for case in corpus["cases"]:
            with self.subTest(case=case["case_id"]):
                actual = intent_from_query(case["prompt"])
                expected = case["intent_expectations"]
                self.assertEqual([item.value for item in actual.media_kinds], expected["media_kinds"])
                self.assertLessEqual(actual.freshness_days, expected["freshness_days_max"])
                self.assertEqual(actual.exclusions, expected["exclusions"])
                self.assertEqual(actual.spoiler_policy.value, expected["spoiler_policy"])
                self.assertEqual(actual.max_results, expected["max_results"])
                if "focus_terms" in expected:
                    self.assertEqual(actual.focus_terms, expected["focus_terms"])

    def test_region_spoilers_count_and_named_focus_are_explicit(self) -> None:
        intent = intent_from_query(
            "Belly + Conrad romance TV in the UK, allow spoilers, return three"
        )
        self.assertEqual(intent.region, "GB")
        self.assertEqual(intent.spoiler_policy.value, "ALLOW")
        self.assertEqual(intent.max_results, 3)
        self.assertEqual(intent.focus_terms, ["romance", "Belly", "Conrad"])

    def test_explicit_female_audience_is_preserved_without_genre_stereotyping(self) -> None:
        intent = intent_from_query(
            "a good show for girls that'll get views on tiktok"
        )

        self.assertEqual(intent.media_kinds, [MediaKind.TV_EPISODE])
        self.assertEqual(intent.focus_terms, ["female-centered"])
        self.assertNotIn("romance", intent.focus_terms)

    def test_explicit_female_audience_cannot_pass_on_title_only_discussion(self) -> None:
        title = "Stuart Fails to Save the Universe"
        locator = EpisodeLocatorFactV2(
            show_or_title=title,
            season_number=1,
            episode_number=4,
            episode_title="Spoiler: Stuart Makes a Wallet",
        )
        metadata = EvidenceCandidate(
            provider="tvmaze",
            provider_record_id="404",
            source_type=EvidenceSourceType.METADATA,
            canonical_url="https://www.tvmaze.com/episodes/404/spoiler-stuart-makes-a-wallet",
            title=f"{title} — S01E04: Spoiler: Stuart Makes a Wallet",
            author_or_channel="TVmaze",
            excerpt_type=ExcerptType.PARAPHRASE,
            excerpt="TVmaze lists Spoiler: Stuart Makes a Wallet as Season 1 Episode 4.",
            verification=VerificationState.SECONDARY_CORROBORATED,
            claim_kind=EvidenceClaimKind.EPISODE_IDENTITY,
            supports_why_now=False,
            policy_class="tvmaze-metadata-v1",
            event_or_release_at=NOW - timedelta(hours=1),
            citation_verified=True,
            episode_locator=locator,
        )

        def discussion(*, host: str, slug: str, headline: str) -> EvidenceCandidate:
            url = f"https://{host}/{slug}"
            return EvidenceCandidate(
                provider="openai",
                provider_record_id=tvmaze_show_source_binding(title, url),
                source_type=EvidenceSourceType.ARTICLE,
                canonical_url=url,
                title=headline,
                author_or_channel=None,
                excerpt_type=ExcerptType.PARAPHRASE,
                excerpt=f"Current cited-source title: {headline}",
                verification=VerificationState.SECONDARY_CORROBORATED,
                claim_kind=EvidenceClaimKind.VIEWER_DISCUSSION,
                supports_why_now=True,
                policy_class="openai-web-evidence-v1",
                source_created_at=NOW - timedelta(hours=1),
                page_published_at=NOW - timedelta(hours=1),
                window_start=NOW - timedelta(days=3),
                window_end=NOW,
                citation_verified=True,
                content_binding_verified=True,
            )

        discussions = (
            discussion(
                host="tomsguide.com",
                slug="matrix-joke",
                headline="How much effort it took to pull off that Matrix joke",
            ),
            discussion(
                host="variety.com",
                slug="similar-shows",
                headline="Ten shows with similar ensemble comedy",
            ),
        )

        class SynthesisMustNotRun:
            name = "openai"

            def synthesize(self, *args, **kwargs):
                del args, kwargs
                raise AssertionError(
                    "unsupported audience evidence must fail before paid synthesis"
                )

        workflow = ResearchWorkflow(
            providers=[
                ProviderPlan(
                    FakeResearchProvider(
                        name="tvmaze",
                        operation="research.metadata",
                        batches=[ProviderBatch(provider="tvmaze", evidence=(metadata,))],
                    ),
                    _authorization("tvmaze", "research.metadata"),
                ),
                ProviderPlan(
                    FakeResearchProvider(
                        name="openai",
                        operation="research.web_verify",
                        batches=[ProviderBatch(provider="openai", evidence=discussions)],
                    ),
                    _authorization("openai", "research.web_verify"),
                ),
            ],
            synthesizer=SynthesisMustNotRun(),
            synthesis_authorization=_authorization("openai", "research.synthesize"),
            official_hosts=set(),
        )

        output = workflow.run(
            intent_from_query("a good show for girls that'll get views on tiktok"),
            generated_at=NOW,
            cancellation=CancellationToken(),
        )

        self.assertEqual(output.result.status.value, "NO_STRONG_OPPORTUNITY")
        self.assertEqual(output.result.opportunities, [])
        self.assertIsNone(output.synthesis)

    def test_female_audience_gate_fills_every_distinct_supported_title(self) -> None:
        def metadata(
            *, title: str, record_id: int, episode_number: int
        ) -> EvidenceCandidate:
            locator = EpisodeLocatorFactV2(
                show_or_title=title,
                season_number=1,
                episode_number=episode_number,
                episode_title="Turning Point",
            )
            return EvidenceCandidate(
                provider="tvmaze",
                provider_record_id=str(record_id),
                source_type=EvidenceSourceType.METADATA,
                canonical_url=(
                    f"https://www.tvmaze.com/episodes/{record_id}/turning-point"
                ),
                title=f"{title} — S01E{episode_number:02d}: Turning Point",
                author_or_channel="TVmaze",
                excerpt_type=ExcerptType.PARAPHRASE,
                excerpt=(
                    f"TVmaze lists Turning Point as Season 1 Episode {episode_number}."
                ),
                verification=VerificationState.SECONDARY_CORROBORATED,
                claim_kind=EvidenceClaimKind.EPISODE_IDENTITY,
                supports_why_now=False,
                policy_class="tvmaze-metadata-v1",
                event_or_release_at=NOW - timedelta(hours=episode_number),
                citation_verified=True,
                episode_locator=locator,
            )

        def discussion(
            *, title: str, host: str, slug: str
        ) -> EvidenceCandidate:
            url = f"https://{host}/{slug}"
            headline = (
                f"{title}: women at the center of a quiet family reconciliation"
                if host == "tomsguide.com"
                else f"{title} review weighs the female-led ensemble's abrupt career decision"
            )
            return EvidenceCandidate(
                provider="openai",
                provider_record_id=tvmaze_show_source_binding(title, url),
                source_type=EvidenceSourceType.ARTICLE,
                canonical_url=url,
                title=headline,
                author_or_channel=None,
                excerpt_type=ExcerptType.PARAPHRASE,
                excerpt=f"Current cited-source title: {headline}",
                verification=VerificationState.SECONDARY_CORROBORATED,
                claim_kind=EvidenceClaimKind.VIEWER_DISCUSSION,
                supports_why_now=True,
                policy_class="openai-web-evidence-v1",
                source_created_at=NOW - timedelta(hours=1),
                page_published_at=NOW - timedelta(hours=1),
                window_start=NOW - timedelta(days=3),
                window_end=NOW,
                citation_verified=True,
                content_binding_verified=True,
            )

        titles = ("First Current Show", "Second Current Show")
        metadata_rows = (
            metadata(title=titles[0], record_id=101, episode_number=1),
            metadata(title=titles[1], record_id=202, episode_number=2),
        )
        discussions = tuple(
            discussion(title=title, host=host, slug=f"{index}-{owner}")
            for index, title in enumerate(titles, start=1)
            for owner, host in (
                ("future", "tomsguide.com"),
                ("penske", "variety.com"),
            )
        )

        class EmptySynthesizer:
            name = "openai"

            def synthesize(self, *args, **kwargs):
                del args, kwargs
                return SynthesisProviderResult(
                    provider=self.name,
                    draft=ResearchSynthesisDraftV2(
                        recommendations=[],
                        no_strong_opportunity_reason="Provider omitted the eligible cards.",
                    ),
                )

        workflow = ResearchWorkflow(
            providers=[
                ProviderPlan(
                    FakeResearchProvider(
                        name="tvmaze",
                        operation="research.metadata",
                        batches=[
                            ProviderBatch(
                                provider="tvmaze", evidence=metadata_rows
                            )
                        ],
                    ),
                    _authorization("tvmaze", "research.metadata"),
                ),
                ProviderPlan(
                    FakeResearchProvider(
                        name="openai",
                        operation="research.web_verify",
                        batches=[
                            ProviderBatch(
                                provider="openai", evidence=discussions
                            )
                        ],
                    ),
                    _authorization("openai", "research.web_verify"),
                ),
            ],
            synthesizer=EmptySynthesizer(),
            synthesis_authorization=_authorization(
                "openai", "research.synthesize"
            ),
            official_hosts=set(),
        )

        output = workflow.run(
            intent_from_query("a good show for girls thatll get views on tiktok"),
            generated_at=NOW,
            cancellation=CancellationToken(),
        )

        self.assertEqual(
            output.result.status.value,
            "OPPORTUNITIES",
            (
                output.result.warnings,
                [
                    (source.title, source.independence_group)
                    for source in output.evidence_sources
                ],
                [
                    (claim.claim_kind.value, claim.text, claim.verification.value)
                    for claim in output.evidence_claims
                ],
            ),
        )
        self.assertEqual(
            {item.media_identity.show_or_title for item in output.result.opportunities},
            set(titles),
        )
        self.assertEqual(len(output.result.footage_requests), 2)
        self.assertTrue(
            any(
                "2 independently qualified distinct TV title" in warning
                for warning in output.result.warnings
            )
        )

    def test_verified_official_video_scene_label_becomes_clickable_optional_source(self) -> None:
        source = EvidenceSourceRecordV2(
            source_id=uuid4(),
            provider="youtube",
            provider_record_id="scene-link",
            source_type=EvidenceSourceType.OFFICIAL_CLIP,
            canonical_url="https://www.youtube.com/watch?v=scene-link",
            title="A Quiet Confession | Example Show | Official Studio",
            author_or_channel="Official Studio",
            source_created_at=NOW,
            page_published_at=NOW,
            retrieved_at=NOW,
            query="Example Show",
            policy_class="youtube-public-metadata-v1",
            content_sha256="3" * 64,
            independence_group="official:youtube-channel:studio",
        )
        claim = EvidenceClaimRecordV2(
            claim_id=uuid4(),
            source_id=source.source_id,
            claim_kind=EvidenceClaimKind.OFFICIAL_CLIP,
            excerpt_type=ExcerptType.PARAPHRASE,
            text="Official channel published a title-bound video.",
            verification=VerificationState.PRIMARY_VERIFIED,
            why_now_event=WhyNowEventFactV2(
                event_kind=WhyNowEventKind.OFFICIAL_CLIP_RELEASE,
                media_identity=MediaIdentityV2(
                    media_kind=MediaKind.OFFICIAL_CLIP,
                    show_or_title="Example Show",
                ),
            ),
            scene_fact=SceneMomentFactV2(
                show_or_title="Example Show",
                description="Official upload labeled “A Quiet Confession”",
                relationship_or_topic="A Quiet Confession",
            ),
            event_or_release_at=NOW,
            confidence=0.95,
            supports_why_now=True,
            content_sha256="4" * 64,
        )

        drafts = _official_video_source_drafts(
            "Example Show",
            [claim],
            source_by_id={source.source_id: source},
        )

        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0].asset_kind, SourceAcquisitionKind.OFFICIAL_CLIP)
        self.assertEqual(
            drafts[0].verification_level,
            FootageVerificationLevel.VERIFIED,
        )
        self.assertEqual(
            drafts[0].scene_or_moment,
            "Official upload labeled “A Quiet Confession”",
        )
        self.assertIsNone(drafts[0].relationship_or_topic)
        self.assertEqual(drafts[0].supporting_claim_ids, [claim.claim_id])

        required = RequestedSourceDraftV2(
            source_key="scene_pack",
            priority=1,
            acquisition_effort=2,
            asset_kind=SourceAcquisitionKind.SCENE_PACK,
            show_or_title="Example Show",
            characters=[],
            relationship_or_topic="current character discussion",
            scene_or_moment=(
                "Any relevant current character discussion material; the exact scene is unknown."
            ),
            purposes=[SourcePurpose.INTRO, SourcePurpose.MONTAGE],
            verification_level=FootageVerificationLevel.UNKNOWN,
            source_quality_summary="The exact scene is unverified.",
            supporting_claim_ids=[],
            why_it_matters_emotionally="This is an inspection target.",
            search_queries=["Example Show character scene pack"],
        )
        footage = FootageRequestDraftV2(
            summary="A compact scene-pack request.",
            natural_request=NaturalFootageRequestV2(
                best="Give me an Example Show scene pack.",
                minimum="One focused scene pack is enough.",
            ),
            required_sources=[required],
            minimum_useful_source_keys=[required.source_key],
            smallest_useful_set_reason="One focused pack is sufficient.",
            search_queries=["Example Show character scene pack"],
        )
        enriched = _attach_official_video_sources(
            footage,
            show_or_title="Example Show",
            claims=[claim],
            source_by_id={source.source_id: source},
        )
        self.assertEqual(len(enriched.optional_sources), 1)
        self.assertEqual(
            enriched.optional_sources[0].source_key,
            "host_official_video_1",
        )
        self.assertIsNotNone(enriched.natural_request.optional_improvement)
        canonical = canonicalize_footage_request(
            draft=enriched,
            footage_request_id=uuid4(),
            opportunity_id=uuid4(),
            evidence_index=EvidenceIndex.build([source], [claim]),
            allowed_claim_ids={claim.claim_id},
        )
        self.assertEqual(
            canonical.optional_sources[0].search_queries,
            [
                'Example Show "A Quiet Confession" official clip',
                "Example Show official clip",
            ],
        )

    def test_exclusion_aliases_are_punctuation_and_metadata_aware(self) -> None:
        intent = intent_from_query("romance TV, no K-drama, no reality TV")
        self.assertTrue(violates_exclusions("K‑drama romance", intent))
        self.assertTrue(violates_exclusions("Korean drama", intent))
        self.assertTrue(violates_exclusions("reality television series", intent))
        self.assertFalse(violates_exclusions("US scripted romance", intent))

    def test_cache_key_rejects_non_hex_and_uppercase_sha(self) -> None:
        kwargs = dict(
            provider="fake",
            resolved_model="fake-1",
            operation="research",
            prompt_version="1",
            schema_version="2",
            normalized_parameters={},
            freshness_bucket="2026-08-15",
            privacy_mode="offline",
        )
        with self.assertRaises(ValueError):
            research_cache_key(input_content_sha256="z" * 64, **kwargs)
        with self.assertRaises(ValueError):
            research_cache_key(input_content_sha256="A" * 64, **kwargs)

    def test_multi_source_priorities_minimum_and_alternatives_are_unambiguous(self) -> None:
        support = uuid4()
        first = _requested_source(
            source_key="first", priority=1, supporting_claim_ids=[support]
        )
        second = _requested_source(
            source_key="second",
            priority=2,
            season_number=2,
            episode_number=4,
            supporting_claim_ids=[support],
        )
        scene_pack = _requested_source(
            source_key="scene_pack",
            priority=1,
            acquisition_effort=1,
            asset_kind=SourceAcquisitionKind.SCENE_PACK,
            season_number=None,
            episode_number=None,
            episode_title=None,
            replaces_required_source_keys=["first", "second"],
            supporting_claim_ids=[support],
        )
        request = _request(
            first,
            required_sources=[first, second],
            alternative_sources=[scene_pack],
            natural_request=NaturalFootageRequestV2(
                best="Give me both episodes.",
                alternative="A scene pack can replace both episodes.",
                minimum="Both episodes are the minimum.",
            ),
            minimum_useful_source_keys=["first", "second"],
        )
        self.assertEqual(request.alternative_sources[0].acquisition_effort, 1)
        bad = scene_pack.model_copy(update={"replaces_required_source_keys": ["first"]})
        with self.assertRaises(ValidationError):
            _request(
                first,
                required_sources=[first, second],
                alternative_sources=[bad],
                natural_request=request.natural_request,
                minimum_useful_source_keys=["first", "second"],
            )

    def test_unknown_source_copy_is_broad_and_drops_unbound_locator_searches(self) -> None:
        source = _requested_source(
            source_key="unknown_pack",
            asset_kind=SourceAcquisitionKind.SCENE_PACK,
            season_number=None,
            episode_number=None,
            episode_title=None,
            verification_level=FootageVerificationLevel.UNKNOWN,
            supporting_claim_ids=[],
            scene_or_moment="The Season 9 beach confession definitely happens here.",
            search_queries=["Example Show S9E99 beach confession quote"],
        )
        rendered = canonicalize_footage_request(
            draft=_request(
                source,
                minimum_useful_source_keys=["unknown_pack"],
                search_queries=["Example Show S9E99 beach confession quote"],
            ),
            footage_request_id=uuid4(),
            opportunity_id=uuid4(),
            evidence_index=EvidenceIndex.build([], []),
            allowed_claim_ids=set(),
        )
        serialized = json.dumps(rendered.model_dump(mode="json"))
        self.assertIn("exact scene is unknown", rendered.required_sources[0].scene_or_moment)
        self.assertNotIn("S9E99", serialized)
        self.assertNotIn("confession", serialized)

    def test_exact_episode_number_cannot_be_inferred_from_same_show(self) -> None:
        source_record = _source()
        episode_claim = _claim(source_record)
        scene_claim = _claim(
            source_record,
            claim_id=uuid4(),
            claim_kind=EvidenceClaimKind.SCENE_CONTEXT,
            episode_locator=None,
            text="A admits the relationship changed.",
            scene_fact=SceneMomentFactV2(
                show_or_title="Example Show",
                description="A admits the relationship changed.",
                characters=["A", "B"],
                relationship_or_topic="A and B",
                episode_locator=EpisodeLocatorFactV2(
                    show_or_title="Example Show",
                    season_number=1,
                    episode_number=2,
                    episode_title="Turning Point",
                ),
            ),
            content_sha256="3" * 64,
        )
        index = EvidenceIndex.build([source_record], [episode_claim, scene_claim])
        requested = _requested_source(
            season_number=9,
            episode_number=9,
            episode_title=None,
            supporting_claim_ids=[episode_claim.claim_id, scene_claim.claim_id],
        )
        with self.assertRaisesRegex(ValueError, "exact episode locator"):
            canonicalize_footage_request(
                draft=_request(requested),
                footage_request_id=uuid4(),
                opportunity_id=uuid4(),
                evidence_index=index,
                allowed_claim_ids={episode_claim.claim_id, scene_claim.claim_id},
            )

    def test_exact_episode_moment_cannot_use_unlocated_show_discussion(self) -> None:
        source_record = _source()
        episode = _claim(source_record)
        discussion = _claim(
            source_record,
            claim_id=uuid4(),
            claim_kind=EvidenceClaimKind.VIEWER_DISCUSSION,
            episode_locator=None,
            excerpt_type=ExcerptType.PARAPHRASE,
            text="A admits the relationship changed.",
            verification=VerificationState.SECONDARY_CORROBORATED,
            content_sha256="a" * 64,
        )
        requested = _requested_source(
            supporting_claim_ids=[episode.claim_id, discussion.claim_id]
        )
        with self.assertRaisesRegex(ValueError, "moment evidence"):
            canonicalize_footage_request(
                draft=_request(requested),
                footage_request_id=uuid4(),
                opportunity_id=uuid4(),
                evidence_index=EvidenceIndex.build(
                    [source_record], [episode, discussion]
                ),
                allowed_claim_ids={episode.claim_id, discussion.claim_id},
            )

    def test_unlocated_quote_lead_cannot_attach_to_exact_episode(self) -> None:
        source_record = _source()
        episode = _claim(source_record)
        scene = _claim(
            source_record,
            claim_id=uuid4(),
            claim_kind=EvidenceClaimKind.SCENE_CONTEXT,
            episode_locator=None,
            text="A admits the relationship changed.",
            scene_fact=SceneMomentFactV2(
                show_or_title="Example Show",
                description="A admits the relationship changed.",
                characters=["A", "B"],
                relationship_or_topic="A and B",
                episode_locator=episode.episode_locator,
            ),
            content_sha256="b" * 64,
        )
        quote_lead = _claim(
            source_record,
            claim_id=uuid4(),
            claim_kind=EvidenceClaimKind.VIEWER_DISCUSSION,
            episode_locator=None,
            excerpt_type=ExcerptType.UNVERIFIED_QUOTE_LEAD,
            text="I still choose you",
            verification=VerificationState.LEAD_ONLY,
            content_sha256="c" * 64,
        )
        requested = _requested_source(
            supporting_claim_ids=[
                episode.claim_id,
                scene.claim_id,
                quote_lead.claim_id,
            ],
            quote=FootageQuoteV2(
                status=FootageQuoteStatus.UNVERIFIED_LEAD,
                text=quote_lead.text,
                claim_id=quote_lead.claim_id,
            ),
        )
        with self.assertRaisesRegex(ValueError, "not bound to the requested episode"):
            canonicalize_footage_request(
                draft=_request(requested),
                footage_request_id=uuid4(),
                opportunity_id=uuid4(),
                evidence_index=EvidenceIndex.build(
                    [source_record], [episode, scene, quote_lead]
                ),
                allowed_claim_ids={episode.claim_id, scene.claim_id, quote_lead.claim_id},
            )

    def test_unlocated_discussion_cannot_place_intro_in_exact_episode(self) -> None:
        source_record = _source()
        episode = _claim(source_record)
        scene = _claim(
            source_record,
            claim_id=uuid4(),
            claim_kind=EvidenceClaimKind.SCENE_CONTEXT,
            episode_locator=None,
            text="A admits the relationship changed.",
            scene_fact=SceneMomentFactV2(
                show_or_title="Example Show",
                description="A admits the relationship changed.",
                characters=["A", "B"],
                relationship_or_topic="A and B",
                episode_locator=episode.episode_locator,
            ),
            content_sha256="d" * 64,
        )
        discussion = _claim(
            source_record,
            claim_id=uuid4(),
            claim_kind=EvidenceClaimKind.VIEWER_DISCUSSION,
            episode_locator=None,
            excerpt_type=ExcerptType.PARAPHRASE,
            text="A looks back before the montage.",
            verification=VerificationState.SECONDARY_CORROBORATED,
            content_sha256="e" * 64,
        )
        requested = _requested_source(
            supporting_claim_ids=[episode.claim_id, scene.claim_id]
        )
        draft = _request(
            requested,
            intro_leads=[
                IntroMaterialLeadDraftV2(
                    source_key=requested.source_key,
                    moment_description=discussion.text,
                    why_it_might_lead_into_montage=(
                        "The pause could create a clean emotional handoff."
                    ),
                    verification_level=FootageVerificationLevel.LIKELY_INFERRED,
                    supporting_claim_ids=[discussion.claim_id],
                )
            ],
        )
        with self.assertRaisesRegex(ValueError, "intro lead needs matching moment evidence"):
            canonicalize_footage_request(
                draft=draft,
                footage_request_id=uuid4(),
                opportunity_id=uuid4(),
                evidence_index=EvidenceIndex.build(
                    [source_record], [episode, scene, discussion]
                ),
                allowed_claim_ids={episode.claim_id, scene.claim_id, discussion.claim_id},
            )

    def test_model_authored_source_and_intro_rationales_are_replaced(self) -> None:
        source_record = _source()
        episode = _claim(source_record)
        scene = _claim(
            source_record,
            claim_id=uuid4(),
            claim_kind=EvidenceClaimKind.SCENE_CONTEXT,
            episode_locator=None,
            text="A admits the relationship changed.",
            scene_fact=SceneMomentFactV2(
                show_or_title="Example Show",
                description="A admits the relationship changed.",
                characters=["A", "B"],
                relationship_or_topic="A and B",
                episode_locator=episode.episode_locator,
            ),
            content_sha256="f" * 64,
        )
        requested = _requested_source(
            supporting_claim_ids=[episode.claim_id, scene.claim_id],
            why_it_matters_emotionally=(
                'S9E99 proves a beach confession and the quote "never leave me".'
            ),
        )
        rendered = canonicalize_footage_request(
            draft=_request(
                requested,
                intro_leads=[
                    IntroMaterialLeadDraftV2(
                        source_key=requested.source_key,
                        moment_description=scene.text,
                        why_it_might_lead_into_montage=(
                            'The S9E99 beach kiss proves "never leave me" is the final intro.'
                        ),
                        verification_level=FootageVerificationLevel.LIKELY_INFERRED,
                        supporting_claim_ids=[scene.claim_id],
                    )
                ],
            ),
            footage_request_id=uuid4(),
            opportunity_id=uuid4(),
            evidence_index=EvidenceIndex.build([source_record], [episode, scene]),
            allowed_claim_ids={episode.claim_id, scene.claim_id},
        )
        self.assertEqual(
            rendered.required_sources[0].why_it_matters_emotionally,
            "Evidence links this source to the intro and montage roles for A and B "
            "through this inspection target: A admits the relationship changed. "
            "Supplied local footage must confirm its emotional value before editing.",
        )
        self.assertEqual(
            rendered.intro_leads[0].why_it_might_lead_into_montage,
            "This evidence-bound lead could provide context for A and B before the montage: "
            "A admits the relationship changed. Supplied local footage must confirm the timing "
            "and emotional handoff.",
        )
        rationale_copy = (
            rendered.required_sources[0].why_it_matters_emotionally
            + rendered.intro_leads[0].why_it_might_lead_into_montage
        )
        self.assertNotIn("S9E99", rationale_copy)
        self.assertNotIn("beach", rationale_copy.casefold())
        self.assertNotIn("never leave me", rationale_copy.casefold())

    def test_unverified_quote_must_match_bound_lead_evidence(self) -> None:
        source_record = _source()
        lead = _claim(
            source_record,
            claim_kind=EvidenceClaimKind.VIEWER_DISCUSSION,
            episode_locator=None,
            excerpt_type=ExcerptType.UNVERIFIED_QUOTE_LEAD,
            text="Example Show fans repeat: I still choose you",
            verification=VerificationState.LEAD_ONLY,
            content_sha256="4" * 64,
        )
        scene = _claim(
            source_record,
            claim_id=uuid4(),
            claim_kind=EvidenceClaimKind.SCENE_CONTEXT,
            episode_locator=None,
            text="A admits the relationship changed.",
            scene_fact=SceneMomentFactV2(
                show_or_title="Example Show",
                description="A admits the relationship changed.",
                characters=["A", "B"],
                relationship_or_topic="A and B",
                episode_locator=EpisodeLocatorFactV2(
                    show_or_title="Example Show",
                    season_number=1,
                    episode_number=2,
                    episode_title="Turning Point",
                ),
            ),
            content_sha256="5" * 64,
        )
        index = EvidenceIndex.build([source_record], [lead, scene])
        episode = _claim(source_record, claim_id=uuid4(), content_sha256="6" * 64)
        index = EvidenceIndex.build([source_record], [lead, scene, episode])
        requested = _requested_source(
            supporting_claim_ids=[lead.claim_id, scene.claim_id, episode.claim_id],
            quote=FootageQuoteV2(
                status=FootageQuoteStatus.UNVERIFIED_LEAD,
                text="invented different dialogue",
                claim_id=lead.claim_id,
            ),
        )
        with self.assertRaisesRegex(ValueError, "exactly match"):
            canonicalize_footage_request(
                draft=_request(requested),
                footage_request_id=uuid4(),
                opportunity_id=uuid4(),
                evidence_index=index,
                allowed_claim_ids={lead.claim_id, scene.claim_id, episode.claim_id},
            )

    def test_stale_scene_cannot_support_inferred_requested_moment(self) -> None:
        source_record = _source()
        episode = _claim(source_record)
        stale_scene = _claim(
            source_record,
            claim_id=uuid4(),
            claim_kind=EvidenceClaimKind.SCENE_CONTEXT,
            excerpt_type=ExcerptType.PARAPHRASE,
            text="A admits the relationship changed.",
            verification=VerificationState.STALE,
            episode_locator=None,
            scene_fact=SceneMomentFactV2(
                show_or_title="Example Show",
                description="A admits the relationship changed.",
                characters=["A", "B"],
                relationship_or_topic="A and B",
                episode_locator=episode.episode_locator,
            ),
            content_sha256="7" * 64,
        )
        requested = _requested_source(
            supporting_claim_ids=[episode.claim_id, stale_scene.claim_id]
        )
        with self.assertRaisesRegex(ValueError, "moment evidence"):
            canonicalize_footage_request(
                draft=_request(requested),
                footage_request_id=uuid4(),
                opportunity_id=uuid4(),
                evidence_index=EvidenceIndex.build(
                    [source_record], [episode, stale_scene]
                ),
                allowed_claim_ids={episode.claim_id, stale_scene.claim_id},
            )

    def test_stale_scene_cannot_support_inferred_intro_lead(self) -> None:
        source_record = _source()
        episode = _claim(source_record)
        fresh_scene = _claim(
            source_record,
            claim_id=uuid4(),
            claim_kind=EvidenceClaimKind.SCENE_CONTEXT,
            excerpt_type=ExcerptType.PARAPHRASE,
            text="A admits the relationship changed.",
            verification=VerificationState.SECONDARY_CORROBORATED,
            episode_locator=None,
            scene_fact=SceneMomentFactV2(
                show_or_title="Example Show",
                description="A admits the relationship changed.",
                characters=["A", "B"],
                relationship_or_topic="A and B",
                episode_locator=episode.episode_locator,
            ),
            content_sha256="8" * 64,
        )
        stale_intro = _claim(
            source_record,
            claim_id=uuid4(),
            claim_kind=EvidenceClaimKind.SCENE_CONTEXT,
            excerpt_type=ExcerptType.PARAPHRASE,
            text="A silently looks back before the montage.",
            verification=VerificationState.RETRACTED,
            episode_locator=None,
            scene_fact=SceneMomentFactV2(
                show_or_title="Example Show",
                description="A silently looks back before the montage.",
                characters=["A", "B"],
                relationship_or_topic="A and B",
                episode_locator=episode.episode_locator,
            ),
            content_sha256="9" * 64,
        )
        requested = _requested_source(
            supporting_claim_ids=[episode.claim_id, fresh_scene.claim_id]
        )
        request = _request(
            requested,
            intro_leads=[
                IntroMaterialLeadDraftV2(
                    source_key=requested.source_key,
                    moment_description="A silently looks back before the montage.",
                    why_it_might_lead_into_montage="It could provide a restrained handoff.",
                    verification_level=FootageVerificationLevel.LIKELY_INFERRED,
                    supporting_claim_ids=[stale_intro.claim_id],
                )
            ],
        )
        with self.assertRaisesRegex(ValueError, "intro lead needs matching"):
            canonicalize_footage_request(
                draft=request,
                footage_request_id=uuid4(),
                opportunity_id=uuid4(),
                evidence_index=EvidenceIndex.build(
                    [source_record], [episode, fresh_scene, stale_intro]
                ),
                allowed_claim_ids={
                    episode.claim_id,
                    fresh_scene.claim_id,
                    stale_intro.claim_id,
                },
            )

    def test_copied_discussion_sources_collapse_to_one_independence_group(self) -> None:
        excerpt = "Viewers are discussing the same emotional reversal in the newly released trailer."
        candidates = []
        for host in ("variety.com", "thewrap.com"):
            candidates.append(
                EvidenceCandidate(
                    provider="openai",
                    provider_record_id=None,
                    source_type=EvidenceSourceType.ARTICLE,
                    canonical_url=f"https://{host}/story",
                    title="Example Film discussion",
                    author_or_channel=host,
                    excerpt_type=ExcerptType.PARAPHRASE,
                    excerpt=excerpt,
                    verification=VerificationState.SECONDARY_CORROBORATED,
                    claim_kind=EvidenceClaimKind.VIEWER_DISCUSSION,
                    supports_why_now=True,
                    policy_class="openai-web-evidence-v1",
                    source_created_at=NOW,
                    page_published_at=NOW,
                    window_start=NOW - timedelta(days=3),
                    window_end=NOW,
                    citation_verified=True,
                )
            )
        sources, _ = normalize_batches(
            [ProviderBatch(provider="openai", evidence=tuple(candidates))],
            retrieved_at=NOW,
            official_hosts=set(),
        )
        self.assertEqual(len({item.independence_group for item in sources}), 1)
        self.assertTrue(sources[0].independence_group.startswith("copy-cluster:"))

    def test_official_trailer_and_two_independent_signals_pass_workflow(self) -> None:
        primary = EvidenceCandidate(
            provider="youtube",
            provider_record_id="video1",
            source_type=EvidenceSourceType.OFFICIAL_CLIP,
            canonical_url="https://www.youtube.com/watch?v=video1",
            title="Example Film | Official Trailer",
            author_or_channel="Official Studio",
            excerpt_type=ExcerptType.PARAPHRASE,
            excerpt="Official channel Official Studio published Example Film | Official Trailer.",
            verification=VerificationState.PRIMARY_VERIFIED,
            claim_kind=EvidenceClaimKind.OFFICIAL_CLIP,
            supports_why_now=True,
            policy_class="youtube-public-metadata-v1",
            source_created_at=NOW - timedelta(hours=2),
            page_published_at=NOW - timedelta(hours=2),
            event_or_release_at=NOW - timedelta(hours=2),
            window_start=NOW - timedelta(days=3),
            window_end=NOW,
            adapter_origin_id="youtube-channel:studio",
            citation_verified=True,
            why_now_event=WhyNowEventFactV2(
                event_kind=WhyNowEventKind.TRAILER_RELEASE,
                media_identity=MediaIdentityV2(
                    media_kind=MediaKind.TRAILER, show_or_title="Example Film"
                ),
            ),
        )
        discussion_texts = {
            "variety.com": "Example Film turns a quiet promise into the trailer's emotional hook.",
            "thewrap.com": "Example Film viewers are focused on the relationship reversal and payoff.",
        }
        signals = tuple(
            EvidenceCandidate(
                provider="openai",
                provider_record_id=f"story-{host}",
                source_type=EvidenceSourceType.ARTICLE,
                canonical_url=f"https://{host}/example-film-story",
                title=f"Example Film discussion at {host}",
                author_or_channel=host,
                excerpt_type=ExcerptType.PARAPHRASE,
                excerpt=discussion_texts[host],
                verification=VerificationState.SECONDARY_CORROBORATED,
                claim_kind=EvidenceClaimKind.VIEWER_DISCUSSION,
                supports_why_now=True,
                policy_class="openai-web-evidence-v1",
                source_created_at=NOW - timedelta(hours=1),
                page_published_at=NOW - timedelta(hours=1),
                window_start=NOW - timedelta(days=3),
                window_end=NOW,
                citation_verified=True,
                content_binding_verified=True,
            )
            for host in ("variety.com", "thewrap.com")
        )
        youtube_batch = ProviderBatch(provider="youtube", evidence=(primary,))
        web_batch = ProviderBatch(provider="openai", evidence=signals)
        intent = intent_from_query("Find one current official film trailer opportunity")
        provider_plans = [
            ProviderPlan(
                FakeResearchProvider(
                    name="youtube", operation="research.youtube", batches=[youtube_batch]
                ),
                _authorization("youtube", "research.youtube"),
            ),
            ProviderPlan(
                FakeResearchProvider(
                    name="openai", operation="research.web_verify", batches=[web_batch]
                ),
                _authorization("openai", "research.web_verify"),
            ),
        ]
        workflow = ResearchWorkflow(
            providers=provider_plans,
            synthesizer=_DynamicTrailerSynthesizer(),
            synthesis_authorization=_authorization("openai", "research.synthesize"),
            official_hosts=set(),
        )
        output = workflow.run(intent, generated_at=NOW, cancellation=CancellationToken())
        self.assertEqual(
            output.result.status.value,
            "OPPORTUNITIES",
            msg=str(
                [
                    (
                        claim.claim_kind.value,
                        claim.verification.value,
                        claim.supports_why_now,
                        next(
                            source.independence_group
                            for source in output.evidence_sources
                            if source.source_id == claim.source_id
                        ),
                    )
                    for claim in output.evidence_claims
                ]
            ),
        )
        self.assertEqual(len(output.result.opportunities), 1)
        requested = output.result.footage_requests[0].required_sources[0]
        self.assertEqual(requested.source_quality_summary, (
            "Likely or inferred from relevant evidence; the exact moment is not verified."
        ))
        opportunity = output.result.opportunities[0]
        self.assertEqual(opportunity.evidence_gate, EvidenceGate.PASSED)
        self.assertEqual(opportunity.title, "Example Film: central relationship")
        self.assertNotIn("Open on", opportunity.creative_hook)

    def test_live_camp_rock_shape_uses_bound_discussions_and_safe_film_fallback(self) -> None:
        """Regress the 2026-08-17 packaged film synthesis rejection.

        The current publisher pages were directly bound to Camp Rock 3, but one
        localized headline omitted the sequel number and the other was a
        list-style headline.  The old footage validator ignored the opaque
        binding, and a rejected inferred moment then erased an otherwise passed
        three-owner evidence gate.
        """

        official_url = "https://press.disneyplus.com/news/next-on-disney-plus-august-2026"
        primary = EvidenceCandidate(
            provider="openai",
            provider_record_id=None,
            source_type=EvidenceSourceType.PRIMARY_RELEASE,
            canonical_url=official_url,
            title="Next on Disney+ and Hulu: August 2026 | Disney+ Press",
            author_or_channel="Disney+ Press",
            excerpt_type=ExcerptType.PARAPHRASE,
            excerpt="Official page identifies Camp Rock 3 with a film release dated 2026-08-14.",
            verification=VerificationState.PRIMARY_VERIFIED,
            claim_kind=EvidenceClaimKind.WHY_NOW,
            supports_why_now=True,
            policy_class="openai-web-evidence-v1",
            source_created_at=NOW - timedelta(days=30),
            page_published_at=NOW - timedelta(days=30),
            event_or_release_at=NOW - timedelta(days=1),
            window_start=NOW - timedelta(days=14),
            window_end=NOW,
            citation_verified=True,
            content_binding_verified=True,
            why_now_event=WhyNowEventFactV2(
                event_kind=WhyNowEventKind.FILM_RELEASE,
                media_identity=MediaIdentityV2(
                    media_kind=MediaKind.FILM,
                    show_or_title="Camp Rock 3",
                ),
            ),
        )
        discussion_rows = (
            (
                "https://los40.com/2026/08/14/camp-rock-saga-current-release/",
                "Así es la cronología completa de la saga de 'Camp Rock' en Disney: del primer fenómeno a la actual entrega nostálgica | Series | LOS40",
            ),
            (
                "https://www.tomsguide.com/entertainment/streaming/5-best-new-movies-to-stream-this-weekend-august-15-16",
                "5 best new movies to stream this weekend on Netflix, Disney+, Hulu, and more (August 15-16)",
            ),
        )
        signals = tuple(
            EvidenceCandidate(
                provider="openai",
                provider_record_id=media_title_source_binding("Camp Rock 3", url),
                source_type=EvidenceSourceType.ARTICLE,
                canonical_url=url,
                title=title,
                author_or_channel=None,
                excerpt_type=ExcerptType.PARAPHRASE,
                excerpt=f"Current cited-source title: {title}",
                verification=VerificationState.SECONDARY_CORROBORATED,
                claim_kind=EvidenceClaimKind.VIEWER_DISCUSSION,
                supports_why_now=True,
                policy_class="openai-web-evidence-v1",
                source_created_at=NOW - timedelta(hours=12),
                page_published_at=NOW - timedelta(hours=12),
                window_start=NOW - timedelta(days=14),
                window_end=NOW,
                citation_verified=True,
                content_binding_verified=True,
            )
            for url, title in discussion_rows
        )

        class LiveShapeRejectedSynthesizer:
            name = "openai"

            def synthesize(
                self,
                intent,
                *,
                evidence_sources,
                evidence_claims,
                authorization,
                cancellation,
            ):
                del intent, evidence_sources, authorization
                cancellation.raise_if_cancelled()
                identity_claim = next(
                    claim
                    for claim in evidence_claims
                    if claim.claim_kind is EvidenceClaimKind.WHY_NOW
                )
                discussion_claims = [
                    claim
                    for claim in evidence_claims
                    if claim.claim_kind is EvidenceClaimKind.VIEWER_DISCUSSION
                ]
                requested = RequestedSourceDraftV2(
                    source_key="nostalgia_pack",
                    priority=1,
                    acquisition_effort=2,
                    asset_kind=SourceAcquisitionKind.SCENE_PACK,
                    show_or_title="Camp Rock 3",
                    characters=[],
                    relationship_or_topic="current release discussion",
                    scene_or_moment="A nostalgic reunion callback not stated by the evidence.",
                    purposes=[SourcePurpose.INTRO, SourcePurpose.MONTAGE, SourcePurpose.PAYOFF],
                    verification_level=FootageVerificationLevel.LIKELY_INFERRED,
                    source_quality_summary="Untrusted model copy.",
                    supporting_claim_ids=[
                        identity_claim.claim_id,
                        *[claim.claim_id for claim in discussion_claims],
                    ],
                    quote=None,
                    why_it_matters_emotionally="Untrusted model rationale.",
                    search_queries=["Camp Rock 3 current release scene pack"],
                )
                footage = _request(
                    requested,
                    natural_request=NaturalFootageRequestV2(
                        best="Give me a Camp Rock 3 scene pack.",
                        minimum="One focused scene pack is enough.",
                    ),
                    minimum_useful_source_keys=[requested.source_key],
                    search_queries=["Camp Rock 3 current release scene pack"],
                )
                opportunity = TrendOpportunityDraftV2(
                    media_kind=MediaKind.FILM,
                    media_identity=MediaIdentityV2(
                        media_kind=MediaKind.FILM,
                        show_or_title="Camp Rock 3",
                    ),
                    title="Camp Rock 3 current release discussion",
                    focus=OpportunityFocus(
                        characters=[], relationship_or_topic="current release discussion"
                    ),
                    why_now=identity_claim.text,
                    what_viewers_are_discussing="; ".join(
                        claim.text for claim in discussion_claims
                    ),
                    creative_hook="Untrusted model hook.",
                    emotional_edit_direction="Untrusted model direction.",
                    evidence=[
                        OpportunityEvidenceSelectionV2(
                            claim_id=identity_claim.claim_id,
                            role=EvidenceRole.PRIMARY_WHY_NOW,
                            supports_why_now=True,
                        ),
                        *[
                            OpportunityEvidenceSelectionV2(
                                claim_id=claim.claim_id,
                                role=EvidenceRole.QUALITATIVE_SIGNAL,
                                supports_why_now=True,
                            )
                            for claim in discussion_claims
                        ],
                    ],
                    confidence=0.75,
                )
                return SynthesisProviderResult(
                    provider=self.name,
                    draft=ResearchSynthesisDraftV2(
                        recommendations=[
                            SynthesisRecommendationDraftV2(
                                opportunity=opportunity,
                                footage_request=footage,
                            )
                        ]
                    ),
                )

        workflow = ResearchWorkflow(
            providers=[
                ProviderPlan(
                    FakeResearchProvider(
                        name="openai",
                        operation="research.web_verify",
                        batches=[ProviderBatch(provider="openai", evidence=(primary, *signals))],
                    ),
                    _authorization("openai", "research.web_verify"),
                )
            ],
            synthesizer=LiveShapeRejectedSynthesizer(),
            synthesis_authorization=_authorization("openai", "research.synthesize"),
            official_hosts={"disneyplus.com"},
        )
        output = workflow.run(
            intent_from_query("new movie or trailer"),
            generated_at=NOW,
            cancellation=CancellationToken(),
        )

        self.assertEqual(output.result.status.value, "OPPORTUNITIES")
        opportunity = output.result.opportunities[0]
        self.assertEqual(opportunity.media_identity.show_or_title, "Camp Rock 3")
        self.assertEqual(opportunity.evidence_gate, EvidenceGate.PASSED)
        self.assertEqual(opportunity.score.independent_source_count, 3)
        request = output.result.footage_requests[0]
        self.assertEqual(
            request.required_sources[0].verification_level,
            FootageVerificationLevel.UNKNOWN,
        )
        self.assertTrue(request.optional_sources)
        self.assertTrue(request.alternative_sources)
        self.assertTrue(request.search_queries)
        self.assertIn("smallest useful set", request.natural_request.minimum)
        warnings = " ".join(output.result.warnings)
        self.assertIn("footage:inferred-source-support=1", warnings)
        self.assertIn("passed-gate film/trailer scene-pack fallback", warnings)
        self.assertNotIn("nostalgic reunion callback", output.result.model_dump_json().casefold())

        source_by_id = {source.source_id: source for source in output.evidence_sources}
        identity_record = next(
            claim
            for claim in output.evidence_claims
            if claim.claim_kind is EvidenceClaimKind.WHY_NOW
        )
        list_page_signal = next(
            claim
            for claim in output.evidence_claims
            if claim.claim_kind is EvidenceClaimKind.VIEWER_DISCUSSION
            and "tomsguide.com" in str(source_by_id[claim.source_id].canonical_url)
        )
        bound_source = RequestedSourceDraftV2(
            source_key="bound_list_page_pack",
            priority=1,
            acquisition_effort=2,
            asset_kind=SourceAcquisitionKind.SCENE_PACK,
            show_or_title="Camp Rock 3",
            characters=[],
            relationship_or_topic="current release discussion",
            scene_or_moment=list_page_signal.text,
            purposes=[SourcePurpose.INTRO, SourcePurpose.MONTAGE],
            verification_level=FootageVerificationLevel.LIKELY_INFERRED,
            source_quality_summary="Untrusted model copy.",
            supporting_claim_ids=[identity_record.claim_id, list_page_signal.claim_id],
            quote=None,
            why_it_matters_emotionally="Untrusted model rationale.",
            search_queries=["Camp Rock 3 current release scene pack"],
        )
        canonical_bound = canonicalize_footage_request(
            draft=_request(
                bound_source,
                minimum_useful_source_keys=[bound_source.source_key],
                search_queries=["Camp Rock 3 current release scene pack"],
            ),
            footage_request_id=uuid4(),
            opportunity_id=uuid4(),
            evidence_index=EvidenceIndex.build(
                list(output.evidence_sources), list(output.evidence_claims)
            ),
            allowed_claim_ids={
                identity_record.claim_id,
                list_page_signal.claim_id,
            },
        )
        self.assertEqual(
            canonical_bound.required_sources[0].verification_level,
            FootageVerificationLevel.LIKELY_INFERRED,
        )

    def test_one_primary_and_one_independent_signal_is_explicitly_low_confidence(self) -> None:
        primary = EvidenceCandidate(
            provider="youtube",
            provider_record_id="video-low",
            source_type=EvidenceSourceType.OFFICIAL_CLIP,
            canonical_url="https://www.youtube.com/watch?v=video-low",
            title="Example Film | Official Trailer",
            author_or_channel="Official Studio",
            excerpt_type=ExcerptType.PARAPHRASE,
            excerpt="Official channel published Example Film | Official Trailer.",
            verification=VerificationState.PRIMARY_VERIFIED,
            claim_kind=EvidenceClaimKind.OFFICIAL_CLIP,
            supports_why_now=True,
            policy_class="youtube-public-metadata-v1",
            source_created_at=NOW - timedelta(hours=2),
            page_published_at=NOW - timedelta(hours=2),
            event_or_release_at=NOW - timedelta(hours=2),
            window_start=NOW - timedelta(days=3),
            window_end=NOW,
            adapter_origin_id="youtube-channel:studio",
            citation_verified=True,
            why_now_event=WhyNowEventFactV2(
                event_kind=WhyNowEventKind.TRAILER_RELEASE,
                media_identity=MediaIdentityV2(
                    media_kind=MediaKind.TRAILER, show_or_title="Example Film"
                ),
            ),
        )
        signal = EvidenceCandidate(
            provider="openai",
            provider_record_id="story-low",
            source_type=EvidenceSourceType.ARTICLE,
            canonical_url="https://thewrap.com/example-film-low",
            title="Example Film central relationship discussion",
            author_or_channel="thewrap.com",
            excerpt_type=ExcerptType.PARAPHRASE,
            excerpt="Example Film viewers are discussing the central relationship payoff.",
            verification=VerificationState.SECONDARY_CORROBORATED,
            claim_kind=EvidenceClaimKind.VIEWER_DISCUSSION,
            supports_why_now=True,
            policy_class="openai-web-evidence-v1",
            source_created_at=NOW - timedelta(hours=1),
            page_published_at=NOW - timedelta(hours=1),
            window_start=NOW - timedelta(days=3),
            window_end=NOW,
            citation_verified=True,
            content_binding_verified=True,
        )
        workflow = ResearchWorkflow(
            providers=[
                ProviderPlan(
                    FakeResearchProvider(
                        name="youtube",
                        operation="research.youtube",
                        batches=[ProviderBatch(provider="youtube", evidence=(primary,))],
                    ),
                    _authorization("youtube", "research.youtube"),
                ),
                ProviderPlan(
                    FakeResearchProvider(
                        name="openai",
                        operation="research.web_verify",
                        batches=[ProviderBatch(provider="openai", evidence=(signal,))],
                    ),
                    _authorization("openai", "research.web_verify"),
                ),
            ],
            synthesizer=_DynamicTrailerSynthesizer(),
            synthesis_authorization=_authorization("openai", "research.synthesize"),
            official_hosts=set(),
        )
        output = workflow.run(
            intent_from_query("Find one current official film trailer opportunity"),
            generated_at=NOW,
            cancellation=CancellationToken(),
        )
        self.assertEqual(output.result.status.value, "OPPORTUNITIES")
        self.assertEqual(
            output.result.opportunities[0].evidence_gate,
            EvidenceGate.LOW_CONFIDENCE,
        )
        self.assertIn("normal official-primary-plus-two-signals gate", output.result.message)
        self.assertTrue(
            any(
                "Low confidence" in caveat
                for caveat in output.result.opportunities[0].caveats
            )
        )

    def test_current_tvmaze_episode_plus_localized_discussion_yields_honest_low_confidence_scene_pack(self) -> None:
        locator = EpisodeLocatorFactV2(
            show_or_title="Example Show",
            season_number=3,
            episode_number=7,
            episode_title="The Choice",
        )
        metadata = EvidenceCandidate(
            provider="tvmaze",
            provider_record_id="episode:307",
            source_type=EvidenceSourceType.METADATA,
            canonical_url="https://www.tvmaze.com/episodes/307/the-choice",
            title="Example Show - S03E07: The Choice",
            author_or_channel="TVmaze",
            excerpt_type=ExcerptType.PARAPHRASE,
            excerpt="TVmaze lists The Choice as Season 3 Episode 7.",
            verification=VerificationState.SECONDARY_CORROBORATED,
            claim_kind=EvidenceClaimKind.EPISODE_IDENTITY,
            supports_why_now=False,
            policy_class="tvmaze-metadata-v1",
            event_or_release_at=NOW - timedelta(hours=4),
            window_start=NOW - timedelta(days=3),
            window_end=NOW,
            citation_verified=True,
            episode_locator=locator,
        )
        unrelated_metadata = tuple(
            replace(
                metadata,
                provider_record_id=f"episode:unrelated-{index}",
                canonical_url=f"https://www.tvmaze.com/episodes/{900 + index}/another-case",
                title=f"Unrelated Procedural {index} - S01E02: Another Case",
                excerpt="TVmaze lists Another Case as Season 1 Episode 2.",
                episode_locator=EpisodeLocatorFactV2(
                    show_or_title=f"Unrelated Procedural {index}",
                    season_number=1,
                    episode_number=2,
                    episode_title="Another Case",
                ),
            )
            for index in range(20)
        )
        # Canonical source sorting keeps the exact-title source first for this
        # fixture's scene-pack inspection target; the second source proves that
        # a localized page title can still count as a distinct show-level
        # discussion after trusted seed binding.
        signal_hosts = ("thewrap.com", "variety.com")
        signals = tuple(
            EvidenceCandidate(
                provider="openai",
                provider_record_id=(
                    f"discussion:{host}"
                    if index == 0
                    else tvmaze_show_source_binding(
                        "Example Show", f"https://{host}/example-show-relationship"
                    )
                ),
                source_type=EvidenceSourceType.ARTICLE,
                canonical_url=f"https://{host}/example-show-relationship",
                title=(
                    f"Example Show central relationship discussion at {host}"
                    if index == 0
                    else "El futuro de la serie despues del estreno"
                ),
                author_or_channel=host,
                excerpt_type=ExcerptType.PARAPHRASE,
                excerpt=(
                    f"Example Show central relationship discussion at {host}"
                    if index == 0
                    else "Current cited-source title: El futuro de la serie despues del estreno"
                ),
                verification=VerificationState.SECONDARY_CORROBORATED,
                claim_kind=EvidenceClaimKind.VIEWER_DISCUSSION,
                supports_why_now=True,
                policy_class="openai-web-evidence-v1",
                source_created_at=NOW - timedelta(hours=2),
                page_published_at=NOW - timedelta(hours=2),
                window_start=NOW - timedelta(days=3),
                window_end=NOW,
                citation_verified=True,
                content_binding_verified=True,
            )
            for index, host in enumerate(signal_hosts)
        )
        official_video = EvidenceCandidate(
            provider="youtube",
            provider_record_id="video:metadata-fallback-preview",
            source_type=EvidenceSourceType.OFFICIAL_CLIP,
            canonical_url="https://www.youtube.com/watch?v=metadata-fallback-preview",
            title="Example Show | Episode Preview | Official Studio",
            author_or_channel="Official Studio",
            excerpt_type=ExcerptType.PARAPHRASE,
            excerpt="Official Studio published an Example Show episode preview.",
            verification=VerificationState.PRIMARY_VERIFIED,
            claim_kind=EvidenceClaimKind.OFFICIAL_CLIP,
            supports_why_now=True,
            policy_class="youtube-public-metadata-v1",
            source_created_at=NOW - timedelta(hours=1),
            page_published_at=NOW - timedelta(hours=1),
            event_or_release_at=NOW - timedelta(hours=1),
            adapter_origin_id="youtube-channel:studio",
            citation_verified=True,
            why_now_event=WhyNowEventFactV2(
                event_kind=WhyNowEventKind.OFFICIAL_CLIP_RELEASE,
                media_identity=MediaIdentityV2(
                    media_kind=MediaKind.OFFICIAL_CLIP,
                    show_or_title="Example Show",
                ),
            ),
        )
        synthesizer = _MetadataLowSynthesizer()
        workflow = ResearchWorkflow(
            providers=[
                ProviderPlan(
                    FakeResearchProvider(
                        name="tvmaze",
                        operation="research.metadata",
                        batches=[
                            ProviderBatch(
                                provider="tvmaze",
                                evidence=(metadata, *unrelated_metadata),
                            )
                        ],
                    ),
                    _authorization("tvmaze", "research.metadata"),
                ),
                ProviderPlan(
                    FakeResearchProvider(
                        name="openai",
                        operation="research.web_verify",
                        batches=[ProviderBatch(provider="openai", evidence=signals)],
                    ),
                    _authorization("openai", "research.web_verify"),
                ),
            ],
            synthesizer=synthesizer,
            synthesis_authorization=_authorization("openai", "research.synthesize"),
            official_hosts=set(),
        )

        output = workflow.run(
            intent_from_query("romance TV from the last three days"),
            generated_at=NOW,
            cancellation=CancellationToken(),
        )

        self.assertEqual(output.result.status.value, "OPPORTUNITIES")
        self.assertFalse(
            any(
                claim.episode_locator is not None
                and claim.episode_locator.show_or_title.startswith(
                    "Unrelated Procedural"
                )
                for claim in synthesizer.seen_claims
            )
        )
        self.assertEqual(len(synthesizer.seen_claims), 3)
        opportunity = output.result.opportunities[0]
        self.assertEqual(opportunity.evidence_gate, EvidenceGate.LOW_CONFIDENCE)
        self.assertTrue(
            opportunity.why_now.startswith(
                "Current episode metadata (not an official why-now proof):"
            )
        )
        self.assertIn("no official why-now proof", " ".join(opportunity.caveats))
        self.assertIn("not proof of a specific scene", opportunity.emotional_edit_direction)
        requested = output.result.footage_requests[0].required_sources[0]
        self.assertEqual(requested.asset_kind, SourceAcquisitionKind.SCENE_PACK)
        self.assertIsNone(requested.season_number)
        self.assertIsNone(requested.episode_number)
        self.assertIn("scene pack", output.result.footage_requests[0].natural_request.best)

        class RejectedMetadataSynthesizer(_MetadataLowSynthesizer):
            def synthesize(self, *args, **kwargs):
                result = super().synthesize(*args, **kwargs)
                assert result.draft is not None
                recommendation = result.draft.recommendations[0]
                rejected_opportunity = recommendation.opportunity.model_copy(
                    update={
                        "focus": OpportunityFocus(
                            characters=[],
                            relationship_or_topic="fabricated beach kiss",
                        )
                    }
                )
                return SynthesisProviderResult(
                    provider=self.name,
                    draft=ResearchSynthesisDraftV2(
                        recommendations=[
                            SynthesisRecommendationDraftV2(
                                opportunity=rejected_opportunity,
                                footage_request=recommendation.footage_request,
                            )
                        ]
                    ),
                )

        fallback_workflow = ResearchWorkflow(
            providers=[
                ProviderPlan(
                    FakeResearchProvider(
                        name="tvmaze",
                        operation="research.metadata",
                        batches=[
                            ProviderBatch(
                                provider="tvmaze",
                                evidence=(metadata, *unrelated_metadata),
                            )
                        ],
                    ),
                    _authorization("tvmaze", "research.metadata"),
                ),
                ProviderPlan(
                    FakeResearchProvider(
                        name="openai",
                        operation="research.web_verify",
                        batches=[ProviderBatch(provider="openai", evidence=signals)],
                    ),
                    _authorization("openai", "research.web_verify"),
                ),
                ProviderPlan(
                    FakeResearchProvider(
                        name="youtube",
                        operation="research.youtube",
                        batches=[
                            ProviderBatch(
                                provider="youtube", evidence=(official_video,)
                            )
                        ],
                    ),
                    _authorization("youtube", "research.youtube"),
                ),
            ],
            synthesizer=RejectedMetadataSynthesizer(),
            synthesis_authorization=_authorization("openai", "research.synthesize"),
            official_hosts=set(),
        )
        fallback_output = fallback_workflow.run(
            intent_from_query("romance TV from the last three days"),
            generated_at=NOW,
            cancellation=CancellationToken(),
        )
        self.assertEqual(fallback_output.result.status.value, "OPPORTUNITIES")
        fallback_opportunity = fallback_output.result.opportunities[0]
        self.assertEqual(fallback_opportunity.evidence_gate, EvidenceGate.LOW_CONFIDENCE)
        self.assertNotIn(
            "fabricated beach kiss",
            fallback_opportunity.model_dump_json().casefold(),
        )
        fallback_request = fallback_output.result.footage_requests[0]
        fallback_source = fallback_request.required_sources[0]
        self.assertEqual(fallback_source.asset_kind, SourceAcquisitionKind.SCENE_PACK)
        self.assertEqual(
            fallback_source.verification_level,
            FootageVerificationLevel.UNKNOWN,
        )
        self.assertIsNone(fallback_source.season_number)
        self.assertIsNone(fallback_source.episode_number)
        self.assertIsNone(fallback_source.quote)
        self.assertEqual(fallback_request.intro_leads, [])
        self.assertEqual(len(fallback_request.optional_sources), 1)
        self.assertIsNotNone(
            fallback_request.natural_request.optional_improvement
        )
        self.assertEqual(
            fallback_request.optional_sources[0].asset_kind,
            SourceAcquisitionKind.OFFICIAL_CLIP,
        )
        self.assertTrue(
            any("deterministic low-confidence scene-pack fallback" in warning
                for warning in fallback_output.result.warnings)
        )

        forged_signals = (
            signals[0],
            replace(
                signals[1],
                provider_record_id=tvmaze_show_source_binding(
                    "Different Show", "https://variety.com/example-show-relationship"
                ),
            ),
        )
        forged_workflow = ResearchWorkflow(
            providers=[
                ProviderPlan(
                    FakeResearchProvider(
                        name="tvmaze",
                        operation="research.metadata",
                        batches=[ProviderBatch(provider="tvmaze", evidence=(metadata,))],
                    ),
                    _authorization("tvmaze", "research.metadata"),
                ),
                ProviderPlan(
                    FakeResearchProvider(
                        name="openai",
                        operation="research.web_verify",
                        batches=[ProviderBatch(provider="openai", evidence=forged_signals)],
                    ),
                    _authorization("openai", "research.web_verify"),
                ),
            ],
            synthesizer=_MetadataLowSynthesizer(),
            synthesis_authorization=_authorization("openai", "research.synthesize"),
            official_hosts=set(),
        )
        forged_output = forged_workflow.run(
            intent_from_query("romance TV from the last three days"),
            generated_at=NOW,
            cancellation=CancellationToken(),
        )
        self.assertEqual(forged_output.result.status.value, "NO_STRONG_OPPORTUNITY")

    def test_live_lanterns_shape_omits_bad_intro_and_never_uses_article_headline_as_footage_focus(self) -> None:
        """Regress the 2026-08-17 packaged Lanterns footage-request failure."""

        locator = EpisodeLocatorFactV2(
            show_or_title="Lanterns",
            season_number=1,
            episode_number=1,
            episode_title="Pilot",
        )
        metadata = EvidenceCandidate(
            provider="tvmaze",
            provider_record_id="3606548",
            source_type=EvidenceSourceType.METADATA,
            canonical_url="https://www.tvmaze.com/episodes/3606548/lanterns-1x01-pilot",
            title="Lanterns — S01E01: Pilot",
            author_or_channel="TVmaze",
            excerpt_type=ExcerptType.PARAPHRASE,
            excerpt="TVmaze lists Pilot as Season 1 Episode 1.",
            verification=VerificationState.SECONDARY_CORROBORATED,
            claim_kind=EvidenceClaimKind.EPISODE_IDENTITY,
            supports_why_now=False,
            policy_class="tvmaze-metadata-v1",
            event_or_release_at=NOW - timedelta(hours=2),
            window_start=NOW - timedelta(days=14),
            window_end=NOW,
            citation_verified=True,
            episode_locator=locator,
        )
        cast_rows = (
            ("Aaron Pierre", "John Stewart"),
            ("Kyle Chandler", "Hal Jordan / Green Lantern"),
        )
        cast = tuple(
            EvidenceCandidate(
                provider="tvmaze",
                provider_record_id="show-cast:44776",
                source_type=EvidenceSourceType.METADATA,
                canonical_url="https://api.tvmaze.com/shows/44776/cast",
                title="Lanterns cast listing",
                author_or_channel="TVmaze",
                excerpt_type=ExcerptType.PARAPHRASE,
                excerpt=f"TVmaze lists {performer} as {character} in Lanterns.",
                verification=VerificationState.SECONDARY_CORROBORATED,
                claim_kind=EvidenceClaimKind.CAST_IDENTITY,
                supports_why_now=False,
                policy_class="tvmaze-metadata-v1",
                window_start=NOW - timedelta(days=14),
                window_end=NOW,
                citation_verified=True,
                cast_fact=CastIdentityFactV2(
                    show_or_title="Lanterns",
                    performer_name=performer,
                    character_name=character,
                ),
            )
            for performer, character in cast_rows
        )
        long_headline = (
            "I watched the first seven episodes of 'Lanterns' on HBO Max — and the new "
            "sci-fi crime show starring Aaron Pierre and Kyle Chandler is a blindingly "
            "brilliant example of how good the DCU can be"
        )
        discussion_rows = (
            (
                "https://www.techradar.com/streaming/hbo-max/lanterns-review",
                long_headline,
            ),
            (
                "https://www.thedailybeast.com/obsessed/lanterns-hbos-next-must-see-tv-event-is-a-superhero-true-detective/",
                "HBO’s Next Must-See TV Event Is a Superhero ‘True Detective’",
            ),
        )
        signals = tuple(
            EvidenceCandidate(
                provider="openai",
                provider_record_id=tvmaze_show_source_binding("Lanterns", url),
                source_type=EvidenceSourceType.ARTICLE,
                canonical_url=url,
                title=title,
                author_or_channel=None,
                excerpt_type=ExcerptType.PARAPHRASE,
                excerpt=f"Current cited-source title: {title}",
                verification=VerificationState.SECONDARY_CORROBORATED,
                claim_kind=EvidenceClaimKind.VIEWER_DISCUSSION,
                supports_why_now=True,
                policy_class="openai-web-evidence-v1",
                source_created_at=NOW - timedelta(hours=1),
                page_published_at=NOW - timedelta(hours=1),
                window_start=NOW - timedelta(days=14),
                window_end=NOW,
                citation_verified=True,
                content_binding_verified=True,
            )
            for url, title in discussion_rows
        )

        class InvalidOptionalIntroSynthesizer:
            name = "openai"

            def synthesize(
                self,
                intent,
                *,
                evidence_sources,
                evidence_claims,
                authorization,
                cancellation,
            ):
                del intent, evidence_sources, authorization
                cancellation.raise_if_cancelled()
                identity_claim = next(
                    claim
                    for claim in evidence_claims
                    if claim.claim_kind is EvidenceClaimKind.EPISODE_IDENTITY
                )
                discussion_claims = [
                    claim
                    for claim in evidence_claims
                    if claim.claim_kind is EvidenceClaimKind.VIEWER_DISCUSSION
                ]
                cast_claims = [
                    claim
                    for claim in evidence_claims
                    if claim.claim_kind is EvidenceClaimKind.CAST_IDENTITY
                ]
                characters = ["John Stewart", "Hal Jordan"]
                focus = "John Stewart and Hal Jordan"
                supporting_ids = [
                    identity_claim.claim_id,
                    *[claim.claim_id for claim in discussion_claims],
                    *[claim.claim_id for claim in cast_claims],
                ]
                requested = RequestedSourceDraftV2(
                    source_key="lantern_scene_pack",
                    priority=1,
                    acquisition_effort=2,
                    asset_kind=SourceAcquisitionKind.SCENE_PACK,
                    show_or_title="Lanterns",
                    characters=characters,
                    relationship_or_topic=focus,
                    scene_or_moment=f"Any relevant {focus} material; the exact scene is unknown.",
                    purposes=[
                        SourcePurpose.INTRO,
                        SourcePurpose.MONTAGE,
                        SourcePurpose.PAYOFF,
                    ],
                    verification_level=FootageVerificationLevel.UNKNOWN,
                    source_quality_summary="Untrusted model copy.",
                    supporting_claim_ids=supporting_ids,
                    quote=None,
                    why_it_matters_emotionally="Untrusted model copy.",
                    search_queries=["Lanterns John Stewart Hal Jordan scene pack"],
                )
                footage = _request(
                    requested,
                    natural_request=NaturalFootageRequestV2(
                        best="Give me a Lanterns character scene pack.",
                        minimum="One focused scene pack is enough.",
                    ),
                    minimum_useful_source_keys=[requested.source_key],
                    intro_leads=[
                        IntroMaterialLeadDraftV2(
                            source_key=requested.source_key,
                            moment_description=(
                                "Hal confesses in a scene not stated by the evidence."
                            ),
                            why_it_might_lead_into_montage="Untrusted model copy.",
                            verification_level=FootageVerificationLevel.UNKNOWN,
                            supporting_claim_ids=[discussion_claims[0].claim_id],
                        )
                    ],
                    search_queries=["Lanterns John Stewart Hal Jordan scene pack"],
                )
                opportunity = TrendOpportunityDraftV2(
                    media_kind=MediaKind.TV_EPISODE,
                    media_identity=MediaIdentityV2(
                        media_kind=MediaKind.TV_EPISODE,
                        show_or_title="Lanterns",
                        season_number=1,
                        episode_number=1,
                        episode_title="Pilot",
                    ),
                    title="Lanterns character focus",
                    focus=OpportunityFocus(
                        characters=characters,
                        relationship_or_topic=focus,
                    ),
                    why_now=identity_claim.text,
                    what_viewers_are_discussing="; ".join(
                        claim.text for claim in discussion_claims
                    ),
                    creative_hook="Untrusted model hook.",
                    emotional_edit_direction="Untrusted model direction.",
                    evidence=[
                        OpportunityEvidenceSelectionV2(
                            claim_id=identity_claim.claim_id,
                            role=EvidenceRole.CONTEXT,
                            supports_why_now=False,
                        ),
                        *[
                            OpportunityEvidenceSelectionV2(
                                claim_id=claim.claim_id,
                                role=EvidenceRole.QUALITATIVE_SIGNAL,
                                supports_why_now=True,
                            )
                            for claim in discussion_claims
                        ],
                        *[
                            OpportunityEvidenceSelectionV2(
                                claim_id=claim.claim_id,
                                role=EvidenceRole.CONTEXT,
                                supports_why_now=False,
                            )
                            for claim in cast_claims
                        ],
                    ],
                    confidence=0.6,
                )
                return SynthesisProviderResult(
                    provider=self.name,
                    draft=ResearchSynthesisDraftV2(
                        recommendations=[
                            SynthesisRecommendationDraftV2(
                                opportunity=opportunity,
                                footage_request=footage,
                            )
                        ]
                    ),
                )

        class EmptySynthesizer:
            name = "openai"

            def synthesize(self, *args, **kwargs):
                return SynthesisProviderResult(
                    provider=self.name,
                    draft=ResearchSynthesisDraftV2(
                        no_strong_opportunity_reason="No model-authored card."
                    ),
                )

        def run_with(synthesizer):
            workflow = ResearchWorkflow(
                providers=[
                    ProviderPlan(
                        FakeResearchProvider(
                            name="tvmaze",
                            operation="research.metadata",
                            batches=[
                                ProviderBatch(
                                    provider="tvmaze",
                                    evidence=(metadata, *cast),
                                )
                            ],
                        ),
                        _authorization("tvmaze", "research.metadata"),
                    ),
                    ProviderPlan(
                        FakeResearchProvider(
                            name="openai",
                            operation="research.web_verify",
                            batches=[
                                ProviderBatch(provider="openai", evidence=signals)
                            ],
                        ),
                        _authorization("openai", "research.web_verify"),
                    ),
                ],
                synthesizer=synthesizer,
                synthesis_authorization=_authorization(
                    "openai", "research.synthesize"
                ),
                official_hosts=set(),
            )
            return workflow.run(
                intent_from_query("new shows that could be popular on TikTok rn"),
                generated_at=NOW,
                cancellation=CancellationToken(),
            )

        salvaged = run_with(InvalidOptionalIntroSynthesizer())
        self.assertEqual(salvaged.result.status.value, "OPPORTUNITIES")
        self.assertEqual(salvaged.result.footage_requests[0].intro_leads, [])
        self.assertTrue(
            any(
                "Omitted 1 optional synthesized intro lead" in item
                for item in salvaged.result.warnings
            )
        )
        self.assertFalse(
            any(
                "Recommendation synthesis did not yield" in item
                for item in salvaged.result.warnings
            )
        )

        for output in (salvaged, run_with(EmptySynthesizer())):
            opportunity = output.result.opportunities[0]
            request = output.result.footage_requests[0]
            required = request.required_sources[0]
            self.assertEqual(
                opportunity.focus.characters,
                ["John Stewart", "Hal Jordan"],
            )
            self.assertEqual(required.characters, ["John Stewart", "Hal Jordan"])
            self.assertEqual(
                request.natural_request.best,
                "Give me a John Stewart and Hal Jordan scene pack.",
            )
            self.assertIn("exact scene is unknown", required.scene_or_moment)
            self.assertNotIn(long_headline, request.model_dump_json())
            self.assertNotIn(
                long_headline,
                opportunity.focus.relationship_or_topic,
            )

    def test_exact_episode_scene_lead_replaces_generic_live_scene_pack(self) -> None:
        """A qualified scene lead must beat a technically valid generic pack."""

        locator = EpisodeLocatorFactV2(
            show_or_title="Lanterns",
            season_number=1,
            episode_number=1,
            episode_title="Pilot",
        )
        metadata = EvidenceCandidate(
            provider="tvmaze",
            provider_record_id="3606548",
            source_type=EvidenceSourceType.METADATA,
            canonical_url="https://www.tvmaze.com/episodes/3606548/lanterns-1x01-pilot",
            title="Lanterns — S01E01: Pilot",
            author_or_channel="TVmaze",
            excerpt_type=ExcerptType.PARAPHRASE,
            excerpt="TVmaze lists Pilot as Season 1 Episode 1.",
            verification=VerificationState.SECONDARY_CORROBORATED,
            claim_kind=EvidenceClaimKind.EPISODE_IDENTITY,
            supports_why_now=False,
            policy_class="tvmaze-metadata-v1",
            event_or_release_at=NOW - timedelta(hours=2),
            citation_verified=True,
            episode_locator=locator,
        )
        cast = EvidenceCandidate(
            provider="tvmaze",
            provider_record_id="show-cast:44776",
            source_type=EvidenceSourceType.METADATA,
            canonical_url="https://api.tvmaze.com/shows/44776/cast",
            title="Lanterns cast listing",
            author_or_channel="TVmaze",
            excerpt_type=ExcerptType.PARAPHRASE,
            excerpt="TVmaze lists Kyle Chandler as Hal Jordan / Green Lantern in Lanterns.",
            verification=VerificationState.SECONDARY_CORROBORATED,
            claim_kind=EvidenceClaimKind.CAST_IDENTITY,
            supports_why_now=False,
            policy_class="tvmaze-metadata-v1",
            citation_verified=True,
            cast_fact=CastIdentityFactV2(
                show_or_title="Lanterns",
                performer_name="Kyle Chandler",
                character_name="Hal Jordan / Green Lantern",
            ),
        )
        techradar_url = (
            "https://www.techradar.com/streaming/hbo-max/"
            "lanterns-episode-1-ending-explained"
        )
        techradar_title = (
            "'Lanterns' episode 1 makes an incredibly bold storytelling choice — "
            "and raises a theory about the show's dual timelines"
        )
        daily_beast_url = (
            "https://www.thedailybeast.com/obsessed/"
            "lanterns-hbos-next-must-see-tv-event-is-a-superhero-true-detective/"
        )
        signals = (
            EvidenceCandidate(
                provider="openai",
                provider_record_id=tvmaze_show_source_binding(
                    "Lanterns", techradar_url
                ),
                source_type=EvidenceSourceType.ARTICLE,
                canonical_url=techradar_url,
                title=techradar_title,
                author_or_channel=None,
                excerpt_type=ExcerptType.PARAPHRASE,
                excerpt=f"Current cited-source title: {techradar_title}",
                verification=VerificationState.SECONDARY_CORROBORATED,
                claim_kind=EvidenceClaimKind.VIEWER_DISCUSSION,
                supports_why_now=True,
                policy_class="openai-web-evidence-v1",
                source_created_at=NOW - timedelta(hours=1),
                page_published_at=NOW - timedelta(hours=1),
                citation_verified=True,
                content_binding_verified=True,
            ),
            EvidenceCandidate(
                provider="openai",
                provider_record_id=tvmaze_show_source_binding(
                    "Lanterns", techradar_url
                ),
                source_type=EvidenceSourceType.ARTICLE,
                canonical_url=techradar_url,
                title=techradar_title,
                author_or_channel=None,
                excerpt_type=ExcerptType.PARAPHRASE,
                excerpt=(
                    "Season 1 Episode 1's ending around Hal Jordan's apparent death"
                ),
                verification=VerificationState.LEAD_ONLY,
                claim_kind=EvidenceClaimKind.SCENE_CONTEXT,
                supports_why_now=False,
                policy_class="openai-web-evidence-v1",
                source_created_at=NOW - timedelta(hours=1),
                page_published_at=NOW - timedelta(hours=1),
                citation_verified=True,
                content_binding_verified=True,
                scene_fact=SceneMomentFactV2(
                    show_or_title="Lanterns",
                    description=(
                        "Season 1 Episode 1's ending around Hal Jordan's apparent death"
                    ),
                    characters=["Hal Jordan"],
                    relationship_or_topic=(
                        "Hal Jordan's apparent death in Episode 1"
                    ),
                    episode_locator=locator,
                ),
            ),
            EvidenceCandidate(
                provider="openai",
                provider_record_id=tvmaze_show_source_binding(
                    "Lanterns", daily_beast_url
                ),
                source_type=EvidenceSourceType.ARTICLE,
                canonical_url=daily_beast_url,
                title="HBO’s Next Must-See TV Event Is a Superhero ‘True Detective’",
                author_or_channel=None,
                excerpt_type=ExcerptType.PARAPHRASE,
                excerpt=(
                    "Current cited-source title: HBO’s Next Must-See TV Event Is a "
                    "Superhero ‘True Detective’"
                ),
                verification=VerificationState.SECONDARY_CORROBORATED,
                claim_kind=EvidenceClaimKind.VIEWER_DISCUSSION,
                supports_why_now=True,
                policy_class="openai-web-evidence-v1",
                source_created_at=NOW - timedelta(minutes=45),
                page_published_at=NOW - timedelta(minutes=45),
                citation_verified=True,
                content_binding_verified=True,
            ),
        )
        official_video = EvidenceCandidate(
            provider="youtube",
            provider_record_id="video:lanterns-episode-preview",
            source_type=EvidenceSourceType.OFFICIAL_CLIP,
            canonical_url="https://www.youtube.com/watch?v=lanterns-episode-preview",
            title="Lanterns | Episode Preview | HBO Max",
            author_or_channel="HBO Max",
            excerpt_type=ExcerptType.PARAPHRASE,
            excerpt="HBO Max published a Lanterns episode preview.",
            verification=VerificationState.PRIMARY_VERIFIED,
            claim_kind=EvidenceClaimKind.OFFICIAL_CLIP,
            supports_why_now=True,
            policy_class="youtube-public-metadata-v1",
            source_created_at=NOW - timedelta(minutes=30),
            page_published_at=NOW - timedelta(minutes=30),
            event_or_release_at=NOW - timedelta(minutes=30),
            adapter_origin_id="youtube-channel:hbo-max",
            citation_verified=True,
            why_now_event=WhyNowEventFactV2(
                event_kind=WhyNowEventKind.OFFICIAL_CLIP_RELEASE,
                media_identity=MediaIdentityV2(
                    media_kind=MediaKind.OFFICIAL_CLIP,
                    show_or_title="Lanterns",
                ),
            ),
        )

        class GenericPackSynthesizer:
            name = "openai"

            def synthesize(
                self,
                intent,
                *,
                evidence_sources,
                evidence_claims,
                authorization,
                cancellation,
            ):
                del intent, evidence_sources, authorization
                cancellation.raise_if_cancelled()
                identity_claim = next(
                    claim
                    for claim in evidence_claims
                    if claim.claim_kind is EvidenceClaimKind.EPISODE_IDENTITY
                )
                discussion_claims = [
                    claim
                    for claim in evidence_claims
                    if claim.claim_kind is EvidenceClaimKind.VIEWER_DISCUSSION
                ]
                requested = RequestedSourceDraftV2(
                    source_key="generic_pack",
                    priority=1,
                    acquisition_effort=2,
                    asset_kind=SourceAcquisitionKind.SCENE_PACK,
                    show_or_title="Lanterns",
                    characters=[],
                    relationship_or_topic="current ending discussion",
                    scene_or_moment=(
                        "Any relevant current ending discussion material; the exact scene is unknown."
                    ),
                    purposes=[
                        SourcePurpose.INTRO,
                        SourcePurpose.MONTAGE,
                        SourcePurpose.PAYOFF,
                    ],
                    verification_level=FootageVerificationLevel.UNKNOWN,
                    source_quality_summary="Untrusted model copy.",
                    supporting_claim_ids=[
                        identity_claim.claim_id,
                        *[claim.claim_id for claim in discussion_claims],
                    ],
                    quote=None,
                    why_it_matters_emotionally="Untrusted model copy.",
                    search_queries=["Lanterns current ending discussion scene pack"],
                )
                opportunity = TrendOpportunityDraftV2(
                    media_kind=MediaKind.TV_EPISODE,
                    media_identity=MediaIdentityV2(
                        media_kind=MediaKind.TV_EPISODE,
                        show_or_title="Lanterns",
                        season_number=1,
                        episode_number=1,
                        episode_title="Pilot",
                    ),
                    title="Lanterns generic ending discussion",
                    focus=OpportunityFocus(
                        characters=[],
                        relationship_or_topic="current ending discussion",
                    ),
                    why_now=identity_claim.text,
                    what_viewers_are_discussing="; ".join(
                        claim.text for claim in discussion_claims
                    ),
                    creative_hook="Untrusted model hook.",
                    emotional_edit_direction="Untrusted model direction.",
                    evidence=[
                        OpportunityEvidenceSelectionV2(
                            claim_id=identity_claim.claim_id,
                            role=EvidenceRole.CONTEXT,
                            supports_why_now=False,
                        ),
                        *[
                            OpportunityEvidenceSelectionV2(
                                claim_id=claim.claim_id,
                                role=EvidenceRole.QUALITATIVE_SIGNAL,
                                supports_why_now=True,
                            )
                            for claim in discussion_claims
                        ],
                    ],
                    confidence=0.6,
                )
                return SynthesisProviderResult(
                    provider=self.name,
                    draft=ResearchSynthesisDraftV2(
                        recommendations=[
                            SynthesisRecommendationDraftV2(
                                opportunity=opportunity,
                                footage_request=_request(
                                    requested,
                                    natural_request=NaturalFootageRequestV2(
                                        best="Give me a generic scene pack.",
                                        minimum="One generic pack is enough.",
                                    ),
                                    minimum_useful_source_keys=[requested.source_key],
                                    search_queries=[
                                        "Lanterns current ending discussion scene pack"
                                    ],
                                ),
                            )
                        ]
                    ),
                )

        workflow = ResearchWorkflow(
            providers=[
                ProviderPlan(
                    FakeResearchProvider(
                        name="tvmaze",
                        operation="research.metadata",
                        batches=[
                            ProviderBatch(
                                provider="tvmaze", evidence=(metadata, cast)
                            )
                        ],
                    ),
                    _authorization("tvmaze", "research.metadata"),
                ),
                ProviderPlan(
                    FakeResearchProvider(
                        name="openai",
                        operation="research.web_verify",
                        batches=[
                            ProviderBatch(provider="openai", evidence=signals)
                        ],
                    ),
                    _authorization("openai", "research.web_verify"),
                ),
                ProviderPlan(
                    FakeResearchProvider(
                        name="youtube",
                        operation="research.youtube",
                        batches=[
                            ProviderBatch(
                                provider="youtube", evidence=(official_video,)
                            )
                        ],
                    ),
                    _authorization("youtube", "research.youtube"),
                ),
            ],
            synthesizer=GenericPackSynthesizer(),
            synthesis_authorization=_authorization(
                "openai", "research.synthesize"
            ),
            official_hosts=set(),
        )

        output = workflow.run(
            intent_from_query("new shows that could be popular on TikTok rn"),
            generated_at=NOW,
            cancellation=CancellationToken(),
        )

        self.assertEqual(output.result.status.value, "OPPORTUNITIES")
        opportunity = output.result.opportunities[0]
        request = output.result.footage_requests[0]
        required = request.required_sources[0]
        self.assertEqual(required.asset_kind, SourceAcquisitionKind.INDIVIDUAL_SCENES)
        self.assertEqual(
            required.verification_level,
            FootageVerificationLevel.LIKELY_INFERRED,
        )
        self.assertEqual(required.characters, ["Hal Jordan"])
        self.assertEqual(
            required.scene_or_moment,
            "Season 1 Episode 1's ending around Hal Jordan's apparent death",
        )
        self.assertEqual(
            request.natural_request.best,
            "Give me the Lanterns scenes covering Season 1 Episode 1's ending around Hal Jordan's apparent death.",
        )
        self.assertEqual(len(request.intro_leads), 1)
        self.assertEqual(len(request.optional_sources), 1)
        self.assertEqual(
            request.optional_sources[0].asset_kind,
            SourceAcquisitionKind.OFFICIAL_CLIP,
        )
        self.assertIsNotNone(request.natural_request.optional_improvement)
        self.assertIn("LIKELY / INFERRED", opportunity.creative_hook)
        self.assertIn("Hal Jordan's apparent death", opportunity.creative_hook)
        self.assertNotIn(techradar_title, request.model_dump_json())
        self.assertTrue(
            any(
                "Replaced a generic same-title scene pack" in warning
                for warning in output.result.warnings
            )
        )

    def test_tvmaze_metadata_plus_one_discussion_does_not_spend_on_synthesis(self) -> None:
        locator = EpisodeLocatorFactV2(
            show_or_title="Example Show",
            season_number=3,
            episode_number=7,
            episode_title="The Choice",
        )
        metadata = EvidenceCandidate(
            provider="tvmaze",
            provider_record_id="episode:307",
            source_type=EvidenceSourceType.METADATA,
            canonical_url="https://www.tvmaze.com/episodes/307/the-choice",
            title="Example Show - S03E07: The Choice",
            author_or_channel="TVmaze",
            excerpt_type=ExcerptType.PARAPHRASE,
            excerpt="TVmaze lists The Choice as Season 3 Episode 7.",
            verification=VerificationState.SECONDARY_CORROBORATED,
            claim_kind=EvidenceClaimKind.EPISODE_IDENTITY,
            supports_why_now=False,
            policy_class="tvmaze-metadata-v1",
            event_or_release_at=NOW - timedelta(hours=4),
            window_start=NOW - timedelta(days=3),
            window_end=NOW,
            citation_verified=True,
            episode_locator=locator,
        )
        signal = EvidenceCandidate(
            provider="openai",
            provider_record_id="discussion:one",
            source_type=EvidenceSourceType.ARTICLE,
            canonical_url="https://variety.com/example-show-relationship",
            title="Example Show central relationship discussion",
            author_or_channel="variety.com",
            excerpt_type=ExcerptType.PARAPHRASE,
            excerpt="Example Show central relationship discussion",
            verification=VerificationState.SECONDARY_CORROBORATED,
            claim_kind=EvidenceClaimKind.VIEWER_DISCUSSION,
            supports_why_now=True,
            policy_class="openai-web-evidence-v1",
            source_created_at=NOW - timedelta(hours=2),
            page_published_at=NOW - timedelta(hours=2),
            window_start=NOW - timedelta(days=3),
            window_end=NOW,
            citation_verified=True,
            content_binding_verified=True,
        )

        class MustNotRun:
            name = "openai"

            def synthesize(self, *args, **kwargs):
                raise AssertionError("one metadata record plus one signal must not synthesize")

        workflow = ResearchWorkflow(
            providers=[
                ProviderPlan(
                    FakeResearchProvider(
                        name="tvmaze",
                        operation="research.metadata",
                        batches=[ProviderBatch(provider="tvmaze", evidence=(metadata,))],
                    ),
                    _authorization("tvmaze", "research.metadata"),
                ),
                ProviderPlan(
                    FakeResearchProvider(
                        name="openai",
                        operation="research.web_verify",
                        batches=[ProviderBatch(provider="openai", evidence=(signal,))],
                    ),
                    _authorization("openai", "research.web_verify"),
                ),
            ],
            synthesizer=MustNotRun(),
            synthesis_authorization=_authorization("openai", "research.synthesize"),
            official_hosts=set(),
        )
        output = workflow.run(
            intent_from_query("romance TV from the last three days"),
            generated_at=NOW,
            cancellation=CancellationToken(),
        )
        self.assertEqual(output.result.status.value, "NO_STRONG_OPPORTUNITY")

    def test_live_r57_tv_clip_cannot_trigger_empty_tv_episode_synthesis(self) -> None:
        """An OFFICIAL_CLIP identity cannot satisfy a TV_EPISODE intent gate."""

        locator = EpisodeLocatorFactV2(
            show_or_title="Example Show",
            season_number=1,
            episode_number=4,
            episode_title="The Turn",
        )
        metadata = EvidenceCandidate(
            provider="tvmaze",
            provider_record_id="episode:r57:4",
            source_type=EvidenceSourceType.METADATA,
            canonical_url="https://www.tvmaze.com/episodes/5704/the-turn",
            title="Example Show - S01E04: The Turn",
            author_or_channel="TVmaze",
            excerpt_type=ExcerptType.PARAPHRASE,
            excerpt="TVmaze lists The Turn as the current episode.",
            verification=VerificationState.SECONDARY_CORROBORATED,
            claim_kind=EvidenceClaimKind.EPISODE_IDENTITY,
            supports_why_now=False,
            policy_class="tvmaze-metadata-v1",
            event_or_release_at=NOW - timedelta(hours=4),
            citation_verified=True,
            episode_locator=locator,
        )
        signal = EvidenceCandidate(
            provider="openai",
            provider_record_id="discussion:r57:future",
            source_type=EvidenceSourceType.ARTICLE,
            canonical_url="https://www.techradar.com/streaming/example-show-current",
            title="Example Show current character discussion",
            author_or_channel="techradar.com",
            excerpt_type=ExcerptType.PARAPHRASE,
            excerpt="Example Show has a current character discussion.",
            verification=VerificationState.SECONDARY_CORROBORATED,
            claim_kind=EvidenceClaimKind.VIEWER_DISCUSSION,
            supports_why_now=True,
            policy_class="openai-web-evidence-v1",
            source_created_at=NOW - timedelta(hours=2),
            page_published_at=NOW - timedelta(hours=2),
            citation_verified=True,
            content_binding_verified=True,
        )
        official_clip = EvidenceCandidate(
            provider="youtube",
            provider_record_id="video:r57:preview",
            source_type=EvidenceSourceType.OFFICIAL_CLIP,
            canonical_url="https://www.youtube.com/watch?v=r57-preview",
            title="Example Show | Episode 4 Preview | Official Studio",
            author_or_channel="Official Studio",
            excerpt_type=ExcerptType.PARAPHRASE,
            excerpt="Official Studio published an Example Show episode preview.",
            verification=VerificationState.PRIMARY_VERIFIED,
            claim_kind=EvidenceClaimKind.OFFICIAL_CLIP,
            supports_why_now=True,
            policy_class="youtube-public-metadata-v1",
            source_created_at=NOW - timedelta(hours=1),
            page_published_at=NOW - timedelta(hours=1),
            event_or_release_at=NOW - timedelta(hours=1),
            adapter_origin_id="youtube-channel:studio",
            citation_verified=True,
            why_now_event=WhyNowEventFactV2(
                event_kind=WhyNowEventKind.OFFICIAL_CLIP_RELEASE,
                media_identity=MediaIdentityV2(
                    media_kind=MediaKind.OFFICIAL_CLIP,
                    show_or_title="Example Show",
                ),
            ),
        )

        class MustNotRun:
            name = "openai"

            def synthesize(self, *args, **kwargs):
                raise AssertionError(
                    "a media-kind-mismatched official clip must not trigger synthesis"
                )

        workflow = ResearchWorkflow(
            providers=[
                ProviderPlan(
                    FakeResearchProvider(
                        name="tvmaze",
                        operation="research.metadata",
                        batches=[ProviderBatch(provider="tvmaze", evidence=(metadata,))],
                    ),
                    _authorization("tvmaze", "research.metadata"),
                ),
                ProviderPlan(
                    FakeResearchProvider(
                        name="openai",
                        operation="research.web_verify",
                        batches=[ProviderBatch(provider="openai", evidence=(signal,))],
                    ),
                    _authorization("openai", "research.web_verify"),
                ),
                ProviderPlan(
                    FakeResearchProvider(
                        name="youtube",
                        operation="research.youtube",
                        batches=[ProviderBatch(provider="youtube", evidence=(official_clip,))],
                    ),
                    _authorization("youtube", "research.youtube"),
                ),
            ],
            synthesizer=MustNotRun(),
            synthesis_authorization=_authorization("openai", "research.synthesize"),
            official_hosts=set(),
        )

        output = workflow.run(
            intent_from_query("a good show for girls thatll get views on tiktok"),
            generated_at=NOW,
            cancellation=CancellationToken(),
        )

        self.assertEqual(output.result.status.value, "NO_STRONG_OPPORTUNITY")
        self.assertIsNone(output.synthesis)
        self.assertNotIn("No supplied sources or claims", output.result.message)

    def test_no_evidence_returns_no_strong_opportunity_without_synthesis(self) -> None:
        class MustNotRun:
            name = "openai"

            def synthesize(self, *args, **kwargs):
                raise AssertionError("synthesis must not spend when the gate cannot possibly pass")

        workflow = ResearchWorkflow(
            providers=[],
            synthesizer=MustNotRun(),
            synthesis_authorization=_authorization("openai", "research.synthesize"),
            official_hosts=set(),
        )
        authoritative_run_id = uuid4()
        result = workflow.run(
            intent_from_query("romance TV, no reality TV"),
            generated_at=NOW,
            cancellation=CancellationToken(),
            run_id=authoritative_run_id,
        ).result
        self.assertEqual(result.run_id, authoritative_run_id)
        self.assertEqual(result.status.value, "NO_STRONG_OPPORTUNITY")
        self.assertEqual(result.opportunities, [])

    def test_public_path_diagnostic_cannot_break_the_result_boundary(self) -> None:
        class MustNotRun:
            name = "openai"

            def synthesize(self, *args, **kwargs):
                raise AssertionError("synthesis must not spend without evidence")

        batch = ProviderBatch(
            provider="openai",
            evidence=(),
            warnings=(
                "Rejected reviewed page https://studio.example/download/manifest because its "
                "source-owned date was stale; this is a public path diagnostic, not an "
                "acquisition instruction.",
            ),
        )
        workflow = ResearchWorkflow(
            providers=[
                ProviderPlan(
                    FakeResearchProvider(
                        name="openai",
                        operation="research.web_verify",
                        batches=[batch],
                    ),
                    _authorization("openai", "research.web_verify"),
                )
            ],
            synthesizer=MustNotRun(),
            synthesis_authorization=_authorization("openai", "research.synthesize"),
            official_hosts=set(),
        )

        result = workflow.run(
            intent_from_query("new movie or trailer"),
            generated_at=NOW,
            cancellation=CancellationToken(),
        ).result

        self.assertEqual(result.status.value, "NO_STRONG_OPPORTUNITY")
        self.assertEqual(len(result.warnings), 1)
        warning = result.warnings[0].casefold()
        for forbidden in ("download", "manifest", "torrent", "viral", "% chance"):
            self.assertNotIn(forbidden, warning)
        self.assertIn("studio.example", warning)
        self.assertIn("source-owned date was stale", warning)
        self.assertLessEqual(len(result.warnings[0]), 500)

    def test_workflow_passes_only_successful_prior_provider_facts_as_context(self) -> None:
        locator = EpisodeLocatorFactV2(
            show_or_title="Example Show",
            season_number=1,
            episode_number=2,
            episode_title="Turning Point",
        )
        tvmaze_evidence = EvidenceCandidate(
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

        class CapturingProvider:
            name = "openai"

            def __init__(self) -> None:
                self.context: ProviderResearchContext | None = None

            def collect(
                self,
                intent,
                *,
                authorization,
                cancellation,
                context=ProviderResearchContext(),
            ):
                del intent, authorization
                cancellation.raise_if_cancelled()
                self.context = context
                return ProviderBatch(provider=self.name, evidence=())

        verifier = CapturingProvider()
        workflow = ResearchWorkflow(
            providers=[
                ProviderPlan(
                    FakeResearchProvider(
                        name="tvmaze",
                        operation="research.metadata",
                        batches=[
                            ProviderBatch(
                                provider="tvmaze",
                                evidence=(tvmaze_evidence,),
                                trusted_official_hosts=("example.com",),
                            )
                        ],
                    ),
                    _authorization("tvmaze", "research.metadata"),
                ),
                ProviderPlan(
                    FakeResearchProvider(
                        name="youtube",
                        operation="research.youtube",
                        batches=[
                            ProviderBatch(
                                provider="youtube",
                                evidence=(),
                                outcome=ProviderRunOutcome.ERROR,
                                error="bounded fixture failure",
                            )
                        ],
                    ),
                    _authorization("youtube", "research.youtube"),
                ),
                ProviderPlan(
                    verifier,
                    _authorization("openai", "research.web_verify"),
                ),
            ],
            synthesizer=object(),
            synthesis_authorization=_authorization("openai", "research.synthesize"),
            official_hosts=set(),
        )

        workflow.run(
            intent_from_query("romance TV from the last three days"),
            generated_at=NOW,
            cancellation=CancellationToken(),
        )

        assert verifier.context is not None
        self.assertEqual(verifier.context.prior_evidence, (tvmaze_evidence,))
        self.assertEqual(verifier.context.trusted_official_hosts, ("example.com",))


def _authorization(provider: str, operation: str) -> CallAuthorization:
    return CallAuthorization(
        job_id=uuid4(),
        reservation_id=uuid4(),
        provider=provider,
        operation=operation,
        configured_model=None,
        allowed_resolved_models=(),
        max_requests=4,
        max_tool_calls=4,
        max_output_tokens=4_000,
        allow_one_repair=False,
        privacy_mode="offline",
        live_calls_enabled=True,
    )


if __name__ == "__main__":
    unittest.main()
