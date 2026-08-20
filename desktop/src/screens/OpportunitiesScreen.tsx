import { useState } from "react";

import type { CandidateDiagnosticView, OpportunityView, RecommendationFeedback, ResearchRunView } from "../domain/contracts";
import { EvidenceList } from "../components/EvidenceList";
import { verificationLabel } from "../domain/contracts";

function RunProvenance({ provenance }: { readonly provenance: ResearchRunView["provenance"] }) {
  return (
    <aside className={`run-provenance ${provenance.legacyResult ? "legacy-result" : ""}`} aria-label="Build and research run provenance">
      {provenance.legacyResult ? (
        <p className="legacy-label"><strong>Legacy M1 result</strong> · This record predates M1.1 dossier/concept provenance and is not a new M1.1 run.</p>
      ) : null}
      <dl>
        <div><dt>Build</dt><dd><code>{provenance.buildIdentifier}</code></dd></div>
        <div><dt>Built</dt><dd>{new Date(provenance.buildTimestampUnixMs).toLocaleString()}</dd></div>
        <div><dt>Pipeline</dt><dd><code>{provenance.pipelineVersion}</code></dd></div>
        <div><dt>Worker manifest</dt><dd><code title={provenance.workerManifestSha256}>{provenance.workerManifestSha256.slice(0, 12)}…</code></dd></div>
        <div><dt>Research run</dt><dd><code>{provenance.researchRunId ?? "legacy/not recorded"}</code></dd></div>
        <div><dt>Run timestamp</dt><dd>{provenance.runTimestamp === null ? "legacy/not recorded" : new Date(provenance.runTimestamp).toLocaleString()}</dd></div>
        <div><dt>Provider config</dt><dd><code>{provenance.providerConfigId}</code></dd></div>
      </dl>
    </aside>
  );
}

function CandidateDiagnostics({ candidates }: { readonly candidates: readonly CandidateDiagnosticView[] }) {
  if (candidates.length === 0) return null;
  return (
    <details className="candidate-diagnostics">
      <summary>Candidate-level diagnosis ({candidates.length} researched titles)</summary>
      <div className="candidate-diagnostic-list">
        {candidates.map((candidate) => (
          <article className="candidate-diagnostic" key={`${candidate.shortlistRank}:${candidate.title}`}>
            <h3>#{candidate.shortlistRank} · {candidate.candidateName}</h3>
            <p><strong>Why it entered:</strong> {candidate.shortlistReason}</p>
            <p><strong>Exact gate:</strong> <code>{candidate.exactRejectionGate}</code> · {candidate.failureClass.toLowerCase().replaceAll("_", " ")}</p>
            <p><strong>Current hook:</strong> {candidate.currentHook ?? "No usable title-bound current hook was retrieved."}</p>
            <p><strong>Inferred short-form potential:</strong> {candidate.inferredShortFormEditPotential}</p>
            <div className="candidate-evidence-grid">
              <section><h4>Audience fit</h4>{candidate.audienceFitEvidence.length === 0 ? <p>None retrieved.</p> : <ul>{candidate.audienceFitEvidence.map((item) => <li key={item}>{item}</li>)}</ul>}</section>
              <section><h4>Fandom</h4>{candidate.fandomEvidence.length === 0 ? <p>None retrieved.</p> : <ul>{candidate.fandomEvidence.map((item) => <li key={item}>{item}</li>)}</ul>}</section>
              <section><h4>Story / episode</h4>{candidate.storyOrEpisodeEvidence.length === 0 ? <p>None retrieved.</p> : <ul>{candidate.storyOrEpisodeEvidence.map((item) => <li key={item}>{item}</li>)}</ul>}</section>
            </div>
            <p className="fine-print">Source categories: {candidate.sourceCategories.length === 0 ? "none" : candidate.sourceCategories.join(" · ")} · Evidence references: {candidate.evidenceReferences.length}</p>
            <details>
              <summary>Scores and thresholds</summary>
              <ul className="candidate-score-list">
                {candidate.scoresAndThresholds.map((score) => {
                  const value = score.value ?? score.countValue;
                  const threshold = score.threshold ?? score.countThreshold;
                  return <li key={score.metric}><code>{score.metric}</code>: {value ?? "NOT_COMPUTED"}{threshold === null ? "" : ` / threshold ${threshold}`} · {score.status} — {score.note}</li>;
                })}
              </ul>
            </details>
          </article>
        ))}
      </div>
    </details>
  );
}

interface OpportunitiesScreenProps {
  readonly run: ResearchRunView;
  readonly onSelect: (opportunity: OpportunityView, conceptId?: string | null) => void;
  readonly onOpenEvidence: (linkHandle: string) => void;
  readonly onFeedback?: (opportunityId: string, conceptId: string | null, rating: RecommendationFeedback) => Promise<void>;
  readonly onGenerateAnotherIdea?: (opportunity: OpportunityView, conceptTitle: string) => void;
  readonly onCancel: () => void;
  readonly onStartOver: () => void;
  readonly onAdjustSearch?: () => void;
}

export function OpportunitiesScreen({ run, onSelect, onOpenEvidence, onFeedback, onGenerateAnotherIdea, onCancel, onStartOver, onAdjustSearch = onStartOver }: OpportunitiesScreenProps) {
  const [feedbackStatus, setFeedbackStatus] = useState<Record<string, string>>({});

  async function submitFeedback(
    opportunityId: string,
    conceptId: string | null,
    rating: RecommendationFeedback,
  ): Promise<void> {
    if (onFeedback === undefined) return;
    const key = `${opportunityId}:${conceptId ?? "opportunity"}`;
    setFeedbackStatus((value) => ({ ...value, [key]: "Saving…" }));
    try {
      await onFeedback(opportunityId, conceptId, rating);
      setFeedbackStatus((value) => ({
        ...value,
        [key]: rating === "GENERATE_ANOTHER_IDEA"
          ? "Saved locally. No paid research run was started automatically."
          : "Saved locally for later evaluation.",
      }));
    } catch {
      setFeedbackStatus((value) => ({ ...value, [key]: "Could not save this preference." }));
    }
  }

  async function generateAnotherIdea(
    opportunity: OpportunityView,
    conceptId: string,
    conceptTitle: string,
  ): Promise<void> {
    await submitFeedback(opportunity.opportunityId, conceptId, "GENERATE_ANOTHER_IDEA");
    onGenerateAnotherIdea?.(opportunity, conceptTitle);
  }
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
        <RunProvenance provenance={run.provenance} />
        {explanation === noOpportunityTitle ? null : <p>{explanation}</p>}
        {run.result.interpretation === null ? null : (
          <section className="interpretation-summary">
            <h2>How I interpreted your request</h2>
            <div className="interpretation-chips">
              {run.result.interpretation.facets.map((facet) => <span className="intent-chip" key={facet.facetId}>{facet.label}</span>)}
            </div>
            {run.result.interpretation.shortFormInferenceDisclaimer === null ? null : <p className="fine-print">{run.result.interpretation.shortFormInferenceDisclaimer}</p>}
          </section>
        )}
        <p className="fine-print">
          {run.result.evidenceBreakdown.metadataRecords} metadata records examined · {run.result.evidenceBreakdown.verifiedWhyNowRecords} verified why-now proofs · {run.result.evidenceBreakdown.currentDiscussionSignals} current discussion signals.
        </p>
        {run.result.candidateFunnel?.shortageExplanation === null || run.result.candidateFunnel === null ? null : (
          <section className="candidate-shortage">
            <h2>Why the result set is small</h2>
            <p>{run.result.candidateFunnel.shortageExplanation}</p>
            <p className="fine-print">
              {run.result.candidateFunnel.rawReleaseCandidates} raw releases · {run.result.candidateFunnel.removedByHardConstraints} removed by hard constraints · {run.result.candidateFunnel.lackingCurrentFandomEvidence} lacked usable current fandom evidence · {run.result.candidateFunnel.lackingActionableFootageInformation} lacked an actionable concept or footage request.
            </p>
          </section>
        )}
        {run.result.candidateFunnel?.falseAbstentionRecoveryAttempted ? (
          <section className="recovery-report" aria-label="False-abstention recovery">
            <h2>False-abstention recovery completed</h2>
            <p>{run.result.candidateFunnel.evidenceCoverageWarning ?? "The bounded recovery pass did not add a result that could pass every factual and concept-specificity gate."}</p>
            <p className="fine-print">Recovered candidates entering synthesis: {run.result.candidateFunnel.recoveredCandidateCount}. Factual verification requirements were unchanged.</p>
          </section>
        ) : null}
        {run.result.candidateFunnel === null ? null : <CandidateDiagnostics candidates={run.result.candidateFunnel.candidateDiagnostics} />}
        {run.result.suggestions.length === 0 ? null : (
          <ul className="plain-list">{run.result.suggestions.map((suggestion) => <li key={suggestion}>{suggestion}</li>)}</ul>
        )}
        <button type="button" className="button primary" onClick={onAdjustSearch}>Adjust the search</button>
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
      <RunProvenance provenance={run.provenance} />
      {run.result.interpretation === null ? null : (
        <section className="interpretation-summary" aria-labelledby="interpretation-heading">
          <div>
            <p className="eyebrow">How I interpreted your request</p>
            <h2 id="interpretation-heading">Search priorities</h2>
          </div>
          <div className="interpretation-chips">
            {run.result.interpretation.facets.map((facet) => (
              <span className={`intent-chip intent-${facet.category.toLowerCase()}`} title={facet.rationale} key={facet.facetId}>
                {facet.label}
              </span>
            ))}
          </div>
          {run.result.interpretation.shortFormInferenceDisclaimer === null ? null : (
            <p className="fine-print">{run.result.interpretation.shortFormInferenceDisclaimer}</p>
          )}
          <button type="button" className="button quiet" onClick={onAdjustSearch}>Adjust these priorities</button>
        </section>
      )}
      {run.result.candidateFunnel?.shortageExplanation === null || run.result.candidateFunnel === null ? null : (
        <section className="candidate-shortage" aria-label="Why the result set is small">
          <h2>Why the result set is small</h2>
          <p>{run.result.candidateFunnel.shortageExplanation}</p>
          <details>
            <summary>Candidate funnel</summary>
            <ol className="funnel-list">
              <li>Parsed intent: {run.result.candidateFunnel.parsedIntent}</li>
              <li>Search variants: {run.result.candidateFunnel.generatedSearchVariants}</li>
              <li>Raw releases: {run.result.candidateFunnel.rawReleaseCandidates}</li>
              <li>Fresh: {run.result.candidateFunnel.candidatesAfterFreshness}</li>
              <li>After hard exclusions: {run.result.candidateFunnel.candidatesAfterHardExclusions}</li>
              <li>After audience screening: {run.result.candidateFunnel.candidatesAfterAudienceFitScreening}</li>
              <li>Selected for social research: {run.result.candidateFunnel.candidatesSelectedForSocialResearch}</li>
              <li>Usable social evidence: {run.result.candidateFunnel.candidatesWithUsableSocialEvidence}</li>
              <li>Passed evidence gates: {run.result.candidateFunnel.candidatesSurvivingEvidenceGates}</li>
              <li>After deduplication: {run.result.candidateFunnel.candidatesSurvivingDeduplication}</li>
              <li>Sent to final ranker: {run.result.candidateFunnel.candidatesSentToFinalRanker}</li>
              <li>Serialized: {run.result.candidateFunnel.finalOpportunitiesSerialized}</li>
              <li>Received by Rust: {run.result.candidateFunnel.finalOpportunitiesReceivedByRust}</li>
              <li>Displayed: {run.result.candidateFunnel.finalOpportunitiesDisplayedByUi}</li>
              <li>Recovery pass: {run.result.candidateFunnel.falseAbstentionRecoveryAttempted ? "completed" : "not needed"}</li>
              <li>Recovered into synthesis: {run.result.candidateFunnel.recoveredCandidateCount}</li>
            </ol>
          </details>
          <div className="query-cloud">{run.result.candidateFunnel.suggestions.map((item) => <span key={item}>{item}</span>)}</div>
          <CandidateDiagnostics candidates={run.result.candidateFunnel.candidateDiagnostics} />
        </section>
      )}
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
            {opportunity.fandomStoryDossier === null ? (
              <section className="dossier-missing" aria-label="Story dossier unavailable">
                <h3>Story dossier unavailable</h3>
                <p>This legacy result predates the evidence-to-concept bridge. It cannot support a new concept-specific footage request.</p>
              </section>
            ) : (
              <details className="story-dossier">
                <summary>Fandom + story dossier</summary>
                <div className="dossier-grid">
                  <section>
                    <h3>Current hook</h3>
                    <p>{opportunity.fandomStoryDossier.currentEventOrHook.text}</p>
                    <p className="fine-print">{verificationLabel(opportunity.fandomStoryDossier.currentEventOrHook.verificationStatus)}</p>
                  </section>
                  <section>
                    <h3>Current source</h3>
                    <p>
                      {opportunity.fandomStoryDossier.currentSource.showOrTitle} · {opportunity.fandomStoryDossier.currentSource.sourceTitle}
                      {opportunity.fandomStoryDossier.currentSource.seasonNumber === null ? "" : ` · S${opportunity.fandomStoryDossier.currentSource.seasonNumber}E${opportunity.fandomStoryDossier.currentSource.episodeNumber}`}
                    </p>
                    <p className="fine-print">{verificationLabel(opportunity.fandomStoryDossier.currentSource.verificationStatus)}</p>
                  </section>
                  <section>
                    <h3>Named subjects</h3>
                    <p>{opportunity.fandomStoryDossier.namedCharacters.map((character) => character.characterName).join(" · ")}</p>
                  </section>
                  <section>
                    <h3>Audience + fandom evidence</h3>
                    <ul>{opportunity.fandomStoryDossier.audienceAndFandomEvidence.map((fact) => <li key={fact.text}>{fact.text} <span className="fine-print">({verificationLabel(fact.verificationStatus)})</span></li>)}</ul>
                  </section>
                  <section>
                    <h3>What fans currently care about</h3>
                    <ul>{opportunity.fandomStoryDossier.whyFansCurrentlyCare.map((fact) => <li key={fact.text}>{fact.text} <span className="fine-print">({verificationLabel(fact.verificationStatus)})</span></li>)}</ul>
                  </section>
                  {opportunity.fandomStoryDossier.centralRelationship === null ? null : (
                    <section><h3>Relationship or character history</h3><p>{opportunity.fandomStoryDossier.centralRelationship.text}</p></section>
                  )}
                </div>
                {opportunity.fandomStoryDossier.franchiseConnections.length === 0 ? null : (
                  <section><h3>Verified context bridge</h3><ul>{opportunity.fandomStoryDossier.franchiseConnections.map((connection) => <li key={`${connection.connectionType}:${connection.connectedTitle}`}>{connection.description} <span className="fine-print">({verificationLabel(connection.verificationStatus)})</span></li>)}</ul></section>
                )}
                {opportunity.fandomStoryDossier.uncertainties.length === 0 ? null : (
                  <section><h3>Uncertainties</h3><ul>{opportunity.fandomStoryDossier.uncertainties.map((item) => <li key={item}>{item}</li>)}</ul></section>
                )}
              </details>
            )}
            {opportunity.shortFormEditPotential === null ? null : (
              <section className="short-form-inference">
                <h3>TikTok potential: {opportunity.shortFormEditPotential.band.toLowerCase()} (inferred)</h3>
                <p>{opportunity.shortFormEditPotential.explanation}</p>
                <p className="fine-print">{opportunity.shortFormEditPotential.disclaimer}</p>
              </section>
            )}
            {opportunity.editorialConcepts.length === 0 ? null : (
              <section className="concept-section" aria-label={`Edit ideas for ${opportunity.title}`}>
                <h3>Edit ideas</h3>
                <div className="concept-list">
                  {opportunity.editorialConcepts.map((concept) => {
                    const isRecommended = concept.conceptId === opportunity.recommendedConceptId;
                    const feedbackKey = `${opportunity.opportunityId}:${concept.conceptId}`;
                    return (
                      <article className={`concept-card ${isRecommended ? "recommended" : ""}`} key={concept.conceptId}>
                        <div className="concept-heading">
                          <h4>{concept.title}</h4>
                          {isRecommended ? <span className="verification verification-verified">Strongest route</span> : null}
                        </div>
                        <p><strong>Why this idea could work:</strong> {concept.whyFansMayCare}</p>
                        <p><strong>Intro lead:</strong> {concept.introLeads[0]?.momentDescription}</p>
                        <p><strong>Song handoff:</strong> {concept.songHandoffIdea}</p>
                        <div>
                          <strong>Montage arc:</strong>
                          <ol>{concept.montageArc.map((beat) => <li key={beat}>{beat}</li>)}</ol>
                        </div>
                        <p><strong>Ending/payoff:</strong> {concept.endingOrPayoff}</p>
                        <p><strong>Footage needed:</strong> {concept.footageRequest.naturalRequest.minimum}</p>
                        <p className="fine-print">{concept.provisionalNotice}</p>
                        <div className="button-row concept-actions">
                          <button type="button" className="button primary" onClick={() => onSelect(opportunity, concept.conceptId)}>Use this concept</button>
                          {onFeedback === undefined ? null : (
                            <>
                              <button type="button" className="button quiet" onClick={() => void generateAnotherIdea(opportunity, concept.conceptId, concept.title)}>Generate another idea</button>
                              <button type="button" className="button quiet" onClick={() => void submitFeedback(opportunity.opportunityId, concept.conceptId, "MORE_LIKE_THIS")}>More like this</button>
                              <button type="button" className="button quiet" onClick={() => void submitFeedback(opportunity.opportunityId, concept.conceptId, "TOO_GENERIC")}>Too generic</button>
                              <button type="button" className="button quiet" onClick={() => void submitFeedback(opportunity.opportunityId, concept.conceptId, "DONT_CARE_ABOUT_THIS_ANGLE")}>I don’t care about this angle</button>
                            </>
                          )}
                        </div>
                        {feedbackStatus[feedbackKey] === undefined ? null : <p className="fine-print" role="status">{feedbackStatus[feedbackKey]}</p>}
                      </article>
                    );
                  })}
                </div>
              </section>
            )}
            <details>
              <summary>Evidence and confidence</summary>
              <p>Overall confidence: {Math.round(opportunity.confidence * 100)}%. Labels describe evidence quality, not viral probability.</p>
              <EvidenceList evidence={opportunity.evidence} onOpen={onOpenEvidence} />
              {opportunity.caveats.length === 0 ? null : (
                <ul className="plain-list">{opportunity.caveats.map((caveat) => <li key={caveat}>{caveat}</li>)}</ul>
              )}
            </details>
            {opportunity.recommendedConceptId === null || opportunity.editorialConcepts.length === 0 ? (
              <div className="request-preview unavailable">
                <p><strong>Footage request unavailable.</strong> No supported editorial concept exists for this result.</p>
                <button type="button" className="button primary" disabled>Footage request disabled</button>
              </div>
            ) : (
              <>
                <div className="request-preview">
                  <p><strong>What to get for the recommended concept:</strong> {opportunity.footageRequest.naturalRequest.best}</p>
                  <p className="fine-print">
                    {opportunity.footageRequest.requiredSources.length} required · {opportunity.footageRequest.optionalSources.length} optional · {opportunity.footageRequest.alternativeSources.length} alternative
                  </p>
                </div>
                <div className="button-row">
                  <button type="button" className="button primary" onClick={() => onSelect(opportunity, opportunity.recommendedConceptId)}>Show the recommended concept’s footage request</button>
                </div>
              </>
            )}
            {onFeedback === undefined ? null : (
              <div className="feedback-actions" aria-label={`Rate ${opportunity.title}`}>
                <span>Help calibrate recommendations:</span>
                {([
                  ["GREAT_RECOMMENDATION", "Great recommendation"],
                  ["RELEVANT_BUT_BORING", "Relevant but boring"],
                  ["WRONG_AUDIENCE", "Wrong audience"],
                  ["NOT_ACTUALLY_TRENDING", "Not actually trending"],
                  ["WEAK_EVIDENCE", "Weak evidence"],
                  ["FOOTAGE_REQUEST_TOO_VAGUE", "Footage request too vague"],
                  ["HIDE_THIS_TYPE", "Hide this type"],
                ] as const).map(([rating, label]) => (
                  <button type="button" className="text-button" key={rating} onClick={() => void submitFeedback(opportunity.opportunityId, null, rating)}>{label}</button>
                ))}
                {feedbackStatus[`${opportunity.opportunityId}:opportunity`] === undefined ? null : (
                  <p className="fine-print" role="status">{feedbackStatus[`${opportunity.opportunityId}:opportunity`]}</p>
                )}
              </div>
            )}
          </article>
        ))}
      </div>
    </main>
  );
}
