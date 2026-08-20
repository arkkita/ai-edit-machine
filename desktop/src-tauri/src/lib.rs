mod commands;
#[cfg(debug_assertions)]
pub use commands::research::run_m1_provider_debug_live;
#[cfg(debug_assertions)]
pub use commands::research::run_m11_calibration_live;
pub use commands::research::run_openai_verifier_diagnostic;
pub mod cost;
pub mod credentials;
pub mod database;
pub mod domain;
pub mod provider_catalog;
pub mod security;
pub mod worker;

pub mod build_provenance {
    include!(concat!(env!("OUT_DIR"), "/build_provenance.rs"));

    pub const PIPELINE_VERSION: &str = "m1.1b-evidence-to-concept-v1";
}

use std::sync::{Arc, Mutex};
use std::time::{SystemTime, UNIX_EPOCH};

use serde::{Serialize, Serializer};
use tauri::{Manager, WebviewWindowBuilder};
use thiserror::Error;

use credentials::{CredentialStore, WindowsCredentialStore};
use database::Database;
use worker::WorkerSupervisor;

pub type AppResult<T> = Result<T, AppError>;

#[derive(Debug, Error)]
pub enum AppError {
    #[error("validation failed: {0}")]
    Validation(String),
    #[error("security policy rejected the operation: {0}")]
    Security(String),
    #[error("cost policy rejected the operation: {0}")]
    Budget(String),
    #[error("provider is unavailable: {0}")]
    Provider(String),
    #[error("worker boundary failed: {0}")]
    Worker(String),
    #[error("credential operation failed: {0}")]
    Credential(String),
    #[error("database invariant failed: {0}")]
    DatabaseInvariant(String),
    #[error("record not found: {0}")]
    NotFound(String),
    #[error("external operation failed: {0}")]
    External(String),
    #[error("database operation failed")]
    Sql(#[from] rusqlite::Error),
    #[error("local file operation failed")]
    Io(#[from] std::io::Error),
    #[error("structured data operation failed")]
    Json(#[from] serde_json::Error),
    #[error("internal trusted-core failure")]
    Internal,
}

impl AppError {
    fn public_message(&self) -> String {
        match self {
            Self::Validation(message)
            | Self::Security(message)
            | Self::Budget(message)
            | Self::Provider(message)
            | Self::Worker(message)
            | Self::Credential(message)
            | Self::DatabaseInvariant(message)
            | Self::NotFound(message)
            | Self::External(message) => security::sanitized_error(message),
            Self::Sql(_) => "The local database operation failed safely.".to_owned(),
            Self::Io(_) => "A local file operation failed safely.".to_owned(),
            Self::Json(_) => "Structured data failed strict validation.".to_owned(),
            Self::Internal => "The trusted core encountered an internal error.".to_owned(),
        }
    }
}

impl Serialize for AppError {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(&self.public_message())
    }
}

pub struct AppState {
    pub database: Arc<Mutex<Database>>,
    pub credentials: Arc<dyn CredentialStore>,
    pub worker: Arc<Mutex<WorkerSupervisor>>,
}

pub fn unix_time_ms() -> AppResult<i64> {
    let value = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| AppError::Internal)?
        .as_millis();
    i64::try_from(value).map_err(|_| AppError::Internal)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            let app_data = app.path().app_local_data_dir()?;
            std::fs::create_dir_all(&app_data)?;
            let mut database = Database::open(&app_data.join("m1.sqlite3"))?;
            provider_catalog::install(&mut database, unix_time_ms()?)?;
            database.run_policy_maintenance(unix_time_ms()?)?;
            let resource_dir = app.path().resource_dir()?;
            let worker_temp = app_data.join("jobs/worker-runtime");
            let worker = WorkerSupervisor::from_paths(&resource_dir, &worker_temp);
            app.manage(AppState {
                database: Arc::new(Mutex::new(database)),
                credentials: Arc::new(WindowsCredentialStore),
                worker: Arc::new(Mutex::new(worker)),
            });

            let window_config = app
                .config()
                .app
                .windows
                .first()
                .ok_or("main window configuration is missing")?
                .clone();
            WebviewWindowBuilder::from_config(app, &window_config)?
                .on_navigation(|url| {
                    security::navigation::is_app_navigation_allowed(url, cfg!(debug_assertions))
                })
                .on_new_window(|_, _| tauri::webview::NewWindowResponse::Deny)
                .devtools(cfg!(debug_assertions))
                .build()?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::diagnostics::get_diagnostics,
            commands::diagnostics::set_project_budget,
            commands::research::preview_research,
            commands::research::start_research,
            commands::research::get_research_run,
            commands::research::cancel_research,
            commands::research::record_recommendation_feedback,
            commands::links::open_evidence_link,
            commands::credentials::get_credential_status,
            commands::credentials::store_credential,
            commands::credentials::validate_credential,
            commands::credentials::delete_credential,
        ])
        .run(tauri::generate_context!())
        .expect("AI Edit Machine trusted desktop host failed");
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn serialized_errors_never_include_sql_or_file_details() {
        let error = AppError::Io(std::io::Error::other("C:\\private\\secret.txt"));
        let value = serde_json::to_string(&error).unwrap();
        assert!(!value.contains("private"));
    }
}
