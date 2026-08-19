import type { QuoteView } from "../domain/contracts";

interface QuoteDetailsProps {
  readonly quote: QuoteView;
  readonly ariaLabel: string;
}

function quoteStatusLabel(status: QuoteView["status"]): string {
  return status.toLowerCase().replaceAll("_", " ");
}

export function QuoteDetails({ quote, ariaLabel }: QuoteDetailsProps) {
  const certainty = quote.status === "VERIFIED"
    ? "authoritative quote evidence attached"
    : "wording or attribution is not authoritative";

  return (
    <blockquote className="quote-details" aria-label={ariaLabel}>
      <p className="quote-text">“{quote.text}”</p>
      <footer>
        {quote.speaker ?? "Speaker unknown"} · {quoteStatusLabel(quote.status)} · {certainty}
      </footer>
      {quote.likelyContext === null ? null : (
        <p className="quote-context"><strong>Likely context:</strong> {quote.likelyContext}</p>
      )}
    </blockquote>
  );
}
