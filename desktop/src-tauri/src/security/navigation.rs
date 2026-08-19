use tauri::Url;

use crate::{AppError, AppResult};

pub fn is_app_navigation_allowed(url: &Url, development: bool) -> bool {
    let packaged = (url.scheme() == "tauri"
        && url.host_str() == Some("localhost")
        && url.port().is_none())
        || (url.scheme() == "http"
            && url.host_str() == Some("tauri.localhost")
            && url.port().is_none());
    let local_development = development
        && url.scheme() == "http"
        && url.host_str() == Some("127.0.0.1")
        && url.port() == Some(1420);
    packaged || local_development
}

pub fn validate_external_https(value: &str) -> AppResult<Url> {
    let url = Url::parse(value)
        .map_err(|_| AppError::Security("stored evidence URL is invalid".to_owned()))?;
    if url.scheme() != "https"
        || url.domain().is_none()
        || url.port().is_some_and(|port| port != 443)
        || !url.username().is_empty()
        || url.password().is_some()
        || url.domain().is_some_and(|domain| {
            let normalized = domain.to_ascii_lowercase();
            normalized == "localhost" || normalized.ends_with(".localhost") || normalized.ends_with(".local")
        })
    {
        return Err(AppError::Security(
            "only credential-free HTTPS evidence links may be opened".to_owned(),
        ));
    }
    Ok(url)
}

#[cfg(windows)]
pub fn open_external_https(value: &str) -> AppResult<()> {
    use std::os::windows::ffi::OsStrExt;
    use std::{ffi::OsStr, ptr};
    use windows_sys::Win32::UI::Shell::ShellExecuteW;
    use windows_sys::Win32::UI::WindowsAndMessaging::SW_SHOWNORMAL;

    let url = validate_external_https(value)?;
    let operation = OsStr::new("open").encode_wide().chain(Some(0)).collect::<Vec<_>>();
    let target = OsStr::new(url.as_str()).encode_wide().chain(Some(0)).collect::<Vec<_>>();
    let result = unsafe {
        ShellExecuteW(
            ptr::null_mut(),
            operation.as_ptr(),
            target.as_ptr(),
            ptr::null(),
            ptr::null(),
            SW_SHOWNORMAL,
        )
    };
    if result as isize <= 32 {
        return Err(AppError::External(
            "Windows could not open the evidence link".to_owned(),
        ));
    }
    Ok(())
}

#[cfg(not(windows))]
pub fn open_external_https(_value: &str) -> AppResult<()> {
    Err(AppError::External(
        "external evidence links are supported only on Windows".to_owned(),
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn navigation_allowlist_is_exact() {
        assert!(is_app_navigation_allowed(&Url::parse("tauri://localhost/").unwrap(), false));
        assert!(is_app_navigation_allowed(&Url::parse("http://tauri.localhost/").unwrap(), false));
        assert!(!is_app_navigation_allowed(&Url::parse("https://example.com/").unwrap(), false));
        assert!(!is_app_navigation_allowed(&Url::parse("https://tauri.localhost/").unwrap(), false));
        assert!(!is_app_navigation_allowed(&Url::parse("http://tauri.localhost:4444/").unwrap(), false));
        assert!(is_app_navigation_allowed(&Url::parse("http://127.0.0.1:1420/").unwrap(), true));
        assert!(!is_app_navigation_allowed(&Url::parse("http://localhost:1420/").unwrap(), true));
    }

    #[test]
    fn external_links_reject_non_https_and_credentials() {
        assert!(validate_external_https("https://example.com/source").is_ok());
        assert!(validate_external_https("http://example.com/source").is_err());
        assert!(validate_external_https("https://user:pass@example.com/source").is_err());
    }
}
