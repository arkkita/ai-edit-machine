use std::time::Duration;

use serde::Serialize;
use tauri::State;
use uuid::Uuid;
use zeroize::Zeroizing;

use crate::credentials::CredentialProvider;
use crate::database::repositories::ModelPreflightInput;
use crate::security::limits;
use crate::worker::protocol::{self, WorkerMessage};
use crate::{AppError, AppResult, AppState};

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CredentialStatusView {
    provider: CredentialProvider,
    configured: bool,
    locally_valid: bool,
    last_validated_at: Option<String>,
}

fn configured_model(provider: CredentialProvider) -> Option<&'static str> {
    match provider {
        CredentialProvider::Openai => Some("gpt-5.6-luna"),
        CredentialProvider::Xai => Some("grok-4.6"),
        CredentialProvider::Youtube => None,
    }
}

fn status(state: &AppState, provider: CredentialProvider) -> AppResult<CredentialStatusView> {
    let value = state.credentials.load(provider)?;
    let locally_valid = value.as_deref().is_some_and(|bytes| limits::validate_secret(bytes).is_ok());
    let now_ms = crate::unix_time_ms()?;
    let last_validated_at = state.database.lock().map_err(|_| AppError::Internal)?
        .current_model_preflight_checked_at(
            provider.as_str(),
            provider.preflight_record_key(),
            now_ms,
        )?;
    Ok(CredentialStatusView { provider, configured: value.is_some(), locally_valid, last_validated_at })
}

#[tauri::command]
pub fn get_credential_status(state: State<'_, AppState>, provider: CredentialProvider) -> AppResult<CredentialStatusView> {
    status(&state, provider)
}

#[tauri::command]
pub fn store_credential(
    state: State<'_, AppState>,
    provider: CredentialProvider,
    secret: String,
) -> AppResult<CredentialStatusView> {
    let secret = Zeroizing::new(secret.into_bytes());
    limits::validate_secret(&secret)?;
    state.credentials.store(provider, &secret)?;
    state.database.lock().map_err(|_| AppError::Internal)?.clear_model_preflight(provider.as_str())?;
    status(&state, provider)
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct PreflightPayload<'a> {
    schema_version: &'static str,
    provider: &'a str,
    configured_model: Option<&'a str>,
    credential: Option<&'a str>,
}

#[tauri::command]
pub fn validate_credential(state: State<'_, AppState>, provider: CredentialProvider) -> AppResult<CredentialStatusView> {
    let bytes = state.credentials.load(provider)?
        .ok_or_else(|| AppError::Credential(format!("{} credential is not configured", provider.as_str())))?;
    limits::validate_secret(&bytes)?;
    let secret = Zeroizing::new(String::from_utf8(bytes.to_vec())
        .map_err(|_| AppError::Credential("stored credential is not valid UTF-8".to_owned()))?);
    let now_ms = crate::unix_time_ms()?;
    let policy = state.database.lock().map_err(|_| AppError::Internal)?
        .provider_disclosures(provider.as_str(), now_ms)?;
    let request_id = Uuid::new_v4();
    let result = {
        let mut worker = state.worker.lock().map_err(|_| AppError::Internal)?;
        worker.start()?;
        worker.send("provider.preflight", request_id, PreflightPayload {
            schema_version: protocol::PAYLOAD_SCHEMA_VERSION,
            provider: provider.as_str(),
            configured_model: configured_model(provider),
            credential: Some(secret.as_str()),
        })?;
        match worker.receive(Duration::from_secs(45))? {
            WorkerMessage::ProviderPreflightResult(value) => value,
            WorkerMessage::ProviderPreflightError(value) => {
                let message = value.message.replace(secret.as_str(), "<redacted>");
                return Err(AppError::Provider(message));
            }
            _ => {
                worker.abort_request(request_id);
                return Err(AppError::Worker("worker returned the wrong preflight response".to_owned()));
            }
        }
    };
    if result.provider != provider.as_str() || !result.available
        || result.retention_mode != policy.retention_summary
        || result.data_use_mode != policy.data_use_summary
        || result.no_storage_mode != policy.no_storage_mode
        || result.privacy_mode != policy.privacy_mode
    {
        state.worker.lock().map_err(|_| AppError::Internal)?.abort_request(request_id);
        return Err(AppError::Security("provider preflight did not match the reviewed privacy policy".to_owned()));
    }
    let preflight_identity = provider.preflight_record_key();
    let persisted_resolved = if configured_model(provider).is_some() {
        let Some(resolved) = result.resolved_model.as_deref() else {
            state.worker.lock().map_err(|_| AppError::Internal)?.abort_request(request_id);
            return Err(AppError::Provider("provider preflight did not resolve the configured model".to_owned()));
        };
        resolved
    } else {
        if result.resolved_model.is_some() {
            state.worker.lock().map_err(|_| AppError::Internal)?.abort_request(request_id);
            return Err(AppError::Security(
                "model-less provider preflight returned an unexpected model identity".to_owned(),
            ));
        }
        preflight_identity
    };
    let expires = now_ms.saturating_add(6 * 60 * 60 * 1000).min(policy.expires_at_ms);
    state.database.lock().map_err(|_| AppError::Internal)?.upsert_model_preflight(&ModelPreflightInput {
        provider: provider.as_str(), configured_model: preflight_identity,
        resolved_model: Some(persisted_resolved), available: true,
        retention_mode: &result.retention_mode, data_use_mode: &result.data_use_mode,
        no_storage_mode: &result.no_storage_mode, privacy_mode: &result.privacy_mode,
        checked_at_ms: now_ms, expires_at_ms: expires,
    })?;
    status(&state, provider)
}

#[tauri::command]
pub fn delete_credential(state: State<'_, AppState>, provider: CredentialProvider) -> AppResult<CredentialStatusView> {
    state.credentials.delete(provider)?;
    state.database.lock().map_err(|_| AppError::Internal)?.clear_model_preflight(provider.as_str())?;
    status(&state, provider)
}
