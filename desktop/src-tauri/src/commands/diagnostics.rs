use rusqlite::{params, OptionalExtension, TransactionBehavior};
use serde::{Deserialize, Serialize};
use tauri::State;

use crate::credentials::CredentialProvider;
use crate::security::limits;
use crate::worker::WorkerRuntimeStatus;
use crate::{AppError, AppResult, AppState};

#[derive(Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
enum ProviderAvailability { Ready, Disabled, Unconfigured, Unverified }

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ProviderDiagnosticView {
    provider: String,
    enabled: bool,
    configured_model: Option<String>,
    resolved_model: Option<String>,
    availability: ProviderAvailability,
    price_card_checked_at: Option<String>,
    policy_checked_at: String,
    policy_expires_at: String,
    retention_mode: String,
    data_use_mode: String,
    no_storage_mode: String,
    privacy_mode: String,
    cache_policy: String,
    purge_after_seconds: i64,
    kill_switch_reason: Option<String>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DiagnosticsView {
    app_version: &'static str,
    protocol_version: &'static str,
    worker_status: WorkerRuntimeStatus,
    worker_version: Option<String>,
    worker_target: Option<String>,
    sqlite_version: String,
    sqlite_fts5: bool,
    warning_budget_micro_usd: i64,
    hard_budget_micro_usd: i64,
    project_hard_budget_micro_usd: i64,
    providers: Vec<ProviderDiagnosticView>,
}

const MIN_PROJECT_BUDGET_MICRO_USD: i64 = 500_000;
const MAX_PROJECT_BUDGET_MICRO_USD: i64 = 100_000_000;

#[tauri::command]
pub fn get_diagnostics(state: State<'_, AppState>) -> AppResult<DiagnosticsView> {
    let now_ms = crate::unix_time_ms()?;
    let database = state.database.lock().map_err(|_| AppError::Internal)?;
    let diagnostics = database.diagnostics().clone();
    let (warning_budget_micro_usd, hard_budget_micro_usd) = database.connection().query_row(
        "SELECT MIN(warning_micro_usd),MIN(hard_micro_usd) FROM budget WHERE enabled=1 AND (scope_type='DEFAULT' OR (scope_type='PROJECT' AND scope_id=?1))",
        [crate::database::repositories::DEFAULT_PROJECT_ID.to_string()],
        |row| Ok((row.get(0)?, row.get(1)?)),
    )?;
    let project_hard_budget_micro_usd = database.connection().query_row(
        "SELECT hard_micro_usd FROM budget WHERE enabled=1 AND scope_type='PROJECT' AND scope_id=?1",
        [crate::database::repositories::DEFAULT_PROJECT_ID.to_string()],
        |row| row.get(0),
    )?;
    let mut providers = Vec::new();
    let mut statement = database.connection().prepare(
        "SELECT provider,enabled,kill_switch_reason,policy_class,retention_summary,data_use_summary,no_storage_mode,privacy_mode,purge_after_seconds,checked_at_ms,expires_at_ms
         FROM provider_policy ORDER BY CASE provider WHEN 'openai' THEN 0 WHEN 'tvmaze' THEN 1 WHEN 'youtube' THEN 2 ELSE 3 END",
    )?;
    let policies = statement.query_map([], |row| Ok((
        row.get::<_, String>(0)?, row.get::<_, bool>(1)?, row.get::<_, Option<String>>(2)?,
        row.get::<_, String>(3)?, row.get::<_, String>(4)?, row.get::<_, String>(5)?,
        row.get::<_, String>(6)?, row.get::<_, String>(7)?, row.get::<_, i64>(8)?,
        row.get::<_, i64>(9)?, row.get::<_, i64>(10)?,
    )))?.collect::<Result<Vec<_>, _>>()?;
    drop(statement);
    for policy in policies {
        let configured_model = match policy.0.as_str() {
            "openai" => Some("gpt-5.6-luna".to_owned()),
            "xai" => Some("grok-4.6".to_owned()),
            _ => None,
        };
        let credential_provider = match policy.0.as_str() {
            "openai" => Some(CredentialProvider::Openai),
            "youtube" => Some(CredentialProvider::Youtube),
            "xai" => Some(CredentialProvider::Xai),
            _ => None,
        };
        let preflight = if let Some(provider) = credential_provider {
            database.connection().query_row(
                "SELECT resolved_model,checked_at_ms,expires_at_ms FROM provider_model_preflight WHERE provider=?1 AND configured_model=?2 AND available=1",
                params![policy.0, provider.preflight_record_key()],
                |row| Ok((row.get::<_, Option<String>>(0)?, row.get::<_, i64>(1)?, row.get::<_, i64>(2)?)),
            ).optional()?
        } else { None };
        let configured = credential_provider
            .map(|provider| state.credentials.load(provider))
            .transpose()?
            .flatten()
            .is_some_and(|value| limits::validate_secret(&value).is_ok());
        let policy_current = policy.9 <= now_ms && policy.10 >= now_ms;
        let enabled = policy.1 && policy.2.is_none() && policy_current;
        let availability = if !enabled {
            ProviderAvailability::Disabled
        } else if credential_provider.is_none() {
            ProviderAvailability::Ready
        } else if !configured {
            ProviderAvailability::Unconfigured
        } else if preflight.as_ref().is_some_and(|value| value.0.is_some() && value.1 <= now_ms && value.2 >= now_ms) {
            ProviderAvailability::Ready
        } else {
            ProviderAvailability::Unverified
        };
        let resolved_model = configured_model
            .as_ref()
            .and_then(|_| preflight.as_ref().and_then(|value| value.0.clone()));
        let price_card_checked_at = database.connection().query_row(
            "SELECT strftime('%Y-%m-%dT%H:%M:%fZ',MAX(checked_at_ms)/1000.0,'unixepoch') FROM price_card WHERE provider=?1",
            [&policy.0],
            |row| row.get::<_, Option<String>>(0),
        )?;
        providers.push(ProviderDiagnosticView {
            provider: policy.0,
            enabled,
            configured_model,
            resolved_model,
            availability,
            price_card_checked_at,
            policy_checked_at: format_timestamp(&database, policy.9)?,
            policy_expires_at: format_timestamp(&database, policy.10)?,
            retention_mode: policy.4,
            data_use_mode: policy.5,
            no_storage_mode: policy.6,
            privacy_mode: policy.7,
            cache_policy: policy.3,
            purge_after_seconds: policy.8,
            kill_switch_reason: policy.2.or_else(|| (!policy_current).then(|| "Reviewed provider policy is stale; refresh the embedded catalog before use.".to_owned())),
        });
    }
    drop(database);
    let worker = state.worker.lock().map_err(|_| AppError::Internal)?;
    Ok(DiagnosticsView {
        app_version: env!("CARGO_PKG_VERSION"),
        protocol_version: crate::worker::protocol::PROTOCOL_VERSION,
        worker_status: worker.status(),
        worker_version: worker.worker_version().map(str::to_owned),
        worker_target: worker.target().map(str::to_owned),
        sqlite_version: diagnostics.sqlite_version,
        sqlite_fts5: diagnostics.fts5_enabled,
        warning_budget_micro_usd,
        hard_budget_micro_usd,
        project_hard_budget_micro_usd,
        providers,
    })
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct ProjectBudgetInput {
    hard_budget_micro_usd: i64,
}

#[tauri::command]
pub fn set_project_budget(
    input: ProjectBudgetInput,
    state: State<'_, AppState>,
) -> AppResult<()> {
    let mut database = state.database.lock().map_err(|_| AppError::Internal)?;
    set_project_budget_value(&mut database, input.hard_budget_micro_usd)
}

fn set_project_budget_value(
    database: &mut crate::database::Database,
    hard_budget_micro_usd: i64,
) -> AppResult<()> {
    if !(MIN_PROJECT_BUDGET_MICRO_USD..=MAX_PROJECT_BUDGET_MICRO_USD)
        .contains(&hard_budget_micro_usd)
    {
        return Err(AppError::Budget(
            "project budget must be between $0.50 and $100.00".to_owned(),
        ));
    }
    let transaction = database
        .connection_mut()
        .transaction_with_behavior(TransactionBehavior::Immediate)?;
    let active_jobs: i64 = transaction.query_row(
        "SELECT COUNT(*) FROM job WHERE state IN ('QUEUED','RUNNING','CANCELLING')",
        [],
        |row| row.get(0),
    )?;
    if active_jobs != 0 {
        return Err(AppError::Budget(
            "project budget cannot change while research is active".to_owned(),
        ));
    }
    let updated = transaction.execute(
        "UPDATE budget SET hard_micro_usd=?1, warning_micro_usd=MIN(warning_micro_usd,?1) WHERE enabled=1 AND scope_type='PROJECT' AND scope_id=?2",
        params![
            hard_budget_micro_usd,
            crate::database::repositories::DEFAULT_PROJECT_ID.to_string()
        ],
    )?;
    if updated != 1 {
        return Err(AppError::DatabaseInvariant(
            "default project budget is missing".to_owned(),
        ));
    }
    transaction.commit()?;
    Ok(())
}

fn format_timestamp(database: &crate::database::Database, unix_ms: i64) -> AppResult<String> {
    Ok(database.connection().query_row(
        "SELECT strftime('%Y-%m-%dT%H:%M:%fZ',?1/1000.0,'unixepoch')",
        [unix_ms],
        |row| row.get(0),
    )?)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn project_budget_change_is_bounded_and_transactional() {
        let mut database = crate::database::Database::open_in_memory().unwrap();
        set_project_budget_value(&mut database, 5_000_000).unwrap();
        let hard: i64 = database
            .connection()
            .query_row(
                "SELECT hard_micro_usd FROM budget WHERE scope_type='PROJECT' AND scope_id=?1",
                [crate::database::repositories::DEFAULT_PROJECT_ID.to_string()],
                |row| row.get(0),
            )
            .unwrap();
        assert_eq!(hard, 5_000_000);
        assert!(set_project_budget_value(&mut database, 100_000_001).is_err());
        let unchanged: i64 = database
            .connection()
            .query_row(
                "SELECT hard_micro_usd FROM budget WHERE scope_type='PROJECT' AND scope_id=?1",
                [crate::database::repositories::DEFAULT_PROJECT_ID.to_string()],
                |row| row.get(0),
            )
            .unwrap();
        assert_eq!(unchanged, 5_000_000);
    }
}
