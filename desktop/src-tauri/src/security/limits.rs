use std::collections::HashSet;

use crate::{AppError, AppResult};

pub const MAX_INVOKE_JSON_BYTES: usize = 64 * 1024;
pub const MAX_PROMPT_CHARACTERS: usize = 4_000;
pub const MAX_SECRET_BYTES: usize = 2_560;
pub const MAX_EXCLUSIONS: usize = 30;
pub const MAX_EXCLUSION_CHARACTERS: usize = 500;

pub fn validate_prompt(value: &str) -> AppResult<()> {
    let count = value.chars().count();
    if value.trim().is_empty() || value.trim() != value || count > MAX_PROMPT_CHARACTERS {
        return Err(AppError::Validation(format!(
            "research prompt must contain 1-{MAX_PROMPT_CHARACTERS} characters"
        )));
    }
    if value.contains('\0') || value.contains('\r') {
        return Err(AppError::Validation(
            "research prompt contains an unsupported control character".to_owned(),
        ));
    }
    Ok(())
}

pub fn validate_exclusions(values: &[String]) -> AppResult<()> {
    if values.len() > MAX_EXCLUSIONS {
        return Err(AppError::Validation(format!(
            "at most {MAX_EXCLUSIONS} exclusions are allowed"
        )));
    }
    let mut normalized = HashSet::new();
    for value in values {
        let trimmed = value.trim();
        if trimmed.is_empty() || trimmed != value || trimmed.chars().count() > MAX_EXCLUSION_CHARACTERS {
            return Err(AppError::Validation("an exclusion is empty or too long".to_owned()));
        }
        if !normalized.insert(trimmed.to_lowercase()) {
            return Err(AppError::Validation("exclusions must be unique".to_owned()));
        }
    }
    Ok(())
}

pub fn validate_secret(value: &[u8]) -> AppResult<()> {
    if value.is_empty() || value.len() > MAX_SECRET_BYTES {
        return Err(AppError::Validation(format!(
            "credential must contain 1-{MAX_SECRET_BYTES} UTF-8 bytes"
        )));
    }
    if value.iter().any(|byte| *byte == 0 || *byte == b'\r' || *byte == b'\n') {
        return Err(AppError::Validation(
            "credential contains an unsupported control character".to_owned(),
        ));
    }
    std::str::from_utf8(value)
        .map_err(|_| AppError::Validation("credential must be valid UTF-8".to_owned()))?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn validates_bounded_user_input() {
        assert!(validate_prompt("romance TV").is_ok());
        assert!(validate_prompt("").is_err());
        assert!(validate_prompt(" romance TV ").is_err());
        assert!(validate_prompt(&"x".repeat(MAX_PROMPT_CHARACTERS + 1)).is_err());
        assert!(validate_exclusions(&[" reality TV ".to_owned()]).is_err());
        assert!(validate_secret(b"secret").is_ok());
        assert!(validate_secret(b"line\nsecret").is_err());
    }
}
