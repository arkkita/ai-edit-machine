import type {
  CostPreview,
  DiagnosticsView,
  EvidenceView,
  OpportunityView,
  PlannedResearchCall,
  ProviderDiagnosticView,
  ResearchRunView,
  RequestedSourceView,
} from "../domain/contracts";

const IDS = {
  evidence: "10000000-0000-4000-8000-000000000001",
  source: "10000000-0000-4000-8000-000000000002",
  request: "10000000-0000-4000-8000-000000000003",
  opportunity: "10000000-0000-4000-8000-000000000004",
  intro: "10000000-0000-4000-8000-000000000005",
  job: "10000000-0000-4000-8000-000000000006",
} as const;

export const evidenceFixture: EvidenceView = {
  evidenceId: IDS.evidence,
  sourceId: IDS.source,
  claimId: IDS.evidence,
  provider: "openai",
  title: "Example Show S3E3 official clip",
  publisher: "Official Network",
  sourceType: "OFFICIAL_CLIP",
  verification: "PRIMARY_VERIFIED",
  retrievedAt: "2026-08-15T20:00:00Z",
  publishedAt: "2026-08-14T20:00:00Z",
  eventOrReleaseAt: "2026-08-14T20:00:00Z",
  excerptType: "SHORT_QUOTE",
  excerpt: "I choose you.",
  linkHandle: IDS.source,
  independenceGroup: "official:network",
};

function requestedSource(
  sourceId: string,
  sourceKey: string,
  group: RequestedSourceView["group"],
  priority: number,
  seasonNumber: number | null,
  episodeNumber: number | null,
): RequestedSourceView {
  const episode = seasonNumber === null ? null : `Episode ${episodeNumber}`;
  return {
    sourceId,
    sourceKey,
    group,
    priority,
    purposes: group === "OPTIONAL" ? ["OPTIONAL_CALLBACK"] : ["INTRO", "MONTAGE"],
    showOrTitle: "Example Show",
    seasonNumber,
    episodeNumber,
    episodeTitle: episode,
    assetKind: group === "ALTERNATIVE" ? "SCENE_PACK" : "EPISODE",
    characters: ["Ada", "Bea"],
    relationshipOrTopic: "Ada and Bea",
    sceneOrMoment: group === "OPTIONAL" ? "An earlier happy callback." : "The trust conversation and reaction.",
    quote: group === "REQUIRED" ? {
      status: "VERIFIED",
      text: "I choose you.",
      speaker: "Ada",
      likelyContext: "The trust conversation.",
      claimId: IDS.evidence,
    } : null,
    whyItMattersEmotionally: "It supplies a clear setup and payoff.",
    verificationLevel: group === "ALTERNATIVE" ? "LIKELY_INFERRED" : "VERIFIED",
    sourceQualitySummary: group === "ALTERNATIVE"
      ? "Likely or inferred from relevant evidence; the exact moment is not verified."
      : "Verified against authoritative source evidence.",
    supportingClaimIds: [IDS.evidence],
    supportingEvidence: [evidenceFixture],
    acquisitionEffort: group === "ALTERNATIVE" ? 1 : 2,
    searchQueries: group === "ALTERNATIVE"
      ? ["Example Show Ada and Bea scene pack"]
      : [`Example Show season ${seasonNumber} episode ${episodeNumber} scenes`],
    replacesRequiredSourceKeys: group === "ALTERNATIVE" ? ["s3e3", "s3e5"] : [],
  };
}

export const opportunityFixture: OpportunityView = {
  opportunityId: IDS.opportunity,
  rank: 1,
  title: "Example Show: Ada and Bea",
  mediaKind: "TV_EPISODE",
  focus: "Ada + Bea / trust",
  whyNow: "A new episode supplied a direct relationship turning point.",
  viewerConversation: "Two independent sources focus on the pair rebuilding trust.",
  creativeHook: "Use the choice line as a legible setup for a multi-season trust montage.",
  emotionalEditIdea: "Begin with the current confession, then contrast older doubt with the new payoff.",
  promisingIntroMaterial: "Ada says “I choose you,” followed by Bea’s reaction.",
  introCaveat: "Promising research lead only; inspect the supplied footage before choosing it.",
  evidenceGate: "PASSED",
  confidence: 0.84,
  evidence: [evidenceFixture],
  caveats: ["Final scene choice belongs to the later creative video pass."],
  footageRequest: {
    requestId: IDS.request,
    summary: "Smallest evidence-bound footage request for this opportunity.",
    naturalRequest: {
      best: "Give me Season 3 Episodes 3 and 5.",
      alternative: "If that is easier, give me an Ada + Bea scene pack.",
      minimum: "The smallest useful set is Episodes 3 and 5.",
      optionalImprovement: "Season 1 Episode 4 would add a happier callback.",
    },
    minimumUsefulSourceKeys: ["s3e3", "s3e5"],
    smallestUsefulSetReason: "Two episodes provide the intro and payoff without asking for a full season.",
    requiredSources: [
      requestedSource("20000000-0000-4000-8000-000000000001", "s3e3", "REQUIRED", 1, 3, 3),
      requestedSource("20000000-0000-4000-8000-000000000002", "s3e5", "REQUIRED", 2, 3, 5),
    ],
    optionalSources: [requestedSource("20000000-0000-4000-8000-000000000003", "s1e4", "OPTIONAL", 1, 1, 4)],
    alternativeSources: [requestedSource("20000000-0000-4000-8000-000000000004", "scene_pack", "ALTERNATIVE", 1, null, null)],
    introLeads: [{
      introLeadId: IDS.intro,
      sourceKey: "s3e3",
      momentDescription: "Ada says “I choose you,” followed by Bea’s reaction.",
      quote: {
        status: "UNVERIFIED_LEAD",
        text: "Maybe we can try again.",
        speaker: "Bea",
        likelyContext: "Immediately after the trust conversation.",
        claimId: IDS.evidence,
      },
      whyItMightLeadIntoMontage: "The reaction creates a natural emotional handoff.",
      verificationLevel: "STRONGLY_SUPPORTED",
      supportingClaimIds: [IDS.evidence],
      supportingEvidence: [evidenceFixture],
    }],
    searchQueries: ["Example Show season 3 episode 3 scenes", "Example Show Ada and Bea scene pack"],
    warnings: [],
  },
};

function plannedCall(overrides: Partial<PlannedResearchCall>): PlannedResearchCall {
  return {
    callId: crypto.randomUUID(),
    provider: "openai",
    operation: "research.web_verify",
    configuredModel: "gpt-5.6-luna",
    resolvedModel: "gpt-5.6-luna-2026-08-12",
    reservationMicroUsd: 100_000,
    cacheStatus: "MISS",
    priceCardCheckedAtMs: 1_786_802_400_000,
    retentionSummary: "Up to 30 days for abuse monitoring.",
    dataUseSummary: "API data is not used for training by default.",
    noStorageMode: "store=false",
    privacyMode: "store_false",
    cheaperAlternative: "Use free metadata only.",
    requiresLiveCall: true,
    costKind: "PAID_CLOUD",
    ...overrides,
  };
}

export const costPreviewFixture: CostPreview = {
  previewId: "30000000-0000-4000-8000-000000000001",
  plannedCalls: [
    plannedCall({ provider: "tvmaze", operation: "research.metadata", configuredModel: null, resolvedModel: null, reservationMicroUsd: 0, priceCardCheckedAtMs: null, privacyMode: "public_metadata", costKind: "FREE_METADATA" }),
    plannedCall({ operation: "research.web_verify", reservationMicroUsd: 120_000 }),
    plannedCall({ operation: "research.synthesize", reservationMicroUsd: 80_000, noStorageMode: "store=false", privacyMode: "store_false" }),
  ],
  maximumCostMicroUsd: 200_000,
  alreadySpentOrReservedMicroUsd: 40_000,
  effectiveWarningMicroUsd: 250_000,
  runHardLimitMicroUsd: 500_000,
  projectHardLimitMicroUsd: 2_000_000,
  effectiveHardLimitMicroUsd: 500_000,
  consentToken: "30000000-0000-4000-8000-000000000002",
};

function providerDiagnostic(overrides: Partial<ProviderDiagnosticView>): ProviderDiagnosticView {
  return {
    provider: "openai",
    enabled: true,
    configuredModel: "gpt-5.6-luna",
    resolvedModel: null,
    availability: "UNCONFIGURED",
    priceCardCheckedAt: "2026-08-15T18:00:00Z",
    policyCheckedAt: "2026-08-15T18:00:00Z",
    policyExpiresAt: "2026-08-22T18:00:00Z",
    retentionMode: "Up to 30 days.",
    dataUseMode: "No training by default.",
    noStorageMode: "store=false",
    privacyMode: "store_false",
    cachePolicy: "openai-web-evidence-v1",
    purgeAfterSeconds: 2_592_000,
    killSwitchReason: null,
    ...overrides,
  };
}

export const diagnosticsFixture: DiagnosticsView = {
  appVersion: "0.1.0",
  protocolVersion: "1.0.0",
  workerStatus: "READY",
  workerVersion: "0.1.0-m1-dev",
  workerTarget: "windows-x86_64",
  sqliteVersion: "3.53.2",
  sqliteFts5: true,
  warningBudgetMicroUsd: 250_000,
  hardBudgetMicroUsd: 500_000,
  projectHardBudgetMicroUsd: 2_000_000,
  providers: [
    providerDiagnostic({}),
    providerDiagnostic({ provider: "youtube", configuredModel: null, priceCardCheckedAt: null, enabled: false, availability: "DISABLED", privacyMode: "disabled", killSwitchReason: "No reviewed official-channel registry is bundled yet." }),
    providerDiagnostic({ provider: "xai", configuredModel: "grok-4.6", priceCardCheckedAt: null, enabled: false, availability: "DISABLED", privacyMode: "disabled", killSwitchReason: "Live adversarial invocation-cap proof has not been recorded." }),
    providerDiagnostic({ provider: "tvmaze", configuredModel: null, resolvedModel: null, priceCardCheckedAt: null, availability: "READY", privacyMode: "public_metadata" }),
  ],
};

export const noOpportunityRun: ResearchRunView = {
  jobId: IDS.job,
  status: "SUCCEEDED",
  progressPercent: 100,
  phase: "complete",
  result: {
    outcome: "NO_STRONG_OPPORTUNITY",
    querySummary: "romance TV",
    freshnessCutoff: "2026-08-12T20:00:00Z",
    explanation: "The current evidence did not establish a worthwhile, actionable edit.",
    evidenceReviewed: 7,
    evidenceBreakdown: {
      metadataRecords: 7,
      verifiedWhyNowRecords: 0,
      currentDiscussionSignals: 0,
    },
    suggestions: ["Try a seven-day window."],
  },
  sanitizedError: null,
};
