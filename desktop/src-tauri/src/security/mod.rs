pub mod limits;
pub mod navigation;

use sha2::{Digest, Sha256};

pub fn sha256_hex(value: &[u8]) -> String {
    hex::encode(Sha256::digest(value))
}

pub fn sanitized_error(value: &str) -> String {
    let mut result = value.replace(['\r', '\n', '\0'], " ");
    for marker in [
        "authorization:", "\"authorization\":", "proxy-authorization:",
        "x-api-key:", "\"x-api-key\":", "x-goog-api-key:", "\"x-goog-api-key\":",
        "api_key=", "apikey=", "?key=", "&key=", "\"api_key\":",
    ] {
        while let Some(start) = result.to_ascii_lowercase().find(marker) {
            let tail = &result[start + marker.len()..];
            let end = tail
                .find(|character: char| matches!(character, ',' | '}' | ';'))
                .map_or(result.len(), |offset| start + marker.len() + offset);
            result.replace_range(start..end, "<redacted>");
        }
    }
    for marker in ["sk-", "xai-", "aiza"] {
        while let Some(start) = result.to_ascii_lowercase().find(marker) {
            let end = result[start..]
                .find(|character: char| character.is_whitespace() || matches!(character, '"' | '\'' | ',' | '}' | ';'))
                .map_or(result.len(), |offset| start + offset);
            result.replace_range(start..end, "<redacted>");
        }
    }
    result.chars().take(500).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn secrets_and_control_characters_are_removed() {
        let value = sanitized_error("provider said\nAuthorization: Bearer bearer-secret, key xai-secret");
        assert!(!value.contains('\n'));
        assert!(!value.contains("bearer-secret"));
        assert!(!value.contains("xai-secret"));
        assert!(!sanitized_error("{\"api_key\":\"AIza-secret\"}").contains("AIza-secret"));
        assert!(!sanitized_error("{\"authorization\":\"Bearer secret-json\"}").contains("secret-json"));
        assert!(!sanitized_error("X-Goog-Api-Key: AIza-google-secret").contains("google-secret"));
    }
}
