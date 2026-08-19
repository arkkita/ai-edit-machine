import type { RequestedSourceView, SourceGroup } from "../domain/contracts";
import { verificationLabel } from "../domain/contracts";
import { EvidenceList } from "./EvidenceList";
import { QuoteDetails } from "./QuoteDetails";

const GROUP_HEADINGS: Readonly<Record<SourceGroup, string>> = {
  REQUIRED: "Required",
  OPTIONAL: "Optional improvement",
  ALTERNATIVE: "Easier alternative",
};

interface FootageSourceGroupProps {
  readonly group: SourceGroup;
  readonly sources: readonly RequestedSourceView[];
  readonly minimumSourceKeys: readonly string[];
  readonly onOpenEvidence: (linkHandle: string) => void;
}

function episodeLabel(source: RequestedSourceView): string {
  if (source.seasonNumber === null || source.episodeNumber === null) return source.assetKind.replaceAll("_", " ").toLowerCase();
  const code = `S${String(source.seasonNumber).padStart(2, "0")}E${String(source.episodeNumber).padStart(2, "0")}`;
  return source.episodeTitle === null ? code : `${code} — ${source.episodeTitle}`;
}

export function FootageSourceGroup({ group, sources, minimumSourceKeys, onOpenEvidence }: FootageSourceGroupProps) {
  if (sources.length === 0) return null;
  const orderedSources = [...sources].sort((left, right) => left.priority - right.priority);
  return (
    <section className="source-group" aria-labelledby={`source-group-${group}`}>
      <h3 id={`source-group-${group}`}>{GROUP_HEADINGS[group]}</h3>
      <ol>
        {orderedSources.map((source) => {
          const isMinimum = minimumSourceKeys.includes(source.sourceKey);
          return (
            <li key={source.sourceId} className="source-card">
              <div className="source-card-heading">
                <div>
                  <p className="eyebrow">Priority {source.priority} · {source.showOrTitle}</p>
                  <h4>{episodeLabel(source)}</h4>
                </div>
                <div className="badge-row">
                  {isMinimum ? <span className="minimum-badge">Minimum set</span> : null}
                  <span className={`verification verification-${source.verificationLevel.toLowerCase()}`}>
                    {verificationLabel(source.verificationLevel)}
                  </span>
                </div>
              </div>
              <p><strong>{source.purposes.map((purpose) => purpose.toLowerCase().replace("_", " ")).join(" + ")}:</strong> {source.sceneOrMoment}</p>
              <p>{source.whyItMattersEmotionally}</p>
              {source.quote === null ? null : (
                <QuoteDetails quote={source.quote} ariaLabel={`Source quote for ${source.sourceKey}`} />
              )}
              <dl className="compact-facts">
                <div><dt>People/topic</dt><dd>{source.characters.length > 0 ? source.characters.join(" + ") : source.relationshipOrTopic ?? "Not established"}</dd></div>
                <div><dt>Asset</dt><dd>{source.assetKind.replaceAll("_", " ").toLowerCase()}</dd></div>
                <div><dt>Source quality</dt><dd>{source.sourceQualitySummary}</dd></div>
                <div><dt>Acquisition effort</dt><dd>{source.acquisitionEffort} / 5</dd></div>
                <div><dt>Evidence claims</dt><dd>{source.supportingClaimIds.length}</dd></div>
                <div><dt>Source key</dt><dd><code>{source.sourceKey}</code></dd></div>
              </dl>
              {source.replacesRequiredSourceKeys.length === 0 ? null : (
                <p className="fine-print">This alternative replaces: {source.replacesRequiredSourceKeys.join(", ")}.</p>
              )}
              {source.supportingEvidence.length === 0 ? (
                <p className="fine-print">No authoritative source locator is attached; treat this request as unknown.</p>
              ) : (
                <details>
                  <summary>Source-specific evidence</summary>
                  <EvidenceList evidence={source.supportingEvidence} onOpen={onOpenEvidence} />
                </details>
              )}
              <div className="search-suggestions">
                <p><strong>Useful searches</strong></p>
                <ul>
                  {source.searchQueries.map((query) => <li key={query}><code>{query}</code></li>)}
                </ul>
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
