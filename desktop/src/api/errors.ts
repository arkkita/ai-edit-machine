const STALE_MODEL_PREFLIGHT = /^([a-z0-9_-]+) model preflight is missing or stale$/iu;
const PROVIDER_LABELS: Readonly<Record<string, string>> = {
  openai: "OpenAI",
  tvmaze: "TVmaze",
  youtube: "YouTube",
  xai: "xAI",
};

export function userFacingError(reason: unknown, fallback: string): string {
  const detail = reason instanceof Error
    ? reason.message.trim()
    : typeof reason === "string"
      ? reason.trim()
      : "";

  if (detail.length === 0) return fallback;

  const stalePreflight = STALE_MODEL_PREFLIGHT.exec(detail);
  if (stalePreflight !== null) {
    const provider = stalePreflight[1] ?? "provider";
    const label = PROVIDER_LABELS[provider.toLowerCase()]
      ?? provider.charAt(0).toUpperCase() + provider.slice(1);
    return `${label} provider preflight expired. Open Settings & diagnostics, select ${provider}, and run provider preflight; then preview again.`;
  }

  // Command errors are serialized by the trusted Rust core as sanitized strings.
  // Preserve those actionable messages instead of replacing them with a generic UI error.
  return detail;
}
