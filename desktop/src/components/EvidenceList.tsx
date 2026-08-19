import type { EvidenceView } from "../domain/contracts";
import { evidenceVerificationLabel } from "../domain/contracts";

interface EvidenceListProps {
  readonly evidence: readonly EvidenceView[];
  readonly onOpen: (linkHandle: string) => void;
}

export function EvidenceList({ evidence, onOpen }: EvidenceListProps) {
  return (
    <ul className="evidence-list" aria-label="Supporting evidence">
      {evidence.map((item) => (
        <li key={item.evidenceId}>
          <div className="evidence-heading">
            <span className={`verification verification-${item.verification.toLowerCase()}`}>
              {evidenceVerificationLabel(item.verification)}
            </span>
            <span className="source-type">{item.sourceType.replaceAll("_", " ").toLowerCase()}</span>
          </div>
          <p><strong>{item.title}</strong> · {item.publisher}</p>
          <p>{item.excerpt}</p>
          <p className="fine-print">
            Retrieved <time dateTime={item.retrievedAt}>{new Date(item.retrievedAt).toLocaleDateString()}</time>
            {item.eventOrReleaseAt === null ? null : (
              <> · Event/release <time dateTime={item.eventOrReleaseAt}>{new Date(item.eventOrReleaseAt).toLocaleDateString()}</time></>
            )}
          </p>
          <button type="button" className="text-button" onClick={() => onOpen(item.linkHandle)}>
            Open source in browser
          </button>
        </li>
      ))}
    </ul>
  );
}
