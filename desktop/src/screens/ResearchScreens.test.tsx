import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { EvidenceView, OpportunityView, ResearchRunView } from "../domain/contracts";
import { noOpportunityRun, opportunityFixture } from "../test/fixtures";
import { FootageRequestScreen } from "./FootageRequestScreen";
import { OpportunitiesScreen } from "./OpportunitiesScreen";

describe("research result screens", () => {
  it("renders an honest no-opportunity outcome without manufacturing a card", () => {
    render(<OpportunitiesScreen run={noOpportunityRun} onSelect={vi.fn()} onOpenEvidence={vi.fn()} onCancel={vi.fn()} onStartOver={vi.fn()} />);

    expect(screen.getByRole("heading", { name: "No strong opportunity found under these constraints." })).toBeInTheDocument();
    expect(screen.getByText("7 metadata records examined · 0 verified why-now proofs · 0 current discussion signals.")).toBeInTheDocument();
    expect(screen.queryByText("Show me the footage request")).not.toBeInTheDocument();
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
        querySummary: "romance TV",
        freshnessCutoff: "2026-08-12T20:00:00Z",
        opportunities: [opportunityFixture],
      },
    };
    render(<OpportunitiesScreen run={run} onSelect={vi.fn()} onOpenEvidence={vi.fn()} onCancel={vi.fn()} onStartOver={vi.fn()} />);

    expect(screen.getByText("Why this could make an edit")).toBeInTheDocument();
    expect(screen.getByText(opportunityFixture.creativeHook)).toBeInTheDocument();
    expect(screen.getByText("2 required · 1 optional · 1 alternative")).toBeInTheDocument();
  });

  it("renders and selects every separately qualified opportunity", () => {
    const secondOpportunity = {
      ...opportunityFixture,
      opportunityId: "40000000-0000-4000-8000-000000000002",
      rank: 2,
      title: "Another Show: a distinct current hook",
    };
    const run: ResearchRunView = {
      ...noOpportunityRun,
      result: {
        outcome: "OPPORTUNITIES",
        querySummary: "current shows",
        freshnessCutoff: "2026-08-12T20:00:00Z",
        opportunities: [opportunityFixture, secondOpportunity],
      },
    };
    const onSelect = vi.fn();

    render(<OpportunitiesScreen run={run} onSelect={onSelect} onOpenEvidence={vi.fn()} onCancel={vi.fn()} onStartOver={vi.fn()} />);

    expect(screen.getByRole("heading", { name: opportunityFixture.title })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: secondOpportunity.title })).toBeInTheDocument();
    const requestButtons = screen.getAllByRole("button", { name: "Show me the footage request" });
    expect(requestButtons).toHaveLength(2);
    fireEvent.click(requestButtons[1]!);
    expect(onSelect).toHaveBeenCalledWith(secondOpportunity);
  });

  it("renders required, optional, and scene-pack alternatives with source-specific evidence and searches", () => {
    const onOpenEvidence = vi.fn();
    render(<FootageRequestScreen opportunity={opportunityFixture} onBack={vi.fn()} onStartOver={vi.fn()} onOpenEvidence={onOpenEvidence} />);

    expect(screen.getByRole("heading", { name: "Required" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Optional improvement" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Easier alternative" })).toBeInTheDocument();
    expect(screen.getByText("If that is easier, give me an Ada + Bea scene pack.")).toBeInTheDocument();
    expect(screen.getAllByText("Source-specific evidence")).toHaveLength(4);
    expect(screen.getAllByText("Example Show Ada and Bea scene pack").length).toBeGreaterThan(0);

    fireEvent.click(screen.getAllByRole("button", { name: "Open source in browser" })[0]!);
    expect(onOpenEvidence).toHaveBeenCalledWith("10000000-0000-4000-8000-000000000002");
  });

  it("renders the live fallback shape with an unknown scene pack and official-video link", () => {
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
    const onOpenEvidence = vi.fn();

    render(<FootageRequestScreen opportunity={liveShape} onBack={vi.fn()} onStartOver={vi.fn()} onOpenEvidence={onOpenEvidence} />);

    expect(screen.getByText("Any relevant female-centered material; the exact scene is unknown.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "official clip" })).toBeInTheDocument();
    expect(screen.getByText(officialEvidence.title)).toBeInTheDocument();
    expect(screen.getByText("No authoritative source locator is attached; treat this request as unknown.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open source in browser" }));
    expect(onOpenEvidence).toHaveBeenCalledWith(officialEvidence.linkHandle);
  });

  it("renders source and intro quote certainty, speaker, and likely context", () => {
    render(<FootageRequestScreen opportunity={opportunityFixture} onBack={vi.fn()} onStartOver={vi.fn()} onOpenEvidence={vi.fn()} />);

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
