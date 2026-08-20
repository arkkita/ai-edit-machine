use std::collections::{HashMap, HashSet};

use rusqlite::{params, OptionalExtension, Transaction, TransactionBehavior};
use serde::Serialize;
use uuid::Uuid;

use super::Database;
use crate::cost::{ceil_cost, CacheStatus, CostComponentPlan, PlannedCallInput, ProviderConfig};
use crate::security::sha256_hex;
use crate::{AppError, AppResult};

pub const DEFAULT_PROJECT_ID: Uuid = Uuid::from_u128(0x00000000_0000_4000_8000_000000000001);

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PlannedCallRecord {
    pub call_id: Uuid,
    pub provider: String,
    pub operation: String,
    pub configured_model: Option<String>,
    pub resolved_model: Option<String>,
    pub reservation_micro_usd: i64,
    pub cost_kind: String,
    pub cache_status: String,
    pub price_card_checked_at_ms: Option<i64>,
    pub retention_summary: String,
    pub data_use_summary: String,
    pub no_storage_mode: String,
    pub privacy_mode: String,
    pub cheaper_alternative: String,
    pub requires_live_call: bool,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CostPreviewRecord {
    pub preview_id: Uuid,
    pub consent_token: Uuid,
    pub planned_calls: Vec<PlannedCallRecord>,
    pub maximum_cost_micro_usd: i64,
    pub already_spent_or_reserved_micro_usd: i64,
    pub effective_warning_micro_usd: i64,
    pub run_hard_limit_micro_usd: i64,
    pub project_hard_limit_micro_usd: i64,
    pub effective_hard_limit_micro_usd: i64,
}

#[derive(Debug, Clone)]
pub struct NewCostPreview<'a> {
    pub project_id: Uuid,
    pub run_scope_key: &'a str,
    pub input_sha256: &'a str,
    pub normalized_intent_json: &'a str,
    pub calls: &'a [PlannedCallInput],
    pub now_ms: i64,
    pub expires_at_ms: i64,
}

#[derive(Debug, Clone)]
pub struct NewResearchJob<'a> {
    pub consent_token: Uuid,
    pub input_sha256: &'a str,
    pub input_contract_json: &'a str,
    pub raw_query: &'a str,
    pub schema_version: &'a str,
    pub now_ms: i64,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct JobRecord {
    pub id: Uuid,
    pub state: String,
    pub progress_percent: i64,
    pub phase: String,
    pub result_contract_json: Option<String>,
    pub sanitized_error: Option<String>,
}

#[derive(Debug, Clone)]
pub struct ResearchExecutionContext {
    pub input_sha256: String,
    pub input_contract_json: String,
    pub normalized_intent_json: String,
    pub capabilities: Vec<ReservationCapability>,
}

#[derive(Debug, Clone)]
pub struct ProviderPolicyInput<'a> {
    pub provider: &'a str,
    pub enabled: bool,
    pub kill_switch_reason: Option<&'a str>,
    pub policy_class: &'a str,
    pub evidence_ttl_seconds: i64,
    pub refresh_after_seconds: i64,
    pub purge_after_seconds: i64,
    pub deletion_after_seconds: Option<i64>,
    pub max_requests_per_run: i64,
    pub max_tool_calls_per_run: i64,
    pub max_input_tokens_per_run: i64,
    pub max_output_tokens_per_run: i64,
    pub retention_summary: &'a str,
    pub data_use_summary: &'a str,
    pub no_storage_mode: &'a str,
    pub privacy_mode: &'a str,
    pub provider_config_json: &'a str,
    pub registry_version: &'a str,
    pub source_url: &'a str,
    pub review_artifact_path: &'a str,
    pub review_artifact_sha256: &'a str,
    pub checked_at_ms: i64,
    pub expires_at_ms: i64,
}

#[derive(Debug, Clone)]
pub struct PriceCardInput<'a> {
    pub id: Uuid,
    pub provider: &'a str,
    pub model: &'a str,
    pub source_url: &'a str,
    pub unit_prices_json: &'a str,
    pub effective_at_ms: i64,
    pub checked_at_ms: i64,
    pub expires_at_ms: i64,
    pub review_artifact_path: &'a str,
    pub review_artifact_sha256: &'a str,
}

#[derive(Debug, Clone)]
pub struct ModelPreflightInput<'a> {
    pub provider: &'a str,
    pub configured_model: &'a str,
    pub resolved_model: Option<&'a str>,
    pub available: bool,
    pub retention_mode: &'a str,
    pub data_use_mode: &'a str,
    pub no_storage_mode: &'a str,
    pub privacy_mode: &'a str,
    pub checked_at_ms: i64,
    pub expires_at_ms: i64,
}

#[derive(Debug, Clone)]
pub struct ModelPreflightRecord {
    pub resolved_model: String,
    pub retention_mode: String,
    pub data_use_mode: String,
    pub no_storage_mode: String,
    pub privacy_mode: String,
}

#[derive(Debug, Clone)]
pub struct ProviderDisclosureRecord {
    pub retention_summary: String,
    pub data_use_summary: String,
    pub no_storage_mode: String,
    pub privacy_mode: String,
    pub expires_at_ms: i64,
}

#[derive(Debug, Clone)]
pub struct TrustedEvidencePolicyRecord {
    pub provider: String,
    pub policy_class: String,
    pub evidence_ttl_seconds: i64,
    pub refresh_after_seconds: i64,
    pub purge_after_seconds: i64,
    pub deletion_after_seconds: Option<i64>,
    pub checked_at_ms: i64,
    pub expires_at_ms: i64,
}

#[derive(Debug, Clone)]
pub struct ReusableEvidenceSnapshot {
    pub sources: Vec<serde_json::Value>,
    pub claims: Vec<serde_json::Value>,
}

#[derive(Debug, Clone)]
pub struct CachePutInput<'a> {
    pub provider: &'a str,
    pub namespace: &'a str,
    pub key: &'a str,
    pub input_sha256: &'a str,
    pub output_sha256: &'a str,
    pub schema_version: &'a str,
    pub model_version: &'a str,
    pub prompt_version: &'a str,
    pub policy_class: &'a str,
    pub contract_json: &'a str,
    pub now_ms: i64,
}

#[derive(Debug, Clone)]
pub struct CacheReadInput<'a> {
    pub namespace: &'a str,
    pub key: &'a str,
    pub input_sha256: &'a str,
    pub output_sha256: &'a str,
    pub schema_version: &'a str,
    pub model_version: &'a str,
    pub prompt_version: &'a str,
    pub policy_class: &'a str,
    pub now_ms: i64,
}

#[derive(Debug, Clone)]
pub struct WholeBundleCacheBinding {
    pub output_sha256: String,
}

#[derive(Debug, Clone)]
pub struct WholeBundleReplay {
    pub planned_call_id: Uuid,
    pub provider_run_id: Uuid,
    pub input_sha256: String,
    pub output_sha256: String,
    pub contract_json: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ReservationCapability {
    pub reservation_id: Uuid,
    pub job_id: Uuid,
    pub planned_call_id: Uuid,
    pub provider_run_id: Uuid,
    pub provider: String,
    pub operation: String,
    pub configured_model: Option<String>,
    pub resolved_model: Option<String>,
    pub maximum_micro_usd: i64,
    pub max_requests: i64,
    pub max_tool_calls: i64,
    pub max_input_tokens: i64,
    pub max_output_tokens: i64,
    pub allow_one_repair: bool,
    pub retention_mode: String,
    pub data_use_mode: String,
    pub no_storage_mode: String,
    pub privacy_mode: String,
    pub policy_class: String,
    pub evidence_ttl_seconds: i64,
    pub refresh_after_seconds: i64,
    pub purge_after_seconds: i64,
    pub deletion_after_seconds: Option<i64>,
    pub provider_config: ProviderConfig,
}

#[derive(Debug, Clone)]
pub struct BeginProviderRun<'a> {
    pub provider_run_id: Uuid,
    pub job_id: Uuid,
    pub planned_call_id: Uuid,
    pub capability: &'a str,
    pub prompt_version: &'a str,
    pub schema_version: &'a str,
    pub input_sha256: &'a str,
    pub retention_mode: &'a str,
    pub data_use_mode: &'a str,
    pub privacy_mode: &'a str,
    pub now_ms: i64,
}

#[derive(Debug, Clone)]
pub struct ReconcileProviderRun<'a> {
    pub provider_run_id: Uuid,
    pub job_id: Uuid,
    pub planned_call_id: Uuid,
    pub provider_native_ticks: Option<&'a str>,
    pub provider_request_id: Option<&'a str>,
    pub outcome: &'a str,
    pub requests: Option<i64>,
    pub input_tokens: Option<i64>,
    pub cached_input_tokens: Option<i64>,
    pub output_tokens: Option<i64>,
    pub reasoning_tokens: Option<i64>,
    pub tool_invocations: Option<i64>,
    pub repair_used: Option<bool>,
    pub tool_usage_json: Option<&'a str>,
    pub output_sha256: Option<&'a str>,
    pub idempotency_key: &'a str,
    pub now_ms: i64,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ReconciliationRecord {
    pub charged_or_held_micro_usd: i64,
    pub usage_verified: bool,
    pub exceeded_reservation: bool,
}

#[derive(Debug, Clone, Copy)]
struct BudgetSnapshot {
    warning: i64,
    run_hard: i64,
    project_hard: i64,
    effective_hard: i64,
}

#[derive(Debug)]
struct PersistedPreview {
    project_id: Uuid,
    run_scope_key: String,
    input_sha256: String,
    normalized_intent_json: String,
    plan_sha256: String,
    plan_contract_json: String,
    maximum: i64,
    expires_at_ms: i64,
    consumed_at_ms: Option<i64>,
}

impl Database {
    /// Apply provider-policy refresh, expiry, purge, and deletion deadlines.
    /// Trend evidence is deliberately short-lived; once deletion/purge is due,
    /// the trusted core removes searchable excerpts and link handles as well as
    /// normalized recommendation rows that still depend on those claims.
    pub fn run_policy_maintenance(&mut self, now_ms: i64) -> AppResult<()> {
        let transaction = self.connection_mut().transaction_with_behavior(TransactionBehavior::Immediate)?;
        transaction.execute(
            "UPDATE cache_entry SET state='STALE' WHERE state='VALID' AND expires_at_ms<=?1",
            [now_ms],
        )?;
        transaction.execute(
            "DELETE FROM cache_entry WHERE purge_at_ms IS NOT NULL AND purge_at_ms<=?1",
            [now_ms],
        )?;
        transaction.execute(
            "DELETE FROM cache_flight WHERE lease_expires_at_ms<=?1",
            [now_ms],
        )?;
        transaction.execute(
            "UPDATE evidence_source SET fetch_status='STALE' WHERE deleted_at_ms IS NULL AND expires_at_ms IS NOT NULL AND expires_at_ms<=?1",
            [now_ms],
        )?;
        let due_sources = {
            let mut statement = transaction.prepare(
                "SELECT id FROM evidence_source WHERE deleted_at_ms IS NULL AND ((purge_due_at_ms IS NOT NULL AND purge_due_at_ms<=?1) OR (deletion_required_at_ms IS NOT NULL AND deletion_required_at_ms<=?1)) ORDER BY id",
            )?;
            statement.query_map([now_ms], |row| row.get::<_, String>(0))?
                .collect::<Result<Vec<_>, _>>()?
        };
        if !due_sources.is_empty() {
            transaction.pragma_update(None, "defer_foreign_keys", true)?;
        }
        for source_id in due_sources {
            let pattern = format!("%{source_id}%");
            let affected_runs = {
                let mut statement = transaction.prepare(
                    "SELECT id,job_id FROM research_run WHERE evidence_sources_json LIKE ?1 OR evidence_claims_json LIKE ?1",
                )?;
                statement.query_map([&pattern], |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?)))?
                    .collect::<Result<Vec<_>, _>>()?
            };
            for (run_id, job_id) in affected_runs {
                let opportunity_ids = {
                    let mut statement = transaction.prepare("SELECT id FROM opportunity WHERE research_run_id=?1")?;
                    statement.query_map([&run_id], |row| row.get::<_, String>(0))?
                        .collect::<Result<Vec<_>, _>>()?
                };
                for opportunity_id in opportunity_ids {
                    transaction.execute("DELETE FROM footage_request WHERE opportunity_id=?1", [&opportunity_id])?;
                    transaction.execute("DELETE FROM opportunity WHERE id=?1", [&opportunity_id])?;
                }
                transaction.execute(
                    "UPDATE research_run SET summary='Research result expired under provider evidence policy.',warnings_json='[\"Evidence expired; run fresh research before using this recommendation.\"]',canonical_result_json=NULL,evidence_sources_json=NULL,evidence_claims_json=NULL WHERE id=?1",
                    [&run_id],
                )?;
                transaction.execute(
                    "UPDATE job SET phase='research result expired by evidence policy',result_contract_json=NULL WHERE id=?1",
                    [&job_id],
                )?;
            }
            transaction.execute(
                "DELETE FROM evidence_fts WHERE evidence_claim_id IN (SELECT id FROM evidence_claim WHERE source_id=?1)",
                [&source_id],
            )?;
            transaction.execute("DELETE FROM external_link WHERE evidence_source_id=?1", [&source_id])?;
            transaction.execute("DELETE FROM evidence_claim WHERE source_id=?1", [&source_id])?;
            transaction.execute("DELETE FROM evidence_source WHERE id=?1", [&source_id])?;
        }
        transaction.commit()?;
        Ok(())
    }

    pub fn upsert_provider_policy(&mut self, input: &ProviderPolicyInput<'_>) -> AppResult<()> {
        let _: serde_json::Value = serde_json::from_str(input.provider_config_json)?;
        self.connection_mut().execute(
            "INSERT INTO provider_policy(provider, enabled, kill_switch_reason, policy_class, evidence_ttl_seconds, refresh_after_seconds, purge_after_seconds, deletion_after_seconds, max_requests_per_run, max_tool_calls_per_run, max_input_tokens_per_run, max_output_tokens_per_run, retention_summary, data_use_summary, no_storage_mode, privacy_mode, provider_config_json, registry_version, source_url, review_artifact_path, review_artifact_sha256, checked_at_ms, expires_at_ms)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15, ?16, ?17, ?18, ?19, ?20, ?21, ?22, ?23)
             ON CONFLICT(provider) DO UPDATE SET enabled=excluded.enabled, kill_switch_reason=excluded.kill_switch_reason, policy_class=excluded.policy_class, evidence_ttl_seconds=excluded.evidence_ttl_seconds, refresh_after_seconds=excluded.refresh_after_seconds, purge_after_seconds=excluded.purge_after_seconds, deletion_after_seconds=excluded.deletion_after_seconds, max_requests_per_run=excluded.max_requests_per_run, max_tool_calls_per_run=excluded.max_tool_calls_per_run, max_input_tokens_per_run=excluded.max_input_tokens_per_run, max_output_tokens_per_run=excluded.max_output_tokens_per_run, retention_summary=excluded.retention_summary, data_use_summary=excluded.data_use_summary, no_storage_mode=excluded.no_storage_mode, privacy_mode=excluded.privacy_mode, provider_config_json=excluded.provider_config_json, registry_version=excluded.registry_version, source_url=excluded.source_url, review_artifact_path=excluded.review_artifact_path, review_artifact_sha256=excluded.review_artifact_sha256, checked_at_ms=excluded.checked_at_ms, expires_at_ms=excluded.expires_at_ms",
            params![input.provider, input.enabled, input.kill_switch_reason, input.policy_class,
                input.evidence_ttl_seconds, input.refresh_after_seconds, input.purge_after_seconds, input.deletion_after_seconds,
                input.max_requests_per_run, input.max_tool_calls_per_run, input.max_input_tokens_per_run, input.max_output_tokens_per_run,
                input.retention_summary, input.data_use_summary, input.no_storage_mode,
                input.privacy_mode, input.provider_config_json, input.registry_version, input.source_url,
                input.review_artifact_path, input.review_artifact_sha256, input.checked_at_ms, input.expires_at_ms],
        )?;
        Ok(())
    }

    pub fn insert_price_card(&mut self, input: &PriceCardInput<'_>) -> AppResult<()> {
        let _: serde_json::Value = serde_json::from_str(input.unit_prices_json)?;
        let inserted = self.connection_mut().execute(
            "INSERT INTO price_card(id, provider, model, source_url, currency, unit_prices_json, effective_at_ms, checked_at_ms, expires_at_ms, review_artifact_path, review_artifact_sha256) VALUES (?1, ?2, ?3, ?4, 'USD', ?5, ?6, ?7, ?8, ?9, ?10) ON CONFLICT(id) DO NOTHING",
            params![input.id.to_string(), input.provider, input.model, input.source_url,
                input.unit_prices_json, input.effective_at_ms, input.checked_at_ms,
                input.expires_at_ms, input.review_artifact_path, input.review_artifact_sha256],
        )?;
        if inserted == 0 {
            let exact = self.connection().query_row(
                "SELECT 1 FROM price_card WHERE id=?1 AND provider=?2 AND model=?3 AND source_url=?4 AND unit_prices_json=?5 AND effective_at_ms=?6 AND checked_at_ms=?7 AND expires_at_ms=?8 AND review_artifact_path=?9 AND review_artifact_sha256=?10",
                params![input.id.to_string(), input.provider, input.model, input.source_url,
                    input.unit_prices_json, input.effective_at_ms, input.checked_at_ms,
                    input.expires_at_ms, input.review_artifact_path, input.review_artifact_sha256],
                |_| Ok(()),
            ).optional()?.is_some();
            if !exact { return Err(AppError::DatabaseInvariant("immutable price card ID was reused with different data".to_owned())); }
        }
        Ok(())
    }

    pub fn upsert_model_preflight(&mut self, input: &ModelPreflightInput<'_>) -> AppResult<()> {
        if input.provider.trim().is_empty() || input.configured_model.trim().is_empty()
            || input.available != input.resolved_model.is_some()
            || input.expires_at_ms <= input.checked_at_ms
            || [input.retention_mode, input.data_use_mode, input.no_storage_mode, input.privacy_mode].iter().any(|value| value.trim().is_empty())
        {
            return Err(AppError::Validation("model preflight record is invalid".to_owned()));
        }
        self.connection_mut().execute(
            "INSERT INTO provider_model_preflight(provider, configured_model, resolved_model, available, retention_mode, data_use_mode, no_storage_mode, privacy_mode, checked_at_ms, expires_at_ms)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10)
             ON CONFLICT(provider, configured_model) DO UPDATE SET resolved_model=excluded.resolved_model, available=excluded.available, retention_mode=excluded.retention_mode, data_use_mode=excluded.data_use_mode, no_storage_mode=excluded.no_storage_mode, privacy_mode=excluded.privacy_mode, checked_at_ms=excluded.checked_at_ms, expires_at_ms=excluded.expires_at_ms",
            params![input.provider, input.configured_model, input.resolved_model, input.available,
                input.retention_mode, input.data_use_mode, input.no_storage_mode, input.privacy_mode,
                input.checked_at_ms, input.expires_at_ms],
        )?;
        Ok(())
    }

    pub fn clear_model_preflight(&mut self, provider: &str) -> AppResult<()> {
        self.connection_mut().execute("DELETE FROM provider_model_preflight WHERE provider=?1", [provider])?;
        Ok(())
    }

    pub fn model_preflight(&self, provider: &str, configured_model: &str, now_ms: i64) -> AppResult<ModelPreflightRecord> {
        self.connection().query_row(
            "SELECT resolved_model, retention_mode, data_use_mode, no_storage_mode, privacy_mode
             FROM provider_model_preflight
             WHERE provider=?1 AND configured_model=?2 AND available=1
               AND checked_at_ms<=?3 AND expires_at_ms>=?3",
            params![provider, configured_model, now_ms],
            |row| Ok(ModelPreflightRecord { resolved_model: row.get(0)?, retention_mode: row.get(1)?, data_use_mode: row.get(2)?, no_storage_mode: row.get(3)?, privacy_mode: row.get(4)? }),
        ).optional()?.ok_or_else(|| AppError::Provider(format!("{provider} model preflight is missing or stale")))
    }

    /// Install one immutable run-scope budget for the development-only M1
    /// provider probe. Reusing the same scope can never authorize a second
    /// paid request once any amount from the first request is committed.
    #[cfg(debug_assertions)]
    pub fn ensure_m1_provider_debug_budget(
        &mut self,
        run_scope_key: &str,
        hard_cap_micro_usd: i64,
        now_ms: i64,
    ) -> AppResult<()> {
        if run_scope_key.trim().is_empty() || hard_cap_micro_usd <= 0 || hard_cap_micro_usd > 50_000 {
            return Err(AppError::Budget("development provider-debug budget is invalid".to_owned()));
        }
        let transaction = self.connection_mut().transaction_with_behavior(TransactionBehavior::Immediate)?;
        transaction.execute(
            "INSERT INTO budget(id,scope_type,scope_id,warning_micro_usd,hard_micro_usd,enabled,created_at_ms)
             VALUES (?1,'RUN',?2,?3,?3,1,?4)
             ON CONFLICT(scope_type,scope_id) DO NOTHING",
            params![Uuid::new_v4().to_string(), run_scope_key, hard_cap_micro_usd, now_ms],
        )?;
        let exact: bool = transaction.query_row(
            "SELECT COUNT(*)=1 FROM budget
             WHERE scope_type='RUN' AND scope_id=?1 AND warning_micro_usd=?2
               AND hard_micro_usd=?2 AND enabled=1",
            params![run_scope_key, hard_cap_micro_usd],
            |row| row.get(0),
        )?;
        if !exact {
            return Err(AppError::Budget("development provider-debug run budget conflicts with existing state".to_owned()));
        }
        transaction.commit()?;
        Ok(())
    }

    /// Install the immutable aggregate budget for the debug-only M1.1 live
    /// calibration loop. Every rerun uses the same scope, so reservations and
    /// unverified charges accumulate durably and can never exceed $2.00.
    #[cfg(debug_assertions)]
    pub fn ensure_m11_calibration_budget(&mut self, now_ms: i64) -> AppResult<()> {
        let run_scope_key = crate::provider_catalog::M11_CALIBRATION_RUN_SCOPE;
        let hard_cap_micro_usd =
            crate::provider_catalog::M11_CALIBRATION_HARD_CAP_MICRO_USD;
        let transaction = self
            .connection_mut()
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        transaction.execute(
            "INSERT INTO budget(id,scope_type,scope_id,warning_micro_usd,hard_micro_usd,enabled,created_at_ms)
             VALUES (?1,'RUN',?2,?3,?3,1,?4)
             ON CONFLICT(scope_type,scope_id) DO NOTHING",
            params![
                Uuid::new_v4().to_string(),
                run_scope_key,
                hard_cap_micro_usd,
                now_ms
            ],
        )?;
        let exact: bool = transaction.query_row(
            "SELECT COUNT(*)=1 FROM budget
             WHERE scope_type='RUN' AND scope_id=?1 AND warning_micro_usd=?2
               AND hard_micro_usd=?2 AND enabled=1",
            params![run_scope_key, hard_cap_micro_usd],
            |row| row.get(0),
        )?;
        if !exact {
            return Err(AppError::Budget(
                "M1.1 calibration budget conflicts with existing state".to_owned(),
            ));
        }
        transaction.commit()?;
        Ok(())
    }

    #[cfg(debug_assertions)]
    pub fn m11_calibration_committed_micro_usd(&self) -> AppResult<i64> {
        Ok(self.connection().query_row(
            "SELECT COALESCE(SUM(committed), 0) FROM (
               SELECT cost_entry.planned_call_id,
                 MAX(
                   MAX(CASE WHEN cost_entry.state IN ('RESERVED','UNVERIFIED') THEN cost_entry.micro_usd ELSE 0 END),
                   SUM(CASE WHEN cost_entry.state = 'ACTUAL' THEN cost_entry.micro_usd ELSE 0 END)
                 ) AS committed
               FROM cost_entry JOIN job ON job.id=cost_entry.job_id
               WHERE job.run_scope_key=?1
               GROUP BY cost_entry.planned_call_id
             )",
            [crate::provider_catalog::M11_CALIBRATION_RUN_SCOPE],
            |row| row.get(0),
        )?)
    }

    pub fn provider_disclosures(&self, provider: &str, now_ms: i64) -> AppResult<ProviderDisclosureRecord> {
        self.connection().query_row(
            "SELECT retention_summary,data_use_summary,no_storage_mode,privacy_mode,expires_at_ms
             FROM provider_policy WHERE provider=?1 AND enabled=1 AND kill_switch_reason IS NULL
               AND checked_at_ms<=?2 AND expires_at_ms>=?2",
            params![provider, now_ms],
            |row| Ok(ProviderDisclosureRecord {
                retention_summary: row.get(0)?, data_use_summary: row.get(1)?,
                no_storage_mode: row.get(2)?, privacy_mode: row.get(3)?, expires_at_ms: row.get(4)?,
            }),
        ).optional()?.ok_or_else(|| AppError::Provider(format!("{provider} policy is disabled or stale")))
    }

    pub fn trusted_evidence_policies(&self, now_ms: i64) -> AppResult<Vec<TrustedEvidencePolicyRecord>> {
        let mut statement = self.connection().prepare(
            "SELECT provider,policy_class,evidence_ttl_seconds,refresh_after_seconds,purge_after_seconds,deletion_after_seconds,checked_at_ms,expires_at_ms
             FROM provider_policy WHERE enabled=1 AND kill_switch_reason IS NULL AND checked_at_ms<=?1 AND expires_at_ms>=?1 ORDER BY provider",
        )?;
        Ok(statement.query_map([now_ms], |row| Ok(TrustedEvidencePolicyRecord {
            provider: row.get(0)?,
            policy_class: row.get(1)?,
            evidence_ttl_seconds: row.get(2)?,
            refresh_after_seconds: row.get(3)?,
            purge_after_seconds: row.get(4)?,
            deletion_after_seconds: row.get(5)?,
            checked_at_ms: row.get(6)?,
            expires_at_ms: row.get(7)?,
        }))?.collect::<Result<Vec<_>, _>>()?)
    }

    pub fn reusable_research_evidence(
        &self,
        now_ms: i64,
        max_sources: i64,
        max_claims: i64,
    ) -> AppResult<ReusableEvidenceSnapshot> {
        if !(1..=64).contains(&max_sources) || !(1..=128).contains(&max_claims) {
            return Err(AppError::DatabaseInvariant(
                "reusable evidence bounds are invalid".to_owned(),
            ));
        }
        // Reuse only previously persisted, page-validated OpenAI discussion
        // evidence whose source and provider policy are still current. The
        // original retrieval time and exact deadlines stay intact; reuse never
        // refreshes or extends a trend record. Free TVmaze metadata is fetched
        // again so the current episode slate remains authoritative for this run.
        let source_rows = {
            let mut statement = self.connection().prepare(
                "WITH ranked AS (
                    SELECT item.value AS contract_json, source.id AS source_id,
                           source.retrieved_at_ms,
                           ROW_NUMBER() OVER (
                               PARTITION BY source.id
                               ORDER BY run.finished_at_ms DESC
                           ) AS occurrence
                    FROM research_run run, json_each(run.evidence_sources_json) item
                    JOIN job ON job.id=run.job_id
                    JOIN evidence_source source
                      ON source.id=json_extract(item.value,'$.sourceId')
                    JOIN provider_policy policy
                      ON policy.provider=source.provider
                     AND policy.policy_class=source.policy_class
                    WHERE run.status='SUCCEEDED'
                      AND job.run_scope_key<>'m1-provider-debug-live-2026-08-19-v1'
                      AND job.run_scope_key<>'m1-1-live-calibration-2026-08-19-v1'
                      AND run.evidence_sources_json IS NOT NULL
                      AND source.provider='openai'
                      AND source.source_type='ARTICLE'
                      AND source.fetch_status='SUCCESS'
                      AND source.deleted_at_ms IS NULL
                      AND source.refresh_due_at_ms>?1
                      AND source.expires_at_ms>?1
                      AND source.purge_due_at_ms>?1
                      AND (source.deletion_required_at_ms IS NULL
                           OR source.deletion_required_at_ms>?1)
                      AND policy.enabled=1
                      AND policy.kill_switch_reason IS NULL
                      AND policy.checked_at_ms<=?1
                      AND policy.expires_at_ms>=?1
                      AND EXISTS (
                          SELECT 1 FROM evidence_claim claim
                          WHERE claim.source_id=source.id
                            AND claim.claim_kind='VIEWER_DISCUSSION'
                            AND claim.verification='SECONDARY_CORROBORATED'
                            AND claim.supports_why_now=1
                      )
                )
                SELECT contract_json FROM ranked
                WHERE occurrence=1
                ORDER BY retrieved_at_ms DESC, source_id
                LIMIT ?2",
            )?;
            statement
                .query_map(params![now_ms, max_sources], |row| row.get::<_, String>(0))?
                .collect::<Result<Vec<_>, _>>()?
        };
        let mut sources = Vec::with_capacity(source_rows.len());
        let mut source_ids = HashSet::new();
        for row in source_rows {
            let value: serde_json::Value = serde_json::from_str(&row)?;
            let source_id = value
                .get("sourceId")
                .and_then(serde_json::Value::as_str)
                .ok_or_else(|| {
                    AppError::DatabaseInvariant(
                        "persisted reusable evidence source lost its identity".to_owned(),
                    )
                })?;
            if source_ids.insert(source_id.to_owned()) {
                sources.push(value);
            }
        }

        let claim_rows = {
            let mut statement = self.connection().prepare(
                "WITH ranked AS (
                    SELECT item.value AS contract_json, claim.id AS claim_id,
                           source.retrieved_at_ms,
                           ROW_NUMBER() OVER (
                               PARTITION BY claim.id
                               ORDER BY run.finished_at_ms DESC
                           ) AS occurrence
                    FROM research_run run, json_each(run.evidence_claims_json) item
                    JOIN job ON job.id=run.job_id
                    JOIN evidence_claim claim
                      ON claim.id=json_extract(item.value,'$.claimId')
                    JOIN evidence_source source ON source.id=claim.source_id
                    JOIN provider_policy policy
                      ON policy.provider=source.provider
                     AND policy.policy_class=source.policy_class
                    WHERE run.status='SUCCEEDED'
                      AND job.run_scope_key<>'m1-provider-debug-live-2026-08-19-v1'
                      AND job.run_scope_key<>'m1-1-live-calibration-2026-08-19-v1'
                      AND run.evidence_claims_json IS NOT NULL
                      AND source.provider='openai'
                      AND source.source_type='ARTICLE'
                      AND source.fetch_status='SUCCESS'
                      AND source.deleted_at_ms IS NULL
                      AND source.refresh_due_at_ms>?1
                      AND source.expires_at_ms>?1
                      AND source.purge_due_at_ms>?1
                      AND (source.deletion_required_at_ms IS NULL
                           OR source.deletion_required_at_ms>?1)
                      AND policy.enabled=1
                      AND policy.kill_switch_reason IS NULL
                      AND policy.checked_at_ms<=?1
                      AND policy.expires_at_ms>=?1
                      AND claim.claim_kind='VIEWER_DISCUSSION'
                      AND claim.verification='SECONDARY_CORROBORATED'
                      AND claim.supports_why_now=1
                )
                SELECT contract_json FROM ranked
                WHERE occurrence=1
                ORDER BY retrieved_at_ms DESC, claim_id
                LIMIT ?2",
            )?;
            statement
                .query_map(params![now_ms, max_claims], |row| row.get::<_, String>(0))?
                .collect::<Result<Vec<_>, _>>()?
        };
        let mut claims = Vec::with_capacity(claim_rows.len());
        let mut claim_ids = HashSet::new();
        for row in claim_rows {
            let value: serde_json::Value = serde_json::from_str(&row)?;
            let claim_id = value
                .get("claimId")
                .and_then(serde_json::Value::as_str)
                .ok_or_else(|| {
                    AppError::DatabaseInvariant(
                        "persisted reusable evidence claim lost its identity".to_owned(),
                    )
                })?;
            let source_id = value
                .get("sourceId")
                .and_then(serde_json::Value::as_str)
                .ok_or_else(|| {
                    AppError::DatabaseInvariant(
                        "persisted reusable evidence claim lost its source".to_owned(),
                    )
                })?;
            if source_ids.contains(source_id) && claim_ids.insert(claim_id.to_owned()) {
                claims.push(value);
            }
        }
        let claimed_sources = claims
            .iter()
            .filter_map(|value| value.get("sourceId").and_then(serde_json::Value::as_str))
            .collect::<HashSet<_>>();
        sources.retain(|value| {
            value
                .get("sourceId")
                .and_then(serde_json::Value::as_str)
                .is_some_and(|source_id| claimed_sources.contains(source_id))
        });
        Ok(ReusableEvidenceSnapshot { sources, claims })
    }

    pub fn current_model_preflight_checked_at(
        &self,
        provider: &str,
        configured_model: &str,
        now_ms: i64,
    ) -> AppResult<Option<String>> {
        Ok(self.connection().query_row(
            "SELECT strftime('%Y-%m-%dT%H:%M:%fZ',checked_at_ms/1000.0,'unixepoch')
             FROM provider_model_preflight
             WHERE provider=?1 AND configured_model=?2 AND available=1
               AND checked_at_ms<=?3 AND expires_at_ms>=?3",
            params![provider, configured_model, now_ms], |row| row.get(0),
        ).optional()?)
    }

    pub fn cache_put(&mut self, input: &CachePutInput<'_>) -> AppResult<()> {
        let _: serde_json::Value = serde_json::from_str(input.contract_json)?;
        validate_sha256(input.input_sha256)?;
        validate_sha256(input.output_sha256)?;
        if sha256_hex(input.contract_json.as_bytes()) != input.output_sha256.to_ascii_lowercase() {
            return Err(AppError::DatabaseInvariant(
                "cache output hash does not match the canonical contract".to_owned(),
            ));
        }
        if input.namespace.is_empty() || input.namespace.len() > 128 || input.key.is_empty() || input.key.len() > 512 {
            return Err(AppError::Validation("cache identity is invalid".to_owned()));
        }
        let size_bytes = i64::try_from(input.contract_json.len())
            .map_err(|_| AppError::Validation("cache entry is too large".to_owned()))?;
        let transaction = self.connection_mut().transaction_with_behavior(TransactionBehavior::Immediate)?;
        let policy = transaction
            .query_row(
                "SELECT policy_class, evidence_ttl_seconds, purge_after_seconds FROM provider_policy WHERE provider=?1 AND enabled=1 AND kill_switch_reason IS NULL AND checked_at_ms<=?2 AND expires_at_ms>=?2",
                params![input.provider, input.now_ms],
                |row| Ok((row.get::<_, String>(0)?, row.get::<_, i64>(1)?, row.get::<_, i64>(2)?)),
            )
            .optional()?
            .ok_or_else(|| AppError::Provider("fresh cache policy is unavailable".to_owned()))?;
        if policy.0 != input.policy_class {
            return Err(AppError::Security("cache policy class is not trusted".to_owned()));
        }
        let expires_at_ms = input.now_ms.checked_add(policy.1.checked_mul(1000).ok_or_else(|| AppError::Validation("cache TTL overflow".to_owned()))?)
            .ok_or_else(|| AppError::Validation("cache TTL overflow".to_owned()))?;
        let purge_at_ms = input.now_ms.checked_add(policy.2.checked_mul(1000).ok_or_else(|| AppError::Validation("cache purge TTL overflow".to_owned()))?)
            .ok_or_else(|| AppError::Validation("cache purge TTL overflow".to_owned()))?;
        transaction.execute(
            "INSERT INTO cache_entry(provider, namespace, cache_key, input_sha256, output_sha256, schema_version, model_version, prompt_version, policy_class, contract_json, created_at_ms, accessed_at_ms, expires_at_ms, purge_at_ms, state, size_bytes, lease_owner, lease_expires_at_ms)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?11, ?12, ?13, 'VALID', ?14, NULL, NULL)
             ON CONFLICT(namespace, cache_key) DO UPDATE SET provider=excluded.provider, input_sha256=excluded.input_sha256, output_sha256=excluded.output_sha256, schema_version=excluded.schema_version, model_version=excluded.model_version, prompt_version=excluded.prompt_version, policy_class=excluded.policy_class, contract_json=excluded.contract_json, created_at_ms=excluded.created_at_ms, accessed_at_ms=excluded.accessed_at_ms, expires_at_ms=excluded.expires_at_ms, purge_at_ms=excluded.purge_at_ms, state='VALID', size_bytes=excluded.size_bytes, lease_owner=NULL, lease_expires_at_ms=NULL",
            params![input.provider, input.namespace, input.key, input.input_sha256, input.output_sha256,
                input.schema_version, input.model_version, input.prompt_version, input.policy_class,
                input.contract_json, input.now_ms, expires_at_ms, purge_at_ms, size_bytes],
        )?;
        transaction.execute(
            "DELETE FROM cache_flight WHERE namespace=?1 AND cache_key=?2 AND input_sha256=?3",
            params![input.namespace, input.key, input.input_sha256],
        )?;
        transaction.commit()?;
        Ok(())
    }

    pub fn create_cost_preview(&mut self, input: &NewCostPreview<'_>) -> AppResult<CostPreviewRecord> {
        validate_sha256(input.input_sha256)?;
        if input.calls.is_empty() || input.expires_at_ms <= input.now_ms || input.run_scope_key.trim().is_empty() {
            return Err(AppError::Validation("cost preview request is incomplete".to_owned()));
        }
        let _: serde_json::Value = serde_json::from_str(input.normalized_intent_json)?;
        for call in input.calls {
            call.validate_shape()?;
            if call.cache_status == CacheStatus::Hit
                && call.cache_input_sha256.as_deref() != Some(input.input_sha256)
            {
                return Err(AppError::Budget("cache hit does not belong to the current research input".to_owned()));
            }
        }
        let plan_contract_json = serde_json::to_string(input.calls)?;
        let plan_sha256 = signed_preview_hash(input.normalized_intent_json, &plan_contract_json);
        let maximum = sum_call_reservations(input.calls)?;

        let transaction = self.connection_mut().transaction_with_behavior(TransactionBehavior::Immediate)?;
        ensure_project(&transaction, input.project_id)?;
        validate_calls(&transaction, input.calls, input.now_ms)?;
        let budgets = budget_snapshot(&transaction, input.project_id, input.run_scope_key)?;
        let calibration_scope = is_m11_calibration_scope(input.run_scope_key);
        let project_committed = if calibration_scope {
            0
        } else {
            committed_for_project(&transaction, input.project_id)?
        };
        let run_committed = committed_for_run(&transaction, input.project_id, input.run_scope_key)?;
        enforce_budget(maximum, project_committed, run_committed, budgets)?;
        let displayed_committed = if calibration_scope {
            run_committed
        } else {
            project_committed
        };

        let consent_token = Uuid::new_v4();
        transaction.execute(
            "INSERT INTO cost_preview(consent_token, project_id, run_scope_key, input_sha256, normalized_intent_json, plan_sha256, plan_contract_json, maximum_micro_usd, already_committed_micro_usd, run_hard_limit_micro_usd, project_hard_limit_micro_usd, effective_hard_limit_micro_usd, expires_at_ms, created_at_ms)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14)",
            params![consent_token.to_string(), input.project_id.to_string(), input.run_scope_key,
                input.input_sha256, input.normalized_intent_json, plan_sha256, plan_contract_json, maximum, displayed_committed,
                budgets.run_hard, budgets.project_hard, budgets.effective_hard,
                input.expires_at_ms, input.now_ms],
        )?;

        let mut records = Vec::with_capacity(input.calls.len());
        for (order, call) in input.calls.iter().enumerate() {
            let call_id = Uuid::new_v4();
            transaction.execute(
                "INSERT INTO planned_provider_call(id, consent_token, display_order, provider, operation, configured_model, resolved_model, price_card_id, reservation_micro_usd, cost_kind, cache_status, cache_namespace, cache_key, cache_input_sha256, cache_output_sha256, cache_schema_version, cache_model_version, cache_prompt_version, cache_policy_class, retention_summary, data_use_summary, no_storage_mode, privacy_mode, cheaper_alternative, requires_live_call, max_requests, max_tool_calls, max_input_tokens, max_output_tokens, allow_one_repair, provider_config_json, policy_class, evidence_ttl_seconds, refresh_after_seconds, purge_after_seconds, deletion_after_seconds)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15, ?16, ?17, ?18, ?19, ?20, ?21, ?22, ?23, ?24, ?25, ?26, ?27, ?28, ?29, ?30, ?31, ?32, ?33, ?34, ?35, ?36)",
                params![call_id.to_string(), consent_token.to_string(), order as i64, call.provider,
                    call.operation, call.configured_model, call.resolved_model,
                    call.price_card_id.map(|value| value.to_string()), call.reservation_micro_usd,
                    call.cost_kind.as_str(), call.cache_status.as_str(), call.cache_namespace,
                    call.cache_key, call.cache_input_sha256, call.cache_output_sha256,
                    call.cache_schema_version, call.cache_model_version, call.cache_prompt_version,
                    call.cache_policy_class, call.retention_summary, call.data_use_summary,
                    call.no_storage_mode, call.privacy_mode, call.cheaper_alternative, call.requires_live_call,
                    call.max_requests, call.max_tool_calls, call.max_input_tokens, call.max_output_tokens,
                    call.allow_one_repair, serde_json::to_string(&call.provider_config)?,
                    call.policy_class, call.evidence_ttl_seconds, call.refresh_after_seconds,
                    call.purge_after_seconds, call.deletion_after_seconds],
            )?;
            for component in &call.components {
                transaction.execute(
                    "INSERT INTO planned_cost_component(id, planned_call_id, category, quantity_numerator, quantity_denominator, unit, unit_price_micro_usd, maximum_micro_usd) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
                    params![Uuid::new_v4().to_string(), call_id.to_string(), component.category,
                        component.quantity_numerator, component.quantity_denominator, component.unit,
                        component.unit_price_micro_usd, component.maximum_micro_usd],
                )?;
            }
            let checked_at = call.price_card_id
                .map(|id| price_card_checked_at(&transaction, id))
                .transpose()?;
            records.push(call_record(call_id, call, checked_at));
        }
        transaction.commit()?;
        Ok(CostPreviewRecord {
            preview_id: consent_token,
            consent_token,
            planned_calls: records,
            maximum_cost_micro_usd: maximum,
            already_spent_or_reserved_micro_usd: displayed_committed,
            effective_warning_micro_usd: budgets.warning,
            run_hard_limit_micro_usd: budgets.run_hard,
            project_hard_limit_micro_usd: budgets.project_hard,
            effective_hard_limit_micro_usd: budgets.effective_hard,
        })
    }

    pub fn consume_preview_and_create_job(&mut self, input: &NewResearchJob<'_>) -> AppResult<JobRecord> {
        validate_sha256(input.input_sha256)?;
        let _: serde_json::Value = crate::worker::protocol::parse_strict_json_bytes(input.input_contract_json.as_bytes())?;
        if sha256_hex(input.input_contract_json.as_bytes()) != input.input_sha256 {
            return Err(AppError::Security("research input contract does not match its trusted hash".to_owned()));
        }
        let transaction = self.connection_mut().transaction_with_behavior(TransactionBehavior::Immediate)?;
        if let Some((existing_id, existing_hash)) = transaction
            .query_row(
                "SELECT id,input_sha256 FROM job WHERE idempotency_key = ?1",
                [input.consent_token.to_string()],
                |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?)),
            )
            .optional()?
        {
            if existing_hash != input.input_sha256 {
                return Err(AppError::Security("idempotent research start does not match the original intent hash".to_owned()));
            }
            let record = job_from_transaction(&transaction, parse_uuid(&existing_id, "job ID")?)?;
            transaction.commit()?;
            return Ok(record);
        }

        let preview = load_preview(&transaction, input.consent_token)?;
        let normalized_intent = crate::domain::parse_intent(serde_json::from_str(&preview.normalized_intent_json)?)?;
        let freshness_cutoff_ms = input.now_ms.saturating_sub(
            normalized_intent.freshness_days().saturating_mul(86_400_000),
        );
        if preview.input_sha256 != input.input_sha256 {
            return Err(AppError::Budget("cost preview does not match this request".to_owned()));
        }
        if preview.consumed_at_ms.is_some() || preview.expires_at_ms < input.now_ms {
            return Err(AppError::Budget("cost preview is expired or already consumed".to_owned()));
        }
        if signed_preview_hash(&preview.normalized_intent_json, &preview.plan_contract_json) != preview.plan_sha256 {
            return Err(AppError::DatabaseInvariant("cost plan hash mismatch".to_owned()));
        }
        let calls: Vec<PlannedCallInput> = serde_json::from_str(&preview.plan_contract_json)?;
        for call in &calls {
            call.validate_shape()?;
        }
        verify_persisted_plan(&transaction, input.consent_token, &calls)?;
        validate_calls(&transaction, &calls, input.now_ms)?;
        let maximum = sum_call_reservations(&calls)?;
        if maximum != preview.maximum {
            return Err(AppError::DatabaseInvariant("cost plan total mismatch".to_owned()));
        }

        let budgets = budget_snapshot(&transaction, preview.project_id, &preview.run_scope_key)?;
        let project_committed = if is_m11_calibration_scope(&preview.run_scope_key) {
            0
        } else {
            committed_for_project(&transaction, preview.project_id)?
        };
        let run_committed = committed_for_run(&transaction, preview.project_id, &preview.run_scope_key)?;
        enforce_budget(maximum, project_committed, run_committed, budgets)?;

        let job_id = Uuid::new_v4();
        let intent_id = Uuid::new_v4();
        // The durable research-run identity is Rust-owned and is also the
        // worker-visible job-bound run ID.
        let research_run_id = job_id;
        transaction.execute(
            "INSERT INTO job(id, project_id, run_scope_key, operation, state, idempotency_key, protocol_version, payload_schema, input_sha256, phase, created_at_ms) VALUES (?1, ?2, ?3, 'research.run', 'QUEUED', ?4, '1.0.0', ?5, ?6, 'queued', ?7)",
            params![job_id.to_string(), preview.project_id.to_string(), preview.run_scope_key,
                input.consent_token.to_string(), format!("research-intent/{}", input.schema_version),
                input.input_sha256, input.now_ms],
        )?;
        transaction.execute(
            "INSERT INTO research_intent_revision(id, schema_version, raw_user_query, request_contract_json, canonical_contract_json, input_sha256, created_at_ms) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
            params![intent_id.to_string(), input.schema_version, input.raw_query, input.input_contract_json,
                preview.normalized_intent_json, input.input_sha256, input.now_ms],
        )?;
        transaction.execute(
            "INSERT INTO research_run(id, job_id, intent_revision_id, status, freshness_cutoff_ms, locale, warning_micro_usd, hard_micro_usd, created_at_ms) VALUES (?1, ?2, ?3, 'QUEUED', ?4, ?5, ?6, ?7, ?8)",
            params![research_run_id.to_string(), job_id.to_string(), intent_id.to_string(),
                freshness_cutoff_ms, normalized_intent.region(), budgets.warning, budgets.effective_hard,
                input.now_ms],
        )?;

        let persisted_calls = persisted_call_ids(&transaction, input.consent_token)?;
        if persisted_calls.len() != calls.len() {
            return Err(AppError::DatabaseInvariant("planned call count changed".to_owned()));
        }
        for (call_id, call) in persisted_calls.into_iter().zip(&calls) {
            transaction.execute(
                "UPDATE planned_provider_call SET provider_run_id=?2 WHERE id=?1 AND provider_run_id IS NULL",
                params![call_id.to_string(), Uuid::new_v4().to_string()],
            )?;
            transaction.execute(
                "INSERT INTO cost_entry(id, job_id, planned_call_id, price_card_id, state, category, micro_usd, idempotency_key, created_at_ms) VALUES (?1, ?2, ?3, ?4, 'RESERVED', 'research.call.maximum', ?5, ?6, ?7)",
                params![Uuid::new_v4().to_string(), job_id.to_string(), call_id.to_string(),
                    call.price_card_id.map(|value| value.to_string()), call.reservation_micro_usd,
                    format!("reserve:{job_id}:{call_id}"), input.now_ms],
            )?;
            if call.requires_live_call {
                transaction.execute(
                    "INSERT INTO provider_quota_entry(id, job_id, planned_call_id, provider, state, requests, tool_calls, input_tokens, output_tokens, idempotency_key, created_at_ms) VALUES (?1, ?2, ?3, ?4, 'RESERVED', ?5, ?6, ?7, ?8, ?9, ?10)",
                    params![Uuid::new_v4().to_string(), job_id.to_string(), call_id.to_string(),
                        call.provider, call.max_requests, call.max_tool_calls, call.max_input_tokens, call.max_output_tokens,
                        format!("quota-reserve:{job_id}:{call_id}"), input.now_ms],
                )?;
            }
        }
        transaction.execute(
            "INSERT INTO job_event(job_id, sequence, event_type, occurred_at_ms, sanitized_payload_json) VALUES (?1, 0, 'QUEUED', ?2, '{\"phase\":\"queued\"}')",
            params![job_id.to_string(), input.now_ms],
        )?;
        let changed = transaction.execute(
            "UPDATE cost_preview SET consumed_at_ms = ?2 WHERE consent_token = ?1 AND consumed_at_ms IS NULL",
            params![input.consent_token.to_string(), input.now_ms],
        )?;
        if changed != 1 {
            return Err(AppError::Budget("cost preview was consumed concurrently".to_owned()));
        }
        transaction.commit()?;
        Ok(JobRecord {
            id: job_id,
            state: "QUEUED".to_owned(),
            progress_percent: 0,
            phase: "queued".to_owned(),
            result_contract_json: None,
            sanitized_error: None,
        })
    }

    /// Claim the one permitted executor for a queued job and, for a live
    /// cache-miss plan, acquire the intent-scoped single-flight lease in the
    /// same immediate transaction.  A duplicate intent already in flight is
    /// failed and its untouched reservations are released rather than allowing
    /// a second paid execution.
    pub fn claim_research_execution(&mut self, job_id: Uuid, now_ms: i64) -> AppResult<bool> {
        let transaction = self.connection_mut().transaction_with_behavior(TransactionBehavior::Immediate)?;
        let changed = transaction.execute(
            "UPDATE job SET attempt=1 WHERE id=?1 AND state='QUEUED' AND attempt=0",
            [job_id.to_string()],
        )?;
        if changed == 0 {
            transaction.commit()?;
            return Ok(false);
        }
        let input_sha256: String = transaction.query_row(
            "SELECT input_sha256 FROM job WHERE id=?1",
            [job_id.to_string()],
            |row| row.get(0),
        )?;
        let has_live: bool = transaction.query_row(
            "SELECT EXISTS(SELECT 1 FROM planned_provider_call call JOIN job ON call.consent_token=job.idempotency_key WHERE job.id=?1 AND call.requires_live_call=1)",
            [job_id.to_string()],
            |row| row.get(0),
        )?;
        if has_live {
            let lease_expires_at_ms = now_ms.saturating_add(6 * 60 * 1000);
            let leased = transaction.execute(
                "INSERT INTO cache_flight(namespace,cache_key,input_sha256,lease_owner,lease_expires_at_ms,created_at_ms)
                 VALUES (?1,?2,?2,?3,?4,?5)
                 ON CONFLICT(namespace,cache_key) DO UPDATE SET input_sha256=excluded.input_sha256,lease_owner=excluded.lease_owner,lease_expires_at_ms=excluded.lease_expires_at_ms,created_at_ms=excluded.created_at_ms
                 WHERE cache_flight.input_sha256=excluded.input_sha256 AND (cache_flight.lease_expires_at_ms<?5 OR cache_flight.lease_owner=?3)",
                params![crate::provider_catalog::BUNDLE_CACHE_NAMESPACE, input_sha256,
                    job_id.to_string(), lease_expires_at_ms, now_ms],
            )? == 1;
            if !leased {
                let message = "An identical research request is already running. Retry after it finishes to reuse its validated cache.";
                transaction.execute(
                    "UPDATE job SET state='FAILED',phase='duplicate research already in flight',sanitized_error=?2,finished_at_ms=?3 WHERE id=?1 AND state='QUEUED'",
                    params![job_id.to_string(), message, now_ms],
                )?;
                transaction.execute(
                    "UPDATE research_run SET status='FAILED',finished_at_ms=?2 WHERE job_id=?1 AND status='QUEUED'",
                    params![job_id.to_string(), now_ms],
                )?;
                transaction.execute(
                    "UPDATE cost_entry SET state='RELEASED',reconciled_at_ms=?2 WHERE job_id=?1 AND state='RESERVED'",
                    params![job_id.to_string(), now_ms],
                )?;
                transaction.execute(
                    "UPDATE provider_quota_entry SET state='RELEASED' WHERE job_id=?1 AND state='RESERVED'",
                    [job_id.to_string()],
                )?;
                transaction.commit()?;
                return Ok(false);
            }
        }
        transaction.commit()?;
        Ok(true)
    }

    pub fn job(&self, job_id: Uuid) -> AppResult<JobRecord> {
        job_from_connection(self.connection(), job_id)
    }

    /// Return a renderer-facing job only while every persisted evidence source
    /// behind its result is still usable under its immutable deadlines.
    pub fn job_for_display(&mut self, job_id: Uuid, now_ms: i64) -> AppResult<JobRecord> {
        self.run_policy_maintenance(now_ms)?;
        let record = self.job(job_id)?;
        if record.state != "SUCCEEDED" {
            return Ok(record);
        }
        if record.result_contract_json.is_none() {
            return if record.phase == "research result expired by evidence policy" {
                Err(AppError::Validation(
                    "research evidence expired; run fresh research before using this result"
                        .to_owned(),
                ))
            } else {
                Err(AppError::DatabaseInvariant(
                    "successful research job has no display result".to_owned(),
                ))
            };
        }
        let has_unusable_evidence = self.connection().query_row(
            "SELECT EXISTS(
                SELECT 1
                FROM research_run run, json_each(run.evidence_sources_json) item
                LEFT JOIN evidence_source source ON source.id=json_extract(item.value,'$.sourceId')
                WHERE run.job_id=?1 AND (
                    source.id IS NULL OR source.deleted_at_ms IS NOT NULL
                    OR source.fetch_status!='SUCCESS'
                    OR source.expires_at_ms IS NULL OR source.expires_at_ms<=?2
                    OR source.purge_due_at_ms IS NULL OR source.purge_due_at_ms<=?2
                    OR (source.deletion_required_at_ms IS NOT NULL AND source.deletion_required_at_ms<=?2)
                )
            )",
            params![job_id.to_string(), now_ms],
            |row| row.get::<_, bool>(0),
        )?;
        if has_unusable_evidence {
            return Err(AppError::Validation(
                "research evidence expired; run fresh research before using this result"
                    .to_owned(),
            ));
        }
        Ok(record)
    }

    pub fn request_cancellation(&mut self, job_id: Uuid, now_ms: i64) -> AppResult<JobRecord> {
        let transaction = self.connection_mut().transaction_with_behavior(TransactionBehavior::Immediate)?;
        let prior_state = transaction.query_row(
            "SELECT state FROM job WHERE id=?1",
            [job_id.to_string()],
            |row| row.get::<_, String>(0),
        ).optional()?.ok_or_else(|| AppError::NotFound("job was not found".to_owned()))?;
        if prior_state == "QUEUED" {
            transaction.execute(
                "UPDATE job SET state='CANCELLED', phase='cancelled before provider start', cancellation_requested_at_ms=?2, finished_at_ms=?2 WHERE id=?1",
                params![job_id.to_string(), now_ms],
            )?;
            transaction.execute(
                "UPDATE research_run SET status='CANCELLED', finished_at_ms=?2 WHERE job_id=?1 AND status='QUEUED'",
                params![job_id.to_string(), now_ms],
            )?;
            transaction.execute(
                "UPDATE cost_entry SET state='RELEASED', reconciled_at_ms=?2 WHERE job_id=?1 AND state='RESERVED'",
                params![job_id.to_string(), now_ms],
            )?;
            transaction.execute(
                "UPDATE provider_quota_entry SET state='RELEASED' WHERE job_id=?1 AND state='RESERVED'",
                [job_id.to_string()],
            )?;
            transaction.execute(
                "INSERT INTO job_event(job_id, sequence, event_type, occurred_at_ms, sanitized_payload_json) VALUES (?1, COALESCE((SELECT MAX(sequence)+1 FROM job_event WHERE job_id=?1),0), 'CANCELLED', ?2, '{\"beforeProviderStart\":true}')",
                params![job_id.to_string(), now_ms],
            )?;
            transaction.execute(
                "DELETE FROM cache_flight WHERE namespace=?1 AND lease_owner=?2",
                params![crate::provider_catalog::BUNDLE_CACHE_NAMESPACE, job_id.to_string()],
            )?;
            let record = job_from_transaction(&transaction, job_id)?;
            transaction.commit()?;
            return Ok(record);
        }
        let changed = transaction.execute(
            "UPDATE job SET state = CASE WHEN state IN ('QUEUED', 'RUNNING') THEN 'CANCELLING' ELSE state END, phase = CASE WHEN state IN ('QUEUED', 'RUNNING') THEN 'cancellation requested' ELSE phase END, cancellation_requested_at_ms = CASE WHEN state IN ('QUEUED', 'RUNNING') THEN ?2 ELSE cancellation_requested_at_ms END WHERE id = ?1",
            params![job_id.to_string(), now_ms],
        )?;
        if changed == 0 {
            return Err(AppError::NotFound("job was not found".to_owned()));
        }
        transaction.execute(
            "UPDATE research_run SET status = 'CANCELLING' WHERE job_id = ?1 AND status IN ('QUEUED', 'RUNNING')",
            [job_id.to_string()],
        )?;
        let record = job_from_transaction(&transaction, job_id)?;
        transaction.commit()?;
        Ok(record)
    }

    pub fn resolve_external_link(&mut self, handle: Uuid, now_ms: i64) -> AppResult<String> {
        self.run_policy_maintenance(now_ms)?;
        self.connection()
            .query_row(
                "SELECT link.canonical_https_url
                 FROM external_link link
                 JOIN evidence_source source ON source.id=link.evidence_source_id
                 WHERE link.handle=?1 AND source.deleted_at_ms IS NULL
                   AND source.fetch_status='SUCCESS'
                   AND source.expires_at_ms IS NOT NULL AND source.expires_at_ms>?2
                   AND source.purge_due_at_ms IS NOT NULL AND source.purge_due_at_ms>?2
                   AND (source.deletion_required_at_ms IS NULL OR source.deletion_required_at_ms>?2)",
                params![handle.to_string(), now_ms],
                |row| row.get(0),
            )
            .optional()?
            .ok_or_else(|| AppError::NotFound("evidence link was not found".to_owned()))
    }

    pub fn cache_get(&mut self, input: &CacheReadInput<'_>) -> AppResult<Option<String>> {
        validate_sha256(input.input_sha256)?;
        validate_sha256(input.output_sha256)?;
        let transaction = self.connection_mut().transaction_with_behavior(TransactionBehavior::Immediate)?;
        let value = transaction
            .query_row(
                "SELECT cache.contract_json, cache.output_sha256 FROM cache_entry cache
                 JOIN provider_policy policy ON policy.provider=cache.provider
                 WHERE cache.namespace=?1 AND cache.cache_key=?2 AND cache.input_sha256=?3 AND cache.output_sha256=?4
                   AND cache.schema_version=?5 AND cache.model_version=?6 AND cache.prompt_version=?7 AND cache.policy_class=?8
                   AND cache.state='VALID' AND cache.expires_at_ms>=?9 AND (cache.purge_at_ms IS NULL OR cache.purge_at_ms>?9)
                   AND policy.enabled=1 AND policy.kill_switch_reason IS NULL AND policy.policy_class=cache.policy_class
                   AND policy.checked_at_ms<=?9 AND policy.expires_at_ms>=?9",
                params![input.namespace, input.key, input.input_sha256, input.output_sha256,
                    input.schema_version, input.model_version, input.prompt_version,
                    input.policy_class, input.now_ms],
                |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?)),
            )
            .optional()?;
        let result = if let Some((contract, persisted_hash)) = value {
            let valid = serde_json::from_str::<serde_json::Value>(&contract).is_ok()
                && sha256_hex(contract.as_bytes()) == persisted_hash.to_ascii_lowercase();
            if !valid {
                transaction.execute(
                    "UPDATE cache_entry SET state='STALE' WHERE namespace=?1 AND cache_key=?2",
                    params![input.namespace, input.key],
                )?;
                None
            } else {
                transaction.execute(
                    "UPDATE cache_entry SET accessed_at_ms=?3 WHERE namespace=?1 AND cache_key=?2",
                    params![input.namespace, input.key, input.now_ms],
                )?;
                Some(contract)
            }
        } else {
            None
        };
        if result.is_some() {
            transaction.execute(
                "DELETE FROM cache_flight WHERE namespace=?1 AND cache_key=?2 AND input_sha256=?3",
                params![input.namespace, input.key, input.input_sha256],
            )?;
        }
        transaction.commit()?;
        Ok(result)
    }

    pub fn whole_bundle_cache_binding(&self, input_sha256: &str, now_ms: i64) -> AppResult<Option<WholeBundleCacheBinding>> {
        validate_sha256(input_sha256)?;
        let row = self.connection().query_row(
            "SELECT cache.output_sha256,cache.contract_json FROM cache_entry cache
             JOIN provider_policy policy ON policy.provider=cache.provider
             WHERE cache.namespace=?1 AND cache.cache_key=?2 AND cache.input_sha256=?2
               AND cache.schema_version=?3 AND cache.model_version=?4 AND cache.prompt_version=?5
               AND cache.policy_class=?6 AND cache.state='VALID' AND cache.expires_at_ms>=?7
               AND (cache.purge_at_ms IS NULL OR cache.purge_at_ms>?7)
               AND policy.enabled=1 AND policy.kill_switch_reason IS NULL
               AND policy.policy_class=cache.policy_class AND policy.checked_at_ms<=?7 AND policy.expires_at_ms>=?7",
            params![crate::provider_catalog::BUNDLE_CACHE_NAMESPACE, input_sha256,
                crate::provider_catalog::BUNDLE_CACHE_SCHEMA, crate::provider_catalog::BUNDLE_CACHE_MODEL,
                crate::provider_catalog::BUNDLE_CACHE_PROMPT, crate::provider_catalog::BUNDLE_CACHE_POLICY, now_ms],
            |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?)),
        ).optional()?;
        Ok(row.and_then(|(hash, contract)| {
            (validate_sha256(&hash).is_ok()
                && crate::worker::protocol::parse_strict_json_bytes(contract.as_bytes()).is_ok()
                && sha256_hex(contract.as_bytes()) == hash)
                .then_some(WholeBundleCacheBinding { output_sha256: hash })
        }))
    }

    pub fn whole_bundle_replay(&mut self, job_id: Uuid, now_ms: i64) -> AppResult<Option<WholeBundleReplay>> {
        let binding = self.connection().query_row(
            "SELECT call.id,call.provider_run_id,job.input_sha256,call.cache_output_sha256
             FROM job JOIN planned_provider_call call ON call.consent_token=job.idempotency_key
             WHERE job.id=?1 AND call.cost_kind='LOCAL_CACHE' AND call.cache_status='HIT'
               AND call.requires_live_call=0 AND call.provider_run_id IS NOT NULL",
            [job_id.to_string()],
            |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?, row.get::<_, String>(2)?, row.get::<_, String>(3)?)),
        ).optional()?;
        let Some((call_id, provider_run_id, input_sha256, output_sha256)) = binding else { return Ok(None); };
        let contract = self.cache_get(&CacheReadInput {
            namespace: crate::provider_catalog::BUNDLE_CACHE_NAMESPACE,
            key: &input_sha256,
            input_sha256: &input_sha256,
            output_sha256: &output_sha256,
            schema_version: crate::provider_catalog::BUNDLE_CACHE_SCHEMA,
            model_version: crate::provider_catalog::BUNDLE_CACHE_MODEL,
            prompt_version: crate::provider_catalog::BUNDLE_CACHE_PROMPT,
            policy_class: crate::provider_catalog::BUNDLE_CACHE_POLICY,
            now_ms,
        })?;
        contract.map(|contract_json| Ok(WholeBundleReplay {
            planned_call_id: parse_uuid(&call_id, "cache planned call ID")?,
            provider_run_id: parse_uuid(&provider_run_id, "cache provider run ID")?,
            input_sha256,
            output_sha256,
            contract_json,
        })).transpose()
    }

    pub fn record_whole_bundle_replay(&mut self, job_id: Uuid, replay: &WholeBundleReplay, now_ms: i64) -> AppResult<()> {
        let transaction = self.connection_mut().transaction_with_behavior(TransactionBehavior::Immediate)?;
        let binding = transaction.query_row(
            "SELECT call.provider,call.configured_model,call.resolved_model,call.retention_summary,call.data_use_summary,call.privacy_mode,job.state
             FROM planned_provider_call call JOIN job ON call.consent_token=job.idempotency_key
             WHERE job.id=?1 AND call.id=?2 AND call.provider_run_id=?3 AND call.cache_status='HIT'
               AND call.cache_output_sha256=?4 AND job.input_sha256=?5",
            params![job_id.to_string(), replay.planned_call_id.to_string(), replay.provider_run_id.to_string(),
                replay.output_sha256, replay.input_sha256],
            |row| Ok((row.get::<_, String>(0)?, row.get::<_, Option<String>>(1)?, row.get::<_, Option<String>>(2)?,
                row.get::<_, String>(3)?, row.get::<_, String>(4)?, row.get::<_, String>(5)?, row.get::<_, String>(6)?)),
        ).optional()?.ok_or_else(|| AppError::Security("cache replay is not bound to the research job".to_owned()))?;
        if !matches!(binding.6.as_str(), "QUEUED" | "RUNNING") {
            return Err(AppError::DatabaseInvariant("cache replay targeted a non-active job".to_owned()));
        }
        let inserted = transaction.execute(
            "INSERT INTO provider_run(id,job_id,planned_call_id,provider,configured_model,resolved_model,capability,prompt_version,schema_version,outcome,input_sha256,output_sha256,retention_mode,data_use_mode,privacy_mode,requests,input_tokens,cached_input_tokens,output_tokens,reasoning_tokens,tool_invocations,repair_used,tool_usage_json,started_at_ms,finished_at_ms)
             VALUES (?1,?2,?3,?4,?5,?6,'trusted whole-result cache replay',?7,'2.0.0','SUCCESS',?8,?9,?10,?11,?12,0,0,0,0,0,0,0,'[]',?13,?13)
             ON CONFLICT(planned_call_id) DO NOTHING",
            params![replay.provider_run_id.to_string(), job_id.to_string(), replay.planned_call_id.to_string(),
                binding.0, binding.1, binding.2, crate::provider_catalog::BUNDLE_CACHE_PROMPT,
                replay.input_sha256, replay.output_sha256, binding.3, binding.4, binding.5, now_ms],
        )?;
        if inserted == 0 {
            let exact = transaction.query_row(
                "SELECT 1 FROM provider_run WHERE id=?1 AND job_id=?2 AND planned_call_id=?3 AND outcome='SUCCESS' AND output_sha256=?4",
                params![replay.provider_run_id.to_string(), job_id.to_string(), replay.planned_call_id.to_string(), replay.output_sha256], |_| Ok(()),
            ).optional()?.is_some();
            if !exact { return Err(AppError::DatabaseInvariant("cache replay provider run identity was reused".to_owned())); }
        }
        transaction.execute(
            "UPDATE cost_entry SET state='RELEASED',reconciled_at_ms=?3 WHERE job_id=?1 AND planned_call_id=?2 AND state='RESERVED'",
            params![job_id.to_string(), replay.planned_call_id.to_string(), now_ms],
        )?;
        transaction.execute(
            "INSERT INTO cost_entry(id,job_id,planned_call_id,provider_run_id,state,category,micro_usd,idempotency_key,created_at_ms,reconciled_at_ms)
             VALUES (?1,?2,?3,?4,'ACTUAL','research.cache.replay',0,?5,?6,?6) ON CONFLICT(idempotency_key) DO NOTHING",
            params![Uuid::new_v4().to_string(), job_id.to_string(), replay.planned_call_id.to_string(),
                replay.provider_run_id.to_string(), format!("cache-replay:{job_id}:{}", replay.planned_call_id), now_ms],
        )?;
        transaction.execute(
            "UPDATE job SET state='RUNNING',phase='validated local research cache',started_at_ms=COALESCE(started_at_ms,?2),heartbeat_at_ms=?2 WHERE id=?1 AND state='QUEUED'",
            params![job_id.to_string(), now_ms],
        )?;
        transaction.execute("UPDATE research_run SET status='RUNNING' WHERE job_id=?1 AND status='QUEUED'", [job_id.to_string()])?;
        transaction.commit()?;
        Ok(())
    }

    pub fn acquire_cache_lease(
        &mut self,
        namespace: &str,
        key: &str,
        input_sha256: &str,
        owner: Uuid,
        now_ms: i64,
        lease_expires_at_ms: i64,
    ) -> AppResult<bool> {
        if lease_expires_at_ms <= now_ms {
            return Err(AppError::Validation("cache lease must expire in the future".to_owned()));
        }
        validate_sha256(input_sha256)?;
        let changed = self.connection_mut().execute(
            "INSERT INTO cache_flight(namespace, cache_key, input_sha256, lease_owner, lease_expires_at_ms, created_at_ms)
             VALUES (?1, ?2, ?3, ?4, ?6, ?5)
             ON CONFLICT(namespace, cache_key) DO UPDATE SET input_sha256=excluded.input_sha256, lease_owner=excluded.lease_owner, lease_expires_at_ms=excluded.lease_expires_at_ms, created_at_ms=excluded.created_at_ms
             WHERE cache_flight.input_sha256=excluded.input_sha256 AND (cache_flight.lease_expires_at_ms < ?5 OR cache_flight.lease_owner = ?4)",
            params![namespace, key, input_sha256, owner.to_string(), now_ms, lease_expires_at_ms],
        )?;
        Ok(changed == 1)
    }

    pub fn reservation_capabilities(&self, job_id: Uuid) -> AppResult<Vec<ReservationCapability>> {
        let mut statement = self.connection().prepare(
            "SELECT cost.id, cost.planned_call_id, call.provider_run_id, call.provider, call.operation, call.configured_model, call.resolved_model, cost.micro_usd, call.max_requests, call.max_tool_calls, call.max_input_tokens, call.max_output_tokens, call.allow_one_repair, call.retention_summary, call.data_use_summary, call.no_storage_mode, call.privacy_mode, call.provider_config_json, call.policy_class, call.evidence_ttl_seconds, call.refresh_after_seconds, call.purge_after_seconds, call.deletion_after_seconds
             FROM cost_entry cost JOIN planned_provider_call call ON call.id = cost.planned_call_id
             JOIN provider_policy policy ON policy.provider=call.provider
             WHERE cost.job_id=?1 AND cost.state='RESERVED' AND call.requires_live_call=1 AND call.provider_run_id IS NOT NULL ORDER BY call.display_order",
        )?;
        let rows = statement
            .query_map([job_id.to_string()], |row| {
                Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?, row.get::<_, String>(2)?,
                    row.get::<_, String>(3)?, row.get::<_, String>(4)?, row.get::<_, Option<String>>(5)?,
                    row.get::<_, Option<String>>(6)?, row.get::<_, i64>(7)?, row.get::<_, i64>(8)?,
                    row.get::<_, i64>(9)?, row.get::<_, i64>(10)?, row.get::<_, i64>(11)?, row.get::<_, bool>(12)?,
                    row.get::<_, String>(13)?, row.get::<_, String>(14)?, row.get::<_, String>(15)?,
                    row.get::<_, String>(16)?, row.get::<_, String>(17)?, row.get::<_, String>(18)?,
                    row.get::<_, i64>(19)?, row.get::<_, i64>(20)?, row.get::<_, i64>(21)?,
                    row.get::<_, Option<i64>>(22)?))
            })?
            .collect::<Result<Vec<_>, _>>()?;
        rows.into_iter().map(|row| Ok(ReservationCapability {
            reservation_id: parse_uuid(&row.0, "reservation ID")?,
            job_id,
            planned_call_id: parse_uuid(&row.1, "planned call ID")?,
            provider_run_id: parse_uuid(&row.2, "provider run ID")?,
            provider: row.3,
            operation: row.4,
            configured_model: row.5,
            resolved_model: row.6,
            maximum_micro_usd: row.7,
            max_requests: row.8,
            max_tool_calls: row.9,
            max_input_tokens: row.10,
            max_output_tokens: row.11,
            allow_one_repair: row.12,
            retention_mode: row.13,
            data_use_mode: row.14,
            no_storage_mode: row.15,
            privacy_mode: row.16,
            provider_config: serde_json::from_str(&row.17)
                .map_err(|_| AppError::DatabaseInvariant("provider config is invalid".to_owned()))?,
            policy_class: row.18,
            evidence_ttl_seconds: row.19,
            refresh_after_seconds: row.20,
            purge_after_seconds: row.21,
            deletion_after_seconds: row.22,
        })).collect()
    }

    pub fn begin_provider_run(&mut self, input: &BeginProviderRun<'_>) -> AppResult<()> {
        validate_sha256(input.input_sha256)?;
        let transaction = self.connection_mut().transaction_with_behavior(TransactionBehavior::Immediate)?;
        let call = transaction
            .query_row(
                "SELECT call.provider, call.configured_model, call.resolved_model, call.retention_summary, call.data_use_summary, call.privacy_mode,
                        job.state, policy.enabled, policy.kill_switch_reason, policy.checked_at_ms, policy.expires_at_ms,call.cost_kind,call.price_card_id
                 FROM planned_provider_call call JOIN cost_entry cost ON cost.planned_call_id=call.id
                 JOIN job ON job.id=cost.job_id JOIN provider_policy policy ON policy.provider=call.provider
                 WHERE call.id=?1 AND cost.job_id=?2 AND call.provider_run_id=?3 AND cost.state='RESERVED'",
                params![input.planned_call_id.to_string(), input.job_id.to_string(), input.provider_run_id.to_string()],
                |row| Ok((row.get::<_, String>(0)?, row.get::<_, Option<String>>(1)?, row.get::<_, Option<String>>(2)?, row.get::<_, String>(3)?, row.get::<_, String>(4)?, row.get::<_, String>(5)?, row.get::<_, String>(6)?, row.get::<_, bool>(7)?, row.get::<_, Option<String>>(8)?, row.get::<_, i64>(9)?, row.get::<_, i64>(10)?, row.get::<_, String>(11)?, row.get::<_, Option<String>>(12)?)),
            )
            .optional()?
            .ok_or_else(|| AppError::Budget("active reservation was not found".to_owned()))?;
        if call.3 != input.retention_mode || call.4 != input.data_use_mode || call.5 != input.privacy_mode {
            return Err(AppError::Security("worker privacy capability does not match the approved plan".to_owned()));
        }
        if !matches!(call.6.as_str(), "QUEUED" | "RUNNING")
            || !call.7 || call.8.is_some() || call.9 > input.now_ms || call.10 < input.now_ms
        {
            return Err(AppError::Provider("provider call was blocked by current job or provider policy state".to_owned()));
        }
        if call.11 == "PAID_CLOUD" {
            let configured = call.1.as_deref().ok_or_else(|| AppError::DatabaseInvariant("paid provider start lost configured model".to_owned()))?;
            let resolved = call.2.as_deref().ok_or_else(|| AppError::DatabaseInvariant("paid provider start lost resolved model".to_owned()))?;
            let preflight_ok = transaction.query_row(
                "SELECT 1 FROM provider_model_preflight WHERE provider=?1 AND configured_model=?2 AND resolved_model=?3 AND available=1 AND checked_at_ms<=?4 AND expires_at_ms>=?4",
                params![call.0, configured, resolved, input.now_ms],
                |_| Ok(()),
            ).optional()?.is_some();
            let price_id = call.12.as_deref().ok_or_else(|| AppError::DatabaseInvariant("paid provider start lost price-card binding".to_owned()))?;
            let price_ok = transaction.query_row(
                "SELECT 1 FROM price_card WHERE id=?1 AND provider=?2 AND model=?3 AND effective_at_ms<=?4 AND checked_at_ms<=?4 AND expires_at_ms>=?4",
                params![price_id, call.0, resolved, input.now_ms],
                |_| Ok(()),
            ).optional()?.is_some();
            if !preflight_ok || !price_ok {
                return Err(AppError::Provider("paid provider call was blocked by stale model or pricing preflight".to_owned()));
            }
        }
        let inserted = transaction.execute(
            "INSERT INTO provider_run(id, job_id, planned_call_id, provider, configured_model, resolved_model, capability, prompt_version, schema_version, outcome, input_sha256, retention_mode, data_use_mode, privacy_mode, started_at_ms)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, 'PENDING', ?10, ?11, ?12, ?13, ?14)
             ON CONFLICT(planned_call_id) DO NOTHING",
            params![input.provider_run_id.to_string(), input.job_id.to_string(), input.planned_call_id.to_string(),
                call.0, call.1, call.2, input.capability, input.prompt_version, input.schema_version,
                input.input_sha256, input.retention_mode, input.data_use_mode, input.privacy_mode, input.now_ms],
        )?;
        if inserted == 0 {
            let exact = transaction.query_row(
                "SELECT 1 FROM provider_run WHERE id=?1 AND job_id=?2 AND planned_call_id=?3 AND input_sha256=?4 AND capability=?5 AND outcome='PENDING'",
                params![input.provider_run_id.to_string(), input.job_id.to_string(), input.planned_call_id.to_string(), input.input_sha256, input.capability],
                |_| Ok(()),
            ).optional()?.is_some();
            if !exact {
                return Err(AppError::DatabaseInvariant("provider run already exists with a different binding".to_owned()));
            }
        }
        transaction.execute(
            "UPDATE job SET state='RUNNING', phase='provider research', started_at_ms=COALESCE(started_at_ms, ?2), heartbeat_at_ms=?2 WHERE id=?1 AND state='QUEUED'",
            params![input.job_id.to_string(), input.now_ms],
        )?;
        transaction.execute(
            "UPDATE research_run SET status='RUNNING' WHERE job_id=?1 AND status='QUEUED'",
            [input.job_id.to_string()],
        )?;
        transaction.commit()?;
        Ok(())
    }

    pub fn reconcile_provider_run(&mut self, input: &ReconcileProviderRun<'_>) -> AppResult<ReconciliationRecord> {
        if !matches!(input.outcome, "SUCCESS" | "REFUSAL" | "INCOMPLETE" | "FAILED") {
            return Err(AppError::Validation("provider outcome is invalid".to_owned()));
        }
        if let Some(hash) = input.output_sha256 { validate_sha256(hash)?; }
        let tool_detail_count = if let Some(json) = input.tool_usage_json {
            let value: serde_json::Value = serde_json::from_str(json)?;
            Some(value.as_array().ok_or_else(|| AppError::Validation("tool usage must be a JSON array".to_owned()))?.len())
        } else {
            None
        };
        if input.cached_input_tokens.zip(input.input_tokens).is_some_and(|(cached, total)| cached > total) {
            return Err(AppError::Validation("cached input usage exceeds total input usage".to_owned()));
        }
        if input.tool_invocations.and_then(|count| usize::try_from(count).ok()).zip(tool_detail_count).is_some_and(|(count, details)| count != details) {
            return Err(AppError::Validation("tool usage detail count does not match tool invocations".to_owned()));
        }
        if input.provider_native_ticks.is_some_and(|value| value.is_empty() || !value.bytes().all(|byte| byte.is_ascii_digit())) {
            return Err(AppError::Validation("provider-native cost ticks are invalid".to_owned()));
        }
        for value in [input.requests, input.input_tokens, input.cached_input_tokens, input.output_tokens, input.reasoning_tokens, input.tool_invocations] {
            if value.is_some_and(|value| value < 0) {
                return Err(AppError::Validation("provider usage cannot be negative".to_owned()));
            }
        }
        let expected_idempotency = format!("reconcile:{}:{}", input.job_id, input.planned_call_id);
        if input.idempotency_key != expected_idempotency {
            return Err(AppError::Security("provider reconciliation idempotency binding is invalid".to_owned()));
        }
        let transaction = self.connection_mut().transaction_with_behavior(TransactionBehavior::Immediate)?;
        if let Some(existing) = transaction
            .query_row(
                "SELECT micro_usd, state, job_id, planned_call_id, provider_run_id FROM cost_entry WHERE idempotency_key=?1",
                [input.idempotency_key],
                |row| Ok((row.get::<_, i64>(0)?, row.get::<_, String>(1)?, row.get::<_, String>(2)?, row.get::<_, String>(3)?, row.get::<_, Option<String>>(4)?)),
            )
            .optional()?
        {
            let expected_job_id = input.job_id.to_string();
            let expected_call_id = input.planned_call_id.to_string();
            let expected_run_id = input.provider_run_id.to_string();
            if existing.2 != expected_job_id
                || existing.3 != input.planned_call_id.to_string()
                || existing.4.as_deref() != Some(expected_run_id.as_str())
            {
                return Err(AppError::Security("reconciliation replay has a different binding".to_owned()));
            }
            let persisted_usage = transaction.query_row(
                "SELECT provider_request_id,outcome,output_sha256,requests,input_tokens,cached_input_tokens,output_tokens,reasoning_tokens,tool_invocations,repair_used,tool_usage_json,provider_cost_ticks
                 FROM provider_run WHERE id=?1 AND job_id=?2 AND planned_call_id=?3",
                params![expected_run_id, expected_job_id, expected_call_id],
                |row| Ok((row.get::<_, Option<String>>(0)?, row.get::<_, String>(1)?, row.get::<_, Option<String>>(2)?,
                    row.get::<_, Option<i64>>(3)?, row.get::<_, Option<i64>>(4)?, row.get::<_, Option<i64>>(5)?,
                    row.get::<_, Option<i64>>(6)?, row.get::<_, Option<i64>>(7)?, row.get::<_, Option<i64>>(8)?,
                    row.get::<_, Option<bool>>(9)?, row.get::<_, Option<String>>(10)?, row.get::<_, Option<String>>(11)?)),
            )?;
            if persisted_usage.0.as_deref() != input.provider_request_id
                || persisted_usage.1 != input.outcome
                || persisted_usage.2.as_deref() != input.output_sha256
                || persisted_usage.3 != input.requests
                || persisted_usage.4 != input.input_tokens
                || persisted_usage.5 != input.cached_input_tokens
                || persisted_usage.6 != input.output_tokens
                || persisted_usage.7 != input.reasoning_tokens
                || persisted_usage.8 != input.tool_invocations
                || persisted_usage.9 != input.repair_used
                || persisted_usage.10.as_deref() != input.tool_usage_json
                || persisted_usage.11.as_deref() != input.provider_native_ticks
            {
                return Err(AppError::Security("reconciliation replay attempted to change immutable provider usage".to_owned()));
            }
            let requires_quota = transaction.query_row(
                "SELECT requires_live_call FROM planned_provider_call WHERE id=?1",
                [expected_call_id],
                |row| row.get::<_, bool>(0),
            )?;
            if requires_quota {
                let quota_matches = transaction.query_row(
                    "SELECT 1 FROM provider_quota_entry WHERE idempotency_key=?1 AND job_id=?2 AND planned_call_id=?3 AND state IN ('ACTUAL','UNVERIFIED')",
                    params![input.idempotency_key, expected_job_id, input.planned_call_id.to_string()],
                    |_| Ok(()),
                ).optional()?.is_some();
                if !quota_matches {
                    return Err(AppError::DatabaseInvariant("reconciled cost is missing its atomic quota record".to_owned()));
                }
            }
            let reservation = reservation_amount(&transaction, input.job_id, input.planned_call_id)?;
            let record = ReconciliationRecord {
                charged_or_held_micro_usd: existing.0,
                usage_verified: existing.1 == "ACTUAL",
                exceeded_reservation: existing.0 > reservation,
            };
            transaction.commit()?;
            return Ok(record);
        }
        let reservation = reservation_amount(&transaction, input.job_id, input.planned_call_id)?;
        let binding = transaction
            .query_row(
                "SELECT call.price_card_id, call.provider, call.max_requests, call.max_tool_calls, call.max_input_tokens, call.max_output_tokens, call.allow_one_repair, call.requires_live_call, call.cost_kind
                 FROM provider_run run JOIN planned_provider_call call ON call.id=run.planned_call_id
                 WHERE run.id=?1 AND run.job_id=?2 AND run.planned_call_id=?3 AND run.outcome='PENDING'",
                params![input.provider_run_id.to_string(), input.job_id.to_string(), input.planned_call_id.to_string()],
                |row| Ok((row.get::<_, Option<String>>(0)?, row.get::<_, String>(1)?, row.get::<_, i64>(2)?, row.get::<_, i64>(3)?, row.get::<_, i64>(4)?, row.get::<_, i64>(5)?, row.get::<_, bool>(6)?, row.get::<_, bool>(7)?, row.get::<_, String>(8)?)),
            )
            .optional()?
            .ok_or_else(|| AppError::DatabaseInvariant("pending provider run binding is missing".to_owned()))?;
        let reserved_quota = transaction
            .query_row(
                "SELECT requests, tool_calls, input_tokens, output_tokens FROM provider_quota_entry
                 WHERE job_id=?1 AND planned_call_id=?2 AND provider=?3 AND state='RESERVED'",
                params![input.job_id.to_string(), input.planned_call_id.to_string(), binding.1],
                |row| Ok((row.get::<_, i64>(0)?, row.get::<_, i64>(1)?, row.get::<_, i64>(2)?, row.get::<_, i64>(3)?)),
            )
            .optional()?;
        if binding.7 != reserved_quota.is_some() {
            return Err(AppError::DatabaseInvariant("provider quota reservation binding is inconsistent".to_owned()));
        }
        let complete_quota = if binding.7 {
            (binding.2 == 0 || input.requests.is_some())
                && (binding.3 == 0 || (input.tool_invocations.is_some() && tool_detail_count.is_some()))
                && (binding.4 == 0 || input.input_tokens.is_some())
                && (binding.5 == 0 || input.output_tokens.is_some())
                && (!binding.6 || input.repair_used.is_some())
        } else {
            true
        } && (
            !binding.7
                || input.requests.is_some_and(|value| value > 0)
                || (binding.8 == "FREE_METADATA" && input.requests == Some(0))
        );
        let actual_requests = input.requests.unwrap_or_else(|| reserved_quota.map_or(0, |value| value.0));
        let actual_tools = input.tool_invocations.unwrap_or_else(|| reserved_quota.map_or(0, |value| value.1));
        let actual_input = input.input_tokens.unwrap_or_else(|| reserved_quota.map_or(0, |value| value.2));
        let actual_output = input.output_tokens.unwrap_or_else(|| reserved_quota.map_or(0, |value| value.3));
        let within_quota = reserved_quota.is_none_or(|reserved| {
            actual_requests <= reserved.0
                && actual_tools <= reserved.1
                && actual_input <= reserved.2
                && actual_output <= reserved.3
                && actual_requests <= binding.2
                && actual_tools <= binding.3
                && actual_input <= binding.4
                && actual_output <= binding.5
                && (!input.repair_used.unwrap_or(false) || binding.6)
        });
        let derived_actual = derive_actual_cost(&transaction, input.planned_call_id, input)?;
        let (state, amount, verified) = match (complete_quota && within_quota, derived_actual) {
            (true, Some(actual)) => ("ACTUAL", actual, true),
            (_, actual) => ("UNVERIFIED", actual.unwrap_or(0).max(reservation), false),
        };
        transaction.execute(
            "UPDATE cost_entry SET state='RELEASED', reconciled_at_ms=?3 WHERE job_id=?1 AND planned_call_id=?2 AND state='RESERVED'",
            params![input.job_id.to_string(), input.planned_call_id.to_string(), input.now_ms],
        )?;
        transaction.execute(
            "INSERT INTO cost_entry(id, job_id, planned_call_id, provider_run_id, price_card_id, state, category, micro_usd, provider_native_ticks, idempotency_key, created_at_ms, reconciled_at_ms)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, 'research.call.reconciled', ?7, ?8, ?9, ?10, ?10)",
            params![Uuid::new_v4().to_string(), input.job_id.to_string(), input.planned_call_id.to_string(),
                input.provider_run_id.to_string(), binding.0, state, amount, input.provider_native_ticks,
                input.idempotency_key, input.now_ms],
        )?;
        if binding.7 {
            transaction.execute(
                "UPDATE provider_quota_entry SET state='RELEASED' WHERE job_id=?1 AND planned_call_id=?2 AND state='RESERVED'",
                params![input.job_id.to_string(), input.planned_call_id.to_string()],
            )?;
            transaction.execute(
                "INSERT INTO provider_quota_entry(id, job_id, planned_call_id, provider, state, requests, tool_calls, input_tokens, output_tokens, idempotency_key, created_at_ms)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11)",
                params![Uuid::new_v4().to_string(), input.job_id.to_string(), input.planned_call_id.to_string(),
                    binding.1, if verified { "ACTUAL" } else { "UNVERIFIED" }, actual_requests,
                    actual_tools, actual_input, actual_output, input.idempotency_key, input.now_ms],
            )?;
        }
        transaction.execute(
            "UPDATE provider_run SET provider_request_id=?2, outcome=?3, output_sha256=?4, requests=?5, input_tokens=?6, cached_input_tokens=?7, output_tokens=?8, reasoning_tokens=?9, tool_invocations=?10, repair_used=?11, tool_usage_json=?12, provider_cost_ticks=?13, finished_at_ms=?14 WHERE id=?1",
            params![input.provider_run_id.to_string(), input.provider_request_id, input.outcome,
                input.output_sha256, input.requests, input.input_tokens, input.cached_input_tokens,
                input.output_tokens, input.reasoning_tokens, input.tool_invocations,
                input.repair_used, input.tool_usage_json, input.provider_native_ticks, input.now_ms],
        )?;
        let exceeded = amount > reservation || !within_quota;
        if exceeded || !verified {
            let reconciliation_message = if exceeded {
                "Provider usage exceeded its reserved capability."
            } else if reservation == 0 {
                "Provider usage was incomplete for a $0.00 provider call; no paid reservation was held."
            } else {
                "Provider usage was incomplete; the full reservation remains held."
            };
            transaction.execute(
                "UPDATE job SET state='FAILED', phase=?3, sanitized_error=?4, finished_at_ms=?2 WHERE id=?1",
                params![input.job_id.to_string(), input.now_ms,
                    if exceeded { "provider capability exceeded" } else { "provider usage unverified" },
                    reconciliation_message],
            )?;
            transaction.execute(
                "UPDATE research_run SET status='FAILED', finished_at_ms=?2 WHERE job_id=?1",
                params![input.job_id.to_string(), input.now_ms],
            )?;
        }
        transaction.commit()?;
        Ok(ReconciliationRecord {
            charged_or_held_micro_usd: amount,
            usage_verified: verified,
            exceeded_reservation: exceeded,
        })
    }

    pub fn execution_context(&self, job_id: Uuid) -> AppResult<ResearchExecutionContext> {
        let (input_sha256, input_contract_json, normalized_intent_json) = self.connection().query_row(
            "SELECT job.input_sha256, intent.request_contract_json, intent.canonical_contract_json
             FROM job JOIN research_run run ON run.job_id=job.id
             JOIN research_intent_revision intent ON intent.id=run.intent_revision_id
             WHERE job.id=?1",
            [job_id.to_string()],
            |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?, row.get::<_, String>(2)?)),
        ).optional()?.ok_or_else(|| AppError::NotFound("research execution context was not found".to_owned()))?;
        Ok(ResearchExecutionContext {
            input_sha256,
            input_contract_json,
            normalized_intent_json,
            capabilities: self.reservation_capabilities(job_id)?,
        })
    }

    pub fn current_rfc3339(&self) -> AppResult<String> {
        Ok(self.connection().query_row(
            "SELECT strftime('%Y-%m-%dT%H:%M:%fZ','now')",
            [],
            |row| row.get(0),
        )?)
    }

    pub fn update_job_progress(&mut self, job_id: Uuid, percent: i64, phase: &str, now_ms: i64) -> AppResult<()> {
        if !(0..=100).contains(&percent) || phase.trim().is_empty() || phase.len() > 200 {
            return Err(AppError::Validation("worker progress is invalid".to_owned()));
        }
        // A worker may report that its local work is complete, but the trusted
        // host owns the terminal validation/persistence transition to 100%.
        let persisted_percent = percent.min(99);
        let changed = self.connection_mut().execute(
            "UPDATE job SET state='RUNNING', progress_percent=MAX(progress_percent,?2), phase=?3, heartbeat_at_ms=?4, started_at_ms=COALESCE(started_at_ms,?4)
             WHERE id=?1 AND state IN ('QUEUED','RUNNING')",
            params![job_id.to_string(), persisted_percent, phase, now_ms],
        )?;
        if changed != 1 { return Err(AppError::DatabaseInvariant("progress targeted a non-active job".to_owned())); }
        Ok(())
    }

    pub fn fail_job_safely(&mut self, job_id: Uuid, cancelled: bool, message: &str, now_ms: i64) -> AppResult<JobRecord> {
        let transaction = self.connection_mut().transaction_with_behavior(TransactionBehavior::Immediate)?;
        transaction.execute(
            "UPDATE provider_run SET outcome='FAILED', finished_at_ms=?2 WHERE job_id=?1 AND outcome='PENDING'",
            params![job_id.to_string(), now_ms],
        )?;
        transaction.execute(
            "DELETE FROM cache_flight WHERE namespace=?1 AND lease_owner=?2",
            params![crate::provider_catalog::BUNDLE_CACHE_NAMESPACE, job_id.to_string()],
        )?;
        transaction.execute(
            "UPDATE cost_entry SET state=CASE WHEN EXISTS(
                SELECT 1 FROM provider_run run WHERE run.job_id=cost_entry.job_id AND run.planned_call_id=cost_entry.planned_call_id
             ) THEN 'UNVERIFIED' ELSE 'RELEASED' END, reconciled_at_ms=?2
             WHERE job_id=?1 AND state='RESERVED'",
            params![job_id.to_string(), now_ms],
        )?;
        transaction.execute(
            "UPDATE provider_quota_entry SET state=CASE WHEN EXISTS(
                SELECT 1 FROM provider_run run WHERE run.job_id=provider_quota_entry.job_id AND run.planned_call_id=provider_quota_entry.planned_call_id
             ) THEN 'UNVERIFIED' ELSE 'RELEASED' END WHERE job_id=?1 AND state='RESERVED'",
            [job_id.to_string()],
        )?;
        let state = if cancelled { "CANCELLED" } else { "FAILED" };
        let phase = if cancelled { "cancelled" } else { "research failed" };
        let sanitized = crate::security::sanitized_error(message);
        transaction.execute(
            "UPDATE job SET state=?2, phase=?3, sanitized_error=?4, finished_at_ms=?5 WHERE id=?1 AND state NOT IN ('SUCCEEDED','FAILED','CANCELLED','INTERRUPTED')",
            params![job_id.to_string(), state, phase, sanitized, now_ms],
        )?;
        transaction.execute(
            "UPDATE research_run SET status=?2, finished_at_ms=?3 WHERE job_id=?1 AND status NOT IN ('SUCCEEDED','FAILED','CANCELLED','INTERRUPTED')",
            params![job_id.to_string(), state, now_ms],
        )?;
        transaction.execute(
            "INSERT INTO job_event(job_id, sequence, event_type, occurred_at_ms, sanitized_payload_json)
             VALUES (?1,COALESCE((SELECT MAX(sequence)+1 FROM job_event WHERE job_id=?1),0),?2,?3,?4)",
            params![job_id.to_string(), state, now_ms, serde_json::to_string(&serde_json::json!({"message": sanitized}))?],
        )?;
        let record = job_from_transaction(&transaction, job_id)?;
        transaction.commit()?;
        Ok(record)
    }

    pub fn annotate_provider_accounting_failure(
        &mut self,
        job_id: Uuid,
        provider_message: &str,
    ) -> AppResult<()> {
        let sanitized = crate::security::sanitized_error(provider_message);
        if sanitized.trim().is_empty() {
            return Ok(());
        }
        self.connection_mut().execute(
            "UPDATE job
             SET sanitized_error=SUBSTR(
                 COALESCE(sanitized_error,'Provider usage could not be verified.')
                 || ' Provider reported: ' || ?2,
                 1,
                 500
             )
             WHERE id=?1 AND state='FAILED'
               AND phase IN ('provider usage unverified','provider capability exceeded')",
            params![job_id.to_string(), sanitized],
        )?;
        Ok(())
    }

    pub fn complete_research(
        &mut self,
        job_id: Uuid,
        bundle: &crate::domain::ValidatedResearchBundle,
        now_ms: i64,
    ) -> AppResult<JobRecord> {
        let transaction = self.connection_mut().transaction_with_behavior(TransactionBehavior::Immediate)?;
        transaction.execute(
            "UPDATE cost_entry SET state='RELEASED', reconciled_at_ms=?2 WHERE job_id=?1 AND state='RESERVED'
             AND NOT EXISTS(SELECT 1 FROM provider_run run WHERE run.job_id=cost_entry.job_id AND run.planned_call_id=cost_entry.planned_call_id)",
            params![job_id.to_string(), now_ms],
        )?;
        transaction.execute(
            "UPDATE provider_quota_entry SET state='RELEASED' WHERE job_id=?1 AND state='RESERVED'
             AND NOT EXISTS(SELECT 1 FROM provider_run run WHERE run.job_id=provider_quota_entry.job_id AND run.planned_call_id=provider_quota_entry.planned_call_id)",
            [job_id.to_string()],
        )?;
        let unsafe_count: i64 = transaction.query_row(
            "SELECT COUNT(*) FROM cost_entry WHERE job_id=?1 AND state IN ('RESERVED','UNVERIFIED')",
            [job_id.to_string()], |row| row.get(0),
        )?;
        let pending_runs: i64 = transaction.query_row(
            "SELECT COUNT(*) FROM provider_run WHERE job_id=?1 AND outcome='PENDING'",
            [job_id.to_string()], |row| row.get(0),
        )?;
        if unsafe_count != 0 || pending_runs != 0 {
            return Err(AppError::Budget("research cannot succeed with unreconciled provider authority".to_owned()));
        }
        let source_replacements = resolve_evidence_source_replacements(&transaction, &bundle.sources)?;
        let bundle = bundle.rebind_evidence_source_ids(&source_replacements)?;
        for source in &bundle.sources {
            let inserted = transaction.execute(
                "INSERT INTO evidence_source(id,provider,provider_record_id,source_type,canonical_url,title,author_or_channel,source_created_at_ms,source_updated_at_ms,page_published_at_ms,retrieved_at_ms,query,window_start_ms,window_end_ms,independence_group,policy_class,content_sha256,refresh_due_at_ms,purge_due_at_ms,expires_at_ms,deletion_required_at_ms,fetch_status)
                 VALUES (?1,?2,?3,?4,?5,?6,?7,CAST(unixepoch(?8,'subsec')*1000 AS INTEGER),CAST(unixepoch(?9,'subsec')*1000 AS INTEGER),CAST(unixepoch(?10,'subsec')*1000 AS INTEGER),CAST(unixepoch(?11,'subsec')*1000 AS INTEGER),?12,CAST(unixepoch(?13,'subsec')*1000 AS INTEGER),CAST(unixepoch(?14,'subsec')*1000 AS INTEGER),?15,?16,?17,CAST(unixepoch(?18,'subsec')*1000 AS INTEGER),CAST(unixepoch(?19,'subsec')*1000 AS INTEGER),CAST(unixepoch(?20,'subsec')*1000 AS INTEGER),CAST(unixepoch(?21,'subsec')*1000 AS INTEGER),'SUCCESS')
                 ON CONFLICT(id) DO NOTHING",
                params![source.id.to_string(), source.provider, source.provider_record_id, source.source_type,
                    source.canonical_url, source.title, source.author_or_channel, source.source_created_at,
                    source.source_updated_at, source.page_published_at, source.retrieved_at, source.query,
                    source.window_start, source.window_end, source.independence_group, source.policy_class,
                    source.content_sha256, source.refresh_due_at, source.purge_due_at, source.expires_at,
                    source.deletion_required_at],
            )?;
            if inserted == 0 {
                let exact: bool = transaction.query_row(
                    "SELECT canonical_url=?2 AND content_sha256=?3 AND provider=?4 FROM evidence_source WHERE id=?1",
                    params![source.id.to_string(), source.canonical_url, source.content_sha256, source.provider],
                    |row| row.get(0),
                )?;
                if !exact { return Err(AppError::DatabaseInvariant("evidence source ID was reused with different provenance".to_owned())); }
            }
            transaction.execute(
                "INSERT INTO external_link(handle,evidence_source_id,canonical_https_url,created_at_ms) VALUES (?1,?1,?2,?3)
                 ON CONFLICT(handle) DO UPDATE SET canonical_https_url=excluded.canonical_https_url WHERE evidence_source_id=excluded.evidence_source_id",
                params![source.id.to_string(), source.canonical_url, now_ms],
            )?;
        }
        for claim in &bundle.claims {
            let inserted = transaction.execute(
                "INSERT INTO evidence_claim(id,source_id,claim_kind,excerpt_type,text,episode_locator_json,quote_fact_json,why_now_event_json,scene_fact_json,cast_fact_json,event_or_release_at_ms,verification,confidence_ppm,supports_why_now,content_sha256,canonical_contract_json)
                 VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,CAST(unixepoch(?11,'subsec')*1000 AS INTEGER),?12,?13,?14,?15,?16)
                 ON CONFLICT(id) DO NOTHING",
                params![claim.id.to_string(), claim.source_id.to_string(), claim.claim_kind, claim.excerpt_type,
                    claim.text, claim.episode_locator_json, claim.quote_fact_json, claim.why_now_event_json,
                    claim.scene_fact_json, claim.cast_fact_json, claim.event_or_release_at, claim.verification,
                    claim.confidence_ppm, claim.supports_why_now, claim.content_sha256, claim.canonical_contract_json],
            )?;
            if inserted == 0 {
                let (stored_source_id, stored_contract): (String, String) = transaction.query_row(
                    "SELECT source_id,canonical_contract_json FROM evidence_claim WHERE id=?1",
                    [claim.id.to_string()],
                    |row| Ok((row.get(0)?, row.get(1)?)),
                )?;
                let same_contract = database_json_contracts_equal(
                    &stored_contract,
                    &claim.canonical_contract_json,
                )?;
                if stored_source_id != claim.source_id.to_string() || !same_contract {
                    return Err(AppError::DatabaseInvariant(
                        "evidence claim ID was reused with different content".to_owned(),
                    ));
                }
            } else {
                let title: String = transaction.query_row("SELECT title FROM evidence_source WHERE id=?1", [claim.source_id.to_string()], |row| row.get(0))?;
                transaction.execute(
                    "INSERT INTO evidence_fts(evidence_claim_id,title,text) VALUES (?1,?2,?3)",
                    params![claim.id.to_string(), title, claim.text],
                )?;
            }
        }
        persist_research_entities(&transaction, job_id, &bundle, now_ms)?;
        transaction.execute(
            "UPDATE research_run SET status='SUCCEEDED', canonical_result_json=?2, evidence_sources_json=?3, evidence_claims_json=?4, finished_at_ms=?5 WHERE job_id=?1 AND status IN ('QUEUED','RUNNING')",
            params![job_id.to_string(), &bundle.canonical_result_json, &bundle.evidence_sources_json,
                &bundle.evidence_claims_json, now_ms],
        )?;
        let changed = transaction.execute(
            "UPDATE job SET state='SUCCEEDED', progress_percent=100, phase='research complete', result_contract_json=?2, sanitized_error=NULL, finished_at_ms=?3 WHERE id=?1 AND state IN ('QUEUED','RUNNING')",
            params![job_id.to_string(), &bundle.ui_view_json, now_ms],
        )?;
        if changed != 1 { return Err(AppError::DatabaseInvariant("research completion targeted a non-active job".to_owned())); }
        transaction.execute(
            "INSERT INTO job_event(job_id,sequence,event_type,occurred_at_ms,sanitized_payload_json) VALUES (?1,COALESCE((SELECT MAX(sequence)+1 FROM job_event WHERE job_id=?1),0),'SUCCEEDED',?2,'{}')",
            params![job_id.to_string(), now_ms],
        )?;
        let record = job_from_transaction(&transaction, job_id)?;
        transaction.commit()?;
        Ok(record)
    }

    pub fn record_recommendation_feedback(
        &mut self,
        job_id: Uuid,
        opportunity_id: Uuid,
        concept_id: Option<Uuid>,
        rating: &str,
        now_ms: i64,
    ) -> AppResult<Uuid> {
        let transaction = self.connection_mut().transaction_with_behavior(TransactionBehavior::Immediate)?;
        let research_run_id: Option<String> = transaction.query_row(
            "SELECT run.id
             FROM research_run run
             JOIN opportunity item ON item.research_run_id=run.id
             WHERE run.job_id=?1 AND run.status='SUCCEEDED' AND item.id=?2",
            params![job_id.to_string(), opportunity_id.to_string()],
            |row| row.get(0),
        ).optional()?;
        let Some(research_run_id) = research_run_id else {
            return Err(AppError::Validation(
                "feedback target does not belong to a completed research result".to_owned(),
            ));
        };
        if let Some(concept_id) = concept_id {
            let concept_exists: bool = transaction.query_row(
                "SELECT EXISTS(
                    SELECT 1
                    FROM research_run run, json_each(run.canonical_result_json, '$.editorialConcepts') concept
                    WHERE run.id=?1
                      AND json_extract(concept.value, '$.opportunityId')=?2
                      AND json_extract(concept.value, '$.conceptId')=?3
                )",
                params![research_run_id, opportunity_id.to_string(), concept_id.to_string()],
                |row| row.get(0),
            )?;
            if !concept_exists {
                return Err(AppError::Validation(
                    "feedback concept does not belong to the selected opportunity".to_owned(),
                ));
            }
        }
        let feedback_id = Uuid::new_v4();
        transaction.execute(
            "INSERT INTO recommendation_feedback(id,research_run_id,opportunity_id,concept_id,rating,created_at_ms)
             VALUES (?1,?2,?3,?4,?5,?6)",
            params![
                feedback_id.to_string(),
                research_run_id,
                opportunity_id.to_string(),
                concept_id.map(|value| value.to_string()),
                rating,
                now_ms,
            ],
        )?;
        transaction.commit()?;
        Ok(feedback_id)
    }
}

fn database_json_contracts_equal(left: &str, right: &str) -> AppResult<bool> {
    let parse = |value: &str| {
        crate::worker::protocol::parse_strict_json_bytes(value.as_bytes()).map_err(|_| {
            AppError::DatabaseInvariant(
                "persisted evidence claim contract is not strict JSON".to_owned(),
            )
        })
    };
    Ok(parse(left)? == parse(right)?)
}

#[derive(Debug)]
struct ExistingEvidenceSource {
    id: Uuid,
    provider: String,
    provider_record_id: Option<String>,
    source_type: String,
    canonical_url: String,
    policy_class: String,
    content_sha256: String,
}

fn existing_evidence_source_from_row(row: &rusqlite::Row<'_>) -> rusqlite::Result<ExistingEvidenceSource> {
    let raw_id: String = row.get(0)?;
    let id = Uuid::parse_str(&raw_id).map_err(|error| {
        rusqlite::Error::FromSqlConversionFailure(
            0,
            rusqlite::types::Type::Text,
            Box::new(error),
        )
    })?;
    Ok(ExistingEvidenceSource {
        id,
        provider: row.get(1)?,
        provider_record_id: row.get(2)?,
        source_type: row.get(3)?,
        canonical_url: row.get(4)?,
        policy_class: row.get(5)?,
        content_sha256: row.get(6)?,
    })
}

fn resolve_evidence_source_replacements(
    transaction: &Transaction<'_>,
    sources: &[crate::domain::PersistedEvidenceSource],
) -> AppResult<HashMap<Uuid, Uuid>> {
    const SELECT_SOURCE: &str =
        "SELECT id,provider,provider_record_id,source_type,canonical_url,policy_class,content_sha256 FROM evidence_source";
    let mut replacements = HashMap::new();
    for source in sources {
        let by_provider_record = if let Some(provider_record_id) = source.provider_record_id.as_deref() {
            transaction
                .query_row(
                    &format!("{SELECT_SOURCE} WHERE provider=?1 AND provider_record_id=?2"),
                    params![source.provider, provider_record_id],
                    existing_evidence_source_from_row,
                )
                .optional()?
        } else {
            None
        };
        let by_content = transaction
            .query_row(
                &format!("{SELECT_SOURCE} WHERE canonical_url=?1 AND content_sha256=?2"),
                params![source.canonical_url, source.content_sha256],
                existing_evidence_source_from_row,
            )
            .optional()?;
        let existing = match (by_provider_record, by_content) {
            (Some(record), Some(content)) if record.id != content.id => {
                return Err(AppError::DatabaseInvariant(
                    "evidence-source natural identities resolve to different stored records".to_owned(),
                ));
            }
            (Some(record), Some(_)) | (Some(record), None) => Some(record),
            (None, Some(content)) => Some(content),
            (None, None) => None,
        };
        let Some(mut existing) = existing else { continue; };
        // A newer trusted adapter may add an opaque provider record binding to
        // an exact source snapshot that an older run stored without one. The
        // canonical URL and content digest already prove this is the same
        // fetched artifact, so upgrade the missing natural key atomically
        // instead of treating the additional trusted identity as conflicting
        // provenance. Never replace or remove an existing non-null binding.
        if existing.provider_record_id.is_none()
            && source.provider_record_id.is_some()
            && existing.provider == source.provider
            && existing.source_type == source.source_type
            && existing.canonical_url == source.canonical_url
            && existing.policy_class == source.policy_class
            && existing.content_sha256 == source.content_sha256
        {
            let changed = transaction.execute(
                "UPDATE evidence_source SET provider_record_id=?2
                 WHERE id=?1 AND provider_record_id IS NULL",
                params![existing.id.to_string(), source.provider_record_id],
            )?;
            if changed != 1 {
                return Err(AppError::DatabaseInvariant(
                    "evidence-source identity upgrade was not atomic".to_owned(),
                ));
            }
            existing.provider_record_id = source.provider_record_id.clone();
        }
        // Ownership and copied-text clustering can be refined by a newer reviewed
        // normalization catalog without changing the underlying fetched content.
        // Each research run keeps its own evidence-group snapshot; the reusable
        // source row records the newest accepted classification.
        if existing.provider != source.provider
            || existing.provider_record_id != source.provider_record_id
            || existing.source_type != source.source_type
            || existing.canonical_url != source.canonical_url
            || existing.policy_class != source.policy_class
            || existing.content_sha256 != source.content_sha256
        {
            return Err(AppError::DatabaseInvariant(
                "evidence-source natural identity was reused with different provenance".to_owned(),
            ));
        }
        if existing.id != source.id {
            replacements.insert(source.id, existing.id);
        }
        transaction.execute(
            "UPDATE evidence_source SET
                source_updated_at_ms=CAST(unixepoch(?2,'subsec')*1000 AS INTEGER),
                retrieved_at_ms=CAST(unixepoch(?3,'subsec')*1000 AS INTEGER),
                independence_group=?4,
                query=?5,
                window_start_ms=CAST(unixepoch(?6,'subsec')*1000 AS INTEGER),
                window_end_ms=CAST(unixepoch(?7,'subsec')*1000 AS INTEGER),
                refresh_due_at_ms=CAST(unixepoch(?8,'subsec')*1000 AS INTEGER),
                purge_due_at_ms=CAST(unixepoch(?9,'subsec')*1000 AS INTEGER),
                expires_at_ms=CAST(unixepoch(?10,'subsec')*1000 AS INTEGER),
                deletion_required_at_ms=CAST(unixepoch(?11,'subsec')*1000 AS INTEGER),
                fetch_status='SUCCESS'
             WHERE id=?1 AND retrieved_at_ms<=CAST(unixepoch(?3,'subsec')*1000 AS INTEGER)",
            params![
                existing.id.to_string(),
                source.source_updated_at,
                source.retrieved_at,
                source.independence_group,
                source.query,
                source.window_start,
                source.window_end,
                source.refresh_due_at,
                source.purge_due_at,
                source.expires_at,
                source.deletion_required_at,
            ],
        )?;
    }
    Ok(replacements)
}

fn validate_sha256(value: &str) -> AppResult<()> {
    if value.len() != 64 || !value.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err(AppError::Validation("SHA-256 value is invalid".to_owned()));
    }
    Ok(())
}

fn persist_research_entities(
    transaction: &Transaction<'_>,
    job_id: Uuid,
    bundle: &crate::domain::ValidatedResearchBundle,
    now_ms: i64,
) -> AppResult<()> {
    let root: serde_json::Value = serde_json::from_str(&bundle.canonical_result_json)?;
    let opportunities = json_array(&root, "opportunities")?;
    let requests = json_array(&root, "footageRequests")?;
    for (index, opportunity) in opportunities.iter().enumerate() {
        let id = json_string(opportunity, "opportunityId")?;
        let request_id = json_string(opportunity, "footageRequestId")?;
        let confidence_ppm = confidence_ppm(opportunity, "confidence")?;
        transaction.execute(
            "INSERT INTO opportunity(id,research_run_id,footage_request_id,rank,media_kind,media_identity_json,title,focus_json,why_now,what_viewers_are_discussing,creative_hook,emotional_edit_direction,evidence_gate,confidence_ppm,score_json,caveats_json,canonical_contract_json,created_at_ms)
             VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16,?17,?18)",
            params![id, job_id.to_string(), request_id, i64::try_from(index + 1).map_err(|_| AppError::DatabaseInvariant("opportunity rank overflow".to_owned()))?,
                json_string(opportunity, "mediaKind")?, json_value_string(opportunity, "mediaIdentity")?,
                json_string(opportunity, "title")?, json_value_string(opportunity, "focus")?,
                json_string(opportunity, "whyNow")?, json_string(opportunity, "whatViewersAreDiscussing")?,
                json_string(opportunity, "creativeHook")?, json_string(opportunity, "emotionalEditDirection")?,
                json_string(opportunity, "evidenceGate")?, confidence_ppm,
                json_value_string(opportunity, "score")?, json_value_string(opportunity, "caveats")?,
                serde_json::to_string(opportunity)?, now_ms],
        )?;
        for reference in json_array(opportunity, "evidence")? {
            transaction.execute(
                "INSERT INTO opportunity_evidence(opportunity_id,evidence_claim_id,evidence_role,independence_group,supports_why_now) VALUES (?1,?2,?3,?4,?5)",
                params![id, json_string(reference, "claimId")?, json_string(reference, "role")?,
                    json_string(reference, "independenceGroup")?, json_bool(reference, "supportsWhyNow")?],
            )?;
        }
    }
    for request in requests {
        persist_footage_request(transaction, request, now_ms)?;
    }
    Ok(())
}

fn persist_footage_request(
    transaction: &Transaction<'_>,
    request: &serde_json::Value,
    now_ms: i64,
) -> AppResult<()> {
    let request_id = json_string(request, "footageRequestId")?;
    let natural = json_object(request, "naturalRequest")?;
    transaction.execute(
        "INSERT INTO footage_request(id,opportunity_id,schema_version,summary,natural_best,natural_alternative,natural_minimum,natural_optional_improvement,smallest_useful_set_reason,search_queries_json,warnings_json,canonical_contract_json,created_at_ms)
         VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13)",
        params![request_id, json_string(request, "opportunityId")?, json_string(request, "schemaVersion")?,
            json_string(request, "summary")?, json_string_value(natural, "best")?, json_optional_string_value(natural, "alternative")?,
            json_string_value(natural, "minimum")?, json_optional_string_value(natural, "optionalImprovement")?,
            json_string(request, "smallestUsefulSetReason")?, json_value_string(request, "searchQueries")?,
            json_value_string(request, "warnings")?, serde_json::to_string(request)?, now_ms],
    )?;
    let minimum = json_array(request, "minimumUsefulSourceKeys")?.iter()
        .map(|value| value.as_str().map(str::to_owned).ok_or_else(|| AppError::DatabaseInvariant("minimum footage key is invalid".to_owned())))
        .collect::<AppResult<HashSet<_>>>()?;
    let mut replacements: Vec<(String, String)> = Vec::new();
    for (group, field) in [("REQUIRED", "requiredSources"), ("OPTIONAL", "optionalSources"), ("ALTERNATIVE", "alternativeSources")] {
        for source in json_array(request, field)? {
            let source_id = json_string(source, "requestedSourceId")?;
            let source_key = json_string(source, "sourceKey")?;
            let quote = source.get("quote").filter(|value| !value.is_null());
            transaction.execute(
                "INSERT INTO footage_requirement(id,footage_request_id,source_key,source_group,priority,asset_kind,show_or_title,season_number,episode_number,episode_title,characters_json,relationship_or_topic,scene_or_moment,purposes_json,verification_level,source_quality_summary,supporting_claim_ids_json,quote_status,quote_text,quote_speaker,quote_likely_context,quote_claim_id,why_it_matters_emotionally,acquisition_effort,search_queries_json,replaces_required_source_keys_json,in_minimum_useful_set)
                 VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16,?17,?18,?19,?20,?21,?22,?23,?24,?25,?26,?27)",
                params![source_id, request_id, source_key, group, json_i64(source, "priority")?,
                    json_string(source, "assetKind")?, json_string(source, "showOrTitle")?,
                    json_optional_i64(source, "seasonNumber")?, json_optional_i64(source, "episodeNumber")?,
                    json_optional_string(source, "episodeTitle")?, json_value_string(source, "characters")?,
                    json_optional_string(source, "relationshipOrTopic")?, json_string(source, "sceneOrMoment")?,
                    json_value_string(source, "purposes")?, json_string(source, "verificationLevel")?,
                    json_string(source, "sourceQualitySummary")?, json_value_string(source, "supportingClaimIds")?,
                    quote.map(|value| json_string(value, "status")).transpose()?,
                    quote.map(|value| json_string(value, "text")).transpose()?,
                    quote.map(|value| json_optional_string(value, "speaker")).transpose()?.flatten(),
                    quote.map(|value| json_optional_string(value, "likelyContext")).transpose()?.flatten(),
                    quote.map(|value| json_string(value, "claimId")).transpose()?,
                    json_string(source, "whyItMattersEmotionally")?, json_i64(source, "acquisitionEffort")?,
                    json_value_string(source, "searchQueries")?, json_value_string(source, "replacesRequiredSourceKeys")?,
                    minimum.contains(&source_key)],
            )?;
            for purpose in json_array(source, "purposes")? {
                transaction.execute(
                    "INSERT INTO footage_requirement_purpose(footage_requirement_id,purpose) VALUES (?1,?2)",
                    params![source_id, purpose.as_str().ok_or_else(|| AppError::DatabaseInvariant("footage purpose is invalid".to_owned()))?],
                )?;
            }
            for claim_id in json_array(source, "supportingClaimIds")? {
                transaction.execute(
                    "INSERT INTO footage_requirement_evidence(footage_requirement_id,evidence_claim_id) VALUES (?1,?2)",
                    params![source_id, claim_id.as_str().ok_or_else(|| AppError::DatabaseInvariant("footage evidence ID is invalid".to_owned()))?],
                )?;
            }
            for (index, query) in json_array(source, "searchQueries")?.iter().enumerate() {
                transaction.execute(
                    "INSERT INTO footage_search_query(id,footage_request_id,footage_requirement_id,display_order,query) VALUES (?1,?2,?3,?4,?5)",
                    params![Uuid::new_v4().to_string(), request_id, source_id,
                        i64::try_from(index).map_err(|_| AppError::DatabaseInvariant("search query order overflow".to_owned()))?,
                        query.as_str().ok_or_else(|| AppError::DatabaseInvariant("footage search query is invalid".to_owned()))?],
                )?;
            }
            if group == "ALTERNATIVE" {
                for required_key in json_array(source, "replacesRequiredSourceKeys")? {
                    replacements.push((source_id.clone(), required_key.as_str()
                        .ok_or_else(|| AppError::DatabaseInvariant("replacement source key is invalid".to_owned()))?.to_owned()));
                }
            }
        }
    }
    for (alternative_id, required_key) in replacements {
        transaction.execute(
            "INSERT INTO footage_alternative_replacement(alternative_requirement_id,footage_request_id,required_source_key) VALUES (?1,?2,?3)",
            params![alternative_id, request_id, required_key],
        )?;
    }
    for (index, query) in json_array(request, "searchQueries")?.iter().enumerate() {
        transaction.execute(
            "INSERT INTO footage_search_query(id,footage_request_id,footage_requirement_id,display_order,query) VALUES (?1,?2,NULL,?3,?4)",
            params![Uuid::new_v4().to_string(), request_id,
                i64::try_from(index).map_err(|_| AppError::DatabaseInvariant("search query order overflow".to_owned()))?,
                query.as_str().ok_or_else(|| AppError::DatabaseInvariant("footage search query is invalid".to_owned()))?],
        )?;
    }
    for (index, lead) in json_array(request, "introLeads")?.iter().enumerate() {
        let lead_id = json_string(lead, "introLeadId")?;
        let quote = lead.get("quote").filter(|value| !value.is_null());
        transaction.execute(
            "INSERT INTO intro_material_lead(id,footage_request_id,source_key,display_order,moment_description,quote_status,quote_text,quote_speaker,quote_likely_context,quote_claim_id,why_it_might_lead_into_montage,verification_level,supporting_claim_ids_json)
             VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13)",
            params![lead_id, request_id, json_string(lead, "sourceKey")?,
                i64::try_from(index).map_err(|_| AppError::DatabaseInvariant("intro order overflow".to_owned()))?,
                json_string(lead, "momentDescription")?, quote.map(|value| json_string(value, "status")).transpose()?,
                quote.map(|value| json_string(value, "text")).transpose()?,
                quote.map(|value| json_optional_string(value, "speaker")).transpose()?.flatten(),
                quote.map(|value| json_optional_string(value, "likelyContext")).transpose()?.flatten(),
                quote.map(|value| json_string(value, "claimId")).transpose()?,
                json_string(lead, "whyItMightLeadIntoMontage")?, json_string(lead, "verificationLevel")?,
                json_value_string(lead, "supportingClaimIds")?],
        )?;
        for claim_id in json_array(lead, "supportingClaimIds")? {
            transaction.execute(
                "INSERT INTO intro_material_evidence(intro_material_lead_id,evidence_claim_id) VALUES (?1,?2)",
                params![lead_id, claim_id.as_str().ok_or_else(|| AppError::DatabaseInvariant("intro evidence ID is invalid".to_owned()))?],
            )?;
        }
    }
    Ok(())
}

fn json_object<'a>(value: &'a serde_json::Value, field: &str) -> AppResult<&'a serde_json::Map<String, serde_json::Value>> {
    value.get(field).and_then(serde_json::Value::as_object)
        .ok_or_else(|| AppError::DatabaseInvariant(format!("validated result field {field} is not an object")))
}

fn json_array<'a>(value: &'a serde_json::Value, field: &str) -> AppResult<&'a Vec<serde_json::Value>> {
    value.get(field).and_then(serde_json::Value::as_array)
        .ok_or_else(|| AppError::DatabaseInvariant(format!("validated result field {field} is not an array")))
}

fn json_string(value: &serde_json::Value, field: &str) -> AppResult<String> {
    value.get(field).and_then(serde_json::Value::as_str).map(str::to_owned)
        .ok_or_else(|| AppError::DatabaseInvariant(format!("validated result field {field} is not text")))
}

fn json_string_value(value: &serde_json::Map<String, serde_json::Value>, field: &str) -> AppResult<String> {
    value.get(field).and_then(serde_json::Value::as_str).map(str::to_owned)
        .ok_or_else(|| AppError::DatabaseInvariant(format!("validated result field {field} is not text")))
}

fn json_optional_string_value(value: &serde_json::Map<String, serde_json::Value>, field: &str) -> AppResult<Option<String>> {
    match value.get(field) {
        Some(serde_json::Value::Null) | None => Ok(None),
        Some(value) => value.as_str().map(|item| Some(item.to_owned()))
            .ok_or_else(|| AppError::DatabaseInvariant(format!("validated result field {field} is not nullable text"))),
    }
}

fn json_optional_string(value: &serde_json::Value, field: &str) -> AppResult<Option<String>> {
    match value.get(field) {
        Some(serde_json::Value::Null) | None => Ok(None),
        Some(value) => value.as_str().map(|item| Some(item.to_owned()))
            .ok_or_else(|| AppError::DatabaseInvariant(format!("validated result field {field} is not nullable text"))),
    }
}

fn json_i64(value: &serde_json::Value, field: &str) -> AppResult<i64> {
    value.get(field).and_then(serde_json::Value::as_i64)
        .ok_or_else(|| AppError::DatabaseInvariant(format!("validated result field {field} is not an integer")))
}

fn json_optional_i64(value: &serde_json::Value, field: &str) -> AppResult<Option<i64>> {
    match value.get(field) {
        Some(serde_json::Value::Null) | None => Ok(None),
        Some(value) => value.as_i64().map(Some)
            .ok_or_else(|| AppError::DatabaseInvariant(format!("validated result field {field} is not a nullable integer"))),
    }
}

fn json_bool(value: &serde_json::Value, field: &str) -> AppResult<bool> {
    value.get(field).and_then(serde_json::Value::as_bool)
        .ok_or_else(|| AppError::DatabaseInvariant(format!("validated result field {field} is not a boolean")))
}

fn json_value_string(value: &serde_json::Value, field: &str) -> AppResult<String> {
    value.get(field).map(serde_json::to_string).transpose()?
        .ok_or_else(|| AppError::DatabaseInvariant(format!("validated result field {field} is missing")))
}

fn confidence_ppm(value: &serde_json::Value, field: &str) -> AppResult<i64> {
    let confidence = value.get(field).and_then(serde_json::Value::as_f64)
        .ok_or_else(|| AppError::DatabaseInvariant(format!("validated result field {field} is not numeric")))?;
    Ok((confidence * 1_000_000.0).round() as i64)
}

fn signed_preview_hash(normalized_intent_json: &str, calls_json: &str) -> String {
    let mut value = String::with_capacity(normalized_intent_json.len() + calls_json.len() + 1);
    value.push_str(normalized_intent_json);
    value.push('\n');
    value.push_str(calls_json);
    sha256_hex(value.as_bytes())
}

fn parse_uuid(value: &str, label: &str) -> AppResult<Uuid> {
    Uuid::parse_str(value).map_err(|_| AppError::DatabaseInvariant(format!("invalid persisted {label}")))
}

fn ensure_project(transaction: &Transaction<'_>, project_id: Uuid) -> AppResult<()> {
    if transaction
        .query_row(
            "SELECT 1 FROM research_project WHERE id = ?1",
            [project_id.to_string()],
            |_| Ok(()),
        )
        .optional()?
        .is_none()
    {
        return Err(AppError::NotFound("research project was not found".to_owned()));
    }
    Ok(())
}

fn budget_snapshot(transaction: &Transaction<'_>, project_id: Uuid, run_scope_key: &str) -> AppResult<BudgetSnapshot> {
    let default = budget_for(transaction, "DEFAULT", None)?
        .ok_or_else(|| AppError::DatabaseInvariant("default budget is missing".to_owned()))?;
    #[cfg(debug_assertions)]
    if is_m11_calibration_scope(run_scope_key) {
        let run = budget_for(transaction, "RUN", Some(run_scope_key))?
            .ok_or_else(|| AppError::Budget("M1.1 calibration budget is missing".to_owned()))?;
        if run.0 != crate::provider_catalog::M11_CALIBRATION_HARD_CAP_MICRO_USD
            || run.1 != crate::provider_catalog::M11_CALIBRATION_HARD_CAP_MICRO_USD
        {
            return Err(AppError::Budget(
                "M1.1 calibration budget is not the immutable $2.00 cap".to_owned(),
            ));
        }
        return Ok(BudgetSnapshot {
            warning: run.0,
            run_hard: run.1,
            project_hard: run.1,
            effective_hard: run.1,
        });
    }
    let project = budget_for(transaction, "PROJECT", Some(&project_id.to_string()))?.unwrap_or(default);
    let run = budget_for(transaction, "RUN", Some(run_scope_key))?.unwrap_or(default);
    Ok(BudgetSnapshot {
        warning: default.0.min(project.0).min(run.0),
        run_hard: run.1.min(default.1),
        project_hard: project.1,
        effective_hard: default.1.min(project.1).min(run.1),
    })
}

fn is_m11_calibration_scope(run_scope_key: &str) -> bool {
    #[cfg(debug_assertions)]
    {
        run_scope_key == crate::provider_catalog::M11_CALIBRATION_RUN_SCOPE
    }
    #[cfg(not(debug_assertions))]
    {
        let _ = run_scope_key;
        false
    }
}

fn budget_for(transaction: &Transaction<'_>, scope_type: &str, scope_id: Option<&str>) -> AppResult<Option<(i64, i64)>> {
    Ok(transaction
        .query_row(
            "SELECT warning_micro_usd, hard_micro_usd FROM budget WHERE scope_type = ?1 AND scope_id IS ?2 AND enabled = 1",
            params![scope_type, scope_id],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )
        .optional()?)
}

fn committed_for_project(transaction: &Transaction<'_>, project_id: Uuid) -> AppResult<i64> {
    committed(transaction, "job.project_id = ?1", &project_id.to_string(), None)
}

fn committed_for_run(transaction: &Transaction<'_>, project_id: Uuid, run_scope_key: &str) -> AppResult<i64> {
    committed(transaction, "job.project_id = ?1 AND job.run_scope_key = ?2", &project_id.to_string(), Some(run_scope_key))
}

fn committed(transaction: &Transaction<'_>, predicate: &str, value: &str, second: Option<&str>) -> AppResult<i64> {
    let sql = format!(
        "SELECT COALESCE(SUM(committed), 0) FROM (
           SELECT cost_entry.planned_call_id,
             MAX(
               MAX(CASE WHEN cost_entry.state IN ('RESERVED','UNVERIFIED') THEN cost_entry.micro_usd ELSE 0 END),
               SUM(CASE WHEN cost_entry.state = 'ACTUAL' THEN cost_entry.micro_usd ELSE 0 END)
             ) AS committed
           FROM cost_entry JOIN job ON job.id = cost_entry.job_id
           WHERE {predicate}
           GROUP BY cost_entry.planned_call_id
         )"
    );
    if let Some(second) = second {
        Ok(transaction.query_row(&sql, params![value, second], |row| row.get(0))?)
    } else {
        Ok(transaction.query_row(&sql, [value], |row| row.get(0))?)
    }
}

fn enforce_budget(maximum: i64, project_committed: i64, run_committed: i64, budgets: BudgetSnapshot) -> AppResult<()> {
    let project_total = project_committed.checked_add(maximum)
        .ok_or_else(|| AppError::Budget("project budget arithmetic overflow".to_owned()))?;
    let run_total = run_committed.checked_add(maximum)
        .ok_or_else(|| AppError::Budget("run budget arithmetic overflow".to_owned()))?;
    if project_total > budgets.project_hard || run_total > budgets.run_hard || run_total > budgets.effective_hard {
        return Err(AppError::Budget(
            "research reservation would exceed the most restrictive durable budget".to_owned(),
        ));
    }
    Ok(())
}

fn sum_call_reservations(calls: &[PlannedCallInput]) -> AppResult<i64> {
    calls.iter().try_fold(0_i64, |total, call| {
        total
            .checked_add(call.reservation_micro_usd)
            .ok_or_else(|| AppError::Budget("cost plan overflow".to_owned()))
    })
}

fn validate_calls(transaction: &Transaction<'_>, calls: &[PlannedCallInput], now_ms: i64) -> AppResult<()> {
    let mut quotas_per_provider: HashMap<&str, (i64, i64, i64, i64)> = HashMap::new();
    for call in calls {
        call.validate_shape()?;
        let policy = transaction
            .query_row(
                "SELECT enabled, kill_switch_reason, max_requests_per_run, max_tool_calls_per_run, max_input_tokens_per_run, max_output_tokens_per_run, retention_summary, data_use_summary, no_storage_mode, privacy_mode, policy_class, evidence_ttl_seconds, refresh_after_seconds, purge_after_seconds, deletion_after_seconds, checked_at_ms, expires_at_ms FROM provider_policy WHERE provider = ?1",
                [&call.provider],
                |row| Ok((row.get::<_, bool>(0)?, row.get::<_, Option<String>>(1)?, row.get::<_, i64>(2)?, row.get::<_, i64>(3)?, row.get::<_, i64>(4)?, row.get::<_, i64>(5)?, row.get::<_, String>(6)?, row.get::<_, String>(7)?, row.get::<_, String>(8)?, row.get::<_, String>(9)?, row.get::<_, String>(10)?, row.get::<_, i64>(11)?, row.get::<_, i64>(12)?, row.get::<_, i64>(13)?, row.get::<_, Option<i64>>(14)?, row.get::<_, i64>(15)?, row.get::<_, i64>(16)?)),
            )
            .optional()?
            .ok_or_else(|| AppError::Provider(format!("{} policy is unavailable", call.provider)))?;
        if !policy.0 || policy.1.is_some() || policy.15 > now_ms || policy.16 < now_ms {
            return Err(AppError::Provider(format!("{} is disabled or its policy is stale", call.provider)));
        }
        if policy.6 != call.retention_summary || policy.7 != call.data_use_summary
            || policy.8 != call.no_storage_mode || policy.9 != call.privacy_mode
            || policy.10 != call.policy_class || policy.11 != call.evidence_ttl_seconds
            || policy.12 != call.refresh_after_seconds || policy.13 != call.purge_after_seconds
            || policy.14 != call.deletion_after_seconds
        {
            return Err(AppError::Security("provider disclosure does not match trusted policy".to_owned()));
        }
        if call.requires_live_call {
            let quota = quotas_per_provider.entry(call.provider.as_str()).or_default();
            quota.0 = quota.0.saturating_add(call.max_requests);
            quota.1 = quota.1.saturating_add(call.max_tool_calls);
            quota.2 = quota.2.saturating_add(call.max_input_tokens);
            quota.3 = quota.3.saturating_add(call.max_output_tokens);
            if quota.0 > policy.2 || quota.1 > policy.3 || quota.2 > policy.4 || quota.3 > policy.5 {
                return Err(AppError::Provider("planned provider capability exceeds policy".to_owned()));
            }
        }
        if !matches!(call.provider_config, ProviderConfig::OpenaiSynthesis) {
            let trusted_config: String = transaction.query_row(
                "SELECT provider_config_json FROM provider_policy WHERE provider=?1",
                [&call.provider],
                |row| row.get(0),
            )?;
            let persisted: ProviderConfig = serde_json::from_str(&trusted_config)
                .map_err(|_| AppError::DatabaseInvariant("trusted provider configuration is invalid".to_owned()))?;
            let config_matches = persisted == call.provider_config;
            #[cfg(debug_assertions)]
            let config_matches = config_matches
                || crate::provider_catalog::is_exact_m1_provider_debug_call(call, &persisted);
            if !config_matches {
                return Err(AppError::Security("planned provider configuration does not match the reviewed registry".to_owned()));
            }
        }
        if call.cost_kind == crate::cost::CostKind::PaidCloud {
            let configured = call.configured_model.as_deref().ok_or_else(|| AppError::Provider("configured model is missing".to_owned()))?;
            let resolved = call.resolved_model.as_deref().ok_or_else(|| AppError::Provider("resolved model is missing".to_owned()))?;
            let preflight = transaction.query_row(
                "SELECT resolved_model, retention_mode, data_use_mode, no_storage_mode, privacy_mode, checked_at_ms, expires_at_ms
                 FROM provider_model_preflight WHERE provider=?1 AND configured_model=?2 AND available=1",
                params![call.provider, configured],
                |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?, row.get::<_, String>(2)?, row.get::<_, String>(3)?, row.get::<_, String>(4)?, row.get::<_, i64>(5)?, row.get::<_, i64>(6)?)),
            ).optional()?.ok_or_else(|| AppError::Provider("fresh model preflight is required".to_owned()))?;
            if preflight.0 != resolved || preflight.1 != call.retention_summary
                || preflight.2 != call.data_use_summary || preflight.3 != call.no_storage_mode
                || preflight.4 != call.privacy_mode || preflight.5 > now_ms || preflight.6 < now_ms
            {
                return Err(AppError::Security("planned model does not match its fresh trusted preflight".to_owned()));
            }
        }
        if let Some(price_card_id) = call.price_card_id {
            validate_price_card(transaction, price_card_id, call, now_ms)?;
        }
        if call.cache_status == CacheStatus::Hit {
            validate_cache_binding(transaction, call, now_ms)?;
        }
    }
    Ok(())
}

fn validate_price_card(transaction: &Transaction<'_>, id: Uuid, call: &PlannedCallInput, now_ms: i64) -> AppResult<()> {
    let row = transaction
        .query_row(
            "SELECT provider, model, unit_prices_json, effective_at_ms, checked_at_ms, expires_at_ms FROM price_card WHERE id = ?1",
            [id.to_string()],
            |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?, row.get::<_, String>(2)?, row.get::<_, i64>(3)?, row.get::<_, i64>(4)?, row.get::<_, i64>(5)?)),
        )
        .optional()?
        .ok_or_else(|| AppError::Budget("price card was not found".to_owned()))?;
    if row.0 != call.provider
        || row.3 > now_ms || row.4 > now_ms || row.5 < now_ms
        || call.resolved_model.as_deref() != Some(row.1.as_str())
    {
        return Err(AppError::Budget("price card is stale or does not match the resolved model".to_owned()));
    }
    let prices: serde_json::Value = serde_json::from_str(&row.2)?;
    let object = prices.as_object().ok_or_else(|| AppError::DatabaseInvariant("price card must be a JSON object".to_owned()))?;
    for component in &call.components {
        let trusted = object
            .get(&component.category)
            .and_then(serde_json::Value::as_i64)
            .ok_or_else(|| AppError::Budget(format!("price card lacks {}", component.category)))?;
        if trusted != component.unit_price_micro_usd {
            return Err(AppError::Budget("price component does not match the immutable price card".to_owned()));
        }
    }
    Ok(())
}

fn validate_cache_binding(transaction: &Transaction<'_>, call: &PlannedCallInput, now_ms: i64) -> AppResult<()> {
    let namespace = call.cache_namespace.as_deref().ok_or_else(|| AppError::Budget("cache namespace is missing".to_owned()))?;
    let key = call.cache_key.as_deref().ok_or_else(|| AppError::Budget("cache key is missing".to_owned()))?;
    let input_sha256 = call.cache_input_sha256.as_deref().ok_or_else(|| AppError::Budget("cache input hash is missing".to_owned()))?;
    let output_sha256 = call.cache_output_sha256.as_deref().ok_or_else(|| AppError::Budget("cache output hash is missing".to_owned()))?;
    let schema_version = call.cache_schema_version.as_deref().ok_or_else(|| AppError::Budget("cache schema version is missing".to_owned()))?;
    let model_version = call.cache_model_version.as_deref().ok_or_else(|| AppError::Budget("cache model version is missing".to_owned()))?;
    let prompt_version = call.cache_prompt_version.as_deref().ok_or_else(|| AppError::Budget("cache prompt version is missing".to_owned()))?;
    let policy_class = call.cache_policy_class.as_deref().ok_or_else(|| AppError::Budget("cache policy class is missing".to_owned()))?;
    let exists = transaction
        .query_row(
            "SELECT cache.contract_json FROM cache_entry cache JOIN provider_policy policy ON policy.provider=cache.provider
             WHERE cache.namespace=?1 AND cache.cache_key=?2 AND cache.input_sha256=?3 AND cache.output_sha256=?4
               AND cache.schema_version=?5 AND cache.model_version=?6 AND cache.prompt_version=?7 AND cache.policy_class=?8
               AND cache.state='VALID' AND cache.expires_at_ms>=?9 AND (cache.purge_at_ms IS NULL OR cache.purge_at_ms>?9)
               AND policy.enabled=1 AND policy.kill_switch_reason IS NULL AND policy.policy_class=cache.policy_class
               AND policy.checked_at_ms<=?9 AND policy.expires_at_ms>=?9",
            params![namespace, key, input_sha256, output_sha256, schema_version,
                model_version, prompt_version, policy_class, now_ms],
            |row| row.get::<_, String>(0),
        )
        .optional()?;
    let exists = exists
        .filter(|contract| {
            serde_json::from_str::<serde_json::Value>(contract).is_ok()
                && sha256_hex(contract.as_bytes()) == output_sha256.to_ascii_lowercase()
        })
        .is_some();
    if !exists {
        return Err(AppError::Budget("claimed cache hit is not valid".to_owned()));
    }
    Ok(())
}

fn price_card_checked_at(transaction: &Transaction<'_>, id: Uuid) -> AppResult<i64> {
    Ok(transaction.query_row(
        "SELECT checked_at_ms FROM price_card WHERE id=?1",
        [id.to_string()],
        |row| row.get(0),
    )?)
}

fn call_record(id: Uuid, call: &PlannedCallInput, checked_at: Option<i64>) -> PlannedCallRecord {
    PlannedCallRecord {
        call_id: id,
        provider: call.provider.clone(),
        operation: call.operation.clone(),
        configured_model: call.configured_model.clone(),
        resolved_model: call.resolved_model.clone(),
        reservation_micro_usd: call.reservation_micro_usd,
        cost_kind: call.cost_kind.as_str().to_owned(),
        cache_status: call.cache_status.as_str().to_owned(),
        price_card_checked_at_ms: checked_at,
        retention_summary: call.retention_summary.clone(),
        data_use_summary: call.data_use_summary.clone(),
        no_storage_mode: call.no_storage_mode.clone(),
        privacy_mode: call.privacy_mode.clone(),
        cheaper_alternative: call.cheaper_alternative.clone(),
        requires_live_call: call.requires_live_call,
    }
}

fn load_preview(transaction: &Transaction<'_>, token: Uuid) -> AppResult<PersistedPreview> {
    transaction
        .query_row(
            "SELECT project_id, run_scope_key, input_sha256, normalized_intent_json, plan_sha256, plan_contract_json, maximum_micro_usd, expires_at_ms, consumed_at_ms FROM cost_preview WHERE consent_token = ?1",
            [token.to_string()],
            |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?, row.get::<_, String>(2)?, row.get::<_, String>(3)?, row.get::<_, String>(4)?, row.get::<_, String>(5)?, row.get::<_, i64>(6)?, row.get::<_, i64>(7)?, row.get::<_, Option<i64>>(8)?)),
        )
        .optional()?
        .map(|row| -> AppResult<PersistedPreview> { Ok(PersistedPreview {
            project_id: parse_uuid(&row.0, "project ID")?,
            run_scope_key: row.1,
            input_sha256: row.2,
            normalized_intent_json: row.3,
            plan_sha256: row.4,
            plan_contract_json: row.5,
            maximum: row.6,
            expires_at_ms: row.7,
            consumed_at_ms: row.8,
        }) })
        .transpose()?
        .ok_or_else(|| AppError::Budget("cost preview does not exist".to_owned()))
}

fn verify_persisted_plan(transaction: &Transaction<'_>, token: Uuid, calls: &[PlannedCallInput]) -> AppResult<()> {
    let mut statement = transaction.prepare(
        "SELECT provider, operation, configured_model, resolved_model, price_card_id, reservation_micro_usd, cost_kind, cache_status, cache_namespace, cache_key, cache_input_sha256, cache_output_sha256, cache_schema_version, cache_model_version, cache_prompt_version, cache_policy_class, retention_summary, data_use_summary, no_storage_mode, privacy_mode, cheaper_alternative, requires_live_call, max_requests, max_tool_calls, max_input_tokens, max_output_tokens, allow_one_repair, provider_config_json, policy_class, evidence_ttl_seconds, refresh_after_seconds, purge_after_seconds, deletion_after_seconds FROM planned_provider_call WHERE consent_token=?1 ORDER BY display_order",
    )?;
    let persisted = statement
        .query_map([token.to_string()], |row| {
            Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?, row.get::<_, Option<String>>(2)?, row.get::<_, Option<String>>(3)?, row.get::<_, Option<String>>(4)?, row.get::<_, i64>(5)?, row.get::<_, String>(6)?, row.get::<_, String>(7)?, row.get::<_, Option<String>>(8)?, row.get::<_, Option<String>>(9)?, row.get::<_, Option<String>>(10)?, row.get::<_, Option<String>>(11)?, row.get::<_, Option<String>>(12)?, row.get::<_, Option<String>>(13)?, row.get::<_, Option<String>>(14)?, row.get::<_, Option<String>>(15)?, row.get::<_, String>(16)?, row.get::<_, String>(17)?, row.get::<_, String>(18)?, row.get::<_, String>(19)?, row.get::<_, String>(20)?, row.get::<_, bool>(21)?, row.get::<_, i64>(22)?, row.get::<_, i64>(23)?, row.get::<_, i64>(24)?, row.get::<_, i64>(25)?, row.get::<_, bool>(26)?, row.get::<_, String>(27)?, row.get::<_, String>(28)?, row.get::<_, i64>(29)?, row.get::<_, i64>(30)?, row.get::<_, i64>(31)?, row.get::<_, Option<i64>>(32)?))
        })?
        .collect::<Result<Vec<_>, _>>()?;
    if persisted.len() != calls.len() {
        return Err(AppError::DatabaseInvariant("planned call rows do not match the signed plan".to_owned()));
    }
    for (row, call) in persisted.iter().zip(calls) {
        let expected_price = call.price_card_id.map(|value| value.to_string());
        if row.0 != call.provider || row.1 != call.operation || row.2 != call.configured_model
            || row.3 != call.resolved_model || row.4 != expected_price
            || row.5 != call.reservation_micro_usd || row.6 != call.cost_kind.as_str()
            || row.7 != call.cache_status.as_str() || row.8 != call.cache_namespace
            || row.9 != call.cache_key || row.10 != call.cache_input_sha256
            || row.11 != call.cache_output_sha256 || row.12 != call.cache_schema_version
            || row.13 != call.cache_model_version || row.14 != call.cache_prompt_version
            || row.15 != call.cache_policy_class || row.16 != call.retention_summary
            || row.17 != call.data_use_summary || row.18 != call.no_storage_mode
            || row.19 != call.privacy_mode || row.20 != call.cheaper_alternative
            || row.21 != call.requires_live_call || row.22 != call.max_requests
            || row.23 != call.max_tool_calls || row.24 != call.max_input_tokens || row.25 != call.max_output_tokens
            || row.26 != call.allow_one_repair
            || row.27 != serde_json::to_string(&call.provider_config)?
            || row.28 != call.policy_class || row.29 != call.evidence_ttl_seconds
            || row.30 != call.refresh_after_seconds || row.31 != call.purge_after_seconds
            || row.32 != call.deletion_after_seconds
        {
            return Err(AppError::DatabaseInvariant("planned call row was modified".to_owned()));
        }
    }
    let call_ids = persisted_call_ids(transaction, token)?;
    for (call_id, call) in call_ids.into_iter().zip(calls) {
        let mut component_statement = transaction.prepare(
            "SELECT category, quantity_numerator, quantity_denominator, unit, unit_price_micro_usd, maximum_micro_usd FROM planned_cost_component WHERE planned_call_id=?1 ORDER BY category",
        )?;
        let components = component_statement
            .query_map([call_id.to_string()], |row| Ok(CostComponentPlan {
                category: row.get(0)?,
                quantity_numerator: row.get(1)?,
                quantity_denominator: row.get(2)?,
                unit: row.get(3)?,
                unit_price_micro_usd: row.get(4)?,
                maximum_micro_usd: row.get(5)?,
            }))?
            .collect::<Result<Vec<_>, _>>()?;
        let mut expected = call.components.clone();
        expected.sort_by(|left, right| left.category.cmp(&right.category));
        if components != expected {
            return Err(AppError::DatabaseInvariant("planned cost component row was modified".to_owned()));
        }
    }
    Ok(())
}

fn persisted_call_ids(transaction: &Transaction<'_>, token: Uuid) -> AppResult<Vec<Uuid>> {
    let mut statement = transaction.prepare(
        "SELECT id FROM planned_provider_call WHERE consent_token=?1 ORDER BY display_order",
    )?;
    let values = statement
        .query_map([token.to_string()], |row| row.get::<_, String>(0))?
        .collect::<Result<Vec<_>, _>>()?;
    values.into_iter().map(|value| parse_uuid(&value, "planned call ID")).collect()
}

fn reservation_amount(transaction: &Transaction<'_>, job_id: Uuid, call_id: Uuid) -> AppResult<i64> {
    transaction
        .query_row(
            "SELECT micro_usd FROM cost_entry WHERE job_id=?1 AND planned_call_id=?2 AND category='research.call.maximum'",
            params![job_id.to_string(), call_id.to_string()],
            |row| row.get(0),
        )
        .optional()?
        .ok_or_else(|| AppError::Budget("reservation was not found".to_owned()))
}

fn derive_actual_cost(
    transaction: &Transaction<'_>,
    call_id: Uuid,
    usage: &ReconcileProviderRun<'_>,
) -> AppResult<Option<i64>> {
    let mut statement = transaction.prepare(
        "SELECT category, quantity_denominator, unit, unit_price_micro_usd FROM planned_cost_component WHERE planned_call_id=?1 ORDER BY category",
    )?;
    let components = statement
        .query_map([call_id.to_string()], |row| {
            Ok((row.get::<_, String>(0)?, row.get::<_, i64>(1)?, row.get::<_, String>(2)?, row.get::<_, i64>(3)?))
        })?
        .collect::<Result<Vec<_>, _>>()?;
    let native_ticks = usage.provider_native_ticks.and_then(|value| value.parse::<i64>().ok());
    let prices_cached_input = components
        .iter()
        .any(|(category, _, unit, _)| category.starts_with("cached_input_") && unit == "CACHED_INPUT_TOKEN");
    let mut total = 0_i64;
    for (_, denominator, unit, unit_price) in components {
        let quantity = match unit.as_str() {
            "REQUEST" => usage.requests,
            "INPUT_TOKEN" if prices_cached_input => usage.input_tokens.zip(usage.cached_input_tokens)
                .and_then(|(total, cached)| total.checked_sub(cached)),
            "INPUT_TOKEN" => usage.input_tokens,
            "CACHED_INPUT_TOKEN" => usage.cached_input_tokens,
            "OUTPUT_TOKEN" => usage.output_tokens,
            "REASONING_TOKEN" => usage.reasoning_tokens,
            "TOOL_CALL" => usage.tool_invocations,
            "PROVIDER_NATIVE_TICK" => native_ticks,
            "REPAIR_REQUEST" => usage.repair_used.map(|used| if used { 1 } else { 0 }),
            "RESERVATION_ONLY" => Some(0),
            _ => return Err(AppError::DatabaseInvariant("planned price unit is unsupported".to_owned())),
        };
        let Some(quantity) = quantity else { return Ok(None); };
        if quantity < 0 { return Ok(None); }
        total = total
            .checked_add(ceil_cost(quantity, denominator, unit_price)?)
            .ok_or_else(|| AppError::Budget("actual cost arithmetic overflow".to_owned()))?;
    }
    Ok(Some(total))
}

fn job_from_connection(connection: &rusqlite::Connection, job_id: Uuid) -> AppResult<JobRecord> {
    connection
        .query_row(
            "SELECT state, progress_percent, phase, result_contract_json, sanitized_error FROM job WHERE id=?1",
            [job_id.to_string()],
            |row| Ok(JobRecord { id: job_id, state: row.get(0)?, progress_percent: row.get(1)?, phase: row.get(2)?, result_contract_json: row.get(3)?, sanitized_error: row.get(4)? }),
        )
        .optional()?
        .ok_or_else(|| AppError::NotFound("job was not found".to_owned()))
}

fn job_from_transaction(transaction: &Transaction<'_>, job_id: Uuid) -> AppResult<JobRecord> {
    transaction
        .query_row(
            "SELECT state, progress_percent, phase, result_contract_json, sanitized_error FROM job WHERE id=?1",
            [job_id.to_string()],
            |row| Ok(JobRecord { id: job_id, state: row.get(0)?, progress_percent: row.get(1)?, phase: row.get(2)?, result_contract_json: row.get(3)?, sanitized_error: row.get(4)? }),
        )
        .optional()?
        .ok_or_else(|| AppError::NotFound("job was not found".to_owned()))
}

#[cfg(test)]
mod tests {
    use super::*;

    const NOW_MS: i64 = 1_787_140_000_000;

    fn setup() -> Database {
        let mut database = Database::open_in_memory().unwrap();
        install_test_catalog(&mut database);
        database
    }

    fn install_test_catalog(database: &mut Database) {
        crate::provider_catalog::install(database, NOW_MS).unwrap();
        let disclosure = database.provider_disclosures("openai", NOW_MS).unwrap();
        database.upsert_model_preflight(&ModelPreflightInput {
            provider: "openai",
            configured_model: "gpt-5.6-luna",
            resolved_model: Some("gpt-5.6-luna"),
            available: true,
            retention_mode: &disclosure.retention_summary,
            data_use_mode: &disclosure.data_use_summary,
            no_storage_mode: &disclosure.no_storage_mode,
            privacy_mode: &disclosure.privacy_mode,
            checked_at_ms: NOW_MS,
            expires_at_ms: NOW_MS + 60_000,
        }).unwrap();
    }

    #[test]
    fn preflight_timestamp_is_exposed_only_while_current() {
        let database = setup();
        assert!(database
            .current_model_preflight_checked_at("openai", "gpt-5.6-luna", NOW_MS)
            .unwrap()
            .is_some());
        assert!(database
            .current_model_preflight_checked_at("openai", "gpt-5.6-luna", NOW_MS + 60_001)
            .unwrap()
            .is_none());
    }

    #[test]
    fn model_less_youtube_preflight_uses_internal_endpoint_identity() {
        let mut database = setup();
        let disclosure = database.provider_disclosures("youtube", NOW_MS).unwrap();
        let identity = crate::credentials::CredentialProvider::Youtube
            .preflight_record_key();
        database.upsert_model_preflight(&ModelPreflightInput {
            provider: "youtube",
            configured_model: identity,
            resolved_model: Some(identity),
            available: true,
            retention_mode: &disclosure.retention_summary,
            data_use_mode: &disclosure.data_use_summary,
            no_storage_mode: &disclosure.no_storage_mode,
            privacy_mode: &disclosure.privacy_mode,
            checked_at_ms: NOW_MS,
            expires_at_ms: NOW_MS + 60_000,
        }).unwrap();

        assert!(database
            .current_model_preflight_checked_at("youtube", identity, NOW_MS)
            .unwrap()
            .is_some());
        assert_eq!(identity, "youtube-data-api-v3");
    }

    fn normalized_intent(query: &str) -> (crate::domain::CanonicalResearchIntent, String) {
        let intent = crate::domain::parse_intent(serde_json::json!({
            "schemaVersion":"2.0.0",
            "query":query,
            "mediaKinds":["TV_EPISODE"],
            "focusTerms":["romance"],
            "region":"US",
            "freshnessDays":3,
            "spoilerPolicy":"CURRENT_EPISODE",
            "exclusions":["reality TV"],
            "maxResults":3
        })).unwrap();
        let json = intent.to_canonical_json().unwrap();
        (intent, json)
    }

    fn create_preview(database: &mut Database, query: &str, run_scope: &str) -> (CostPreviewRecord, String, String) {
        let (intent, normalized) = normalized_intent(query);
        let request = serde_json::json!({
            "exclusions":null,"freshnessDays":null,"maxResults":null,"mediaKinds":null,
            "prompt":query,"region":null,"schemaVersion":"2.0.0","spoilerPolicy":null
        });
        let request_json = serde_json::to_string(&request).unwrap();
        let input_sha256 = sha256_hex(request_json.as_bytes());
        let calls = crate::provider_catalog::build_plan(database, &intent, &input_sha256, NOW_MS).unwrap();
        let preview = database.create_cost_preview(&NewCostPreview {
            project_id: DEFAULT_PROJECT_ID,
            run_scope_key: run_scope,
            input_sha256: &input_sha256,
            normalized_intent_json: &normalized,
            calls: &calls,
            now_ms: NOW_MS,
            expires_at_ms: NOW_MS + 60_000,
        }).unwrap();
        (preview, input_sha256, request_json)
    }

    fn consume(database: &mut Database, preview: &CostPreviewRecord, hash: &str, request_json: &str) -> JobRecord {
        database.consume_preview_and_create_job(&NewResearchJob {
            consent_token: preview.consent_token,
            input_sha256: hash,
            input_contract_json: request_json,
            raw_query: "romance TV",
            schema_version: "2.0.0",
            now_ms: NOW_MS,
        }).unwrap()
    }

    fn begin_capability(database: &mut Database, job: Uuid, hash: &str, provider: &str, operation: &str) -> ReservationCapability {
        let capability = database.reservation_capabilities(job).unwrap().into_iter()
            .find(|value| value.provider == provider && value.operation == operation).unwrap();
        let capability_json = serde_json::to_string(&capability).unwrap();
        database.begin_provider_run(&BeginProviderRun {
            provider_run_id: capability.provider_run_id,
            job_id: job,
            planned_call_id: capability.planned_call_id,
            capability: &capability_json,
            prompt_version: "test",
            schema_version: "2.0.0",
            input_sha256: hash,
            retention_mode: &capability.retention_mode,
            data_use_mode: &capability.data_use_mode,
            privacy_mode: &capability.privacy_mode,
            now_ms: NOW_MS,
        }).unwrap();
        capability
    }

    fn persistence_bundle(job_id: Uuid, replacement_key: &str) -> crate::domain::ValidatedResearchBundle {
        let source_id = Uuid::new_v4();
        let claim_id = Uuid::new_v4();
        let opportunity_id = Uuid::new_v4();
        let request_id = Uuid::new_v4();
        let required_id = Uuid::new_v4();
        let optional_id = Uuid::new_v4();
        let alternative_id = Uuid::new_v4();
        let intro_id = Uuid::new_v4();
        let canonical_result = serde_json::json!({
            "schemaVersion":"2.0.0",
            "runId":job_id,
            "status":"OPPORTUNITIES",
            "intent":{
                "schemaVersion":"2.0.0","query":"romance TV","mediaKinds":["TV_EPISODE"],
                "focusTerms":["romance"],"region":"US","freshnessDays":3,
                "spoilerPolicy":"CURRENT_EPISODE","exclusions":["reality TV"],"maxResults":3
            },
            "opportunities":[{
                "schemaVersion":"2.0.0","opportunityId":opportunity_id,"footageRequestId":request_id,
                "mediaKind":"TV_EPISODE","mediaIdentity":{"mediaKind":"TV_EPISODE","showOrTitle":"Example Show","seasonNumber":3,"episodeNumber":3},
                "title":"A supported relationship moment","focus":{"characters":["Alex","Sam"],"relationshipOrTopic":"Alex and Sam"},
                "whyNow":"A current episode gives the relationship a concrete turning point.",
                "whatViewersAreDiscussing":"Viewers are discussing the turning point.",
                "creativeHook":"Open on the turning point, then contrast earlier moments.",
                "emotionalEditDirection":"Build from hesitation into payoff.",
                "evidence":[{"claimId":claim_id,"role":"CONTEXT","independenceGroup":"tvmaze.example","supportsWhyNow":false}],
                "evidenceGate":"LOW_CONFIDENCE","confidence":0.6,
                "score":{"releaseFreshness":0.6,"crossSourceAgreement":0.4,"sceneSpecificity":0.7,"footageActionability":0.7,"independentSourceCount":1,"total":0.6},
                "caveats":["Confirm the exact scene in supplied footage."]
            }],
            "footageRequests":[{
                "schemaVersion":"2.0.0","footageRequestId":request_id,"opportunityId":opportunity_id,
                "summary":"Get the smallest useful episode set, with a scene-pack fallback.",
                "naturalRequest":{"best":"Give me Season 3 Episode 3.","alternative":"Give me an Alex and Sam scene pack.","minimum":"Give me the turning-point scene.","optionalImprovement":"An earlier happy callback would strengthen the montage."},
                "requiredSources":[{
                    "requestedSourceId":required_id,"sourceKey":"required_episode","priority":1,"acquisitionEffort":2,
                    "assetKind":"EPISODE","showOrTitle":"Example Show","seasonNumber":3,"episodeNumber":3,"episodeTitle":"Turning Point",
                    "characters":["Alex","Sam"],"relationshipOrTopic":"Alex and Sam","sceneOrMoment":"The turning-point conversation.",
                    "purposes":["INTRO","MONTAGE"],"verificationLevel":"STRONGLY_SUPPORTED","sourceQualitySummary":"Episode identity is supported by attributed metadata.",
                    "supportingClaimIds":[claim_id],"quote":null,"whyItMattersEmotionally":"It supplies setup and emotional direction.",
                    "searchQueries":["Example Show season 3 episode 3 scenes"],"replacesRequiredSourceKeys":[]
                }],
                "optionalSources":[{
                    "requestedSourceId":optional_id,"sourceKey":"optional_callback","priority":1,"acquisitionEffort":3,
                    "assetKind":"SCENE_PACK","showOrTitle":"Example Show","seasonNumber":null,"episodeNumber":null,"episodeTitle":null,
                    "characters":["Alex","Sam"],"relationshipOrTopic":"Alex and Sam","sceneOrMoment":"An earlier happy callback.",
                    "purposes":["OPTIONAL_CALLBACK"],"verificationLevel":"UNKNOWN","sourceQualitySummary":"No exact episode is asserted.",
                    "supportingClaimIds":[],"quote":null,"whyItMattersEmotionally":"It adds contrast without blocking the edit.",
                    "searchQueries":["Alex Sam scene pack"],"replacesRequiredSourceKeys":[]
                }],
                "alternativeSources":[{
                    "requestedSourceId":alternative_id,"sourceKey":"scene_pack_alternative","priority":1,"acquisitionEffort":1,
                    "assetKind":"SCENE_PACK","showOrTitle":"Example Show","seasonNumber":null,"episodeNumber":null,"episodeTitle":null,
                    "characters":["Alex","Sam"],"relationshipOrTopic":"Alex and Sam","sceneOrMoment":"A multi-season relationship scene pack.",
                    "purposes":["INTRO","MONTAGE","PAYOFF"],"verificationLevel":"UNKNOWN","sourceQualitySummary":"A user-supplied scene pack avoids an unsupported locator.",
                    "supportingClaimIds":[],"quote":null,"whyItMattersEmotionally":"It can replace the required episode with lower acquisition effort.",
                    "searchQueries":["Alex Sam multi-season scene pack"],"replacesRequiredSourceKeys":[replacement_key]
                }],
                "minimumUsefulSourceKeys":["required_episode"],
                "smallestUsefulSetReason":"One episode contains the essential setup; everything else is optional or substitutive.",
                "introLeads":[{
                    "introLeadId":intro_id,"sourceKey":"required_episode","momentDescription":"Investigate the opening conversation as a contextual lead.",
                    "quote":null,"whyItMightLeadIntoMontage":"The exchange establishes the relationship tension before the music enters.",
                    "verificationLevel":"STRONGLY_SUPPORTED","supportingClaimIds":[claim_id]
                }],
                "searchQueries":["Example Show S3E3 official clip","Alex Sam scene pack"],"warnings":["Inspect supplied footage before choosing the final intro."]
            }],
            "message":"One actionable opportunity was found.","appliedExclusions":["reality TV"],"warnings":[],
            "generatedAt":"2026-08-15T12:00:00Z"
        });
        crate::domain::ValidatedResearchBundle {
            canonical_result_json: serde_json::to_string(&canonical_result).unwrap(),
            evidence_sources_json: "[]".to_owned(),
            evidence_claims_json: "[]".to_owned(),
            ui_view_json: serde_json::to_string(&serde_json::json!({"kind":"OPPORTUNITIES","opportunities":[]})).unwrap(),
            sources: vec![crate::domain::PersistedEvidenceSource {
                id: source_id,
                provider: "tvmaze".to_owned(),
                provider_record_id: Some("episode-303".to_owned()),
                source_type: "METADATA".to_owned(),
                canonical_url: "https://www.tvmaze.com/episodes/303".to_owned(),
                title: "Example Show S3E3".to_owned(),
                author_or_channel: Some("TVmaze".to_owned()),
                source_created_at: Some("2026-08-15T10:00:00Z".to_owned()),
                source_updated_at: None,
                page_published_at: Some("2026-08-15T10:00:00Z".to_owned()),
                retrieved_at: "2026-08-15T12:00:00Z".to_owned(),
                query: "Example Show S3E3".to_owned(),
                window_start: None,
                window_end: None,
                independence_group: "tvmaze.example".to_owned(),
                policy_class: "tvmaze-metadata-v1".to_owned(),
                content_sha256: sha256_hex(b"persistence source"),
                refresh_due_at: Some("2026-08-16T12:00:00Z".to_owned()),
                purge_due_at: Some("2026-09-14T12:00:00Z".to_owned()),
                expires_at: Some("2026-08-16T12:00:00Z".to_owned()),
                deletion_required_at: None,
            }],
            claims: vec![crate::domain::PersistedEvidenceClaim {
                id: claim_id,
                source_id,
                claim_kind: "EPISODE_IDENTITY".to_owned(),
                excerpt_type: "PARAPHRASE".to_owned(),
                text: "Episode 3 is titled Turning Point.".to_owned(),
                episode_locator_json: Some(r#"{"show":"Example Show","seasonNumber":3,"episodeNumber":3}"#.to_owned()),
                quote_fact_json: None,
                why_now_event_json: None,
                scene_fact_json: None,
                cast_fact_json: None,
                event_or_release_at: None,
                verification: "SECONDARY_CORROBORATED".to_owned(),
                confidence_ppm: 800_000,
                supports_why_now: false,
                content_sha256: sha256_hex(b"persistence claim"),
                canonical_contract_json: "{}".to_owned(),
            }],
        }
    }

    #[test]
    fn start_is_idempotent_and_only_one_executor_can_claim_the_job() {
        let mut database = setup();
        let (preview, hash, request) = create_preview(&mut database, "romance TV", "run-one");
        assert_eq!(preview.maximum_cost_micro_usd, 286_200);
        let first = consume(&mut database, &preview, &hash, &request);
        let replay = consume(&mut database, &preview, &hash, &request);
        assert_eq!(first.id, replay.id);
        let ceilings = database.reservation_capabilities(first.id).unwrap()
            .into_iter().map(|value| (
                value.operation,
                (value.max_tool_calls, value.max_input_tokens, value.maximum_micro_usd),
            ))
            .collect::<HashMap<_, _>>();
        assert_eq!(ceilings.get("research.metadata"), Some(&(0, 0, 0)));
        assert_eq!(
            ceilings.get("research.web_verify"),
            Some(&(20, 230_000, 255_000)),
        );
        assert_eq!(
            ceilings.get("research.synthesize"),
            Some(&(0, 60_000, 31_200)),
        );
        assert!(database.claim_research_execution(first.id, NOW_MS).unwrap());
        assert!(!database.claim_research_execution(first.id, NOW_MS).unwrap());
        let other_hash = "f".repeat(64);
        assert!(database.consume_preview_and_create_job(&NewResearchJob {
            consent_token: preview.consent_token,
            input_sha256: &other_hash,
            input_contract_json: &request,
            raw_query: "different",
            schema_version: "2.0.0",
            now_ms: NOW_MS,
        }).is_err());
    }

    #[test]
    fn project_budget_counts_existing_reservations_before_a_second_plan() {
        let mut database = setup();
        let (first_preview, hash, request) = create_preview(&mut database, "romance TV", "budget-one");
        let cap = first_preview.maximum_cost_micro_usd + 1;
        database.connection_mut().execute(
            "UPDATE budget SET warning_micro_usd=0,hard_micro_usd=?1 WHERE scope_type IN ('DEFAULT','PROJECT')",
            [cap],
        ).unwrap();
        consume(&mut database, &first_preview, &hash, &request);
        let (intent, normalized) = normalized_intent("another romance TV query");
        let hash_two = sha256_hex(b"another canonical input");
        let calls = crate::provider_catalog::build_plan(&database, &intent, &hash_two, NOW_MS).unwrap();
        let result = database.create_cost_preview(&NewCostPreview {
            project_id: DEFAULT_PROJECT_ID,
            run_scope_key: "budget-two",
            input_sha256: &hash_two,
            normalized_intent_json: &normalized,
            calls: &calls,
            now_ms: NOW_MS,
            expires_at_ms: NOW_MS + 60_000,
        });
        assert!(matches!(result, Err(AppError::Budget(_))));
    }

    #[test]
    fn development_provider_debug_budget_blocks_a_second_reserved_call() {
        let mut database = setup();
        let run_scope = crate::provider_catalog::M1_PROVIDER_DEBUG_RUN_SCOPE;
        database.ensure_m1_provider_debug_budget(run_scope, 50_000, NOW_MS).unwrap();
        let calls = crate::provider_catalog::build_m1_provider_debug_plan(&database, NOW_MS).unwrap();
        assert_eq!(calls.len(), 1);
        assert_eq!(calls[0].reservation_micro_usd, 49_960);
        let (_, normalized) = normalized_intent("female-centered current TV");
        let request_json = serde_json::json!({
            "exclusions":null,"freshnessDays":14,"maxResults":5,"mediaKinds":["TV_EPISODE"],
            "prompt":"female-centered current TV","region":"US","schemaVersion":"2.0.0",
            "spoilerPolicy":"CURRENT_EPISODE"
        }).to_string();
        let first_hash = sha256_hex(request_json.as_bytes());
        let first = database.create_cost_preview(&NewCostPreview {
            project_id: DEFAULT_PROJECT_ID,
            run_scope_key: run_scope,
            input_sha256: &first_hash,
            normalized_intent_json: &normalized,
            calls: &calls,
            now_ms: NOW_MS,
            expires_at_ms: NOW_MS + 60_000,
        }).unwrap();
        database.consume_preview_and_create_job(&NewResearchJob {
            consent_token: first.consent_token,
            input_sha256: &first_hash,
            input_contract_json: &request_json,
            raw_query: "female-centered current TV",
            schema_version: "2.0.0",
            now_ms: NOW_MS,
        }).unwrap();

        let second_hash = sha256_hex(b"m1-provider-debug-second");
        let error = database.create_cost_preview(&NewCostPreview {
            project_id: DEFAULT_PROJECT_ID,
            run_scope_key: run_scope,
            input_sha256: &second_hash,
            normalized_intent_json: &normalized,
            calls: &calls,
            now_ms: NOW_MS + 1,
            expires_at_ms: NOW_MS + 60_000,
        }).expect_err("the immutable run cap must reject a second paid reservation");
        assert!(matches!(error, AppError::Budget(_)));
    }

    #[test]
    fn m11_calibration_budget_is_aggregate_and_cannot_exceed_two_dollars() {
        let mut database = setup();
        database.ensure_m11_calibration_budget(NOW_MS).unwrap();
        let run_scope = crate::provider_catalog::M11_CALIBRATION_RUN_SCOPE;
        let (intent, normalized) = normalized_intent(
            "find shows for girls that'll likely be popular on tiktok",
        );
        let calls = crate::provider_catalog::build_m11_calibration_plan(
            &database,
            &intent,
            NOW_MS,
        )
        .unwrap();
        assert_eq!(
            calls.iter().map(|call| call.reservation_micro_usd).sum::<i64>(),
            crate::provider_catalog::M11_CALIBRATION_RUN_RESERVATION_MICRO_USD
        );

        for index in 0..6 {
            let request_json = serde_json::json!({
                "exclusions":null,
                "freshnessDays":14,
                "maxResults":5,
                "mediaKinds":["TV_EPISODE"],
                "prompt":format!("find shows for girls that'll likely be popular on tiktok #{index}"),
                "region":"US",
                "schemaVersion":"2.0.0",
                "spoilerPolicy":"CURRENT_EPISODE"
            })
            .to_string();
            let input_sha256 = sha256_hex(request_json.as_bytes());
            let preview = database
                .create_cost_preview(&NewCostPreview {
                    project_id: DEFAULT_PROJECT_ID,
                    run_scope_key: run_scope,
                    input_sha256: &input_sha256,
                    normalized_intent_json: &normalized,
                    calls: &calls,
                    now_ms: NOW_MS + index,
                    expires_at_ms: NOW_MS + 60_000,
                })
                .unwrap();
            assert_eq!(
                preview.already_spent_or_reserved_micro_usd,
                index * crate::provider_catalog::M11_CALIBRATION_RUN_RESERVATION_MICRO_USD
            );
            database
                .consume_preview_and_create_job(&NewResearchJob {
                    consent_token: preview.consent_token,
                    input_sha256: &input_sha256,
                    input_contract_json: &request_json,
                    raw_query: "find shows for girls that'll likely be popular on tiktok",
                    schema_version: "2.0.0",
                    now_ms: NOW_MS + index,
                })
                .unwrap();
        }

        let request_json = serde_json::json!({
            "exclusions":null,"freshnessDays":14,"maxResults":5,
            "mediaKinds":["TV_EPISODE"],
            "prompt":"find shows for girls that'll likely be popular on tiktok final",
            "region":"US","schemaVersion":"2.0.0","spoilerPolicy":"CURRENT_EPISODE"
        })
        .to_string();
        let input_sha256 = sha256_hex(request_json.as_bytes());
        let error = database
            .create_cost_preview(&NewCostPreview {
                project_id: DEFAULT_PROJECT_ID,
                run_scope_key: run_scope,
                input_sha256: &input_sha256,
                normalized_intent_json: &normalized,
                calls: &calls,
                now_ms: NOW_MS + 7,
                expires_at_ms: NOW_MS + 60_000,
            })
            .expect_err("the seventh full calibration run must exceed the $2.00 aggregate cap");
        assert!(matches!(error, AppError::Budget(_)));
    }

    #[test]
    fn identical_cache_misses_are_single_flight_across_jobs() {
        let mut database = setup();
        let (preview_one, hash, request) = create_preview(&mut database, "same romance TV", "flight-one");
        let first = consume(&mut database, &preview_one, &hash, &request);
        let (intent, normalized) = normalized_intent("same romance TV");
        let calls = crate::provider_catalog::build_plan(&database, &intent, &hash, NOW_MS).unwrap();
        let preview_two = database.create_cost_preview(&NewCostPreview {
            project_id: DEFAULT_PROJECT_ID,
            run_scope_key: "flight-two",
            input_sha256: &hash,
            normalized_intent_json: &normalized,
            calls: &calls,
            now_ms: NOW_MS + 1,
            expires_at_ms: NOW_MS + 60_000,
        }).unwrap();
        let second = consume(&mut database, &preview_two, &hash, &request);
        assert!(database.claim_research_execution(first.id, NOW_MS).unwrap());
        assert!(!database.claim_research_execution(second.id, NOW_MS + 1).unwrap());
        assert_eq!(database.job(second.id).unwrap().state, "FAILED");
        let outstanding: i64 = database.connection().query_row(
            "SELECT COUNT(*) FROM cost_entry WHERE job_id=?1 AND state='RESERVED'",
            [second.id.to_string()],
            |row| row.get(0),
        ).unwrap();
        assert_eq!(outstanding, 0);
    }

    #[test]
    fn queued_cancellation_releases_budget_quota_and_single_flight() {
        let mut database = setup();
        let (preview, hash, request) = create_preview(&mut database, "cancel romance TV", "cancel");
        let job = consume(&mut database, &preview, &hash, &request);
        assert!(database.claim_research_execution(job.id, NOW_MS).unwrap());
        let cancelled = database.request_cancellation(job.id, NOW_MS + 1).unwrap();
        assert_eq!(cancelled.state, "CANCELLED");
        let reserved_cost: i64 = database.connection().query_row(
            "SELECT COUNT(*) FROM cost_entry WHERE job_id=?1 AND state='RESERVED'",
            [job.id.to_string()], |row| row.get(0),
        ).unwrap();
        let reserved_quota: i64 = database.connection().query_row(
            "SELECT COUNT(*) FROM provider_quota_entry WHERE job_id=?1 AND state='RESERVED'",
            [job.id.to_string()], |row| row.get(0),
        ).unwrap();
        let leases: i64 = database.connection().query_row(
            "SELECT COUNT(*) FROM cache_flight WHERE lease_owner=?1",
            [job.id.to_string()], |row| row.get(0),
        ).unwrap();
        assert_eq!((reserved_cost, reserved_quota, leases), (0, 0, 0));
    }

    #[test]
    fn cache_recomputes_hash_and_binds_input_schema_model_prompt_and_policy() {
        let mut database = setup();
        let input_hash = sha256_hex(b"cache input");
        let contract = r#"{"evidenceClaims":[],"evidenceSources":[],"result":{},"schemaVersion":"1.0.0"}"#;
        let output_hash = sha256_hex(contract.as_bytes());
        database.cache_put(&CachePutInput {
            provider: "openai",
            namespace: crate::provider_catalog::BUNDLE_CACHE_NAMESPACE,
            key: &input_hash,
            input_sha256: &input_hash,
            output_sha256: &output_hash,
            schema_version: crate::provider_catalog::BUNDLE_CACHE_SCHEMA,
            model_version: crate::provider_catalog::BUNDLE_CACHE_MODEL,
            prompt_version: crate::provider_catalog::BUNDLE_CACHE_PROMPT,
            policy_class: crate::provider_catalog::BUNDLE_CACHE_POLICY,
            contract_json: contract,
            now_ms: NOW_MS,
        }).unwrap();
        assert!(database.whole_bundle_cache_binding(&input_hash, NOW_MS).unwrap().is_some());
        database.connection_mut().execute(
            "UPDATE cache_entry SET input_sha256=?1 WHERE namespace=?2 AND cache_key=?3",
            params![sha256_hex(b"wrong input"), crate::provider_catalog::BUNDLE_CACHE_NAMESPACE, input_hash],
        ).unwrap();
        assert!(database.whole_bundle_cache_binding(&input_hash, NOW_MS).unwrap().is_none());
        let wrong_output = "0".repeat(64);
        assert!(database.cache_put(&CachePutInput {
            provider: "openai", namespace: "bad", key: "bad", input_sha256: &input_hash,
            output_sha256: &wrong_output, schema_version: "x", model_version: "x",
            prompt_version: "x", policy_class: crate::provider_catalog::BUNDLE_CACHE_POLICY,
            contract_json: contract, now_ms: NOW_MS,
        }).is_err());
    }

    #[test]
    fn second_identical_query_gets_zero_cost_whole_bundle_replay_without_live_capabilities() {
        let mut database = setup();
        let query = "cached romance TV";
        let (_, normalized_json) = normalized_intent(query);
        let normalized: serde_json::Value = serde_json::from_str(&normalized_json).unwrap();
        let request = serde_json::json!({
            "exclusions":null,"freshnessDays":null,"maxResults":null,"mediaKinds":null,
            "prompt":query,"region":null,"schemaVersion":"2.0.0","spoilerPolicy":null
        });
        let request_json = serde_json::to_string(&request).unwrap();
        let input_hash = sha256_hex(request_json.as_bytes());
        let contract = serde_json::to_string(&serde_json::json!({
            "schemaVersion":"1.0.0",
            "result":{
                "schemaVersion":"2.0.0","runId":Uuid::new_v4(),"status":"NO_STRONG_OPPORTUNITY",
                "intent":normalized,"opportunities":[],"footageRequests":[],
                "message":"No strong opportunity found under these constraints.",
                "appliedExclusions":["reality TV"],"warnings":[],"generatedAt":"2026-08-15T12:00:00Z"
            },
            "evidenceSources":[],"evidenceClaims":[]
        })).unwrap();
        let output_hash = sha256_hex(contract.as_bytes());
        database.cache_put(&CachePutInput {
            provider: "openai", namespace: crate::provider_catalog::BUNDLE_CACHE_NAMESPACE,
            key: &input_hash, input_sha256: &input_hash, output_sha256: &output_hash,
            schema_version: crate::provider_catalog::BUNDLE_CACHE_SCHEMA,
            model_version: crate::provider_catalog::BUNDLE_CACHE_MODEL,
            prompt_version: crate::provider_catalog::BUNDLE_CACHE_PROMPT,
            policy_class: crate::provider_catalog::BUNDLE_CACHE_POLICY,
            contract_json: &contract, now_ms: NOW_MS,
        }).unwrap();
        let (preview, hash, persisted_request) = create_preview(&mut database, query, "cache-replay");
        assert_eq!(hash, input_hash);
        assert_eq!(preview.maximum_cost_micro_usd, 0);
        assert_eq!(preview.planned_calls.len(), 1);
        assert_eq!(preview.planned_calls[0].cache_status, "HIT");
        let job = consume(&mut database, &preview, &hash, &persisted_request);
        assert!(database.claim_research_execution(job.id, NOW_MS).unwrap());
        assert!(database.execution_context(job.id).unwrap().capabilities.is_empty());
        let replay = database.whole_bundle_replay(job.id, NOW_MS).unwrap().unwrap();
        database.record_whole_bundle_replay(job.id, &replay, NOW_MS).unwrap();
        let actual: (i64, i64) = database.connection().query_row(
            "SELECT COUNT(*),COALESCE(SUM(micro_usd),0) FROM cost_entry WHERE job_id=?1 AND state='ACTUAL'",
            [job.id.to_string()],
            |row| Ok((row.get(0)?, row.get(1)?)),
        ).unwrap();
        assert_eq!(actual, (1, 0));
    }

    #[test]
    fn policy_maintenance_stales_then_purges_cache_and_evidence_links() {
        let mut database = setup();
        let source_id = Uuid::new_v4();
        let claim_id = Uuid::new_v4();
        database.connection_mut().execute(
            "INSERT INTO evidence_source(id,provider,source_type,canonical_url,title,retrieved_at_ms,query,independence_group,policy_class,content_sha256,expires_at_ms,purge_due_at_ms,fetch_status)
             VALUES (?1,'openai','ARTICLE','https://example.com/evidence','Evidence',?2,'query','example.com','openai-web-evidence-v1',?3,?4,?4,'SUCCESS')",
            params![source_id.to_string(), NOW_MS - 10_000, sha256_hex(b"source"), NOW_MS - 1],
        ).unwrap();
        database.connection_mut().execute(
            "INSERT INTO evidence_claim(id,source_id,claim_kind,excerpt_type,text,verification,confidence_ppm,supports_why_now,content_sha256,canonical_contract_json)
             VALUES (?1,?2,'VIEWER_DISCUSSION','PARAPHRASE','A short signal','SECONDARY_CORROBORATED',700000,0,?3,'{}')",
            params![claim_id.to_string(), source_id.to_string(), sha256_hex(b"claim")],
        ).unwrap();
        database.connection_mut().execute(
            "INSERT INTO evidence_fts(evidence_claim_id,title,text) VALUES (?1,'Evidence','A short signal')",
            [claim_id.to_string()],
        ).unwrap();
        database.connection_mut().execute(
            "INSERT INTO external_link(handle,evidence_source_id,canonical_https_url,created_at_ms) VALUES (?1,?1,'https://example.com/evidence',?2)",
            params![source_id.to_string(), NOW_MS - 10_000],
        ).unwrap();
        let input_hash = sha256_hex(b"maintenance input");
        let contract = "{}";
        let output_hash = sha256_hex(contract.as_bytes());
        database.cache_put(&CachePutInput {
            provider: "openai", namespace: "maintenance", key: "entry", input_sha256: &input_hash,
            output_sha256: &output_hash, schema_version: "1", model_version: "1", prompt_version: "1",
            policy_class: crate::provider_catalog::BUNDLE_CACHE_POLICY, contract_json: contract, now_ms: NOW_MS,
        }).unwrap();
        database.connection_mut().execute(
            "UPDATE cache_entry SET purge_at_ms=?1 WHERE namespace='maintenance' AND cache_key='entry'",
            [NOW_MS - 1],
        ).unwrap();
        database.run_policy_maintenance(NOW_MS).unwrap();
        for table in ["evidence_source", "evidence_claim", "external_link", "cache_entry"] {
            let count: i64 = database.connection().query_row(&format!("SELECT COUNT(*) FROM {table}"), [], |row| row.get(0)).unwrap();
            assert_eq!(count, 0, "{table} should be purged");
        }
        let fts_count: i64 = database.connection().query_row("SELECT COUNT(*) FROM evidence_fts", [], |row| row.get(0)).unwrap();
        assert_eq!(fts_count, 0);
    }

    #[test]
    fn time_advanced_expiry_blocks_result_display_before_purge() {
        let mut database = setup();
        let (preview, hash, request) =
            create_preview(&mut database, "romance TV", "display-expiry");
        let job = consume(&mut database, &preview, &hash, &request);
        let source_id = Uuid::new_v4();
        database.connection_mut().execute(
            "INSERT INTO evidence_source(id,provider,source_type,canonical_url,title,retrieved_at_ms,query,independence_group,policy_class,content_sha256,expires_at_ms,purge_due_at_ms,fetch_status)
             VALUES (?1,'openai','ARTICLE','https://example.com/display-evidence','Evidence',?2,'query','example.com','openai-web-evidence-v1',?3,?4,?5,'SUCCESS')",
            params![
                source_id.to_string(),
                NOW_MS,
                sha256_hex(b"display source"),
                NOW_MS + 100,
                NOW_MS + 10_000,
            ],
        ).unwrap();
        database.connection_mut().execute(
            "UPDATE research_run SET status='SUCCEEDED',canonical_result_json='{}',evidence_sources_json=?2,evidence_claims_json='[]',finished_at_ms=?3 WHERE job_id=?1",
            params![
                job.id.to_string(),
                serde_json::json!([{"sourceId":source_id}]).to_string(),
                NOW_MS,
            ],
        ).unwrap();
        database.connection_mut().execute(
            "UPDATE job SET state='SUCCEEDED',progress_percent=100,phase='research complete',result_contract_json='{}',finished_at_ms=?2 WHERE id=?1",
            params![job.id.to_string(), NOW_MS],
        ).unwrap();

        assert!(database.job_for_display(job.id, NOW_MS).is_ok());
        assert!(matches!(
            database.job_for_display(job.id, NOW_MS + 101),
            Err(AppError::Validation(_))
        ));
        let persisted: (String, i64) = database.connection().query_row(
            "SELECT fetch_status,(SELECT COUNT(*) FROM evidence_source WHERE id=?1) FROM evidence_source WHERE id=?1",
            [source_id.to_string()],
            |row| Ok((row.get(0)?, row.get(1)?)),
        ).unwrap();
        assert_eq!(persisted, ("STALE".to_owned(), 1));
    }

    #[test]
    fn time_advanced_expiry_blocks_external_link_before_purge() {
        let mut database = setup();
        let source_id = Uuid::new_v4();
        let handle = Uuid::new_v4();
        database.connection_mut().execute(
            "INSERT INTO evidence_source(id,provider,source_type,canonical_url,title,retrieved_at_ms,query,independence_group,policy_class,content_sha256,expires_at_ms,purge_due_at_ms,fetch_status)
             VALUES (?1,'openai','ARTICLE','https://example.com/link-evidence','Evidence',?2,'query','example.com','openai-web-evidence-v1',?3,?4,?5,'SUCCESS')",
            params![
                source_id.to_string(),
                NOW_MS,
                sha256_hex(b"link source"),
                NOW_MS + 100,
                NOW_MS + 10_000,
            ],
        ).unwrap();
        database.connection_mut().execute(
            "INSERT INTO external_link(handle,evidence_source_id,canonical_https_url,created_at_ms) VALUES (?1,?2,'https://example.com/link-evidence',?3)",
            params![handle.to_string(), source_id.to_string(), NOW_MS],
        ).unwrap();

        assert_eq!(
            database.resolve_external_link(handle, NOW_MS).unwrap(),
            "https://example.com/link-evidence"
        );
        assert!(matches!(
            database.resolve_external_link(handle, NOW_MS + 101),
            Err(AppError::NotFound(_))
        ));
        let persisted: (String, i64) = database.connection().query_row(
            "SELECT source.fetch_status,COUNT(link.handle)
             FROM evidence_source source
             LEFT JOIN external_link link ON link.evidence_source_id=source.id
             WHERE source.id=?1 GROUP BY source.id",
            [source_id.to_string()],
            |row| Ok((row.get(0)?, row.get(1)?)),
        ).unwrap();
        assert_eq!(persisted, ("STALE".to_owned(), 1));
    }

    #[test]
    fn time_advanced_deletion_deadline_removes_external_evidence() {
        let mut database = setup();
        let source_id = Uuid::new_v4();
        let handle = Uuid::new_v4();
        database.connection_mut().execute(
            "INSERT INTO evidence_source(id,provider,source_type,canonical_url,title,retrieved_at_ms,query,independence_group,policy_class,content_sha256,expires_at_ms,purge_due_at_ms,deletion_required_at_ms,fetch_status)
             VALUES (?1,'openai','ARTICLE','https://example.com/deletion-evidence','Evidence',?2,'query','example.com','openai-web-evidence-v1',?3,?4,?4,?5,'SUCCESS')",
            params![
                source_id.to_string(),
                NOW_MS,
                sha256_hex(b"deletion source"),
                NOW_MS + 10_000,
                NOW_MS + 100,
            ],
        ).unwrap();
        database.connection_mut().execute(
            "INSERT INTO external_link(handle,evidence_source_id,canonical_https_url,created_at_ms) VALUES (?1,?2,'https://example.com/deletion-evidence',?3)",
            params![handle.to_string(), source_id.to_string(), NOW_MS],
        ).unwrap();

        assert!(database.resolve_external_link(handle, NOW_MS).is_ok());
        assert!(matches!(
            database.resolve_external_link(handle, NOW_MS + 101),
            Err(AppError::NotFound(_))
        ));
        for table in ["evidence_source", "external_link"] {
            let count: i64 = database.connection().query_row(
                &format!("SELECT COUNT(*) FROM {table}"),
                [],
                |row| row.get(0),
            ).unwrap();
            assert_eq!(count, 0, "{table} should be deleted at the mandatory deadline");
        }
    }

    #[test]
    fn tvmaze_reconciliation_is_zero_cost_and_requires_only_operation_relevant_usage() {
        let mut database = setup();
        let (preview, hash, request) = create_preview(&mut database, "romance TV", "reconcile-tvmaze");
        let job = consume(&mut database, &preview, &hash, &request);
        assert!(database.claim_research_execution(job.id, NOW_MS).unwrap());
        let capability = begin_capability(&mut database, job.id, &hash, "tvmaze", "research.metadata");
        let idempotency = format!("reconcile:{}:{}", job.id, capability.planned_call_id);
        let result = database.reconcile_provider_run(&ReconcileProviderRun {
            provider_run_id: capability.provider_run_id,
            job_id: job.id,
            planned_call_id: capability.planned_call_id,
            provider_native_ticks: None,
            provider_request_id: None,
            outcome: "SUCCESS",
            requests: Some(1),
            input_tokens: None,
            cached_input_tokens: None,
            output_tokens: None,
            reasoning_tokens: None,
            tool_invocations: None,
            repair_used: None,
            tool_usage_json: None,
            output_sha256: None,
            idempotency_key: &idempotency,
            now_ms: NOW_MS + 1,
        }).unwrap();
        assert!(result.usage_verified);
        assert_eq!(result.charged_or_held_micro_usd, 0);
        let replay = database.reconcile_provider_run(&ReconcileProviderRun {
            provider_run_id: capability.provider_run_id,
            job_id: job.id,
            planned_call_id: capability.planned_call_id,
            provider_native_ticks: None,
            provider_request_id: None,
            outcome: "SUCCESS",
            requests: Some(1),
            input_tokens: None,
            cached_input_tokens: None,
            output_tokens: None,
            reasoning_tokens: None,
            tool_invocations: None,
            repair_used: None,
            tool_usage_json: None,
            output_sha256: None,
            idempotency_key: &idempotency,
            now_ms: NOW_MS + 2,
        }).unwrap();
        assert_eq!(replay.charged_or_held_micro_usd, 0);
    }

    #[test]
    fn conditionally_skipped_free_metadata_call_reconciles_zero_requests() {
        let mut database = setup();
        let (preview, hash, request) = create_preview(
            &mut database,
            "romance TV",
            "reconcile-youtube-skipped",
        );
        let job = consume(&mut database, &preview, &hash, &request);
        assert!(database.claim_research_execution(job.id, NOW_MS).unwrap());
        let capability = begin_capability(
            &mut database,
            job.id,
            &hash,
            "youtube",
            "research.youtube",
        );
        let idempotency = format!("reconcile:{}:{}", job.id, capability.planned_call_id);
        let result = database.reconcile_provider_run(&ReconcileProviderRun {
            provider_run_id: capability.provider_run_id,
            job_id: job.id,
            planned_call_id: capability.planned_call_id,
            provider_native_ticks: None,
            provider_request_id: None,
            outcome: "SUCCESS",
            requests: Some(0),
            input_tokens: None,
            cached_input_tokens: None,
            output_tokens: None,
            reasoning_tokens: None,
            tool_invocations: None,
            repair_used: None,
            tool_usage_json: None,
            output_sha256: None,
            idempotency_key: &idempotency,
            now_ms: NOW_MS + 1,
        }).unwrap();
        assert!(result.usage_verified);
        assert_eq!(result.charged_or_held_micro_usd, 0);
        assert_ne!(database.job(job.id).unwrap().state, "FAILED");
    }

    #[test]
    fn incomplete_free_provider_usage_never_claims_money_was_held() {
        let mut database = setup();
        let (preview, hash, request) = create_preview(
            &mut database,
            "romance TV",
            "reconcile-tvmaze-incomplete",
        );
        let job = consume(&mut database, &preview, &hash, &request);
        assert!(database.claim_research_execution(job.id, NOW_MS).unwrap());
        let capability = begin_capability(
            &mut database,
            job.id,
            &hash,
            "tvmaze",
            "research.metadata",
        );
        let idempotency = format!("reconcile:{}:{}", job.id, capability.planned_call_id);
        let result = database.reconcile_provider_run(&ReconcileProviderRun {
            provider_run_id: capability.provider_run_id,
            job_id: job.id,
            planned_call_id: capability.planned_call_id,
            provider_native_ticks: None,
            provider_request_id: None,
            outcome: "FAILED",
            requests: None,
            input_tokens: None,
            cached_input_tokens: None,
            output_tokens: None,
            reasoning_tokens: None,
            tool_invocations: Some(0),
            repair_used: None,
            tool_usage_json: Some("[]"),
            output_sha256: None,
            idempotency_key: &idempotency,
            now_ms: NOW_MS + 1,
        }).unwrap();
        assert!(!result.usage_verified);
        assert_eq!(result.charged_or_held_micro_usd, 0);
        let failed = database.job(job.id).unwrap();
        assert_eq!(failed.state, "FAILED");
        assert_eq!(
            failed.sanitized_error.as_deref(),
            Some("Provider usage was incomplete for a $0.00 provider call; no paid reservation was held."),
        );
    }

    #[test]
    fn paid_cost_is_derived_from_bound_usage_and_replay_cannot_change_it() {
        let mut database = setup();
        let (preview, hash, request) = create_preview(&mut database, "romance TV", "reconcile-openai");
        let job = consume(&mut database, &preview, &hash, &request);
        assert!(database.claim_research_execution(job.id, NOW_MS).unwrap());
        let capability = begin_capability(&mut database, job.id, &hash, "openai", "research.web_verify");
        let idempotency = format!("reconcile:{}:{}", job.id, capability.planned_call_id);
        let tool_usage = r#"[{"tool":"web_search"}]"#;
        let reconciliation = ReconcileProviderRun {
            provider_run_id: capability.provider_run_id,
            job_id: job.id,
            planned_call_id: capability.planned_call_id,
            provider_native_ticks: None,
            provider_request_id: Some("provider-request-1"),
            outcome: "SUCCESS",
            requests: Some(1),
            input_tokens: Some(100),
            cached_input_tokens: Some(0),
            output_tokens: Some(10),
            reasoning_tokens: Some(0),
            tool_invocations: Some(1),
            repair_used: None,
            tool_usage_json: Some(tool_usage),
            output_sha256: Some("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"),
            idempotency_key: &idempotency,
            now_ms: NOW_MS + 1,
        };
        let result = database.reconcile_provider_run(&reconciliation).unwrap();
        assert!(result.usage_verified);
        assert_eq!(result.charged_or_held_micro_usd, 10_032);
        let replay = database.reconcile_provider_run(&reconciliation).unwrap();
        assert_eq!(replay.charged_or_held_micro_usd, 10_032);
        let changed_usage = ReconcileProviderRun { output_tokens: Some(0), ..reconciliation };
        assert!(matches!(database.reconcile_provider_run(&changed_usage), Err(AppError::Security(_))));
    }

    #[test]
    fn live_r58_fourteen_search_usage_is_inside_the_rebalanced_reservation() {
        let mut database = setup();
        let (preview, hash, request) =
            create_preview(&mut database, "romance TV", "reconcile-web-context");
        let job = consume(&mut database, &preview, &hash, &request);
        assert!(database.claim_research_execution(job.id, NOW_MS).unwrap());
        let capability = begin_capability(
            &mut database,
            job.id,
            &hash,
            "openai",
            "research.web_verify",
        );
        let idempotency = format!("reconcile:{}:{}", job.id, capability.planned_call_id);
        let tool_usage = serde_json::to_string(
            &(0..14)
                .map(|index| format!("web_search_call:sha256-{index}"))
                .collect::<Vec<_>>(),
        )
        .unwrap();

        let result = database.reconcile_provider_run(&ReconcileProviderRun {
            provider_run_id: capability.provider_run_id,
            job_id: job.id,
            planned_call_id: capability.planned_call_id,
            provider_native_ticks: None,
            provider_request_id: Some("provider-request-context-accounting"),
            outcome: "FAILED",
            requests: Some(1),
            input_tokens: Some(126_026),
            cached_input_tokens: Some(35_832),
            output_tokens: Some(4_915),
            reasoning_tokens: Some(3_829),
            tool_invocations: Some(14),
            repair_used: Some(false),
            tool_usage_json: Some(&tool_usage),
            output_sha256: Some(
                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            ),
            idempotency_key: &idempotency,
            now_ms: NOW_MS + 1,
        }).unwrap();

        assert!(result.usage_verified);
        assert!(!result.exceeded_reservation);
        assert_eq!(result.charged_or_held_micro_usd, 164_654);
        assert_eq!(database.job(job.id).unwrap().state, "RUNNING");
    }

    #[test]
    fn live_r67_measured_usage_is_inside_the_reallocated_capability() {
        let mut database = setup();
        let (preview, hash, request) =
            create_preview(&mut database, "romance TV", "reconcile-r67-input-cap");
        let job = consume(&mut database, &preview, &hash, &request);
        assert!(database.claim_research_execution(job.id, NOW_MS).unwrap());
        let capability = begin_capability(
            &mut database,
            job.id,
            &hash,
            "openai",
            "research.web_verify",
        );
        let idempotency = format!("reconcile:{}:{}", job.id, capability.planned_call_id);
        let tool_usage = serde_json::to_string(
            &(0..14)
                .map(|index| format!("web_search_call:r67-{index}"))
                .collect::<Vec<_>>(),
        )
        .unwrap();

        let result = database.reconcile_provider_run(&ReconcileProviderRun {
            provider_run_id: capability.provider_run_id,
            job_id: job.id,
            planned_call_id: capability.planned_call_id,
            provider_native_ticks: None,
            provider_request_id: Some("responses-batch:r67-measured"),
            outcome: "SUCCESS",
            requests: Some(40),
            input_tokens: Some(139_237),
            cached_input_tokens: Some(44_120),
            output_tokens: Some(2_872),
            reasoning_tokens: Some(1_017),
            tool_invocations: Some(14),
            repair_used: Some(false),
            tool_usage_json: Some(&tool_usage),
            output_sha256: Some(
                "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            ),
            idempotency_key: &idempotency,
            now_ms: NOW_MS + 1,
        })
        .unwrap();

        assert_eq!(capability.max_input_tokens, 230_000);
        assert_eq!(capability.max_output_tokens, 7_500);
        assert_eq!(capability.maximum_micro_usd, 255_000);
        assert!(result.usage_verified);
        assert!(!result.exceeded_reservation);
        assert_eq!(result.charged_or_held_micro_usd, 163_354);
        assert_eq!(database.job(job.id).unwrap().state, "RUNNING");
    }

    #[test]
    fn web_context_usage_above_the_corrected_ceiling_still_fails_closed() {
        let mut database = setup();
        let (preview, hash, request) =
            create_preview(&mut database, "romance TV", "reconcile-web-context-overrun");
        let job = consume(&mut database, &preview, &hash, &request);
        assert!(database.claim_research_execution(job.id, NOW_MS).unwrap());
        let capability = begin_capability(
            &mut database,
            job.id,
            &hash,
            "openai",
            "research.web_verify",
        );
        let idempotency = format!("reconcile:{}:{}", job.id, capability.planned_call_id);
        let tool_usage = r#"["web_search_call:sha256-overrun"]"#;

        let result = database.reconcile_provider_run(&ReconcileProviderRun {
            provider_run_id: capability.provider_run_id,
            job_id: job.id,
            planned_call_id: capability.planned_call_id,
            provider_native_ticks: None,
            provider_request_id: Some("provider-request-context-overrun"),
            outcome: "FAILED",
            requests: Some(1),
            input_tokens: Some(230_001),
            cached_input_tokens: Some(0),
            output_tokens: Some(10),
            reasoning_tokens: Some(0),
            tool_invocations: Some(1),
            repair_used: Some(false),
            tool_usage_json: Some(tool_usage),
            output_sha256: None,
            idempotency_key: &idempotency,
            now_ms: NOW_MS + 1,
        }).unwrap();

        assert!(!result.usage_verified);
        assert!(result.exceeded_reservation);
        assert_eq!(result.charged_or_held_micro_usd, capability.maximum_micro_usd);
        let failed = database.job(job.id).unwrap();
        assert_eq!(failed.phase, "provider capability exceeded");
    }

    #[test]
    fn paid_tool_overrun_is_held_and_recorded_instead_of_discarded_as_malformed() {
        let mut database = setup();
        let (preview, hash, request) =
            create_preview(&mut database, "romance TV", "reconcile-tool-overrun");
        let job = consume(&mut database, &preview, &hash, &request);
        assert!(database.claim_research_execution(job.id, NOW_MS).unwrap());
        let capability = begin_capability(
            &mut database,
            job.id,
            &hash,
            "openai",
            "research.web_verify",
        );
        let idempotency = format!("reconcile:{}:{}", job.id, capability.planned_call_id);
        let tool_usage = serde_json::to_string(
            &(0..21)
                .map(|index| format!("web_search_call:{index}"))
                .collect::<Vec<_>>(),
        )
        .unwrap();
        let result = database
            .reconcile_provider_run(&ReconcileProviderRun {
                provider_run_id: capability.provider_run_id,
                job_id: job.id,
                planned_call_id: capability.planned_call_id,
                provider_native_ticks: None,
                provider_request_id: Some("provider-request-overrun"),
                outcome: "FAILED",
                requests: Some(1),
                input_tokens: Some(100),
                cached_input_tokens: Some(0),
                output_tokens: Some(10),
                reasoning_tokens: Some(0),
                tool_invocations: Some(21),
                repair_used: None,
                tool_usage_json: Some(&tool_usage),
                output_sha256: None,
                idempotency_key: &idempotency,
                now_ms: NOW_MS + 1,
            })
            .unwrap();
        assert!(!result.usage_verified);
        assert!(result.exceeded_reservation);
        assert!(result.charged_or_held_micro_usd >= capability.maximum_micro_usd);
        let persisted: (i64, String) = database
            .connection()
            .query_row(
                "SELECT tool_invocations, tool_usage_json FROM provider_run WHERE id=?1",
                [capability.provider_run_id.to_string()],
                |row| Ok((row.get(0)?, row.get(1)?)),
            )
            .unwrap();
        assert_eq!(persisted, (21, tool_usage));
        database.annotate_provider_accounting_failure(
            job.id,
            "openai research did not complete: provider exceeded the bounded input context",
        ).unwrap();
        let message = database.job(job.id).unwrap().sanitized_error.unwrap();
        assert!(message.contains("reserved capability"));
        assert!(message.contains("Provider reported: openai research did not complete"));
    }

    #[test]
    fn missing_reserved_paid_usage_is_held_unverified() {
        let mut database = setup();
        let (preview, hash, request) = create_preview(&mut database, "romance TV", "reconcile-missing");
        let job = consume(&mut database, &preview, &hash, &request);
        assert!(database.claim_research_execution(job.id, NOW_MS).unwrap());
        let capability = begin_capability(&mut database, job.id, &hash, "openai", "research.web_verify");
        let idempotency = format!("reconcile:{}:{}", job.id, capability.planned_call_id);
        let result = database.reconcile_provider_run(&ReconcileProviderRun {
            provider_run_id: capability.provider_run_id,
            job_id: job.id,
            planned_call_id: capability.planned_call_id,
            provider_native_ticks: None,
            provider_request_id: None,
            outcome: "INCOMPLETE",
            requests: Some(1),
            input_tokens: Some(100),
            cached_input_tokens: Some(0),
            output_tokens: None,
            reasoning_tokens: None,
            tool_invocations: Some(0),
            repair_used: None,
            tool_usage_json: Some("[]"),
            output_sha256: None,
            idempotency_key: &idempotency,
            now_ms: NOW_MS + 1,
        }).unwrap();
        assert!(!result.usage_verified);
        assert_eq!(result.charged_or_held_micro_usd, capability.maximum_micro_usd);
        assert_eq!(database.job(job.id).unwrap().state, "FAILED");
        database.annotate_provider_accounting_failure(
            job.id,
            "openai research did not complete: provider returned HTTP 400",
        ).unwrap();
        let failed = database.job(job.id).unwrap();
        let message = failed.sanitized_error.unwrap();
        assert!(message.contains("full reservation remains held"));
        assert!(message.contains("Provider reported: openai research did not complete"));
    }

    #[test]
    fn restart_holds_only_started_call_and_releases_untouched_reservations() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("restart.sqlite3");
        let (job_id, started_call) = {
            let mut database = Database::open(&path).unwrap();
            install_test_catalog(&mut database);
            let (preview, hash, request) = create_preview(&mut database, "restart romance TV", "restart");
            let job = consume(&mut database, &preview, &hash, &request);
            assert!(database.claim_research_execution(job.id, NOW_MS).unwrap());
            let capability = begin_capability(&mut database, job.id, &hash, "tvmaze", "research.metadata");
            (job.id, capability.planned_call_id)
        };
        let database = Database::open(&path).unwrap();
        assert_eq!(database.job(job_id).unwrap().state, "INTERRUPTED");
        let states = {
            let mut statement = database.connection().prepare(
                "SELECT planned_call_id,state FROM cost_entry WHERE job_id=?1 AND category='research.call.maximum' ORDER BY planned_call_id",
            ).unwrap();
            statement.query_map([job_id.to_string()], |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))).unwrap()
                .collect::<Result<Vec<_>, _>>().unwrap()
        };
        assert!(states.iter().any(|(call, state)| call == &started_call.to_string() && state == "UNVERIFIED"));
        assert!(states.iter().filter(|(call, _)| call != &started_call.to_string()).all(|(_, state)| state == "RELEASED"));
        let leases: i64 = database.connection().query_row(
            "SELECT COUNT(*) FROM cache_flight WHERE lease_owner=?1",
            [job_id.to_string()],
            |row| row.get(0),
        ).unwrap();
        assert_eq!(leases, 0);
    }

    #[test]
    fn completion_persists_all_first_class_research_entities_atomically() {
        let mut database = setup();
        let (preview, hash, request) = create_preview(&mut database, "persist romance TV", "persist");
        let job = consume(&mut database, &preview, &hash, &request);
        assert!(database.claim_research_execution(job.id, NOW_MS).unwrap());
        database.update_job_progress(job.id, 100, "worker locally validated", NOW_MS).unwrap();
        assert_eq!(database.job(job.id).unwrap().progress_percent, 99);

        let invalid = persistence_bundle(job.id, "missing_required_key");
        assert!(database.complete_research(job.id, &invalid, NOW_MS + 1).is_err());
        for table in ["opportunity", "footage_request", "footage_requirement", "intro_material_lead"] {
            let count: i64 = database.connection().query_row(
                &format!("SELECT COUNT(*) FROM {table}"), [], |row| row.get(0),
            ).unwrap();
            assert_eq!(count, 0, "{table} must roll back with the failed replacement binding");
        }
        assert_eq!(database.job(job.id).unwrap().state, "RUNNING");

        let bundle = persistence_bundle(job.id, "required_episode");
        let completed = database.complete_research(job.id, &bundle, NOW_MS + 2).unwrap();
        assert_eq!(completed.state, "SUCCEEDED");
        let counts = database.connection().query_row(
            "SELECT
               (SELECT COUNT(*) FROM opportunity WHERE research_run_id=?1),
               (SELECT COUNT(*) FROM footage_request),
               (SELECT COUNT(*) FROM footage_requirement),
               (SELECT COUNT(*) FROM footage_requirement_purpose),
               (SELECT COUNT(*) FROM footage_requirement_evidence),
               (SELECT COUNT(*) FROM footage_alternative_replacement),
               (SELECT COUNT(*) FROM intro_material_lead),
               (SELECT COUNT(*) FROM intro_material_evidence),
               (SELECT COUNT(*) FROM footage_search_query)",
            [job.id.to_string()],
            |row| Ok((row.get::<_, i64>(0)?, row.get::<_, i64>(1)?, row.get::<_, i64>(2)?,
                row.get::<_, i64>(3)?, row.get::<_, i64>(4)?, row.get::<_, i64>(5)?,
                row.get::<_, i64>(6)?, row.get::<_, i64>(7)?, row.get::<_, i64>(8)?)),
        ).unwrap();
        assert_eq!(counts, (1, 1, 3, 6, 1, 1, 1, 1, 5));
        let persisted: (i64, String, String, i64, String) = database.connection().query_row(
            "SELECT priority,asset_kind,purposes_json,acquisition_effort,source_quality_summary
             FROM footage_requirement WHERE source_key='required_episode'",
            [], |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?, row.get(4)?)),
        ).unwrap();
        assert_eq!(persisted.0, 1);
        assert_eq!(persisted.1, "EPISODE");
        assert_eq!(persisted.2, r#"["INTRO","MONTAGE"]"#);
        assert_eq!(persisted.3, 2);
        assert!(persisted.4.contains("attributed metadata"));
    }

    #[test]
    fn repeated_evidence_source_is_reused_and_all_run_references_are_rebound() {
        let mut database = setup();
        let (first_preview, first_hash, first_request) =
            create_preview(&mut database, "first persistence run", "source-reuse-first");
        let first_job = consume(&mut database, &first_preview, &first_hash, &first_request);
        assert!(database.claim_research_execution(first_job.id, NOW_MS).unwrap());
        let first_bundle = persistence_bundle(first_job.id, "required_episode");
        let canonical_source_id = first_bundle.sources[0].id;
        database.complete_research(first_job.id, &first_bundle, NOW_MS + 1).unwrap();

        let (second_preview, second_hash, second_request) =
            create_preview(&mut database, "second persistence run", "source-reuse-second");
        let second_job = consume(&mut database, &second_preview, &second_hash, &second_request);
        assert!(database.claim_research_execution(second_job.id, NOW_MS + 2).unwrap());
        let mut second_bundle = persistence_bundle(second_job.id, "required_episode");
        let proposed_source_id = second_bundle.sources[0].id;
        let second_claim_id = second_bundle.claims[0].id;
        assert_ne!(canonical_source_id, proposed_source_id);
        second_bundle.evidence_sources_json = serde_json::json!([
            {"sourceId": proposed_source_id, "provider": "tvmaze"}
        ]).to_string();
        second_bundle.evidence_claims_json = serde_json::json!([
            {"claimId": second_claim_id, "sourceId": proposed_source_id}
        ]).to_string();
        second_bundle.ui_view_json = serde_json::json!({
            "outcome": "OPPORTUNITIES",
            "evidence": [{"sourceId": proposed_source_id, "linkHandle": proposed_source_id}]
        }).to_string();
        second_bundle.claims[0].canonical_contract_json = serde_json::json!({
            "claimId": second_claim_id,
            "sourceId": proposed_source_id
        }).to_string();

        let completed = database.complete_research(second_job.id, &second_bundle, NOW_MS + 3).unwrap();
        assert_eq!(completed.state, "SUCCEEDED");
        let source_count: i64 = database.connection().query_row(
            "SELECT COUNT(*) FROM evidence_source WHERE provider='tvmaze' AND provider_record_id='episode-303'",
            [],
            |row| row.get(0),
        ).unwrap();
        assert_eq!(source_count, 1);
        let persisted_claim_source: String = database.connection().query_row(
            "SELECT source_id FROM evidence_claim WHERE id=?1",
            [second_claim_id.to_string()],
            |row| row.get(0),
        ).unwrap();
        assert_eq!(persisted_claim_source, canonical_source_id.to_string());
        let (sources_json, claims_json): (String, String) = database.connection().query_row(
            "SELECT evidence_sources_json,evidence_claims_json FROM research_run WHERE job_id=?1",
            [second_job.id.to_string()],
            |row| Ok((row.get(0)?, row.get(1)?)),
        ).unwrap();
        let sources: serde_json::Value = serde_json::from_str(&sources_json).unwrap();
        let claims: serde_json::Value = serde_json::from_str(&claims_json).unwrap();
        assert_eq!(sources[0]["sourceId"], canonical_source_id.to_string());
        assert_eq!(claims[0]["sourceId"], canonical_source_id.to_string());
        let view: serde_json::Value = serde_json::from_str(
            completed.result_contract_json.as_deref().unwrap(),
        ).unwrap();
        assert_eq!(view["evidence"][0]["sourceId"], canonical_source_id.to_string());
        assert_eq!(view["evidence"][0]["linkHandle"], canonical_source_id.to_string());
        let canonical_claim: String = database.connection().query_row(
            "SELECT canonical_contract_json FROM evidence_claim WHERE id=?1",
            [second_claim_id.to_string()],
            |row| row.get(0),
        ).unwrap();
        assert_eq!(
            serde_json::from_str::<serde_json::Value>(&canonical_claim).unwrap()["sourceId"],
            canonical_source_id.to_string(),
        );
    }

    #[test]
    fn repeated_claim_accepts_semantically_identical_strict_json_key_order() {
        let mut database = setup();
        let (first_preview, first_hash, first_request) =
            create_preview(&mut database, "first claim-order run", "claim-order-first");
        let first_job = consume(&mut database, &first_preview, &first_hash, &first_request);
        assert!(database.claim_research_execution(first_job.id, NOW_MS).unwrap());
        let mut first_bundle = persistence_bundle(first_job.id, "required_episode");
        let canonical_claim_id = first_bundle.claims[0].id;
        first_bundle.claims[0].canonical_contract_json =
            r#"{"alpha":1,"beta":2}"#.to_owned();
        database.complete_research(first_job.id, &first_bundle, NOW_MS + 1).unwrap();

        let (second_preview, second_hash, second_request) =
            create_preview(&mut database, "second claim-order run", "claim-order-second");
        let second_job = consume(&mut database, &second_preview, &second_hash, &second_request);
        assert!(database.claim_research_execution(second_job.id, NOW_MS + 2).unwrap());
        let mut second_bundle = persistence_bundle(second_job.id, "required_episode");
        let proposed_claim_id = second_bundle.claims[0].id;
        second_bundle.claims[0].id = canonical_claim_id;
        second_bundle.claims[0].canonical_contract_json =
            r#"{"beta":2,"alpha":1}"#.to_owned();
        second_bundle.canonical_result_json = second_bundle
            .canonical_result_json
            .replace(&proposed_claim_id.to_string(), &canonical_claim_id.to_string());

        let completed = database.complete_research(
            second_job.id,
            &second_bundle,
            NOW_MS + 3,
        ).unwrap();
        assert_eq!(completed.state, "SUCCEEDED");
        let claim_count: i64 = database.connection().query_row(
            "SELECT COUNT(*) FROM evidence_claim WHERE id=?1",
            [canonical_claim_id.to_string()],
            |row| row.get(0),
        ).unwrap();
        assert_eq!(claim_count, 1);
    }

    #[test]
    fn repeated_evidence_source_accepts_a_newer_independence_classification() {
        let mut database = setup();
        let (first_preview, first_hash, first_request) =
            create_preview(&mut database, "first ownership run", "ownership-refresh-first");
        let first_job = consume(&mut database, &first_preview, &first_hash, &first_request);
        assert!(database.claim_research_execution(first_job.id, NOW_MS).unwrap());
        let first_bundle = persistence_bundle(first_job.id, "required_episode");
        let canonical_source_id = first_bundle.sources[0].id;
        database.complete_research(first_job.id, &first_bundle, NOW_MS + 1).unwrap();
        database.connection().execute(
            "UPDATE evidence_source SET independence_group='publisher:unverified-web' WHERE id=?1",
            [canonical_source_id.to_string()],
        ).unwrap();

        let (second_preview, second_hash, second_request) =
            create_preview(&mut database, "second ownership run", "ownership-refresh-second");
        let second_job = consume(&mut database, &second_preview, &second_hash, &second_request);
        assert!(database.claim_research_execution(second_job.id, NOW_MS + 2).unwrap());
        let mut second_bundle = persistence_bundle(second_job.id, "required_episode");
        let proposed_source_id = second_bundle.sources[0].id;
        second_bundle.sources[0].retrieved_at = "2026-08-15T12:01:00Z".to_owned();
        assert_ne!(canonical_source_id, proposed_source_id);

        let completed = database.complete_research(second_job.id, &second_bundle, NOW_MS + 3).unwrap();
        assert_eq!(completed.state, "SUCCEEDED");
        let persisted: (String, String) = database.connection().query_row(
            "SELECT id,independence_group FROM evidence_source WHERE provider='tvmaze' AND provider_record_id='episode-303'",
            [],
            |row| Ok((row.get(0)?, row.get(1)?)),
        ).unwrap();
        assert_eq!(persisted.0, canonical_source_id.to_string());
        assert_eq!(persisted.1, second_bundle.sources[0].independence_group);
    }

    #[test]
    fn exact_source_snapshot_accepts_a_new_trusted_provider_record_binding() {
        let mut database = setup();
        let (first_preview, first_hash, first_request) =
            create_preview(&mut database, "unbound source run", "source-binding-first");
        let first_job = consume(&mut database, &first_preview, &first_hash, &first_request);
        assert!(database.claim_research_execution(first_job.id, NOW_MS).unwrap());
        let mut first_bundle = persistence_bundle(first_job.id, "required_episode");
        let canonical_source_id = first_bundle.sources[0].id;
        first_bundle.sources[0].provider_record_id = None;
        database.complete_research(first_job.id, &first_bundle, NOW_MS + 1).unwrap();

        let (second_preview, second_hash, second_request) =
            create_preview(&mut database, "bound source run", "source-binding-second");
        let second_job = consume(&mut database, &second_preview, &second_hash, &second_request);
        assert!(database.claim_research_execution(second_job.id, NOW_MS + 2).unwrap());
        let second_bundle = persistence_bundle(second_job.id, "required_episode");
        assert_ne!(canonical_source_id, second_bundle.sources[0].id);
        assert_eq!(second_bundle.sources[0].provider_record_id.as_deref(), Some("episode-303"));

        let completed = database.complete_research(second_job.id, &second_bundle, NOW_MS + 3).unwrap();
        assert_eq!(completed.state, "SUCCEEDED");
        let persisted: (String, Option<String>) = database.connection().query_row(
            "SELECT id,provider_record_id FROM evidence_source WHERE canonical_url=?1 AND content_sha256=?2",
            params![second_bundle.sources[0].canonical_url, second_bundle.sources[0].content_sha256],
            |row| Ok((row.get(0)?, row.get(1)?)),
        ).unwrap();
        assert_eq!(persisted.0, canonical_source_id.to_string());
        assert_eq!(persisted.1.as_deref(), Some("episode-303"));
    }

    #[test]
    fn reusable_discussion_cache_never_extends_the_refresh_deadline() {
        let mut database = setup();
        let (preview, hash, request) = create_preview(&mut database, "romance TV", "reuse-evidence");
        let job = consume(&mut database, &preview, &hash, &request);
        let source_id = Uuid::new_v4();
        let claim_id = Uuid::new_v4();
        database.connection_mut().execute(
            "INSERT INTO evidence_source(
                id,provider,provider_record_id,source_type,canonical_url,title,author_or_channel,
                source_created_at_ms,page_published_at_ms,retrieved_at_ms,query,window_start_ms,window_end_ms,
                independence_group,policy_class,content_sha256,refresh_due_at_ms,purge_due_at_ms,
                expires_at_ms,deletion_required_at_ms,deleted_at_ms,fetch_status
             ) VALUES (?1,'openai',NULL,'ARTICLE','https://techradar.com/example-show',
                'Example Show current discussion','TechRadar',?2,?2,?2,'romance TV',?3,?2,
                'owner:future-plc','openai-web-evidence-v1',?4,?5,?6,?5,NULL,NULL,'SUCCESS')",
            params![
                source_id.to_string(),
                NOW_MS,
                NOW_MS - 86_400_000,
                "a".repeat(64),
                NOW_MS + 3_600_000,
                NOW_MS + 86_400_000,
            ],
        ).unwrap();
        let source_contract = serde_json::json!({
            "schemaVersion":"2.0.0","sourceId":source_id,"provider":"openai",
            "providerRecordId":null,"sourceType":"ARTICLE",
            "canonicalUrl":"https://techradar.com/example-show","title":"Example Show current discussion",
            "authorOrChannel":"TechRadar","sourceCreatedAt":"2026-08-15T12:00:00Z",
            "sourceUpdatedAt":null,"pagePublishedAt":"2026-08-15T12:00:00Z",
            "retrievedAt":"2026-08-15T12:00:00Z","query":"romance TV",
            "windowStart":"2026-08-14T12:00:00Z","windowEnd":"2026-08-15T12:00:00Z",
            "policyClass":"openai-web-evidence-v1","refreshDueAt":"2026-08-15T13:00:00Z",
            "purgeDueAt":"2026-08-16T12:00:00Z","expiresAt":"2026-08-15T13:00:00Z",
            "deletionRequiredAt":null,"contentSha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "independenceGroup":"owner:future-plc"
        });
        let claim_contract = serde_json::json!({
            "schemaVersion":"2.0.0","claimId":claim_id,"sourceId":source_id,
            "claimKind":"VIEWER_DISCUSSION","excerptType":"PARAPHRASE",
            "text":"Example Show current discussion","verification":"SECONDARY_CORROBORATED",
            "episodeLocator":null,"quoteFact":null,"whyNowEvent":null,"sceneFact":null,"castFact":null,
            "eventOrReleaseAt":null,"confidence":0.8,"supportsWhyNow":true,
            "contentSha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        });
        database.connection_mut().execute(
            "INSERT INTO evidence_claim(
                id,source_id,claim_kind,excerpt_type,text,episode_locator_json,quote_fact_json,
                why_now_event_json,scene_fact_json,cast_fact_json,event_or_release_at_ms,verification,
                confidence_ppm,supports_why_now,content_sha256,canonical_contract_json
             ) VALUES (?1,?2,'VIEWER_DISCUSSION','PARAPHRASE','Example Show current discussion',
                NULL,NULL,NULL,NULL,NULL,NULL,'SECONDARY_CORROBORATED',800000,1,?3,?4)",
            params![claim_id.to_string(), source_id.to_string(), "b".repeat(64), claim_contract.to_string()],
        ).unwrap();
        database.connection_mut().execute(
            "UPDATE research_run SET status='SUCCEEDED',evidence_sources_json=?2,
             evidence_claims_json=?3,finished_at_ms=?4 WHERE job_id=?1",
            params![job.id.to_string(), serde_json::json!([source_contract]).to_string(), serde_json::json!([claim_contract]).to_string(), NOW_MS],
        ).unwrap();

        let current = database.reusable_research_evidence(NOW_MS + 1, 64, 128).unwrap();
        assert_eq!(current.sources.len(), 1);
        assert_eq!(current.claims.len(), 1);
        database.connection_mut().execute(
            "UPDATE evidence_source SET refresh_due_at_ms=?2 WHERE id=?1",
            params![source_id.to_string(), NOW_MS + 1],
        ).unwrap();
        let due = database.reusable_research_evidence(NOW_MS + 1, 64, 128).unwrap();
        assert!(due.sources.is_empty());
        assert!(due.claims.is_empty());
    }

    #[test]
    fn repeated_provider_identity_with_changed_content_fails_closed() {
        let mut database = setup();
        let (first_preview, first_hash, first_request) =
            create_preview(&mut database, "first collision run", "source-collision-first");
        let first_job = consume(&mut database, &first_preview, &first_hash, &first_request);
        assert!(database.claim_research_execution(first_job.id, NOW_MS).unwrap());
        let first_bundle = persistence_bundle(first_job.id, "required_episode");
        database.complete_research(first_job.id, &first_bundle, NOW_MS + 1).unwrap();

        let (second_preview, second_hash, second_request) =
            create_preview(&mut database, "second collision run", "source-collision-second");
        let second_job = consume(&mut database, &second_preview, &second_hash, &second_request);
        assert!(database.claim_research_execution(second_job.id, NOW_MS + 2).unwrap());
        let state_before_completion = database.job(second_job.id).unwrap().state;
        let mut conflicting = persistence_bundle(second_job.id, "required_episode");
        conflicting.sources[0].content_sha256 = sha256_hex(b"different source content");
        assert!(database.complete_research(second_job.id, &conflicting, NOW_MS + 3).is_err());
        assert_eq!(database.job(second_job.id).unwrap().state, state_before_completion);
        let source_count: i64 = database.connection().query_row(
            "SELECT COUNT(*) FROM evidence_source WHERE provider='tvmaze' AND provider_record_id='episode-303'",
            [],
            |row| row.get(0),
        ).unwrap();
        assert_eq!(source_count, 1);
    }

    #[test]
    fn one_tvmaze_person_can_have_distinct_cast_credit_sources() {
        let mut database = setup();
        let (first_preview, first_hash, first_request) =
            create_preview(&mut database, "Sterling Point cast", "cast-credit-first");
        let first_job = consume(&mut database, &first_preview, &first_hash, &first_request);
        assert!(database.claim_research_execution(first_job.id, NOW_MS).unwrap());
        let mut first_bundle = persistence_bundle(first_job.id, "required_episode");
        first_bundle.sources[0].provider_record_id = Some(format!("cast-sha256:v1:{}", "a".repeat(64)));
        first_bundle.sources[0].canonical_url = "https://www.tvmaze.com/people/3388/jeffrey-dean-morgan".to_owned();
        first_bundle.sources[0].content_sha256 = sha256_hex(b"Jeffrey Dean Morgan as Joe Anderson in Sterling Point");
        database.complete_research(first_job.id, &first_bundle, NOW_MS + 1).unwrap();

        let (second_preview, second_hash, second_request) =
            create_preview(&mut database, "Dead City cast", "cast-credit-second");
        let second_job = consume(&mut database, &second_preview, &second_hash, &second_request);
        assert!(database.claim_research_execution(second_job.id, NOW_MS + 2).unwrap());
        let mut second_bundle = persistence_bundle(second_job.id, "required_episode");
        second_bundle.sources[0].provider_record_id = Some(format!("cast-sha256:v1:{}", "b".repeat(64)));
        second_bundle.sources[0].canonical_url = "https://www.tvmaze.com/people/3388/jeffrey-dean-morgan".to_owned();
        second_bundle.sources[0].content_sha256 = sha256_hex(b"Jeffrey Dean Morgan as Negan in The Walking Dead: Dead City");
        let completed = database.complete_research(second_job.id, &second_bundle, NOW_MS + 3).unwrap();
        assert_eq!(completed.state, "SUCCEEDED");

        let source_count: i64 = database.connection().query_row(
            "SELECT COUNT(*) FROM evidence_source WHERE provider='tvmaze' AND canonical_url=?1",
            ["https://www.tvmaze.com/people/3388/jeffrey-dean-morgan"],
            |row| row.get(0),
        ).unwrap();
        assert_eq!(source_count, 2);
    }
}
