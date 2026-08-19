import type { OpportunityView, ResearchRunView } from "../domain/contracts";
import { EvidenceList } from "../components/EvidenceList";

interface OpportunitiesScreenProps {
  readonly run: ResearchRunView;
  readonly onSelect: (opportunity: OpportunityView) => void;
  readonly onOpenEvidence: (linkHandle: string) => void;
  readonly onCancel: () => void;
  readonly onStartOver: () => void;
}

export function OpportunitiesScreen({ run, onSelect, onOpenEvidence, onCancel, onStartOver }: OpportunitiesScreenProps) {
  if (run.status === "QUEUED" || run.status === "RUNNING" || run.status === "CANCELLING") {
    return (
      <main className="screen centered-state" id="main-content">
        <p className="eyebrow">Screen B · Opportunities</p>
        <h1>{run.status === "CANCELLING" ? "Stopping safely…" : "Looking for something real…"}</h1>
        <p>{run.phase}</p>
        <progress max={100} value={run.progressPercent}>{run.progressPercent}%</progress>
        <p>{run.progressPercent}%</p>
        <button type="button" className="button quiet" disabled={run.status === "CANCELLING"} onClick={onCancel}>Cancel research</button>
      </main>
    );
  }

  if (run.status !== "SUCCEEDED" || run.result === null) {
    return (
      <main className="screen centered-state" id="main-content">
        <p className="eyebrow">Screen B · Opportunities</p>
        <h1>Research did not complete</h1>
        <p>{run.sanitizedError ?? `The job ended as ${run.status.toLowerCase()}. No recommendation was manufactured.`}</p>
        <button type="button" className="button primary" onClick={onStartOver}>Change request</button>
      </main>
    );
  }

  if (run.result.outcome === "NO_STRONG_OPPORTUNITY") {
    const noOpportunityTitle = "No strong opportunity found under these constraints.";
    const explanation = run.result.explanation.trim();
    return (
      <main className="screen centered-state" id="main-content">
        <p className="eyebrow">Screen B · Opportunities</p>
        <h1>{noOpportunityTitle}</h1>
        {explanation === noOpportunityTitle ? null : <p>{explanation}</p>}
        <p className="fine-print">
          {run.result.evidenceBreakdown.metadataRecords} metadata records examined · {run.result.evidenceBreakdown.verifiedWhyNowRecords} verified why-now proofs · {run.result.evidenceBreakdown.currentDiscussionSignals} current discussion signals.
        </p>
        {run.result.suggestions.length === 0 ? null : (
          <ul className="plain-list">{run.result.suggestions.map((suggestion) => <li key={suggestion}>{suggestion}</li>)}</ul>
        )}
        <button type="button" className="button primary" onClick={onStartOver}>Adjust the search</button>
      </main>
    );
  }

  return (
    <main className="screen" id="main-content">
      <header className="screen-heading">
        <div>
          <p className="eyebrow">Screen B · Opportunities</p>
          <h1>A few ideas with a reason to exist</h1>
          <p>{run.result.querySummary}</p>
        </div>
        <button type="button" className="button quiet" onClick={onStartOver}>New search</button>
      </header>
      <div className="opportunity-list">
        {run.result.opportunities.map((opportunity) => (
          <article className="opportunity-card" key={opportunity.opportunityId}>
            <div className="opportunity-card-heading">
              <div>
                <p className="eyebrow">#{opportunity.rank} · {opportunity.mediaKind.toLowerCase()}</p>
                <h2>{opportunity.title}</h2>
                <p className="focus-line">{opportunity.focus}</p>
              </div>
              <span className={`verification verification-${opportunity.evidenceGate === "PASSED" ? "verified" : "unknown"}`}>
                {opportunity.evidenceGate === "PASSED" ? "Evidence gate passed" : "Low confidence"}
              </span>
            </div>
            <div className="editorial-grid">
              <section><h3>Why now</h3><p>{opportunity.whyNow}</p></section>
              <section><h3>What viewers care about</h3><p>{opportunity.viewerConversation}</p></section>
              <section><h3>Why this could make an edit</h3><p>{opportunity.creativeHook}</p></section>
              <section><h3>Emotional edit idea</h3><p>{opportunity.emotionalEditIdea}</p></section>
              <section>
                <h3>Intro worth investigating</h3>
                <p>{opportunity.promisingIntroMaterial ?? "No specific intro moment is reliably supported yet."}</p>
                <p className="fine-print">{opportunity.introCaveat}</p>
              </section>
            </div>
            <details>
              <summary>Evidence and confidence</summary>
              <p>Overall confidence: {Math.round(opportunity.confidence * 100)}%. Labels describe evidence quality, not viral probability.</p>
              <EvidenceList evidence={opportunity.evidence} onOpen={onOpenEvidence} />
              {opportunity.caveats.length === 0 ? null : (
                <ul className="plain-list">{opportunity.caveats.map((caveat) => <li key={caveat}>{caveat}</li>)}</ul>
              )}
            </details>
            <div className="request-preview">
              <p><strong>What to get:</strong> {opportunity.footageRequest.naturalRequest.best}</p>
              <p className="fine-print">
                {opportunity.footageRequest.requiredSources.length} required · {opportunity.footageRequest.optionalSources.length} optional · {opportunity.footageRequest.alternativeSources.length} alternative
              </p>
            </div>
            <button type="button" className="button primary" onClick={() => onSelect(opportunity)}>Show me the footage request</button>
          </article>
        ))}
      </div>
    </main>
  );
}
