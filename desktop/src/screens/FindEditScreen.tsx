import { useMemo, type FormEvent } from "react";

import type { CostPreview, ResearchIntentInput } from "../domain/contracts";
import { CONTRACT_VERSION } from "../domain/contracts";
import { CostConsentPanel } from "../components/CostConsentPanel";

interface FindEditScreenProps {
  readonly draft: ResearchFormDraft;
  readonly preview: CostPreview | null;
  readonly busy: boolean;
  readonly error: string | null;
  readonly onDraftChange: (draft: ResearchFormDraft) => void;
  readonly onPreview: (intent: ResearchIntentInput) => void;
  readonly onApprove: () => void;
  readonly onDismissPreview: () => void;
}

export interface ResearchFormDraft {
  readonly prompt: string;
  readonly freshnessDays: "" | "1" | "3" | "7" | "14";
  readonly maxResults: "" | "3" | "4" | "5";
  readonly region: "" | "US" | "CA" | "GB" | "AU";
  readonly spoilerPolicy: "" | NonNullable<ResearchIntentInput["spoilerPolicy"]>;
  readonly mediaOverride: "" | "TV" | "FILM" | "TV_AND_FILM";
  readonly exclusions: string;
}

export const DEFAULT_RESEARCH_FORM_DRAFT: ResearchFormDraft = {
  prompt: "romance/romcom TV, preferably a new episode from the last three days, no K-drama, no reality TV",
  freshnessDays: "",
  maxResults: "",
  region: "",
  spoilerPolicy: "",
  mediaOverride: "",
  exclusions: "",
};

export function FindEditScreen({
  draft,
  preview,
  busy,
  error,
  onDraftChange,
  onPreview,
  onApprove,
  onDismissPreview,
}: FindEditScreenProps) {
  function updateDraft<Key extends keyof ResearchFormDraft>(key: Key, value: ResearchFormDraft[Key]): void {
    onDraftChange({ ...draft, [key]: value });
  }

  const parsedExclusions = useMemo(
    () => draft.exclusions.trim().length === 0
      ? null
      : draft.exclusions.split(",").map((value) => value.trim()).filter((value) => value.length > 0),
    [draft.exclusions],
  );

  function submit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    onPreview({
      schemaVersion: CONTRACT_VERSION,
      prompt: draft.prompt.trim(),
      mediaKinds: draft.mediaOverride === "TV" ? ["TV_EPISODE"] : draft.mediaOverride === "FILM" ? ["FILM"] : draft.mediaOverride === "TV_AND_FILM" ? ["TV_EPISODE", "FILM", "TRAILER"] : null,
      region: draft.region === "" ? null : draft.region,
      freshnessDays: draft.freshnessDays === "" ? null : Number(draft.freshnessDays),
      spoilerPolicy: draft.spoilerPolicy === "" ? null : draft.spoilerPolicy,
      exclusions: parsedExclusions,
      maxResults: draft.maxResults === "" ? null : Number(draft.maxResults),
    });
  }

  return (
    <main className="screen find-screen" id="main-content">
      <header className="hero">
        <p className="eyebrow">Screen A · Find an edit</p>
        <h1>What feels worth editing right now?</h1>
        <p>
          Describe the audience and mood. The researcher will look for a small number of current,
          evidence-backed ideas—and tell you exactly what footage would make each one possible.
        </p>
      </header>
      <form className="research-form" onSubmit={submit}>
        <label htmlFor="research-prompt">What are you looking for?</label>
        <textarea
          id="research-prompt"
          rows={5}
          maxLength={4_000}
          value={draft.prompt}
          onChange={(event) => updateDraft("prompt", event.currentTarget.value)}
          disabled={busy || preview !== null}
          required
        />
        <div className="form-grid">
          <label>
            Freshness override
            <select value={draft.freshnessDays} onChange={(event) => updateDraft("freshnessDays", event.currentTarget.value as ResearchFormDraft["freshnessDays"])} disabled={busy || preview !== null}>
              <option value="">Read it from my request</option>
              <option value="1">Last day</option>
              <option value="3">Last 3 days</option>
              <option value="7">Last 7 days</option>
              <option value="14">Last 14 days</option>
            </select>
          </label>
          <label>
            Region override
            <select value={draft.region} onChange={(event) => updateDraft("region", event.currentTarget.value as ResearchFormDraft["region"])} disabled={busy || preview !== null}>
              <option value="">Read it from my request</option>
              <option value="US">United States</option>
              <option value="CA">Canada</option>
              <option value="GB">United Kingdom</option>
              <option value="AU">Australia</option>
            </select>
          </label>
          <label>
            Result-count override
            <select value={draft.maxResults} onChange={(event) => updateDraft("maxResults", event.currentTarget.value as ResearchFormDraft["maxResults"])} disabled={busy || preview !== null}>
              <option value="">Read it from my request</option>
              <option value={3}>3</option>
              <option value={4}>4</option>
              <option value={5}>5</option>
            </select>
          </label>
          <label>
            Spoiler override
            <select value={draft.spoilerPolicy} onChange={(event) => updateDraft("spoilerPolicy", event.currentTarget.value as ResearchFormDraft["spoilerPolicy"])} disabled={busy || preview !== null}>
              <option value="">Read it from my request</option>
              <option value="AVOID">Avoid spoilers</option>
              <option value="CURRENT_EPISODE">Current-episode context</option>
              <option value="ALLOW">Allow spoilers</option>
            </select>
          </label>
          <label>
            Additional exclusions (optional)
            <input value={draft.exclusions} onChange={(event) => updateDraft("exclusions", event.currentTarget.value)} disabled={busy || preview !== null} />
          </label>
        </div>
        <label>
          Media override
          <select value={draft.mediaOverride} onChange={(event) => updateDraft("mediaOverride", event.currentTarget.value as ResearchFormDraft["mediaOverride"])} disabled={busy || preview !== null}>
            <option value="">Read it from my request</option>
            <option value="TV">TV episodes only</option>
            <option value="FILM">Films only</option>
            <option value="TV_AND_FILM">TV, films, and trailers</option>
          </select>
        </label>
        {error === null ? null : <p role="alert" className="error-banner">{error}</p>}
        {preview === null ? (
          <button className="button primary" type="submit" disabled={busy || draft.prompt.trim().length === 0}>
            {busy ? "Checking cost…" : "Preview research"}
          </button>
        ) : (
          <CostConsentPanel preview={preview} busy={busy} onApprove={onApprove} onDismiss={onDismissPreview} />
        )}
      </form>
      <aside className="principle-card">
        <strong>Honesty is part of the result.</strong>
        <p>If the evidence is weak, the researcher can say “No strong opportunity found under these constraints.”</p>
      </aside>
    </main>
  );
}
