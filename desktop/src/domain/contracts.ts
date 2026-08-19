export const CONTRACT_VERSION = "2.0.0" as const;

export type ScreenId = "find" | "opportunities" | "footage" | "settings";
export type ProviderId = "xai" | "openai" | "youtube" | "tvmaze";
export type CredentialProvider = "xai" | "openai" | "youtube";
export type MediaKind = "TV_EPISODE" | "TV_SERIES" | "FILM" | "TRAILER" | "OFFICIAL_CLIP";
export type VerificationLevel =
  | "VERIFIED"
  | "STRONGLY_SUPPORTED"
  | "LIKELY_INFERRED"
  | "UNKNOWN";
export type FootagePurpose = "INTRO" | "MONTAGE" | "PAYOFF" | "OPTIONAL_CALLBACK";
export type SourceGroup = "REQUIRED" | "OPTIONAL" | "ALTERNATIVE";
export type FootageQuoteStatus = "VERIFIED" | "PARAPHRASE" | "UNVERIFIED_LEAD";

export interface ResearchIntentInput {
  readonly schemaVersion: typeof CONTRACT_VERSION;
  readonly prompt: string;
  readonly mediaKinds: readonly MediaKind[] | null;
  readonly region: string | null;
  readonly freshnessDays: number | null;
  readonly spoilerPolicy: "ALLOW" | "AVOID" | "CURRENT_EPISODE" | null;
  readonly exclusions: readonly string[] | null;
  readonly maxResults: number | null;
}

export interface PlannedResearchCall {
  readonly callId: string;
  readonly provider: ProviderId;
  readonly operation: string;
  readonly configuredModel: string | null;
  readonly resolvedModel: string | null;
  readonly reservationMicroUsd: number;
  readonly cacheStatus: "MISS" | "HIT" | "STALE";
  readonly priceCardCheckedAtMs: number | null;
  readonly retentionSummary: string;
  readonly dataUseSummary: string;
  readonly noStorageMode: string;
  readonly privacyMode: string;
  readonly cheaperAlternative: string;
  readonly requiresLiveCall: boolean;
  readonly costKind: "PAID_CLOUD" | "FREE_METADATA" | "LOCAL_CACHE";
}

export interface CostPreview {
  readonly previewId: string;
  readonly plannedCalls: readonly PlannedResearchCall[];
  readonly maximumCostMicroUsd: number;
  readonly alreadySpentOrReservedMicroUsd: number;
  readonly effectiveWarningMicroUsd: number;
  readonly runHardLimitMicroUsd: number;
  readonly projectHardLimitMicroUsd: number;
  readonly effectiveHardLimitMicroUsd: number;
  readonly consentToken: string;
}

export interface EvidenceView {
  readonly evidenceId: string;
  readonly sourceId: string;
  readonly claimId: string;
  readonly provider: ProviderId;
  readonly title: string;
  readonly publisher: string;
  readonly sourceType: "PRIMARY_RELEASE" | "OFFICIAL_CLIP" | "PLATFORM_SIGNAL" | "ARTICLE" | "METADATA";
  readonly verification: "PRIMARY_VERIFIED" | "SECONDARY_CORROBORATED" | "LEAD_ONLY" | "STALE" | "RETRACTED";
  readonly retrievedAt: string;
  readonly publishedAt: string | null;
  readonly eventOrReleaseAt: string | null;
  readonly excerptType: "SHORT_QUOTE" | "PARAPHRASE" | "UNVERIFIED_QUOTE_LEAD";
  readonly excerpt: string;
  readonly linkHandle: string;
  readonly independenceGroup: string;
}

export interface QuoteView {
  readonly status: FootageQuoteStatus;
  readonly text: string;
  readonly speaker: string | null;
  readonly likelyContext: string | null;
  readonly claimId: string | null;
}

export interface RequestedSourceView {
  readonly sourceId: string;
  readonly sourceKey: string;
  readonly group: SourceGroup;
  readonly priority: number;
  readonly purposes: readonly FootagePurpose[];
  readonly showOrTitle: string;
  readonly seasonNumber: number | null;
  readonly episodeNumber: number | null;
  readonly episodeTitle: string | null;
  readonly assetKind: "EPISODE" | "OFFICIAL_TRAILER" | "OFFICIAL_CLIP" | "SCENE_PACK" | "INDIVIDUAL_SCENES";
  readonly characters: readonly string[];
  readonly relationshipOrTopic: string | null;
  readonly sceneOrMoment: string;
  readonly quote: QuoteView | null;
  readonly whyItMattersEmotionally: string;
  readonly verificationLevel: VerificationLevel;
  readonly sourceQualitySummary: string;
  readonly supportingClaimIds: readonly string[];
  readonly supportingEvidence: readonly EvidenceView[];
  readonly acquisitionEffort: number;
  readonly searchQueries: readonly string[];
  readonly replacesRequiredSourceKeys: readonly string[];
}

export interface IntroMaterialLeadView {
  readonly introLeadId: string;
  readonly sourceKey: string;
  readonly momentDescription: string;
  readonly quote: QuoteView | null;
  readonly whyItMightLeadIntoMontage: string;
  readonly verificationLevel: VerificationLevel;
  readonly supportingClaimIds: readonly string[];
  readonly supportingEvidence: readonly EvidenceView[];
}

export interface FootageRequestView {
  readonly requestId: string;
  readonly summary: string;
  readonly naturalRequest: {
    readonly best: string;
    readonly alternative: string | null;
    readonly minimum: string;
    readonly optionalImprovement: string | null;
  };
  readonly minimumUsefulSourceKeys: readonly string[];
  readonly smallestUsefulSetReason: string;
  readonly requiredSources: readonly RequestedSourceView[];
  readonly optionalSources: readonly RequestedSourceView[];
  readonly alternativeSources: readonly RequestedSourceView[];
  readonly introLeads: readonly IntroMaterialLeadView[];
  readonly searchQueries: readonly string[];
  readonly warnings: readonly string[];
}

export interface OpportunityView {
  readonly opportunityId: string;
  readonly rank: number;
  readonly title: string;
  readonly mediaKind: MediaKind;
  readonly focus: string;
  readonly whyNow: string;
  readonly viewerConversation: string;
  readonly creativeHook: string;
  readonly emotionalEditIdea: string;
  readonly promisingIntroMaterial: string | null;
  readonly introCaveat: string;
  readonly evidenceGate: "PASSED" | "LOW_CONFIDENCE";
  readonly confidence: number;
  readonly evidence: readonly EvidenceView[];
  readonly footageRequest: FootageRequestView;
  readonly caveats: readonly string[];
}

export type ResearchResultView =
  | {
      readonly outcome: "OPPORTUNITIES";
      readonly querySummary: string;
      readonly freshnessCutoff: string;
      readonly opportunities: readonly OpportunityView[];
    }
  | {
      readonly outcome: "NO_STRONG_OPPORTUNITY";
      readonly querySummary: string;
      readonly freshnessCutoff: string;
      readonly explanation: string;
      readonly evidenceReviewed: number;
      readonly evidenceBreakdown: {
        readonly metadataRecords: number;
        readonly verifiedWhyNowRecords: number;
        readonly currentDiscussionSignals: number;
      };
      readonly suggestions: readonly string[];
    };

export interface ResearchRunView {
  readonly jobId: string;
  readonly status: "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED" | "CANCELLING" | "CANCELLED" | "INTERRUPTED";
  readonly progressPercent: number;
  readonly phase: string;
  readonly result: ResearchResultView | null;
  readonly sanitizedError: string | null;
}

export interface CredentialStatusView {
  readonly provider: CredentialProvider;
  readonly configured: boolean;
  readonly locallyValid: boolean;
  readonly lastValidatedAt: string | null;
}

export interface ProviderDiagnosticView {
  readonly provider: ProviderId;
  readonly enabled: boolean;
  readonly configuredModel: string | null;
  readonly resolvedModel: string | null;
  readonly availability: "READY" | "DISABLED" | "UNCONFIGURED" | "UNVERIFIED";
  readonly priceCardCheckedAt: string | null;
  readonly policyCheckedAt: string;
  readonly policyExpiresAt: string;
  readonly retentionMode: string;
  readonly dataUseMode: string;
  readonly noStorageMode: string;
  readonly privacyMode: string;
  readonly cachePolicy: string;
  readonly purgeAfterSeconds: number;
  readonly killSwitchReason: string | null;
}

export interface DiagnosticsView {
  readonly appVersion: string;
  readonly protocolVersion: string;
  readonly workerStatus: "READY" | "RUNNING" | "UNAVAILABLE" | "INVALID_BUNDLE" | "STOPPED";
  readonly workerVersion: string | null;
  readonly workerTarget: string | null;
  readonly sqliteVersion: string;
  readonly sqliteFts5: boolean;
  readonly warningBudgetMicroUsd: number;
  readonly hardBudgetMicroUsd: number;
  readonly projectHardBudgetMicroUsd: number;
  readonly providers: readonly ProviderDiagnosticView[];
}

export function formatUsd(microUsd: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  }).format(microUsd / 1_000_000);
}

export function verificationLabel(level: VerificationLevel): string {
  if (level === "LIKELY_INFERRED") return "Likely / inferred";
  return level.toLowerCase().replace("_", " ").replace(/^./u, (value) => value.toUpperCase());
}

export function evidenceVerificationLabel(level: EvidenceView["verification"]): string {
  return level.toLowerCase().replaceAll("_", " ").replace(/^./u, (value) => value.toUpperCase());
}
