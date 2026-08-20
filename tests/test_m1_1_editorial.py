from __future__ import annotations

import sys
import unittest
from types import SimpleNamespace
from pathlib import Path
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ai_edit_machine.contracts import EvidenceRole, MediaKind  # noqa: E402
from ai_edit_machine.m1_contracts import (  # noqa: E402
    DossierCharacterV1,
    DossierCurrentSourceKind,
    DossierCurrentSourceV1,
    DossierEvidenceFactV1,
    EditorialConceptDraftV1,
    FandomStoryDossierDraftV1,
    FootageRequestDraftV2,
    FootageVerificationLevel,
    IntroMaterialLeadDraftV2,
    LegacyConnectionType,
    NaturalFootageRequestV2,
    MediaIdentityV2,
    OpportunityFocus,
    OpportunityEvidenceSelectionV2,
    RequestedSourceDraftV2,
    SourceAcquisitionKind,
    SourcePurpose,
    SynthesisRecommendationDraftV2,
    TrendOpportunityDraftV2,
)
from ai_edit_machine.research.workflow import (  # noqa: E402
    _validate_pair_against_intent,
    _validate_editorial_concept_copy,
)
from ai_edit_machine.research.ranking import score_editorial_concept  # noqa: E402
from ai_edit_machine.research.intent import intent_from_query  # noqa: E402


class M11EditorialContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.claim_id = uuid4()

    def _source(
        self,
        key: str,
        *,
        title: str,
        moment: str,
        kind: SourceAcquisitionKind,
        priority: int,
        verification: FootageVerificationLevel,
        season: int | None = None,
        episode: int | None = None,
    ) -> RequestedSourceDraftV2:
        return RequestedSourceDraftV2(
            source_key=key,
            priority=priority,
            acquisition_effort=2,
            asset_kind=kind,
            show_or_title=title,
            season_number=season,
            episode_number=episode,
            episode_title=("The Return" if season is not None else None),
            characters=["Ari", "Bea"],
            relationship_or_topic="Ari and Bea's shared history",
            scene_or_moment=moment,
            purposes=[SourcePurpose.INTRO, SourcePurpose.MONTAGE, SourcePurpose.PAYOFF],
            verification_level=verification,
            source_quality_summary="Synthetic evidence fixture; local footage remains uninspected.",
            supporting_claim_ids=(
                []
                if verification is FootageVerificationLevel.UNKNOWN
                else [self.claim_id]
            ),
            why_it_matters_emotionally="It establishes one functional beat in the proposed arc.",
            search_queries=[f"{title} Ari Bea {key.replace('_', ' ')}"],
        )

    def _footage(
        self,
        *,
        concept_key: str = "recognition_history_payoff",
        current_title: str = "Current Continuation",
        legacy_title: str | None = "Parent Series",
        current_kind: SourceAcquisitionKind = SourceAcquisitionKind.EPISODE,
        current_verification: FootageVerificationLevel = FootageVerificationLevel.VERIFIED,
        current_moment: str = "Ari recognizes Bea during their present-day reunion",
    ) -> FootageRequestDraftV2:
        current = self._source(
            "current_hook",
            title=current_title,
            moment=current_moment,
            kind=current_kind,
            priority=1,
            verification=current_verification,
            season=(1 if current_kind is SourceAcquisitionKind.EPISODE else None),
            episode=(2 if current_kind is SourceAcquisitionKind.EPISODE else None),
        )
        required = [current]
        if legacy_title is not None:
            required.append(
                self._source(
                    "legacy_history",
                    title=legacy_title,
                    moment="Ari and Bea's early distrust, growing loyalty, rupture, and repair",
                    kind=SourceAcquisitionKind.SCENE_PACK,
                    priority=2,
                    verification=FootageVerificationLevel.STRONGLY_SUPPORTED,
                )
            )
        lead = IntroMaterialLeadDraftV2(
            source_key="current_hook",
            moment_description=current_moment,
            why_it_might_lead_into_montage=(
                "The recognition opens the question of what history made this reaction matter."
            ),
            verification_level=current_verification,
            supporting_claim_ids=[self.claim_id],
        )
        minimum = [item.source_key for item in required]
        return FootageRequestDraftV2(
            concept_key=concept_key,
            summary="Current recognition into evidence-backed relationship history.",
            natural_request=NaturalFootageRequestV2(
                best="Give me the current reunion and the compact Ari and Bea legacy scene pack.",
                minimum="One current episode plus one relationship scene pack is the minimum useful set.",
            ),
            required_sources=required,
            minimum_useful_source_keys=minimum,
            smallest_useful_set_reason=(
                "The present hook establishes why now; the compact legacy pack supplies the arc."
            ),
            intro_leads=[lead],
            search_queries=[
                f"{current_title} Ari Bea reunion scene",
                f"{legacy_title or current_title} Ari Bea relationship scene pack",
            ],
            warnings=[
                "Exact timing and usable reactions require later footage inspection."
            ],
        )

    def _concept(
        self,
        *,
        key: str = "recognition_history_payoff",
        connection: LegacyConnectionType = LegacyConnectionType.SAME_CHARACTER,
        footage: FootageRequestDraftV2 | None = None,
        verification: FootageVerificationLevel = FootageVerificationLevel.STRONGLY_SUPPORTED,
        central_subject: str = "Ari recognizing Bea after their shared history",
    ) -> EditorialConceptDraftV1:
        footage = footage or self._footage(concept_key=key)
        if footage.concept_key != key:
            footage = footage.model_copy(update={"concept_key": key})
        return EditorialConceptDraftV1(
            concept_key=key,
            dossier_key="ari_bea_dossier",
            title="Recognition, history, payoff",
            central_subject=central_subject,
            central_relationship="Ari and Bea",
            core_emotion="recognition changed by accumulated loyalty",
            viewer_hook="The current reunion asks why one look carries years of history.",
            why_fans_may_care="Current discussion centers their remembered bond and reunion.",
            current_event="The continuation released a current reunion scene.",
            legacy_or_contextual_connection=(
                "The evidence identifies the same canonical characters in the parent series."
            ),
            legacy_connection_type=connection,
            intro_leads=footage.intro_leads,
            song_handoff_idea="Cut from the recognition reaction into their earliest uneasy exchange.",
            montage_arc=[
                "early distrust and comic friction",
                "growing trust through repeated choices",
                "rupture followed by loyalty",
                "present-day recognition and emotional payoff",
            ],
            ending_or_payoff="Return to the reunion reaction after the history has changed its meaning.",
            evidence=[
                OpportunityEvidenceSelectionV2(
                    claim_id=self.claim_id,
                    role=EvidenceRole.CONTEXT,
                    supports_why_now=False,
                )
            ],
            verification_status=verification,
            creative_strength=0.86,
            footage_feasibility=0.82,
            known_uncertainties=[
                "The web evidence does not establish frame-accurate timing."
            ],
            footage_request=footage,
        )

    def _dossier(self) -> FandomStoryDossierDraftV1:
        evidence = [
            OpportunityEvidenceSelectionV2(
                claim_id=self.claim_id,
                role=EvidenceRole.CONTEXT,
                supports_why_now=False,
            )
        ]
        return FandomStoryDossierDraftV1(
            dossier_key="ari_bea_dossier",
            show_or_title="Current Continuation",
            current_event_or_hook=DossierEvidenceFactV1(
                text="Ari recognizes Bea during a present-day reunion in the current episode.",
                verification_status=FootageVerificationLevel.VERIFIED,
                supporting_claim_ids=[self.claim_id],
            ),
            named_characters=[
                DossierCharacterV1(
                    character_name=name,
                    show_or_title="Current Continuation",
                    verification_status=FootageVerificationLevel.VERIFIED,
                    supporting_claim_ids=[self.claim_id],
                )
                for name in ("Ari", "Bea")
            ],
            central_relationship=DossierEvidenceFactV1(
                text="Ari and Bea share a history of distrust, loyalty, rupture, and repair.",
                verification_status=FootageVerificationLevel.STRONGLY_SUPPORTED,
                supporting_claim_ids=[self.claim_id],
            ),
            current_source=DossierCurrentSourceV1(
                source_kind=DossierCurrentSourceKind.EPISODE,
                show_or_title="Current Continuation",
                source_title="The Return",
                season_number=1,
                episode_number=2,
                episode_title="The Return",
                verification_status=FootageVerificationLevel.VERIFIED,
                supporting_claim_ids=[self.claim_id],
            ),
            relationship_or_character_history=[
                DossierEvidenceFactV1(
                    text="Their earlier distrust gradually became loyalty before a rupture and repair.",
                    verification_status=FootageVerificationLevel.STRONGLY_SUPPORTED,
                    supporting_claim_ids=[self.claim_id],
                )
            ],
            why_fans_currently_care=[
                DossierEvidenceFactV1(
                    text="Current discussion focuses on the remembered bond and reunion.",
                    verification_status=FootageVerificationLevel.STRONGLY_SUPPORTED,
                    supporting_claim_ids=[self.claim_id],
                )
            ],
            audience_and_fandom_evidence=[
                DossierEvidenceFactV1(
                    text="Viewers are discussing how the reunion changes the meaning of their shared history.",
                    verification_status=FootageVerificationLevel.STRONGLY_SUPPORTED,
                    supporting_claim_ids=[self.claim_id],
                )
            ],
            uncertainties=["Local footage has not yet been inspected."],
            evidence=evidence,
        )

    def _opportunity(self) -> TrendOpportunityDraftV2:
        return TrendOpportunityDraftV2(
            media_kind=MediaKind.TV_EPISODE,
            media_identity=MediaIdentityV2(
                media_kind=MediaKind.TV_EPISODE,
                show_or_title="Current Continuation",
                season_number=1,
                episode_number=2,
                episode_title="The Return",
            ),
            title="Current reunion recontextualizes Ari and Bea",
            focus=OpportunityFocus(
                characters=["Ari", "Bea"],
                relationship_or_topic="Ari and Bea's shared history",
            ),
            why_now="A current episode contains their evidence-supported reunion.",
            what_viewers_are_discussing="Current discussion focuses on the remembered bond.",
            creative_hook="Recognition opens into their accumulated history.",
            emotional_edit_direction="Move from distrust to loyalty and back to recognition.",
            evidence=[
                OpportunityEvidenceSelectionV2(
                    claim_id=self.claim_id,
                    role=EvidenceRole.CONTEXT,
                    supports_why_now=False,
                )
            ],
            confidence=0.82,
        )

    def test_verified_returning_character_supports_current_to_history_route(self) -> None:
        concept = self._concept()
        self.assertEqual(concept.legacy_connection_type, LegacyConnectionType.SAME_CHARACTER)
        self.assertIn("present-day recognition", concept.montage_arc[-1])

    def test_parent_series_footage_is_first_class_required_material(self) -> None:
        concept = self._concept()
        self.assertEqual(concept.footage_request.required_sources[1].show_or_title, "Parent Series")

    def test_cross_title_sources_require_an_explicit_evidence_bound_concept_path(self) -> None:
        opportunity = self._opportunity()
        footage = self._footage()
        intent = intent_from_query("current TV character history edit")

        with self.assertRaisesRegex(ValueError, "different title"):
            _validate_pair_against_intent(intent, opportunity, footage)
        _validate_pair_against_intent(
            intent,
            opportunity,
            footage,
            allow_cross_title_sources=True,
        )

    def test_relationship_arc_can_span_multiple_seasons_via_compact_scene_pack(self) -> None:
        concept = self._concept()
        self.assertEqual(
            concept.footage_request.required_sources[1].asset_kind,
            SourceAcquisitionKind.SCENE_PACK,
        )
        self.assertGreaterEqual(len(concept.montage_arc), 4)

    def test_non_romance_character_evolution_route_is_valid(self) -> None:
        concept = self._concept(
            key="character_resilience",
            connection=LegacyConnectionType.NONE,
            central_subject="Ari's repeated failures becoming present-day resilience",
        )
        self.assertNotIn("romance", " ".join(concept.montage_arc).casefold())

    def test_comedy_callback_route_has_setup_and_return(self) -> None:
        concept = self._concept(
            key="comic_callback",
            connection=LegacyConnectionType.EXPLICIT_CALLBACK,
            central_subject="Ari and Bea's recurring joke gaining affectionate meaning",
        )
        self.assertIn("comic friction", concept.montage_arc[0])
        self.assertTrue(concept.ending_or_payoff.startswith("Return"))

    def test_new_title_without_specific_angle_fails_generic_gate(self) -> None:
        with self.assertRaisesRegex(ValueError, "generic get-clips"):
            self._concept(
                connection=LegacyConnectionType.NONE,
                central_subject="Get clips from this show and make an emotional edit",
            )

    def test_false_franchise_connection_is_rejected_without_canonical_evidence(self) -> None:
        concept = self._concept(connection=LegacyConnectionType.SAME_CANONICAL_UNIVERSE)
        claims = [
            SimpleNamespace(
                text="A current review discusses two unrelated performers.",
                episode_locator=None,
                quote_fact=None,
                why_now_event=None,
                scene_fact=None,
                cast_fact=None,
            )
        ]
        sources = [SimpleNamespace(title="Current review")]
        with self.assertRaisesRegex(ValueError, "unsupported canonical"):
            _validate_editorial_concept_copy(concept, claims=claims, sources=sources)

    def test_rumored_cameo_cannot_be_presented_as_verified_canon(self) -> None:
        with self.assertRaisesRegex(ValueError, "fan interpretation"):
            self._concept(
                connection=LegacyConnectionType.FAN_INTERPRETATION,
                verification=FootageVerificationLevel.VERIFIED,
            )

    def test_two_concepts_for_one_opportunity_keep_different_footage(self) -> None:
        selected = self._concept()
        character_footage = self._footage(legacy_title=None)
        alternate = self._concept(
            key="current_character_reaction",
            connection=LegacyConnectionType.NONE,
            footage=character_footage,
            central_subject="Ari's present-day reaction and resilience",
        )
        recommendation = SynthesisRecommendationDraftV2(
            opportunity=self._opportunity(),
            fandom_story_dossier=self._dossier(),
            editorial_concepts=[selected, alternate],
            recommended_concept_key=selected.concept_key,
        )
        self.assertNotEqual(
            recommendation.editorial_concepts[0].footage_request,
            recommendation.editorial_concepts[1].footage_request,
        )

    def test_generic_get_clips_request_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self._concept(central_subject="This show is trending. Get clips from this show")

    def test_minimum_set_can_be_one_current_episode_plus_one_legacy_pack(self) -> None:
        footage = self._concept().footage_request
        self.assertEqual(len(footage.required_sources), 2)
        self.assertEqual(
            [item.asset_kind for item in footage.required_sources],
            [SourceAcquisitionKind.EPISODE, SourceAcquisitionKind.SCENE_PACK],
        )

    def test_unknown_episode_exposes_uncertainty_without_locator(self) -> None:
        footage = self._footage(
            legacy_title=None,
            current_kind=SourceAcquisitionKind.SCENE_PACK,
            current_verification=FootageVerificationLevel.LIKELY_INFERRED,
            current_moment="The discussed reunion moment whose exact episode is unknown",
        ).model_copy(
            update={
                "warnings": [
                    "Exact dialogue and episode are not yet verified; provide a scene pack for later footage inspection."
                ]
            }
        )
        concept = self._concept(
            key="unknown_episode_reunion",
            connection=LegacyConnectionType.FAN_INTERPRETATION,
            footage=footage,
            verification=FootageVerificationLevel.LIKELY_INFERRED,
        )
        source = concept.footage_request.required_sources[0]
        self.assertIsNone(source.season_number)
        self.assertIn("not yet verified", concept.footage_request.warnings[0])

    def test_concept_score_is_derived_from_structure_and_uncertainty(self) -> None:
        strong = self._concept()
        weak_footage = self._footage(
            legacy_title=None,
            current_kind=SourceAcquisitionKind.SCENE_PACK,
            current_verification=FootageVerificationLevel.LIKELY_INFERRED,
            current_moment="A discussed reaction whose exact source is not known",
        )
        weak = self._concept(
            connection=LegacyConnectionType.NONE,
            footage=weak_footage,
            verification=FootageVerificationLevel.LIKELY_INFERRED,
            central_subject="Ari reacting to a difficult change",
        ).model_copy(
            update={
                "current_event": "A current title was released.",
                "ending_or_payoff": "End on another emotional scene.",
                "known_uncertainties": [
                    "Exact episode unknown",
                    "Exact event unknown",
                    "Reaction unverified",
                    "Payoff unverified",
                ],
            }
        )

        strong_score = score_editorial_concept(
            draft=strong,
            footage=strong.footage_request,
            evidence_quality=0.9,
        )
        weak_score = score_editorial_concept(
            draft=weak,
            footage=weak.footage_request,
            evidence_quality=0.6,
        )

        self.assertGreater(strong_score.total, weak_score.total)
        self.assertGreater(strong_score.concept_specificity, weak_score.concept_specificity)
        self.assertGreater(weak_score.uncertainty_penalty, strong_score.uncertainty_penalty)


if __name__ == "__main__":
    unittest.main()
