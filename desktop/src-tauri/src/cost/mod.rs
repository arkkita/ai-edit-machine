use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::{AppError, AppResult};

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields, tag = "kind", rename_all = "SCREAMING_SNAKE_CASE", rename_all_fields = "camelCase")]
pub enum ProviderConfig {
    Tvmaze,
    OpenaiWeb {
        registry_version: String,
        official_hosts: Vec<String>,
        search_context_size: String,
        request_body_max_input_tokens: i64,
        request_max_tool_calls: i64,
    },
    OpenaiSynthesis,
    YoutubeOfficialChannels {
        registry_version: String,
        official_channel_ids: Vec<String>,
        official_hosts: Vec<String>,
    },
    XaiSearch {
        adversarial_proof_id: Uuid,
        proof_record_sha256: String,
        request_policy_sha256: String,
        proof_checked_at_unix_ms: i64,
        proof_expires_at_unix_ms: i64,
        max_turns: i64,
    },
}

impl ProviderConfig {
    fn validate(&self, call: &PlannedCallInput) -> AppResult<()> {
        let matches_operation = match self {
            Self::Tvmaze => call.provider == "tvmaze" && call.operation == "research.metadata",
            Self::OpenaiWeb {
                registry_version,
                official_hosts,
                search_context_size,
                request_body_max_input_tokens,
                request_max_tool_calls,
            } => {
                call.provider == "openai" && call.operation == "research.web_verify"
                    && !registry_version.trim().is_empty() && registry_version.len() <= 128
                    && !official_hosts.is_empty() && official_hosts.len() <= 256
                    && official_hosts.iter().all(|host| valid_bare_host(host))
                    && search_context_size == "low"
                    && *request_body_max_input_tokens > 0
                    && *request_body_max_input_tokens <= call.max_input_tokens
                    && *request_max_tool_calls > 0
                    && *request_max_tool_calls <= call.max_tool_calls
            }
            Self::OpenaiSynthesis => call.provider == "openai" && call.operation == "research.synthesize",
            Self::YoutubeOfficialChannels { registry_version, official_channel_ids, official_hosts } => {
                !registry_version.trim().is_empty() && registry_version.len() <= 128
                    && call.provider == "youtube" && call.operation == "research.youtube"
                    && !official_channel_ids.is_empty() && official_channel_ids.len() <= 64
                    && official_channel_ids.iter().all(|value| !value.trim().is_empty() && value.len() <= 128)
                    && official_hosts.iter().all(|host| valid_bare_host(host))
            }
            Self::XaiSearch {
                proof_record_sha256,
                request_policy_sha256,
                proof_checked_at_unix_ms,
                proof_expires_at_unix_ms,
                max_turns,
                ..
            } => {
                call.provider == "xai" && call.operation == "research.x_search"
                    && valid_sha256(proof_record_sha256) && valid_sha256(request_policy_sha256)
                    && *proof_checked_at_unix_ms > 0 && proof_expires_at_unix_ms > proof_checked_at_unix_ms
                    && (1..=100).contains(max_turns)
                    && recompute_xai_policy_hash(call, *max_turns)? == *request_policy_sha256
            }
        };
        if !matches_operation {
            return Err(AppError::Security("provider configuration does not match the planned operation".to_owned()));
        }
        Ok(())
    }
}

fn recompute_xai_policy_hash(call: &PlannedCallInput, max_turns: i64) -> AppResult<String> {
    let value = serde_json::json!({
        "configuredModel": call.configured_model,
        "maxOutputTokens": call.max_output_tokens,
        "maxToolCalls": call.max_tool_calls,
        "maxTurns": max_turns,
        "parallelToolCalls": false,
        "resolvedModel": call.resolved_model,
        "schemaVersion": "2.0.0",
        "toolType": "x_search",
    });
    let canonical = serde_json::to_vec(&value)?;
    Ok(crate::security::sha256_hex(&canonical))
}

fn valid_sha256(value: &str) -> bool {
    value.len() == 64 && value.bytes().all(|byte| byte.is_ascii_digit() || matches!(byte, b'a'..=b'f'))
}

fn valid_bare_host(value: &str) -> bool {
    !value.is_empty() && value.len() <= 253 && value == value.to_ascii_lowercase()
        && !value.contains(['/', ':', '*', '@']) && value.split('.').count() >= 2
        && value.split('.').all(|label| !label.is_empty() && label.len() <= 63
            && !label.starts_with('-') && !label.ends_with('-')
            && label.bytes().all(|byte| byte.is_ascii_alphanumeric() || byte == b'-'))
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct CostComponentPlan {
    pub category: String,
    pub quantity_numerator: i64,
    pub quantity_denominator: i64,
    pub unit: String,
    pub unit_price_micro_usd: i64,
    pub maximum_micro_usd: i64,
}

impl CostComponentPlan {
    pub fn validate(&self) -> AppResult<()> {
        if self.category.trim().is_empty()
            || self.unit.trim().is_empty()
            || !self
                .category
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-'))
            || self.quantity_numerator < 0
            || self.quantity_denominator <= 0
            || self.unit_price_micro_usd < 0
        {
            return Err(AppError::Budget("invalid price component".to_owned()));
        }
        if !matches!(self.unit.as_str(),
            "REQUEST" | "INPUT_TOKEN" | "CACHED_INPUT_TOKEN" | "OUTPUT_TOKEN"
                | "REASONING_TOKEN" | "TOOL_CALL" | "PROVIDER_NATIVE_TICK"
                | "REPAIR_REQUEST" | "RESERVATION_ONLY")
        {
            return Err(AppError::Budget("price component unit is not registered".to_owned()));
        }
        let expected = ceil_cost(
            self.quantity_numerator,
            self.quantity_denominator,
            self.unit_price_micro_usd,
        )?;
        if expected != self.maximum_micro_usd {
            return Err(AppError::Budget(
                "price component maximum does not match trusted integer arithmetic".to_owned(),
            ));
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, Deserialize, Serialize, Eq, PartialEq)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CostKind {
    PaidCloud,
    FreeMetadata,
    LocalCache,
}

impl CostKind {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::PaidCloud => "PAID_CLOUD",
            Self::FreeMetadata => "FREE_METADATA",
            Self::LocalCache => "LOCAL_CACHE",
        }
    }
}

#[derive(Debug, Clone, Copy, Deserialize, Serialize, Eq, PartialEq)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CacheStatus {
    Miss,
    Hit,
    Stale,
}

impl CacheStatus {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Miss => "MISS",
            Self::Hit => "HIT",
            Self::Stale => "STALE",
        }
    }
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct PlannedCallInput {
    pub provider: String,
    pub operation: String,
    pub configured_model: Option<String>,
    pub resolved_model: Option<String>,
    pub price_card_id: Option<Uuid>,
    pub reservation_micro_usd: i64,
    pub cost_kind: CostKind,
    pub cache_status: CacheStatus,
    pub cache_namespace: Option<String>,
    pub cache_key: Option<String>,
    pub cache_input_sha256: Option<String>,
    pub cache_output_sha256: Option<String>,
    pub cache_schema_version: Option<String>,
    pub cache_model_version: Option<String>,
    pub cache_prompt_version: Option<String>,
    pub cache_policy_class: Option<String>,
    pub retention_summary: String,
    pub data_use_summary: String,
    pub no_storage_mode: String,
    pub privacy_mode: String,
    pub policy_class: String,
    pub evidence_ttl_seconds: i64,
    pub refresh_after_seconds: i64,
    pub purge_after_seconds: i64,
    pub deletion_after_seconds: Option<i64>,
    pub cheaper_alternative: String,
    pub requires_live_call: bool,
    pub max_requests: i64,
    pub max_tool_calls: i64,
    pub max_input_tokens: i64,
    pub max_output_tokens: i64,
    pub allow_one_repair: bool,
    pub provider_config: ProviderConfig,
    pub components: Vec<CostComponentPlan>,
}

impl PlannedCallInput {
    pub fn validate_shape(&self) -> AppResult<()> {
        if self.provider.trim().is_empty() || self.operation.trim().is_empty() {
            return Err(AppError::Validation(
                "planned provider call identity is empty".to_owned(),
            ));
        }
        self.provider_config.validate(self)?;
        if self.retention_summary.trim().is_empty()
            || self.data_use_summary.trim().is_empty()
            || self.no_storage_mode.trim().is_empty()
            || self.privacy_mode.trim().is_empty()
            || self.policy_class.trim().is_empty()
            || self.cheaper_alternative.trim().is_empty()
        {
            return Err(AppError::Validation(
                "planned calls require complete privacy and alternative disclosures".to_owned(),
            ));
        }
        if self.evidence_ttl_seconds <= 0
            || self.refresh_after_seconds <= 0
            || self.purge_after_seconds < self.evidence_ttl_seconds
            || self.deletion_after_seconds.is_some_and(|value| value < self.evidence_ttl_seconds)
        {
            return Err(AppError::Security("planned call policy deadlines are invalid".to_owned()));
        }
        for component in &self.components {
            component.validate()?;
        }
        let component_total = self.components.iter().try_fold(0_i64, |total, component| {
            total
                .checked_add(component.maximum_micro_usd)
                .ok_or_else(|| AppError::Budget("cost plan overflow".to_owned()))
        })?;
        if component_total != self.reservation_micro_usd {
            return Err(AppError::Budget(
                "planned call reservation does not equal its component maxima".to_owned(),
            ));
        }
        if self.cost_kind == CostKind::PaidCloud {
            if self.price_card_id.is_none()
                || self.configured_model.as_deref().is_none_or(str::is_empty)
                || self.resolved_model.as_deref().is_none_or(str::is_empty)
                || !self.requires_live_call
                || self.reservation_micro_usd <= 0
                || self.components.is_empty()
                || self.cache_status == CacheStatus::Hit
                || self.max_requests <= 0
                || self.max_input_tokens <= 0
                || self.max_output_tokens <= 0
            {
                return Err(AppError::Budget(
                    "paid calls require a live, nonzero, model-resolved price-card plan".to_owned(),
                ));
            }
        } else if self.price_card_id.is_some()
            || self.reservation_micro_usd != 0
            || !self.components.is_empty()
        {
            return Err(AppError::Budget(
                "free and local-cache calls cannot carry paid price components".to_owned(),
            ));
        }
        if self.max_requests < 0 || self.max_tool_calls < 0 || self.max_input_tokens < 0 || self.max_output_tokens < 0 {
            return Err(AppError::Budget("provider capability ceilings cannot be negative".to_owned()));
        }
        if self.requires_live_call && self.max_requests == 0 {
            return Err(AppError::Budget("live calls require a nonzero request ceiling".to_owned()));
        }
        if !self.requires_live_call
            && (self.max_requests != 0 || self.max_tool_calls != 0 || self.max_input_tokens != 0 || self.max_output_tokens != 0 || self.allow_one_repair)
        {
            return Err(AppError::Budget("non-live calls cannot carry provider quota".to_owned()));
        }
        if self.allow_one_repair
            && (self.max_requests < 2
                || !self.components.iter().any(|component| component.category.to_ascii_lowercase().contains("repair")))
        {
            return Err(AppError::Budget("repair authority requires a separately reserved repair component".to_owned()));
        }
        if self.max_tool_calls > 0
            && !self.components.iter().any(|component| component.category.to_ascii_lowercase().contains("tool"))
        {
            return Err(AppError::Budget("tool authority requires a separately reserved tool component".to_owned()));
        }
        if self.cache_status == CacheStatus::Hit
            && (self.cache_namespace.is_none()
                || self.cache_key.is_none()
                || self.cache_input_sha256.is_none()
                || self.cache_output_sha256.is_none()
                || self.cache_schema_version.is_none()
                || self.cache_model_version.is_none()
                || self.cache_prompt_version.is_none()
                || self.cache_policy_class.is_none()
                || self.reservation_micro_usd != 0
                || self.requires_live_call)
        {
            return Err(AppError::Budget(
                "cache hits require a complete zero-cost cache binding".to_owned(),
            ));
        }
        if self.cache_status == CacheStatus::Hit {
            for value in [
                self.cache_namespace.as_deref().unwrap_or_default(),
                self.cache_key.as_deref().unwrap_or_default(),
            ] {
                if value.is_empty() || value.len() > 512 {
                    return Err(AppError::Budget("cache binding is invalid".to_owned()));
                }
            }
            for hash in [self.cache_input_sha256.as_deref(), self.cache_output_sha256.as_deref()] {
                let hash = hash.unwrap_or_default();
                if hash.len() != 64 || !hash.bytes().all(|byte| byte.is_ascii_hexdigit()) {
                    return Err(AppError::Budget("cache binding hash is invalid".to_owned()));
                }
            }
            for value in [
                self.cache_schema_version.as_deref(),
                self.cache_model_version.as_deref(),
                self.cache_prompt_version.as_deref(),
                self.cache_policy_class.as_deref(),
            ] {
                if value.is_none_or(|value| value.is_empty() || value.len() > 128) {
                    return Err(AppError::Budget("cache version binding is invalid".to_owned()));
                }
            }
        }
        Ok(())
    }
}

pub fn ceil_cost(numerator: i64, denominator: i64, unit_price: i64) -> AppResult<i64> {
    if numerator < 0 || denominator <= 0 || unit_price < 0 {
        return Err(AppError::Budget("invalid cost arithmetic input".to_owned()));
    }
    let product = i128::from(numerator)
        .checked_mul(i128::from(unit_price))
        .ok_or_else(|| AppError::Budget("cost arithmetic overflow".to_owned()))?;
    let value = product
        .checked_add(i128::from(denominator) - 1)
        .ok_or_else(|| AppError::Budget("cost arithmetic overflow".to_owned()))?
        / i128::from(denominator);
    i64::try_from(value).map_err(|_| AppError::Budget("cost arithmetic overflow".to_owned()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cost_components_round_up_in_integer_micro_usd() {
        assert_eq!(ceil_cost(1, 3, 10).unwrap(), 4);
        assert_eq!(ceil_cost(0, 3, 10).unwrap(), 0);
        assert!(ceil_cost(1, 0, 10).is_err());
    }

    #[test]
    fn cache_hit_cannot_claim_a_paid_reservation() {
        let call = PlannedCallInput {
            provider: "openai".into(),
            operation: "verify".into(),
            configured_model: Some("model".into()),
            resolved_model: Some("snapshot".into()),
            price_card_id: None,
            reservation_micro_usd: 1,
            cost_kind: CostKind::LocalCache,
            cache_status: CacheStatus::Hit,
            cache_namespace: Some("research".into()),
            cache_key: Some("key".into()),
            cache_input_sha256: Some("b".repeat(64)),
            cache_output_sha256: Some("a".repeat(64)),
            cache_schema_version: Some("2.0.0".into()),
            cache_model_version: Some("snapshot".into()),
            cache_prompt_version: Some("m1".into()),
            cache_policy_class: Some("research".into()),
            retention_summary: "none".into(),
            data_use_summary: "none".into(),
            no_storage_mode: "local".into(),
            privacy_mode: "local".into(),
            policy_class: "openai-web-evidence-v1".into(),
            evidence_ttl_seconds: 43_200,
            refresh_after_seconds: 43_200,
            purge_after_seconds: 2_592_000,
            deletion_after_seconds: None,
            cheaper_alternative: "already cached".into(),
            requires_live_call: false,
            max_requests: 0,
            max_tool_calls: 0,
            max_input_tokens: 0,
            max_output_tokens: 0,
            allow_one_repair: false,
            provider_config: ProviderConfig::OpenaiWeb {
                registry_version: "test-v1".into(),
                official_hosts: vec!["example.com".into()],
                search_context_size: "low".into(),
                request_body_max_input_tokens: 30_000,
                request_max_tool_calls: 4,
            },
            components: vec![],
        };
        assert!(call.validate_shape().is_err());
    }
}
