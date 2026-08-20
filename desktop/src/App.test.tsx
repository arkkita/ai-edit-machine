import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import type { BackendApi } from "./api/backend";
import type { ResearchRunView } from "./domain/contracts";
import { costPreviewFixture, diagnosticsFixture, noOpportunityRun } from "./test/fixtures";

const running: ResearchRunView = {
  jobId: noOpportunityRun.jobId,
  status: "RUNNING",
  progressPercent: 45,
  phase: "verifying evidence",
  result: null,
  provenance: noOpportunityRun.provenance,
  sanitizedError: null,
};

function backend(): BackendApi {
  return {
    getDiagnostics: vi.fn(async () => diagnosticsFixture),
    setProjectBudget: vi.fn(async () => undefined),
    previewResearch: vi.fn(async () => costPreviewFixture),
    startResearch: vi.fn(async () => running),
    getResearchRun: vi.fn()
      .mockRejectedValueOnce(new Error("Temporary database contention."))
      .mockResolvedValueOnce(noOpportunityRun),
    cancelResearch: vi.fn(async (): Promise<ResearchRunView> => ({ ...running, status: "CANCELLING" })),
    openEvidenceLink: vi.fn(async () => undefined),
    recordRecommendationFeedback: vi.fn(async () => undefined),
    getCredentialStatus: vi.fn(async (provider) => ({ provider, configured: false, locallyValid: false, lastValidatedAt: null })),
    storeCredential: vi.fn(async (provider) => ({ provider, configured: true, locallyValid: true, lastValidatedAt: null })),
    validateCredential: vi.fn(async (provider) => ({ provider, configured: true, locallyValid: true, lastValidatedAt: "2026-08-15T20:00:00Z" })),
    deleteCredential: vi.fn(async (provider) => ({ provider, configured: false, locallyValid: false, lastValidatedAt: null })),
  };
}

describe("active research polling", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("retries a transient status failure with bounded backoff and reaches the terminal result", async () => {
    const api = backend();
    render(<App api={api} />);

    fireEvent.click(screen.getByRole("button", { name: "Preview research" }));
    await act(async () => { await Promise.resolve(); });
    fireEvent.click(screen.getByRole("button", { name: "Approve and research" }));
    await act(async () => { await Promise.resolve(); });
    expect(screen.getByRole("heading", { name: "Looking for something real…" })).toBeInTheDocument();
    const home = screen.getByRole("button", { name: "AI Edit Machine home" });
    expect(home).toBeDisabled();
    fireEvent.click(home);
    expect(screen.getByRole("heading", { name: "Looking for something real…" })).toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(750);
      await Promise.resolve();
    });
    expect(screen.getByRole("alert")).toHaveTextContent("Retrying status");

    await act(async () => {
      vi.advanceTimersByTime(1_500);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByRole("heading", { name: "No strong opportunity found under these constraints." })).toBeInTheDocument();
    expect(api.getResearchRun).toHaveBeenCalledTimes(2);
  });
});

describe("trusted command errors", () => {
  it("shows an actionable stale-preflight error returned as a Tauri string", async () => {
    const api = backend();
    vi.mocked(api.previewResearch).mockRejectedValueOnce("openai model preflight is missing or stale");
    render(<App api={api} />);

    fireEvent.click(screen.getByRole("button", { name: "Preview research" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "OpenAI provider preflight expired. Open Settings & diagnostics, select openai, and run provider preflight; then preview again.",
    );
    expect(screen.queryByText("Research could not be priced safely.")).not.toBeInTheDocument();
  });

  it("preserves the complete research draft across diagnostics after a failed preview", async () => {
    const api = backend();
    vi.mocked(api.previewResearch)
      .mockRejectedValueOnce("openai model preflight is missing or stale")
      .mockResolvedValueOnce(costPreviewFixture);
    render(<App api={api} />);

    const prompt = screen.getByLabelText("What are you looking for?");
    const freshness = screen.getByLabelText("Freshness override");
    const count = screen.getByLabelText("Result-count override");
    fireEvent.change(prompt, { target: { value: "a good show for girls thatll get views on tiktok" } });
    fireEvent.change(freshness, { target: { value: "14" } });
    fireEvent.change(count, { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: "Preview research" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("OpenAI provider preflight expired");

    fireEvent.click(screen.getByRole("button", { name: "Settings & diagnostics" }));
    expect(screen.getByRole("heading", { name: "Trust should be inspectable." })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Done" }));

    expect(screen.getByLabelText("What are you looking for?")).toHaveValue(
      "a good show for girls thatll get views on tiktok",
    );
    expect(screen.getByLabelText("Freshness override")).toHaveValue("14");
    expect(screen.getByLabelText("Result-count override")).toHaveValue("5");

    fireEvent.click(screen.getByRole("button", { name: "Preview research" }));
    expect(await screen.findByRole("button", { name: "Approve and research" })).toBeInTheDocument();
    expect(api.previewResearch).toHaveBeenLastCalledWith(expect.objectContaining({
      prompt: "a good show for girls thatll get views on tiktok",
      freshnessDays: 14,
      maxResults: 5,
    }));
  });
});
