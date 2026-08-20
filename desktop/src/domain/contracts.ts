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
  readonly conceptId: string | null;
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

export interface DossierEvidenceFactView {
  readonly text: string;
  readonly verificationStatus: VerificationLevel;
  readonly supportingEvidence: readonly EvidenceView[];
}

export interface DossierCharacterView {
  readonly characterName: string;
  readonly performerName: string | null;
  readonly showOrTitle: string;
  readonly verificationStatus: VerificationLevel;
  readonly supportingEvidence: readonly EvidenceView[];
}

export interface DossierCurrentSourceView {
  readonly sourceKind: "EPISODE" | "SEASON" | "TRAILER" | "OFFICIAL_CLIP" | "ANNOUNCEMENT" | "INTERVIEW" | "ARTICLE" | "OTHER";
  readonly showOrTitle: string;
  readonly sourceTitle: string;
  readonly seasonNumber: number | null;
  readonly episodeNumber: number | null;
  readonly episodeTitle: string | null;
  readonly verificationStatus: VerificationLevel;
  readonly supportingEvidence: readonly EvidenceView[];
}

export interface FandomStoryDossierView {
  readonly dossierId: string;
  readonly currentEventOrHook: DossierEvidenceFactView;
  readonly namedCharacters: readonly DossierCharacterView[];
  readonly centralRelationship: DossierEvidenceFactView | null;
  readonly currentSource: DossierCurrentSourceView;
  readonly exactOrLikelyQuote: {
    readonly quote: QuoteView;
    readonly sourceTitle: string;
    readonly verificationStatus: VerificationLevel;
    readonly supportingEvidence: readonly EvidenceView[];
  } | null;
  readonly franchiseConnections: readonly {
    readonly connectionType: "SAME_CHARACTER" | "SAME_CANONICAL_UNIVERSE" | "EXPLICIT_CALLBACK" | "THEMATIC_PARALLEL" | "ACTOR_CONNECTION_ONLY" | "FAN_INTERPRETATION";
    readonly currentTitle: string;
    readonly connectedTitle: string;
    readonly characters: readonly string[];
    readonly description: string;
    readonly verificationStatus: VerificationLevel;
    readonly supportingEvidence: readonly EvidenceView[];
  }[];
  readonly relationshipOrCharacterHistory: readonly DossierEvidenceFactView[];
  readonly whyFansCurrentlyCare: readonly DossierEvidenceFactView[];
  readonly audienceAndFandomEvidence: readonly DossierEvidenceFactView[];
  readonly uncertainties: readonly string[];
}

export interface IntentFacetView {
  readonly facetId: string;
  readonly category: "HARD_CONSTRAINT" | "SOFT_PREFERENCE" | "AUDIENCE" | "PLATFORM_FIT" | "CREATIVE_EDIT";
  readonly label: string;
  readonly source: "EXPLICIT" | "INFERRED_PRIOR";
  readonly removable: boolean;
  readonly rationale: string;
}

export interface IntentInterpretationView {
  readonly facets: readonly IntentFacetView[];
  readonly broadQuery: boolean;
  readonly clarificationNeeded: boolean;
  readonly clarificationReason: string | null;
  readonly directTiktokDataUsed: boolean;
  readonly shortFormInferenceDisclaimer: string | null;
}

export interface CandidateScoreTraceView {
  readonly metric: string;
  readonly value: number | null;
  readonly countValue: number | null;
  readonly threshold: number | null;
  readonly countThreshold: number | null;
  readonly status: "PASSED" | "FAILED" | "INFORMATIONAL" | "NOT_COMPUTED";
  readonly note: string;
}

export interface CandidateDiagnosticView {
  readonly candidateName: string;
  readonly title: string;
  readonly shortlistRank: number;
  readonly shortlistReason: string;
  readonly currentHook: string | null;
  readonly audienceFitEvidence: readonly string[];
  readonly fandomEvidence: readonly string[];
  readonly storyOrEpisodeEvidence: readonly string[];
  readonly sourceCategories: readonly string[];
  readonly evidenceReferences: readonly string[];
  readonly inferredShortFormEditPotential: string;
  readonly scoresAndThresholds: readonly CandidateScoreTraceView[];
  readonly exactRejectionGate: string;
  readonly failureClass: "RETRIEVAL_RELATED" | "EVIDENCE_RELATED" | "THRESHOLD_RELATED" | "SUPPORTED";
}

export interface CandidateFunnelView {
  readonly parsedIntent: number;
  readonly generatedSearchVariants: number;
  readonly rawReleaseCandidates: number;
  readonly candidatesAfterFreshness: number;
  readonly candidatesAfterHardExclusions: number;
  readonly candidatesAfterAudienceFitScreening: number;
  readonly candidatesSelectedForSocialResearch: number;
  readonly candidatesWithUsableSocialEvidence: number;
  readonly candidatesSurvivingEvidenceGates: number;
  readonly candidatesSurvivingDeduplication: number;
  readonly candidatesSentToFinalRanker: number;
  readonly finalOpportunitiesSerialized: number;
  readonly finalOpportunitiesReceivedByRust: number;
  readonly finalOpportunitiesDisplayedByUi: number;
  readonly removedByHardConstraints: number;
  readonly lackingCurrentFandomEvidence: number;
  readonly lackingActionableFootageInformation: number;
  readonly falseAbstentionRecoveryAttempted: boolean;
  readonly recoveredCandidateCount: number;
  readonly evidenceCoverageWarning: string | null;
  readonly rejectionReasons: readonly { readonly reasonCode: string; readonly count: number }[];
  readonly candidateDiagnostics: readonly CandidateDiagnosticView[];
  readonly shortageExplanation: string | null;
  readonly suggestions: readonly string[];
}

export interface OpportunityQualityScoreView {
  readonly profileId: string;
  readonly intentFit: number;
  readonly audienceFit: number;
  readonly freshness: number;
  readonly fandomVelocity: number;
  readonly shortFormEditPotential: number;
  readonly relationshipOrCharacterSalience: number;
  readonly footageActionability: number;
  readonly evidenceQuality: number;
  readonly sourceDiversity: number;
  readonly uncertaintyPenalty: number;
  readonly total: number;
}

export interface ShortFormEditPotentialView {
  readonly metricName: "SHORT_FORM_EDIT_POTENTIAL";
  readonly band: "LOW" | "MODERATE" | "HIGH";
  readonly explanation: string;
  readonly signals: readonly string[];
  readonly directTiktokDataUsed: false;
  readonly disclaimer: string;
}

export interface EditorialConceptView {
  readonly conceptId: string;
  readonly dossierId: string | null;
  readonly title: string;
  readonly centralSubject: string;
  readonly centralRelationship: string | null;
  readonly coreEmotion: string;
  readonly viewerHook: string;
  readonly whyFansMayCare: string;
  readonly currentEvent: string;
  readonly legacyOrContextualConnection: string;
  readonly legacyConnectionType: "NONE" | "SAME_CHARACTER" | "SAME_CANONICAL_UNIVERSE" | "EXPLICIT_CALLBACK" | "THEMATIC_PARALLEL" | "ACTOR_CONNECTION_ONLY" | "FAN_INTERPRETATION";
  readonly introLeads: readonly IntroMaterialLeadView[];
  readonly songHandoffIdea: string;
  readonly montageArc: readonly string[];
  readonly endingOrPayoff: string;
  readonly verificationStatus: VerificationLevel;
  readonly score: {
    readonly conceptSpecificity: number;
    readonly introStrength: number;
    readonly emotionalArcStrength: number;
    readonly narrativeBridgeStrength: number;
    readonly fanRecognition: number;
    readonly currentEventRelevance: number;
    readonly legacyContextValue: number;
    readonly payoffStrength: number;
    readonly footageFeasibility: number;
    readonly sourceActionability: number;
    readonly originality: number;
    readonly evidenceQuality: number;
    readonly uncertaintyPenalty: number;
    readonly total: number;
  };
  readonly knownUncertainties: readonly string[];
  readonly footageRequest: FootageRequestView;
  readonly provisionalNotice: string;
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
  readonly qualityScore: OpportunityQualityScoreView | null;
  readonly shortFormEditPotential: ShortFormEditPotentialView | null;
  readonly fandomStoryDossier: FandomStoryDossierView | null;
  readonly editorialConcepts: readonly EditorialConceptView[];
  readonly recommendedConceptId: string | null;
  readonly evidence: readonly EvidenceView[];
  readonly footageRequest: FootageRequestView;
  readonly caveats: readonly string[];
}

export type ResearchResultView =
  | {
      readonly outcome: "OPPORTUNITIES";
      readonly researchRunId: string;
      readonly runTimestamp: string;
      readonly pipelineVersion: string;
      readonly providerConfigId: string;
      readonly querySummary: string;
      readonly freshnessCutoff: string;
      readonly interpretation: IntentInterpretationView | null;
      readonly candidateFunnel: CandidateFunnelView | null;
      readonly opportunities: readonly OpportunityView[];
    }
  | {
      readonly outcome: "NO_STRONG_OPPORTUNITY";
      readonly researchRunId: string;
      readonly runTimestamp: string;
      readonly pipelineVersion: string;
      readonly providerConfigId: string;
      readonly querySummary: string;
      readonly freshnessCutoff: string;
      readonly explanation: string;
      readonly interpretation: IntentInterpretationView | null;
      readonly candidateFunnel: CandidateFunnelView | null;
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
  readonly provenance: {
    readonly buildCommit: string;
    readonly buildIdentifier: string;
    readonly buildIsDirty: boolean;
    readonly buildTimestampUnixMs: number;
    readonly pipelineVersion: string;
    readonly workerManifestSha256: string;
    readonly researchRunId: string | null;
    readonly runTimestamp: string | null;
    readonly providerConfigId: string;
    readonly legacyResult: boolean;
  };
  readonly sanitizedError: string | null;
}

export type RecommendationFeedback =
  | "GREAT_RECOMMENDATION"
  | "RELEVANT_BUT_BORING"
  | "WRONG_AUDIENCE"
  | "NOT_ACTUALLY_TRENDING"
  | "WEAK_EVIDENCE"
  | "FOOTAGE_REQUEST_TOO_VAGUE"
  | "HIDE_THIS_TYPE"
  | "GENERATE_ANOTHER_IDEA"
  | "MORE_LIKE_THIS"
  | "TOO_GENERIC"
  | "DONT_CARE_ABOUT_THIS_ANGLE";

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
  readonly buildCommit: string;
  readonly buildIdentifier: string;
  readonly buildIsDirty: boolean;
  readonly buildTimestampUnixMs: number;
  readonly pipelineVersion: string;
  readonly workerManifestSha256: string;
  readonly providerConfigId: string;
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
