import { useEffect, useMemo, useState } from "react";

import { tauriBackend, type BackendApi } from "./api/backend";
import { userFacingError } from "./api/errors";
import type {
  CostPreview,
  OpportunityView,
  ResearchIntentInput,
  ResearchRunView,
  ScreenId,
} from "./domain/contracts";
import {
  DEFAULT_RESEARCH_FORM_DRAFT,
  FindEditScreen,
  type ResearchFormDraft,
} from "./screens/FindEditScreen";
import { FootageRequestScreen } from "./screens/FootageRequestScreen";
import { OpportunitiesScreen } from "./screens/OpportunitiesScreen";
import { SettingsDiagnosticsScreen } from "./screens/SettingsDiagnosticsScreen";
import "./app.css";

interface AppProps {
  readonly api?: BackendApi;
}

export function App({ api = tauriBackend }: AppProps) {
  const [screen, setScreen] = useState<ScreenId>("find");
  const [returnScreen, setReturnScreen] = useState<Exclude<ScreenId, "settings">>("find");
  const [researchDraft, setResearchDraft] = useState<ResearchFormDraft>(DEFAULT_RESEARCH_FORM_DRAFT);
  const [intent, setIntent] = useState<ResearchIntentInput | null>(null);
  const [preview, setPreview] = useState<CostPreview | null>(null);
  const [run, setRun] = useState<ResearchRunView | null>(null);
  const [selectedOpportunityId, setSelectedOpportunityId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedOpportunity = useMemo<OpportunityView | null>(() => {
    if (selectedOpportunityId === null || run?.result?.outcome !== "OPPORTUNITIES") return null;
    return run.result.opportunities.find((item) => item.opportunityId === selectedOpportunityId) ?? null;
  }, [run, selectedOpportunityId]);
  const researchIsActive = run !== null
    && (run.status === "QUEUED" || run.status === "RUNNING" || run.status === "CANCELLING");

  useEffect(() => {
    if (run === null || (run.status !== "QUEUED" && run.status !== "RUNNING" && run.status !== "CANCELLING")) return;
    let active = true;
    let timer: number | undefined;
    let failures = 0;
    const poll = async (): Promise<void> => {
      try {
        const next = await api.getResearchRun(run.jobId);
        if (!active) return;
        setError(null);
        setRun(next);
      } catch (reason: unknown) {
        if (!active) return;
        failures += 1;
        const retryDelay = Math.min(750 * 2 ** failures, 6_000);
        const detail = userFacingError(reason, "Research status could not be refreshed.");
        setError(`${detail} Retrying status in ${Math.round(retryDelay / 1_000)} seconds.`);
        timer = window.setTimeout(() => { void poll(); }, retryDelay);
      }
    };
    timer = window.setTimeout(() => { void poll(); }, 750);
    return () => {
      active = false;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [api, run]);

  async function handlePreview(nextIntent: ResearchIntentInput): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      const nextPreview = await api.previewResearch(nextIntent);
      setIntent(nextIntent);
      setPreview(nextPreview);
    } catch (reason: unknown) {
      setError(userFacingError(reason, "Research could not be priced safely."));
    } finally {
      setBusy(false);
    }
  }

  async function handleStart(): Promise<void> {
    if (intent === null || preview === null) return;
    setBusy(true);
    setError(null);
    try {
      const nextRun = await api.startResearch(intent, preview.consentToken);
      setRun(nextRun);
      setScreen("opportunities");
    } catch (reason: unknown) {
      setError(userFacingError(reason, "Research could not start."));
    } finally {
      setBusy(false);
    }
  }

  async function handleCancel(): Promise<void> {
    if (run === null) return;
    setError(null);
    try {
      setRun(await api.cancelResearch(run.jobId));
    } catch (reason: unknown) {
      setError(userFacingError(reason, "Cancellation could not be confirmed."));
    }
  }

  function startOver(): void {
    if (researchIsActive) return;
    setScreen("find");
    setResearchDraft(DEFAULT_RESEARCH_FORM_DRAFT);
    setIntent(null);
    setPreview(null);
    setRun(null);
    setSelectedOpportunityId(null);
    setError(null);
  }

  function openSettings(): void {
    if (screen !== "settings") setReturnScreen(screen);
    setScreen("settings");
  }

  function openEvidence(linkHandle: string): void {
    void api.openEvidenceLink(linkHandle).catch((reason: unknown) => {
      setError(userFacingError(reason, "The trusted core rejected that link."));
    });
  }

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">Skip to content</a>
      <header className="app-header">
        <button
          type="button"
          className="brand-button"
          onClick={startOver}
          aria-label="AI Edit Machine home"
          disabled={researchIsActive}
          title={researchIsActive ? "Cancel or wait for the active research run before starting over." : undefined}
        >
          <span className="brand-mark" aria-hidden="true">A/E</span>
          <span>AI Edit Machine</span>
        </button>
        <nav aria-label="Research steps">
          <ol className="step-list">
            <li className={screen === "find" ? "active" : ""}>Find</li>
            <li className={screen === "opportunities" ? "active" : ""}>Opportunities</li>
            <li className={screen === "footage" ? "active" : ""}>Footage request</li>
          </ol>
        </nav>
        <button type="button" className="settings-button" onClick={openSettings}>Settings & diagnostics</button>
      </header>
      {error === null || screen === "find" ? null : <div className="global-error" role="alert">{error}</div>}
      {screen === "find" ? (
        <FindEditScreen
          draft={researchDraft}
          preview={preview}
          busy={busy}
          error={error}
          onDraftChange={setResearchDraft}
          onPreview={(value) => void handlePreview(value)}
          onApprove={() => void handleStart()}
          onDismissPreview={() => { setPreview(null); setError(null); }}
        />
      ) : null}
      {screen === "opportunities" && run !== null ? (
        <OpportunitiesScreen
          run={run}
          onSelect={(opportunity) => { setSelectedOpportunityId(opportunity.opportunityId); setScreen("footage"); }}
          onOpenEvidence={openEvidence}
          onCancel={() => void handleCancel()}
          onStartOver={startOver}
        />
      ) : null}
      {screen === "footage" && selectedOpportunity !== null ? (
        <FootageRequestScreen
          opportunity={selectedOpportunity}
          onBack={() => setScreen("opportunities")}
          onStartOver={startOver}
          onOpenEvidence={openEvidence}
        />
      ) : null}
      {screen === "settings" ? <SettingsDiagnosticsScreen api={api} onClose={() => setScreen(returnScreen)} /> : null}
      <footer className="app-footer">
        <span>Milestone 1 · Research only</span>
        <span>No footage ingestion, video analysis, or editing is active.</span>
      </footer>
    </div>
  );
}
