use zeroize::Zeroizing;

use super::{CredentialProvider, CredentialStore};
use crate::security::limits;
use crate::{AppError, AppResult};

#[derive(Default)]
pub struct WindowsCredentialStore;

#[cfg(windows)]
mod platform {
    use std::ptr;

    use windows_sys::Win32::Foundation::{ERROR_NOT_FOUND, GetLastError};
    use windows_sys::Win32::Security::Credentials::{
        CREDENTIALW, CRED_PERSIST_LOCAL_MACHINE, CRED_TYPE_GENERIC, CredDeleteW, CredFree,
        CredReadW, CredWriteW,
    };

    use super::*;

    struct CredentialAllocation(*mut CREDENTIALW);

    impl Drop for CredentialAllocation {
        fn drop(&mut self) {
            if !self.0.is_null() {
                unsafe { CredFree(self.0.cast()) };
            }
        }
    }

    fn wide(value: &str) -> Vec<u16> {
        value.encode_utf16().chain(Some(0)).collect()
    }

    impl CredentialStore for WindowsCredentialStore {
        fn store(&self, provider: CredentialProvider, secret: &[u8]) -> AppResult<()> {
            limits::validate_secret(secret)?;
            let mut secret = Zeroizing::new(secret.to_vec());
            let mut target = wide(&provider.credential_target());
            let mut username = wide(provider.as_str());
            let credential = CREDENTIALW {
                Flags: 0,
                Type: CRED_TYPE_GENERIC,
                TargetName: target.as_mut_ptr(),
                Comment: ptr::null_mut(),
                LastWritten: Default::default(),
                CredentialBlobSize: secret.len() as u32,
                CredentialBlob: secret.as_mut_ptr(),
                Persist: CRED_PERSIST_LOCAL_MACHINE,
                AttributeCount: 0,
                Attributes: ptr::null_mut(),
                TargetAlias: ptr::null_mut(),
                UserName: username.as_mut_ptr(),
            };
            let succeeded = unsafe { CredWriteW(&credential, 0) };
            if succeeded == 0 {
                let code = unsafe { GetLastError() };
                return Err(AppError::Credential(format!(
                    "Windows Credential Manager rejected the credential (error {code})"
                )));
            }
            Ok(())
        }

        fn load(&self, provider: CredentialProvider) -> AppResult<Option<Zeroizing<Vec<u8>>>> {
            let target = wide(&provider.credential_target());
            let mut raw: *mut CREDENTIALW = ptr::null_mut();
            let succeeded = unsafe { CredReadW(target.as_ptr(), CRED_TYPE_GENERIC, 0, &mut raw) };
            if succeeded == 0 {
                let code = unsafe { GetLastError() };
                if code == ERROR_NOT_FOUND {
                    return Ok(None);
                }
                return Err(AppError::Credential(format!(
                    "Windows Credential Manager could not read the credential (error {code})"
                )));
            }
            if raw.is_null() {
                return Err(AppError::Credential(
                    "Windows Credential Manager returned an invalid credential".to_owned(),
                ));
            }
            let allocation = CredentialAllocation(raw);
            let credential = unsafe { &*allocation.0 };
            if credential.CredentialBlobSize == 0 || credential.CredentialBlob.is_null() {
                return Err(AppError::Credential(
                    "Windows Credential Manager returned an empty credential".to_owned(),
                ));
            }
            let bytes = unsafe {
                std::slice::from_raw_parts(
                    credential.CredentialBlob,
                    credential.CredentialBlobSize as usize,
                )
            };
            limits::validate_secret(bytes).map_err(|_| {
                AppError::Credential(
                    "Windows Credential Manager returned an invalid credential".to_owned(),
                )
            })?;
            Ok(Some(Zeroizing::new(bytes.to_vec())))
        }

        fn delete(&self, provider: CredentialProvider) -> AppResult<()> {
            let target = wide(&provider.credential_target());
            let succeeded = unsafe { CredDeleteW(target.as_ptr(), CRED_TYPE_GENERIC, 0) };
            if succeeded == 0 {
                let code = unsafe { GetLastError() };
                if code != ERROR_NOT_FOUND {
                    return Err(AppError::Credential(format!(
                        "Windows Credential Manager could not delete the credential (error {code})"
                    )));
                }
            }
            Ok(())
        }
    }
}

#[cfg(not(windows))]
impl CredentialStore for WindowsCredentialStore {
    fn store(&self, _provider: CredentialProvider, _secret: &[u8]) -> AppResult<()> {
        Err(AppError::Credential(
            "Windows Credential Manager is unavailable on this platform".to_owned(),
        ))
    }

    fn load(&self, _provider: CredentialProvider) -> AppResult<Option<Zeroizing<Vec<u8>>>> {
        Err(AppError::Credential(
            "Windows Credential Manager is unavailable on this platform".to_owned(),
        ))
    }

    fn delete(&self, _provider: CredentialProvider) -> AppResult<()> {
        Err(AppError::Credential(
            "Windows Credential Manager is unavailable on this platform".to_owned(),
        ))
    }
}

#[cfg(test)]
mod tests {
    use super::super::testing::MemoryCredentialStore;
    use super::*;

    #[test]
    fn injected_store_never_requires_a_real_windows_credential() {
        let store = MemoryCredentialStore::default();
        store.store(CredentialProvider::Openai, b"test-only").unwrap();
        assert_eq!(store.load(CredentialProvider::Openai).unwrap().unwrap().as_slice(), b"test-only");
        store.delete(CredentialProvider::Openai).unwrap();
        assert!(!store.is_configured(CredentialProvider::Openai).unwrap());
    }
}
