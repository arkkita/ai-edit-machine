import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { BackendApi } from "../api/backend";
import { diagnosticsFixture } from "../test/fixtures";
import { SettingsDiagnosticsScreen } from "./SettingsDiagnosticsScreen";

function backend(): BackendApi {
  return {
    getDiagnostics: vi.fn(async () => diagnosticsFixture),
    setProjectBudget: vi.fn(async () => undefined),
    previewResearch: vi.fn(),
    startResearch: vi.fn(),
    getResearchRun: vi.fn(),
    cancelResearch: vi.fn(),
    openEvidenceLink: vi.fn(),
    recordRecommendationFeedback: vi.fn(),
    getCredentialStatus: vi.fn(async (provider) => ({ provider, configured: provider === "openai", locallyValid: provider === "openai", lastValidatedAt: null })),
    storeCredential: vi.fn(async (provider) => ({ provider, configured: true, locallyValid: true, lastValidatedAt: null })),
    validateCredential: vi.fn(async (provider) => ({ provider, configured: true, locallyValid: true, lastValidatedAt: "2026-08-15T20:00:00Z" })),
    deleteCredential: vi.fn(async (provider) => ({ provider, configured: false, locallyValid: false, lastValidatedAt: null })),
  };
}

describe("settings and diagnostics", () => {
  it("defaults to enabled OpenAI and disables remote validation for kill-switched providers", async () => {
    render(<SettingsDiagnosticsScreen api={backend()} onClose={vi.fn()} />);

    const provider = await screen.findByLabelText("Provider");
    expect(provider).toHaveValue("openai");
    expect((await screen.findAllByText("store=false", { exact: false })).length).toBeGreaterThan(0);

    fireEvent.change(provider, { target: { value: "xai" } });
    expect(screen.getByRole("button", { name: "Run provider preflight" })).toBeDisabled();
    expect(screen.getAllByText("Live adversarial invocation-cap proof has not been recorded.").length).toBeGreaterThan(0);
  });

  it("describes a save as local-only rather than a successful provider preflight", async () => {
    const api = backend();
    render(<SettingsDiagnosticsScreen api={api} onClose={vi.fn()} />);
    await screen.findByLabelText("Provider");

    fireEvent.change(screen.getByLabelText("New API key"), { target: { value: "sk-test-not-a-real-secret" } });
    fireEvent.click(screen.getByRole("button", { name: "Save securely" }));

    expect(await screen.findByText("No provider request was made", { exact: false })).toBeInTheDocument();
    expect(api.validateCredential).not.toHaveBeenCalled();
  });

  it("changes the cumulative project ceiling without changing the per-run cap", async () => {
    const api = backend();
    vi.mocked(api.getDiagnostics)
      .mockResolvedValueOnce(diagnosticsFixture)
      .mockResolvedValueOnce({ ...diagnosticsFixture, projectHardBudgetMicroUsd: 5_000_000 });
    render(<SettingsDiagnosticsScreen api={api} onClose={vi.fn()} />);

    const budget = await screen.findByLabelText("Project hard budget (USD)");
    fireEvent.change(budget, { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: "Update project budget" }));

    expect(api.setProjectBudget).toHaveBeenCalledWith(5_000_000);
    expect(await screen.findByText("The per-run hard cap remains $0.50.", { exact: false })).toBeInTheDocument();
  });
});
