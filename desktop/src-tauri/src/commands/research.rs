use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use std::path::Path;

use rusqlite::OptionalExtension;
use serde::{Deserialize, Serialize};
use tauri::State;
use uuid::Uuid;
use zeroize::Zeroizing;

use crate::cost::ProviderConfig;
use crate::credentials::{CredentialProvider, CredentialStore, WindowsCredentialStore};
use crate::database::repositories::{
    BeginProviderRun, CachePutInput, JobRecord, NewCostPreview, NewResearchJob, ReconcileProviderRun,
    ReservationCapability, DEFAULT_PROJECT_ID,
};
use crate::database::Database;
use crate::domain::CanonicalResearchIntent;
use crate::security::{limits, sha256_hex};
use crate::worker::protocol::{self, ProviderOutcome, ProviderStarted, WorkerMessage};
use crate::worker::WorkerSupervisor;
use crate::{AppError, AppResult, AppState};

const EXECUTION_TIMEOUT: Duration = Duration::from_secs(5 * 60);
const PROMPT_VERSION: &str = "m1-research-2026-08-18-r61";

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct ResearchIntentInput {
    schema_version: String,
    prompt: String,
    media_kinds: Option<Vec<String>>,
    region: Option<String>,
    freshness_days: Option<u32>,
    spoiler_policy: Option<String>,
    exclusions: Option<Vec<String>>,
    max_results: Option<u32>,
}

impl ResearchIntentInput {
    fn validate(&self) -> AppResult<()> {
        if self.schema_version != "2.0.0" {
            return Err(AppError::Validation("research input schema is unsupported".to_owned()));
        }
        limits::validate_prompt(&self.prompt)?;
        if self.region.as_deref().is_some_and(|value| !matches!(value, "US" | "CA" | "GB" | "AU")) {
            return Err(AppError::Validation("research region override is unsupported".to_owned()));
        }
        if self.freshness_days.is_some_and(|value| !(1..=90).contains(&value)) {
            return Err(AppError::Validation("freshness override is outside 1-90 days".to_owned()));
        }
        if self.max_results.is_some_and(|value| !(1..=10).contains(&value)) {
            return Err(AppError::Validation("result-count override is outside 1-10".to_owned()));
        }
        if let Some(values) = &self.exclusions { limits::validate_exclusions(values)?; }
        if let Some(values) = &self.media_kinds {
            if values.is_empty() || values.len() > 5
                || values.iter().any(|value| !matches!(value.as_str(), "TV_EPISODE" | "TV_SERIES" | "FILM" | "TRAILER" | "OFFICIAL_CLIP"))
            {
                return Err(AppError::Validation("media-kind override is invalid".to_owned()));
            }
        }
        if self.spoiler_policy.as_deref().is_some_and(|value| !matches!(value, "AVOID" | "CURRENT_EPISODE" | "ALLOW")) {
            return Err(AppError::Validation("spoiler override is invalid".to_owned()));
        }
        Ok(())
    }

    fn canonical_json_and_hash(&self) -> AppResult<(String, String)> {
        self.validate()?;
        let json = serde_json::to_string(&serde_json::to_value(self)?)?;
        Ok((json.clone(), sha256_hex(json.as_bytes())))
    }

    fn validate_normalized(&self, normalized: &CanonicalResearchIntent) -> AppResult<()> {
        let exact_exclusions = self.exclusions.as_ref().is_none_or(|values| values.iter().all(|value| {
            normalized.exclusions().iter().any(|candidate| candidate.eq_ignore_ascii_case(value))
        }));
        if normalized.query() != self.prompt
            || self.media_kinds.as_ref().is_some_and(|value| value.as_slice() != normalized.media_kinds())
            || self.region.as_deref().is_some_and(|value| value != normalized.region())
            || self.freshness_days.is_some_and(|value| i64::from(value) != normalized.freshness_days())
            || self.max_results.is_some_and(|value| i64::from(value) != normalized.max_results())
            || self.spoiler_policy.as_deref().is_some_and(|value| value != normalized.spoiler_policy())
            || !exact_exclusions
        {
            return Err(AppError::Worker("worker normalization dropped or altered an explicit research constraint".to_owned()));
        }
        Ok(())
    }
}

#[derive(Serialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct PreviewPayload<'a> {
    schema_version: &'static str,
    intent: &'a ResearchIntentInput,
    input_sha256: &'a str,
    now_unix_ms: i64,
}

#[derive(Serialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct ExecuteCapability<'a> {
    provider_run_id: Uuid,
    reservation_id: Uuid,
    planned_call_id: Uuid,
    provider: &'a str,
    operation: &'a str,
    configured_model: &'a Option<String>,
    resolved_model: &'a Option<String>,
    maximum_micro_usd: i64,
    max_requests: i64,
    max_tool_calls: i64,
    max_input_tokens: i64,
    max_output_tokens: i64,
    allow_one_repair: bool,
    retention_mode: &'a str,
    data_use_mode: &'a str,
    no_storage_mode: &'a str,
    privacy_mode: &'a str,
    policy_class: &'a str,
    evidence_ttl_seconds: i64,
    refresh_after_seconds: i64,
    purge_after_seconds: i64,
    deletion_after_seconds: Option<i64>,
    credential: Option<&'a str>,
    provider_config: &'a ProviderConfig,
}

#[derive(Serialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct ExecutePayload<'a> {
    schema_version: &'static str,
    job_id: Uuid,
    research_run_id: Uuid,
    input_sha256: &'a str,
    intent: &'a ResearchIntentInput,
    normalized_intent: &'a serde_json::Value,
    capabilities: &'a [ExecuteCapability<'a>],
    reusable_evidence_sources: &'a [serde_json::Value],
    reusable_evidence_claims: &'a [serde_json::Value],
    generated_at: &'a str,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct CachedBundle {
    schema_version: String,
    result: serde_json::Value,
    evidence_sources: Vec<serde_json::Value>,
    evidence_claims: Vec<serde_json::Value>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ResearchRunView {
    job_id: Uuid,
    status: String,
    progress_percent: i64,
    phase: String,
    result: Option<serde_json::Value>,
    sanitized_error: Option<String>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct VerifierDiagnosticReport {
    pub job_id: Uuid,
    pub diagnostic: String,
    pub provider_request_id: Option<String>,
    pub provider_outcome: String,
    pub configured_model: Option<String>,
    pub resolved_model: Option<String>,
    pub requests: Option<i64>,
    pub input_tokens: Option<i64>,
    pub cached_input_tokens: Option<i64>,
    pub output_tokens: Option<i64>,
    pub reasoning_tokens: Option<i64>,
    pub tool_invocations: Option<i64>,
    pub charged_or_held_micro_usd: i64,
    pub cost_state: String,
}

fn view(record: JobRecord) -> AppResult<ResearchRunView> {
    let result = record.result_contract_json
        .map(|value| serde_json::from_str(&value))
        .transpose()
        .map_err(|_| AppError::DatabaseInvariant("persisted research result is invalid".to_owned()))?;
    Ok(ResearchRunView {
        job_id: record.id,
        status: record.state,
        progress_percent: record.progress_percent,
        phase: record.phase,
        result,
        sanitized_error: record.sanitized_error,
    })
}

/// Execute the explicitly approved seeded OpenAI verifier-only diagnostic
/// through the same WinCred, reservation, worker, quota, and reconciliation
/// boundaries as an interactive research run.  The fixed plan includes free
/// TVmaze metadata, one paid verifier, and no synthesis or other paid provider.
pub fn run_openai_verifier_diagnostic(
    database_path: &Path,
    resource_dir: &Path,
    worker_temp: &Path,
) -> AppResult<VerifierDiagnosticReport> {
    let intent = ResearchIntentInput {
        schema_version: "2.0.0".to_owned(),
        prompt: "romance/romcom TV, preferably a new episode from the last three days, no K-drama, no reality TV".to_owned(),
        media_kinds: Some(vec!["TV_EPISODE".to_owned()]),
        region: Some("US".to_owned()),
        freshness_days: Some(3),
        spoiler_policy: Some("CURRENT_EPISODE".to_owned()),
        exclusions: Some(vec!["K-drama".to_owned(), "reality TV".to_owned()]),
        max_results: Some(5),
    };
    let (input_json, input_sha256) = intent.canonical_json_and_hash()?;
    let now_ms = crate::unix_time_ms()?;
    let mut database = Database::open(database_path)?;
    crate::provider_catalog::install(&mut database, now_ms)?;
    database.run_policy_maintenance(now_ms)?;

    let mut worker = WorkerSupervisor::from_paths(resource_dir, worker_temp);
    let preview_request_id = Uuid::new_v4();
    worker.start()?;
    worker.send(
        "research.preview",
        preview_request_id,
        PreviewPayload {
            schema_version: protocol::PAYLOAD_SCHEMA_VERSION,
            intent: &intent,
            input_sha256: &input_sha256,
            now_unix_ms: now_ms,
        },
    )?;
    let normalized_value = match worker.receive(Duration::from_secs(15))? {
        WorkerMessage::ResearchPreviewResult(payload) => payload.normalized_intent,
        _ => {
            worker.abort_request(preview_request_id);
            return Err(AppError::Worker(
                "worker returned the wrong diagnostic preview response".to_owned(),
            ));
        }
    };
    let normalized = crate::domain::parse_intent(normalized_value)?;
    intent.validate_normalized(&normalized)?;
    let normalized_json = normalized.to_canonical_json()?;
    let calls = crate::provider_catalog::build_openai_verifier_diagnostic_plan(
        &database,
        now_ms,
    )?;
    if calls.len() != 2
        || calls[0].provider != "tvmaze"
        || calls[0].operation != "research.metadata"
        || calls[0].reservation_micro_usd != 0
        || calls[0].max_requests != 16
        || calls[1].provider != "openai"
        || calls[1].operation != "research.web_verify"
        || calls[1].reservation_micro_usd != 91_200
        || calls[1].max_requests != 6
    {
        return Err(AppError::Security(
            "verifier diagnostic plan escaped its approved boundary".to_owned(),
        ));
    }
    let run_scope_key = format!("verifier-diagnostic-{}", Uuid::new_v4());
    let preview = database.create_cost_preview(&NewCostPreview {
        project_id: DEFAULT_PROJECT_ID,
        run_scope_key: &run_scope_key,
        input_sha256: &input_sha256,
        normalized_intent_json: &normalized_json,
        calls: &calls,
        now_ms,
        expires_at_ms: now_ms.saturating_add(5 * 60 * 1000),
    })?;
    if preview.maximum_cost_micro_usd != 91_200 {
        return Err(AppError::Budget(
            "verifier diagnostic preview exceeded the approved cap".to_owned(),
        ));
    }
    let job = database.consume_preview_and_create_job(&NewResearchJob {
        consent_token: preview.consent_token,
        input_sha256: &input_sha256,
        input_contract_json: &input_json,
        raw_query: &intent.prompt,
        schema_version: &intent.schema_version,
        now_ms,
    })?;
    if !database.claim_research_execution(job.id, now_ms)? {
        return Err(AppError::DatabaseInvariant(
            "verifier diagnostic execution could not be claimed".to_owned(),
        ));
    }

    let database = Arc::new(Mutex::new(database));
    let worker = Arc::new(Mutex::new(worker));
    let credentials: Arc<dyn CredentialStore> = Arc::new(WindowsCredentialStore);
    let execution_error = execute_research(
        job.id,
        &database,
        &worker,
        credentials.as_ref(),
    )
    .err()
    .ok_or_else(|| {
        AppError::Worker(
            "verifier-only diagnostic unexpectedly produced a full research result".to_owned(),
        )
    })?;
    if let Ok(mut supervisor) = worker.lock() {
        let _ = supervisor.stop();
    }
    let diagnostic = crate::security::sanitized_error(&execution_error.to_string());
    let finished_ms = crate::unix_time_ms()?;
    let mut database = database.lock().map_err(|_| AppError::Internal)?;
    database.fail_job_safely(job.id, false, &diagnostic, finished_ms)?;

    type ProviderRow = (
        Option<String>,
        String,
        Option<String>,
        Option<String>,
        Option<i64>,
        Option<i64>,
        Option<i64>,
        Option<i64>,
        Option<i64>,
        Option<i64>,
        String,
    );
    let row: ProviderRow = database
        .connection()
        .query_row(
            "SELECT provider_request_id,outcome,configured_model,resolved_model,requests,input_tokens,cached_input_tokens,output_tokens,reasoning_tokens,tool_invocations,id FROM provider_run WHERE job_id=?1 AND provider='openai' ORDER BY started_at_ms DESC LIMIT 1",
            [job.id.to_string()],
            |row| {
                Ok((
                    row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?, row.get(4)?,
                    row.get(5)?, row.get(6)?, row.get(7)?, row.get(8)?, row.get(9)?,
                    row.get(10)?,
                ))
            },
        )
        .optional()?
        .ok_or_else(|| {
            AppError::DatabaseInvariant(
                "verifier diagnostic did not record a provider run".to_owned(),
            )
        })?;
    let cost: (i64, String) = database
        .connection()
        .query_row(
            "SELECT micro_usd,state FROM cost_entry WHERE job_id=?1 AND provider_run_id=?2 AND state IN ('ACTUAL','UNVERIFIED') ORDER BY created_at_ms DESC LIMIT 1",
            rusqlite::params![job.id.to_string(), row.10],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )
        .optional()?
        .ok_or_else(|| {
            AppError::DatabaseInvariant(
                "verifier diagnostic did not reconcile its reservation".to_owned(),
            )
        })?;
    if cost.0 > 91_200 {
        return Err(AppError::Budget(
            "verifier diagnostic charge or hold exceeded the approved cap".to_owned(),
        ));
    }
    Ok(VerifierDiagnosticReport {
        job_id: job.id,
        diagnostic,
        provider_request_id: row.0,
        provider_outcome: row.1,
        configured_model: row.2,
        resolved_model: row.3,
        requests: row.4,
        input_tokens: row.5,
        cached_input_tokens: row.6,
        output_tokens: row.7,
        reasoning_tokens: row.8,
        tool_invocations: row.9,
        charged_or_held_micro_usd: cost.0,
        cost_state: cost.1,
    })
}

#[tauri::command]
pub fn preview_research(
    state: State<'_, AppState>,
    intent: ResearchIntentInput,
) -> AppResult<crate::database::repositories::CostPreviewRecord> {
    let (input_json, hash) = intent.canonical_json_and_hash()?;
    let now_ms = crate::unix_time_ms()?;
    let request_id = Uuid::new_v4();
    let normalized_value = {
        let mut worker = state.worker.lock().map_err(|_| AppError::Internal)?;
        worker.start()?;
        worker.send("research.preview", request_id, PreviewPayload {
            schema_version: protocol::PAYLOAD_SCHEMA_VERSION,
            intent: &intent,
            input_sha256: &hash,
            now_unix_ms: now_ms,
        })?;
        match worker.receive(Duration::from_secs(15))? {
            WorkerMessage::ResearchPreviewResult(payload) => payload.normalized_intent,
            _ => {
                worker.abort_request(request_id);
                return Err(AppError::Worker("worker returned the wrong preview response".to_owned()));
            }
        }
    };
    let normalized = match crate::domain::parse_intent(normalized_value) {
        Ok(value) => value,
        Err(error) => {
            state.worker.lock().map_err(|_| AppError::Internal)?.abort_request(request_id);
            return Err(error);
        }
    };
    if let Err(error) = intent.validate_normalized(&normalized) {
        state.worker.lock().map_err(|_| AppError::Internal)?.abort_request(request_id);
        return Err(error);
    }
    let normalized_json = normalized.to_canonical_json()?;
    let run_scope_key = Uuid::new_v4().to_string();
    let mut database = state.database.lock().map_err(|_| AppError::Internal)?;
    database.run_policy_maintenance(now_ms)?;
    let calls = crate::provider_catalog::build_plan(&database, &normalized, &hash, now_ms)?;
    // Keep the exact UI request alive only through its hash; the normalized
    // intent and trusted call plan are what the consent token signs.
    debug_assert_eq!(sha256_hex(input_json.as_bytes()), hash);
    database.create_cost_preview(&NewCostPreview {
        project_id: DEFAULT_PROJECT_ID,
        run_scope_key: &run_scope_key,
        input_sha256: &hash,
        normalized_intent_json: &normalized_json,
        calls: &calls,
        now_ms,
        expires_at_ms: now_ms.saturating_add(5 * 60 * 1000),
    })
}

#[tauri::command]
pub fn start_research(
    state: State<'_, AppState>,
    intent: ResearchIntentInput,
    consent_token: Uuid,
) -> AppResult<ResearchRunView> {
    let (input_json, hash) = intent.canonical_json_and_hash()?;
    let now_ms = crate::unix_time_ms()?;
    let record = {
        let mut database = state.database.lock().map_err(|_| AppError::Internal)?;
        database.run_policy_maintenance(now_ms)?;
        database.consume_preview_and_create_job(&NewResearchJob {
            consent_token,
            input_sha256: &hash,
            input_contract_json: &input_json,
            raw_query: &intent.prompt,
            schema_version: &intent.schema_version,
            now_ms,
        })?
    };
    let claimed = if record.state == "QUEUED" {
        state.database.lock().map_err(|_| AppError::Internal)?
            .claim_research_execution(record.id, now_ms)?
    } else { false };
    if claimed {
        if let Err(error) = spawn_execution(
            record.id,
            Arc::clone(&state.database),
            Arc::clone(&state.worker),
            Arc::clone(&state.credentials),
        ) {
            state.database.lock().map_err(|_| AppError::Internal)?
                .fail_job_safely(record.id, false, &error.to_string(), crate::unix_time_ms()?)?;
            return Err(error);
        }
    }
    let current = state.database.lock().map_err(|_| AppError::Internal)?.job(record.id)?;
    view(current)
}

fn spawn_execution(
    job_id: Uuid,
    database: Arc<Mutex<Database>>,
    worker: Arc<Mutex<WorkerSupervisor>>,
    credentials: Arc<dyn crate::credentials::CredentialStore>,
) -> AppResult<()> {
    std::thread::Builder::new()
        .name(format!("ai-edit-research-{job_id}"))
        .spawn(move || {
            if let Err(error) = execute_research(job_id, &database, &worker, credentials.as_ref()) {
                if let Ok(mut worker) = worker.lock() {
                    worker.abort_request(job_id);
                }
                if let Ok(mut database) = database.lock() {
                    let cancelled = database.job(job_id).ok().is_some_and(|job| matches!(job.state.as_str(), "CANCELLING" | "CANCELLED"));
                    let _ = database.fail_job_safely(job_id, cancelled, &error.to_string(), crate::unix_time_ms().unwrap_or(0));
                }
            }
        })
        .map_err(|_| AppError::Internal)?;
    Ok(())
}

fn execute_research(
    job_id: Uuid,
    database: &Arc<Mutex<Database>>,
    worker: &Arc<Mutex<WorkerSupervisor>>,
    credentials: &dyn crate::credentials::CredentialStore,
) -> AppResult<()> {
    let (context, generated_at) = {
        let database = database.lock().map_err(|_| AppError::Internal)?;
        let job = database.job(job_id)?;
        if matches!(job.state.as_str(), "CANCELLING" | "CANCELLED") {
            return Err(AppError::Worker("research was cancelled before execution".to_owned()));
        }
        (database.execution_context(job_id)?, database.current_rfc3339()?)
    };
    let intent: ResearchIntentInput = serde_json::from_str(&context.input_contract_json)
        .map_err(|_| AppError::DatabaseInvariant("stored research request is invalid".to_owned()))?;
    let (canonical_input, recomputed_hash) = intent.canonical_json_and_hash()?;
    if canonical_input != context.input_contract_json || recomputed_hash != context.input_sha256 {
        return Err(AppError::DatabaseInvariant("stored research request hash changed".to_owned()));
    }
    let normalized_value: serde_json::Value = serde_json::from_str(&context.normalized_intent_json)?;
    let normalized = crate::domain::parse_intent(normalized_value.clone())?;
    intent.validate_normalized(&normalized)?;
    if context.capabilities.is_empty() {
        let replay = database.lock().map_err(|_| AppError::Internal)?
            .whole_bundle_replay(job_id, crate::unix_time_ms()?)?
            .ok_or_else(|| AppError::DatabaseInvariant("approved whole-result cache binding disappeared".to_owned()))?;
        let strict = crate::worker::protocol::parse_strict_json_bytes(replay.contract_json.as_bytes())?;
        let mut cached: CachedBundle = serde_json::from_value(strict)
            .map_err(|_| AppError::DatabaseInvariant("whole-result cache violates its strict schema".to_owned()))?;
        if cached.schema_version != protocol::PAYLOAD_SCHEMA_VERSION {
            return Err(AppError::DatabaseInvariant("whole-result cache schema version mismatch".to_owned()));
        }
        // A cached result's generatedAt is part of its validated semantic snapshot:
        // opportunity freshness scores were computed against that instant. Rekey only
        // run-owned UUIDs. Current replay eligibility is checked separately below so
        // preserving the original timestamp cannot extend an evidence deadline.
        rekey_cached_result(&mut cached.result, job_id)?;
        let trusted_policies = database.lock().map_err(|_| AppError::Internal)?
            .trusted_evidence_policies(crate::unix_time_ms()?)?;
        crate::domain::validate_cached_evidence_currentness(
            &cached.evidence_sources,
            &generated_at,
            &trusted_policies,
        )?;
        let bundle = crate::domain::parse_bundle(
            cached.result, cached.evidence_sources, cached.evidence_claims, job_id, &normalized,
            &trusted_policies,
        )?;
        let mut database = database.lock().map_err(|_| AppError::Internal)?;
        database.record_whole_bundle_replay(job_id, &replay, crate::unix_time_ms()?)?;
        database.complete_research(job_id, &bundle, crate::unix_time_ms()?)?;
        return Ok(());
    }

    let evidence_now_ms = crate::unix_time_ms()?;
    let (reusable_evidence, reusable_policies) = {
        let database = database.lock().map_err(|_| AppError::Internal)?;
        (
            database.reusable_research_evidence(evidence_now_ms, 64, 128)?,
            database.trusted_evidence_policies(evidence_now_ms)?,
        )
    };
    crate::domain::validate_reusable_evidence(
        &reusable_evidence.sources,
        &reusable_evidence.claims,
        &generated_at,
        &reusable_policies,
    )?;
    let secrets = load_capability_secrets(&context.capabilities, credentials)?;
    let wire_capabilities = context.capabilities.iter().zip(&secrets).map(|(capability, secret)| ExecuteCapability {
        provider_run_id: capability.provider_run_id,
        reservation_id: capability.reservation_id,
        planned_call_id: capability.planned_call_id,
        provider: &capability.provider,
        operation: &capability.operation,
        configured_model: &capability.configured_model,
        resolved_model: &capability.resolved_model,
        maximum_micro_usd: capability.maximum_micro_usd,
        max_requests: capability.max_requests,
        max_tool_calls: capability.max_tool_calls,
        max_input_tokens: capability.max_input_tokens,
        max_output_tokens: capability.max_output_tokens,
        allow_one_repair: capability.allow_one_repair,
        retention_mode: &capability.retention_mode,
        data_use_mode: &capability.data_use_mode,
        no_storage_mode: &capability.no_storage_mode,
        privacy_mode: &capability.privacy_mode,
        policy_class: &capability.policy_class,
        evidence_ttl_seconds: capability.evidence_ttl_seconds,
        refresh_after_seconds: capability.refresh_after_seconds,
        purge_after_seconds: capability.purge_after_seconds,
        deletion_after_seconds: capability.deletion_after_seconds,
        credential: secret.as_deref().map(String::as_str),
        provider_config: &capability.provider_config,
    }).collect::<Vec<_>>();
    {
        let mut worker = worker.lock().map_err(|_| AppError::Internal)?;
        worker.start()?;
        worker.send("research.execute", job_id, ExecutePayload {
            schema_version: protocol::PAYLOAD_SCHEMA_VERSION,
            job_id,
            research_run_id: job_id,
            input_sha256: &context.input_sha256,
            intent: &intent,
            normalized_intent: &normalized_value,
            capabilities: &wire_capabilities,
            reusable_evidence_sources: &reusable_evidence.sources,
            reusable_evidence_claims: &reusable_evidence.claims,
            generated_at: &generated_at,
        })?;
    }
    drop(wire_capabilities);

    let started = Instant::now();
    loop {
        if started.elapsed() > EXECUTION_TIMEOUT {
            worker.lock().map_err(|_| AppError::Internal)?.abort_active();
            return Err(AppError::Worker("research worker exceeded its bounded execution time".to_owned()));
        }
        let message = worker.lock().map_err(|_| AppError::Internal)?.poll(Duration::from_millis(100))?;
        let Some(message) = message else { continue; };
        match message {
            WorkerMessage::ProviderStarted(payload) => {
                authorize_provider_start(job_id, &context.input_sha256, &context.capabilities, &payload, database)?;
                worker.lock().map_err(|_| AppError::Internal)?.send("provider.started.ack", job_id, &payload)?;
            }
            WorkerMessage::ResearchProgress(progress) => {
                if progress.job_id != job_id { return Err(AppError::Worker("worker progress job identity mismatch".to_owned())); }
                database.lock().map_err(|_| AppError::Internal)?.update_job_progress(job_id, progress.percent, &progress.phase, crate::unix_time_ms()?)?;
            }
            WorkerMessage::ResearchCancelAck(ack) => {
                if ack.job_id != job_id { return Err(AppError::Worker("worker cancellation identity mismatch".to_owned())); }
            }
            WorkerMessage::ResearchResult(payload) => {
                if payload.job_id != job_id { return Err(AppError::Worker("worker result job identity mismatch".to_owned())); }
                reconcile_all(job_id, &context.capabilities, &payload.provider_outcomes, database)?;
                require_host_generated_at(&payload.result, &generated_at)?;
                let trusted_policies = database.lock().map_err(|_| AppError::Internal)?
                    .trusted_evidence_policies(crate::unix_time_ms()?)?;
                let bundle = crate::domain::parse_bundle(
                    payload.result, payload.evidence_sources, payload.evidence_claims, job_id, &normalized,
                    &trusted_policies,
                )?;
                let contract = bundle.cache_contract_json()?;
                let output_sha256 = sha256_hex(contract.as_bytes());
                let now_ms = crate::unix_time_ms()?;
                let mut database = database.lock().map_err(|_| AppError::Internal)?;
                database.cache_put(&CachePutInput {
                    provider: "openai", namespace: crate::provider_catalog::BUNDLE_CACHE_NAMESPACE,
                    key: &context.input_sha256, input_sha256: &context.input_sha256,
                    output_sha256: &output_sha256, schema_version: crate::provider_catalog::BUNDLE_CACHE_SCHEMA,
                    model_version: crate::provider_catalog::BUNDLE_CACHE_MODEL,
                    prompt_version: crate::provider_catalog::BUNDLE_CACHE_PROMPT,
                    policy_class: crate::provider_catalog::BUNDLE_CACHE_POLICY,
                    contract_json: &contract, now_ms,
                })?;
                database.complete_research(job_id, &bundle, now_ms)?;
                return Ok(());
            }
            WorkerMessage::ResearchRefusal(detail)
            | WorkerMessage::ResearchIncomplete(detail)
            | WorkerMessage::ResearchError(detail) => {
                if detail.job_id != job_id { return Err(AppError::Worker("worker terminal job identity mismatch".to_owned())); }
                let reconcile_error = reconcile_all(job_id, &context.capabilities, &detail.provider_outcomes, database).err();
                let message = redact_known(&detail.message, &secrets);
                if matches!(reconcile_error.as_ref(), Some(AppError::Budget(_))) {
                    database.lock().map_err(|_| AppError::Internal)?
                        .annotate_provider_accounting_failure(job_id, &message)?;
                }
                return Err(reconcile_error.unwrap_or_else(|| AppError::Provider(message)));
            }
            WorkerMessage::ResearchCancelled(detail) => {
                if detail.job_id != job_id { return Err(AppError::Worker("worker cancellation job identity mismatch".to_owned())); }
                let _ = reconcile_all(job_id, &context.capabilities, &detail.provider_outcomes, database);
                database.lock().map_err(|_| AppError::Internal)?.fail_job_safely(job_id, true, "Research was cancelled.", crate::unix_time_ms()?)?;
                return Ok(());
            }
            _ => return Err(AppError::Worker("worker emitted a response outside the active research operation".to_owned())),
        }
    }
}

fn load_capability_secrets(
    capabilities: &[ReservationCapability],
    credentials: &dyn crate::credentials::CredentialStore,
) -> AppResult<Vec<Option<Zeroizing<String>>>> {
    capabilities.iter().map(|capability| {
        let provider = match capability.provider.as_str() {
            "tvmaze" => return Ok(None),
            "openai" => CredentialProvider::Openai,
            "youtube" => CredentialProvider::Youtube,
            "xai" => CredentialProvider::Xai,
            _ => return Err(AppError::Security("capability names an unsupported credential provider".to_owned())),
        };
        let bytes = credentials.load(provider)?
            .ok_or_else(|| AppError::Credential(format!("{} credential is not configured", provider.as_str())))?;
        limits::validate_secret(&bytes)?;
        let value = String::from_utf8(bytes.to_vec())
            .map_err(|_| AppError::Credential("stored credential is not valid UTF-8".to_owned()))?;
        Ok(Some(Zeroizing::new(value)))
    }).collect()
}

fn authorize_provider_start(
    job_id: Uuid,
    input_sha256: &str,
    capabilities: &[ReservationCapability],
    payload: &ProviderStarted,
    database: &Arc<Mutex<Database>>,
) -> AppResult<()> {
    if payload.job_id != job_id { return Err(AppError::Worker("provider-start job identity mismatch".to_owned())); }
    let capability = capabilities.iter().find(|value| {
        value.provider_run_id == payload.provider_run_id && value.planned_call_id == payload.planned_call_id
    }).ok_or_else(|| AppError::Security("worker requested an unissued provider capability".to_owned()))?;
    let capability_json = serde_json::to_string(capability)?;
    database.lock().map_err(|_| AppError::Internal)?.begin_provider_run(&BeginProviderRun {
        provider_run_id: capability.provider_run_id,
        job_id,
        planned_call_id: capability.planned_call_id,
        capability: &capability_json,
        prompt_version: PROMPT_VERSION,
        schema_version: "2.0.0",
        input_sha256,
        retention_mode: &capability.retention_mode,
        data_use_mode: &capability.data_use_mode,
        privacy_mode: &capability.privacy_mode,
        now_ms: crate::unix_time_ms()?,
    })
}

fn reconcile_all(
    job_id: Uuid,
    capabilities: &[ReservationCapability],
    outcomes: &[ProviderOutcome],
    database: &Arc<Mutex<Database>>,
) -> AppResult<()> {
    let mut seen = std::collections::HashSet::new();
    let mut first_error: Option<AppError> = None;
    for outcome in outcomes {
        let Some(capability) = capabilities.iter().find(|value| {
            value.provider_run_id == outcome.provider_run_id
                && value.planned_call_id == outcome.planned_call_id
        }) else {
            first_error.get_or_insert_with(|| AppError::Security("worker returned usage for an unissued provider run".to_owned()));
            continue;
        };
        if !seen.insert(outcome.planned_call_id)
            || outcome.provider != capability.provider
            || outcome.configured_model != capability.configured_model
            || !resolved_model_observation_is_valid(
                &outcome.outcome,
                outcome.resolved_model.as_deref(),
                capability.resolved_model.as_deref(),
            )
        {
            first_error.get_or_insert_with(|| AppError::Security("worker provider outcome identity is invalid".to_owned()));
            continue;
        }
        if !provider_usage_detail_is_structurally_valid(outcome) {
            first_error.get_or_insert_with(|| AppError::Security("worker provider usage detail is invalid".to_owned()));
            continue;
        }
        let tool_usage = serde_json::to_string(&outcome.tool_usage)?;
        let reconciliation = database.lock().map_err(|_| AppError::Internal)?.reconcile_provider_run(&ReconcileProviderRun {
            provider_run_id: outcome.provider_run_id,
            job_id,
            planned_call_id: outcome.planned_call_id,
            provider_native_ticks: outcome.provider_native_ticks.as_deref(),
            provider_request_id: outcome.provider_request_id.as_deref(),
            outcome: &outcome.outcome,
            requests: outcome.requests,
            input_tokens: outcome.input_tokens,
            cached_input_tokens: outcome.cached_input_tokens,
            output_tokens: outcome.output_tokens,
            reasoning_tokens: outcome.reasoning_tokens,
            tool_invocations: outcome.tool_invocations,
            repair_used: outcome.repair_used,
            tool_usage_json: Some(&tool_usage),
            output_sha256: outcome.output_sha256.as_deref(),
            idempotency_key: &format!("reconcile:{job_id}:{}", outcome.planned_call_id),
            now_ms: crate::unix_time_ms()?,
        });
        match reconciliation {
            Ok(value) if value.usage_verified && !value.exceeded_reservation => {}
            Ok(_) => { first_error.get_or_insert_with(|| AppError::Budget("provider usage could not be verified inside its reservation".to_owned())); }
            Err(error) => { first_error.get_or_insert(error); }
        }
    }
    if let Some(error) = first_error { Err(error) } else { Ok(()) }
}

fn provider_usage_detail_is_structurally_valid(outcome: &ProviderOutcome) -> bool {
    let invalid_text = |value: &str, maximum: usize| {
        value.is_empty() || value.len() > maximum || value.contains(['\r', '\n', '\0'])
    };
    let detail_count_matches = match outcome.tool_invocations {
        Some(count) => usize::try_from(count).ok() == Some(outcome.tool_usage.len()),
        None => outcome.tool_usage.is_empty(),
    };
    detail_count_matches
        && !outcome
            .provider_request_id
            .as_deref()
            .is_some_and(|value| invalid_text(value, 512))
        && !outcome
            .provider_native_ticks
            .as_deref()
            .is_some_and(|value| value.len() > 64)
        && !outcome
            .tool_usage
            .iter()
            .any(|value| invalid_text(value, 256))
}

fn resolved_model_observation_is_valid(
    outcome: &str,
    observed: Option<&str>,
    expected: Option<&str>,
) -> bool {
    observed == expected || (outcome == "FAILED" && observed.is_none())
}

fn redact_known(message: &str, secrets: &[Option<Zeroizing<String>>]) -> String {
    secrets.iter().flatten().fold(message.to_owned(), |value, secret| {
        if secret.is_empty() { value } else { value.replace(secret.as_str(), "<redacted>") }
    })
}

fn require_host_generated_at(result: &serde_json::Value, expected: &str) -> AppResult<()> {
    if !result.get("generatedAt").and_then(serde_json::Value::as_str)
        .is_some_and(|value| crate::domain::timestamps_represent_same_instant(value, expected))
    {
        return Err(AppError::Worker(
            "worker result generation time is not bound to the trusted host clock".to_owned(),
        ));
    }
    Ok(())
}

#[tauri::command]
pub fn get_research_run(state: State<'_, AppState>, job_id: Uuid) -> AppResult<ResearchRunView> {
    let mut database = state.database.lock().map_err(|_| AppError::Internal)?;
    view(database.job_for_display(job_id, crate::unix_time_ms()?)?)
}

#[tauri::command]
pub fn cancel_research(state: State<'_, AppState>, job_id: Uuid) -> AppResult<ResearchRunView> {
    let record = {
        let mut database = state.database.lock().map_err(|_| AppError::Internal)?;
        database.request_cancellation(job_id, crate::unix_time_ms()?)?
    };
    if record.state == "CANCELLING" {
        // The worker is single-job by design. If it has not received execute yet,
        // the background thread observes CANCELLING and exits without a call.
        let _ = state.worker.lock().map_err(|_| AppError::Internal)?.send_cancel(job_id);
        let database = Arc::clone(&state.database);
        let worker = Arc::clone(&state.worker);
        std::thread::Builder::new()
            .name(format!("ai-edit-cancel-watchdog-{job_id}"))
            .spawn(move || {
                std::thread::sleep(Duration::from_secs(3));
                let still_cancelling = database.lock().ok()
                    .and_then(|database| database.job(job_id).ok())
                    .is_some_and(|job| job.state == "CANCELLING");
                if still_cancelling {
                    if let Ok(mut worker) = worker.lock() {
                        worker.abort_request(job_id);
                    }
                    if let Ok(mut database) = database.lock() {
                        let _ = database.fail_job_safely(job_id, true, "Research cancellation required bounded worker termination; started provider reservations remain conservatively unverified.", crate::unix_time_ms().unwrap_or(0));
                    }
                }
            })
            .map_err(|_| AppError::Internal)?;
    }
    view(record)
}

fn rekey_cached_result(result: &mut serde_json::Value, run_id: Uuid) -> AppResult<()> {
    let object = result.as_object_mut()
        .ok_or_else(|| AppError::DatabaseInvariant("cached research result is not an object".to_owned()))?;
    object.insert("runId".to_owned(), serde_json::Value::String(run_id.to_string()));
    let opportunities = object.get_mut("opportunities").and_then(serde_json::Value::as_array_mut)
        .ok_or_else(|| AppError::DatabaseInvariant("cached opportunities are missing".to_owned()))?;
    let mut opportunity_ids = std::collections::HashMap::new();
    let mut request_ids = std::collections::HashMap::new();
    for opportunity in opportunities.iter_mut() {
        let opportunity = opportunity.as_object_mut().ok_or_else(|| AppError::DatabaseInvariant("cached opportunity is invalid".to_owned()))?;
        let old_opportunity = opportunity.get("opportunityId").and_then(serde_json::Value::as_str)
            .ok_or_else(|| AppError::DatabaseInvariant("cached opportunity identity is missing".to_owned()))?.to_owned();
        let old_request = opportunity.get("footageRequestId").and_then(serde_json::Value::as_str)
            .ok_or_else(|| AppError::DatabaseInvariant("cached footage-request identity is missing".to_owned()))?.to_owned();
        let new_opportunity = Uuid::new_v4().to_string();
        let new_request = Uuid::new_v4().to_string();
        if opportunity_ids.insert(old_opportunity, new_opportunity.clone()).is_some()
            || request_ids.insert(old_request, new_request.clone()).is_some()
        {
            return Err(AppError::DatabaseInvariant("cached recommendation identities are not unique".to_owned()));
        }
        opportunity.insert("opportunityId".to_owned(), serde_json::Value::String(new_opportunity));
        opportunity.insert("footageRequestId".to_owned(), serde_json::Value::String(new_request));
    }
    let requests = object.get_mut("footageRequests").and_then(serde_json::Value::as_array_mut)
        .ok_or_else(|| AppError::DatabaseInvariant("cached footage requests are missing".to_owned()))?;
    for request in requests {
        let request = request.as_object_mut().ok_or_else(|| AppError::DatabaseInvariant("cached footage request is invalid".to_owned()))?;
        let old_opportunity = request.get("opportunityId").and_then(serde_json::Value::as_str)
            .ok_or_else(|| AppError::DatabaseInvariant("cached request opportunity identity is missing".to_owned()))?;
        let old_request = request.get("footageRequestId").and_then(serde_json::Value::as_str)
            .ok_or_else(|| AppError::DatabaseInvariant("cached request identity is missing".to_owned()))?;
        let new_opportunity = opportunity_ids.get(old_opportunity)
            .ok_or_else(|| AppError::DatabaseInvariant("cached request lost its opportunity".to_owned()))?.clone();
        let new_request = request_ids.get(old_request)
            .ok_or_else(|| AppError::DatabaseInvariant("cached request lost its reciprocal identity".to_owned()))?.clone();
        request.insert("opportunityId".to_owned(), serde_json::Value::String(new_opportunity));
        request.insert("footageRequestId".to_owned(), serde_json::Value::String(new_request));
        for bucket in ["requiredSources", "optionalSources", "alternativeSources"] {
            let sources = request.get_mut(bucket).and_then(serde_json::Value::as_array_mut)
                .ok_or_else(|| AppError::DatabaseInvariant("cached footage source bucket is invalid".to_owned()))?;
            for source in sources {
                let source = source.as_object_mut().ok_or_else(|| AppError::DatabaseInvariant("cached footage source is invalid".to_owned()))?;
                source.insert("requestedSourceId".to_owned(), serde_json::Value::String(Uuid::new_v4().to_string()));
            }
        }
        let leads = request.get_mut("introLeads").and_then(serde_json::Value::as_array_mut)
            .ok_or_else(|| AppError::DatabaseInvariant("cached intro leads are invalid".to_owned()))?;
        for lead in leads {
            let lead = lead.as_object_mut().ok_or_else(|| AppError::DatabaseInvariant("cached intro lead is invalid".to_owned()))?;
            lead.insert("introLeadId".to_owned(), serde_json::Value::String(Uuid::new_v4().to_string()));
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn canonical_input_hash_matches_sorted_compact_json() {
        let intent = ResearchIntentInput {
            schema_version: "2.0.0".into(), prompt: "current horror movie".into(),
            media_kinds: None, region: None, freshness_days: None, spoiler_policy: None,
            exclusions: None, max_results: None,
        };
        let (json, hash) = intent.canonical_json_and_hash().unwrap();
        assert_eq!(hash, sha256_hex(json.as_bytes()));
        assert!(json.starts_with("{\"exclusions\":"));
    }

    #[test]
    fn result_generation_time_must_echo_the_host_value_exactly() {
        let expected = "2026-08-15T12:00:00.000Z";
        assert!(require_host_generated_at(
            &serde_json::json!({"generatedAt":"2026-08-15T12:00:00Z"}), expected,
        ).is_ok());
        assert!(require_host_generated_at(
            &serde_json::json!({"generatedAt":"2026-08-15T11:59:59.999Z"}), expected,
        ).is_err());
    }

    #[test]
    fn failed_call_may_lack_a_model_observation_but_may_not_change_identity() {
        assert!(resolved_model_observation_is_valid(
            "FAILED",
            None,
            Some("gpt-5.6-luna"),
        ));
        assert!(!resolved_model_observation_is_valid(
            "SUCCESS",
            None,
            Some("gpt-5.6-luna"),
        ));
        assert!(!resolved_model_observation_is_valid(
            "FAILED",
            Some("different-model"),
            Some("gpt-5.6-luna"),
        ));
        assert!(resolved_model_observation_is_valid(
            "SUCCESS",
            Some("gpt-5.6-luna"),
            Some("gpt-5.6-luna"),
        ));
    }

    #[test]
    fn bounded_usage_overrun_is_accounting_data_not_a_malformed_worker_frame() {
        let outcome = ProviderOutcome {
            provider_run_id: Uuid::new_v4(),
            planned_call_id: Uuid::new_v4(),
            provider: "openai".into(),
            outcome: "SUCCESS".into(),
            configured_model: Some("gpt-5.6-luna".into()),
            resolved_model: Some("gpt-5.6-luna".into()),
            provider_request_id: Some("resp_safe".into()),
            requests: Some(1),
            input_tokens: Some(100),
            cached_input_tokens: Some(0),
            output_tokens: Some(10),
            reasoning_tokens: Some(0),
            tool_invocations: Some(5),
            repair_used: Some(false),
            tool_usage: (0..5).map(|index| format!("web_search_call:{index}")) .collect(),
            provider_native_ticks: None,
            output_sha256: Some("a".repeat(64)),
        };
        assert!(provider_usage_detail_is_structurally_valid(&outcome));
        let mut malformed = outcome;
        malformed.tool_usage[0] = "provider\ncontrolled".into();
        assert!(!provider_usage_detail_is_structurally_valid(&malformed));
    }

    #[test]
    fn cached_replay_rekeys_the_complete_run_owned_identity_graph() {
        let old_run = Uuid::new_v4();
        let old_opportunity = Uuid::new_v4();
        let old_request = Uuid::new_v4();
        let old_source = Uuid::new_v4();
        let old_intro = Uuid::new_v4();
        let mut value = serde_json::json!({
            "runId":old_run,
            "generatedAt":"2026-08-15T00:00:00Z",
            "opportunities":[{"opportunityId":old_opportunity,"footageRequestId":old_request}],
            "footageRequests":[{
                "opportunityId":old_opportunity,"footageRequestId":old_request,
                "requiredSources":[{"requestedSourceId":old_source}],
                "optionalSources":[],"alternativeSources":[],
                "introLeads":[{"introLeadId":old_intro}]
            }]
        });
        let new_run = Uuid::new_v4();
        rekey_cached_result(&mut value, new_run).unwrap();
        assert_eq!(value["runId"], new_run.to_string());
        assert_eq!(value["generatedAt"], "2026-08-15T00:00:00Z");
        assert_ne!(value["opportunities"][0]["opportunityId"], old_opportunity.to_string());
        assert_ne!(value["opportunities"][0]["footageRequestId"], old_request.to_string());
        assert_eq!(value["opportunities"][0]["opportunityId"], value["footageRequests"][0]["opportunityId"]);
        assert_eq!(value["opportunities"][0]["footageRequestId"], value["footageRequests"][0]["footageRequestId"]);
        assert_ne!(value["footageRequests"][0]["requiredSources"][0]["requestedSourceId"], old_source.to_string());
        assert_ne!(value["footageRequests"][0]["introLeads"][0]["introLeadId"], old_intro.to_string());
    }
}
