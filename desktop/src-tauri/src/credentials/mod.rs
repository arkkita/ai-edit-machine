mod wincred;

use std::fmt;

use serde::{Deserialize, Serialize};
use zeroize::Zeroizing;

use crate::AppResult;

pub use wincred::WindowsCredentialStore;

#[derive(Clone, Copy, Debug, Deserialize, Serialize, Eq, PartialEq, Hash)]
#[serde(rename_all = "lowercase")]
pub enum CredentialProvider {
    Xai,
    Openai,
    Youtube,
}

impl CredentialProvider {
    pub const ALL: [Self; 3] = [Self::Xai, Self::Openai, Self::Youtube];

    pub fn as_str(self) -> &'static str {
        match self {
            Self::Xai => "xai",
            Self::Openai => "openai",
            Self::Youtube => "youtube",
        }
    }

    pub(crate) fn preflight_record_key(self) -> &'static str {
        match self {
            Self::Xai => "grok-4.6",
            Self::Openai => "gpt-5.6-luna",
            // The existing immutable preflight table requires a non-null
            // resolved identity for an available row. YouTube has no model,
            // so this internal endpoint identity records only that the
            // reviewed Data API preflight completed. It is never exposed as a
            // configured/resolved model or sent to the worker/provider.
            Self::Youtube => "youtube-data-api-v3",
        }
    }

    fn credential_target(self) -> String {
        format!("AI Edit Machine/M1/{}", self.as_str())
    }
}

impl fmt::Display for CredentialProvider {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.as_str())
    }
}

pub trait CredentialStore: Send + Sync {
    fn store(&self, provider: CredentialProvider, secret: &[u8]) -> AppResult<()>;
    fn load(&self, provider: CredentialProvider) -> AppResult<Option<Zeroizing<Vec<u8>>>>;
    fn delete(&self, provider: CredentialProvider) -> AppResult<()>;

    fn is_configured(&self, provider: CredentialProvider) -> AppResult<bool> {
        Ok(self.load(provider)?.is_some())
    }
}

#[cfg(test)]
pub mod testing {
    use std::collections::HashMap;
    use std::sync::Mutex;

    use zeroize::Zeroizing;

    use super::*;

    #[derive(Default)]
    pub struct MemoryCredentialStore {
        values: Mutex<HashMap<CredentialProvider, Vec<u8>>>,
    }

    impl CredentialStore for MemoryCredentialStore {
        fn store(&self, provider: CredentialProvider, secret: &[u8]) -> AppResult<()> {
            self.values.lock().expect("credential test lock").insert(provider, secret.to_vec());
            Ok(())
        }

        fn load(&self, provider: CredentialProvider) -> AppResult<Option<Zeroizing<Vec<u8>>>> {
            Ok(self
                .values
                .lock()
                .expect("credential test lock")
                .get(&provider)
                .cloned()
                .map(Zeroizing::new))
        }

        fn delete(&self, provider: CredentialProvider) -> AppResult<()> {
            self.values.lock().expect("credential test lock").remove(&provider);
            Ok(())
        }
    }
}
