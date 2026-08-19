import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CostConsentPanel } from "../components/CostConsentPanel";
import { DEFAULT_RESEARCH_FORM_DRAFT, FindEditScreen } from "./FindEditScreen";
import { costPreviewFixture } from "../test/fixtures";

describe("Find an Edit and cost consent", () => {
  it("keeps the natural-language prompt authoritative when overrides are untouched", () => {
    const onPreview = vi.fn();
    render(<FindEditScreen draft={DEFAULT_RESEARCH_FORM_DRAFT} preview={null} busy={false} error={null} onDraftChange={vi.fn()} onPreview={onPreview} onApprove={vi.fn()} onDismissPreview={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Preview research" }));

    expect(onPreview).toHaveBeenCalledOnce();
    expect(onPreview.mock.calls[0]?.[0]).toMatchObject({
      prompt: "romance/romcom TV, preferably a new episode from the last three days, no K-drama, no reality TV",
      mediaKinds: null,
      region: null,
      freshnessDays: null,
      spoilerPolicy: null,
      exclusions: null,
      maxResults: null,
    });
  });

  it("shows every planned call, aggregate limits, and per-call privacy mode before consent", () => {
    render(<CostConsentPanel preview={costPreviewFixture} busy={false} onApprove={vi.fn()} onDismiss={vi.fn()} />);

    expect(screen.getAllByRole("article")).toHaveLength(3);
    expect(screen.getByText("research.metadata", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("research.web_verify", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("research.synthesize", { exact: false })).toBeInTheDocument();
    expect(screen.getAllByText("Privacy mode")).toHaveLength(3);
    expect(screen.getByText("Total maximum reservation")).toBeInTheDocument();
    expect(screen.getByText("Project hard limit")).toBeInTheDocument();
  });

  it("does not describe a zero-cost cache replay as a new warning-threshold crossing", () => {
    const cachedCall = {
      ...costPreviewFixture.plannedCalls[1]!,
      reservationMicroUsd: 0,
      cacheStatus: "HIT" as const,
      requiresLiveCall: false,
      costKind: "LOCAL_CACHE" as const,
    };
    render(<CostConsentPanel preview={{
      ...costPreviewFixture,
      plannedCalls: [cachedCall],
      maximumCostMicroUsd: 0,
      alreadySpentOrReservedMicroUsd: 6_953_771,
    }} busy={false} onApprove={vi.fn()} onDismiss={vi.fn()} />);

    expect(screen.getByRole("button", { name: "Use cached result" })).toBeInTheDocument();
    expect(screen.queryByText(/This reservation crosses/)).not.toBeInTheDocument();
  });
});
