mod migrations;
pub mod repositories;

use rusqlite::Connection;
use std::path::Path;

use crate::{AppError, AppResult};

pub const MINIMUM_SQLITE_VERSION: (u32, u32, u32) = (3, 51, 3);

#[derive(Debug, Clone, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DatabaseDiagnostics {
    pub sqlite_version: String,
    pub fts5_enabled: bool,
    pub journal_mode: String,
    pub foreign_keys_enabled: bool,
    pub quick_check: String,
    pub migration_version: i64,
}

pub struct Database {
    connection: Connection,
    diagnostics: DatabaseDiagnostics,
}

impl Database {
    pub fn open(path: &Path) -> AppResult<Self> {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let connection = Connection::open(path)?;
        Self::initialize(connection, false)
    }

    #[cfg(test)]
    pub fn open_in_memory() -> AppResult<Self> {
        Self::initialize(Connection::open_in_memory()?, true)
    }

    fn initialize(mut connection: Connection, in_memory: bool) -> AppResult<Self> {
        connection.busy_timeout(std::time::Duration::from_secs(5))?;
        let sqlite_version: String = connection.query_row("SELECT sqlite_version()", [], |row| row.get(0))?;
        ensure_sqlite_floor(&sqlite_version)?;
        let fts5_enabled = connection.query_row(
            "SELECT sqlite_compileoption_used('ENABLE_FTS5') != 0",
            [],
            |row| row.get::<_, bool>(0),
        )?;
        if !fts5_enabled {
            return Err(AppError::DatabaseInvariant("SQLite FTS5 is not enabled".to_owned()));
        }
        connection.pragma_update(None, "foreign_keys", true)?;
        connection.pragma_update(None, "synchronous", "FULL")?;
        let journal_mode: String = connection.query_row(
            if in_memory { "PRAGMA journal_mode" } else { "PRAGMA journal_mode = WAL" },
            [],
            |row| row.get(0),
        )?;
        if !in_memory && !journal_mode.eq_ignore_ascii_case("wal") {
            return Err(AppError::DatabaseInvariant(
                "SQLite refused the required WAL journal mode".to_owned(),
            ));
        }
        migrations::apply(&mut connection)?;
        connection.pragma_update(None, "trusted_schema", false)?;
        let foreign_keys_enabled = connection.query_row("PRAGMA foreign_keys", [], |row| row.get::<_, bool>(0))?;
        if !foreign_keys_enabled {
            return Err(AppError::DatabaseInvariant("SQLite foreign keys are disabled".to_owned()));
        }
        let quick_check: String = connection.query_row("PRAGMA quick_check", [], |row| row.get(0))?;
        if quick_check != "ok" {
            return Err(AppError::DatabaseInvariant("SQLite quick_check failed".to_owned()));
        }
        let migration_version: i64 = connection.query_row("PRAGMA user_version", [], |row| row.get(0))?;
        let diagnostics = DatabaseDiagnostics {
            sqlite_version,
            fts5_enabled,
            journal_mode,
            foreign_keys_enabled,
            quick_check,
            migration_version,
        };
        recover_interrupted_jobs(&mut connection)?;
        Ok(Self { connection, diagnostics })
    }

    pub fn diagnostics(&self) -> &DatabaseDiagnostics {
        &self.diagnostics
    }

    pub(crate) fn connection(&self) -> &Connection {
        &self.connection
    }

    pub(crate) fn connection_mut(&mut self) -> &mut Connection {
        &mut self.connection
    }
}

fn recover_interrupted_jobs(connection: &mut Connection) -> AppResult<()> {
    let transaction = connection.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
    let now_ms: i64 = transaction.query_row(
        "SELECT CAST(unixepoch('subsec') * 1000 AS INTEGER)",
        [],
        |row| row.get(0),
    )?;
    let job_ids = {
        let mut statement = transaction.prepare(
            "SELECT id FROM job WHERE state IN ('QUEUED', 'RUNNING', 'CANCELLING') ORDER BY id",
        )?;
        statement
            .query_map([], |row| row.get::<_, String>(0))?
            .collect::<Result<Vec<_>, _>>()?
    };
    for job_id in job_ids {
        transaction.execute(
            "UPDATE job SET state = 'INTERRUPTED', phase = 'interrupted on restart', finished_at_ms = ?2 WHERE id = ?1 AND state IN ('QUEUED', 'RUNNING', 'CANCELLING')",
            rusqlite::params![job_id, now_ms],
        )?;
        transaction.execute(
            "UPDATE research_run SET status = 'INTERRUPTED', finished_at_ms = ?2 WHERE job_id = ?1 AND status IN ('QUEUED', 'RUNNING', 'CANCELLING')",
            rusqlite::params![job_id, now_ms],
        )?;
        transaction.execute(
            "UPDATE provider_run SET outcome = 'FAILED', finished_at_ms = ?2 WHERE job_id = ?1 AND outcome = 'PENDING'",
            rusqlite::params![job_id, now_ms],
        )?;
        transaction.execute(
            "UPDATE cost_entry SET state = CASE WHEN EXISTS(
                SELECT 1 FROM provider_run run WHERE run.job_id=cost_entry.job_id AND run.planned_call_id=cost_entry.planned_call_id
             ) THEN 'UNVERIFIED' ELSE 'RELEASED' END, reconciled_at_ms = ?2
             WHERE job_id = ?1 AND state = 'RESERVED'",
            rusqlite::params![job_id, now_ms],
        )?;
        transaction.execute(
            "UPDATE provider_quota_entry SET state = CASE WHEN EXISTS(
                SELECT 1 FROM provider_run run WHERE run.job_id=provider_quota_entry.job_id AND run.planned_call_id=provider_quota_entry.planned_call_id
             ) THEN 'UNVERIFIED' ELSE 'RELEASED' END WHERE job_id = ?1 AND state = 'RESERVED'",
            rusqlite::params![job_id],
        )?;
        transaction.execute(
            "INSERT INTO job_event(job_id, sequence, event_type, occurred_at_ms, sanitized_payload_json) VALUES (?1, COALESCE((SELECT MAX(sequence) + 1 FROM job_event WHERE job_id = ?1), 0), 'INTERRUPTED', ?2, '{\"reason\":\"application restart; remote cost may be unverified\"}')",
            rusqlite::params![job_id, now_ms],
        )?;
        transaction.execute("DELETE FROM cache_flight WHERE lease_owner=?1", [&job_id])?;
    }
    transaction.commit()?;
    Ok(())
}

fn ensure_sqlite_floor(version: &str) -> AppResult<()> {
    let values = version
        .split('.')
        .map(str::parse::<u32>)
        .collect::<Result<Vec<_>, _>>()
        .map_err(|_| AppError::DatabaseInvariant("SQLite returned an invalid version".to_owned()))?;
    if values.len() < 3 || (values[0], values[1], values[2]) < MINIMUM_SQLITE_VERSION {
        return Err(AppError::DatabaseInvariant(format!(
            "SQLite {version} is below the required 3.51.3 floor"
        )));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn version_floor_is_numeric() {
        assert!(ensure_sqlite_floor("3.51.3").is_ok());
        assert!(ensure_sqlite_floor("3.53.2").is_ok());
        assert!(ensure_sqlite_floor("3.51.2").is_err());
        assert!(ensure_sqlite_floor("bad").is_err());
    }

    #[test]
    fn empty_database_runs_the_numbered_migration_and_preflights_fts() {
        let database = Database::open_in_memory().unwrap();
        assert_eq!(database.diagnostics().migration_version, 3);
        assert!(database.diagnostics().fts5_enabled);
        let tables: i64 = database.connection().query_row(
            "SELECT COUNT(*) FROM sqlite_schema WHERE type='table' AND name IN ('job','cost_entry','opportunity','footage_requirement')",
            [],
            |row| row.get(0),
        ).unwrap();
        assert_eq!(tables, 4);
    }

    #[test]
    fn file_database_uses_required_wal_mode() {
        let directory = tempfile::tempdir().unwrap();
        let database = Database::open(&directory.path().join("wal.sqlite3")).unwrap();
        assert!(database.diagnostics().journal_mode.eq_ignore_ascii_case("wal"));
    }
}
