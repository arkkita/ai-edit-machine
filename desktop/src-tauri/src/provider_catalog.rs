use std::collections::{BTreeMap, HashSet};

use rusqlite::{params, OptionalExtension, TransactionBehavior};
use serde::Deserialize;
use uuid::Uuid;

use crate::cost::{ceil_cost, CacheStatus, CostComponentPlan, CostKind, PlannedCallInput, ProviderConfig};
use crate::database::Database;
use crate::domain::CanonicalResearchIntent;
use crate::{AppError, AppResult};

const CATALOG_JSON: &str = include_str!("../resources/provider-catalog.json");
const RESEARCH_AUDIT: &str = include_str!("../../../docs/RESEARCH_AUDIT.md");
const API_COSTS: &str = include_str!("../../../docs/API_COSTS.md");
const CATALOG_SCHEMA: &str = "1.0.0";
const CATALOG_REGISTRY: &str = "m1-2026-08-19-r73";
const OPENAI_MODEL: &str = "gpt-5.6-luna";
const OPENAI_PRICE_CARD: &str = "7f771320-9944-465d-98a1-924ed837fe34";
const TVMAZE_CAST_SHOW_LIMIT: i64 = 8;
#[cfg(debug_assertions)]
pub(crate) const M1_PROVIDER_DEBUG_MODE: &str = "M1_PROVIDER_ONE_SHOT";
#[cfg(debug_assertions)]
pub(crate) const M1_PROVIDER_DEBUG_RUN_SCOPE: &str = "m1-provider-debug-live-2026-08-19-v1";
#[cfg(debug_assertions)]
pub(crate) const M1_PROVIDER_DEBUG_MAX_REQUESTS: i64 = 8;
#[cfg(debug_assertions)]
pub(crate) const M1_PROVIDER_DEBUG_MAX_TOOL_CALLS: i64 = 1;
#[cfg(debug_assertions)]
pub(crate) const M1_PROVIDER_DEBUG_MAX_INPUT_TOKENS: i64 = 198_000;
#[cfg(debug_assertions)]
pub(crate) const M1_PROVIDER_DEBUG_MAX_OUTPUT_TOKENS: i64 = 300;
#[cfg(debug_assertions)]
pub(crate) const M1_PROVIDER_DEBUG_RESERVATION_MICRO_USD: i64 = 49_960;
#[cfg(debug_assertions)]
pub(crate) const M1_PROVIDER_DEBUG_HARD_CAP_MICRO_USD: i64 = 50_000;
pub const BUNDLE_CACHE_NAMESPACE: &str = "research-bundle-v2";
pub const BUNDLE_CACHE_SCHEMA: &str = "research-result-bundle/2.0.0";
pub const BUNDLE_CACHE_MODEL: &str = "openai:gpt-5.6-luna|catalog:m1-2026-08-19-r73";
pub const BUNDLE_CACHE_PROMPT: &str = "m1-research-2026-08-19-r69+catalog:m1-2026-08-19-r73";
pub const BUNDLE_CACHE_POLICY: &str = "openai-web-evidence-v1";

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct Catalog {
    schema_version: String,
    registry_version: String,
    review_artifact_path: String,
    review_artifact_sha256: String,
    policies: Vec<CatalogPolicy>,
    price_cards: Vec<CatalogPriceCard>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct CatalogPolicy {
    provider: String,
    enabled: bool,
    kill_switch_reason: Option<String>,
    policy_class: String,
    evidence_ttl_seconds: i64,
    refresh_after_seconds: i64,
    purge_after_seconds: i64,
    deletion_after_seconds: Option<i64>,
    max_requests_per_run: i64,
    max_tool_calls_per_run: i64,
    max_input_tokens_per_run: i64,
    max_output_tokens_per_run: i64,
    retention_summary: String,
    data_use_summary: String,
    no_storage_mode: String,
    privacy_mode: String,
    provider_config: serde_json::Value,
    checked_at_unix_ms: i64,
    expires_at_unix_ms: i64,
    source_url: String,
    source_review_artifact_path: String,
    source_review_artifact_sha256: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct CatalogPriceCard {
    id: Uuid,
    provider: String,
    model: String,
    source_url: String,
    unit_prices: BTreeMap<String, i64>,
    effective_at_unix_ms: i64,
    checked_at_unix_ms: i64,
    expires_at_unix_ms: i64,
    source_review_artifact_path: String,
    source_review_artifact_sha256: String,
}

#[derive(Debug)]
struct PolicySnapshot {
    provider: String,
    policy_class: String,
    evidence_ttl_seconds: i64,
    refresh_after_seconds: i64,
    purge_after_seconds: i64,
    deletion_after_seconds: Option<i64>,
    retention_summary: String,
    data_use_summary: String,
    no_storage_mode: String,
    privacy_mode: String,
    provider_config: ProviderConfig,
}

pub fn install(database: &mut Database, now_ms: i64) -> AppResult<()> {
    let value = crate::worker::protocol::parse_strict_json_bytes(CATALOG_JSON.as_bytes())?;
    let catalog: Catalog = serde_json::from_value(value)
        .map_err(|_| AppError::DatabaseInvariant("embedded provider catalog violates its strict schema".to_owned()))?;
    validate_catalog(&catalog, now_ms)?;
    let transaction = database.connection_mut().transaction_with_behavior(TransactionBehavior::Immediate)?;
    for policy in &catalog.policies {
        let provider_config_json = serde_json::to_string(&policy.provider_config)?;
        transaction.execute(
            "INSERT INTO provider_policy(provider, enabled, kill_switch_reason, policy_class, evidence_ttl_seconds, refresh_after_seconds, purge_after_seconds, deletion_after_seconds, max_requests_per_run, max_tool_calls_per_run, max_input_tokens_per_run, max_output_tokens_per_run, retention_summary, data_use_summary, no_storage_mode, privacy_mode, provider_config_json, registry_version, source_url, review_artifact_path, review_artifact_sha256, checked_at_ms, expires_at_ms)
             VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16,?17,?18,?19,?20,?21,?22,?23)
             ON CONFLICT(provider) DO UPDATE SET enabled=excluded.enabled, kill_switch_reason=excluded.kill_switch_reason, policy_class=excluded.policy_class, evidence_ttl_seconds=excluded.evidence_ttl_seconds, refresh_after_seconds=excluded.refresh_after_seconds, purge_after_seconds=excluded.purge_after_seconds, deletion_after_seconds=excluded.deletion_after_seconds, max_requests_per_run=excluded.max_requests_per_run, max_tool_calls_per_run=excluded.max_tool_calls_per_run, max_input_tokens_per_run=excluded.max_input_tokens_per_run, max_output_tokens_per_run=excluded.max_output_tokens_per_run, retention_summary=excluded.retention_summary, data_use_summary=excluded.data_use_summary, no_storage_mode=excluded.no_storage_mode, privacy_mode=excluded.privacy_mode, provider_config_json=excluded.provider_config_json, registry_version=excluded.registry_version, source_url=excluded.source_url, review_artifact_path=excluded.review_artifact_path, review_artifact_sha256=excluded.review_artifact_sha256, checked_at_ms=excluded.checked_at_ms, expires_at_ms=excluded.expires_at_ms",
            params![policy.provider, policy.enabled, policy.kill_switch_reason, policy.policy_class,
                policy.evidence_ttl_seconds, policy.refresh_after_seconds, policy.purge_after_seconds,
                policy.deletion_after_seconds, policy.max_requests_per_run, policy.max_tool_calls_per_run,
                policy.max_input_tokens_per_run, policy.max_output_tokens_per_run, policy.retention_summary, policy.data_use_summary,
                policy.no_storage_mode, policy.privacy_mode, provider_config_json, catalog.registry_version,
                policy.source_url, policy.source_review_artifact_path, policy.source_review_artifact_sha256, policy.checked_at_unix_ms,
                policy.expires_at_unix_ms],
        )?;
    }
    for card in &catalog.price_cards {
        let prices = serde_json::to_string(&card.unit_prices)?;
        let inserted = transaction.execute(
            "INSERT INTO price_card(id, provider, model, source_url, currency, unit_prices_json, effective_at_ms, checked_at_ms, expires_at_ms, review_artifact_path, review_artifact_sha256)
             VALUES (?1,?2,?3,?4,'USD',?5,?6,?7,?8,?9,?10) ON CONFLICT(id) DO NOTHING",
            params![card.id.to_string(), card.provider, card.model, card.source_url, prices,
                card.effective_at_unix_ms, card.checked_at_unix_ms, card.expires_at_unix_ms,
                card.source_review_artifact_path, card.source_review_artifact_sha256],
        )?;
        if inserted == 0 {
            let exact = transaction.query_row(
                "SELECT 1 FROM price_card WHERE id=?1 AND provider=?2 AND model=?3 AND source_url=?4 AND unit_prices_json=?5 AND effective_at_ms=?6 AND checked_at_ms=?7 AND expires_at_ms=?8 AND review_artifact_path=?9 AND review_artifact_sha256=?10",
                params![card.id.to_string(), card.provider, card.model, card.source_url, prices,
                    card.effective_at_unix_ms, card.checked_at_unix_ms, card.expires_at_unix_ms,
                    card.source_review_artifact_path, card.source_review_artifact_sha256],
                |_| Ok(()),
            ).optional()?.is_some();
            if !exact {
                return Err(AppError::DatabaseInvariant("embedded immutable price-card identity was reused".to_owned()));
            }
        }
    }
    transaction.commit()?;
    Ok(())
}

pub fn build_plan(
    database: &Database,
    intent: &CanonicalResearchIntent,
    input_sha256: &str,
    now_ms: i64,
) -> AppResult<Vec<PlannedCallInput>> {
    let openai = policy(database, "openai", now_ms)?;
    if let Some(binding) = database.whole_bundle_cache_binding(input_sha256, now_ms)? {
        let call = PlannedCallInput {
            provider: "openai".to_owned(), operation: "research.synthesize".to_owned(),
            configured_model: Some(OPENAI_MODEL.to_owned()), resolved_model: None, price_card_id: None,
            reservation_micro_usd: 0, cost_kind: CostKind::LocalCache, cache_status: CacheStatus::Hit,
            cache_namespace: Some(BUNDLE_CACHE_NAMESPACE.to_owned()), cache_key: Some(input_sha256.to_owned()),
            cache_input_sha256: Some(input_sha256.to_owned()), cache_output_sha256: Some(binding.output_sha256),
            cache_schema_version: Some(BUNDLE_CACHE_SCHEMA.to_owned()), cache_model_version: Some(BUNDLE_CACHE_MODEL.to_owned()),
            cache_prompt_version: Some(BUNDLE_CACHE_PROMPT.to_owned()), cache_policy_class: Some(BUNDLE_CACHE_POLICY.to_owned()),
            retention_summary: openai.retention_summary.clone(), data_use_summary: openai.data_use_summary.clone(),
            no_storage_mode: openai.no_storage_mode.clone(), privacy_mode: openai.privacy_mode.clone(),
            policy_class: openai.policy_class.clone(), evidence_ttl_seconds: openai.evidence_ttl_seconds,
            refresh_after_seconds: openai.refresh_after_seconds, purge_after_seconds: openai.purge_after_seconds,
            deletion_after_seconds: openai.deletion_after_seconds,
            cheaper_alternative: "Validated local whole-result cache replay; no cloud call.".to_owned(),
            requires_live_call: false, max_requests: 0, max_tool_calls: 0, max_input_tokens: 0, max_output_tokens: 0,
            allow_one_repair: false, provider_config: ProviderConfig::OpenaiSynthesis, components: vec![],
        };
        call.validate_shape()?;
        return Ok(vec![call]);
    }
    let tvmaze = policy(database, "tvmaze", now_ms)?;
    let youtube = policy(database, "youtube", now_ms)?;
    let (openai, resolved_model, price_id, prices) =
        openai_paid_binding(database, openai, now_ms)?;

    let uses_tv_metadata = intent
        .media_kinds()
        .iter()
        .any(|kind| matches!(kind.as_str(), "TV_EPISODE" | "TV_SERIES"));
    let mut calls = Vec::new();
    if uses_tv_metadata {
        let tv_requests = tvmaze_request_ceiling(intent.freshness_days());
        calls.push(free_call(
            &tvmaze,
            "research.metadata",
            tv_requests,
            "Use a fresh valid local TVmaze cache entry when available.",
        )?);
    }
    calls.push(paid_call(
        &openai,
        &resolved_model,
        price_id,
        "research.web_verify",
        match &openai.provider_config {
            ProviderConfig::OpenaiWeb { .. } => openai.provider_config.clone(),
            _ => return Err(AppError::DatabaseInvariant("OpenAI official-host registry is invalid".to_owned())),
        },
        40,
        14,
        170_000,
        5_333,
        false,
        vec![
            component("input_primary", 170_000, 1_000_000, "INPUT_TOKEN", price(&prices, "input_primary")?)?,
            component("cached_input_primary", 0, 1_000_000, "CACHED_INPUT_TOKEN", price(&prices, "cached_input_primary")?)?,
            component("output_primary", 5_333, 1_000_000, "OUTPUT_TOKEN", price(&prices, "output_primary")?)?,
            component("web_search_tool", 14, 1, "TOOL_CALL", price(&prices, "web_search_tool")?)?,
        ],
        "TVmaze plus official pages can still yield a lower-cost metadata-only result.",
    )?);
    calls.push(free_call(
        &youtube,
        "research.youtube",
        intent.max_results().min(5),
        "Skip official-video discovery and keep the validated research evidence only.",
    )?);
    calls.push(paid_call(
        &openai,
        &resolved_model,
        price_id,
        "research.synthesize",
        ProviderConfig::OpenaiSynthesis,
        2,
        0,
        60_000,
        16_000,
        true,
        vec![
            component("input_synthesis", 30_000, 1_000_000, "INPUT_TOKEN", price(&prices, "input_synthesis")?)?,
            component("cached_input_synthesis", 0, 1_000_000, "CACHED_INPUT_TOKEN", price(&prices, "cached_input_synthesis")?)?,
            component("output_synthesis", 8_000, 1_000_000, "OUTPUT_TOKEN", price(&prices, "output_synthesis")?)?,
            component("repair_reserve", 1, 1, "RESERVATION_ONLY", price(&prices, "repair_reserve")?)?,
        ],
        "Skip synthesis and return normalized evidence only.",
    )?);
    Ok(calls)
}

/// The one verifier-only diagnostic approved on 2026-08-15 was consumed under
/// its immutable historical price card. It is deliberately impossible to
/// recreate from the current catalog without a new explicit authorization.
pub fn build_openai_verifier_diagnostic_plan(
    _database: &Database,
    _now_ms: i64,
) -> AppResult<Vec<PlannedCallInput>> {
    Err(AppError::Budget(
        "the approved 2026-08-15 verifier-only diagnostic authorization is exhausted"
            .to_owned(),
    ))
}

/// Build the one fixed development-only provider probe authorized on
/// 2026-08-19. Release builds do not contain this function or its narrower
/// provider-configuration exception.
#[cfg(debug_assertions)]
pub fn build_m1_provider_debug_plan(database: &Database, now_ms: i64) -> AppResult<Vec<PlannedCallInput>> {
    let openai = policy(database, "openai", now_ms)?;
    let (openai, resolved_model, price_id, prices) = openai_paid_binding(database, openai, now_ms)?;
    let config = match openai.provider_config.clone() {
        ProviderConfig::OpenaiWeb {
            registry_version, official_hosts, search_context_size,
            request_body_max_input_tokens, ..
        } => ProviderConfig::OpenaiWeb {
            registry_version, official_hosts, search_context_size,
            request_body_max_input_tokens,
            request_max_tool_calls: M1_PROVIDER_DEBUG_MAX_TOOL_CALLS,
        },
        _ => return Err(AppError::DatabaseInvariant("OpenAI provider-debug registry is invalid".to_owned())),
    };
    let call = paid_call(
        &openai, &resolved_model, price_id, "research.web_verify", config,
        M1_PROVIDER_DEBUG_MAX_REQUESTS, M1_PROVIDER_DEBUG_MAX_TOOL_CALLS,
        M1_PROVIDER_DEBUG_MAX_INPUT_TOKENS, M1_PROVIDER_DEBUG_MAX_OUTPUT_TOKENS,
        false,
        vec![
            component("input_primary", M1_PROVIDER_DEBUG_MAX_INPUT_TOKENS, 1_000_000, "INPUT_TOKEN", price(&prices, "input_primary")?)?,
            component("cached_input_primary", 0, 1_000_000, "CACHED_INPUT_TOKEN", price(&prices, "cached_input_primary")?)?,
            component("output_primary", M1_PROVIDER_DEBUG_MAX_OUTPUT_TOKENS, 1_000_000, "OUTPUT_TOKEN", price(&prices, "output_primary")?)?,
            component("web_search_tool", M1_PROVIDER_DEBUG_MAX_TOOL_CALLS, 1, "TOOL_CALL", price(&prices, "web_search_tool")?)?,
        ],
        "Replay the sanitized fixture locally; this probe is development-only.",
    )?;
    if call.reservation_micro_usd != M1_PROVIDER_DEBUG_RESERVATION_MICRO_USD
        || call.reservation_micro_usd > M1_PROVIDER_DEBUG_HARD_CAP_MICRO_USD
    {
        return Err(AppError::Budget("provider-debug price card no longer fits the $0.05 hard cap".to_owned()));
    }
    Ok(vec![call])
}

#[cfg(debug_assertions)]
pub(crate) fn is_exact_m1_provider_debug_call(call: &PlannedCallInput, trusted: &ProviderConfig) -> bool {
    let (
        ProviderConfig::OpenaiWeb {
            registry_version: call_registry, official_hosts: call_hosts,
            search_context_size: call_context, request_body_max_input_tokens: call_body_input,
            request_max_tool_calls: call_request_tools,
        },
        ProviderConfig::OpenaiWeb {
            registry_version: trusted_registry, official_hosts: trusted_hosts,
            search_context_size: trusted_context, request_body_max_input_tokens: trusted_body_input,
            request_max_tool_calls: trusted_request_tools,
        },
    ) = (&call.provider_config, trusted) else { return false; };
    call.provider == "openai"
        && call.operation == "research.web_verify"
        && call.configured_model.as_deref() == Some(OPENAI_MODEL)
        && call.resolved_model.as_deref() == Some(OPENAI_MODEL)
        && call.reservation_micro_usd == M1_PROVIDER_DEBUG_RESERVATION_MICRO_USD
        && call.max_requests == M1_PROVIDER_DEBUG_MAX_REQUESTS
        && call.max_tool_calls == M1_PROVIDER_DEBUG_MAX_TOOL_CALLS
        && call.max_input_tokens == M1_PROVIDER_DEBUG_MAX_INPUT_TOKENS
        && call.max_output_tokens == M1_PROVIDER_DEBUG_MAX_OUTPUT_TOKENS
        && !call.allow_one_repair
        && call_registry == trusted_registry && call_hosts == trusted_hosts
        && call_context == trusted_context && call_body_input == trusted_body_input
        && *call_request_tools == M1_PROVIDER_DEBUG_MAX_TOOL_CALLS
        && *trusted_request_tools >= *call_request_tools
}

fn tvmaze_request_ceiling(freshness_days: i64) -> i64 {
    // TVmaze schedules are calendar-day endpoints, but canonical freshness
    // is a rolling duration. Include the oldest partial calendar day; Python
    // filters exact airstamps against the rolling cutoff. Eight cast lookups
    // keep the fourteen-day maximum within the reviewed 40-request ceiling.
    ((freshness_days.min(14) + 1) * 2 + TVMAZE_CAST_SHOW_LIMIT).min(40)
}

fn openai_paid_binding(
    database: &Database,
    openai: PolicySnapshot,
    now_ms: i64,
) -> AppResult<(PolicySnapshot, String, Uuid, BTreeMap<String, i64>)> {
    let preflight = database.model_preflight("openai", OPENAI_MODEL, now_ms)?;
    if preflight.retention_mode != openai.retention_summary
        || preflight.data_use_mode != openai.data_use_summary
        || preflight.no_storage_mode != openai.no_storage_mode
        || preflight.privacy_mode != openai.privacy_mode
    {
        return Err(AppError::Security(
            "OpenAI preflight disclosures do not match the reviewed provider policy".to_owned(),
        ));
    }
    let price_id = Uuid::parse_str(OPENAI_PRICE_CARD)
        .map_err(|_| AppError::DatabaseInvariant("embedded price-card UUID is invalid".to_owned()))?;
    let (priced_model, prices): (String, String) = database
        .connection()
        .query_row(
            "SELECT model, unit_prices_json FROM price_card WHERE id=?1 AND effective_at_ms<=?2 AND checked_at_ms<=?2 AND expires_at_ms>=?2",
            params![price_id.to_string(), now_ms],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )
        .optional()?
        .ok_or_else(|| AppError::Budget("fresh trusted OpenAI price card is unavailable".to_owned()))?;
    if priced_model != preflight.resolved_model {
        return Err(AppError::Budget(
            "resolved OpenAI model is not bound to the trusted price card".to_owned(),
        ));
    }
    let prices: BTreeMap<String, i64> = serde_json::from_str(&prices)
        .map_err(|_| AppError::DatabaseInvariant("trusted price card is invalid".to_owned()))?;
    Ok((openai, preflight.resolved_model, price_id, prices))
}

fn validate_catalog(catalog: &Catalog, now_ms: i64) -> AppResult<()> {
    let research_hash = crate::security::sha256_hex(RESEARCH_AUDIT.as_bytes());
    let costs_hash = crate::security::sha256_hex(API_COSTS.as_bytes());
    if catalog.schema_version != CATALOG_SCHEMA || catalog.registry_version != CATALOG_REGISTRY
        || catalog.review_artifact_path != "docs/RESEARCH_AUDIT.md"
        || catalog.review_artifact_sha256 != research_hash || catalog.policies.is_empty()
    {
        return Err(AppError::DatabaseInvariant("embedded provider catalog identity is invalid".to_owned()));
    }
    let mut providers = HashSet::new();
    for policy in &catalog.policies {
        if !providers.insert(policy.provider.as_str())
            || !matches!(policy.provider.as_str(), "tvmaze" | "openai" | "youtube" | "xai")
            || policy.policy_class.trim().is_empty()
            || policy.evidence_ttl_seconds <= 0 || policy.refresh_after_seconds <= 0
            || policy.purge_after_seconds < policy.evidence_ttl_seconds
            || policy.deletion_after_seconds.is_some_and(|value| value < policy.evidence_ttl_seconds)
            || [policy.max_requests_per_run, policy.max_tool_calls_per_run, policy.max_input_tokens_per_run, policy.max_output_tokens_per_run].iter().any(|value| *value < 0)
            || [policy.retention_summary.as_str(), policy.data_use_summary.as_str(), policy.no_storage_mode.as_str(), policy.privacy_mode.as_str(), policy.source_url.as_str()].iter().any(|value| value.trim().is_empty())
            || policy.source_review_artifact_path != "docs/RESEARCH_AUDIT.md"
            || policy.source_review_artifact_sha256 != research_hash
            || policy.checked_at_unix_ms <= 0 || policy.checked_at_unix_ms > now_ms
            || policy.expires_at_unix_ms <= policy.checked_at_unix_ms
            || (policy.enabled && policy.kill_switch_reason.is_some())
            || (!policy.enabled && policy.kill_switch_reason.as_deref().is_none_or(str::is_empty))
        {
            return Err(AppError::DatabaseInvariant("embedded provider policy is invalid".to_owned()));
        }
        if policy.enabled {
            let config: ProviderConfig = serde_json::from_value(policy.provider_config.clone())
                .map_err(|_| AppError::DatabaseInvariant("enabled provider configuration is invalid".to_owned()))?;
            let matches = matches!((&*policy.provider, config),
                ("tvmaze", ProviderConfig::Tvmaze) | ("openai", ProviderConfig::OpenaiWeb { .. })
                    | ("youtube", ProviderConfig::YoutubeOfficialChannels { .. }) | ("xai", ProviderConfig::XaiSearch { .. }));
            if !matches { return Err(AppError::DatabaseInvariant("provider configuration identity is invalid".to_owned())); }
        }
    }
    let mut cards = HashSet::new();
    for card in &catalog.price_cards {
        if !cards.insert(card.id) || card.provider.trim().is_empty() || card.model.trim().is_empty()
            || card.source_review_artifact_path != "docs/API_COSTS.md"
            || card.source_review_artifact_sha256 != costs_hash || card.unit_prices.is_empty()
            || card.unit_prices.values().any(|value| *value < 0)
            || card.effective_at_unix_ms > now_ms || card.checked_at_unix_ms > now_ms
            || card.expires_at_unix_ms <= card.checked_at_unix_ms
        {
            return Err(AppError::DatabaseInvariant("embedded price card is invalid".to_owned()));
        }
    }
    Ok(())
}

fn policy(database: &Database, provider: &str, now_ms: i64) -> AppResult<PolicySnapshot> {
    database.connection().query_row(
        "SELECT provider, policy_class, evidence_ttl_seconds, refresh_after_seconds, purge_after_seconds, deletion_after_seconds, retention_summary, data_use_summary, no_storage_mode, privacy_mode, provider_config_json
         FROM provider_policy WHERE provider=?1 AND enabled=1 AND kill_switch_reason IS NULL AND checked_at_ms<=?2 AND expires_at_ms>=?2",
        params![provider, now_ms],
        |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?, row.get::<_, i64>(2)?,
            row.get::<_, i64>(3)?, row.get::<_, i64>(4)?, row.get::<_, Option<i64>>(5)?,
            row.get::<_, String>(6)?, row.get::<_, String>(7)?, row.get::<_, String>(8)?,
            row.get::<_, String>(9)?, row.get::<_, String>(10)?)),
    ).optional()?.map(|row| -> AppResult<PolicySnapshot> { Ok(PolicySnapshot {
        provider: row.0,
        policy_class: row.1,
        evidence_ttl_seconds: row.2,
        refresh_after_seconds: row.3,
        purge_after_seconds: row.4,
        deletion_after_seconds: row.5,
        retention_summary: row.6,
        data_use_summary: row.7,
        no_storage_mode: row.8,
        privacy_mode: row.9,
        provider_config: serde_json::from_str(&row.10)
            .map_err(|_| AppError::DatabaseInvariant("trusted provider configuration is invalid".to_owned()))?,
    }) }).transpose()?.ok_or_else(|| AppError::Provider(format!("{provider} policy is disabled or stale")))
}

fn free_call(
    policy: &PolicySnapshot,
    operation: &str,
    max_requests: i64,
    cheaper_alternative: &str,
) -> AppResult<PlannedCallInput> {
    let config = policy.provider_config.clone();
    let call = PlannedCallInput {
        provider: policy.provider.clone(), operation: operation.to_owned(),
        configured_model: None, resolved_model: None, price_card_id: None,
        reservation_micro_usd: 0, cost_kind: CostKind::FreeMetadata,
        cache_status: CacheStatus::Miss, cache_namespace: None, cache_key: None,
        cache_input_sha256: None, cache_output_sha256: None, cache_schema_version: None,
        cache_model_version: None, cache_prompt_version: None, cache_policy_class: None,
        retention_summary: policy.retention_summary.clone(), data_use_summary: policy.data_use_summary.clone(),
        no_storage_mode: policy.no_storage_mode.clone(), privacy_mode: policy.privacy_mode.clone(),
        policy_class: policy.policy_class.clone(), evidence_ttl_seconds: policy.evidence_ttl_seconds,
        refresh_after_seconds: policy.refresh_after_seconds, purge_after_seconds: policy.purge_after_seconds,
        deletion_after_seconds: policy.deletion_after_seconds,
        cheaper_alternative: cheaper_alternative.to_owned(),
        requires_live_call: true, max_requests, max_tool_calls: 0, max_input_tokens: 0, max_output_tokens: 0,
        allow_one_repair: false, provider_config: config, components: vec![],
    };
    call.validate_shape()?;
    Ok(call)
}

#[allow(clippy::too_many_arguments)]
fn paid_call(
    policy: &PolicySnapshot, resolved_model: &str, price_card_id: Uuid, operation: &str,
    provider_config: ProviderConfig, max_requests: i64, max_tool_calls: i64,
    max_input_tokens: i64, max_output_tokens: i64, allow_one_repair: bool, components: Vec<CostComponentPlan>,
    cheaper_alternative: &str,
) -> AppResult<PlannedCallInput> {
    let reservation_micro_usd = components.iter().try_fold(0_i64, |total, value| {
        total.checked_add(value.maximum_micro_usd).ok_or_else(|| AppError::Budget("provider reservation overflow".to_owned()))
    })?;
    let call = PlannedCallInput {
        provider: policy.provider.clone(), operation: operation.to_owned(),
        configured_model: Some(OPENAI_MODEL.to_owned()), resolved_model: Some(resolved_model.to_owned()),
        price_card_id: Some(price_card_id), reservation_micro_usd, cost_kind: CostKind::PaidCloud,
        cache_status: CacheStatus::Miss, cache_namespace: None, cache_key: None,
        cache_input_sha256: None, cache_output_sha256: None, cache_schema_version: None,
        cache_model_version: None, cache_prompt_version: None, cache_policy_class: None,
        retention_summary: policy.retention_summary.clone(), data_use_summary: policy.data_use_summary.clone(),
        no_storage_mode: policy.no_storage_mode.clone(), privacy_mode: policy.privacy_mode.clone(),
        policy_class: policy.policy_class.clone(), evidence_ttl_seconds: policy.evidence_ttl_seconds,
        refresh_after_seconds: policy.refresh_after_seconds, purge_after_seconds: policy.purge_after_seconds,
        deletion_after_seconds: policy.deletion_after_seconds,
        cheaper_alternative: cheaper_alternative.to_owned(), requires_live_call: true,
        max_requests, max_tool_calls, max_input_tokens, max_output_tokens, allow_one_repair, provider_config, components,
    };
    call.validate_shape()?;
    Ok(call)
}

fn component(category: &str, quantity: i64, denominator: i64, unit: &str, unit_price: i64) -> AppResult<CostComponentPlan> {
    Ok(CostComponentPlan {
        category: category.to_owned(), quantity_numerator: quantity, quantity_denominator: denominator,
        unit: unit.to_owned(), unit_price_micro_usd: unit_price,
        maximum_micro_usd: ceil_cost(quantity, denominator, unit_price)?,
    })
}

fn price(prices: &BTreeMap<String, i64>, category: &str) -> AppResult<i64> {
    prices.get(category).copied().ok_or_else(|| AppError::Budget(format!("trusted price card lacks {category}")))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::database::repositories::ModelPreflightInput;

    #[test]
    fn embedded_catalog_is_strict_and_not_future_dated() {
        let value = crate::worker::protocol::parse_strict_json_bytes(CATALOG_JSON.as_bytes()).unwrap();
        let catalog: Catalog = serde_json::from_value(value).unwrap();
        validate_catalog(&catalog, 1_787_140_000_000).unwrap();
        assert!(validate_catalog(&catalog, catalog.policies[0].checked_at_unix_ms - 1).is_err());
    }

    #[test]
    fn catalog_upgrade_preserves_the_prior_immutable_price_card() {
        let mut database = Database::open_in_memory().unwrap();
        let prior_id = "0f701e00-9821-4244-ab36-2eba5b2999c6";
        database.connection_mut().execute(
            "INSERT INTO price_card(id, provider, model, source_url, currency, unit_prices_json, effective_at_ms, checked_at_ms, expires_at_ms, review_artifact_path, review_artifact_sha256)
             VALUES (?1, 'openai', 'gpt-5.6-luna', 'https://developers.openai.com/api/docs/pricing', 'USD', '{}', 1, 1, 2, 'docs/API_COSTS.md', ?2)",
            params![prior_id, "3328e5c570bcc5c956e73fedcacb68226453fc433b60c605d43a903ac722e9e0"],
        ).unwrap();

        install(&mut database, 1_787_140_000_000).unwrap();

        let prior_count: i64 = database.connection().query_row(
            "SELECT COUNT(*) FROM price_card WHERE id=?1",
            [prior_id],
            |row| row.get(0),
        ).unwrap();
        let current_count: i64 = database.connection().query_row(
            "SELECT COUNT(*) FROM price_card WHERE id=?1",
            [OPENAI_PRICE_CARD],
            |row| row.get(0),
        ).unwrap();
        assert_eq!(prior_count, 1);
        assert_eq!(current_count, 1);
        assert_ne!(prior_id, OPENAI_PRICE_CARD);
    }

    #[test]
    fn consumed_verifier_diagnostic_authorization_cannot_be_reused() {
        let now_ms = 1_787_140_000_000;
        let mut database = Database::open_in_memory().unwrap();
        install(&mut database, now_ms).unwrap();
        database
            .upsert_model_preflight(&ModelPreflightInput {
                provider: "openai",
                configured_model: OPENAI_MODEL,
                resolved_model: Some(OPENAI_MODEL),
                available: true,
                retention_mode: "up to 30 days abuse monitoring unless approved controls apply",
                data_use_mode: "API data is not used for training by default",
                no_storage_mode: "store=false for Responses; stronger ZDR is not assumed",
                privacy_mode: "store_false",
                checked_at_ms: now_ms,
                expires_at_ms: now_ms + 3_600_000,
            })
            .unwrap();

        let error = build_openai_verifier_diagnostic_plan(&database, now_ms)
            .expect_err("the consumed diagnostic capability must fail closed");
        assert!(error.to_string().contains("authorization is exhausted"));
    }

    #[test]
    fn development_provider_debug_plan_is_exactly_one_call_under_five_cents() {
        let now_ms = 1_787_140_000_000;
        let mut database = Database::open_in_memory().unwrap();
        install(&mut database, now_ms).unwrap();
        database.upsert_model_preflight(&ModelPreflightInput {
            provider: "openai",
            configured_model: OPENAI_MODEL,
            resolved_model: Some(OPENAI_MODEL),
            available: true,
            retention_mode: "up to 30 days abuse monitoring unless approved controls apply",
            data_use_mode: "API data is not used for training by default",
            no_storage_mode: "store=false for Responses; stronger ZDR is not assumed",
            privacy_mode: "store_false",
            checked_at_ms: now_ms,
            expires_at_ms: now_ms + 3_600_000,
        }).unwrap();

        let calls = build_m1_provider_debug_plan(&database, now_ms).unwrap();

        assert_eq!(calls.len(), 1);
        let call = &calls[0];
        assert_eq!(call.operation, "research.web_verify");
        assert_eq!(call.max_requests, M1_PROVIDER_DEBUG_MAX_REQUESTS);
        assert_eq!(call.max_tool_calls, 1);
        assert_eq!(call.max_input_tokens, 198_000);
        assert_eq!(call.max_output_tokens, 300);
        assert_eq!(call.reservation_micro_usd, 49_960);
        assert!(!call.allow_one_repair);
        assert!(is_exact_m1_provider_debug_call(
            call,
            &policy(&database, "openai", now_ms).unwrap().provider_config,
        ));
    }

    #[test]
    fn exact_quality_bar_prompt_gets_widened_bounded_metadata_plan() {
        let now_ms = 1_787_140_000_000;
        let mut database = Database::open_in_memory().unwrap();
        install(&mut database, now_ms).unwrap();
        database
            .upsert_model_preflight(&ModelPreflightInput {
                provider: "openai",
                configured_model: OPENAI_MODEL,
                resolved_model: Some(OPENAI_MODEL),
                available: true,
                retention_mode: "up to 30 days abuse monitoring unless approved controls apply",
                data_use_mode: "API data is not used for training by default",
                no_storage_mode: "store=false for Responses; stronger ZDR is not assumed",
                privacy_mode: "store_false",
                checked_at_ms: now_ms,
                expires_at_ms: now_ms + 3_600_000,
            })
            .unwrap();
        let intent = crate::domain::parse_intent(serde_json::json!({
            "schemaVersion": "2.0.0",
            "query": "romance/romcom TV, preferably a new episode from the last three days, no K-drama, no reality TV",
            "mediaKinds": ["TV_EPISODE"],
            "focusTerms": ["romance", "romcom"],
            "region": "US",
            "freshnessDays": 3,
            "spoilerPolicy": "CURRENT_EPISODE",
            "exclusions": ["K-drama", "reality TV"],
            "maxResults": 5
        }))
        .unwrap();

        let calls = build_plan(&database, &intent, &"a".repeat(64), now_ms).unwrap();

        assert_eq!(calls.len(), 4);
        assert_eq!(calls[0].provider, "tvmaze");
        assert_eq!(calls[0].max_requests, 16);
        assert_eq!(calls[0].reservation_micro_usd, 0);
        assert_eq!(calls[1].operation, "research.web_verify");
        assert_eq!(calls[1].max_requests, 40);
        assert_eq!(calls[1].max_tool_calls, 14);
        assert_eq!(calls[1].max_input_tokens, 170_000);
        assert_eq!(calls[1].max_output_tokens, 5_333);
        assert_eq!(calls[1].reservation_micro_usd, 180_400);
        assert_eq!(calls[2].provider, "youtube");
        assert_eq!(calls[2].operation, "research.youtube");
        assert_eq!(calls[2].max_requests, 5);
        assert_eq!(calls[2].reservation_micro_usd, 0);
        assert_eq!(calls[3].operation, "research.synthesize");
        assert_eq!(calls[3].reservation_micro_usd, 31_200);
        assert_eq!(
            calls.iter().map(|call| call.reservation_micro_usd).sum::<i64>(),
            211_600
        );
        assert_eq!(tvmaze_request_ceiling(1), 12);
        assert_eq!(tvmaze_request_ceiling(7), 24);
        assert_eq!(tvmaze_request_ceiling(14), 38);
        assert_eq!(tvmaze_request_ceiling(90), 38);
    }

    #[test]
    fn film_and_trailer_plan_does_not_schedule_tvmaze() {
        let now_ms = 1_787_140_000_000;
        let mut database = Database::open_in_memory().unwrap();
        install(&mut database, now_ms).unwrap();
        database
            .upsert_model_preflight(&ModelPreflightInput {
                provider: "openai",
                configured_model: OPENAI_MODEL,
                resolved_model: Some(OPENAI_MODEL),
                available: true,
                retention_mode: "up to 30 days abuse monitoring unless approved controls apply",
                data_use_mode: "API data is not used for training by default",
                no_storage_mode: "store=false for Responses; stronger ZDR is not assumed",
                privacy_mode: "store_false",
                checked_at_ms: now_ms,
                expires_at_ms: now_ms + 3_600_000,
            })
            .unwrap();
        let intent = crate::domain::parse_intent(serde_json::json!({
            "schemaVersion": "2.0.0",
            "query": "trailers and new movies",
            "mediaKinds": ["FILM", "TRAILER"],
            "focusTerms": [],
            "region": "US",
            "freshnessDays": 14,
            "spoilerPolicy": "CURRENT_EPISODE",
            "exclusions": [],
            "maxResults": 5
        }))
        .unwrap();

        let calls = build_plan(&database, &intent, &"b".repeat(64), now_ms).unwrap();

        assert_eq!(calls.len(), 3);
        assert_eq!(calls[0].operation, "research.web_verify");
        assert_eq!(calls[1].provider, "youtube");
        assert_eq!(calls[1].operation, "research.youtube");
        assert_eq!(calls[2].operation, "research.synthesize");
        assert_eq!(
            calls.iter().map(|call| call.reservation_micro_usd).sum::<i64>(),
            211_600
        );
    }
}
