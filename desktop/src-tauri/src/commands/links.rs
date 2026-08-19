use tauri::State;
use uuid::Uuid;

use crate::{AppError, AppResult, AppState};

#[tauri::command]
pub fn open_evidence_link(state: State<'_, AppState>, link_handle: Uuid) -> AppResult<()> {
    let mut database = state.database.lock().map_err(|_| AppError::Internal)?;
    let url = database.resolve_external_link(link_handle, crate::unix_time_ms()?)?;
    drop(database);
    crate::security::navigation::open_external_https(&url)
}
