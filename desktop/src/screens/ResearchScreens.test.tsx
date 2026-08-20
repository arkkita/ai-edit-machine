import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { EvidenceView, OpportunityView, ResearchRunView } from "../domain/contracts";
import { editorialConceptFixture, noOpportunityRun, opportunityFixture, opportunityWithConceptFixture } from "../test/fixtures";
import { FootageRequestScreen } from "./FootageRequestScreen";
import { OpportunitiesScreen } from "./OpportunitiesScreen";

const RESULT_PROVENANCE = {
  researchRunId: noOpportunityRun.provenance.researchRunId!,
  runTimestamp: noOpportunityRun.provenance.runTimestamp!,
  pipelineVersion: noOpportunityRun.provenance.pipelineVersion,
  providerConfigId: noOpportunityRun.provenance.providerConfigId,
};

describe("research result screens", () => {
  it("renders an honest no-opportunity outcome without manufacturing a card", () => {
    render(<OpportunitiesScreen run={noOpportunityRun} onSelect={vi.fn()} onOpenEvidence={vi.fn()} onCancel={vi.fn()} onStartOver={vi.fn()} />);

    expect(screen.getByRole("heading", { name: "No strong opportunity found under these constraints." })).toBeInTheDocument();
    expect(screen.getByText("7 metadata records examined · 0 verified why-now proofs · 0 current discussion signals.")).toBeInTheDocument();
    expect(screen.queryByText("Show me the footage request")).not.toBeInTheDocument();
  });

  it("shows candidate-level rejection reasons after a zero-result recovery pass", () => {
    const noResult = noOpportunityRun.result;
    if (noResult?.outcome !== "NO_STRONG_OPPORTUNITY") throw new Error("fixture must be a no-opportunity result");
    const run: ResearchRunView = {
      ...noOpportunityRun,
      result: {
        ...noResult,
        candidateFunnel: {
          parsedIntent: 1,
          generatedSearchVariants: 10,
          rawReleaseCandidates: 30,
          candidatesAfterFreshness: 30,
          candidatesAfterHardExclusions: 30,
          candidatesAfterAudienceFitScreening: 30,
          candidatesSelectedForSocialResearch: 1,
          candidatesWithUsableSocialEvidence: 1,
          candidatesSurvivingEvidenceGates: 1,
          candidatesSurvivingDeduplication: 0,
          candidatesSentToFinalRanker: 0,
          finalOpportunitiesSerialized: 0,
          finalOpportunitiesReceivedByRust: 0,
          finalOpportunitiesDisplayedByUi: 0,
          removedByHardConstraints: 0,
          lackingCurrentFandomEvidence: 0,
          lackingActionableFootageInformation: 1,
          falseAbstentionRecoveryAttempted: true,
          recoveredCandidateCount: 1,
          evidenceCoverageWarning: "Recovery found evidence, but no supported editorial concept survived.",
          rejectionReasons: [{ reasonCode: "concept:missing-editorial-concept", count: 1 }],
          candidateDiagnostics: [{
            candidateName: "Recovery Show — S01E03 The Turn",
            title: "Recovery Show",
            shortlistRank: 1,
            shortlistReason: "Selected by the bounded semantic audience/editability title-slate pass.",
            currentHook: "The current episode is The Turn.",
            audienceFitEvidence: ["Current female-led ensemble coverage."],
            fandomEvidence: ["Current viewers discuss the central relationship."],
            storyOrEpisodeEvidence: ["TVmaze lists The Turn as Season 1 Episode 3."],
            sourceCategories: ["openai:ARTICLE:VIEWER_DISCUSSION", "tvmaze:METADATA:EPISODE_IDENTITY"],
            evidenceReferences: ["10000000-0000-4000-8000-000000000001"],
            inferredShortFormEditPotential: "PROMISING SIGNALS, NOT SCORED: direct TikTok data was not used.",
            scoresAndThresholds: [{
              metric: "concept_specificity",
              value: null,
              countValue: null,
              threshold: 0.5,
              countThreshold: null,
              status: "NOT_COMPUTED",
              note: "Computed only after a dossier-backed concept exists.",
            }],
            exactRejectionGate: "THRESHOLD:NO_SUPPORTED_EDITORIAL_CONCEPT",
            failureClass: "THRESHOLD_RELATED",
          }],
          shortageExplanation: "One researched title lacked an actionable concept.",
          suggestions: ["Try a narrower relationship angle."],
        },
      },
    };

    render(<OpportunitiesScreen run={run} onSelect={vi.fn()} onOpenEvidence={vi.fn()} onCancel={vi.fn()} onStartOver={vi.fn()} />);

    expect(screen.getByText("Candidate-level diagnosis (1 researched titles)")).toBeInTheDocument();
    expect(screen.getByText(/THRESHOLD:NO_SUPPORTED_EDITORIAL_CONCEPT/)).toBeInTheDocument();
    expect(screen.getByText(/PROMISING SIGNALS, NOT SCORED/)).toBeInTheDocument();
  });

  it("does not repeat the canonical no-opportunity explanation", () => {
    const noResult = noOpportunityRun.result;
    if (noResult?.outcome !== "NO_STRONG_OPPORTUNITY") {
      throw new Error("fixture must be a no-opportunity result");
    }
    const run: ResearchRunView = {
      ...noOpportunityRun,
      result: {
        ...noResult,
        explanation: "No strong opportunity found under these constraints.",
      },
    };

    render(<OpportunitiesScreen run={run} onSelect={vi.fn()} onOpenEvidence={vi.fn()} onCancel={vi.fn()} onStartOver={vi.fn()} />);

    expect(screen.getAllByText("No strong opportunity found under these constraints.")).toHaveLength(1);
  });

  it("shows evidence-specific creative reasoning on an opportunity card", () => {
    const run: ResearchRunView = {
      ...noOpportunityRun,
      result: {
        outcome: "OPPORTUNITIES",
        ...RESULT_PROVENANCE,
        querySummary: "romance TV",
        freshnessCutoff: "2026-08-12T20:00:00Z",
        interpretation: null,
        candidateFunnel: null,
        opportunities: [opportunityWithConceptFixture],
      },
    };
    render(<OpportunitiesScreen run={run} onSelect={vi.fn()} onOpenEvidence={vi.fn()} onCancel={vi.fn()} onStartOver={vi.fn()} />);

    expect(screen.getByText("Why this could make an edit")).toBeInTheDocument();
    expect(screen.getByText(opportunityFixture.creativeHook)).toBeInTheDocument();
    expect(screen.getByText("2 required · 1 optional · 1 alternative")).toBeInTheDocument();
  });

  it("renders and selects every separately qualified opportunity", () => {
    const secondOpportunity = {
      ...opportunityWithConceptFixture,
      opportunityId: "40000000-0000-4000-8000-000000000002",
      rank: 2,
      title: "Another Show: a distinct current hook",
    };
    const run: ResearchRunView = {
      ...noOpportunityRun,
      result: {
        outcome: "OPPORTUNITIES",
        ...RESULT_PROVENANCE,
        querySummary: "current shows",
        freshnessCutoff: "2026-08-12T20:00:00Z",
        interpretation: null,
        candidateFunnel: null,
        opportunities: [opportunityWithConceptFixture, secondOpportunity],
      },
    };
    const onSelect = vi.fn();

    render(<OpportunitiesScreen run={run} onSelect={onSelect} onOpenEvidence={vi.fn()} onCancel={vi.fn()} onStartOver={vi.fn()} />);

    expect(screen.getByRole("heading", { name: opportunityWithConceptFixture.title })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: secondOpportunity.title })).toBeInTheDocument();
    const requestButtons = screen.getAllByRole("button", { name: "Show the recommended concept’s footage request" });
    expect(requestButtons).toHaveLength(2);
    fireEvent.click(requestButtons[1]!);
    expect(onSelect).toHaveBeenCalledWith(secondOpportunity, secondOpportunity.recommendedConceptId);
  });

  it("records and routes a generate-another-idea request to a reviewable rerun", async () => {
    const run: ResearchRunView = {
      ...noOpportunityRun,
      result: {
        outcome: "OPPORTUNITIES",
        ...RESULT_PROVENANCE,
        querySummary: "relationship TV",
        freshnessCutoff: "2026-08-12T20:00:00Z",
        interpretation: null,
        candidateFunnel: null,
        opportunities: [opportunityWithConceptFixture],
      },
    };
    const onFeedback = vi.fn(async () => undefined);
    const onGenerateAnotherIdea = vi.fn();

    render(
      <OpportunitiesScreen
        run={run}
        onSelect={vi.fn()}
        onOpenEvidence={vi.fn()}
        onFeedback={onFeedback}
        onGenerateAnotherIdea={onGenerateAnotherIdea}
        onCancel={vi.fn()}
        onStartOver={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Generate another idea" }));
    await waitFor(() => expect(onFeedback).toHaveBeenCalledWith(
      opportunityWithConceptFixture.opportunityId,
      opportunityWithConceptFixture.editorialConcepts[0]!.conceptId,
      "GENERATE_ANOTHER_IDEA",
    ));
    expect(onGenerateAnotherIdea).toHaveBeenCalledWith(
      opportunityWithConceptFixture,
      opportunityWithConceptFixture.editorialConcepts[0]!.title,
    );
  });

  it("renders required, optional, and scene-pack alternatives with source-specific evidence and searches", () => {
    const onOpenEvidence = vi.fn();
    render(<FootageRequestScreen opportunity={opportunityWithConceptFixture} concept={editorialConceptFixture} provenance={noOpportunityRun.provenance} onBack={vi.fn()} onStartOver={vi.fn()} onOpenEvidence={onOpenEvidence} />);

    expect(screen.getByRole("heading", { name: "Required" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Optional improvement" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Easier alternative" })).toBeInTheDocument();
    expect(screen.getByText("If that is easier, give me an Ada + Bea scene pack.")).toBeInTheDocument();
    expect(screen.getAllByText("Source-specific evidence")).toHaveLength(4);
    expect(screen.getAllByText("Example Show Ada and Bea scene pack").length).toBeGreaterThan(0);

    fireEvent.click(screen.getAllByRole("button", { name: "Open source in browser" })[0]!);
    expect(onOpenEvidence).toHaveBeenCalledWith("10000000-0000-4000-8000-000000000002");
  });

  it("rejects the former generic unknown-scene fallback when no supported concept owns it", () => {
    const baseRequired = opportunityFixture.footageRequest.requiredSources[0]!;
    const baseOptional = opportunityFixture.footageRequest.optionalSources[0]!;
    const officialEvidence: EvidenceView = {
      ...opportunityFixture.evidence[0]!,
      evidenceId: "50000000-0000-4000-8000-000000000001",
      sourceId: "50000000-0000-4000-8000-000000000002",
      claimId: "50000000-0000-4000-8000-000000000001",
      provider: "youtube",
      title: "Stuart Fails to Save the Universe | Episode 4 Preview | HBO Max",
      publisher: "HBO Max",
      sourceType: "OFFICIAL_CLIP" as const,
      excerpt: "HBO Max published an exact-title episode preview.",
      linkHandle: "50000000-0000-4000-8000-000000000002",
    };
    const liveShape: OpportunityView = {
      ...opportunityFixture,
      footageRequest: {
        ...opportunityFixture.footageRequest,
        naturalRequest: {
          best: "Give me a female-centered scene pack.",
          alternative: null,
          minimum: "The smallest useful set is a female-centered scene pack.",
          optionalImprovement: "If you have it, the official preview would add another emotional option.",
        },
        minimumUsefulSourceKeys: ["current_scene_pack"],
        requiredSources: [{
          ...baseRequired,
          sourceId: "50000000-0000-4000-8000-000000000003",
          sourceKey: "current_scene_pack",
          assetKind: "SCENE_PACK",
          seasonNumber: null,
          episodeNumber: null,
          episodeTitle: null,
          characters: [],
          relationshipOrTopic: "female-centered discussion",
          sceneOrMoment: "Any relevant female-centered material; the exact scene is unknown.",
          quote: null,
          verificationLevel: "UNKNOWN",
          sourceQualitySummary: "The discussion supports the topic, but not a particular scene.",
          supportingEvidence: [],
          searchQueries: ["current show female-centered scene pack"],
        }],
        optionalSources: [{
          ...baseOptional,
          sourceId: "50000000-0000-4000-8000-000000000004",
          sourceKey: "official_preview",
          assetKind: "OFFICIAL_CLIP",
          seasonNumber: null,
          episodeNumber: null,
          episodeTitle: null,
          characters: [],
          relationshipOrTopic: null,
          sceneOrMoment: "Episode 4 Preview",
          quote: null,
          verificationLevel: "VERIFIED",
          sourceQualitySummary: "Reviewed official-channel metadata verifies the link and source-owned label.",
          supportingClaimIds: [officialEvidence.claimId],
          supportingEvidence: [officialEvidence],
          searchQueries: ["Stuart Fails to Save the Universe Episode 4 Preview official video"],
        }],
        alternativeSources: [],
        introLeads: [],
        searchQueries: ["current show female-centered scene pack"],
      },
    };
    render(<FootageRequestScreen opportunity={liveShape} concept={null} provenance={noOpportunityRun.provenance} onBack={vi.fn()} onStartOver={vi.fn()} onOpenEvidence={vi.fn()} />);

    expect(screen.getByRole("heading", { name: "No supported concept is selected." })).toBeInTheDocument();
    expect(screen.queryByText("Any relevant female-centered material; the exact scene is unknown.")).not.toBeInTheDocument();
  });

  it("renders source and intro quote certainty, speaker, and likely context", () => {
    render(<FootageRequestScreen opportunity={opportunityWithConceptFixture} concept={editorialConceptFixture} provenance={noOpportunityRun.provenance} onBack={vi.fn()} onStartOver={vi.fn()} onOpenEvidence={vi.fn()} />);

    const sourceQuote = screen.getByLabelText("Source quote for s3e3");
    expect(within(sourceQuote).getByText("“I choose you.”")).toBeInTheDocument();
    expect(sourceQuote).toHaveTextContent("Ada · verified · authoritative quote evidence attached");
    expect(sourceQuote).toHaveTextContent("Likely context: The trust conversation.");

    const introQuote = screen.getByLabelText("Intro quote lead for s3e3");
    expect(within(introQuote).getByText("“Maybe we can try again.”")).toBeInTheDocument();
    expect(introQuote).toHaveTextContent("Bea · unverified lead · wording or attribution is not authoritative");
    expect(introQuote).toHaveTextContent("Likely context: Immediately after the trust conversation.");
  });
});
