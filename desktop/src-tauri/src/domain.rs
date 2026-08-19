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
}

impl CanonicalResearchIntent {
    pub fn freshness_days(&self) -> i64 { self.freshness_days }
    pub fn max_results(&self) -> i64 { self.max_results }
    pub fn region(&self) -> &str { &self.region }
    pub fn query(&self) -> &str { &self.query }
    pub fn media_kinds(&self) -> &[String] { &self.media_kinds }
    pub fn spoiler_policy(&self) -> &str { &self.spoiler_policy }
    pub fn exclusions(&self) -> &[String] { &self.exclusions }
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
struct Opportunity {
    schema_version: String,
    opportunity_id: Uuid,
    footage_request_id: Uuid,
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
pub struct CanonicalResearchResult {
    schema_version: String,
    run_id: Uuid,
    status: String,
    intent: CanonicalResearchIntent,
    opportunities: Vec<Opportunity>,
    footage_requests: Vec<FootageRequest>,
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
        query_summary: String,
        freshness_cutoff: String,
        opportunities: Vec<OpportunityView>,
    },
    NoStrongOpportunity {
        query_summary: String,
        freshness_cutoff: String,
        explanation: String,
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
    {
        return Err(AppError::Worker("canonical research intent failed domain validation".to_owned()));
    }
    Ok(())
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
        let sort_key = (-opportunity.score.total, opportunity.title.to_lowercase());
        if prior_sort_key.as_ref().is_some_and(|prior| prior > &sort_key) {
            return invalid_bundle_at("opportunity_sort");
        }
        prior_sort_key = Some(sort_key);
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
    {
        return Err("opportunity_header");
    }
    if !validate_footage_request(request, opportunity, intent, sources, claims, all_ids) {
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
        && validate_opportunity_request_pair(opportunity, request, intent)
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
) -> bool {
    let all = request.required_sources.iter().chain(&request.optional_sources).chain(&request.alternative_sources).collect::<Vec<_>>();
    if all.iter().any(|source| !same_text(&source.show_or_title, &opportunity.media_identity.show_or_title)) {
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
            query_summary: result.intent.query.clone(),
            freshness_cutoff: freshness_cutoff(result)?,
            explanation: result.message.clone(),
            evidence_reviewed: sources.len(),
            evidence_breakdown,
            suggestions: result.warnings.clone(),
        });
    }
    let request_by_id = result.footage_requests.iter().map(|request| (request.footage_request_id, request)).collect::<HashMap<_, _>>();
    let mut output = Vec::with_capacity(result.opportunities.len());
    for (index, opportunity) in result.opportunities.iter().enumerate() {
        let request = request_by_id.get(&opportunity.footage_request_id)
            .ok_or_else(|| AppError::Worker("canonical opportunity lost its footage request".to_owned()))?;
        let evidence = map_evidence(opportunity.evidence.iter().map(|reference| reference.claim_id), &claim_by_id, &source_by_id)?;
        let footage = map_footage(request, &claim_by_id, &source_by_id)?;
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
            evidence,
            footage_request: footage,
            caveats: opportunity.caveats.clone(),
        });
    }
    Ok(ResearchResultView::Opportunities {
        query_summary: result.intent.query.clone(),
        freshness_cutoff: freshness_cutoff(result)?,
        opportunities: output,
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
