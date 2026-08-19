import type { CostPreview } from "../domain/contracts";
import { formatUsd } from "../domain/contracts";

interface CostConsentPanelProps {
  readonly preview: CostPreview;
  readonly busy: boolean;
  readonly onApprove: () => void;
  readonly onDismiss: () => void;
}

export function CostConsentPanel({ preview, busy, onApprove, onDismiss }: CostConsentPanelProps) {
  const requiresLiveCall = preview.plannedCalls.some((call) => call.requiresLiveCall);
  const crossesWarning = requiresLiveCall
    && preview.maximumCostMicroUsd > 0
    && preview.alreadySpentOrReservedMicroUsd + preview.maximumCostMicroUsd > preview.effectiveWarningMicroUsd;
  return (
    <section className="cost-panel" aria-labelledby="cost-preview-title">
      <div>
        <p className="eyebrow">Before any cloud request</p>
        <h2 id="cost-preview-title">Research cost and privacy</h2>
      </div>
      <div className="call-plan" aria-label="Planned provider calls">
        {preview.plannedCalls.map((call) => (
          <article key={call.callId} className="call-plan-row">
            <div className="call-plan-heading">
              <div>
                <p className="eyebrow">{call.provider} · {call.operation}</p>
                <h3>{call.resolvedModel ?? call.configuredModel ?? "No model (metadata request)"}</h3>
              </div>
              <strong>{formatUsd(call.reservationMicroUsd)}</strong>
            </div>
            <dl className="compact-facts">
              <div><dt>Call type</dt><dd>{call.costKind.replaceAll("_", " ").toLowerCase()}</dd></div>
              <div><dt>Cache</dt><dd>{call.cacheStatus.toLowerCase()}</dd></div>
              <div><dt>Price checked</dt><dd>{call.priceCardCheckedAtMs === null ? "Free / not applicable" : <time dateTime={new Date(call.priceCardCheckedAtMs).toISOString()}>{new Date(call.priceCardCheckedAtMs).toLocaleString()}</time>}</dd></div>
              <div><dt>No-storage mode</dt><dd>{call.noStorageMode}</dd></div>
              <div><dt>Privacy mode</dt><dd>{call.privacyMode}</dd></div>
            </dl>
            <div className="notice-stack">
              <p><strong>Retention:</strong> {call.retentionSummary}</p>
              <p><strong>Data use:</strong> {call.dataUseSummary}</p>
              <p><strong>Cheaper/local alternative:</strong> {call.cheaperAlternative}</p>
            </div>
          </article>
        ))}
      </div>
      <dl className="fact-grid">
        <div><dt>Total maximum reservation</dt><dd>{formatUsd(preview.maximumCostMicroUsd)}</dd></div>
        <div><dt>Already spent/reserved</dt><dd>{formatUsd(preview.alreadySpentOrReservedMicroUsd)}</dd></div>
        <div><dt>Effective hard limit</dt><dd>{formatUsd(preview.effectiveHardLimitMicroUsd)}</dd></div>
        <div><dt>Warning threshold</dt><dd>{formatUsd(preview.effectiveWarningMicroUsd)}</dd></div>
        <div><dt>Run hard limit</dt><dd>{formatUsd(preview.runHardLimitMicroUsd)}</dd></div>
        <div><dt>Project hard limit</dt><dd>{formatUsd(preview.projectHardLimitMicroUsd)}</dd></div>
      </dl>
      {crossesWarning ? (
        <p className="budget-warning" role="status">This reservation crosses the {formatUsd(preview.effectiveWarningMicroUsd)} research warning threshold. The hard limit is still enforced by Rust.</p>
      ) : null}
      <p className="fine-print">
        A reservation is a ceiling, not a charge. Actual usage is reconciled after the call.
        Cancellation may not cause a provider refund.
      </p>
      <div className="button-row">
        <button type="button" className="button primary" disabled={busy} onClick={onApprove}>
          {busy ? "Starting…" : requiresLiveCall ? "Approve and research" : "Use cached result"}
        </button>
        <button type="button" className="button quiet" disabled={busy} onClick={onDismiss}>Change request</button>
      </div>
    </section>
  );
}
