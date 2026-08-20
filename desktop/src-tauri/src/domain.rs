use std::collections::{HashMap, HashSet};

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use uuid::Uuid;

use crate::database::repositories::TrustedEvidencePolicyRecord;
use crate::{AppError, AppResult};

const V2: &str = "2.0.0";
const MAX_SEASON_NUMBER: i64 = 9_999;
const TVMAZE_SHOW_BINDING_PREFIX: &str = "tvmaze-show-title-sha256:v1:";
const MEDIA_TITLE_BINDING_PREFIX: &str = "media-title-sha256:v1:";
const SOURCE_BINDING_SEPARATOR: &str = ":source-sha256:v1:";
const CONCEPT_PROVISIONAL_NOTICE: &str = "This concept is based on current story and fandom evidence. Once you provide the footage, the video analyzer will verify whether the proposed intro, quote, reactions, and montage material are actually present and usable.";

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct IntentFacet {
    facet_id: String,
    category: String,
    label: String,
    source: String,
    removable: bool,
    rationale: String,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct IntentSearchQuestion {
    question_id: String,
    query: String,
    evidence_goal: String,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct IntentInterpretation {
    schema_version: String,
    facets: Vec<IntentFacet>,
    search_questions: Vec<IntentSearchQuestion>,
    broad_query: bool,
    clarification_needed: bool,
    clarification_reason: Option<String>,
    direct_tiktok_data_used: bool,
    short_form_inference_disclaimer: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct CanonicalResearchIntent {
    schema_version: String,
    query: String,
    media_kinds: Vec<String>,
    focus_terms: Vec<String>,
    region: String,
    freshness_days: i64,
    spoiler_policy: String,
    exclusions: Vec<String>,
    max_results: i64,
    interpretation: Option<IntentInterpretation>,
}

impl CanonicalResearchIntent {
    pub fn freshness_days(&self) -> i64 { self.freshness_days }
    pub fn max_results(&self) -> i64 { self.max_results }
    pub fn region(&self) -> &str { &self.region }
    pub fn query(&self) -> &str { &self.query }
    pub fn media_kinds(&self) -> &[String] { &self.media_kinds }
    pub fn focus_terms(&self) -> &[String] { &self.focus_terms }
    pub fn spoiler_policy(&self) -> &str { &self.spoiler_policy }
    pub fn exclusions(&self) -> &[String] { &self.exclusions }
    fn interpretation(&self) -> Option<&IntentInterpretation> { self.interpretation.as_ref() }
    pub fn to_canonical_json(&self) -> AppResult<String> {
        Ok(serde_json::to_string(&serde_json::to_value(self)?)?)
    }
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct MediaIdentity {
    media_kind: String,
    show_or_title: String,
    season_number: Option<i64>,
    episode_number: Option<i64>,
    episode_title: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct EpisodeLocator {
    show_or_title: String,
    season_number: i64,
    episode_number: i64,
    episode_title: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct WhyNowEvent {
    event_kind: String,
    media_identity: MediaIdentity,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct QuoteFact {
    exact_text: String,
    speaker: String,
    media_identity: MediaIdentity,
    context: Option<String>,
    episode_locator: Option<EpisodeLocator>,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct SceneFact {
    show_or_title: String,
    description: String,
    characters: Vec<String>,
    relationship_or_topic: Option<String>,
    episode_locator: Option<EpisodeLocator>,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct CastFact {
    show_or_title: String,
    character_name: String,
    performer_name: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct EvidenceSource {
    schema_version: String,
    source_id: Uuid,
    provider: String,
    provider_record_id: Option<String>,
    source_type: String,
    canonical_url: String,
    title: String,
    author_or_channel: Option<String>,
    source_created_at: Option<String>,
    source_updated_at: Option<String>,
    page_published_at: Option<String>,
    retrieved_at: String,
    query: String,
    window_start: Option<String>,
    window_end: Option<String>,
    policy_class: String,
    refresh_due_at: Option<String>,
    purge_due_at: Option<String>,
    expires_at: Option<String>,
    deletion_required_at: Option<String>,
    content_sha256: String,
    independence_group: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct EvidenceClaim {
    schema_version: String,
    claim_id: Uuid,
    source_id: Uuid,
    claim_kind: String,
    excerpt_type: String,
    text: String,
    verification: String,
    episode_locator: Option<EpisodeLocator>,
    quote_fact: Option<QuoteFact>,
    why_now_event: Option<WhyNowEvent>,
    scene_fact: Option<SceneFact>,
    cast_fact: Option<CastFact>,
    event_or_release_at: Option<String>,
    confidence: f64,
    supports_why_now: bool,
    content_sha256: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct OpportunityFocus {
    characters: Vec<String>,
    relationship_or_topic: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct OpportunityEvidenceRef {
    claim_id: Uuid,
    role: String,
    supports_why_now: bool,
    independence_group: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct OpportunityScore {
    release_freshness: f64,
    cross_source_agreement: f64,
    scene_specificity: f64,
    footage_actionability: f64,
    independent_source_count: i64,
    total: f64,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct OpportunityRankingWeights {
    intent_fit: f64,
    audience_fit: f64,
    freshness: f64,
    fandom_velocity: f64,
    short_form_edit_potential: f64,
    relationship_or_character_salience: f64,
    footage_actionability: f64,
    evidence_quality: f64,
    source_diversity: f64,
    uncertainty_penalty: f64,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct OpportunityQualityScore {
    schema_version: String,
    profile_id: String,
    weights: OpportunityRankingWeights,
    intent_fit: f64,
    audience_fit: f64,
    freshness: f64,
    fandom_velocity: f64,
    short_form_edit_potential: f64,
    relationship_or_character_salience: f64,
    footage_actionability: f64,
    evidence_quality: f64,
    source_diversity: f64,
    uncertainty_penalty: f64,
    total: f64,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct ShortFormEditPotential {
    schema_version: String,
    metric_name: String,
    band: String,
    explanation: String,
    signals: Vec<String>,
    supporting_claim_ids: Vec<Uuid>,
    direct_tiktok_data_used: bool,
    disclaimer: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct Opportunity {
    schema_version: String,
    opportunity_id: Uuid,
    footage_request_id: Uuid,
    #[serde(default)]
    dossier_id: Option<Uuid>,
    media_kind: String,
    media_identity: MediaIdentity,
    title: String,
    focus: OpportunityFocus,
    why_now: String,
    what_viewers_are_discussing: String,
    creative_hook: String,
    emotional_edit_direction: String,
    evidence: Vec<OpportunityEvidenceRef>,
    evidence_gate: String,
    confidence: f64,
    score: OpportunityScore,
    quality_score: Option<OpportunityQualityScore>,
    short_form_edit_potential: Option<ShortFormEditPotential>,
    recommended_concept_id: Option<Uuid>,
    caveats: Vec<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct FootageQuote {
    status: String,
    text: String,
    speaker: Option<String>,
    likely_context: Option<String>,
    claim_id: Uuid,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct DossierEvidenceFact {
    text: String,
    verification_status: String,
    supporting_claim_ids: Vec<Uuid>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct DossierCharacter {
    character_name: String,
    performer_name: Option<String>,
    show_or_title: String,
    verification_status: String,
    supporting_claim_ids: Vec<Uuid>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct DossierCurrentSource {
    source_kind: String,
    show_or_title: String,
    source_title: String,
    season_number: Option<i64>,
    episode_number: Option<i64>,
    episode_title: Option<String>,
    verification_status: String,
    supporting_claim_ids: Vec<Uuid>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct DossierQuoteLead {
    quote: FootageQuote,
    source_title: String,
    verification_status: String,
    supporting_claim_ids: Vec<Uuid>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct DossierFranchiseConnection {
    connection_type: String,
    current_title: String,
    connected_title: String,
    characters: Vec<String>,
    description: String,
    verification_status: String,
    supporting_claim_ids: Vec<Uuid>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct FandomStoryDossier {
    schema_version: String,
    dossier_id: Uuid,
    opportunity_id: Uuid,
    dossier_key: String,
    show_or_title: String,
    current_event_or_hook: DossierEvidenceFact,
    named_characters: Vec<DossierCharacter>,
    central_relationship: Option<DossierEvidenceFact>,
    current_source: DossierCurrentSource,
    exact_or_likely_quote: Option<DossierQuoteLead>,
    franchise_connections: Vec<DossierFranchiseConnection>,
    relationship_or_character_history: Vec<DossierEvidenceFact>,
    why_fans_currently_care: Vec<DossierEvidenceFact>,
    audience_and_fandom_evidence: Vec<DossierEvidenceFact>,
    uncertainties: Vec<String>,
    evidence: Vec<OpportunityEvidenceRef>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct RequestedSource {
    requested_source_id: Uuid,
    source_key: String,
    priority: i64,
    acquisition_effort: i64,
    asset_kind: String,
    show_or_title: String,
    season_number: Option<i64>,
    episode_number: Option<i64>,
    episode_title: Option<String>,
    characters: Vec<String>,
    relationship_or_topic: Option<String>,
    scene_or_moment: String,
    purposes: Vec<String>,
    verification_level: String,
    source_quality_summary: String,
    supporting_claim_ids: Vec<Uuid>,
    quote: Option<FootageQuote>,
    why_it_matters_emotionally: String,
    search_queries: Vec<String>,
    replaces_required_source_keys: Vec<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct NaturalFootageRequest {
    best: String,
    alternative: Option<String>,
    minimum: String,
    optional_improvement: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct IntroMaterialLead {
    intro_lead_id: Uuid,
    source_key: String,
    moment_description: String,
    quote: Option<FootageQuote>,
    why_it_might_lead_into_montage: String,
    verification_level: String,
    supporting_claim_ids: Vec<Uuid>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct FootageRequest {
    schema_version: String,
    footage_request_id: Uuid,
    opportunity_id: Uuid,
    #[serde(default)]
    concept_id: Option<Uuid>,
    summary: String,
    natural_request: NaturalFootageRequest,
    required_sources: Vec<RequestedSource>,
    optional_sources: Vec<RequestedSource>,
    alternative_sources: Vec<RequestedSource>,
    minimum_useful_source_keys: Vec<String>,
    smallest_useful_set_reason: String,
    intro_leads: Vec<IntroMaterialLead>,
    search_queries: Vec<String>,
    warnings: Vec<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct EditorialConceptScore {
    concept_specificity: f64,
    intro_strength: f64,
    emotional_arc_strength: f64,
    narrative_bridge_strength: f64,
    fan_recognition: f64,
    current_event_relevance: f64,
    legacy_context_value: f64,
    payoff_strength: f64,
    footage_feasibility: f64,
    source_actionability: f64,
    originality: f64,
    evidence_quality: f64,
    uncertainty_penalty: f64,
    total: f64,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct EditorialConcept {
    schema_version: String,
    concept_id: Uuid,
    opportunity_id: Uuid,
    #[serde(default)]
    dossier_id: Option<Uuid>,
    concept_key: String,
    title: String,
    central_subject: String,
    central_relationship: Option<String>,
    core_emotion: String,
    viewer_hook: String,
    why_fans_may_care: String,
    current_event: String,
    legacy_or_contextual_connection: String,
    legacy_connection_type: String,
    intro_leads: Vec<IntroMaterialLead>,
    song_handoff_idea: String,
    montage_arc: Vec<String>,
    ending_or_payoff: String,
    evidence: Vec<OpportunityEvidenceRef>,
    verification_status: String,
    score: EditorialConceptScore,
    known_uncertainties: Vec<String>,
    footage_request: FootageRequest,
    provisional_notice: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct CandidateFunnelRejection {
    reason_code: String,
    count: i64,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct CandidateScoreTrace {
    metric: String,
    value: Option<f64>,
    count_value: Option<i64>,
    threshold: Option<f64>,
    count_threshold: Option<i64>,
    status: String,
    note: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct CandidateDiagnostic {
    candidate_name: String,
    title: String,
    shortlist_rank: i64,
    shortlist_reason: String,
    current_hook: Option<String>,
    audience_fit_evidence: Vec<String>,
    fandom_evidence: Vec<String>,
    story_or_episode_evidence: Vec<String>,
    source_categories: Vec<String>,
    evidence_references: Vec<Uuid>,
    inferred_short_form_edit_potential: String,
    scores_and_thresholds: Vec<CandidateScoreTrace>,
    exact_rejection_gate: String,
    failure_class: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct CandidateFunnel {
    schema_version: String,
    parsed_intent: i64,
    generated_search_variants: i64,
    raw_release_candidates: i64,
    candidates_after_freshness: i64,
    candidates_after_hard_exclusions: i64,
    candidates_after_audience_fit_screening: i64,
    candidates_selected_for_social_research: i64,
    candidates_with_usable_social_evidence: i64,
    candidates_surviving_evidence_gates: i64,
    candidates_surviving_deduplication: i64,
    candidates_sent_to_final_ranker: i64,
    final_opportunities_serialized: i64,
    removed_by_hard_constraints: i64,
    lacking_current_fandom_evidence: i64,
    lacking_actionable_footage_information: i64,
    #[serde(default)]
    false_abstention_recovery_attempted: bool,
    #[serde(default)]
    recovered_candidate_count: i64,
    #[serde(default)]
    evidence_coverage_warning: Option<String>,
    rejection_reasons: Vec<CandidateFunnelRejection>,
    #[serde(default)]
    candidate_diagnostics: Vec<CandidateDiagnostic>,
    shortage_explanation: Option<String>,
    suggestions: Vec<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct CanonicalResearchResult {
    schema_version: String,
    run_id: Uuid,
    status: String,
    intent: CanonicalResearchIntent,
    opportunities: Vec<Opportunity>,
    footage_requests: Vec<FootageRequest>,
    #[serde(default)]
    editorial_concepts: Vec<EditorialConcept>,
    #[serde(default)]
    fandom_story_dossiers: Vec<FandomStoryDossier>,
    candidate_funnel: Option<CandidateFunnel>,
    message: String,
    applied_exclusions: Vec<String>,
    warnings: Vec<String>,
    generated_at: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct EvidenceView {
    evidence_id: Uuid,
    source_id: Uuid,
    claim_id: Uuid,
    provider: String,
    title: String,
    publisher: String,
    source_type: String,
    verification: String,
    retrieved_at: String,
    published_at: Option<String>,
    event_or_release_at: Option<String>,
    excerpt_type: String,
    excerpt: String,
    link_handle: Uuid,
    independence_group: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct QuoteView {
    status: String,
    text: String,
    speaker: Option<String>,
    likely_context: Option<String>,
    claim_id: Uuid,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DossierEvidenceFactView {
    text: String,
    verification_status: String,
    supporting_evidence: Vec<EvidenceView>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DossierCharacterView {
    character_name: String,
    performer_name: Option<String>,
    show_or_title: String,
    verification_status: String,
    supporting_evidence: Vec<EvidenceView>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DossierCurrentSourceView {
    source_kind: String,
    show_or_title: String,
    source_title: String,
    season_number: Option<i64>,
    episode_number: Option<i64>,
    episode_title: Option<String>,
    verification_status: String,
    supporting_evidence: Vec<EvidenceView>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DossierQuoteLeadView {
    quote: QuoteView,
    source_title: String,
    verification_status: String,
    supporting_evidence: Vec<EvidenceView>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DossierFranchiseConnectionView {
    connection_type: String,
    current_title: String,
    connected_title: String,
    characters: Vec<String>,
    description: String,
    verification_status: String,
    supporting_evidence: Vec<EvidenceView>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct FandomStoryDossierView {
    dossier_id: Uuid,
    current_event_or_hook: DossierEvidenceFactView,
    named_characters: Vec<DossierCharacterView>,
    central_relationship: Option<DossierEvidenceFactView>,
    current_source: DossierCurrentSourceView,
    exact_or_likely_quote: Option<DossierQuoteLeadView>,
    franchise_connections: Vec<DossierFranchiseConnectionView>,
    relationship_or_character_history: Vec<DossierEvidenceFactView>,
    why_fans_currently_care: Vec<DossierEvidenceFactView>,
    audience_and_fandom_evidence: Vec<DossierEvidenceFactView>,
    uncertainties: Vec<String>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct RequestedSourceView {
    source_id: Uuid,
    source_key: String,
    group: String,
    priority: i64,
    purposes: Vec<String>,
    show_or_title: String,
    season_number: Option<i64>,
    episode_number: Option<i64>,
    episode_title: Option<String>,
    asset_kind: String,
    characters: Vec<String>,
    relationship_or_topic: Option<String>,
    scene_or_moment: String,
    quote: Option<QuoteView>,
    why_it_matters_emotionally: String,
    verification_level: String,
    source_quality_summary: String,
    supporting_claim_ids: Vec<Uuid>,
    supporting_evidence: Vec<EvidenceView>,
    acquisition_effort: i64,
    search_queries: Vec<String>,
    replaces_required_source_keys: Vec<String>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct IntroMaterialLeadView {
    intro_lead_id: Uuid,
    source_key: String,
    moment_description: String,
    quote: Option<QuoteView>,
    why_it_might_lead_into_montage: String,
    verification_level: String,
    supporting_claim_ids: Vec<Uuid>,
    supporting_evidence: Vec<EvidenceView>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct FootageRequestView {
    request_id: Uuid,
    concept_id: Option<Uuid>,
    summary: String,
    natural_request: NaturalFootageRequest,
    minimum_useful_source_keys: Vec<String>,
    smallest_useful_set_reason: String,
    required_sources: Vec<RequestedSourceView>,
    optional_sources: Vec<RequestedSourceView>,
    alternative_sources: Vec<RequestedSourceView>,
    intro_leads: Vec<IntroMaterialLeadView>,
    search_queries: Vec<String>,
    warnings: Vec<String>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct IntentFacetView {
    facet_id: String,
    category: String,
    label: String,
    source: String,
    removable: bool,
    rationale: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct IntentInterpretationView {
    facets: Vec<IntentFacetView>,
    broad_query: bool,
    clarification_needed: bool,
    clarification_reason: Option<String>,
    direct_tiktok_data_used: bool,
    short_form_inference_disclaimer: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CandidateFunnelView {
    parsed_intent: i64,
    generated_search_variants: i64,
    raw_release_candidates: i64,
    candidates_after_freshness: i64,
    candidates_after_hard_exclusions: i64,
    candidates_after_audience_fit_screening: i64,
    candidates_selected_for_social_research: i64,
    candidates_with_usable_social_evidence: i64,
    candidates_surviving_evidence_gates: i64,
    candidates_surviving_deduplication: i64,
    candidates_sent_to_final_ranker: i64,
    final_opportunities_serialized: i64,
    final_opportunities_received_by_rust: usize,
    final_opportunities_displayed_by_ui: usize,
    removed_by_hard_constraints: i64,
    lacking_current_fandom_evidence: i64,
    lacking_actionable_footage_information: i64,
    false_abstention_recovery_attempted: bool,
    recovered_candidate_count: i64,
    evidence_coverage_warning: Option<String>,
    rejection_reasons: Vec<CandidateFunnelRejection>,
    candidate_diagnostics: Vec<CandidateDiagnostic>,
    shortage_explanation: Option<String>,
    suggestions: Vec<String>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct OpportunityQualityScoreView {
    profile_id: String,
    intent_fit: f64,
    audience_fit: f64,
    freshness: f64,
    fandom_velocity: f64,
    short_form_edit_potential: f64,
    relationship_or_character_salience: f64,
    footage_actionability: f64,
    evidence_quality: f64,
    source_diversity: f64,
    uncertainty_penalty: f64,
    total: f64,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ShortFormEditPotentialView {
    metric_name: String,
    band: String,
    explanation: String,
    signals: Vec<String>,
    direct_tiktok_data_used: bool,
    disclaimer: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct EditorialConceptScoreView {
    concept_specificity: f64,
    intro_strength: f64,
    emotional_arc_strength: f64,
    narrative_bridge_strength: f64,
    fan_recognition: f64,
    current_event_relevance: f64,
    legacy_context_value: f64,
    payoff_strength: f64,
    footage_feasibility: f64,
    source_actionability: f64,
    originality: f64,
    evidence_quality: f64,
    uncertainty_penalty: f64,
    total: f64,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct EditorialConceptView {
    concept_id: Uuid,
    dossier_id: Option<Uuid>,
    title: String,
    central_subject: String,
    central_relationship: Option<String>,
    core_emotion: String,
    viewer_hook: String,
    why_fans_may_care: String,
    current_event: String,
    legacy_or_contextual_connection: String,
    legacy_connection_type: String,
    intro_leads: Vec<IntroMaterialLeadView>,
    song_handoff_idea: String,
    montage_arc: Vec<String>,
    ending_or_payoff: String,
    verification_status: String,
    score: EditorialConceptScoreView,
    known_uncertainties: Vec<String>,
    footage_request: FootageRequestView,
    provisional_notice: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct OpportunityView {
    opportunity_id: Uuid,
    rank: usize,
    title: String,
    media_kind: String,
    focus: String,
    why_now: String,
    viewer_conversation: String,
    creative_hook: String,
    emotional_edit_idea: String,
    promising_intro_material: Option<String>,
    intro_caveat: String,
    evidence_gate: String,
    confidence: f64,
    quality_score: Option<OpportunityQualityScoreView>,
    short_form_edit_potential: Option<ShortFormEditPotentialView>,
    fandom_story_dossier: Option<FandomStoryDossierView>,
    editorial_concepts: Vec<EditorialConceptView>,
    recommended_concept_id: Option<Uuid>,
    evidence: Vec<EvidenceView>,
    footage_request: FootageRequestView,
    caveats: Vec<String>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct EvidenceReviewBreakdownView {
    metadata_records: usize,
    verified_why_now_records: usize,
    current_discussion_signals: usize,
}

#[derive(Debug, Clone, Serialize)]
#[serde(tag = "outcome", rename_all = "SCREAMING_SNAKE_CASE", rename_all_fields = "camelCase")]
pub enum ResearchResultView {
    Opportunities {
        research_run_id: Uuid,
        run_timestamp: String,
        pipeline_version: &'static str,
        provider_config_id: &'static str,
        query_summary: String,
        freshness_cutoff: String,
        interpretation: Option<IntentInterpretationView>,
        candidate_funnel: Option<CandidateFunnelView>,
        opportunities: Vec<OpportunityView>,
    },
    NoStrongOpportunity {
        research_run_id: Uuid,
        run_timestamp: String,
        pipeline_version: &'static str,
        provider_config_id: &'static str,
        query_summary: String,
        freshness_cutoff: String,
        explanation: String,
        interpretation: Option<IntentInterpretationView>,
        candidate_funnel: Option<CandidateFunnelView>,
        evidence_reviewed: usize,
        evidence_breakdown: EvidenceReviewBreakdownView,
        suggestions: Vec<String>,
    },
}

#[derive(Debug, Clone)]
pub struct PersistedEvidenceSource {
    pub id: Uuid,
    pub provider: String,
    pub provider_record_id: Option<String>,
    pub source_type: String,
    pub canonical_url: String,
    pub title: String,
    pub author_or_channel: Option<String>,
    pub source_created_at: Option<String>,
    pub source_updated_at: Option<String>,
    pub page_published_at: Option<String>,
    pub retrieved_at: String,
    pub query: String,
    pub window_start: Option<String>,
    pub window_end: Option<String>,
    pub independence_group: String,
    pub policy_class: String,
    pub content_sha256: String,
    pub refresh_due_at: Option<String>,
    pub purge_due_at: Option<String>,
    pub expires_at: Option<String>,
    pub deletion_required_at: Option<String>,
}

#[derive(Debug, Clone)]
pub struct PersistedEvidenceClaim {
    pub id: Uuid,
    pub source_id: Uuid,
    pub claim_kind: String,
    pub excerpt_type: String,
    pub text: String,
    pub episode_locator_json: Option<String>,
    pub quote_fact_json: Option<String>,
    pub why_now_event_json: Option<String>,
    pub scene_fact_json: Option<String>,
    pub cast_fact_json: Option<String>,
    pub event_or_release_at: Option<String>,
    pub verification: String,
    pub confidence_ppm: i64,
    pub supports_why_now: bool,
    pub content_sha256: String,
    pub canonical_contract_json: String,
}

#[derive(Debug, Clone)]
pub struct ValidatedResearchBundle {
    pub canonical_result_json: String,
    pub evidence_sources_json: String,
    pub evidence_claims_json: String,
    pub ui_view_json: String,
    pub sources: Vec<PersistedEvidenceSource>,
    pub claims: Vec<PersistedEvidenceClaim>,
}

impl ValidatedResearchBundle {
    pub fn cache_contract_json(&self) -> AppResult<String> {
        let result: serde_json::Value = serde_json::from_str(&self.canonical_result_json)?;
        let sources: serde_json::Value = serde_json::from_str(&self.evidence_sources_json)?;
        let claims: serde_json::Value = serde_json::from_str(&self.evidence_claims_json)?;
        Ok(serde_json::to_string(&serde_json::json!({
            "schemaVersion": "1.0.0",
            "result": result,
            "evidenceSources": sources,
            "evidenceClaims": claims,
        }))?)
    }

    pub(crate) fn rebind_evidence_source_ids(
        &self,
        replacements: &HashMap<Uuid, Uuid>,
    ) -> AppResult<Self> {
        if replacements.is_empty() {
            return Ok(self.clone());
        }

        let mut rebound = self.clone();
        let mut rebound_source_ids = HashSet::new();
        for source in &mut rebound.sources {
            source.id = replacements.get(&source.id).copied().unwrap_or(source.id);
            if !rebound_source_ids.insert(source.id) {
                return Err(AppError::DatabaseInvariant(
                    "evidence-source deduplication produced a duplicate canonical identity".to_owned(),
                ));
            }
        }
        for claim in &mut rebound.claims {
            claim.source_id = replacements
                .get(&claim.source_id)
                .copied()
                .unwrap_or(claim.source_id);
            let mut canonical: serde_json::Value = serde_json::from_str(&claim.canonical_contract_json)?;
            replace_source_references(&mut canonical, replacements)?;
            claim.canonical_contract_json = serde_json::to_string(&canonical)?;
        }

        for document in [
            &mut rebound.evidence_sources_json,
            &mut rebound.evidence_claims_json,
            &mut rebound.ui_view_json,
        ] {
            let mut value: serde_json::Value = serde_json::from_str(document)?;
            replace_source_references(&mut value, replacements)?;
            *document = serde_json::to_string(&value)?;
        }
        Ok(rebound)
    }
}

fn replace_source_references(
    value: &mut serde_json::Value,
    replacements: &HashMap<Uuid, Uuid>,
) -> AppResult<()> {
    match value {
        serde_json::Value::Array(values) => {
            for value in values {
                replace_source_references(value, replacements)?;
            }
        }
        serde_json::Value::Object(object) => {
            for (key, value) in object {
                if matches!(key.as_str(), "sourceId" | "linkHandle") {
                    if let Some(raw) = value.as_str() {
                        let source_id = Uuid::parse_str(raw).map_err(|_| {
                            AppError::DatabaseInvariant(
                                "validated evidence JSON contains an invalid source identity".to_owned(),
                            )
                        })?;
                        if let Some(replacement) = replacements.get(&source_id) {
                            *value = serde_json::Value::String(replacement.to_string());
                        }
                    }
                } else {
                    replace_source_references(value, replacements)?;
                }
            }
        }
        _ => {}
    }
    Ok(())
}

pub fn parse_intent(value: serde_json::Value) -> AppResult<CanonicalResearchIntent> {
    let intent: CanonicalResearchIntent = serde_json::from_value(value)
        .map_err(|_| AppError::Worker("worker returned an invalid canonical research intent".to_owned()))?;
    validate_intent(&intent)?;
    Ok(intent)
}

pub fn parse_bundle(
    result: serde_json::Value,
    sources: Vec<serde_json::Value>,
    claims: Vec<serde_json::Value>,
    expected_run_id: Uuid,
    expected_intent: &CanonicalResearchIntent,
    trusted_policies: &[TrustedEvidencePolicyRecord],
) -> AppResult<ValidatedResearchBundle> {
    let result: CanonicalResearchResult = serde_json::from_value(result)
        .map_err(|_| AppError::Worker("worker returned an invalid canonical research result".to_owned()))?;
    let sources = sources.into_iter().map(|value| serde_json::from_value(value)
        .map_err(|_| AppError::Worker("worker returned an invalid canonical evidence source".to_owned())))
        .collect::<AppResult<Vec<EvidenceSource>>>()?;
    let claims = claims.into_iter().map(|value| serde_json::from_value(value)
        .map_err(|_| AppError::Worker("worker returned an invalid canonical evidence claim".to_owned())))
        .collect::<AppResult<Vec<EvidenceClaim>>>()?;
    if result.run_id != expected_run_id || &result.intent != expected_intent {
        return Err(AppError::Worker("worker result is not bound to the requested job and normalized intent".to_owned()));
    }
    validate_bundle(&result, &sources, &claims, trusted_policies)?;
    let view = map_view(&result, &sources, &claims)?;
    let persisted_sources = sources.iter().map(|source| PersistedEvidenceSource {
        id: source.source_id,
        provider: source.provider.clone(),
        provider_record_id: source.provider_record_id.clone(),
        source_type: source.source_type.clone(),
        canonical_url: source.canonical_url.clone(),
        title: source.title.clone(),
        author_or_channel: source.author_or_channel.clone(),
        source_created_at: source.source_created_at.clone(),
        source_updated_at: source.source_updated_at.clone(),
        page_published_at: source.page_published_at.clone(),
        retrieved_at: source.retrieved_at.clone(),
        query: source.query.clone(),
        window_start: source.window_start.clone(),
        window_end: source.window_end.clone(),
        independence_group: source.independence_group.clone(),
        policy_class: source.policy_class.clone(),
        content_sha256: source.content_sha256.clone(),
        refresh_due_at: source.refresh_due_at.clone(),
        purge_due_at: source.purge_due_at.clone(),
        expires_at: source.expires_at.clone(),
        deletion_required_at: source.deletion_required_at.clone(),
    }).collect();
    let persisted_claims = claims.iter().map(|claim| -> AppResult<PersistedEvidenceClaim> {
        Ok(PersistedEvidenceClaim {
            id: claim.claim_id,
            source_id: claim.source_id,
            claim_kind: claim.claim_kind.clone(),
            excerpt_type: claim.excerpt_type.clone(),
            text: claim.text.clone(),
            episode_locator_json: claim.episode_locator.as_ref().map(serde_json::to_string).transpose()?,
            quote_fact_json: claim.quote_fact.as_ref().map(serde_json::to_string).transpose()?,
            why_now_event_json: claim.why_now_event.as_ref().map(serde_json::to_string).transpose()?,
            scene_fact_json: claim.scene_fact.as_ref().map(serde_json::to_string).transpose()?,
            cast_fact_json: claim.cast_fact.as_ref().map(serde_json::to_string).transpose()?,
            event_or_release_at: claim.event_or_release_at.clone(),
            verification: claim.verification.clone(),
            confidence_ppm: (claim.confidence * 1_000_000.0).round() as i64,
            supports_why_now: claim.supports_why_now,
            content_sha256: claim.content_sha256.clone(),
            canonical_contract_json: serde_json::to_string(claim)?,
        })
    }).collect::<AppResult<Vec<_>>>()?;
    Ok(ValidatedResearchBundle {
        canonical_result_json: serde_json::to_string(&result)?,
        evidence_sources_json: serde_json::to_string(&sources)?,
        evidence_claims_json: serde_json::to_string(&claims)?,
        ui_view_json: serde_json::to_string(&view)?,
        sources: persisted_sources,
        claims: persisted_claims,
    })
}

pub fn validate_reusable_evidence(
    source_values: &[serde_json::Value],
    claim_values: &[serde_json::Value],
    generated_at: &str,
    trusted_policies: &[TrustedEvidencePolicyRecord],
) -> AppResult<()> {
    if source_values.len() > 64 || claim_values.len() > 128 {
        return Err(AppError::DatabaseInvariant(
            "reusable evidence exceeded its bounded contract".to_owned(),
        ));
    }
    let Some(now) = parse_timestamp(generated_at) else {
        return Err(AppError::DatabaseInvariant(
            "reusable evidence has no trusted evaluation time".to_owned(),
        ));
    };
    let sources = source_values
        .iter()
        .cloned()
        .map(|value| {
            serde_json::from_value::<EvidenceSource>(value).map_err(|_| {
                AppError::DatabaseInvariant(
                    "reusable evidence source violates its canonical schema".to_owned(),
                )
            })
        })
        .collect::<AppResult<Vec<_>>>()?;
    let claims = claim_values
        .iter()
        .cloned()
        .map(|value| {
            serde_json::from_value::<EvidenceClaim>(value).map_err(|_| {
                AppError::DatabaseInvariant(
                    "reusable evidence claim violates its canonical schema".to_owned(),
                )
            })
        })
        .collect::<AppResult<Vec<_>>>()?;
    let mut all_ids = HashSet::new();
    let mut source_by_id = HashMap::new();
    for source in &sources {
        if source.provider != "openai"
            || source.source_type != "ARTICLE"
            || !insert_uuid_v4(&mut all_ids, source.source_id)
            || source_by_id.insert(source.source_id, source).is_some()
            || !validate_evidence_source(source, now, trusted_policies)
        {
            return Err(AppError::DatabaseInvariant(
                "reusable evidence source failed trusted policy validation".to_owned(),
            ));
        }
    }
    let mut claim_ids = HashSet::new();
    for claim in &claims {
        let Some(source) = source_by_id.get(&claim.source_id) else {
            return Err(AppError::DatabaseInvariant(
                "reusable evidence claim lost its source".to_owned(),
            ));
        };
        if claim.claim_kind != "VIEWER_DISCUSSION"
            || claim.verification != "SECONDARY_CORROBORATED"
            || !claim.supports_why_now
            || !insert_uuid_v4(&mut all_ids, claim.claim_id)
            || !claim_ids.insert(claim.claim_id)
            || !validate_evidence_claim(claim, source)
        {
            return Err(AppError::DatabaseInvariant(
                "reusable evidence claim failed trusted domain validation".to_owned(),
            ));
        }
    }
    if sources.iter().any(|source| {
        !claims.iter().any(|claim| claim.source_id == source.source_id)
    }) {
        return Err(AppError::DatabaseInvariant(
            "reusable evidence included an unclaimed source".to_owned(),
        ));
    }
    Ok(())
}

/// Recheck a host-owned whole-result cache snapshot against the actual replay time.
///
/// The canonical result keeps its original `generatedAt` because its deterministic
/// freshness scores are bound to that instant. This separate check prevents that
/// preserved timestamp from extending refresh, expiry, purge, deletion, or provider
/// policy deadlines when the result is replayed later.
pub fn validate_cached_evidence_currentness(
    source_values: &[serde_json::Value],
    replayed_at: &str,
    trusted_policies: &[TrustedEvidencePolicyRecord],
) -> AppResult<()> {
    let Some(now) = parse_timestamp(replayed_at) else {
        return Err(AppError::DatabaseInvariant(
            "cached evidence replay time is invalid".to_owned(),
        ));
    };
    for value in source_values {
        let source: EvidenceSource = serde_json::from_value(value.clone()).map_err(|_| {
            AppError::DatabaseInvariant(
                "cached evidence source violates its canonical schema".to_owned(),
            )
        })?;
        let mut matching = trusted_policies.iter().filter(|policy| {
            policy.provider == source.provider && policy.policy_class == source.policy_class
        });
        let Some(policy) = matching.next() else {
            return Err(AppError::DatabaseInvariant(
                "cached evidence policy is no longer trusted".to_owned(),
            ));
        };
        let current_policy = matching.next().is_none()
            && policy.checked_at_ms as i128 * 1_000_000 <= now.0
            && policy.expires_at_ms as i128 * 1_000_000 >= now.0;
        let current_source = parse_timestamp(&source.retrieved_at).is_some_and(|retrieved| {
                retrieved <= now.checked_add_seconds(300).unwrap_or(now)
            })
            && [
                source.refresh_due_at.as_deref(),
                source.expires_at.as_deref(),
                source.purge_due_at.as_deref(),
            ]
            .into_iter()
            .all(|deadline| deadline.and_then(parse_timestamp).is_some_and(|value| value > now))
            && source
                .deletion_required_at
                .as_deref()
                .and_then(parse_timestamp)
                .is_none_or(|value| value > now);
        if !current_policy || !current_source {
            return Err(AppError::DatabaseInvariant(
                "cached evidence is past a trusted refresh or deletion boundary".to_owned(),
            ));
        }
    }
    Ok(())
}

fn validate_intent(intent: &CanonicalResearchIntent) -> AppResult<()> {
    if intent.schema_version != V2
        || !valid_text(&intent.query, 4_000)
        || intent.media_kinds.is_empty() || intent.media_kinds.len() > 5
        || intent.focus_terms.len() > 20 || intent.exclusions.len() > 30
        || !(1..=90).contains(&intent.freshness_days)
        || !(1..=10).contains(&intent.max_results)
        || !matches!(intent.spoiler_policy.as_str(), "AVOID" | "CURRENT_EPISODE" | "ALLOW")
        || !valid_text(&intent.region, 16) || intent.region.chars().count() < 2
        || intent.media_kinds.iter().any(|kind| !is_media_kind(kind))
        || intent.focus_terms.iter().any(|value| !valid_text(value, 500))
        || intent.exclusions.iter().any(|value| !valid_text(value, 500))
        || !unique_casefolded(&intent.media_kinds)
        || !unique_casefolded(&intent.focus_terms)
        || !unique_casefolded(&intent.exclusions)
        || intent.interpretation.as_ref().is_some_and(|value| !valid_intent_interpretation(value))
    {
        return Err(AppError::Worker("canonical research intent failed domain validation".to_owned()));
    }
    Ok(())
}

fn valid_intent_interpretation(value: &IntentInterpretation) -> bool {
    if value.schema_version != "1.0.0"
        || value.facets.len() > 30
        || value.search_questions.len() > 20
        || value.clarification_needed != value.clarification_reason.is_some()
        || value.clarification_reason.as_deref().is_some_and(|text| !valid_text(text, 500))
        || (value.direct_tiktok_data_used && value.short_form_inference_disclaimer.is_some())
        || value.short_form_inference_disclaimer.as_deref().is_some_and(|text| !valid_text(text, 500))
    {
        return false;
    }
    let facet_ids = value.facets.iter().map(|item| item.facet_id.as_str()).collect::<Vec<_>>();
    let question_ids = value.search_questions.iter().map(|item| item.question_id.as_str()).collect::<Vec<_>>();
    facet_ids.iter().all(|id| valid_identifier(id, 64))
        && question_ids.iter().all(|id| valid_identifier(id, 64))
        && unique_borrowed(&facet_ids)
        && unique_borrowed(&question_ids)
        && value.facets.iter().all(|item| {
            matches!(item.category.as_str(), "HARD_CONSTRAINT" | "SOFT_PREFERENCE" | "AUDIENCE" | "PLATFORM_FIT" | "CREATIVE_EDIT")
                && matches!(item.source.as_str(), "EXPLICIT" | "INFERRED_PRIOR")
                && valid_text(&item.label, 80)
                && valid_text(&item.rationale, 300)
        })
        && value.search_questions.iter().all(|item| {
            valid_text(&item.query, 500) && valid_text(&item.evidence_goal, 300)
        })
}

fn valid_candidate_diagnostic(value: &CandidateDiagnostic) -> bool {
    let mut metrics = HashSet::new();
    let valid_scores = value.scores_and_thresholds.len() <= 30
        && !value.scores_and_thresholds.is_empty()
        && value.scores_and_thresholds.iter().all(|score| {
            let float_values = [score.value, score.threshold];
            let count_values = [score.count_value, score.count_threshold];
            valid_text(&score.metric, 80)
                && score.metric.bytes().all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'_')
                && metrics.insert(score.metric.as_str())
                && float_values.into_iter().flatten().all(|item| item.is_finite() && (0.0..=1.0).contains(&item))
                && count_values.into_iter().flatten().all(|item| (0..=1_000).contains(&item))
                && !(score.value.is_some() && score.count_value.is_some())
                && !(score.threshold.is_some() && score.count_threshold.is_some())
                && matches!(score.status.as_str(), "PASSED" | "FAILED" | "INFORMATIONAL" | "NOT_COMPUTED")
                && (score.status != "NOT_COMPUTED" || (score.value.is_none() && score.count_value.is_none()))
                && valid_text(&score.note, 500)
        });
    let valid_gate = !value.exact_rejection_gate.is_empty()
        && value.exact_rejection_gate.len() <= 160
        && value.exact_rejection_gate.bytes().all(|byte| {
            byte.is_ascii_uppercase() || byte.is_ascii_digit() || matches!(byte, b':' | b'.' | b'_' | b'-')
        });
    (1..=1_000).contains(&value.shortlist_rank)
        && valid_text(&value.candidate_name, 500)
        && valid_text(&value.title, 500)
        && valid_text(&value.shortlist_reason, 500)
        && value.current_hook.as_deref().is_none_or(|item| valid_text(item, 500))
        && value.audience_fit_evidence.len() <= 12
        && value.fandom_evidence.len() <= 12
        && value.story_or_episode_evidence.len() <= 12
        && value.source_categories.len() <= 20
        && value.evidence_references.len() <= 40
        && value.audience_fit_evidence.iter().all(|item| valid_text(item, 500))
        && value.fandom_evidence.iter().all(|item| valid_text(item, 500))
        && value.story_or_episode_evidence.iter().all(|item| valid_text(item, 500))
        && value.source_categories.iter().all(|item| valid_text(item, 500))
        && value.evidence_references.iter().copied().collect::<HashSet<_>>().len()
            == value.evidence_references.len()
        && valid_text(&value.inferred_short_form_edit_potential, 500)
        && valid_scores
        && valid_gate
        && matches!(
            value.failure_class.as_str(),
            "RETRIEVAL_RELATED" | "EVIDENCE_RELATED" | "THRESHOLD_RELATED" | "SUPPORTED"
        )
        && ((value.failure_class == "SUPPORTED") == (value.exact_rejection_gate == "SUPPORTED"))
}

fn valid_candidate_funnel(value: &CandidateFunnel, result_count: usize) -> bool {
    let counts = [
        value.parsed_intent,
        value.generated_search_variants,
        value.raw_release_candidates,
        value.candidates_after_freshness,
        value.candidates_after_hard_exclusions,
        value.candidates_after_audience_fit_screening,
        value.candidates_selected_for_social_research,
        value.candidates_with_usable_social_evidence,
        value.candidates_surviving_evidence_gates,
        value.candidates_surviving_deduplication,
        value.candidates_sent_to_final_ranker,
        value.final_opportunities_serialized,
        value.removed_by_hard_constraints,
        value.lacking_current_fandom_evidence,
        value.lacking_actionable_footage_information,
        value.recovered_candidate_count,
    ];
    let reason_codes = value.rejection_reasons.iter().map(|item| item.reason_code.as_str()).collect::<Vec<_>>();
    let diagnostic_titles = value.candidate_diagnostics.iter().map(|item| item.title.to_lowercase()).collect::<Vec<_>>();
    let diagnostic_ranks = value.candidate_diagnostics.iter().map(|item| item.shortlist_rank).collect::<Vec<_>>();
    value.schema_version == "1.0.0"
        && value.parsed_intent <= 1
        && counts.into_iter().all(|count| (0..=1_000_000).contains(&count))
        && value.final_opportunities_serialized as usize == result_count
        && value.rejection_reasons.len() <= 50
        && value.rejection_reasons.iter().all(|item| {
            (1..=1_000_000).contains(&item.count)
                && !item.reason_code.is_empty()
                && item.reason_code.len() <= 120
                && item.reason_code.bytes().all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || matches!(byte, b':' | b'.' | b'_' | b'-'))
        })
        && unique_borrowed(&reason_codes)
        && value.candidate_diagnostics.len() <= 30
        && value.candidate_diagnostics.iter().all(valid_candidate_diagnostic)
        && diagnostic_titles.iter().collect::<HashSet<_>>().len() == diagnostic_titles.len()
        && diagnostic_ranks.iter().collect::<HashSet<_>>().len() == diagnostic_ranks.len()
        && value.suggestions.len() <= 10
        && value.suggestions.iter().all(|item| valid_text(item, 500))
        && value.shortage_explanation.as_deref().is_none_or(|item| result_count < 3 && valid_text(item, 1_000))
        && (result_count < 3 || value.shortage_explanation.is_none())
        && (!value.false_abstention_recovery_attempted
            || value.evidence_coverage_warning.as_deref().is_none_or(|item| {
                result_count == 0 && valid_text(item, 1_000)
            }))
        && (value.false_abstention_recovery_attempted
            || (value.recovered_candidate_count == 0 && value.evidence_coverage_warning.is_none()))
        && value.removed_by_hard_constraints
            == (value.candidates_after_freshness - value.candidates_after_hard_exclusions).max(0)
        && value.lacking_current_fandom_evidence
            == (value.candidates_selected_for_social_research - value.candidates_with_usable_social_evidence).max(0)
        && value.lacking_actionable_footage_information
            == (value.candidates_surviving_evidence_gates - value.candidates_sent_to_final_ranker).max(0)
}

fn validate_bundle(
    result: &CanonicalResearchResult,
    sources: &[EvidenceSource],
    claims: &[EvidenceClaim],
    trusted_policies: &[TrustedEvidencePolicyRecord],
) -> AppResult<()> {
    validate_intent(&result.intent)?;
    let Some(now) = parse_timestamp(&result.generated_at) else { return invalid_bundle_at("generated_at"); };
    if result.schema_version != V2 { return invalid_bundle_at("result_schema"); }
    if result.candidate_funnel.as_ref().is_some_and(|value| !valid_candidate_funnel(value, result.opportunities.len())) {
        return invalid_bundle_at("candidate_funnel");
    }
    if !valid_text(&result.message, 2_000) { return invalid_bundle_at("result_message_shape"); }
    if result.opportunities.len() > result.intent.max_results as usize { return invalid_bundle_at("result_count"); }
    if result.warnings.len() > 30 { return invalid_bundle_at("result_warning_count"); }
    if result.warnings.iter().any(|value| !valid_text(value, 500)) { return invalid_bundle_at("result_warning_shape"); }
    if result.applied_exclusions.len() > 30 { return invalid_bundle_at("result_exclusion_count"); }
    if result.applied_exclusions.iter().map(|value| value.to_lowercase()).collect::<Vec<_>>()
        != result.intent.exclusions.iter().map(|value| value.to_lowercase()).collect::<Vec<_>>()
    {
        return invalid_bundle_at("result_exclusions");
    }
    if contains_prohibited_or_viral_text(&result.message) { return invalid_bundle_at("result_message_policy"); }
    if result.warnings.iter().any(|value| contains_prohibited_or_viral_text(value)) {
        return invalid_bundle_at("result_warning_policy");
    }
    if (result.status == "NO_STRONG_OPPORTUNITY") != (result.opportunities.is_empty() && result.footage_requests.is_empty())
        || !matches!(result.status.as_str(), "OPPORTUNITIES" | "NO_STRONG_OPPORTUNITY")
        || result.opportunities.len() != result.footage_requests.len()
        || (result.status == "NO_STRONG_OPPORTUNITY"
            && (!result.editorial_concepts.is_empty() || !result.fandom_story_dossiers.is_empty()))
    {
        return invalid_bundle_at("result_shape");
    }
    let mut all_ids = HashSet::new();
    if !insert_uuid_v4(&mut all_ids, result.run_id) {
        return invalid_bundle_at("run_id");
    }
    let mut source_by_id = HashMap::new();
    for source in sources {
        if !insert_uuid_v4(&mut all_ids, source.source_id)
            || source_by_id.insert(source.source_id, source).is_some()
            || !validate_evidence_source(source, now, trusted_policies)
        {
            return invalid_bundle_at("evidence_source");
        }
    }
    let mut claim_by_id = HashMap::new();
    for claim in claims {
        if !insert_uuid_v4(&mut all_ids, claim.claim_id)
            || claim_by_id.insert(claim.claim_id, claim).is_some()
            || !source_by_id.contains_key(&claim.source_id)
            || !validate_evidence_claim(claim, source_by_id[&claim.source_id])
        {
            return invalid_bundle_at("evidence_claim");
        }
    }
    let request_by_opportunity = result.footage_requests.iter().map(|request| (request.opportunity_id, request)).collect::<HashMap<_, _>>();
    if request_by_opportunity.len() != result.footage_requests.len() {
        return invalid_bundle_at("request_join");
    }
    let mut prior_sort_key: Option<(f64, String)> = None;
    for opportunity in &result.opportunities {
        let Some(request) = request_by_opportunity.get(&opportunity.opportunity_id).copied() else { return invalid_bundle_at("opportunity_request_join"); };
        if !insert_uuid_v4(&mut all_ids, opportunity.opportunity_id)
            || !insert_uuid_v4(&mut all_ids, request.footage_request_id)
            || opportunity.opportunity_id != request.opportunity_id
            || opportunity.footage_request_id != request.footage_request_id
        {
            return invalid_bundle_at("opportunity_request_ids");
        }
        if let Err(stage) = validate_opportunity_and_request(
            opportunity,
            request,
            &result.intent,
            now,
            &source_by_id,
            &claim_by_id,
            &mut all_ids,
        ) {
            return invalid_bundle_at(stage);
        }
        let sort_key = (
            -opportunity.quality_score.as_ref().map_or(opportunity.score.total, |score| score.total),
            opportunity.title.to_lowercase(),
        );
        if prior_sort_key.as_ref().is_some_and(|prior| prior > &sort_key) {
            return invalid_bundle_at("opportunity_sort");
        }
        prior_sort_key = Some(sort_key);
    }
    if let Err(stage) = validate_fandom_story_dossiers(result, &source_by_id, &claim_by_id, &mut all_ids) {
        return invalid_bundle_at(stage);
    }
    if let Err(stage) = validate_editorial_concepts(result, &request_by_opportunity, &source_by_id, &claim_by_id, &mut all_ids) {
        return invalid_bundle_at(stage);
    }
    Ok(())
}

fn structured_claim_shape_is_valid(claim: &EvidenceClaim) -> bool {
    if claim.excerpt_type == "SHORT_QUOTE" && claim.claim_kind != "QUOTE" {
        return false;
    }
    if claim.supports_why_now && !matches!(claim.claim_kind.as_str(), "WHY_NOW" | "OFFICIAL_CLIP" | "VIEWER_DISCUSSION") {
        return false;
    }
    match claim.claim_kind.as_str() {
        "QUOTE" => claim.quote_fact.as_ref().is_some_and(|fact| {
                fact.exact_text == claim.text && quote_fact_is_valid(fact)
            })
            && claim.excerpt_type == "SHORT_QUOTE" && claim.episode_locator.is_none()
            && claim.why_now_event.is_none() && claim.scene_fact.is_none() && claim.cast_fact.is_none(),
        "EPISODE_IDENTITY" => claim.episode_locator.as_ref().is_some_and(episode_locator_is_valid) && claim.quote_fact.is_none()
            && claim.why_now_event.is_none() && claim.scene_fact.is_none() && claim.cast_fact.is_none(),
        "SCENE_CONTEXT" => claim.scene_fact.as_ref().is_some_and(scene_fact_is_valid) && claim.episode_locator.is_none()
            && claim.quote_fact.is_none() && claim.why_now_event.is_none() && claim.cast_fact.is_none(),
        "CAST_IDENTITY" => claim.cast_fact.as_ref().is_some_and(cast_fact_is_valid) && claim.episode_locator.is_none()
            && claim.quote_fact.is_none() && claim.why_now_event.is_none() && claim.scene_fact.is_none(),
        "WHY_NOW" | "OFFICIAL_CLIP" => claim.why_now_event.as_ref().is_some_and(|event| {
                why_now_event_is_valid(event)
                    && if event.media_identity.media_kind == "TV_EPISODE" {
                        claim.episode_locator.as_ref().is_some_and(|locator| {
                            media_identity_locator(&event.media_identity).as_ref() == Some(locator)
                        })
                    } else {
                        claim.episode_locator.is_none()
                    }
            })
            && claim.event_or_release_at.is_some()
            && claim.quote_fact.is_none() && claim.cast_fact.is_none()
            && (claim.claim_kind == "OFFICIAL_CLIP" || claim.scene_fact.is_none())
            && claim.scene_fact.as_ref().is_none_or(scene_fact_is_valid),
        "VIEWER_DISCUSSION" => claim.episode_locator.is_none() && claim.quote_fact.is_none()
            && claim.why_now_event.is_none() && claim.scene_fact.is_none() && claim.cast_fact.is_none(),
        _ => false,
    }
}

fn validate_evidence_source(
    source: &EvidenceSource,
    generated_at: Timestamp,
    trusted_policies: &[TrustedEvidencePolicyRecord],
) -> bool {
    let Some(retrieved) = parse_timestamp(&source.retrieved_at) else { return false; };
    let mut matching = trusted_policies.iter().filter(|policy| policy.provider == source.provider && policy.policy_class == source.policy_class);
    let Some(policy) = matching.next() else { return false; };
    if matching.next().is_some()
        || policy.checked_at_ms as i128 * 1_000_000 > generated_at.0
        || policy.expires_at_ms as i128 * 1_000_000 < generated_at.0
        || retrieved > generated_at.checked_add_seconds(300).unwrap_or(generated_at)
    {
        return false;
    }
    let date_values = [
        source.source_created_at.as_deref(), source.source_updated_at.as_deref(),
        source.page_published_at.as_deref(), source.window_start.as_deref(),
        source.window_end.as_deref(), source.refresh_due_at.as_deref(),
        source.purge_due_at.as_deref(), source.expires_at.as_deref(),
        source.deletion_required_at.as_deref(),
    ];
    if date_values.into_iter().flatten().any(|value| parse_timestamp(value).is_none()) {
        return false;
    }
    if let (Some(start), Some(end)) = (
        source.window_start.as_deref().and_then(parse_timestamp),
        source.window_end.as_deref().and_then(parse_timestamp),
    ) {
        if end <= start { return false; }
    }
    if [source.refresh_due_at.as_deref(), source.purge_due_at.as_deref(), source.expires_at.as_deref(), source.deletion_required_at.as_deref()]
        .into_iter().flatten().any(|value| parse_timestamp(value).is_none_or(|deadline| deadline <= retrieved))
    {
        return false;
    }
    let exact_deadlines = source.expires_at.as_deref().and_then(parse_timestamp) == retrieved.checked_add_seconds(policy.evidence_ttl_seconds)
        && source.refresh_due_at.as_deref().and_then(parse_timestamp) == retrieved.checked_add_seconds(policy.refresh_after_seconds)
        && source.purge_due_at.as_deref().and_then(parse_timestamp) == retrieved.checked_add_seconds(policy.purge_after_seconds)
        && source.deletion_required_at.as_deref().and_then(parse_timestamp)
            == policy.deletion_after_seconds.and_then(|seconds| retrieved.checked_add_seconds(seconds));
    source.schema_version == V2
        && matches!(source.source_type.as_str(), "PRIMARY_RELEASE" | "OFFICIAL_CLIP" | "PLATFORM_SIGNAL" | "ARTICLE" | "METADATA")
        && valid_text(&source.provider, 64)
        && valid_provider_record_id(source)
        && valid_https_url(&source.canonical_url)
        && valid_text(&source.title, 500)
        && source.author_or_channel.as_ref().is_none_or(|value| valid_optional_text(value, 200))
        && valid_text(&source.query, 1_000)
        && valid_text(&source.policy_class, 64)
        && valid_text(&source.independence_group, 128)
        && exact_deadlines
        && source.expires_at.as_deref().and_then(parse_timestamp).is_some_and(|value| value > generated_at)
        && source.purge_due_at.as_deref().and_then(parse_timestamp).is_some_and(|value| value > generated_at)
        && source.deletion_required_at.as_deref().and_then(parse_timestamp).is_none_or(|value| value > generated_at)
        && valid_hash(&source.content_sha256)
        && source.content_sha256 == evidence_source_hash(source)
}

fn validate_evidence_claim(claim: &EvidenceClaim, source: &EvidenceSource) -> bool {
    claim.schema_version == V2
        && matches!(claim.claim_kind.as_str(), "WHY_NOW" | "VIEWER_DISCUSSION" | "EPISODE_IDENTITY" | "QUOTE" | "SCENE_CONTEXT" | "OFFICIAL_CLIP" | "CAST_IDENTITY")
        && matches!(claim.excerpt_type.as_str(), "SHORT_QUOTE" | "PARAPHRASE" | "UNVERIFIED_QUOTE_LEAD")
        && matches!(claim.verification.as_str(), "PRIMARY_VERIFIED" | "SECONDARY_CORROBORATED" | "LEAD_ONLY" | "STALE" | "RETRACTED")
        && valid_text(&claim.text, 500)
        && valid_hash(&claim.content_sha256)
        && valid_confidence(claim.confidence)
        && claim.event_or_release_at.as_deref().is_none_or(|value| parse_timestamp(value).is_some())
        && structured_claim_shape_is_valid(claim)
        && claim.content_sha256 == evidence_claim_hash(claim, &source.content_sha256)
}

fn validate_opportunity_and_request(
    opportunity: &Opportunity,
    request: &FootageRequest,
    intent: &CanonicalResearchIntent,
    now: Timestamp,
    sources: &HashMap<Uuid, &EvidenceSource>,
    claims: &HashMap<Uuid, &EvidenceClaim>,
    all_ids: &mut HashSet<Uuid>,
) -> Result<(), &'static str> {
    if opportunity.schema_version != V2 || request.schema_version != V2
        || opportunity.media_kind != opportunity.media_identity.media_kind
        || !media_identity_is_valid(&opportunity.media_identity)
        || !intent.media_kinds.contains(&opportunity.media_kind)
        || !valid_focus(&opportunity.focus)
        || !valid_confidence(opportunity.confidence)
        || !matches!(opportunity.evidence_gate.as_str(), "PASSED" | "LOW_CONFIDENCE")
        || opportunity.evidence.is_empty() || opportunity.evidence.len() > 30
        || !valid_score(&opportunity.score)
        || opportunity.quality_score.as_ref().is_some_and(|score| !valid_quality_score(score))
        || opportunity.short_form_edit_potential.as_ref().is_some_and(|value| {
            !valid_short_form_potential(value, claims)
        })
    {
        return Err("opportunity_header");
    }
    if !required_focus_is_supported(opportunity, intent, now, sources, claims) {
        return Err("opportunity_required_focus");
    }
    if !validate_footage_request(
        request,
        opportunity,
        intent,
        sources,
        claims,
        all_ids,
        opportunity.recommended_concept_id.is_some(),
    ) {
        return Err("footage_request");
    }
    if contains_prohibited_or_viral(&[&opportunity.title, &opportunity.why_now, &opportunity.what_viewers_are_discussing, &opportunity.creative_hook, &opportunity.emotional_edit_direction]) {
        return Err("opportunity_prohibited_copy");
    }
    if opportunity.caveats.iter().any(|value| !valid_text(value, 500) || contains_prohibited_or_viral_text(value)) {
        return Err("opportunity_caveats");
    }
    let Some(gate) = recompute_gate(opportunity, now, intent.freshness_days, sources, claims) else { return Err("opportunity_evidence_gate"); };
    let expected_gate = if gate.passed { "PASSED" } else { "LOW_CONFIDENCE" };
    let expected_actionability = footage_actionability(request);
    let expected_total = (gate.freshness + gate.agreement + gate.specificity + expected_actionability) / 4.0;
    let signal_summary = gate.signal_texts.join("; ");
    let primary_summary = gate.primary_texts.join("; ");
    let metadata_summary = gate.metadata_texts.join("; ");
    let has_scene_lead = !gate.scene_texts.is_empty();
    let expected_caveats = if gate.passed {
        vec!["Creative scene selection is provisional until the supplied local footage is inspected."]
    } else if gate.metadata_low {
        if has_scene_lead {
            vec![
                "Creative scene selection is provisional until the supplied local footage is inspected.",
                "Low confidence: no official why-now proof was verified; this uses exact current TVmaze episode metadata plus two independent title-bound discussion sources. The displayed scene is a LIKELY / INFERRED source-bound inspection lead, not a verified outcome or footage location.",
            ]
        } else {
            vec![
                "Creative scene selection is provisional until the supplied local footage is inspected.",
                "Low confidence: no official why-now proof was verified; this uses exact current TVmaze episode metadata plus two independent title-bound discussion sources. No discussion claim is treated as proof of a scene occurring in that episode.",
            ]
        }
    } else {
        vec![
            "Creative scene selection is provisional until the supplied local footage is inspected.",
            "Low confidence: this has one current independent qualitative signal; the normal evidence gate requires two.",
        ]
    };
    if opportunity.evidence_gate != expected_gate {
        return Err("opportunity_gate_label");
    }
    if !approx(opportunity.score.release_freshness, gate.freshness)
        || !approx(opportunity.score.cross_source_agreement, gate.agreement)
        || !approx(opportunity.score.scene_specificity, gate.specificity)
        || !approx(opportunity.score.footage_actionability, expected_actionability)
        || opportunity.score.independent_source_count != gate.independent_group_count as i64
        || !approx(opportunity.score.total, expected_total)
        || opportunity.confidence > expected_total + 1e-9
    {
        return Err("opportunity_score");
    }
    if opportunity.title != truncate_chars(&format!("{}: {}", opportunity.media_identity.show_or_title, opportunity.focus.relationship_or_topic), 500) {
        return Err("opportunity_title");
    }
    let expected_why_now = if gate.metadata_low {
            truncate_chars(&format!("Current episode metadata (not an official why-now proof): {metadata_summary}"), 2_000)
        } else {
            truncate_chars(&format!("Verified why-now evidence: {primary_summary}"), 2_000)
        };
    if opportunity.why_now != expected_why_now {
        return Err("opportunity_why_now");
    }
    if opportunity.what_viewers_are_discussing != truncate_chars(&format!("Current qualitative signals: {signal_summary}"), 2_000) {
        return Err("opportunity_discussion");
    }
    let scene_summary = gate.scene_texts.join("; ");
    let expected_hook = if has_scene_lead {
        truncate_chars(&format!(
            "Start with this LIKELY / INFERRED exact-episode scene lead: {scene_summary}. It is tied to the current discussion signals: {signal_summary}. The source does not verify the final outcome, timestamp, or footage location."
        ), 2_000)
    } else {
        truncate_chars(&format!(
            "Investigate {} through the specific current signals: {signal_summary}. Treat these as evidence-led inspection targets, not final scene selections.",
            opportunity.focus.relationship_or_topic
        ), 2_000)
    };
    if opportunity.creative_hook != expected_hook {
        return Err("opportunity_hook");
    }
    let expected_direction = if gate.metadata_low && has_scene_lead {
            truncate_chars(&format!(
                "Use the current episode metadata only to bind the identity and timing: {metadata_summary} Inspect supplied local footage around the provisional scene selector—{scene_summary}—for an intro, montage escalation, and payoff. Confirm the exact action and emotional beat locally before editing."
            ), 2_000)
        } else if gate.metadata_low {
            truncate_chars(&format!(
                "Use the current episode metadata only as a timing lead, not proof of a specific scene: {metadata_summary} Then inspect a supplied scene pack or other lawfully obtained local footage for a montage and payoff shaped by: {signal_summary}. The later creative video analysis must confirm every exact visual moment."
            ), 2_000)
        } else {
            truncate_chars(&format!(
                "Anchor the contextual setup in the verified current event: {primary_summary} Then inspect the supplied footage for a montage and payoff shaped by: {signal_summary}. The later creative video analysis must confirm the exact visual moments."
            ), 2_000)
        };
    if opportunity.emotional_edit_direction != expected_direction {
        return Err("opportunity_direction");
    }
    if !opportunity.caveats.iter().map(String::as_str).eq(expected_caveats) {
        return Err("opportunity_expected_caveats");
    }
    if !focus_is_supported(opportunity, now, sources, claims) {
        return Err("opportunity_focus_support");
    }
    Ok(())
}

fn valid_quality_score(score: &OpportunityQualityScore) -> bool {
    let weights = &score.weights;
    let positive_weights = [
        weights.intent_fit,
        weights.audience_fit,
        weights.freshness,
        weights.fandom_velocity,
        weights.short_form_edit_potential,
        weights.relationship_or_character_salience,
        weights.footage_actionability,
        weights.evidence_quality,
        weights.source_diversity,
    ];
    let values = [
        score.intent_fit,
        score.audience_fit,
        score.freshness,
        score.fandom_velocity,
        score.short_form_edit_potential,
        score.relationship_or_character_salience,
        score.footage_actionability,
        score.evidence_quality,
        score.source_diversity,
        score.uncertainty_penalty,
        score.total,
        weights.uncertainty_penalty,
    ];
    if score.schema_version != "1.0.0"
        || !valid_text(&score.profile_id, 100)
        || !values.into_iter().all(valid_confidence)
        || !positive_weights.into_iter().all(valid_confidence)
        || !approx(positive_weights.iter().sum::<f64>(), 1.0)
    {
        return false;
    }
    let weighted = score.intent_fit * weights.intent_fit
        + score.audience_fit * weights.audience_fit
        + score.freshness * weights.freshness
        + score.fandom_velocity * weights.fandom_velocity
        + score.short_form_edit_potential * weights.short_form_edit_potential
        + score.relationship_or_character_salience * weights.relationship_or_character_salience
        + score.footage_actionability * weights.footage_actionability
        + score.evidence_quality * weights.evidence_quality
        + score.source_diversity * weights.source_diversity;
    approx(
        score.total,
        (weighted - score.uncertainty_penalty * weights.uncertainty_penalty).clamp(0.0, 1.0),
    )
}

fn valid_short_form_potential(
    value: &ShortFormEditPotential,
    claims: &HashMap<Uuid, &EvidenceClaim>,
) -> bool {
    value.schema_version == "1.0.0"
        && value.metric_name == "SHORT_FORM_EDIT_POTENTIAL"
        && matches!(value.band.as_str(), "LOW" | "MODERATE" | "HIGH")
        && !value.direct_tiktok_data_used
        && value.disclaimer == "TikTok potential is inferred from cross-platform fandom and editability signals. Direct TikTok trend data was not used."
        && valid_text(&value.explanation, 2_000)
        && (1..=12).contains(&value.signals.len())
        && value.signals.iter().all(|item| valid_text(item, 500))
        && (1..=30).contains(&value.supporting_claim_ids.len())
        && unique_uuids(&value.supporting_claim_ids)
        && value.supporting_claim_ids.iter().all(|id| claims.contains_key(id))
}

fn valid_dossier_verification(value: &str) -> bool {
    matches!(value, "VERIFIED" | "STRONGLY_SUPPORTED" | "LIKELY_INFERRED" | "UNKNOWN")
}

fn generic_editorial_placeholder(value: &str) -> bool {
    let normalized = normalized_words(value);
    [
        "current character discussion",
        "any relevant material",
        "exact scene unknown",
        "exact scene is unknown",
        "clips from the show",
        "clips from this show",
        "get clips from this show",
        "intro montage payoff",
    ]
    .iter()
    .any(|needle| normalized.contains(needle))
}

fn valid_dossier_fact(
    fact: &DossierEvidenceFact,
    evidence_ids: &HashSet<Uuid>,
    claims: &HashMap<Uuid, &EvidenceClaim>,
) -> bool {
    valid_text(&fact.text, 2_000)
        && !generic_editorial_placeholder(&fact.text)
        && valid_dossier_verification(&fact.verification_status)
        && !fact.supporting_claim_ids.is_empty()
        && fact.supporting_claim_ids.len() <= 30
        && unique_uuids(&fact.supporting_claim_ids)
        && fact
            .supporting_claim_ids
            .iter()
            .all(|id| evidence_ids.contains(id) && claims.contains_key(id))
        && match fact.verification_status.as_str() {
            "VERIFIED" => fact.supporting_claim_ids.iter().any(|id| claims[id].verification == "PRIMARY_VERIFIED"),
            "STRONGLY_SUPPORTED" => fact.supporting_claim_ids.iter().any(|id| {
                matches!(claims[id].verification.as_str(), "PRIMARY_VERIFIED" | "SECONDARY_CORROBORATED")
            }),
            "LIKELY_INFERRED" => fact.supporting_claim_ids.iter().any(|id| {
                !matches!(claims[id].verification.as_str(), "STALE" | "RETRACTED")
            }),
            "UNKNOWN" => true,
            _ => false,
        }
}

fn validate_fandom_story_dossiers(
    result: &CanonicalResearchResult,
    sources: &HashMap<Uuid, &EvidenceSource>,
    claims: &HashMap<Uuid, &EvidenceClaim>,
    all_ids: &mut HashSet<Uuid>,
) -> Result<(), &'static str> {
    if result.fandom_story_dossiers.is_empty() {
        return if result.opportunities.iter().all(|item| item.dossier_id.is_none())
            && result.editorial_concepts.iter().all(|item| item.dossier_id.is_none())
        {
            Ok(())
        } else {
            Err("dossier_selection")
        };
    }
    if result.fandom_story_dossiers.len() != result.opportunities.len() {
        return Err("dossier_count");
    }
    let opportunity_by_id = result
        .opportunities
        .iter()
        .map(|item| (item.opportunity_id, item))
        .collect::<HashMap<_, _>>();
    let mut dossier_by_opportunity = HashMap::new();
    for dossier in &result.fandom_story_dossiers {
        let Some(opportunity) = opportunity_by_id.get(&dossier.opportunity_id).copied() else {
            return Err("dossier_opportunity_join");
        };
        if !insert_uuid_v4(all_ids, dossier.dossier_id)
            || dossier.schema_version != "1.0.0"
            || !source_key_is_valid(&dossier.dossier_key)
            || dossier_by_opportunity.insert(dossier.opportunity_id, dossier).is_some()
            || opportunity.dossier_id != Some(dossier.dossier_id)
            || !same_text(&dossier.show_or_title, &opportunity.media_identity.show_or_title)
            || dossier.named_characters.is_empty()
            || dossier.named_characters.len() > 30
            || dossier.why_fans_currently_care.is_empty()
            || dossier.why_fans_currently_care.len() > 20
            || dossier.audience_and_fandom_evidence.is_empty()
            || dossier.audience_and_fandom_evidence.len() > 20
            || dossier.relationship_or_character_history.len() > 20
            || dossier.franchise_connections.len() > 20
            || dossier.uncertainties.len() > 30
            || dossier.uncertainties.iter().any(|value| !valid_text(value, 500))
            || dossier.evidence.is_empty()
            || dossier.evidence.len() > 60
        {
            return Err("dossier_header");
        }
        let mut evidence_ids = HashSet::new();
        for reference in &dossier.evidence {
            let Some(claim) = claims.get(&reference.claim_id).copied() else {
                return Err("dossier_evidence");
            };
            let Some(source) = sources.get(&claim.source_id).copied() else {
                return Err("dossier_evidence");
            };
            if !evidence_ids.insert(reference.claim_id)
                || !matches!(reference.role.as_str(), "PRIMARY_WHY_NOW" | "QUALITATIVE_SIGNAL" | "QUOTE_PROOF" | "CONTEXT")
                || reference.supports_why_now != claim.supports_why_now
                || reference.independence_group != source.independence_group
            {
                return Err("dossier_evidence");
            }
        }
        if !opportunity.evidence.iter().all(|reference| evidence_ids.contains(&reference.claim_id))
            || !valid_dossier_fact(&dossier.current_event_or_hook, &evidence_ids, claims)
            || dossier.current_event_or_hook.verification_status == "UNKNOWN"
            || dossier.central_relationship.as_ref().is_some_and(|fact| !valid_dossier_fact(fact, &evidence_ids, claims))
            || dossier.relationship_or_character_history.iter().any(|fact| !valid_dossier_fact(fact, &evidence_ids, claims))
            || dossier.why_fans_currently_care.iter().any(|fact| !valid_dossier_fact(fact, &evidence_ids, claims))
            || dossier.audience_and_fandom_evidence.iter().any(|fact| !valid_dossier_fact(fact, &evidence_ids, claims))
        {
            return Err("dossier_fact");
        }
        let character_names = dossier.named_characters.iter().map(|item| item.character_name.as_str()).collect::<Vec<_>>();
        if !unique_borrowed(&character_names)
            || dossier.named_characters.iter().any(|character| {
                !valid_text(&character.character_name, 500)
                    || !valid_text(&character.show_or_title, 500)
                    || character.performer_name.as_deref().is_some_and(|value| !valid_optional_text(value, 200))
                    || !valid_dossier_verification(&character.verification_status)
                    || character.verification_status == "UNKNOWN"
                    || character.supporting_claim_ids.is_empty()
                    || character.supporting_claim_ids.len() > 20
                    || !unique_uuids(&character.supporting_claim_ids)
                    || character.supporting_claim_ids.iter().any(|id| !evidence_ids.contains(id) || !claims.contains_key(id))
            })
        {
            return Err("dossier_characters");
        }
        let current = &dossier.current_source;
        let locator_pair = current.season_number.is_some() == current.episode_number.is_some();
        if !matches!(current.source_kind.as_str(), "EPISODE" | "SEASON" | "TRAILER" | "OFFICIAL_CLIP" | "ANNOUNCEMENT" | "INTERVIEW" | "ARTICLE" | "OTHER")
            || !valid_text(&current.show_or_title, 500)
            || !valid_text(&current.source_title, 500)
            || !valid_dossier_verification(&current.verification_status)
            || current.verification_status == "UNKNOWN"
            || !locator_pair
            || (current.source_kind == "EPISODE") != current.season_number.is_some()
            || (current.source_kind != "EPISODE" && current.episode_title.is_some())
            || current.season_number.is_some_and(|value| !(0..=MAX_SEASON_NUMBER).contains(&value))
            || current.episode_number.is_some_and(|value| !(1..=9_999).contains(&value))
            || current.supporting_claim_ids.is_empty()
            || current.supporting_claim_ids.len() > 30
            || !unique_uuids(&current.supporting_claim_ids)
            || current.supporting_claim_ids.iter().any(|id| !evidence_ids.contains(id) || !claims.contains_key(id))
        {
            return Err("dossier_current_source");
        }
        if let Some(quote) = &dossier.exact_or_likely_quote {
            if !valid_text(&quote.source_title, 500)
                || !valid_dossier_verification(&quote.verification_status)
                || quote.supporting_claim_ids.is_empty()
                || quote.supporting_claim_ids.len() > 20
                || !unique_uuids(&quote.supporting_claim_ids)
                || !quote.supporting_claim_ids.contains(&quote.quote.claim_id)
                || quote.supporting_claim_ids.iter().any(|id| !evidence_ids.contains(id) || !claims.contains_key(id))
                || !validate_footage_quote(&quote.quote, None, sources, claims)
            {
                return Err("dossier_quote");
            }
        }
        for connection in &dossier.franchise_connections {
            if !matches!(connection.connection_type.as_str(), "SAME_CHARACTER" | "SAME_CANONICAL_UNIVERSE" | "EXPLICIT_CALLBACK" | "THEMATIC_PARALLEL" | "ACTOR_CONNECTION_ONLY" | "FAN_INTERPRETATION")
                || !valid_text(&connection.current_title, 500)
                || !valid_text(&connection.connected_title, 500)
                || !valid_text(&connection.description, 2_000)
                || connection.characters.len() > 20
                || connection.characters.iter().any(|value| !valid_text(value, 500))
                || !unique_casefolded(&connection.characters)
                || !valid_dossier_verification(&connection.verification_status)
                || (connection.connection_type == "FAN_INTERPRETATION"
                    && matches!(connection.verification_status.as_str(), "VERIFIED" | "STRONGLY_SUPPORTED"))
                || connection.supporting_claim_ids.is_empty()
                || connection.supporting_claim_ids.len() > 30
                || !unique_uuids(&connection.supporting_claim_ids)
                || connection.supporting_claim_ids.iter().any(|id| !evidence_ids.contains(id) || !claims.contains_key(id))
            {
                return Err("dossier_franchise_connection");
            }
        }
    }
    Ok(())
}

fn validate_editorial_concepts(
    result: &CanonicalResearchResult,
    request_by_opportunity: &HashMap<Uuid, &FootageRequest>,
    sources: &HashMap<Uuid, &EvidenceSource>,
    claims: &HashMap<Uuid, &EvidenceClaim>,
    all_ids: &mut HashSet<Uuid>,
) -> Result<(), &'static str> {
    if result.editorial_concepts.is_empty() {
        return if result.opportunities.iter().all(|item| item.recommended_concept_id.is_none()) {
            Ok(())
        } else {
            Err("concept_selection")
        };
    }
    let opportunity_by_id = result.opportunities.iter().map(|item| (item.opportunity_id, item)).collect::<HashMap<_, _>>();
    let dossier_by_opportunity = result.fandom_story_dossiers.iter().map(|item| (item.opportunity_id, item)).collect::<HashMap<_, _>>();
    let dossier_path = !result.fandom_story_dossiers.is_empty();
    let mut keys_by_opportunity: HashMap<Uuid, HashSet<&str>> = HashMap::new();
    for concept in &result.editorial_concepts {
        let Some(opportunity) = opportunity_by_id.get(&concept.opportunity_id).copied() else {
            return Err("concept_opportunity_join");
        };
        let dossier = dossier_by_opportunity.get(&concept.opportunity_id).copied();
        if !insert_uuid_v4(all_ids, concept.concept_id)
            || concept.schema_version != "1.0.0"
            || (dossier_path
                && dossier.is_none_or(|item| concept.dossier_id != Some(item.dossier_id)))
            || !source_key_is_valid(&concept.concept_key)
            || !keys_by_opportunity.entry(concept.opportunity_id).or_default().insert(&concept.concept_key)
            || !valid_text(&concept.title, 500)
            || !valid_text(&concept.central_subject, 2_000)
            || concept.central_relationship.as_deref().is_some_and(|value| !valid_optional_text(value, 500))
            || !valid_text(&concept.core_emotion, 500)
            || !valid_text(&concept.viewer_hook, 2_000)
            || !valid_text(&concept.why_fans_may_care, 2_000)
            || !valid_text(&concept.current_event, 2_000)
            || !valid_text(&concept.legacy_or_contextual_connection, 2_000)
            || !matches!(concept.legacy_connection_type.as_str(), "NONE" | "SAME_CHARACTER" | "SAME_CANONICAL_UNIVERSE" | "EXPLICIT_CALLBACK" | "THEMATIC_PARALLEL" | "ACTOR_CONNECTION_ONLY" | "FAN_INTERPRETATION")
            || !(1..=3).contains(&concept.intro_leads.len())
            || !valid_text(&concept.song_handoff_idea, 2_000)
            || !(3..=6).contains(&concept.montage_arc.len())
            || concept.montage_arc.iter().any(|value| !valid_text(value, 2_000))
            || !unique_casefolded(&concept.montage_arc)
            || !valid_text(&concept.ending_or_payoff, 2_000)
            || concept.evidence.is_empty()
            || concept.evidence.len() > 30
            || !matches!(concept.verification_status.as_str(), "VERIFIED" | "STRONGLY_SUPPORTED" | "LIKELY_INFERRED" | "UNKNOWN")
            || concept.known_uncertainties.len() > 20
            || concept.known_uncertainties.iter().any(|value| !valid_text(value, 500))
            || concept.provisional_notice != CONCEPT_PROVISIONAL_NOTICE
            || (concept.legacy_connection_type == "FAN_INTERPRETATION"
                && matches!(concept.verification_status.as_str(), "VERIFIED" | "STRONGLY_SUPPORTED"))
            || !valid_editorial_concept_score(&concept.score)
            || concept.footage_request.opportunity_id != concept.opportunity_id
            || (dossier_path && concept.footage_request.concept_id != Some(concept.concept_id))
            || serde_json::to_value(&concept.intro_leads).ok() != serde_json::to_value(&concept.footage_request.intro_leads).ok()
            || generic_concept_copy(concept)
            || contains_prohibited_or_viral(&[
                &concept.title,
                &concept.central_subject,
                &concept.core_emotion,
                &concept.viewer_hook,
                &concept.why_fans_may_care,
                &concept.current_event,
                &concept.legacy_or_contextual_connection,
                &concept.song_handoff_idea,
                &concept.ending_or_payoff,
            ])
            || concept.montage_arc.iter().any(|value| contains_prohibited_or_viral_text(value))
            || concept.known_uncertainties.iter().any(|value| contains_prohibited_or_viral_text(value))
        {
            return Err("concept_header");
        }
        let mut seen_claims = HashSet::new();
        for reference in &concept.evidence {
            let Some(claim) = claims.get(&reference.claim_id).copied() else {
                return Err("concept_evidence");
            };
            let Some(source) = sources.get(&claim.source_id).copied() else {
                return Err("concept_evidence");
            };
            if !insert_uuid_v4(&mut seen_claims, reference.claim_id)
                || !matches!(reference.role.as_str(), "PRIMARY_WHY_NOW" | "QUALITATIVE_SIGNAL" | "QUOTE_PROOF" | "CONTEXT")
                || reference.supports_why_now != claim.supports_why_now
                || reference.independence_group != source.independence_group
            {
                return Err("concept_evidence");
            }
        }
        if dossier_path && dossier.is_some_and(|item| {
            let dossier_ids = item.evidence.iter().map(|reference| reference.claim_id).collect::<HashSet<_>>();
            concept.evidence.iter().any(|reference| !dossier_ids.contains(&reference.claim_id))
        }) {
            return Err("concept_dossier_evidence");
        }
        if matches!(
            concept.legacy_connection_type.as_str(),
            "SAME_CHARACTER" | "SAME_CANONICAL_UNIVERSE" | "EXPLICIT_CALLBACK"
        ) && !canonical_connection_is_supported(concept, sources, claims)
        {
            return Err("concept_connection");
        }
        if concept.verification_status == "VERIFIED"
            && concept.intro_leads.iter().any(|lead| lead.verification_level != "VERIFIED")
        {
            return Err("concept_verification");
        }
        let selected = opportunity.recommended_concept_id == Some(concept.concept_id);
        if selected {
            let Some(top_level) = request_by_opportunity.get(&concept.opportunity_id).copied() else {
                return Err("concept_footage_join");
            };
            if serde_json::to_value(top_level).ok() != serde_json::to_value(&concept.footage_request).ok() {
                return Err("concept_selected_footage");
            }
        } else {
            if !insert_uuid_v4(all_ids, concept.footage_request.footage_request_id)
                || !validate_footage_request(
                    &concept.footage_request,
                    opportunity,
                    &result.intent,
                    sources,
                    claims,
                    all_ids,
                    true,
                )
            {
                return Err("concept_footage_request");
            }
        }
    }
    for opportunity in &result.opportunities {
        let concepts = result.editorial_concepts.iter().filter(|item| item.opportunity_id == opportunity.opportunity_id).collect::<Vec<_>>();
        if !(1..=4).contains(&concepts.len())
            || opportunity.recommended_concept_id.is_none()
            || concepts.iter().filter(|item| Some(item.concept_id) == opportunity.recommended_concept_id).count() != 1
            || (dossier_path && opportunity.dossier_id.is_none())
        {
            return Err("concept_selection");
        }
    }
    Ok(())
}

fn valid_editorial_concept_score(score: &EditorialConceptScore) -> bool {
    let positive = [
        score.concept_specificity,
        score.intro_strength,
        score.emotional_arc_strength,
        score.narrative_bridge_strength,
        score.fan_recognition,
        score.current_event_relevance,
        score.legacy_context_value,
        score.payoff_strength,
        score.footage_feasibility,
        score.source_actionability,
        score.originality,
        score.evidence_quality,
    ];
    positive.into_iter().chain([score.uncertainty_penalty, score.total]).all(valid_confidence)
        && approx(
            score.total,
            (positive.iter().sum::<f64>() / positive.len() as f64 - 0.25 * score.uncertainty_penalty).clamp(0.0, 1.0),
        )
}

fn generic_concept_copy(concept: &EditorialConcept) -> bool {
    let normalized = normalized_words(&format!(
        "{} {} {}",
        concept.central_subject, concept.viewer_hook, concept.montage_arc.join(" ")
    ));
    normalized.starts_with("this show is current get clips from this show")
        || normalized.starts_with("this show is trending get clips from this show")
        || normalized.starts_with("get clips from this show")
        || normalized.starts_with("use clips from this show")
        || normalized.starts_with("find clips from this show")
}

fn canonical_connection_is_supported(
    concept: &EditorialConcept,
    sources: &HashMap<Uuid, &EvidenceSource>,
    claims: &HashMap<Uuid, &EvidenceClaim>,
) -> bool {
    let mut parts = Vec::new();
    for reference in &concept.evidence {
        let Some(claim) = claims.get(&reference.claim_id) else { return false; };
        let Some(source) = sources.get(&claim.source_id) else { return false; };
        parts.push(claim.text.as_str());
        parts.push(source.title.as_str());
    }
    let corpus = format!(" {} ", normalized_words(&parts.join(" ")));
    [
        " spinoff ",
        " spin off ",
        " sequel ",
        " prequel ",
        " same universe ",
        " return ",
        " returns ",
        " returning ",
        " reunion ",
        " callback ",
        " continuation ",
        " parent series ",
        " reprise ",
        " reprising ",
    ]
    .iter()
    .any(|term| corpus.contains(term))
}

struct GateComputation {
    passed: bool,
    metadata_low: bool,
    freshness: f64,
    agreement: f64,
    specificity: f64,
    independent_group_count: usize,
    primary_texts: Vec<String>,
    metadata_texts: Vec<String>,
    signal_texts: Vec<String>,
    scene_texts: Vec<String>,
}

fn recompute_gate(
    opportunity: &Opportunity,
    now: Timestamp,
    freshness_days: i64,
    sources: &HashMap<Uuid, &EvidenceSource>,
    claims: &HashMap<Uuid, &EvidenceClaim>,
) -> Option<GateComputation> {
    let cutoff = now.checked_sub_days(freshness_days)?;
    let future_limit = now.checked_add_seconds(300)?;
    let mut seen_claims = HashSet::new();
    let mut primary = Vec::new();
    let mut metadata = Vec::new();
    let mut signals = Vec::new();
    let mut scene_leads = Vec::new();
    for reference in &opportunity.evidence {
        if !insert_uuid_v4(&mut seen_claims, reference.claim_id)
            || !matches!(reference.role.as_str(), "PRIMARY_WHY_NOW" | "QUALITATIVE_SIGNAL" | "QUOTE_PROOF" | "CONTEXT")
        {
            return None;
        }
        let claim = claims.get(&reference.claim_id)?;
        let source = sources.get(&claim.source_id)?;
        if reference.supports_why_now != claim.supports_why_now
            || reference.independence_group != source.independence_group
        {
            return None;
        }
        if reference.role == "CONTEXT"
            && provisional_scene_matches_opportunity(
                opportunity,
                claim,
                source,
                cutoff,
                now,
                future_limit,
            )
        {
            scene_leads.push((*claim, *source));
        }
        if !usable_evidence(claim, source, now) { continue; }
        if reference.role == "PRIMARY_WHY_NOW"
            && claim.verification == "PRIMARY_VERIFIED"
            && matches!(claim.claim_kind.as_str(), "WHY_NOW" | "OFFICIAL_CLIP")
            && claim.supports_why_now
            && claim.why_now_event.as_ref().is_some_and(|event| event.media_identity == opportunity.media_identity)
            && claim.event_or_release_at.as_deref().and_then(parse_timestamp).is_some_and(|value| value >= cutoff && value <= future_limit)
        {
            primary.push((*claim, *source));
        } else if reference.role == "CONTEXT"
            && current_tvmaze_episode_matches_opportunity(
                opportunity,
                claim,
                source,
                cutoff,
                future_limit,
            )
        {
            metadata.push((*claim, *source));
        } else if reference.role == "QUALITATIVE_SIGNAL"
            && claim.claim_kind == "VIEWER_DISCUSSION" && claim.supports_why_now
        {
            let discussion_at = source.source_created_at.as_deref().or(source.page_published_at.as_deref()).and_then(parse_timestamp);
            if discussion_at.is_some_and(|value| value >= cutoff && value <= future_limit)
                && discussion_matches_opportunity(opportunity, source)
            {
                signals.push((*claim, *source));
            }
        }
    }
    let primary_groups = primary.iter().map(|(_, source)| source.independence_group.as_str()).collect::<HashSet<_>>();
    let metadata_groups = metadata.iter().map(|(_, source)| source.independence_group.as_str()).collect::<HashSet<_>>();
    let signal_groups = signals.iter().map(|(_, source)| source.independence_group.as_str()).collect::<HashSet<_>>();
    let all_groups = primary_groups.iter().chain(&metadata_groups).chain(&signal_groups).copied().collect::<HashSet<_>>();
    let passed = !primary.is_empty() && signals.len() >= 2 && signal_groups.len() >= 2 && all_groups.len() >= 3;
    let primary_low = !passed && !primary.is_empty() && !signal_groups.is_empty()
        && primary_groups.union(&signal_groups).count() >= 2;
    let metadata_low = !passed && primary.is_empty() && !metadata.is_empty()
        && signals.len() >= 2 && signal_groups.len() >= 2
        && metadata_groups.union(&signal_groups).count() >= 3;
    if !passed && !primary_low && !metadata_low {
        return None;
    }
    let latest = primary.iter().chain(&metadata).filter_map(|(claim, _)| claim.event_or_release_at.as_deref().and_then(parse_timestamp)).max()?;
    let age_seconds = ((now.0 - latest.0).max(0) as f64) / 1_000_000_000.0;
    let freshness = (1.0 - age_seconds / (freshness_days as f64 * 86_400.0)).max(0.0);
    Some(GateComputation {
        passed,
        metadata_low,
        freshness,
        agreement: (signal_groups.len() as f64 / 2.0).min(1.0),
        specificity: if !opportunity.focus.characters.is_empty() {
            1.0
        } else if !scene_leads.is_empty() {
            0.9
        } else {
            0.7
        },
        independent_group_count: all_groups.len(),
        primary_texts: unique_strings(primary.iter().map(|(claim, _)| claim.text.as_str())),
        metadata_texts: unique_strings(metadata.iter().map(|(claim, _)| claim.text.as_str())),
        signal_texts: unique_strings(signals.iter().map(|(claim, _)| claim.text.as_str())),
        scene_texts: unique_strings(scene_leads.iter().filter_map(|(claim, _)| {
            claim.scene_fact.as_ref().map(|fact| fact.description.as_str())
        })),
    })
}

fn provisional_scene_matches_opportunity(
    opportunity: &Opportunity,
    claim: &EvidenceClaim,
    source: &EvidenceSource,
    cutoff: Timestamp,
    now: Timestamp,
    future_limit: Timestamp,
) -> bool {
    let Some(scene) = claim.scene_fact.as_ref() else { return false; };
    let source_at = source
        .source_created_at
        .as_deref()
        .or(source.page_published_at.as_deref())
        .and_then(parse_timestamp);
    claim.claim_kind == "SCENE_CONTEXT"
        && !matches!(claim.verification.as_str(), "STALE" | "RETRACTED")
        && source.expires_at.as_deref().and_then(parse_timestamp).is_some_and(|value| value > now)
        && source.purge_due_at.as_deref().and_then(parse_timestamp).is_some_and(|value| value > now)
        && source.deletion_required_at.as_deref().and_then(parse_timestamp).is_none_or(|value| value > now)
        && same_text(&scene.show_or_title, &opportunity.media_identity.show_or_title)
        && (opportunity.media_identity.media_kind != "TV_EPISODE"
            || scene.episode_locator.as_ref().is_some_and(|locator| {
                Some(locator.season_number) == opportunity.media_identity.season_number
                    && Some(locator.episode_number) == opportunity.media_identity.episode_number
            }))
        && source_at.is_some_and(|value| value >= cutoff && value <= future_limit)
}

fn current_tvmaze_episode_matches_opportunity(
    opportunity: &Opportunity,
    claim: &EvidenceClaim,
    source: &EvidenceSource,
    cutoff: Timestamp,
    future_limit: Timestamp,
) -> bool {
    let Some(locator) = claim.episode_locator.as_ref() else { return false; };
    source.provider == "tvmaze"
        && source.policy_class == "tvmaze-metadata-v1"
        && claim.claim_kind == "EPISODE_IDENTITY"
        && claim.verification == "SECONDARY_CORROBORATED"
        && !claim.supports_why_now
        && opportunity.media_identity.media_kind == "TV_EPISODE"
        && same_text(&locator.show_or_title, &opportunity.media_identity.show_or_title)
        && Some(locator.season_number) == opportunity.media_identity.season_number
        && Some(locator.episode_number) == opportunity.media_identity.episode_number
        && opportunity.media_identity.episode_title.as_ref().is_none_or(|title| {
            locator.episode_title.as_ref().is_some_and(|value| same_text(value, title))
        })
        && claim.event_or_release_at.as_deref().and_then(parse_timestamp)
            .is_some_and(|value| value >= cutoff && value <= future_limit)
}

fn validate_footage_request(
    request: &FootageRequest,
    opportunity: &Opportunity,
    intent: &CanonicalResearchIntent,
    sources: &HashMap<Uuid, &EvidenceSource>,
    claims: &HashMap<Uuid, &EvidenceClaim>,
    all_ids: &mut HashSet<Uuid>,
    allow_cross_title_sources: bool,
) -> bool {
    if request.required_sources.is_empty() || request.required_sources.len() > 30
        || request.optional_sources.len() > 30 || request.alternative_sources.len() > 30
        || request.intro_leads.len() > 20 || request.warnings.len() > 20
        || request.search_queries.is_empty() || request.search_queries.len() > 30
        || !unique_casefolded(&request.search_queries)
        || contains_prohibited_or_viral(&[&request.summary, &request.smallest_useful_set_reason])
        || request.warnings.iter().any(|value| !valid_text(value, 500) || contains_prohibited_or_viral_text(value))
    {
        return false;
    }
    let required_keys = request.required_sources.iter().map(|source| source.source_key.as_str()).collect::<HashSet<_>>();
    if required_keys.len() != request.required_sources.len()
        || required_keys != request.minimum_useful_source_keys.iter().map(String::as_str).collect()
        || request.minimum_useful_source_keys.len() != required_keys.len()
        || request.natural_request.alternative.is_some() != !request.alternative_sources.is_empty()
        || request.natural_request.optional_improvement.is_some() != !request.optional_sources.is_empty()
    {
        return false;
    }
    let mut all_keys = HashSet::new();
    let mut source_by_key = HashMap::new();
    for (group, bucket) in [("REQUIRED", &request.required_sources), ("OPTIONAL", &request.optional_sources), ("ALTERNATIVE", &request.alternative_sources)] {
        for (index, source) in bucket.iter().enumerate() {
            if source.priority != index as i64 + 1
                || !insert_uuid_v4(all_ids, source.requested_source_id)
                || !all_keys.insert(source.source_key.as_str())
                || source_by_key.insert(source.source_key.as_str(), source).is_some()
                || !validate_requested_source(source, sources, claims)
                || (group == "ALTERNATIVE") != !source.replaces_required_source_keys.is_empty()
                || (group == "ALTERNATIVE" && source.replaces_required_source_keys.iter().map(String::as_str).collect::<HashSet<_>>() != required_keys)
                || (group != "ALTERNATIVE" && !source.replaces_required_source_keys.is_empty())
            {
                return false;
            }
        }
    }
    if request.intro_leads.iter().any(|lead| {
        !insert_uuid_v4(all_ids, lead.intro_lead_id)
            || !validate_intro_lead(lead, &source_by_key, sources, claims)
    }) {
        return false;
    }
    let all_sources = request.required_sources.iter().chain(&request.optional_sources).chain(&request.alternative_sources).collect::<Vec<_>>();
    let cross_title_sources = all_sources
        .iter()
        .filter(|source| !same_text(&source.show_or_title, &opportunity.media_identity.show_or_title))
        .collect::<Vec<_>>();
    if !cross_title_sources.is_empty()
        && (!allow_cross_title_sources
            || cross_title_sources.iter().any(|source| {
                source.verification_level == "UNKNOWN"
                    || source.supporting_claim_ids.is_empty()
            }))
    {
        return false;
    }
    let expected_natural = render_natural_request(&request.required_sources, &request.optional_sources, &request.alternative_sources);
    let expected_searches = unique_strings(all_sources.iter().flat_map(|source| source.search_queries.iter().map(String::as_str))).into_iter().take(30).collect::<Vec<_>>();
    let has_unknown = all_sources.iter().any(|source| source.verification_level == "UNKNOWN");
    let expected_warnings = if has_unknown {
        vec!["Unknown source suggestions are broad inspection targets, not verified scene claims.".to_owned()]
    } else { Vec::new() };
    request.summary == "Smallest evidence-bound footage request for this research opportunity."
        && request.smallest_useful_set_reason == "The required bucket is the smallest set supported by the current evidence; optional and alternative items are not prerequisites."
        && request.natural_request.best == expected_natural.best
        && request.natural_request.minimum == expected_natural.minimum
        && request.natural_request.alternative == expected_natural.alternative
        && request.natural_request.optional_improvement == expected_natural.optional_improvement
        && request.search_queries == expected_searches
        && request.warnings == expected_warnings
        && validate_opportunity_request_pair(
            opportunity,
            request,
            intent,
            allow_cross_title_sources,
        )
}

fn validate_requested_source(
    source: &RequestedSource,
    sources: &HashMap<Uuid, &EvidenceSource>,
    claims: &HashMap<Uuid, &EvidenceClaim>,
) -> bool {
    let locator_pair = source.season_number.is_some() == source.episode_number.is_some();
    let episode_shape = (source.asset_kind == "EPISODE") == source.season_number.is_some();
    if !(locator_pair && episode_shape && (1..=30).contains(&source.priority)
        && (1..=5).contains(&source.acquisition_effort)
        && matches!(source.asset_kind.as_str(), "EPISODE" | "OFFICIAL_TRAILER" | "OFFICIAL_CLIP" | "SCENE_PACK" | "INDIVIDUAL_SCENES")
        && matches!(source.verification_level.as_str(), "VERIFIED" | "STRONGLY_SUPPORTED" | "LIKELY_INFERRED" | "UNKNOWN")
        && source_key_is_valid(&source.source_key)
        && valid_text(&source.show_or_title, 500)
        && source.episode_title.as_ref().is_none_or(|value| valid_optional_text(value, 500))
        && source.season_number.is_none_or(|value| (0..=MAX_SEASON_NUMBER).contains(&value))
        && source.episode_number.is_none_or(|value| (1..=9_999).contains(&value))
        && (source.asset_kind == "EPISODE" || source.episode_title.is_none())
        && !(source.verification_level == "UNKNOWN" && (source.season_number.is_some() || source.episode_title.is_some()))
        && !(source.asset_kind == "SCENE_PACK" && matches!(source.verification_level.as_str(), "VERIFIED" | "STRONGLY_SUPPORTED"))
        && source.characters.len() <= 20 && source.characters.iter().all(|value| valid_text(value, 500))
        && unique_casefolded(&source.characters)
        && source.relationship_or_topic.as_ref().is_none_or(|value| valid_optional_text(value, 500))
        && valid_text(&source.scene_or_moment, 2_000)
        && valid_text(&source.why_it_matters_emotionally, 2_000)
        && !source.purposes.is_empty() && source.purposes.len() <= 4
        && source.purposes.iter().all(|purpose| matches!(purpose.as_str(), "INTRO" | "MONTAGE" | "PAYOFF" | "OPTIONAL_CALLBACK"))
        && purposes_are_canonical(&source.purposes)
        && !source.search_queries.is_empty() && source.search_queries.len() <= 20
        && source.search_queries.iter().all(|value| valid_text(value, 500))
        && unique_casefolded(&source.search_queries)
        && source.supporting_claim_ids.len() <= 30
        && unique_uuids(&source.supporting_claim_ids)
        && source.supporting_claim_ids.iter().all(|id| valid_uuid_v4(*id) && claims.contains_key(id))
        && (source.verification_level == "UNKNOWN" || !source.supporting_claim_ids.is_empty())
        && source.quote.as_ref().is_none_or(|quote| {
            source.supporting_claim_ids.contains(&quote.claim_id) && validate_footage_quote(quote, Some(source), sources, claims)
        })
        && source.replaces_required_source_keys.len() <= 30
        && source.replaces_required_source_keys.iter().all(|value| source_key_is_valid(value))
        && unique_casefolded(&source.replaces_required_source_keys)
        && !contains_prohibited_or_viral(&[&source.show_or_title, &source.scene_or_moment, &source.why_it_matters_emotionally, &source.source_quality_summary]))
    {
        return false;
    }
    if source.source_quality_summary != quality_summary(&source.verification_level)
        || source.search_queries != safe_search_queries(source)
        || source.why_it_matters_emotionally != source_emotional_rationale(source)
    {
        return false;
    }
    if source.verification_level == "UNKNOWN" {
        let focus = source.relationship_or_topic.clone().unwrap_or_else(|| source.characters.join(" + "));
        let label = if focus.is_empty() { source.show_or_title.as_str() } else { focus.as_str() };
        return source.scene_or_moment == format!("Any relevant {label} material; the exact scene is unknown.");
    }
    let joined = source.supporting_claim_ids.iter().filter_map(|id| claims.get(id).copied()).collect::<Vec<_>>();
    if source.asset_kind == "EPISODE" && !joined.iter().any(|claim| {
        matches!(claim.verification.as_str(), "PRIMARY_VERIFIED" | "SECONDARY_CORROBORATED")
            && episode_fact_matches(source, claim)
    }) {
        return false;
    }
    match source.verification_level.as_str() {
        "VERIFIED" => joined.iter().any(|claim| claim.verification == "PRIMARY_VERIFIED" && asset_identity_matches(source, claim))
            && joined.iter().any(|claim| claim.verification == "PRIMARY_VERIFIED" && scene_fact_matches(source, claim, &source.scene_or_moment)),
        "STRONGLY_SUPPORTED" => joined.iter().any(|claim| matches!(claim.verification.as_str(), "PRIMARY_VERIFIED" | "SECONDARY_CORROBORATED") && asset_identity_matches(source, claim))
            && joined.iter().any(|claim| matches!(claim.verification.as_str(), "PRIMARY_VERIFIED" | "SECONDARY_CORROBORATED") && scene_fact_matches(source, claim, &source.scene_or_moment)),
        "LIKELY_INFERRED" => joined.iter().any(|claim| claim_relevant_to_inference(source, claim))
            && source.supporting_claim_ids.iter().any(|id| {
                let claim = claims[id];
                let evidence_source = sources[&claim.source_id];
                !matches!(claim.verification.as_str(), "STALE" | "RETRACTED")
                    && (source.asset_kind != "EPISODE" || claim_carries_matching_episode_locator(source, claim))
                    && (scene_fact_matches(source, claim, &source.scene_or_moment)
                    || quote_context_matches_source(source, claim)
                    || (claim.claim_kind == "OFFICIAL_CLIP" && asset_identity_matches(source, claim) && same_text(&claim.text, &source.scene_or_moment))
                    || (claim.claim_kind == "VIEWER_DISCUSSION"
                        && matches!(claim.excerpt_type.as_str(), "PARAPHRASE" | "UNVERIFIED_QUOTE_LEAD")
                        && same_text(&claim.text, &source.scene_or_moment)
                        && evidence_source_binds_title(evidence_source, &source.show_or_title)))
            }),
        _ => false,
    }
}

fn validate_footage_quote(
    quote: &FootageQuote,
    requested: Option<&RequestedSource>,
    sources: &HashMap<Uuid, &EvidenceSource>,
    claims: &HashMap<Uuid, &EvidenceClaim>,
) -> bool {
    let Some(claim) = claims.get(&quote.claim_id) else { return false; };
    if !valid_uuid_v4(quote.claim_id) || !valid_text(&quote.text, 500)
        || matches!(claim.verification.as_str(), "STALE" | "RETRACTED")
    {
        return false;
    }
    match quote.status.as_str() {
        "VERIFIED" => {
            let Some(fact) = claim.quote_fact.as_ref() else { return false; };
            quote.speaker.as_ref().is_some_and(|speaker| same_text(speaker, &fact.speaker))
                && claim.claim_kind == "QUOTE" && claim.excerpt_type == "SHORT_QUOTE"
                && claim.verification == "PRIMARY_VERIFIED" && same_text(&fact.exact_text, &quote.text)
                && quote.likely_context.as_ref().is_none_or(|context| fact.context.as_ref().is_some_and(|expected| same_text(context, expected)))
                && requested.is_none_or(|source| {
                    same_text(&fact.media_identity.show_or_title, &source.show_or_title)
                        && (source.asset_kind != "EPISODE" || fact.episode_locator.as_ref().is_some_and(|locator| episode_locator_matches_source(source, locator)))
                })
        },
        "PARAPHRASE" | "UNVERIFIED_LEAD" => {
            let expected = if quote.status == "PARAPHRASE" { "PARAPHRASE" } else { "UNVERIFIED_QUOTE_LEAD" };
            quote.speaker.is_none() && quote.likely_context.is_none()
                && claim.excerpt_type == expected && same_text(&claim.text, &quote.text)
                && requested.is_none_or(|source| {
                    (source.asset_kind != "EPISODE" || claim_carries_matching_episode_locator(source, claim))
                        && (claim_relevant_to_inference(source, claim)
                            || sources.get(&claim.source_id).is_some_and(|evidence_source| normalized_words(&evidence_source.title).contains(&normalized_words(&source.show_or_title)))
                            || normalized_words(&claim.text).contains(&normalized_words(&source.show_or_title)))
                })
        },
        _ => false,
    }
}

fn validate_intro_lead(
    lead: &IntroMaterialLead,
    source_by_key: &HashMap<&str, &RequestedSource>,
    sources: &HashMap<Uuid, &EvidenceSource>,
    claims: &HashMap<Uuid, &EvidenceClaim>,
) -> bool {
    let Some(requested) = source_by_key.get(lead.source_key.as_str()).copied() else { return false; };
    if !valid_text(&lead.moment_description, 2_000)
        || !valid_text(&lead.why_it_might_lead_into_montage, 2_000)
        || !matches!(lead.verification_level.as_str(), "VERIFIED" | "STRONGLY_SUPPORTED" | "LIKELY_INFERRED" | "UNKNOWN")
        || lead.supporting_claim_ids.is_empty() || lead.supporting_claim_ids.len() > 30
        || !unique_uuids(&lead.supporting_claim_ids)
        || lead.supporting_claim_ids.iter().any(|id| !claims.contains_key(id) || !valid_uuid_v4(*id))
        || lead.quote.as_ref().is_some_and(|quote| !lead.supporting_claim_ids.contains(&quote.claim_id) || !validate_footage_quote(quote, Some(requested), sources, claims))
        || lead.why_it_might_lead_into_montage != intro_rationale(lead, requested)
        || contains_prohibited_or_viral_text(&lead.moment_description)
        || contains_prohibited_or_viral_text(&lead.why_it_might_lead_into_montage)
    {
        return false;
    }
    match lead.verification_level.as_str() {
        "VERIFIED" | "STRONGLY_SUPPORTED" => {
            lead.supporting_claim_ids.iter().filter_map(|id| claims.get(id)).any(|claim| {
                let acceptable = lead.verification_level == "VERIFIED" && claim.verification == "PRIMARY_VERIFIED"
                    || lead.verification_level == "STRONGLY_SUPPORTED"
                        && matches!(claim.verification.as_str(), "PRIMARY_VERIFIED" | "SECONDARY_CORROBORATED");
                acceptable && matches!(claim.claim_kind.as_str(), "SCENE_CONTEXT" | "OFFICIAL_CLIP")
                    && scene_fact_matches(requested, claim, &lead.moment_description)
            })
        },
        _ => lead.supporting_claim_ids.iter().any(|id| {
            let claim = claims[id];
            let evidence_source = sources[&claim.source_id];
            !matches!(claim.verification.as_str(), "STALE" | "RETRACTED")
                && (requested.asset_kind != "EPISODE" || claim_carries_matching_episode_locator(requested, claim))
                && (scene_fact_matches(requested, claim, &lead.moment_description)
                || (claim.claim_kind == "OFFICIAL_CLIP"
                    && asset_identity_matches(requested, claim)
                    && same_text(&claim.text, &lead.moment_description))
                || (claim.claim_kind == "VIEWER_DISCUSSION"
                    && matches!(claim.excerpt_type.as_str(), "PARAPHRASE" | "UNVERIFIED_QUOTE_LEAD")
                    && same_text(&claim.text, &lead.moment_description)
                    && evidence_source_binds_title(evidence_source, &requested.show_or_title)))
        }),
    }
}

fn validate_opportunity_request_pair(
    opportunity: &Opportunity,
    request: &FootageRequest,
    intent: &CanonicalResearchIntent,
    allow_cross_title_sources: bool,
) -> bool {
    let all = request.required_sources.iter().chain(&request.optional_sources).chain(&request.alternative_sources).collect::<Vec<_>>();
    if !allow_cross_title_sources
        && all.iter().any(|source| !same_text(&source.show_or_title, &opportunity.media_identity.show_or_title))
    {
        return false;
    }
    let requested_characters = all.iter().flat_map(|source| source.characters.iter()).map(|value| same_key(value)).collect::<HashSet<_>>();
    let focus_characters = opportunity.focus.characters.iter().map(|value| same_key(value)).collect::<HashSet<_>>();
    if !focus_characters.iter().all(|value| requested_characters.contains(value))
        || !requested_characters.is_subset(&focus_characters)
    {
        return false;
    }
    let topic_tokens = meaningful_topic_tokens(&opportunity.focus.relationship_or_topic);
    let footage_topic = normalized_words(&all.iter().map(|source| format!("{} {}", source.relationship_or_topic.as_deref().unwrap_or(""), source.scene_or_moment)).collect::<Vec<_>>().join(" "));
    if !topic_tokens.is_empty() && !topic_tokens.iter().any(|token| footage_topic.split_whitespace().any(|value| value == token)) {
        return false;
    }
    for source in &all {
        let Some(topic) = source.relationship_or_topic.as_ref() else { continue; };
        let item_tokens = normalized_words(topic).split_whitespace().filter(|token| token.len() >= 4).map(str::to_owned).collect::<HashSet<_>>();
        if !item_tokens.is_empty() && !topic_tokens.is_empty() && item_tokens.is_disjoint(&topic_tokens) {
            return false;
        }
    }
    if intent.spoiler_policy == "AVOID" && all.iter().any(|source| !matches!(source.asset_kind.as_str(), "OFFICIAL_TRAILER" | "OFFICIAL_CLIP")) {
        return false;
    }
    let displayed = format!(
        "{} {} {} {} {} {} {}",
        opportunity.title, opportunity.focus.characters.join(" "), opportunity.focus.relationship_or_topic,
        opportunity.why_now, opportunity.what_viewers_are_discussing,
        all.iter().map(|source| format!("{} {} {} {}", source.show_or_title, source.characters.join(" "), source.relationship_or_topic.as_deref().unwrap_or(""), source.scene_or_moment)).collect::<Vec<_>>().join(" "),
        request.search_queries.join(" "),
    );
    !violates_exclusions(&displayed, &intent.exclusions)
}

fn focus_is_supported(
    opportunity: &Opportunity,
    now: Timestamp,
    sources: &HashMap<Uuid, &EvidenceSource>,
    claims: &HashMap<Uuid, &EvidenceClaim>,
) -> bool {
    let mut corpus_parts = Vec::new();
    for reference in &opportunity.evidence {
        let Some(claim) = claims.get(&reference.claim_id) else { return false; };
        let Some(source) = sources.get(&claim.source_id) else { return false; };
        if !usable_evidence(claim, source, now) { continue; }
        corpus_parts.push(claim.text.clone());
        corpus_parts.push(source.title.clone());
        corpus_parts.push(source.author_or_channel.clone().unwrap_or_default());
        for value in [
            claim.episode_locator.as_ref().map(episode_locator_value),
            claim.quote_fact.as_ref().map(quote_fact_value),
            claim.why_now_event.as_ref().map(why_now_event_value),
            claim.scene_fact.as_ref().map(scene_fact_value),
            claim.cast_fact.as_ref().map(cast_fact_value),
        ].into_iter().flatten() {
            corpus_parts.push(value.to_string());
        }
    }
    let corpus = format!(" {} ", normalized_words(&corpus_parts.join(" ")));
    if opportunity.focus.characters.iter().any(|character| {
        let normalized = normalized_words(character);
        normalized.is_empty() || !corpus.contains(&format!(" {normalized} "))
    }) {
        return false;
    }
    let tokens = meaningful_topic_tokens(&opportunity.focus.relationship_or_topic);
    tokens.is_empty() || tokens.iter().any(|token| corpus.contains(&format!(" {token} ")))
}

fn required_focus_is_supported(
    opportunity: &Opportunity,
    intent: &CanonicalResearchIntent,
    now: Timestamp,
    sources: &HashMap<Uuid, &EvidenceSource>,
    claims: &HashMap<Uuid, &EvidenceClaim>,
) -> bool {
    if !intent.focus_terms.iter().any(|value| normalized_words(value) == "female centered") {
        return true;
    }
    let mut relevant = Vec::new();
    for reference in &opportunity.evidence {
        let Some(claim) = claims.get(&reference.claim_id) else { return false; };
        let Some(source) = sources.get(&claim.source_id) else { return false; };
        if !usable_evidence(claim, source, now) { continue; }
        let structured_title_matches = [
            claim.episode_locator.as_ref().map(|value| value.show_or_title.as_str()),
            claim.quote_fact.as_ref().map(|value| value.media_identity.show_or_title.as_str()),
            claim.scene_fact.as_ref().map(|value| value.show_or_title.as_str()),
            claim.why_now_event.as_ref().map(|value| value.media_identity.show_or_title.as_str()),
            claim.cast_fact.as_ref().map(|value| value.show_or_title.as_str()),
        ].into_iter().flatten().any(|value| same_text(value, &opportunity.media_identity.show_or_title));
        if !structured_title_matches && !evidence_source_binds_title(source, &opportunity.media_identity.show_or_title) {
            continue;
        }
        relevant.push(source.title.as_str());
        relevant.push(claim.text.as_str());
    }
    female_audience_evidence(&relevant.join(" "))
}

fn female_audience_evidence(value: &str) -> bool {
    let normalized = format!(" {} ", normalized_words(value));
    let direct = [
        " female skewing audience ",
        " female skewing fandom ",
        " female audience ",
        " female fandom ",
        " women audience ",
        " women fandom ",
        " women viewers ",
        " girls audience ",
        " girls fandom ",
        " girls viewers ",
        " popular among women ",
        " popular with women ",
        " popular among girls ",
        " popular with girls ",
    ]
    .iter()
    .any(|term| normalized.contains(term));
    if direct {
        return true;
    }
    [
        " female centered ",
        " female centred ",
        " female focused ",
        " female led ",
        " women at the center ",
        " centers its women ",
        " centres its women ",
        " heroine ",
        " heroines ",
        " mother ",
        " daughter ",
        " sister ",
        " young adult ",
        " teen ",
        " romance ",
        " romcom ",
        " shipping ",
        " couple ",
        " chemistry ",
        " confession ",
        " relationship fandom ",
    ]
    .iter()
    .filter(|term| normalized.contains(*term))
    .count()
        >= 2
}

fn discussion_matches_opportunity(opportunity: &Opportunity, source: &EvidenceSource) -> bool {
    let title = normalized_words(&source.title);
    let media = normalized_words(&opportunity.media_identity.show_or_title);
    !media.is_empty()
        && (format!(" {title} ").contains(&format!(" {media} "))
            || source_binds_media_title(source, &opportunity.media_identity.show_or_title))
}

fn tvmaze_show_title_binding(show_or_title: &str) -> Option<String> {
    let normalized = normalized_words(show_or_title);
    (!normalized.is_empty()).then(|| {
        format!(
            "{TVMAZE_SHOW_BINDING_PREFIX}{}",
            hex::encode(Sha256::digest(normalized.as_bytes()))
        )
    })
}

fn tvmaze_show_source_binding(show_or_title: &str, canonical_url: &str) -> Option<String> {
    tvmaze_show_title_binding(show_or_title).map(|show_binding| {
        format!(
            "{show_binding}{SOURCE_BINDING_SEPARATOR}{}",
            hex::encode(Sha256::digest(canonical_url.as_bytes()))
        )
    })
}

fn media_title_source_binding(show_or_title: &str, canonical_url: &str) -> Option<String> {
    let normalized = normalized_words(show_or_title);
    (!normalized.is_empty()).then(|| {
        format!(
            "{MEDIA_TITLE_BINDING_PREFIX}{}{SOURCE_BINDING_SEPARATOR}{}",
            hex::encode(Sha256::digest(normalized.as_bytes())),
            hex::encode(Sha256::digest(canonical_url.as_bytes()))
        )
    })
}

fn source_binds_tvmaze_show(source: &EvidenceSource, show_or_title: &str) -> bool {
    if source.provider != "openai" { return false; }
    let Some(value) = source.provider_record_id.as_deref() else { return false; };
    value == tvmaze_show_title_binding(show_or_title).as_deref().unwrap_or("")
        || value
            == tvmaze_show_source_binding(show_or_title, &source.canonical_url)
                .as_deref()
                .unwrap_or("")
}

fn source_binds_media_title(source: &EvidenceSource, show_or_title: &str) -> bool {
    if source.provider != "openai" { return false; }
    let Some(value) = source.provider_record_id.as_deref() else { return false; };
    value
        == media_title_source_binding(show_or_title, &source.canonical_url)
            .as_deref()
            .unwrap_or("")
        || source_binds_tvmaze_show(source, show_or_title)
}

fn evidence_source_binds_title(source: &EvidenceSource, show_or_title: &str) -> bool {
    let title = normalized_words(&source.title);
    let media = normalized_words(show_or_title);
    !media.is_empty()
        && (format!(" {title} ").contains(&format!(" {media} "))
            || source_binds_media_title(source, show_or_title))
}

fn valid_provider_record_id(source: &EvidenceSource) -> bool {
    let Some(value) = source.provider_record_id.as_deref() else { return true; };
    if let Some(binding) = value.strip_prefix(TVMAZE_SHOW_BINDING_PREFIX) {
        let valid_binding = if let Some((show_digest, source_digest)) =
            binding.split_once(SOURCE_BINDING_SEPARATOR)
        {
            valid_hash(show_digest)
                && valid_hash(source_digest)
                && source_digest
                    == hex::encode(Sha256::digest(source.canonical_url.as_bytes()))
        } else {
            valid_hash(binding)
        };
        return source.provider == "openai" && valid_binding;
    }
    if let Some(binding) = value.strip_prefix(MEDIA_TITLE_BINDING_PREFIX) {
        let Some((title_digest, source_digest)) = binding.split_once(SOURCE_BINDING_SEPARATOR)
        else { return false; };
        return source.provider == "openai"
            && valid_hash(title_digest)
            && valid_hash(source_digest)
            && source_digest == hex::encode(Sha256::digest(source.canonical_url.as_bytes()));
    }
    value.chars().count() <= 256
}

fn usable_evidence(claim: &EvidenceClaim, source: &EvidenceSource, now: Timestamp) -> bool {
    matches!(claim.verification.as_str(), "PRIMARY_VERIFIED" | "SECONDARY_CORROBORATED")
        && [source.expires_at.as_deref(), source.purge_due_at.as_deref(), source.deletion_required_at.as_deref()]
            .into_iter().flatten().all(|value| parse_timestamp(value).is_some_and(|deadline| deadline > now))
}

fn footage_actionability(request: &FootageRequest) -> f64 {
    let required_effort = request.required_sources.iter().map(|source| source.acquisition_effort).sum::<i64>();
    let required_count = request.required_sources.len() as i64;
    let mut score = 1.0 - 0.08 * (required_count - 1).max(0) as f64
        - 0.04 * (required_effort - required_count).max(0) as f64;
    if request.alternative_sources.iter().map(|source| source.acquisition_effort).min().is_some_and(|effort| effort < required_effort) {
        score += 0.05;
    }
    score.clamp(0.0, 1.0)
}

fn render_natural_request(required: &[RequestedSource], optional: &[RequestedSource], alternatives: &[RequestedSource]) -> NaturalFootageRequest {
    let required_label = join_labels(&required.iter().map(|source| source_label(source)).collect::<Vec<_>>(), "and");
    NaturalFootageRequest {
        best: format!("Give me {required_label}."),
        alternative: (!alternatives.is_empty()).then(|| format!(
            "If that is easier, give me {}.",
            join_labels(&alternatives.iter().map(|source| source_label(source)).collect::<Vec<_>>(), "or")
        )),
        minimum: format!("The smallest useful set is {required_label}."),
        optional_improvement: (!optional.is_empty()).then(|| format!(
            "If you have it, {} would add another emotional option.",
            join_labels(&optional.iter().map(|source| source_label(source)).collect::<Vec<_>>(), "and")
        )),
    }
}

fn source_label(source: &RequestedSource) -> String {
    match source.asset_kind.as_str() {
        "EPISODE" => {
            let label = format!("Season {} Episode {}", source.season_number.unwrap_or_default(), source.episode_number.unwrap_or_default());
            let episode = source.episode_title.as_ref().map_or(label.clone(), |title| format!("{label} (\"{title}\")"));
            format!("{} {episode}", source.show_or_title)
        },
        "SCENE_PACK" => {
            let focus = source.relationship_or_topic.clone().unwrap_or_else(|| source.characters.join(" + "));
            if focus.is_empty() { format!("a {} scene pack", source.show_or_title) } else { format!("a {focus} scene pack") }
        },
        "OFFICIAL_TRAILER" => format!("the official {} trailer", source.show_or_title),
        "OFFICIAL_CLIP" => format!("the official {} clip", source.show_or_title),
        "INDIVIDUAL_SCENES" => format!(
            "the {} scenes covering {}",
            source.show_or_title,
            source
                .scene_or_moment
                .trim_end_matches(|value| value == ' ' || value == '.'),
        ),
        _ => format!("the requested {} scenes", source.show_or_title),
    }
}

fn join_labels(values: &[String], conjunction: &str) -> String {
    match values {
        [] => String::new(),
        [one] => one.clone(),
        [left, right] => format!("{left} {conjunction} {right}"),
        _ => format!("{}, {conjunction} {}", values[..values.len() - 1].join(", "), values.last().unwrap()),
    }
}

fn safe_search_queries(source: &RequestedSource) -> Vec<String> {
    let focus = source.relationship_or_topic.clone().unwrap_or_else(|| source.characters.join(" "));
    let official_label = source
        .scene_or_moment
        .strip_prefix("Official upload labeled “")
        .and_then(|value| value.strip_suffix('”'))
        .map(str::trim)
        .filter(|value| source.verification_level != "UNKNOWN" && !value.is_empty());
    let official_focus = official_label.unwrap_or(&focus);
    let mut queries = match source.asset_kind.as_str() {
        "EPISODE" => vec![format!("{} season {} episode {} scenes", source.show_or_title, source.season_number.unwrap_or_default(), source.episode_number.unwrap_or_default())],
        "SCENE_PACK" => vec![format!("{} {} scene pack", source.show_or_title, if focus.is_empty() { "character" } else { &focus })],
        "OFFICIAL_TRAILER" => {
            let mut values = Vec::new();
            if !official_focus.is_empty() && official_focus != "official promotional footage" {
                values.push(format!("{} \"{}\" official trailer", source.show_or_title, official_focus));
            }
            values.push(format!("{} official trailer", source.show_or_title));
            values
        }
        "OFFICIAL_CLIP" => {
            let mut values = Vec::new();
            if !official_focus.is_empty() && official_focus != "official promotional footage" {
                values.push(format!("{} \"{}\" official clip", source.show_or_title, official_focus));
            }
            values.push(format!("{} official clip", source.show_or_title));
            values
        }
        _ => vec![format!("{} {} scenes", source.show_or_title, if focus.is_empty() { "character" } else { &focus })],
    };
    if let Some(quote) = source.quote.as_ref() {
        queries.push(format!("\"{}\" {}", quote.text, source.show_or_title));
    }
    unique_strings(queries.iter().map(String::as_str)).into_iter().take(20).collect()
}

fn quality_summary(level: &str) -> &'static str {
    match level {
        "VERIFIED" => "Verified against authoritative source evidence.",
        "STRONGLY_SUPPORTED" => "Strongly supported by relevant corroborated evidence; inspect the local footage before relying on the exact moment.",
        "LIKELY_INFERRED" => "Likely or inferred from relevant evidence; the exact moment is not verified.",
        _ => "Unverified lead; the exact source location remains unknown.",
    }
}

fn source_focus_label(source: &RequestedSource) -> String {
    let focus = source
        .relationship_or_topic
        .clone()
        .unwrap_or_else(|| source.characters.join(" + "));
    truncate_chars(
        if focus.is_empty() {
            &source.show_or_title
        } else {
            &focus
        },
        300,
    )
}

fn source_purpose_label(source: &RequestedSource) -> String {
    join_labels(
        &source
            .purposes
            .iter()
            .map(|purpose| purpose.replace('_', " ").to_lowercase())
            .collect::<Vec<_>>(),
        "and",
    )
}

fn source_emotional_rationale(source: &RequestedSource) -> String {
    let focus = source_focus_label(source);
    let purposes = source_purpose_label(source);
    if source.verification_level == "UNKNOWN" {
        return format!(
            "This is a broad inspection target for {focus} and the {purposes} roles. No specific emotional beat is asserted until the supplied local footage is inspected."
        );
    }
    let moment = truncate_chars(&source.scene_or_moment, 900);
    format!(
        "Evidence links this source to the {purposes} roles for {focus} through this inspection target: {moment} Supplied local footage must confirm its emotional value before editing."
    )
}

fn intro_rationale(lead: &IntroMaterialLead, source: &RequestedSource) -> String {
    let focus = source_focus_label(source);
    if lead.verification_level == "UNKNOWN" {
        return format!(
            "This broad lead may provide context for {focus} before the montage. No exact intro beat is asserted until the supplied local footage is inspected."
        );
    }
    let moment = truncate_chars(&lead.moment_description, 900);
    format!(
        "This evidence-bound lead could provide context for {focus} before the montage: {moment} Supplied local footage must confirm the timing and emotional handoff."
    )
}

fn episode_locator_matches_source(source: &RequestedSource, locator: &EpisodeLocator) -> bool {
    same_text(&locator.show_or_title, &source.show_or_title)
        && source.season_number == Some(locator.season_number)
        && source.episode_number == Some(locator.episode_number)
        && source.episode_title.as_ref().is_none_or(|title| locator.episode_title.as_ref().is_some_and(|expected| same_text(title, expected)))
}

fn episode_fact_matches(source: &RequestedSource, claim: &EvidenceClaim) -> bool {
    claim.episode_locator.as_ref().is_some_and(|locator| episode_locator_matches_source(source, locator))
}

fn claim_carries_matching_episode_locator(source: &RequestedSource, claim: &EvidenceClaim) -> bool {
    claim.episode_locator.as_ref().is_some_and(|locator| episode_locator_matches_source(source, locator))
        || claim.scene_fact.as_ref().and_then(|fact| fact.episode_locator.as_ref()).is_some_and(|locator| episode_locator_matches_source(source, locator))
        || claim.quote_fact.as_ref().and_then(|fact| fact.episode_locator.as_ref()).is_some_and(|locator| episode_locator_matches_source(source, locator))
        || claim.why_now_event.as_ref().and_then(|event| media_identity_locator(&event.media_identity)).as_ref().is_some_and(|locator| episode_locator_matches_source(source, locator))
}

fn scene_fact_matches(source: &RequestedSource, claim: &EvidenceClaim, description: &str) -> bool {
    let Some(fact) = claim.scene_fact.as_ref() else { return false; };
    if !same_text(&fact.show_or_title, &source.show_or_title) || !same_text(&fact.description, description) {
        return false;
    }
    let requested = source.characters.iter().map(|value| same_key(value)).collect::<HashSet<_>>();
    let factual = fact.characters.iter().map(|value| same_key(value)).collect::<HashSet<_>>();
    if !requested.is_subset(&factual) { return false; }
    if source.relationship_or_topic.as_ref().is_some_and(|topic| fact.relationship_or_topic.as_ref().is_none_or(|expected| !same_text(topic, expected))) {
        return false;
    }
    source.asset_kind != "EPISODE" || fact.episode_locator.as_ref().is_some_and(|locator| episode_locator_matches_source(source, locator))
}

fn asset_identity_matches(source: &RequestedSource, claim: &EvidenceClaim) -> bool {
    match source.asset_kind.as_str() {
        "EPISODE" => episode_fact_matches(source, claim),
        "OFFICIAL_CLIP" | "OFFICIAL_TRAILER" => claim.why_now_event.as_ref().is_some_and(|event| {
            event.media_identity.media_kind == if source.asset_kind == "OFFICIAL_CLIP" { "OFFICIAL_CLIP" } else { "TRAILER" }
                && same_text(&event.media_identity.show_or_title, &source.show_or_title)
        }),
        "INDIVIDUAL_SCENES" => scene_fact_matches(source, claim, &source.scene_or_moment),
        _ => false,
    }
}

fn claim_matches_source(source: &RequestedSource, claim: &EvidenceClaim) -> bool {
    match source.asset_kind.as_str() {
        "EPISODE" | "INDIVIDUAL_SCENES" => scene_fact_matches(source, claim, &source.scene_or_moment),
        "OFFICIAL_CLIP" | "OFFICIAL_TRAILER" => asset_identity_matches(source, claim) && scene_fact_matches(source, claim, &source.scene_or_moment),
        _ => false,
    }
}

fn claim_relevant_to_inference(source: &RequestedSource, claim: &EvidenceClaim) -> bool {
    if matches!(claim.verification.as_str(), "STALE" | "RETRACTED") { return false; }
    if claim_matches_source(source, claim) { return true; }
    let identities = [
        claim.episode_locator.as_ref().map(|value| value.show_or_title.as_str()),
        claim.quote_fact.as_ref().map(|value| value.media_identity.show_or_title.as_str()),
        claim.scene_fact.as_ref().map(|value| value.show_or_title.as_str()),
        claim.why_now_event.as_ref().map(|value| value.media_identity.show_or_title.as_str()),
        claim.cast_fact.as_ref().map(|value| value.show_or_title.as_str()),
    ];
    identities.into_iter().flatten().any(|value| same_text(value, &source.show_or_title))
}

fn quote_context_matches_source(source: &RequestedSource, claim: &EvidenceClaim) -> bool {
    claim.quote_fact.as_ref().is_some_and(|fact| {
        same_text(&fact.media_identity.show_or_title, &source.show_or_title)
            && fact.context.as_ref().is_some_and(|context| same_text(context, &source.scene_or_moment))
            && (source.asset_kind != "EPISODE" || fact.episode_locator.as_ref().is_some_and(|locator| episode_locator_matches_source(source, locator)))
    })
}

fn media_identity_is_valid(identity: &MediaIdentity) -> bool {
    valid_text(&identity.show_or_title, 500)
        && if identity.media_kind == "TV_EPISODE" {
            identity.season_number.is_some_and(|value| (0..=MAX_SEASON_NUMBER).contains(&value))
                && identity.episode_number.is_some_and(|value| (1..=9_999).contains(&value))
                && identity.episode_title.as_ref().is_none_or(|value| valid_optional_text(value, 500))
        } else {
            is_media_kind(&identity.media_kind) && identity.season_number.is_none() && identity.episode_number.is_none() && identity.episode_title.is_none()
        }
}

fn media_identity_locator(identity: &MediaIdentity) -> Option<EpisodeLocator> {
    if identity.media_kind != "TV_EPISODE" { return None; }
    Some(EpisodeLocator {
        show_or_title: identity.show_or_title.clone(),
        season_number: identity.season_number?,
        episode_number: identity.episode_number?,
        episode_title: identity.episode_title.clone(),
    })
}

fn episode_locator_is_valid(locator: &EpisodeLocator) -> bool {
    valid_text(&locator.show_or_title, 500)
        && (0..=MAX_SEASON_NUMBER).contains(&locator.season_number)
        && (1..=9_999).contains(&locator.episode_number)
        && locator.episode_title.as_ref().is_none_or(|value| valid_optional_text(value, 500))
}

fn why_now_event_is_valid(event: &WhyNowEvent) -> bool {
    media_identity_is_valid(&event.media_identity)
        && matches!(
            (event.event_kind.as_str(), event.media_identity.media_kind.as_str()),
            ("EPISODE_RELEASE", "TV_EPISODE") | ("FILM_RELEASE", "FILM")
                | ("TRAILER_RELEASE", "TRAILER") | ("OFFICIAL_CLIP_RELEASE", "OFFICIAL_CLIP")
        )
}

fn quote_fact_is_valid(fact: &QuoteFact) -> bool {
    valid_text(&fact.exact_text, 500) && valid_text(&fact.speaker, 500)
        && media_identity_is_valid(&fact.media_identity)
        && fact.context.as_ref().is_none_or(|value| valid_optional_text(value, 500))
        && if let Some(locator) = fact.episode_locator.as_ref() {
            episode_locator_is_valid(locator) && media_identity_locator(&fact.media_identity).as_ref() == Some(locator)
        } else { fact.media_identity.media_kind != "TV_EPISODE" }
}

fn scene_fact_is_valid(fact: &SceneFact) -> bool {
    valid_text(&fact.show_or_title, 500) && valid_text(&fact.description, 2_000)
        && fact.characters.len() <= 20 && fact.characters.iter().all(|value| valid_text(value, 500))
        && fact.relationship_or_topic.as_ref().is_none_or(|value| valid_optional_text(value, 500))
        && fact.episode_locator.as_ref().is_none_or(episode_locator_is_valid)
}

fn cast_fact_is_valid(fact: &CastFact) -> bool {
    valid_text(&fact.show_or_title, 500) && valid_text(&fact.character_name, 500) && valid_text(&fact.performer_name, 500)
}

fn valid_focus(focus: &OpportunityFocus) -> bool {
    focus.characters.len() <= 20 && focus.characters.iter().all(|value| valid_text(value, 500))
        && unique_casefolded(&focus.characters) && valid_text(&focus.relationship_or_topic, 500)
}

fn evidence_source_hash(source: &EvidenceSource) -> String {
    hash_json(&serde_json::json!({
        "provider": source.provider,
        "canonical_url": source.canonical_url,
        "title": source.title,
        "author_or_channel": source.author_or_channel,
        "source_created_at": source.source_created_at.as_deref().map(python_isoformat),
        "page_published_at": source.page_published_at.as_deref().map(python_isoformat),
    }))
}

fn evidence_claim_hash(claim: &EvidenceClaim, source_sha256: &str) -> String {
    hash_json(&serde_json::json!({
        "source_sha256": source_sha256,
        "claim_kind": claim.claim_kind,
        "excerpt_type": claim.excerpt_type,
        "excerpt": claim.text,
        "event_or_release_at": claim.event_or_release_at.as_deref().map(python_isoformat),
        "episode_locator": claim.episode_locator.as_ref().map(episode_locator_value),
        "quote_fact": claim.quote_fact.as_ref().map(quote_fact_value),
        "why_now_event": claim.why_now_event.as_ref().map(why_now_event_value),
        "scene_fact": claim.scene_fact.as_ref().map(scene_fact_value),
        "cast_fact": claim.cast_fact.as_ref().map(cast_fact_value),
    }))
}

fn media_identity_value(value: &MediaIdentity) -> serde_json::Value {
    serde_json::json!({"media_kind":value.media_kind,"show_or_title":value.show_or_title,"season_number":value.season_number,"episode_number":value.episode_number,"episode_title":value.episode_title})
}
fn episode_locator_value(value: &EpisodeLocator) -> serde_json::Value {
    serde_json::json!({"show_or_title":value.show_or_title,"season_number":value.season_number,"episode_number":value.episode_number,"episode_title":value.episode_title})
}
fn why_now_event_value(value: &WhyNowEvent) -> serde_json::Value {
    serde_json::json!({"event_kind":value.event_kind,"media_identity":media_identity_value(&value.media_identity)})
}
fn quote_fact_value(value: &QuoteFact) -> serde_json::Value {
    serde_json::json!({"exact_text":value.exact_text,"speaker":value.speaker,"media_identity":media_identity_value(&value.media_identity),"context":value.context,"episode_locator":value.episode_locator.as_ref().map(episode_locator_value)})
}
fn scene_fact_value(value: &SceneFact) -> serde_json::Value {
    serde_json::json!({"show_or_title":value.show_or_title,"description":value.description,"characters":value.characters,"relationship_or_topic":value.relationship_or_topic,"episode_locator":value.episode_locator.as_ref().map(episode_locator_value)})
}
fn cast_fact_value(value: &CastFact) -> serde_json::Value {
    serde_json::json!({"show_or_title":value.show_or_title,"character_name":value.character_name,"performer_name":value.performer_name})
}

fn hash_json(value: &serde_json::Value) -> String {
    hex::encode(Sha256::digest(serde_json::to_vec(value).expect("JSON value serialization cannot fail")))
}

fn python_isoformat(value: &str) -> String {
    value.strip_suffix('Z').map_or_else(|| value.to_owned(), |prefix| format!("{prefix}+00:00"))
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
struct Timestamp(i128);

impl Timestamp {
    fn checked_sub_days(self, days: i64) -> Option<Self> { self.0.checked_sub(days as i128 * 86_400_000_000_000).map(Self) }
    fn checked_add_seconds(self, seconds: i64) -> Option<Self> { self.0.checked_add(seconds as i128 * 1_000_000_000).map(Self) }
}

fn parse_timestamp(value: &str) -> Option<Timestamp> {
    if !value.is_ascii() || value.len() < 20 { return None; }
    let bytes = value.as_bytes();
    if bytes.get(4) != Some(&b'-') || bytes.get(7) != Some(&b'-') || bytes.get(10) != Some(&b'T')
        || bytes.get(13) != Some(&b':') || bytes.get(16) != Some(&b':')
    { return None; }
    let year = ascii_digits(bytes, 0, 4)? as i64;
    let month = ascii_digits(bytes, 5, 2)? as u32;
    let day = ascii_digits(bytes, 8, 2)? as u32;
    let hour = ascii_digits(bytes, 11, 2)? as i64;
    let minute = ascii_digits(bytes, 14, 2)? as i64;
    let second = ascii_digits(bytes, 17, 2)? as i64;
    if year == 0 || !(1..=12).contains(&month) || day == 0 || day > days_in_month(year, month)
        || hour > 23 || minute > 59 || second > 59
    { return None; }
    let (zone_at, offset_seconds) = if value.ends_with('Z') {
        (value.len() - 1, 0_i64)
    } else {
        if value.len() < 25 { return None; }
        let at = value.len() - 6;
        let sign = match bytes[at] { b'+' => 1_i64, b'-' => -1_i64, _ => return None };
        if bytes.get(at + 3) != Some(&b':') { return None; }
        let zone_hour = ascii_digits(bytes, at + 1, 2)? as i64;
        let zone_minute = ascii_digits(bytes, at + 4, 2)? as i64;
        if zone_hour > 23 || zone_minute > 59 { return None; }
        (at, sign * (zone_hour * 3_600 + zone_minute * 60))
    };
    let fractional = if zone_at == 19 { 0_i128 } else {
        if bytes.get(19) != Some(&b'.') || zone_at <= 20 || zone_at - 20 > 9 { return None; }
        let digits = &bytes[20..zone_at];
        if digits.iter().any(|byte| !byte.is_ascii_digit()) { return None; }
        let mut nanos = digits.iter().fold(0_i128, |total, byte| total * 10 + (byte - b'0') as i128);
        for _ in digits.len()..9 { nanos *= 10; }
        nanos
    };
    let days = days_from_civil(year, month, day);
    let local_seconds = days as i128 * 86_400 + hour as i128 * 3_600 + minute as i128 * 60 + second as i128;
    Some(Timestamp((local_seconds - offset_seconds as i128) * 1_000_000_000 + fractional))
}

pub(crate) fn timestamps_represent_same_instant(left: &str, right: &str) -> bool {
    parse_timestamp(left).zip(parse_timestamp(right)).is_some_and(|(left, right)| left == right)
}

fn ascii_digits(bytes: &[u8], start: usize, count: usize) -> Option<u32> {
    bytes.get(start..start + count)?.iter().try_fold(0_u32, |total, byte| byte.is_ascii_digit().then_some(total * 10 + (byte - b'0') as u32))
}

fn days_in_month(year: i64, month: u32) -> u32 {
    match month { 1 | 3 | 5 | 7 | 8 | 10 | 12 => 31, 4 | 6 | 9 | 11 => 30, 2 if year % 4 == 0 && (year % 100 != 0 || year % 400 == 0) => 29, 2 => 28, _ => 0 }
}

fn days_from_civil(year: i64, month: u32, day: u32) -> i64 {
    let adjusted_year = year - i64::from(month <= 2);
    let era = if adjusted_year >= 0 { adjusted_year } else { adjusted_year - 399 } / 400;
    let year_of_era = adjusted_year - era * 400;
    let shifted_month = month as i64 + if month > 2 { -3 } else { 9 };
    let day_of_year = (153 * shifted_month + 2) / 5 + day as i64 - 1;
    let day_of_era = year_of_era * 365 + year_of_era / 4 - year_of_era / 100 + day_of_year;
    era * 146_097 + day_of_era - 719_468
}

fn format_timestamp(value: Timestamp) -> String {
    let seconds = value.0.div_euclid(1_000_000_000);
    let nanos = value.0.rem_euclid(1_000_000_000) as u32;
    let days = seconds.div_euclid(86_400) as i64;
    let day_seconds = seconds.rem_euclid(86_400) as i64;
    let (year, month, day) = civil_from_days(days);
    let hour = day_seconds / 3_600;
    let minute = day_seconds % 3_600 / 60;
    let second = day_seconds % 60;
    if nanos == 0 {
        format!("{year:04}-{month:02}-{day:02}T{hour:02}:{minute:02}:{second:02}Z")
    } else {
        let fraction = format!("{nanos:09}").trim_end_matches('0').to_owned();
        format!("{year:04}-{month:02}-{day:02}T{hour:02}:{minute:02}:{second:02}.{fraction}Z")
    }
}

fn civil_from_days(days: i64) -> (i64, i64, i64) {
    let shifted = days + 719_468;
    let era = if shifted >= 0 { shifted } else { shifted - 146_096 } / 146_097;
    let day_of_era = shifted - era * 146_097;
    let year_of_era = (day_of_era - day_of_era / 1_460 + day_of_era / 36_524 - day_of_era / 146_096) / 365;
    let mut year = year_of_era + era * 400;
    let day_of_year = day_of_era - (365 * year_of_era + year_of_era / 4 - year_of_era / 100);
    let month_prime = (5 * day_of_year + 2) / 153;
    let day = day_of_year - (153 * month_prime + 2) / 5 + 1;
    let month = month_prime + if month_prime < 10 { 3 } else { -9 };
    year += i64::from(month <= 2);
    (year, month, day)
}

fn valid_text(value: &str, max: usize) -> bool {
    !value.trim().is_empty() && value.trim() == value && value.chars().count() <= max
}
fn valid_optional_text(value: &str, max: usize) -> bool { value.trim() == value && value.chars().count() <= max }
fn valid_identifier(value: &str, max: usize) -> bool {
    (2..=max).contains(&value.len())
        && value.as_bytes().first().is_some_and(u8::is_ascii_lowercase)
        && value.bytes().all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'_')
}
fn unique_borrowed(values: &[&str]) -> bool {
    values.iter().copied().collect::<HashSet<_>>().len() == values.len()
}
fn same_text(left: &str, right: &str) -> bool { same_key(left) == same_key(right) }
fn same_key(value: &str) -> String { value.split_whitespace().collect::<Vec<_>>().join(" ").to_lowercase() }
fn normalized_words(value: &str) -> String {
    value.to_lowercase().chars().map(|character| if character.is_ascii_alphanumeric() { character } else { ' ' }).collect::<String>().split_whitespace().collect::<Vec<_>>().join(" ")
}
fn meaningful_topic_tokens(value: &str) -> HashSet<String> {
    normalized_words(value).split_whitespace().filter(|token| token.len() >= 4 && !matches!(*token, "relationship" | "character" | "characters" | "central" | "story" | "edit" | "montage")).map(str::to_owned).collect()
}
fn unique_strings<'a>(values: impl Iterator<Item = &'a str>) -> Vec<String> {
    let mut seen = HashSet::new();
    values.filter_map(|value| seen.insert(value.to_owned()).then(|| value.to_owned())).collect()
}
fn unique_uuids(values: &[Uuid]) -> bool { values.iter().copied().collect::<HashSet<_>>().len() == values.len() }
fn valid_uuid_v4(value: Uuid) -> bool { value.as_bytes()[6] >> 4 == 4 && value.as_bytes()[8] & 0xc0 == 0x80 }
fn insert_uuid_v4(values: &mut HashSet<Uuid>, value: Uuid) -> bool { valid_uuid_v4(value) && values.insert(value) }
fn source_key_is_valid(value: &str) -> bool {
    (2..=64).contains(&value.len()) && value.as_bytes().first().is_some_and(u8::is_ascii_lowercase)
        && value.bytes().all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'_')
}
fn purposes_are_canonical(values: &[String]) -> bool {
    let rank = |value: &str| match value { "INTRO" => 0, "MONTAGE" => 1, "PAYOFF" => 2, "OPTIONAL_CALLBACK" => 3, _ => 9 };
    values.windows(2).all(|pair| rank(&pair[0]) < rank(&pair[1]))
}
fn violates_exclusions(text: &str, exclusions: &[String]) -> bool {
    let normalized = format!(" {} ", normalized_words(text));
    exclusions.iter().any(|exclusion| {
        let key = normalized_words(exclusion);
        let aliases: &[&str] = match key.as_str() {
            "k drama" => &["k drama", "kdrama", "korean drama"],
            "reality tv" => &["reality tv", "reality television", "reality series"],
            "competition shows" => &["competition show", "competition shows", "competition series", "reality competition"],
            "true crime" => &["true crime", "crime documentary", "crime docuseries"],
            _ => &[],
        };
        if aliases.is_empty() { normalized.contains(&format!(" {key} ")) } else { aliases.iter().any(|value| normalized.contains(&format!(" {value} "))) }
    })
}
fn approx(left: f64, right: f64) -> bool { (left - right).abs() <= 1e-9 }
fn truncate_chars(value: &str, max: usize) -> String { value.chars().take(max).collect() }

fn map_view(result: &CanonicalResearchResult, sources: &[EvidenceSource], claims: &[EvidenceClaim]) -> AppResult<ResearchResultView> {
    let source_by_id = sources.iter().map(|source| (source.source_id, source)).collect::<HashMap<_, _>>();
    let claim_by_id = claims.iter().map(|claim| (claim.claim_id, claim)).collect::<HashMap<_, _>>();
    let interpretation = result.intent.interpretation().map(map_interpretation);
    let candidate_funnel = result.candidate_funnel.as_ref().map(|value| {
        map_candidate_funnel(value, result.opportunities.len())
    });
    if result.status == "NO_STRONG_OPPORTUNITY" {
        let evidence_breakdown = EvidenceReviewBreakdownView {
            metadata_records: sources
                .iter()
                .filter(|source| source.source_type == "METADATA")
                .count(),
            verified_why_now_records: claims
                .iter()
                .filter(|claim| {
                    claim.verification == "PRIMARY_VERIFIED"
                        && matches!(claim.claim_kind.as_str(), "WHY_NOW" | "OFFICIAL_CLIP")
                        && claim.supports_why_now
                })
                .count(),
            current_discussion_signals: claims
                .iter()
                .filter(|claim| {
                    claim.verification == "SECONDARY_CORROBORATED"
                        && claim.claim_kind == "VIEWER_DISCUSSION"
                        && claim.supports_why_now
                })
                .count(),
        };
        return Ok(ResearchResultView::NoStrongOpportunity {
            research_run_id: result.run_id,
            run_timestamp: result.generated_at.clone(),
            pipeline_version: crate::build_provenance::PIPELINE_VERSION,
            provider_config_id: crate::provider_catalog::CATALOG_REGISTRY,
            query_summary: result.intent.query.clone(),
            freshness_cutoff: freshness_cutoff(result)?,
            explanation: result.message.clone(),
            interpretation,
            candidate_funnel: candidate_funnel.clone(),
            evidence_reviewed: sources.len(),
            evidence_breakdown,
            suggestions: unique_strings(
                candidate_funnel
                    .as_ref()
                    .into_iter()
                    .flat_map(|value| value.suggestions.iter().map(String::as_str))
                    .chain(result.warnings.iter().map(String::as_str)),
            ),
        });
    }
    let request_by_id = result.footage_requests.iter().map(|request| (request.footage_request_id, request)).collect::<HashMap<_, _>>();
    let concepts_by_opportunity = result.editorial_concepts.iter().fold(
        HashMap::<Uuid, Vec<&EditorialConcept>>::new(),
        |mut values, concept| {
            values.entry(concept.opportunity_id).or_default().push(concept);
            values
        },
    );
    let dossier_by_opportunity = result
        .fandom_story_dossiers
        .iter()
        .map(|dossier| (dossier.opportunity_id, dossier))
        .collect::<HashMap<_, _>>();
    let mut output = Vec::with_capacity(result.opportunities.len());
    for (index, opportunity) in result.opportunities.iter().enumerate() {
        let request = request_by_id.get(&opportunity.footage_request_id)
            .ok_or_else(|| AppError::Worker("canonical opportunity lost its footage request".to_owned()))?;
        let evidence = map_evidence(opportunity.evidence.iter().map(|reference| reference.claim_id), &claim_by_id, &source_by_id)?;
        let footage = map_footage(request, &claim_by_id, &source_by_id)?;
        let editorial_concepts = concepts_by_opportunity
            .get(&opportunity.opportunity_id)
            .into_iter()
            .flat_map(|values| values.iter().copied())
            .map(|concept| map_editorial_concept(concept, &claim_by_id, &source_by_id))
            .collect::<AppResult<Vec<_>>>()?;
        let fandom_story_dossier = dossier_by_opportunity
            .get(&opportunity.opportunity_id)
            .copied()
            .map(|dossier| map_fandom_story_dossier(dossier, &claim_by_id, &source_by_id))
            .transpose()?;
        let focus = if opportunity.focus.characters.is_empty() {
            opportunity.focus.relationship_or_topic.clone()
        } else {
            format!("{} / {}", opportunity.focus.characters.join(" + "), opportunity.focus.relationship_or_topic)
        };
        output.push(OpportunityView {
            opportunity_id: opportunity.opportunity_id,
            rank: index + 1,
            title: opportunity.title.clone(),
            media_kind: opportunity.media_kind.clone(),
            focus,
            why_now: opportunity.why_now.clone(),
            viewer_conversation: opportunity.what_viewers_are_discussing.clone(),
            creative_hook: opportunity.creative_hook.clone(),
            emotional_edit_idea: opportunity.emotional_edit_direction.clone(),
            promising_intro_material: request.intro_leads.first().map(|lead| lead.moment_description.clone()),
            intro_caveat: "Promising research lead only; the future creative video pass must inspect supplied footage before choosing an intro.".to_owned(),
            evidence_gate: opportunity.evidence_gate.clone(),
            confidence: opportunity.confidence,
            quality_score: opportunity.quality_score.as_ref().map(map_quality_score),
            short_form_edit_potential: opportunity.short_form_edit_potential.as_ref().map(map_short_form_potential),
            fandom_story_dossier,
            editorial_concepts,
            recommended_concept_id: opportunity.recommended_concept_id,
            evidence,
            footage_request: footage,
            caveats: opportunity.caveats.clone(),
        });
    }
    Ok(ResearchResultView::Opportunities {
        research_run_id: result.run_id,
        run_timestamp: result.generated_at.clone(),
        pipeline_version: crate::build_provenance::PIPELINE_VERSION,
        provider_config_id: crate::provider_catalog::CATALOG_REGISTRY,
        query_summary: result.intent.query.clone(),
        freshness_cutoff: freshness_cutoff(result)?,
        interpretation,
        candidate_funnel,
        opportunities: output,
    })
}

fn map_interpretation(value: &IntentInterpretation) -> IntentInterpretationView {
    IntentInterpretationView {
        facets: value.facets.iter().map(|item| IntentFacetView {
            facet_id: item.facet_id.clone(),
            category: item.category.clone(),
            label: item.label.clone(),
            source: item.source.clone(),
            removable: item.removable,
            rationale: item.rationale.clone(),
        }).collect(),
        broad_query: value.broad_query,
        clarification_needed: value.clarification_needed,
        clarification_reason: value.clarification_reason.clone(),
        direct_tiktok_data_used: value.direct_tiktok_data_used,
        short_form_inference_disclaimer: value.short_form_inference_disclaimer.clone(),
    }
}

fn map_candidate_funnel(value: &CandidateFunnel, result_count: usize) -> CandidateFunnelView {
    CandidateFunnelView {
        parsed_intent: value.parsed_intent,
        generated_search_variants: value.generated_search_variants,
        raw_release_candidates: value.raw_release_candidates,
        candidates_after_freshness: value.candidates_after_freshness,
        candidates_after_hard_exclusions: value.candidates_after_hard_exclusions,
        candidates_after_audience_fit_screening: value.candidates_after_audience_fit_screening,
        candidates_selected_for_social_research: value.candidates_selected_for_social_research,
        candidates_with_usable_social_evidence: value.candidates_with_usable_social_evidence,
        candidates_surviving_evidence_gates: value.candidates_surviving_evidence_gates,
        candidates_surviving_deduplication: value.candidates_surviving_deduplication,
        candidates_sent_to_final_ranker: value.candidates_sent_to_final_ranker,
        final_opportunities_serialized: value.final_opportunities_serialized,
        final_opportunities_received_by_rust: result_count,
        final_opportunities_displayed_by_ui: result_count,
        removed_by_hard_constraints: value.removed_by_hard_constraints,
        lacking_current_fandom_evidence: value.lacking_current_fandom_evidence,
        lacking_actionable_footage_information: value.lacking_actionable_footage_information,
        false_abstention_recovery_attempted: value.false_abstention_recovery_attempted,
        recovered_candidate_count: value.recovered_candidate_count,
        evidence_coverage_warning: value.evidence_coverage_warning.clone(),
        rejection_reasons: value.rejection_reasons.clone(),
        candidate_diagnostics: value.candidate_diagnostics.clone(),
        shortage_explanation: value.shortage_explanation.clone(),
        suggestions: value.suggestions.clone(),
    }
}

fn map_quality_score(value: &OpportunityQualityScore) -> OpportunityQualityScoreView {
    OpportunityQualityScoreView {
        profile_id: value.profile_id.clone(),
        intent_fit: value.intent_fit,
        audience_fit: value.audience_fit,
        freshness: value.freshness,
        fandom_velocity: value.fandom_velocity,
        short_form_edit_potential: value.short_form_edit_potential,
        relationship_or_character_salience: value.relationship_or_character_salience,
        footage_actionability: value.footage_actionability,
        evidence_quality: value.evidence_quality,
        source_diversity: value.source_diversity,
        uncertainty_penalty: value.uncertainty_penalty,
        total: value.total,
    }
}

fn map_short_form_potential(value: &ShortFormEditPotential) -> ShortFormEditPotentialView {
    ShortFormEditPotentialView {
        metric_name: value.metric_name.clone(),
        band: value.band.clone(),
        explanation: value.explanation.clone(),
        signals: value.signals.clone(),
        direct_tiktok_data_used: value.direct_tiktok_data_used,
        disclaimer: value.disclaimer.clone(),
    }
}

fn map_dossier_fact(
    fact: &DossierEvidenceFact,
    claims: &HashMap<Uuid, &EvidenceClaim>,
    sources: &HashMap<Uuid, &EvidenceSource>,
) -> AppResult<DossierEvidenceFactView> {
    Ok(DossierEvidenceFactView {
        text: fact.text.clone(),
        verification_status: fact.verification_status.clone(),
        supporting_evidence: map_evidence(fact.supporting_claim_ids.iter().copied(), claims, sources)?,
    })
}

fn map_fandom_story_dossier(
    dossier: &FandomStoryDossier,
    claims: &HashMap<Uuid, &EvidenceClaim>,
    sources: &HashMap<Uuid, &EvidenceSource>,
) -> AppResult<FandomStoryDossierView> {
    let map_facts = |facts: &[DossierEvidenceFact]| {
        facts
            .iter()
            .map(|fact| map_dossier_fact(fact, claims, sources))
            .collect::<AppResult<Vec<_>>>()
    };
    Ok(FandomStoryDossierView {
        dossier_id: dossier.dossier_id,
        current_event_or_hook: map_dossier_fact(&dossier.current_event_or_hook, claims, sources)?,
        named_characters: dossier
            .named_characters
            .iter()
            .map(|character| {
                Ok(DossierCharacterView {
                    character_name: character.character_name.clone(),
                    performer_name: character.performer_name.clone(),
                    show_or_title: character.show_or_title.clone(),
                    verification_status: character.verification_status.clone(),
                    supporting_evidence: map_evidence(character.supporting_claim_ids.iter().copied(), claims, sources)?,
                })
            })
            .collect::<AppResult<Vec<_>>>()?,
        central_relationship: dossier
            .central_relationship
            .as_ref()
            .map(|fact| map_dossier_fact(fact, claims, sources))
            .transpose()?,
        current_source: DossierCurrentSourceView {
            source_kind: dossier.current_source.source_kind.clone(),
            show_or_title: dossier.current_source.show_or_title.clone(),
            source_title: dossier.current_source.source_title.clone(),
            season_number: dossier.current_source.season_number,
            episode_number: dossier.current_source.episode_number,
            episode_title: dossier.current_source.episode_title.clone(),
            verification_status: dossier.current_source.verification_status.clone(),
            supporting_evidence: map_evidence(dossier.current_source.supporting_claim_ids.iter().copied(), claims, sources)?,
        },
        exact_or_likely_quote: dossier
            .exact_or_likely_quote
            .as_ref()
            .map(|lead| -> AppResult<DossierQuoteLeadView> {
                Ok(DossierQuoteLeadView {
                    quote: map_quote(&lead.quote),
                    source_title: lead.source_title.clone(),
                    verification_status: lead.verification_status.clone(),
                    supporting_evidence: map_evidence(lead.supporting_claim_ids.iter().copied(), claims, sources)?,
                })
            })
            .transpose()?,
        franchise_connections: dossier
            .franchise_connections
            .iter()
            .map(|connection| {
                Ok(DossierFranchiseConnectionView {
                    connection_type: connection.connection_type.clone(),
                    current_title: connection.current_title.clone(),
                    connected_title: connection.connected_title.clone(),
                    characters: connection.characters.clone(),
                    description: connection.description.clone(),
                    verification_status: connection.verification_status.clone(),
                    supporting_evidence: map_evidence(connection.supporting_claim_ids.iter().copied(), claims, sources)?,
                })
            })
            .collect::<AppResult<Vec<_>>>()?,
        relationship_or_character_history: map_facts(&dossier.relationship_or_character_history)?,
        why_fans_currently_care: map_facts(&dossier.why_fans_currently_care)?,
        audience_and_fandom_evidence: map_facts(&dossier.audience_and_fandom_evidence)?,
        uncertainties: dossier.uncertainties.clone(),
    })
}

fn map_editorial_concept(
    concept: &EditorialConcept,
    claims: &HashMap<Uuid, &EvidenceClaim>,
    sources: &HashMap<Uuid, &EvidenceSource>,
) -> AppResult<EditorialConceptView> {
    let footage_request = map_footage(&concept.footage_request, claims, sources)?;
    Ok(EditorialConceptView {
        concept_id: concept.concept_id,
        dossier_id: concept.dossier_id,
        title: concept.title.clone(),
        central_subject: concept.central_subject.clone(),
        central_relationship: concept.central_relationship.clone(),
        core_emotion: concept.core_emotion.clone(),
        viewer_hook: concept.viewer_hook.clone(),
        why_fans_may_care: concept.why_fans_may_care.clone(),
        current_event: concept.current_event.clone(),
        legacy_or_contextual_connection: concept.legacy_or_contextual_connection.clone(),
        legacy_connection_type: concept.legacy_connection_type.clone(),
        intro_leads: footage_request.intro_leads.clone(),
        song_handoff_idea: concept.song_handoff_idea.clone(),
        montage_arc: concept.montage_arc.clone(),
        ending_or_payoff: concept.ending_or_payoff.clone(),
        verification_status: concept.verification_status.clone(),
        score: EditorialConceptScoreView {
            concept_specificity: concept.score.concept_specificity,
            intro_strength: concept.score.intro_strength,
            emotional_arc_strength: concept.score.emotional_arc_strength,
            narrative_bridge_strength: concept.score.narrative_bridge_strength,
            fan_recognition: concept.score.fan_recognition,
            current_event_relevance: concept.score.current_event_relevance,
            legacy_context_value: concept.score.legacy_context_value,
            payoff_strength: concept.score.payoff_strength,
            footage_feasibility: concept.score.footage_feasibility,
            source_actionability: concept.score.source_actionability,
            originality: concept.score.originality,
            evidence_quality: concept.score.evidence_quality,
            uncertainty_penalty: concept.score.uncertainty_penalty,
            total: concept.score.total,
        },
        known_uncertainties: concept.known_uncertainties.clone(),
        footage_request,
        provisional_notice: concept.provisional_notice.clone(),
    })
}

fn freshness_cutoff(result: &CanonicalResearchResult) -> AppResult<String> {
    parse_timestamp(&result.generated_at)
        .and_then(|value| value.checked_sub_days(result.intent.freshness_days))
        .map(format_timestamp)
        .ok_or_else(|| AppError::Worker("canonical result freshness cutoff overflowed".to_owned()))
}

fn map_footage(request: &FootageRequest, claims: &HashMap<Uuid, &EvidenceClaim>, sources: &HashMap<Uuid, &EvidenceSource>) -> AppResult<FootageRequestView> {
    fn bucket(values: &[RequestedSource], group: &str, claims: &HashMap<Uuid, &EvidenceClaim>, sources: &HashMap<Uuid, &EvidenceSource>) -> AppResult<Vec<RequestedSourceView>> {
        values.iter().map(|source| Ok(RequestedSourceView {
            source_id: source.requested_source_id,
            source_key: source.source_key.clone(),
            group: group.to_owned(),
            priority: source.priority,
            purposes: source.purposes.clone(),
            show_or_title: source.show_or_title.clone(),
            season_number: source.season_number,
            episode_number: source.episode_number,
            episode_title: source.episode_title.clone(),
            asset_kind: source.asset_kind.clone(),
            characters: source.characters.clone(),
            relationship_or_topic: source.relationship_or_topic.clone(),
            scene_or_moment: source.scene_or_moment.clone(),
            quote: source.quote.as_ref().map(map_quote),
            why_it_matters_emotionally: source.why_it_matters_emotionally.clone(),
            verification_level: source.verification_level.clone(),
            source_quality_summary: source.source_quality_summary.clone(),
            supporting_claim_ids: source.supporting_claim_ids.clone(),
            supporting_evidence: map_evidence(source.supporting_claim_ids.iter().copied(), claims, sources)?,
            acquisition_effort: source.acquisition_effort,
            search_queries: source.search_queries.clone(),
            replaces_required_source_keys: source.replaces_required_source_keys.clone(),
        })).collect()
    }
    let intro_leads = request.intro_leads.iter().map(|lead| Ok(IntroMaterialLeadView {
        intro_lead_id: lead.intro_lead_id,
        source_key: lead.source_key.clone(),
        moment_description: lead.moment_description.clone(),
        quote: lead.quote.as_ref().map(map_quote),
        why_it_might_lead_into_montage: lead.why_it_might_lead_into_montage.clone(),
        verification_level: lead.verification_level.clone(),
        supporting_claim_ids: lead.supporting_claim_ids.clone(),
        supporting_evidence: map_evidence(lead.supporting_claim_ids.iter().copied(), claims, sources)?,
    })).collect::<AppResult<Vec<_>>>()?;
    Ok(FootageRequestView {
        request_id: request.footage_request_id,
        concept_id: request.concept_id,
        summary: request.summary.clone(),
        natural_request: request.natural_request.clone(),
        minimum_useful_source_keys: request.minimum_useful_source_keys.clone(),
        smallest_useful_set_reason: request.smallest_useful_set_reason.clone(),
        required_sources: bucket(&request.required_sources, "REQUIRED", claims, sources)?,
        optional_sources: bucket(&request.optional_sources, "OPTIONAL", claims, sources)?,
        alternative_sources: bucket(&request.alternative_sources, "ALTERNATIVE", claims, sources)?,
        intro_leads,
        search_queries: request.search_queries.clone(),
        warnings: request.warnings.clone(),
    })
}

fn map_quote(value: &FootageQuote) -> QuoteView {
    QuoteView { status: value.status.clone(), text: value.text.clone(), speaker: value.speaker.clone(), likely_context: value.likely_context.clone(), claim_id: value.claim_id }
}

fn map_evidence<'a>(ids: impl Iterator<Item = Uuid>, claims: &HashMap<Uuid, &'a EvidenceClaim>, sources: &HashMap<Uuid, &'a EvidenceSource>) -> AppResult<Vec<EvidenceView>> {
    ids.map(|id| {
        let claim = claims.get(&id).ok_or_else(|| AppError::Worker("evidence claim join failed".to_owned()))?;
        let source = sources.get(&claim.source_id).ok_or_else(|| AppError::Worker("evidence source join failed".to_owned()))?;
        Ok(EvidenceView {
            evidence_id: claim.claim_id,
            source_id: source.source_id,
            claim_id: claim.claim_id,
            provider: source.provider.clone(),
            title: source.title.clone(),
            publisher: source.author_or_channel.clone().unwrap_or_else(|| source.provider.clone()),
            source_type: source.source_type.clone(),
            verification: claim.verification.clone(),
            retrieved_at: source.retrieved_at.clone(),
            published_at: source.page_published_at.clone().or_else(|| source.source_created_at.clone()),
            event_or_release_at: claim.event_or_release_at.clone(),
            excerpt_type: claim.excerpt_type.clone(),
            excerpt: claim.text.clone(),
            link_handle: source.source_id,
            independence_group: source.independence_group.clone(),
        })
    }).collect()
}

fn valid_score(score: &OpportunityScore) -> bool {
    let values = [score.release_freshness, score.cross_source_agreement, score.scene_specificity, score.footage_actionability, score.total];
    values.into_iter().all(valid_confidence)
        && (score.total - values[..4].iter().sum::<f64>() / 4.0).abs() <= 1e-9
        && (0..=30).contains(&score.independent_source_count)
}

fn is_media_kind(value: &str) -> bool { matches!(value, "TV_EPISODE" | "TV_SERIES" | "FILM" | "TRAILER" | "OFFICIAL_CLIP") }
fn valid_confidence(value: f64) -> bool { value.is_finite() && (0.0..=1.0).contains(&value) }
fn valid_hash(value: &str) -> bool { value.len() == 64 && value.bytes().all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte)) }
fn unique_casefolded(values: &[String]) -> bool { values.iter().map(|value| value.to_lowercase()).collect::<HashSet<_>>().len() == values.len() }
fn valid_https_url(value: &str) -> bool {
    tauri::Url::parse(value).is_ok_and(|url| url.scheme() == "https" && url.host_str().is_some() && url.username().is_empty() && url.password().is_none())
}
fn contains_prohibited_or_viral(values: &[&String]) -> bool {
    values.iter().any(|value| contains_prohibited_or_viral_text(value))
}
fn contains_prohibited_or_viral_text(value: &str) -> bool {
    let lower = format!(" {} ", value.to_lowercase());
    ["yt-dlp", "yt dlp", "m3u8", "manifest", "torrent", "download", " rip ", "ripping", "ripped", "bypass", "defeat", "circumvent", "drm", "paywall", "cookie", "auth token", "authorization header", "viral", "% chance"]
        .iter().any(|needle| lower.contains(needle))
}
fn invalid_bundle_at<T>(stage: &'static str) -> AppResult<T> {
    Err(AppError::Worker(format!(
        "canonical research bundle failed trusted domain validation at {stage}"
    )))
}

#[cfg(test)]
mod tests {
    use super::*;

    struct OpportunityFixture {
        result: serde_json::Value,
        sources: Vec<serde_json::Value>,
        claims: Vec<serde_json::Value>,
        run_id: Uuid,
        intent: CanonicalResearchIntent,
        policies: Vec<TrustedEvidencePolicyRecord>,
    }

    fn finish_source(mut value: serde_json::Value) -> serde_json::Value {
        let parsed: EvidenceSource = serde_json::from_value(value.clone()).unwrap();
        value["contentSha256"] = evidence_source_hash(&parsed).into();
        value
    }

    fn finish_claim(mut value: serde_json::Value, source: &serde_json::Value) -> serde_json::Value {
        let parsed: EvidenceClaim = serde_json::from_value(value.clone()).unwrap();
        value["contentSha256"] = evidence_claim_hash(&parsed, source["contentSha256"].as_str().unwrap()).into();
        value
    }

    fn evidence_source(
        id: Uuid,
        provider: &str,
        source_type: &str,
        url: &str,
        title: &str,
        created: Option<&str>,
        published: Option<&str>,
        group: &str,
    ) -> serde_json::Value {
        let (policy, refresh, expiry) = if provider == "tvmaze" {
            ("tvmaze-metadata-v1", "2026-08-16T20:00:00Z", "2026-08-16T20:00:00Z")
        } else {
            ("openai-web-evidence-v1", "2026-08-16T08:00:00Z", "2026-08-16T08:00:00Z")
        };
        finish_source(serde_json::json!({
            "schemaVersion":"2.0.0","sourceId":id,"provider":provider,"providerRecordId":null,
            "sourceType":source_type,"canonicalUrl":url,"title":title,"authorOrChannel":"Fixture Publisher",
            "sourceCreatedAt":created,"sourceUpdatedAt":null,"pagePublishedAt":published,
            "retrievedAt":"2026-08-15T20:00:00Z","query":"romance TV",
            "windowStart":"2026-08-12T20:00:00Z","windowEnd":"2026-08-15T20:00:00Z",
            "policyClass":policy,"refreshDueAt":refresh,"purgeDueAt":"2026-09-14T20:00:00Z",
            "expiresAt":expiry,"deletionRequiredAt":null,"contentSha256":"",
            "independenceGroup":group
        }))
    }

    fn opportunity_fixture() -> OpportunityFixture {
        let run_id = Uuid::new_v4();
        let opportunity_id = Uuid::new_v4();
        let request_id = Uuid::new_v4();
        let requested_source_id = Uuid::new_v4();
        let intro_id = Uuid::new_v4();
        let primary_source_id = Uuid::new_v4();
        let signal_a_source_id = Uuid::new_v4();
        let signal_b_source_id = Uuid::new_v4();
        let official_source_id = Uuid::new_v4();
        let primary_claim_id = Uuid::new_v4();
        let signal_a_claim_id = Uuid::new_v4();
        let signal_b_claim_id = Uuid::new_v4();
        let scene_claim_id = Uuid::new_v4();
        let quote_claim_id = Uuid::new_v4();
        let media_identity = serde_json::json!({
            "mediaKind":"TV_EPISODE","showOrTitle":"Example Show","seasonNumber":1,
            "episodeNumber":2,"episodeTitle":"The Turning Point"
        });
        let locator = serde_json::json!({
            "showOrTitle":"Example Show","seasonNumber":1,"episodeNumber":2,
            "episodeTitle":"The Turning Point"
        });
        let primary_source = evidence_source(
            primary_source_id, "tvmaze", "METADATA", "https://api.tvmaze.com/episodes/2",
            "Example Show Season 1 Episode 2 The Turning Point", None, Some("2026-08-14T20:00:00Z"),
            "publisher:tvmaze",
        );
        let signal_a_source = evidence_source(
            signal_a_source_id, "openai", "ARTICLE", "https://variety.com/example-show-ada-bea/",
            "Example Show: viewers discuss Ada and Bea", Some("2026-08-15T19:00:00Z"), None,
            "owner:penske-media",
        );
        let signal_b_source = evidence_source(
            signal_b_source_id, "openai", "ARTICLE", "https://vulture.com/example-show-ada-bea/",
            "Example Show Ada and Bea relationship reactions", Some("2026-08-15T18:00:00Z"), None,
            "owner:new-york-media",
        );
        let official_source = evidence_source(
            official_source_id, "openai", "PRIMARY_RELEASE", "https://abc.com/example-show/episode-2/",
            "Example Show Season 1 Episode 2 official page", None, Some("2026-08-14T20:00:00Z"),
            "official:abc",
        );
        let primary_text = "Example Show Season 1 Episode 2 premiered on August 14.";
        let signal_a_text = "Viewers are discussing how Ada finally trusts Bea.";
        let signal_b_text = "Fans highlight Ada and Bea repairing trust after the argument.";
        let scene_text = "Ada admits she trusts Bea after the argument.";
        let primary_claim = finish_claim(serde_json::json!({
            "schemaVersion":"2.0.0","claimId":primary_claim_id,"sourceId":primary_source_id,
            "claimKind":"WHY_NOW","excerptType":"PARAPHRASE","text":primary_text,
            "verification":"PRIMARY_VERIFIED","episodeLocator":locator,"quoteFact":null,
            "whyNowEvent":{"eventKind":"EPISODE_RELEASE","mediaIdentity":media_identity},
            "sceneFact":null,"castFact":null,"eventOrReleaseAt":"2026-08-14T20:00:00Z",
            "confidence":1.0,"supportsWhyNow":true,"contentSha256":""
        }), &primary_source);
        let signal_a_claim = finish_claim(serde_json::json!({
            "schemaVersion":"2.0.0","claimId":signal_a_claim_id,"sourceId":signal_a_source_id,
            "claimKind":"VIEWER_DISCUSSION","excerptType":"PARAPHRASE","text":signal_a_text,
            "verification":"SECONDARY_CORROBORATED","episodeLocator":null,"quoteFact":null,
            "whyNowEvent":null,"sceneFact":null,"castFact":null,"eventOrReleaseAt":null,
            "confidence":0.8,"supportsWhyNow":true,"contentSha256":""
        }), &signal_a_source);
        let signal_b_claim = finish_claim(serde_json::json!({
            "schemaVersion":"2.0.0","claimId":signal_b_claim_id,"sourceId":signal_b_source_id,
            "claimKind":"VIEWER_DISCUSSION","excerptType":"PARAPHRASE","text":signal_b_text,
            "verification":"SECONDARY_CORROBORATED","episodeLocator":null,"quoteFact":null,
            "whyNowEvent":null,"sceneFact":null,"castFact":null,"eventOrReleaseAt":null,
            "confidence":0.8,"supportsWhyNow":true,"contentSha256":""
        }), &signal_b_source);
        let scene_fact = serde_json::json!({
            "showOrTitle":"Example Show","description":scene_text,"characters":["Ada"],
            "relationshipOrTopic":"Ada and Bea","episodeLocator":locator
        });
        let scene_claim = finish_claim(serde_json::json!({
            "schemaVersion":"2.0.0","claimId":scene_claim_id,"sourceId":official_source_id,
            "claimKind":"SCENE_CONTEXT","excerptType":"PARAPHRASE","text":scene_text,
            "verification":"PRIMARY_VERIFIED","episodeLocator":null,"quoteFact":null,
            "whyNowEvent":null,"sceneFact":scene_fact,"castFact":null,"eventOrReleaseAt":null,
            "confidence":0.95,"supportsWhyNow":false,"contentSha256":""
        }), &official_source);
        let quote_claim = finish_claim(serde_json::json!({
            "schemaVersion":"2.0.0","claimId":quote_claim_id,"sourceId":official_source_id,
            "claimKind":"QUOTE","excerptType":"SHORT_QUOTE","text":"I trust you.",
            "verification":"PRIMARY_VERIFIED","episodeLocator":null,
            "quoteFact":{"exactText":"I trust you.","speaker":"Ada","mediaIdentity":media_identity,
                "context":scene_text,"episodeLocator":locator},
            "whyNowEvent":null,"sceneFact":null,"castFact":null,"eventOrReleaseAt":null,
            "confidence":1.0,"supportsWhyNow":false,"contentSha256":""
        }), &official_source);
        let actionability = 1.0_f64;
        let freshness = 2.0_f64 / 3.0;
        let total = (freshness + 1.0 + 1.0 + actionability) / 4.0;
        let signal_summary = format!("{signal_a_text}; {signal_b_text}");
        let result = serde_json::json!({
            "schemaVersion":"2.0.0","runId":run_id,"status":"OPPORTUNITIES",
            "intent":{"schemaVersion":"2.0.0","query":"romance TV","mediaKinds":["TV_EPISODE"],
                "focusTerms":[],"region":"US","freshnessDays":3,"spoilerPolicy":"CURRENT_EPISODE",
                "exclusions":[],"maxResults":3},
            "opportunities":[{
                "schemaVersion":"2.0.0","opportunityId":opportunity_id,"footageRequestId":request_id,
                "mediaKind":"TV_EPISODE","mediaIdentity":media_identity,
                "title":"Example Show: Ada and Bea","focus":{"characters":["Ada"],"relationshipOrTopic":"Ada and Bea"},
                "whyNow":format!("Verified why-now evidence: {primary_text}"),
                "whatViewersAreDiscussing":format!("Current qualitative signals: {signal_summary}"),
                "creativeHook":format!("Start with this LIKELY / INFERRED exact-episode scene lead: {scene_text}. It is tied to the current discussion signals: {signal_summary}. The source does not verify the final outcome, timestamp, or footage location."),
                "emotionalEditDirection":format!("Anchor the contextual setup in the verified current event: {primary_text} Then inspect the supplied footage for a montage and payoff shaped by: {signal_summary}. The later creative video analysis must confirm the exact visual moments."),
                "evidence":[
                    {"claimId":primary_claim_id,"role":"PRIMARY_WHY_NOW","supportsWhyNow":true,"independenceGroup":"publisher:tvmaze"},
                    {"claimId":signal_a_claim_id,"role":"QUALITATIVE_SIGNAL","supportsWhyNow":true,"independenceGroup":"owner:penske-media"},
                    {"claimId":signal_b_claim_id,"role":"QUALITATIVE_SIGNAL","supportsWhyNow":true,"independenceGroup":"owner:new-york-media"},
                    {"claimId":scene_claim_id,"role":"CONTEXT","supportsWhyNow":false,"independenceGroup":"official:abc"},
                    {"claimId":quote_claim_id,"role":"QUOTE_PROOF","supportsWhyNow":false,"independenceGroup":"official:abc"}
                ],
                "evidenceGate":"PASSED","confidence":0.8,
                "score":{"releaseFreshness":freshness,"crossSourceAgreement":1.0,"sceneSpecificity":1.0,
                    "footageActionability":actionability,"independentSourceCount":3,"total":total},
                "caveats":["Creative scene selection is provisional until the supplied local footage is inspected."]
            }],
            "footageRequests":[{
                "schemaVersion":"2.0.0","footageRequestId":request_id,"opportunityId":opportunity_id,
                "summary":"Smallest evidence-bound footage request for this research opportunity.",
                "naturalRequest":{"best":"Give me Example Show Season 1 Episode 2 (\"The Turning Point\").",
                    "alternative":null,"minimum":"The smallest useful set is Example Show Season 1 Episode 2 (\"The Turning Point\").",
                    "optionalImprovement":null},
                "requiredSources":[{
                    "requestedSourceId":requested_source_id,"sourceKey":"episode_main","priority":1,"acquisitionEffort":1,
                    "assetKind":"EPISODE","showOrTitle":"Example Show","seasonNumber":1,"episodeNumber":2,
                    "episodeTitle":"The Turning Point","characters":["Ada"],"relationshipOrTopic":"Ada and Bea",
                    "sceneOrMoment":scene_text,"purposes":["INTRO","MONTAGE"],"verificationLevel":"VERIFIED",
                    "sourceQualitySummary":"Verified against authoritative source evidence.",
                    "supportingClaimIds":[primary_claim_id,scene_claim_id,quote_claim_id],
                    "quote":{"status":"VERIFIED","text":"I trust you.","speaker":"Ada","likelyContext":scene_text,"claimId":quote_claim_id},
                    "whyItMattersEmotionally":format!("Evidence links this source to the intro and montage roles for Ada and Bea through this inspection target: {scene_text} Supplied local footage must confirm its emotional value before editing."),
                    "searchQueries":["Example Show season 1 episode 2 scenes","\"I trust you.\" Example Show"],
                    "replacesRequiredSourceKeys":[]
                }],
                "optionalSources":[],"alternativeSources":[],"minimumUsefulSourceKeys":["episode_main"],
                "smallestUsefulSetReason":"The required bucket is the smallest set supported by the current evidence; optional and alternative items are not prerequisites.",
                "introLeads":[{"introLeadId":intro_id,"sourceKey":"episode_main","momentDescription":scene_text,
                    "quote":{"status":"VERIFIED","text":"I trust you.","speaker":"Ada","likelyContext":scene_text,"claimId":quote_claim_id},
                    "whyItMightLeadIntoMontage":format!("This evidence-bound lead could provide context for Ada and Bea before the montage: {scene_text} Supplied local footage must confirm the timing and emotional handoff."),
                    "verificationLevel":"VERIFIED","supportingClaimIds":[scene_claim_id,quote_claim_id]}],
                "searchQueries":["Example Show season 1 episode 2 scenes","\"I trust you.\" Example Show"],"warnings":[]
            }],
            "message":"These opportunities passed the current evidence gate; inspect supplied local footage before making final creative decisions.",
            "appliedExclusions":[],"warnings":[],"generatedAt":"2026-08-15T20:00:00Z"
        });
        let intent = parse_intent(result["intent"].clone()).unwrap();
        let generated_ms = (parse_timestamp("2026-08-15T20:00:00Z").unwrap().0 / 1_000_000) as i64;
        let policies = vec![
            TrustedEvidencePolicyRecord { provider:"tvmaze".into(), policy_class:"tvmaze-metadata-v1".into(), evidence_ttl_seconds:86_400, refresh_after_seconds:86_400, purge_after_seconds:2_592_000, deletion_after_seconds:None, checked_at_ms:generated_ms-86_400_000, expires_at_ms:generated_ms+86_400_000 },
            TrustedEvidencePolicyRecord { provider:"openai".into(), policy_class:"openai-web-evidence-v1".into(), evidence_ttl_seconds:43_200, refresh_after_seconds:43_200, purge_after_seconds:2_592_000, deletion_after_seconds:None, checked_at_ms:generated_ms-86_400_000, expires_at_ms:generated_ms+86_400_000 },
        ];
        OpportunityFixture {
            result,
            sources: vec![primary_source, signal_a_source, signal_b_source, official_source],
            claims: vec![primary_claim, signal_a_claim, signal_b_claim, scene_claim, quote_claim],
            run_id, intent, policies,
        }
    }

    fn metadata_low_fixture() -> OpportunityFixture {
        let mut fixture = opportunity_fixture();
        let metadata_claim_id = fixture.claims[0]["claimId"].clone();
        let signal_a_claim_id = fixture.claims[1]["claimId"].clone();
        let signal_b_claim_id = fixture.claims[2]["claimId"].clone();
        let metadata_text = "TVmaze lists The Turning Point as Season 1 Episode 2.";
        let signal_a_text = fixture.claims[1]["text"].as_str().unwrap().to_owned();
        let signal_b_text = fixture.claims[2]["text"].as_str().unwrap().to_owned();
        let signal_summary = format!("{signal_a_text}; {signal_b_text}");

        fixture.claims[0]["claimKind"] = "EPISODE_IDENTITY".into();
        fixture.claims[0]["text"] = metadata_text.into();
        fixture.claims[0]["verification"] = "SECONDARY_CORROBORATED".into();
        fixture.claims[0]["whyNowEvent"] = serde_json::Value::Null;
        fixture.claims[0]["supportsWhyNow"] = false.into();
        fixture.claims[0] = finish_claim(fixture.claims[0].clone(), &fixture.sources[0]);

        let opportunity = &mut fixture.result["opportunities"][0];
        opportunity["whyNow"] = format!(
            "Current episode metadata (not an official why-now proof): {metadata_text}"
        ).into();
        opportunity["whatViewersAreDiscussing"] =
            format!("Current qualitative signals: {signal_summary}").into();
        opportunity["creativeHook"] = format!(
            "Investigate Ada and Bea through the specific current signals: {signal_summary}. Treat these as evidence-led inspection targets, not final scene selections."
        ).into();
        opportunity["emotionalEditDirection"] = format!(
            "Use the current episode metadata only as a timing lead, not proof of a specific scene: {metadata_text} Then inspect a supplied scene pack or other lawfully obtained local footage for a montage and payoff shaped by: {signal_summary}. The later creative video analysis must confirm every exact visual moment."
        ).into();
        opportunity["evidence"] = serde_json::json!([
            {"claimId":metadata_claim_id,"role":"CONTEXT","supportsWhyNow":false,"independenceGroup":"publisher:tvmaze"},
            {"claimId":signal_a_claim_id,"role":"QUALITATIVE_SIGNAL","supportsWhyNow":true,"independenceGroup":"owner:penske-media"},
            {"claimId":signal_b_claim_id,"role":"QUALITATIVE_SIGNAL","supportsWhyNow":true,"independenceGroup":"owner:new-york-media"}
        ]);
        opportunity["evidenceGate"] = "LOW_CONFIDENCE".into();
        let freshness = 2.0_f64 / 3.0;
        let actionability = 0.96_f64;
        let total = (freshness + 1.0 + 1.0 + actionability) / 4.0;
        opportunity["score"] = serde_json::json!({
            "releaseFreshness":freshness,"crossSourceAgreement":1.0,"sceneSpecificity":1.0,
            "footageActionability":actionability,"independentSourceCount":3,"total":total
        });
        opportunity["caveats"] = serde_json::json!([
            "Creative scene selection is provisional until the supplied local footage is inspected.",
            "Low confidence: no official why-now proof was verified; this uses exact current TVmaze episode metadata plus two independent title-bound discussion sources. No discussion claim is treated as proof of a scene occurring in that episode."
        ]);

        let source = &mut fixture.result["footageRequests"][0]["requiredSources"][0];
        source["sourceKey"] = "relationship_pack".into();
        source["priority"] = 1.into();
        source["acquisitionEffort"] = 2.into();
        source["assetKind"] = "SCENE_PACK".into();
        source["seasonNumber"] = serde_json::Value::Null;
        source["episodeNumber"] = serde_json::Value::Null;
        source["episodeTitle"] = serde_json::Value::Null;
        source["sceneOrMoment"] = signal_a_text.clone().into();
        source["verificationLevel"] = "LIKELY_INFERRED".into();
        source["sourceQualitySummary"] =
            "Likely or inferred from relevant evidence; the exact moment is not verified.".into();
        source["supportingClaimIds"] = serde_json::json!([
            metadata_claim_id, signal_a_claim_id, signal_b_claim_id
        ]);
        source["quote"] = serde_json::Value::Null;
        source["whyItMattersEmotionally"] = format!(
            "Evidence links this source to the intro and montage roles for Ada and Bea through this inspection target: {signal_a_text} Supplied local footage must confirm its emotional value before editing."
        ).into();
        source["searchQueries"] = serde_json::json!([
            "Example Show Ada and Bea scene pack"
        ]);

        let request = &mut fixture.result["footageRequests"][0];
        request["naturalRequest"] = serde_json::json!({
            "best":"Give me a Ada and Bea scene pack.",
            "alternative":null,
            "minimum":"The smallest useful set is a Ada and Bea scene pack.",
            "optionalImprovement":null
        });
        request["minimumUsefulSourceKeys"] = serde_json::json!(["relationship_pack"]);
        request["introLeads"] = serde_json::json!([]);
        request["searchQueries"] = serde_json::json!(["Example Show Ada and Bea scene pack"]);
        fixture.result["message"] = "Some opportunities are explicitly low confidence because they did not meet the normal official-primary-plus-two-signals gate; inspect each card's caveat, cited evidence, and supplied local footage before proceeding.".into();
        fixture
    }

    fn metadata_low_scene_fixture() -> OpportunityFixture {
        let mut fixture = metadata_low_fixture();
        let metadata_claim_id = fixture.claims[0]["claimId"].clone();
        let signal_a_claim_id = fixture.claims[1]["claimId"].clone();
        let signal_b_claim_id = fixture.claims[2]["claimId"].clone();
        let scene_claim_id = fixture.claims[3]["claimId"].clone();
        let metadata_text = fixture.claims[0]["text"].as_str().unwrap().to_owned();
        let signal_a_text = fixture.claims[1]["text"].as_str().unwrap().to_owned();
        let signal_b_text = fixture.claims[2]["text"].as_str().unwrap().to_owned();
        let scene_text = fixture.claims[3]["text"].as_str().unwrap().to_owned();
        let signal_summary = format!("{signal_a_text}; {signal_b_text}");

        let opportunity = &mut fixture.result["opportunities"][0];
        opportunity["creativeHook"] = format!(
            "Start with this LIKELY / INFERRED exact-episode scene lead: {scene_text}. It is tied to the current discussion signals: {signal_summary}. The source does not verify the final outcome, timestamp, or footage location."
        ).into();
        opportunity["emotionalEditDirection"] = format!(
            "Use the current episode metadata only to bind the identity and timing: {metadata_text} Inspect supplied local footage around the provisional scene selector—{scene_text}—for an intro, montage escalation, and payoff. Confirm the exact action and emotional beat locally before editing."
        ).into();
        opportunity["evidence"] = serde_json::json!([
            {"claimId":metadata_claim_id,"role":"CONTEXT","supportsWhyNow":false,"independenceGroup":"publisher:tvmaze"},
            {"claimId":signal_a_claim_id,"role":"QUALITATIVE_SIGNAL","supportsWhyNow":true,"independenceGroup":"owner:penske-media"},
            {"claimId":signal_b_claim_id,"role":"QUALITATIVE_SIGNAL","supportsWhyNow":true,"independenceGroup":"owner:new-york-media"},
            {"claimId":scene_claim_id,"role":"CONTEXT","supportsWhyNow":false,"independenceGroup":"official:abc"}
        ]);
        opportunity["caveats"] = serde_json::json!([
            "Creative scene selection is provisional until the supplied local footage is inspected.",
            "Low confidence: no official why-now proof was verified; this uses exact current TVmaze episode metadata plus two independent title-bound discussion sources. The displayed scene is a LIKELY / INFERRED source-bound inspection lead, not a verified outcome or footage location."
        ]);

        let source = &mut fixture.result["footageRequests"][0]["requiredSources"][0];
        source["assetKind"] = "INDIVIDUAL_SCENES".into();
        source["sceneOrMoment"] = scene_text.clone().into();
        source["supportingClaimIds"] = serde_json::json!([scene_claim_id.clone()]);
        source["whyItMattersEmotionally"] = format!(
            "Evidence links this source to the intro and montage roles for Ada and Bea through this inspection target: {scene_text} Supplied local footage must confirm its emotional value before editing."
        ).into();
        source["searchQueries"] = serde_json::json!(["Example Show Ada and Bea scenes"]);

        let request = &mut fixture.result["footageRequests"][0];
        request["naturalRequest"] = serde_json::json!({
            "best":format!("Give me the Example Show scenes covering {scene_text}"),
            "alternative":null,
            "minimum":format!("The smallest useful set is the Example Show scenes covering {scene_text}"),
            "optionalImprovement":null
        });
        request["introLeads"] = serde_json::json!([{
            "introLeadId":Uuid::new_v4(),"sourceKey":"relationship_pack",
            "momentDescription":scene_text,
            "quote":null,
            "whyItMightLeadIntoMontage":format!(
                "This evidence-bound lead could provide context for Ada and Bea before the montage: {scene_text} Supplied local footage must confirm the timing and emotional handoff."
            ),
            "verificationLevel":"LIKELY_INFERRED","supportingClaimIds":[scene_claim_id]
        }]);
        request["searchQueries"] = serde_json::json!(["Example Show Ada and Bea scenes"]);
        fixture
    }

    #[test]
    fn cached_snapshot_keeps_its_score_time_but_rechecks_current_deadlines() {
        let fixture = opportunity_fixture();
        assert!(validate_cached_evidence_currentness(
            &fixture.sources,
            "2026-08-15T21:00:00Z",
            &fixture.policies,
        )
        .is_ok());
        assert!(validate_cached_evidence_currentness(
            &fixture.sources,
            "2026-08-16T08:00:01Z",
            &fixture.policies,
        )
        .is_err());
    }

    fn validate_fixture(fixture: OpportunityFixture) -> AppResult<ValidatedResearchBundle> {
        parse_bundle(fixture.result, fixture.sources, fixture.claims, fixture.run_id, &fixture.intent, &fixture.policies)
    }

    #[test]
    fn intent_rejects_unknown_media_and_duplicate_exclusions() {
        let value = serde_json::json!({
            "schemaVersion":"2.0.0","query":"romance TV","mediaKinds":["TV_EPISODE"],
            "focusTerms":[],"region":"US","freshnessDays":3,"spoilerPolicy":"CURRENT_EPISODE",
            "exclusions":["Reality","reality"],"maxResults":3
        });
        assert!(parse_intent(value).is_err());
    }

    #[test]
    fn individual_scene_copy_matches_the_worker_for_the_live_lanterns_shape() {
        // Packaged r47 job 2bd8dc31 failed at the independent Rust boundary
        // because Python had begun rendering the evidence-bound scene moment
        // while this renderer still emitted "the requested ... scenes".
        let fixture = opportunity_fixture();
        let mut requested: RequestedSource = serde_json::from_value(
            fixture.result["footageRequests"][0]["requiredSources"][0].clone(),
        )
        .unwrap();
        requested.asset_kind = "INDIVIDUAL_SCENES".into();
        requested.show_or_title = "Lanterns".into();
        requested.season_number = None;
        requested.episode_number = None;
        requested.episode_title = None;
        requested.scene_or_moment =
            "Season 1 Episode 1's ending around Hal Jordan's apparent death.".into();

        let natural = render_natural_request(&[requested], &[], &[]);
        assert_eq!(
            natural.best,
            "Give me the Lanterns scenes covering Season 1 Episode 1's ending around Hal Jordan's apparent death."
        );
        assert_eq!(
            natural.minimum,
            "The smallest useful set is the Lanterns scenes covering Season 1 Episode 1's ending around Hal Jordan's apparent death."
        );
    }

    #[test]
    fn evidence_bound_individual_scene_request_passes_the_full_rust_boundary() {
        let mut fixture = opportunity_fixture();
        let scene_claim_id = fixture.claims[3]["claimId"].clone();
        let scene_text = "Ada admits she trusts Bea after the argument.";
        let requested = &mut fixture.result["footageRequests"][0]["requiredSources"][0];
        requested["assetKind"] = "INDIVIDUAL_SCENES".into();
        requested["seasonNumber"] = serde_json::Value::Null;
        requested["episodeNumber"] = serde_json::Value::Null;
        requested["episodeTitle"] = serde_json::Value::Null;
        requested["verificationLevel"] = "LIKELY_INFERRED".into();
        requested["sourceQualitySummary"] =
            "Likely or inferred from relevant evidence; the exact moment is not verified.".into();
        requested["supportingClaimIds"] = serde_json::json!([scene_claim_id.clone()]);
        requested["quote"] = serde_json::Value::Null;
        requested["searchQueries"] =
            serde_json::json!(["Example Show Ada and Bea scenes"]);

        let request = &mut fixture.result["footageRequests"][0];
        request["naturalRequest"] = serde_json::json!({
            "best":format!("Give me the Example Show scenes covering {scene_text}"),
            "alternative":null,
            "minimum":format!("The smallest useful set is the Example Show scenes covering {scene_text}"),
            "optionalImprovement":null
        });
        request["introLeads"][0]["quote"] = serde_json::Value::Null;
        request["introLeads"][0]["verificationLevel"] = "LIKELY_INFERRED".into();
        request["introLeads"][0]["supportingClaimIds"] =
            serde_json::json!([scene_claim_id]);
        request["searchQueries"] =
            serde_json::json!(["Example Show Ada and Bea scenes"]);

        validate_fixture(fixture).unwrap();
    }

    #[test]
    fn metadata_low_scene_copy_matches_the_live_r48_worker_bundle() {
        // Packaged r48 job 0595c612 failed at opportunity_hook after Python
        // promoted an exact-episode article lead. The independent Rust boundary
        // must derive the same hook, direction, caveat, and scene request.
        validate_fixture(metadata_low_scene_fixture()).unwrap();
    }

    #[test]
    fn explicit_female_audience_requires_source_backed_evidence() {
        let mut fixture = metadata_low_scene_fixture();
        fixture.intent.focus_terms = vec!["female-centered".into()];
        fixture.result["intent"]["focusTerms"] = serde_json::json!(["female-centered"]);

        let error = validate_fixture(fixture).unwrap_err().to_string();
        assert!(error.contains("opportunity_required_focus"), "unexpected validation error: {error}");
    }

    #[test]
    fn explicit_female_audience_accepts_source_owned_title_evidence() {
        let mut fixture = metadata_low_scene_fixture();
        fixture.intent.focus_terms = vec!["female-centered".into()];
        fixture.result["intent"]["focusTerms"] = serde_json::json!(["female-centered"]);
        fixture.sources[1]["title"] = "Example Show: female-skewing fandom discussion of Ada and Bea".into();
        fixture.sources[1] = finish_source(fixture.sources[1].clone());
        fixture.claims[1] = finish_claim(fixture.claims[1].clone(), &fixture.sources[1]);

        validate_fixture(fixture).unwrap();
    }

    #[test]
    fn metadata_low_scene_request_with_official_clip_passes_full_rust_boundary() {
        // Packaged r71 job 9ee84e51 failed after successful retrieval and
        // synthesis because a deterministic fallback included an official
        // YouTube clip without the matching optional-improvement copy. Keep the
        // complete live-shaped worker bundle aligned with Rust's independent
        // evidence, policy, copy, and search-query validation.
        let mut fixture = metadata_low_scene_fixture();
        let official_source_id = Uuid::new_v4();
        let official_claim_id = Uuid::new_v4();
        let official_moment = "Official upload labeled “Episode 4 Preview”";
        let official_source = finish_source(serde_json::json!({
            "schemaVersion":"2.0.0",
            "sourceId":official_source_id,
            "provider":"youtube",
            "providerRecordId":"episode-preview",
            "sourceType":"OFFICIAL_CLIP",
            "canonicalUrl":"https://www.youtube.com/watch?v=episode-preview",
            "title":"Example Show | Episode 4 Preview | HBO Max",
            "authorOrChannel":"HBO Max",
            "sourceCreatedAt":"2026-08-15T19:30:00Z",
            "sourceUpdatedAt":null,
            "pagePublishedAt":"2026-08-15T19:30:00Z",
            "retrievedAt":"2026-08-15T20:00:00Z",
            "query":"romance TV",
            "windowStart":"2026-08-12T20:00:00Z",
            "windowEnd":"2026-08-15T20:00:00Z",
            "policyClass":"youtube-public-metadata-v1",
            "refreshDueAt":"2026-09-13T20:00:00Z",
            "purgeDueAt":"2026-09-14T20:00:00Z",
            "expiresAt":"2026-08-16T02:00:00Z",
            "deletionRequiredAt":"2026-09-14T20:00:00Z",
            "contentSha256":"",
            "independenceGroup":"official:hbo-max"
        }));
        let official_claim = finish_claim(serde_json::json!({
            "schemaVersion":"2.0.0",
            "claimId":official_claim_id,
            "sourceId":official_source_id,
            "claimKind":"OFFICIAL_CLIP",
            "excerptType":"PARAPHRASE",
            "text":"Official channel HBO Max published a title-bound Episode 4 preview.",
            "verification":"PRIMARY_VERIFIED",
            "episodeLocator":null,
            "quoteFact":null,
            "whyNowEvent":{
                "eventKind":"OFFICIAL_CLIP_RELEASE",
                "mediaIdentity":{
                    "mediaKind":"OFFICIAL_CLIP",
                    "showOrTitle":"Example Show",
                    "seasonNumber":null,
                    "episodeNumber":null,
                    "episodeTitle":null
                }
            },
            "sceneFact":{
                "showOrTitle":"Example Show",
                "description":official_moment,
                "characters":[],
                "relationshipOrTopic":null,
                "episodeLocator":null
            },
            "castFact":null,
            "eventOrReleaseAt":"2026-08-15T19:30:00Z",
            "confidence":0.95,
            "supportsWhyNow":true,
            "contentSha256":""
        }), &official_source);

        fixture.sources.push(official_source);
        fixture.claims.push(official_claim);
        let generated_ms =
            (parse_timestamp("2026-08-15T20:00:00Z").unwrap().0 / 1_000_000) as i64;
        fixture.policies.push(TrustedEvidencePolicyRecord {
            provider: "youtube".into(),
            policy_class: "youtube-public-metadata-v1".into(),
            evidence_ttl_seconds: 21_600,
            refresh_after_seconds: 2_505_600,
            purge_after_seconds: 2_592_000,
            deletion_after_seconds: Some(2_592_000),
            checked_at_ms: generated_ms - 86_400_000,
            expires_at_ms: generated_ms + 86_400_000,
        });

        fixture.result["footageRequests"][0]["optionalSources"] = serde_json::json!([{
            "requestedSourceId":Uuid::new_v4(),
            "sourceKey":"official_preview",
            "priority":1,
            "acquisitionEffort":1,
            "assetKind":"OFFICIAL_CLIP",
            "showOrTitle":"Example Show",
            "seasonNumber":null,
            "episodeNumber":null,
            "episodeTitle":null,
            "characters":[],
            "relationshipOrTopic":null,
            "sceneOrMoment":official_moment,
            "purposes":["INTRO","MONTAGE"],
            "verificationLevel":"VERIFIED",
            "sourceQualitySummary":"Verified against authoritative source evidence.",
            "supportingClaimIds":[official_claim_id],
            "quote":null,
            "whyItMattersEmotionally":format!(
                "Evidence links this source to the intro and montage roles for Example Show through this inspection target: {official_moment} Supplied local footage must confirm its emotional value before editing."
            ),
            "searchQueries":[
                "Example Show \"Episode 4 Preview\" official clip",
                "Example Show official clip"
            ],
            "replacesRequiredSourceKeys":[]
        }]);
        fixture.result["footageRequests"][0]["naturalRequest"]["optionalImprovement"] =
            "If you have it, the official Example Show clip would add another emotional option."
                .into();
        fixture.result["footageRequests"][0]["searchQueries"] = serde_json::json!([
            "Example Show Ada and Bea scenes",
            "Example Show \"Episode 4 Preview\" official clip",
            "Example Show official clip"
        ]);

        validate_fixture(fixture).unwrap();
    }

    #[test]
    fn no_opportunity_maps_to_explicit_non_manufactured_result() {
        let run_id = Uuid::new_v4();
        let intent = parse_intent(serde_json::json!({"schemaVersion":"2.0.0","query":"romance TV","mediaKinds":["TV_EPISODE"],"focusTerms":[],"region":"US","freshnessDays":3,"spoilerPolicy":"CURRENT_EPISODE","exclusions":["reality"],"maxResults":3})).unwrap();
        let result = serde_json::json!({
            "schemaVersion":"2.0.0","runId":run_id,"status":"NO_STRONG_OPPORTUNITY",
            "intent":{"schemaVersion":"2.0.0","query":"romance TV","mediaKinds":["TV_EPISODE"],"focusTerms":[],"region":"US","freshnessDays":3,"spoilerPolicy":"CURRENT_EPISODE","exclusions":["reality"],"maxResults":3},
            "opportunities":[],"footageRequests":[],"message":"No strong opportunity found under these constraints.",
            "appliedExclusions":["reality"],"warnings":["Try a wider window."],"generatedAt":"2026-08-15T20:00:00Z"
        });
        let bundle = parse_bundle(result, vec![], vec![], run_id, &intent, &[]).unwrap();
        let rendered: serde_json::Value = serde_json::from_str(&bundle.ui_view_json).unwrap();
        assert_eq!(rendered["outcome"], "NO_STRONG_OPPORTUNITY");
        assert_eq!(rendered["evidenceBreakdown"]["metadataRecords"], 0);
        assert_eq!(rendered["evidenceBreakdown"]["verifiedWhyNowRecords"], 0);
        assert_eq!(rendered["evidenceBreakdown"]["currentDiscussionSignals"], 0);
    }

    #[test]
    fn trusted_opportunity_fixture_passes_and_maps_specific_creative_copy() {
        let bundle = validate_fixture(opportunity_fixture()).unwrap();
        let rendered: serde_json::Value = serde_json::from_str(&bundle.ui_view_json).unwrap();
        assert_eq!(rendered["outcome"], "OPPORTUNITIES");
        assert!(rendered["opportunities"][0]["creativeHook"].as_str().unwrap().contains("Ada and Bea"));
        assert_eq!(rendered["freshnessCutoff"], "2026-08-12T20:00:00Z");
    }

    #[test]
    fn metadata_plus_two_independent_signals_maps_an_honest_low_confidence_card() {
        let bundle = validate_fixture(metadata_low_fixture()).unwrap();
        let rendered: serde_json::Value = serde_json::from_str(&bundle.ui_view_json).unwrap();
        let card = &rendered["opportunities"][0];
        assert_eq!(card["evidenceGate"], "LOW_CONFIDENCE");
        assert!(card["whyNow"].as_str().unwrap().contains("not an official why-now proof"));
        assert_eq!(card["footageRequest"]["requiredSources"][0]["assetKind"], "SCENE_PACK");
    }

    #[test]
    fn metadata_gate_accepts_only_exact_trusted_localized_title_binding() {
        let mut localized = metadata_low_fixture();
        localized.sources[2]["title"] = "El futuro de la serie despues del estreno".into();
        localized.sources[2]["providerRecordId"] = tvmaze_show_source_binding(
            "Example Show",
            localized.sources[2]["canonicalUrl"].as_str().unwrap(),
        ).unwrap().into();
        localized.sources[2] = finish_source(localized.sources[2].clone());
        localized.claims[2] =
            finish_claim(localized.claims[2].clone(), &localized.sources[2]);
        assert!(validate_fixture(localized).is_ok());

        let mut forged = metadata_low_fixture();
        forged.sources[2]["title"] = "El futuro de la serie despues del estreno".into();
        forged.sources[2]["providerRecordId"] = tvmaze_show_source_binding(
            "Different Show",
            forged.sources[2]["canonicalUrl"].as_str().unwrap(),
        ).unwrap().into();
        forged.sources[2] = finish_source(forged.sources[2].clone());
        forged.claims[2] = finish_claim(forged.claims[2].clone(), &forged.sources[2]);
        assert!(validate_fixture(forged).is_err());
    }

    #[test]
    fn opportunity_gate_accepts_exact_media_title_source_bindings() {
        let mut bound = opportunity_fixture();
        for (index, title) in [
            (1_usize, "Cronica localizada sin el titulo literal"),
            (2_usize, "Current streaming roundup without the title"),
        ] {
            let url = bound.sources[index]["canonicalUrl"]
                .as_str()
                .unwrap()
                .to_owned();
            bound.sources[index]["title"] = title.into();
            bound.sources[index]["providerRecordId"] =
                media_title_source_binding("Example Show", &url).unwrap().into();
            bound.sources[index] = finish_source(bound.sources[index].clone());
            bound.claims[index] =
                finish_claim(bound.claims[index].clone(), &bound.sources[index]);
        }
        assert!(validate_fixture(bound).is_ok());

        let mut forged = opportunity_fixture();
        for index in [1_usize, 2_usize] {
            let url = forged.sources[index]["canonicalUrl"]
                .as_str()
                .unwrap()
                .to_owned();
            forged.sources[index]["title"] = "Generic current roundup".into();
            forged.sources[index]["providerRecordId"] = media_title_source_binding(
                if index == 1 { "Example Show" } else { "Different Film" },
                &url,
            )
            .unwrap()
            .into();
            forged.sources[index] = finish_source(forged.sources[index].clone());
            forged.claims[index] =
                finish_claim(forged.claims[index].clone(), &forged.sources[index]);
        }
        assert!(validate_fixture(forged).is_err());
    }

    #[test]
    fn metadata_low_path_rejects_one_signal_or_a_changed_episode_locator() {
        let mut one_signal = metadata_low_fixture();
        one_signal.result["opportunities"][0]["evidence"]
            .as_array_mut().unwrap().pop();
        assert!(validate_fixture(one_signal).is_err());

        let mut changed = metadata_low_fixture();
        changed.claims[0]["episodeLocator"]["episodeNumber"] = 99.into();
        changed.claims[0] = finish_claim(changed.claims[0].clone(), &changed.sources[0]);
        assert!(validate_fixture(changed).is_err());
    }

    #[test]
    fn rejects_worker_authored_policy_or_extended_deadline() {
        let mut fixture = opportunity_fixture();
        fixture.sources[1]["expiresAt"] = "2026-08-17T08:00:00Z".into();
        assert!(validate_fixture(fixture).is_err());
    }

    #[test]
    fn rejects_content_changed_without_canonical_hash_rebinding() {
        let mut fixture = opportunity_fixture();
        fixture.sources[1]["title"] = "Unrelated title".into();
        assert!(validate_fixture(fixture).is_err());
    }

    #[test]
    fn rejects_forged_evidence_role_independence_or_gate() {
        let mut fixture = opportunity_fixture();
        fixture.result["opportunities"][0]["evidence"][1]["independenceGroup"] = "owner:new-york-media".into();
        assert!(validate_fixture(fixture).is_err());
    }

    #[test]
    fn rejects_fabricated_episode_scene_and_quote_fields() {
        let mut episode = opportunity_fixture();
        episode.result["footageRequests"][0]["requiredSources"][0]["episodeNumber"] = 9.into();
        assert!(validate_fixture(episode).is_err());

        let mut scene = opportunity_fixture();
        scene.result["footageRequests"][0]["requiredSources"][0]["sceneOrMoment"] = "Ada and Bea kiss on the beach.".into();
        assert!(validate_fixture(scene).is_err());

        let mut quote = opportunity_fixture();
        quote.result["footageRequests"][0]["requiredSources"][0]["quote"]["speaker"] = "Bea".into();
        assert!(validate_fixture(quote).is_err());
    }

    #[test]
    fn rejects_model_authored_footage_and_intro_rationales() {
        let mut source_rationale = opportunity_fixture();
        source_rationale.result["footageRequests"][0]["requiredSources"][0]
            ["whyItMattersEmotionally"] =
            "Their secret beach kiss makes this the definitive romantic payoff.".into();
        assert!(validate_fixture(source_rationale).is_err());

        let mut intro_rationale = opportunity_fixture();
        intro_rationale.result["footageRequests"][0]["introLeads"][0]
            ["whyItMightLeadIntoMontage"] =
            "Ada cries in close-up before Bea confesses, creating the perfect transition.".into();
        assert!(validate_fixture(intro_rationale).is_err());
    }

    #[test]
    fn official_upload_label_produces_specific_and_generic_search_suggestions() {
        let fixture = opportunity_fixture();
        let mut requested: RequestedSource = serde_json::from_value(
            fixture.result["footageRequests"][0]["requiredSources"][0].clone(),
        )
        .unwrap();
        requested.asset_kind = "OFFICIAL_CLIP".into();
        requested.show_or_title = "Example Show".into();
        requested.season_number = None;
        requested.episode_number = None;
        requested.episode_title = None;
        requested.characters.clear();
        requested.relationship_or_topic = None;
        requested.scene_or_moment = "Official upload labeled “A Quiet Confession”".into();
        requested.verification_level = "VERIFIED".into();
        requested.quote = None;

        assert_eq!(
            safe_search_queries(&requested),
            vec![
                "Example Show \"A Quiet Confession\" official clip".to_owned(),
                "Example Show official clip".to_owned(),
            ]
        );
    }

    #[test]
    fn inferred_episode_moment_requires_locator_on_the_moment_claim() {
        let fixture = opportunity_fixture();
        let mut requested: RequestedSource = serde_json::from_value(
            fixture.result["footageRequests"][0]["requiredSources"][0].clone(),
        )
        .unwrap();
        let parsed_sources = fixture
            .sources
            .into_iter()
            .map(serde_json::from_value::<EvidenceSource>)
            .collect::<Result<Vec<_>, _>>()
            .unwrap();
        let parsed_claims = fixture
            .claims
            .into_iter()
            .map(serde_json::from_value::<EvidenceClaim>)
            .collect::<Result<Vec<_>, _>>()
            .unwrap();
        let episode_claim = parsed_claims
            .iter()
            .find(|claim| claim.claim_kind == "WHY_NOW")
            .unwrap();
        let unlocated_discussion = parsed_claims
            .iter()
            .find(|claim| claim.claim_kind == "VIEWER_DISCUSSION")
            .unwrap();

        requested.verification_level = "LIKELY_INFERRED".into();
        requested.source_quality_summary = quality_summary("LIKELY_INFERRED").into();
        requested.scene_or_moment = unlocated_discussion.text.clone();
        requested.supporting_claim_ids =
            vec![episode_claim.claim_id, unlocated_discussion.claim_id];
        requested.quote = None;
        requested.search_queries = safe_search_queries(&requested);

        let source_index = parsed_sources
            .iter()
            .map(|source| (source.source_id, source))
            .collect::<HashMap<_, _>>();
        let claim_index = parsed_claims
            .iter()
            .map(|claim| (claim.claim_id, claim))
            .collect::<HashMap<_, _>>();

        assert!(!validate_requested_source(
            &requested,
            &source_index,
            &claim_index,
        ));
    }

    #[test]
    fn inferred_episode_quote_requires_locator_on_the_quote_claim() {
        let fixture = opportunity_fixture();
        let requested: RequestedSource = serde_json::from_value(
            fixture.result["footageRequests"][0]["requiredSources"][0].clone(),
        )
        .unwrap();
        let parsed_sources = fixture
            .sources
            .into_iter()
            .map(serde_json::from_value::<EvidenceSource>)
            .collect::<Result<Vec<_>, _>>()
            .unwrap();
        let parsed_claims = fixture
            .claims
            .into_iter()
            .map(serde_json::from_value::<EvidenceClaim>)
            .collect::<Result<Vec<_>, _>>()
            .unwrap();
        let unlocated_discussion = parsed_claims
            .iter()
            .find(|claim| claim.claim_kind == "VIEWER_DISCUSSION")
            .unwrap();
        let quote = FootageQuote {
            status: "PARAPHRASE".into(),
            text: unlocated_discussion.text.clone(),
            speaker: None,
            likely_context: None,
            claim_id: unlocated_discussion.claim_id,
        };
        let source_index = parsed_sources
            .iter()
            .map(|source| (source.source_id, source))
            .collect::<HashMap<_, _>>();
        let claim_index = parsed_claims
            .iter()
            .map(|claim| (claim.claim_id, claim))
            .collect::<HashMap<_, _>>();

        assert!(!validate_footage_quote(
            &quote,
            Some(&requested),
            &source_index,
            &claim_index,
        ));
    }

    #[test]
    fn inferred_or_unknown_episode_intro_requires_locator_on_the_moment_claim() {
        let fixture = opportunity_fixture();
        let requested: RequestedSource = serde_json::from_value(
            fixture.result["footageRequests"][0]["requiredSources"][0].clone(),
        )
        .unwrap();
        let parsed_sources = fixture
            .sources
            .into_iter()
            .map(serde_json::from_value::<EvidenceSource>)
            .collect::<Result<Vec<_>, _>>()
            .unwrap();
        let parsed_claims = fixture
            .claims
            .into_iter()
            .map(serde_json::from_value::<EvidenceClaim>)
            .collect::<Result<Vec<_>, _>>()
            .unwrap();
        let unlocated_discussion = parsed_claims
            .iter()
            .find(|claim| claim.claim_kind == "VIEWER_DISCUSSION")
            .unwrap();
        let source_index = parsed_sources
            .iter()
            .map(|source| (source.source_id, source))
            .collect::<HashMap<_, _>>();
        let claim_index = parsed_claims
            .iter()
            .map(|claim| (claim.claim_id, claim))
            .collect::<HashMap<_, _>>();
        let source_by_key = HashMap::from([(requested.source_key.as_str(), &requested)]);

        for verification_level in ["LIKELY_INFERRED", "UNKNOWN"] {
            let lead = IntroMaterialLead {
                intro_lead_id: Uuid::new_v4(),
                source_key: requested.source_key.clone(),
                moment_description: unlocated_discussion.text.clone(),
                quote: None,
                why_it_might_lead_into_montage:
                    "The discussion suggests a potentially useful contextual handoff.".into(),
                verification_level: verification_level.into(),
                supporting_claim_ids: vec![unlocated_discussion.claim_id],
            };
            assert!(!validate_intro_lead(
                &lead,
                &source_by_key,
                &source_index,
                &claim_index,
            ));
        }
    }

    #[test]
    fn rejects_non_v4_or_reused_entity_identifiers() {
        let mut fixture = opportunity_fixture();
        fixture.result["footageRequests"][0]["requiredSources"][0]["requestedSourceId"] = fixture.run_id.to_string().into();
        assert!(validate_fixture(fixture).is_err());
    }

    #[test]
    fn calendar_year_seasons_are_valid_but_remain_bounded() {
        let locator = EpisodeLocator {
            show_or_title: "Example Daily Drama".into(),
            season_number: 2026,
            episode_number: 158,
            episode_title: Some("Episode 158".into()),
        };
        assert!(episode_locator_is_valid(&locator));
        assert!(media_identity_is_valid(&MediaIdentity {
            media_kind: "TV_EPISODE".into(),
            show_or_title: locator.show_or_title.clone(),
            season_number: Some(locator.season_number),
            episode_number: Some(locator.episode_number),
            episode_title: locator.episode_title.clone(),
        }));

        let outside_bound = EpisodeLocator {
            season_number: MAX_SEASON_NUMBER + 1,
            ..locator
        };
        assert!(!episode_locator_is_valid(&outside_bound));
    }
}
