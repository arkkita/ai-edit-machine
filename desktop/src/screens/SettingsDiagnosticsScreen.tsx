import { useEffect, useState, type FormEvent } from "react";

import type { BackendApi } from "../api/backend";
import { userFacingError } from "../api/errors";
import type { CredentialProvider, CredentialStatusView, DiagnosticsView } from "../domain/contracts";
import { formatUsd } from "../domain/contracts";

const CREDENTIAL_PROVIDERS: readonly CredentialProvider[] = ["openai", "youtube", "xai"];

interface SettingsDiagnosticsScreenProps {
  readonly api: BackendApi;
  readonly onClose: () => void;
}

export function SettingsDiagnosticsScreen({ api, onClose }: SettingsDiagnosticsScreenProps) {
  const [diagnostics, setDiagnostics] = useState<DiagnosticsView | null>(null);
  const [statuses, setStatuses] = useState<Partial<Record<CredentialProvider, CredentialStatusView>>>({});
  const [provider, setProvider] = useState<CredentialProvider>("openai");
  const [secret, setSecret] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [projectBudgetUsd, setProjectBudgetUsd] = useState("");

  useEffect(() => {
    let active = true;
    async function load(): Promise<void> {
      try {
        const [nextDiagnostics, ...nextStatuses] = await Promise.all([
          api.getDiagnostics(),
          ...CREDENTIAL_PROVIDERS.map((value) => api.getCredentialStatus(value)),
        ]);
        if (!active) return;
        setDiagnostics(nextDiagnostics);
        setProjectBudgetUsd((current) => current || String(nextDiagnostics.projectHardBudgetMicroUsd / 1_000_000));
        setStatuses(Object.fromEntries(nextStatuses.map((status) => [status.provider, status])));
      } catch (error: unknown) {
        if (active) setMessage(error instanceof Error ? error.message : "Diagnostics could not be loaded.");
      }
    }
    void load();
    return () => { active = false; };
  }, [api]);

  async function store(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      const status = await api.storeCredential(provider, secret);
      setSecret("");
      setStatuses((current) => ({ ...current, [provider]: status }));
      setDiagnostics(await api.getDiagnostics());
      setMessage(`${provider} credential saved locally. No provider request was made; run provider preflight before research. The value will not be displayed again.`);
    } catch (error: unknown) {
      setMessage(userFacingError(error, "Credential could not be saved."));
    } finally {
      setBusy(false);
    }
  }

  async function validate(): Promise<void> {
    setBusy(true);
    try {
      const status = await api.validateCredential(provider);
      setStatuses((current) => ({ ...current, [provider]: status }));
      setDiagnostics(await api.getDiagnostics());
      setMessage(status.locallyValid && status.lastValidatedAt !== null
        ? `${provider} remote provider preflight succeeded at ${new Date(status.lastValidatedAt).toLocaleString()}.`
        : `${provider} credential is readable locally, but a current remote provider preflight was not recorded.`);
    } catch (error: unknown) {
      setMessage(userFacingError(error, "Credential validation failed."));
    } finally {
      setBusy(false);
    }
  }

  async function remove(): Promise<void> {
    setBusy(true);
    try {
      const status = await api.deleteCredential(provider);
      setStatuses((current) => ({ ...current, [provider]: status }));
      setDiagnostics(await api.getDiagnostics());
      setMessage(`${provider} credential deleted.`);
    } catch (error: unknown) {
      setMessage(userFacingError(error, "Credential could not be deleted."));
    } finally {
      setBusy(false);
    }
  }

  async function updateProjectBudget(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const dollars = Number(projectBudgetUsd);
    const hardBudgetMicroUsd = Math.round(dollars * 1_000_000);
    setBusy(true);
    setMessage(null);
    try {
      await api.setProjectBudget(hardBudgetMicroUsd);
      const nextDiagnostics = await api.getDiagnostics();
      setDiagnostics(nextDiagnostics);
      setProjectBudgetUsd(String(nextDiagnostics.projectHardBudgetMicroUsd / 1_000_000));
      setMessage(`Project hard budget updated to ${formatUsd(nextDiagnostics.projectHardBudgetMicroUsd)}. The per-run hard cap remains ${formatUsd(nextDiagnostics.hardBudgetMicroUsd)}.`);
    } catch (error: unknown) {
      setMessage(userFacingError(error, "Project budget could not be updated."));
    } finally {
      setBusy(false);
    }
  }

  const currentStatus = statuses[provider];
  const currentDiagnostic = diagnostics?.providers.find((item) => item.provider === provider);
  const preflightDisabled = currentDiagnostic?.enabled === false;
  return (
    <main className="screen" id="main-content">
      <header className="screen-heading">
        <div><p className="eyebrow">Settings · Diagnostics</p><h1>Trust should be inspectable.</h1></div>
        <button type="button" className="button quiet" onClick={onClose}>Done</button>
      </header>
      <section className="settings-card">
        <h2>Provider credentials</h2>
        <p>Secrets are written by Rust to Windows Credential Manager. Saved values are never returned to this screen.</p>
        <form onSubmit={(event) => void store(event)}>
          <div className="form-grid">
            <label>Provider<select value={provider} onChange={(event) => setProvider(event.currentTarget.value as CredentialProvider)}>{CREDENTIAL_PROVIDERS.map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
            <label>New API key<input type="password" autoComplete="off" value={secret} onChange={(event) => setSecret(event.currentTarget.value)} /></label>
          </div>
          <p className="status-line">
            Local key: {currentStatus?.configured === true ? currentStatus.locallyValid ? "saved and readable" : "saved, local validation pending" : "not configured"}
            {currentStatus?.lastValidatedAt === null || currentStatus?.lastValidatedAt === undefined
              ? " · Remote provider preflight: not current"
              : ` · Remote provider preflight: ${new Date(currentStatus.lastValidatedAt).toLocaleString()}`}
          </p>
          {currentDiagnostic?.killSwitchReason === null || currentDiagnostic?.killSwitchReason === undefined ? null : (
            <p className="budget-warning" role="status"><strong>Provider disabled:</strong> {currentDiagnostic.killSwitchReason}</p>
          )}
          <div className="button-row">
            <button className="button primary" type="submit" disabled={busy || secret.length === 0}>Save securely</button>
            <button className="button quiet" type="button" disabled={busy || currentStatus?.configured !== true || preflightDisabled} onClick={() => void validate()}>Run provider preflight</button>
            <button className="button danger" type="button" disabled={busy || currentStatus?.configured !== true} onClick={() => void remove()}>Delete</button>
          </div>
        </form>
        {message === null ? null : <p role="status" className="status-message">{message}</p>}
      </section>
      <section className="settings-card">
        <h2>Runtime diagnostics</h2>
        {diagnostics === null ? <p>Loading diagnostics…</p> : (
          <>
            <dl className="fact-grid">
              <div><dt>App</dt><dd>{diagnostics.appVersion}</dd></div>
              <div><dt>Build</dt><dd><code>{diagnostics.buildIdentifier}</code>{diagnostics.buildIsDirty ? " · dirty" : " · checkpoint"}</dd></div>
              <div><dt>Build timestamp</dt><dd>{new Date(diagnostics.buildTimestampUnixMs).toLocaleString()}</dd></div>
              <div><dt>Pipeline</dt><dd><code>{diagnostics.pipelineVersion}</code></dd></div>
              <div><dt>Provider configuration</dt><dd><code>{diagnostics.providerConfigId}</code></dd></div>
              <div><dt>Worker manifest</dt><dd><code title={diagnostics.workerManifestSha256}>{diagnostics.workerManifestSha256.slice(0, 16)}…</code></dd></div>
              <div><dt>Protocol</dt><dd>{diagnostics.protocolVersion}</dd></div>
              <div><dt>Worker</dt><dd>{diagnostics.workerStatus.toLowerCase()}</dd></div>
              <div><dt>Worker build</dt><dd>{diagnostics.workerVersion ?? "not packaged"}</dd></div>
              <div><dt>SQLite</dt><dd>{diagnostics.sqliteVersion} · FTS5 {diagnostics.sqliteFts5 ? "on" : "off"}</dd></div>
              <div><dt>Research budget</dt><dd>{formatUsd(diagnostics.warningBudgetMicroUsd)} warning / {formatUsd(diagnostics.hardBudgetMicroUsd)} hard</dd></div>
              <div><dt>Project hard budget</dt><dd>{formatUsd(diagnostics.projectHardBudgetMicroUsd)}</dd></div>
            </dl>
            <form onSubmit={(event) => void updateProjectBudget(event)}>
              <div className="form-grid">
                <label>Project hard budget (USD)<input type="number" min="0.5" max="100" step="0.5" value={projectBudgetUsd} onChange={(event) => setProjectBudgetUsd(event.currentTarget.value)} /></label>
              </div>
              <p className="fine-print">This is the cumulative Milestone 1 project ceiling. The separate $0.50 hard cap for each research run remains enforced.</p>
              <div className="button-row"><button className="button quiet" type="submit" disabled={busy || !Number.isFinite(Number(projectBudgetUsd)) || Number(projectBudgetUsd) < 0.5 || Number(projectBudgetUsd) > 100}>Update project budget</button></div>
            </form>
            <div className="diagnostic-table-wrap">
              <table>
                <caption>Provider capabilities</caption>
                <thead><tr><th>Provider</th><th>Status</th><th>Model</th><th>Policy review</th><th>Privacy and retention</th><th>Cache/purge</th></tr></thead>
                <tbody>{diagnostics.providers.map((item) => (
                  <tr key={item.provider}>
                    <th scope="row">{item.provider}</th>
                    <td>{item.availability.toLowerCase()}{item.killSwitchReason === null ? null : <><br /><span className="fine-print">{item.killSwitchReason}</span></>}</td>
                    <td>{item.configuredModel ?? "n/a"}<br /><span className="fine-print">Resolved: {item.resolvedModel ?? "not preflighted"}</span></td>
                    <td>
                      {new Date(item.policyCheckedAt).toLocaleString()} – {new Date(item.policyExpiresAt).toLocaleString()}
                      <br /><span className="fine-print">Price: {item.priceCardCheckedAt === null ? "not applicable" : new Date(item.priceCardCheckedAt).toLocaleString()}</span>
                    </td>
                    <td>{item.retentionMode}<br /><span className="fine-print">{item.dataUseMode}; {item.noStorageMode}; privacy: {item.privacyMode}</span></td>
                    <td>{item.cachePolicy}<br /><span className="fine-print">Purge after {Math.round(item.purgeAfterSeconds / 86_400)} days</span></td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          </>
        )}
      </section>
    </main>
  );
}
