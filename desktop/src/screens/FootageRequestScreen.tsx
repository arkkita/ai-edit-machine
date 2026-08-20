import type { EditorialConceptView, OpportunityView, ResearchRunView } from "../domain/contracts";
import { verificationLabel } from "../domain/contracts";
import { FootageSourceGroup } from "../components/FootageSourceGroup";
import { EvidenceList } from "../components/EvidenceList";
import { QuoteDetails } from "../components/QuoteDetails";

interface FootageRequestScreenProps {
  readonly opportunity: OpportunityView;
  readonly concept?: EditorialConceptView | null;
  readonly provenance: ResearchRunView["provenance"];
  readonly onBack: () => void;
  readonly onStartOver: () => void;
  readonly onOpenEvidence: (linkHandle: string) => void;
}

export function FootageRequestScreen({ concept = null, provenance, onBack, onStartOver, onOpenEvidence }: FootageRequestScreenProps) {
  if (concept === null || concept.footageRequest.conceptId !== concept.conceptId) {
    return (
      <main className="screen centered-state" id="main-content">
        <p className="eyebrow">Screen C · Footage request</p>
        <h1>No supported concept is selected.</h1>
        <p>A footage request is unavailable until an evidence-backed editorial concept passes validation and owns this request.</p>
        <button type="button" className="button primary" onClick={onBack}>Back to edit ideas</button>
      </main>
    );
  }
  const request = concept.footageRequest;
  return (
    <main className="screen" id="main-content">
      <header className="screen-heading footage-heading">
        <div>
          <p className="eyebrow">Screen C · Footage request</p>
          <h1>Here’s the smallest useful set I’d ask you for.</h1>
          <p>{concept === null ? request.summary : `${concept.title} — ${request.summary}`}</p>
        </div>
        <button type="button" className="button quiet" onClick={onBack}>Back to ideas</button>
      </header>
      <aside className={`run-provenance ${provenance.legacyResult ? "legacy-result" : ""}`} aria-label="Build and research run provenance">
        {provenance.legacyResult ? <p className="legacy-label"><strong>Legacy M1 result</strong> · not a new M1.1 concept run.</p> : null}
        <p className="fine-print">Build <code>{provenance.buildIdentifier}</code> · pipeline <code>{provenance.pipelineVersion}</code> · run <code>{provenance.researchRunId ?? "legacy/not recorded"}</code> · {provenance.runTimestamp === null ? "run time not recorded" : new Date(provenance.runTimestamp).toLocaleString()}</p>
      </aside>
      <section className="selected-concept" aria-label="Selected editorial concept">
          <p className="eyebrow">Selected edit idea</p>
          <h2>{concept.title}</h2>
          <p><strong>Hook:</strong> {concept.viewerHook}</p>
          <p><strong>Song handoff:</strong> {concept.songHandoffIdea}</p>
          <ol>{concept.montageArc.map((beat) => <li key={beat}>{beat}</li>)}</ol>
          <p><strong>Ending:</strong> {concept.endingOrPayoff}</p>
          <p className="fine-print">{concept.provisionalNotice}</p>
      </section>
      <section className="request-language" aria-label="Recommended requests">
        <div><span>Best</span><p>{request.naturalRequest.best}</p></div>
        {request.naturalRequest.alternative === null ? null : <div><span>Alternative</span><p>{request.naturalRequest.alternative}</p></div>}
        <div><span>Minimum</span><p>{request.naturalRequest.minimum}</p></div>
        {request.naturalRequest.optionalImprovement === null ? null : <div><span>Optional improvement</span><p>{request.naturalRequest.optionalImprovement}</p></div>}
      </section>
      <section className="minimum-rationale">
        <h2>Why this is the minimum</h2>
        <p>{request.smallestUsefulSetReason}</p>
      </section>
      <FootageSourceGroup group="REQUIRED" sources={request.requiredSources} minimumSourceKeys={request.minimumUsefulSourceKeys} onOpenEvidence={onOpenEvidence} />
      <FootageSourceGroup group="OPTIONAL" sources={request.optionalSources} minimumSourceKeys={request.minimumUsefulSourceKeys} onOpenEvidence={onOpenEvidence} />
      <FootageSourceGroup group="ALTERNATIVE" sources={request.alternativeSources} minimumSourceKeys={request.minimumUsefulSourceKeys} onOpenEvidence={onOpenEvidence} />
      <section className="policy-note">
        <h2>What this app will—and won’t—do</h2>
        <p>
          These searches help you identify material. You provide lawfully obtained local footage.
          The app does not bypass DRM, download protected streams, scrape transcripts, or rip media.
        </p>
      </section>
      {request.introLeads.length === 0 ? null : (
        <section className="intro-leads">
          <h2>Intro moments worth inspecting later</h2>
          {request.introLeads.map((lead) => (
            <article key={lead.introLeadId}>
              <p><strong>{lead.momentDescription}</strong></p>
              <p>{lead.whyItMightLeadIntoMontage}</p>
              {lead.quote === null ? null : (
                <QuoteDetails quote={lead.quote} ariaLabel={`Intro quote lead for ${lead.sourceKey}`} />
              )}
              <p className="fine-print">{verificationLabel(lead.verificationLevel)} · source <code>{lead.sourceKey}</code></p>
              {lead.supportingEvidence.length === 0 ? null : <EvidenceList evidence={lead.supportingEvidence} onOpen={onOpenEvidence} />}
            </article>
          ))}
        </section>
      )}
      {request.warnings.length === 0 ? null : (
        <section className="uncertainty-note">
          <h2>Still uncertain</h2>
          <ul>{request.warnings.map((item) => <li key={item}>{item}</li>)}</ul>
        </section>
      )}
      {request.searchQueries.length === 0 ? null : (
        <section className="all-searches">
          <h2>Search suggestions</h2>
          <div className="query-cloud">{request.searchQueries.map((query) => <code key={query}>{query}</code>)}</div>
        </section>
      )}
      <div className="button-row footer-actions">
        <button type="button" className="button quiet" onClick={onBack}>Compare another idea</button>
        <button type="button" className="button primary" onClick={onStartOver}>Start another search</button>
      </div>
    </main>
  );
}
