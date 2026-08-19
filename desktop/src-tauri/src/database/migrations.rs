use rusqlite::{Connection, TransactionBehavior};

use crate::{AppError, AppResult};

struct Migration {
    version: i64,
    sql: &'static str,
}

const MIGRATIONS: &[Migration] = &[
    Migration {
        version: 1,
        sql: include_str!("../../migrations/0001_m1.sql"),
    },
    Migration {
        version: 2,
        sql: include_str!("../../migrations/0002_year_season_numbers.sql"),
    },
];

pub(super) fn apply(connection: &mut Connection) -> AppResult<()> {
    let current: i64 = connection.query_row("PRAGMA user_version", [], |row| row.get(0))?;
    let latest = MIGRATIONS.last().map_or(0, |migration| migration.version);
    if current > latest {
        return Err(AppError::DatabaseInvariant(format!(
            "database schema version {current} is newer than supported version {latest}"
        )));
    }
    connection.execute_batch(
        "CREATE TABLE IF NOT EXISTS schema_migration (
            version INTEGER PRIMARY KEY,
            applied_at_ms INTEGER NOT NULL,
            content_sha256 TEXT NOT NULL CHECK (length(content_sha256) = 64)
        ) STRICT;",
    )?;

    let mut statement = connection.prepare(
        "SELECT version, content_sha256 FROM schema_migration ORDER BY version",
    )?;
    let recorded = statement
        .query_map([], |row| Ok((row.get::<_, i64>(0)?, row.get::<_, String>(1)?)))?
        .collect::<Result<Vec<_>, _>>()?;
    drop(statement);
    for (version, recorded_hash) in &recorded {
        let migration = MIGRATIONS
            .iter()
            .find(|migration| migration.version == *version)
            .ok_or_else(|| AppError::DatabaseInvariant(format!(
                "database records unknown migration version {version}"
            )))?;
        if *version > current {
            return Err(AppError::DatabaseInvariant(
                "migration history is ahead of PRAGMA user_version".to_owned(),
            ));
        }
        let expected_hash = crate::security::sha256_hex(migration.sql.as_bytes());
        if *recorded_hash != expected_hash {
            return Err(AppError::DatabaseInvariant(format!(
                "migration {version} content hash does not match this build"
            )));
        }
    }
    for migration in MIGRATIONS.iter().filter(|migration| migration.version <= current) {
        if !recorded.iter().any(|(version, _)| *version == migration.version) {
            return Err(AppError::DatabaseInvariant(format!(
                "migration {} is missing from durable history",
                migration.version
            )));
        }
    }
    for migration in MIGRATIONS.iter().filter(|migration| migration.version > current) {
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        transaction.execute_batch(migration.sql)?;
        let content_hash = crate::security::sha256_hex(migration.sql.as_bytes());
        transaction.execute(
            "INSERT INTO schema_migration(version, applied_at_ms, content_sha256) VALUES (?1, CAST(unixepoch('subsec') * 1000 AS INTEGER), ?2)",
            rusqlite::params![migration.version, content_hash],
        )?;
        transaction.pragma_update(None, "user_version", migration.version)?;
        transaction.commit()?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn migration_is_versioned_idempotent_and_hash_checked() {
        let mut connection = Connection::open_in_memory().unwrap();
        connection.pragma_update(None, "foreign_keys", true).unwrap();
        apply(&mut connection).unwrap();
        assert_eq!(connection.query_row("PRAGMA user_version", [], |row| row.get::<_, i64>(0)).unwrap(), 2);
        assert_eq!(connection.query_row("SELECT COUNT(*) FROM schema_migration", [], |row| row.get::<_, i64>(0)).unwrap(), 2);
        apply(&mut connection).unwrap();
        connection.execute("UPDATE schema_migration SET content_sha256=?1 WHERE version=1", ["0".repeat(64)]).unwrap();
        assert!(apply(&mut connection).is_err());
    }

    #[test]
    fn calendar_year_season_migration_preserves_v1_rows_and_widens_the_bound() {
        let mut connection = Connection::open_in_memory().unwrap();
        connection.execute_batch(
            "CREATE TABLE schema_migration (
                version INTEGER PRIMARY KEY,
                applied_at_ms INTEGER NOT NULL,
                content_sha256 TEXT NOT NULL CHECK (length(content_sha256) = 64)
             ) STRICT;",
        ).unwrap();
        connection.execute_batch(MIGRATIONS[0].sql).unwrap();
        connection.execute(
            "INSERT INTO schema_migration(version,applied_at_ms,content_sha256) VALUES (1,0,?1)",
            [crate::security::sha256_hex(MIGRATIONS[0].sql.as_bytes())],
        ).unwrap();
        connection.pragma_update(None, "user_version", 1).unwrap();
        // This focused migration fixture does not need to recreate the entire
        // opportunity/run graph. Re-enable FK enforcement before exercising
        // the real v1 -> v2 subtree rebuild below.
        connection.pragma_update(None, "foreign_keys", false).unwrap();
        connection.execute(
            "INSERT INTO footage_request(id,opportunity_id,schema_version,summary,natural_best,natural_alternative,natural_minimum,natural_optional_improvement,smallest_useful_set_reason,search_queries_json,warnings_json,canonical_contract_json,created_at_ms)
             VALUES ('request-1','opportunity-1','2.0.0','summary','best',NULL,'minimum',NULL,'reason','[]','[]','{}',0)",
            [],
        ).unwrap();
        connection.execute(
            "INSERT INTO footage_requirement(id,footage_request_id,source_key,source_group,priority,asset_kind,show_or_title,season_number,episode_number,episode_title,characters_json,relationship_or_topic,scene_or_moment,purposes_json,verification_level,source_quality_summary,supporting_claim_ids_json,quote_status,quote_text,quote_speaker,quote_likely_context,quote_claim_id,why_it_matters_emotionally,acquisition_effort,search_queries_json,replaces_required_source_keys_json,in_minimum_useful_set)
             VALUES ('requirement-1','request-1','required_episode','REQUIRED',1,'EPISODE','Example Show',12,1,'Pilot','[]',NULL,'Opening scene','[\"MONTAGE\"]','STRONGLY_SUPPORTED','attributed metadata','[]',NULL,NULL,NULL,NULL,NULL,'Supports the montage.',1,'[\"Example Show season 12 episode 1 scenes\"]','[]',1)",
            [],
        ).unwrap();
        connection.execute(
            "INSERT INTO footage_requirement_purpose(footage_requirement_id,purpose) VALUES ('requirement-1','MONTAGE')",
            [],
        ).unwrap();
        connection.pragma_update(None, "foreign_keys", true).unwrap();

        apply(&mut connection).unwrap();

        assert_eq!(connection.query_row("PRAGMA user_version", [], |row| row.get::<_, i64>(0)).unwrap(), 2);
        assert_eq!(connection.query_row("SELECT season_number FROM footage_requirement WHERE id='requirement-1'", [], |row| row.get::<_, i64>(0)).unwrap(), 12);
        assert_eq!(connection.query_row("SELECT COUNT(*) FROM footage_requirement_purpose WHERE footage_requirement_id='requirement-1'", [], |row| row.get::<_, i64>(0)).unwrap(), 1);
        connection.execute(
            "INSERT INTO footage_requirement(id,footage_request_id,source_key,source_group,priority,asset_kind,show_or_title,season_number,episode_number,episode_title,characters_json,relationship_or_topic,scene_or_moment,purposes_json,verification_level,source_quality_summary,supporting_claim_ids_json,quote_status,quote_text,quote_speaker,quote_likely_context,quote_claim_id,why_it_matters_emotionally,acquisition_effort,search_queries_json,replaces_required_source_keys_json,in_minimum_useful_set)
             VALUES ('requirement-2','request-1','optional_year_episode','OPTIONAL',1,'EPISODE','Example Daily Drama',2026,158,'Episode 158','[]',NULL,'Current episode','[\"MONTAGE\"]','STRONGLY_SUPPORTED','attributed metadata','[]',NULL,NULL,NULL,NULL,NULL,'Supports the montage.',1,'[\"Example Daily Drama season 2026 episode 158 scenes\"]','[]',0)",
            [],
        ).unwrap();
        assert_eq!(connection.query_row("SELECT season_number FROM footage_requirement WHERE id='requirement-2'", [], |row| row.get::<_, i64>(0)).unwrap(), 2026);
    }

    #[test]
    fn migration_rejects_unknown_future_user_version() {
        let mut connection = Connection::open_in_memory().unwrap();
        connection.pragma_update(None, "user_version", 99).unwrap();
        assert!(apply(&mut connection).is_err());
        let history_table_count: i64 = connection.query_row(
            "SELECT COUNT(*) FROM sqlite_schema WHERE type='table' AND name='schema_migration'",
            [],
            |row| row.get(0),
        ).unwrap();
        assert_eq!(history_table_count, 0);
    }
}
