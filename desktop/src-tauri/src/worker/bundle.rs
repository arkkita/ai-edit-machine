use std::collections::{BTreeMap, BTreeSet};
use std::fs::{self, File};
use std::io::Read;
use std::io::{Seek, SeekFrom};
use std::path::{Component, Path, PathBuf};

use serde::Deserialize;
use sha2::{Digest, Sha256};

use crate::{AppError, AppResult};

include!(concat!(env!("OUT_DIR"), "/embedded_worker_manifest.rs"));

pub const EXPECTED_WORKER_TARGET: &str = "windows-x86_64";
pub const EXPECTED_LAUNCHER: &str = "ai-edit-machine-worker.exe";
pub const WORKER_CONTRACT: &str = "worker-contract.json";

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct WorkerManifest {
    pub manifest_version: String,
    pub available: bool,
    pub worker_version: String,
    pub target: String,
    pub build_target: String,
    pub launcher_relative_path: String,
    pub files: Vec<WorkerManifestFile>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct WorkerManifestFile {
    pub relative_path: String,
    pub size_bytes: u64,
    pub sha256: String,
}

#[derive(Debug, Clone)]
pub struct VerifiedWorkerBundle {
    pub root: PathBuf,
    pub launcher: PathBuf,
    pub worker_version: String,
    pub target: String,
    pub file_count: usize,
}

pub fn embedded_manifest() -> AppResult<WorkerManifest> {
    serde_json::from_str(EMBEDDED_WORKER_MANIFEST_JSON)
        .map_err(|_| AppError::Worker("embedded worker manifest is invalid".to_owned()))
}

pub fn embedded_manifest_sha256() -> &'static str {
    EMBEDDED_WORKER_MANIFEST_SHA256
}

pub fn verify_embedded(resource_dir: &Path) -> AppResult<VerifiedWorkerBundle> {
    let manifest = embedded_manifest()?;
    if !manifest.available {
        return Err(AppError::Worker(
            "this development build explicitly contains no packaged worker".to_owned(),
        ));
    }
    verify_bundle(&resource_dir.join("worker/windows-x86_64"), &manifest)
}

pub fn verify_bundle(root: &Path, manifest: &WorkerManifest) -> AppResult<VerifiedWorkerBundle> {
    if manifest.manifest_version != "1.0.0"
        || manifest.target != EXPECTED_WORKER_TARGET
        || manifest.build_target != "x86_64-pc-windows-msvc"
        || manifest.launcher_relative_path != EXPECTED_LAUNCHER
        || manifest.worker_version.trim().is_empty()
        || manifest.worker_version.len() > 64
        || !manifest.worker_version.bytes().all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-'))
        || manifest.files.is_empty()
    {
        return Err(AppError::Worker(
            "worker manifest version, target, or launcher is not approved".to_owned(),
        ));
    }
    let root_metadata = fs::symlink_metadata(root)
        .map_err(|_| AppError::Worker("worker bundle directory is missing".to_owned()))?;
    if !root_metadata.is_dir() || is_reparse_point(&root_metadata) {
        return Err(AppError::Worker("worker bundle root is not a plain directory".to_owned()));
    }
    let canonical_root = fs::canonicalize(root)
        .map_err(|_| AppError::Worker("worker bundle directory cannot be resolved".to_owned()))?;

    let mut expected = BTreeMap::new();
    let mut expected_casefolded = BTreeSet::new();
    for file in &manifest.files {
        validate_relative_path(&file.relative_path)?;
        if file.sha256.len() != 64 || !file.sha256.bytes().all(|byte| byte.is_ascii_hexdigit()) {
            return Err(AppError::Worker("worker manifest contains an invalid SHA-256".to_owned()));
        }
        if expected.insert(file.relative_path.clone(), file).is_some() {
            return Err(AppError::Worker("worker manifest contains duplicate paths".to_owned()));
        }
        if !expected_casefolded.insert(file.relative_path.to_ascii_lowercase()) {
            return Err(AppError::Worker("worker manifest paths collide case-insensitively".to_owned()));
        }
    }
    if !expected.contains_key(EXPECTED_LAUNCHER) {
        return Err(AppError::Worker("worker launcher is absent from the manifest".to_owned()));
    }
    if !expected.contains_key(WORKER_CONTRACT) {
        return Err(AppError::Worker("worker contract is absent from the manifest".to_owned()));
    }

    let mut actual = BTreeSet::new();
    collect_actual_files(&canonical_root, &canonical_root, &mut actual)?;
    let expected_paths = expected.keys().cloned().collect::<BTreeSet<_>>();
    if actual != expected_paths {
        return Err(AppError::Worker(
            "worker bundle has missing or extra files".to_owned(),
        ));
    }
    validate_worker_contract(&canonical_root.join(WORKER_CONTRACT), manifest)?;
    for (relative, expected_file) in expected {
        let path = canonical_root.join(relative.replace('/', std::path::MAIN_SEPARATOR_STR));
        let metadata = fs::symlink_metadata(&path)?;
        if !metadata.is_file() || is_reparse_point(&metadata) || metadata.len() != expected_file.size_bytes {
            return Err(AppError::Worker("worker file type or size does not match".to_owned()));
        }
        let mut file = File::open(&path)?;
        let mut hasher = Sha256::new();
        let mut buffer = [0_u8; 64 * 1024];
        loop {
            let count = file.read(&mut buffer)?;
            if count == 0 { break; }
            hasher.update(&buffer[..count]);
        }
        if hex::encode(hasher.finalize()) != expected_file.sha256.to_ascii_lowercase() {
            return Err(AppError::Worker("worker file hash does not match".to_owned()));
        }
        if is_pe_path(&relative) {
            validate_amd64_pe(&path)?;
        }
    }
    let launcher = canonical_root.join(EXPECTED_LAUNCHER);
    Ok(VerifiedWorkerBundle {
        root: canonical_root,
        launcher,
        worker_version: manifest.worker_version.clone(),
        target: manifest.target.clone(),
        file_count: manifest.files.len(),
    })
}

fn validate_worker_contract(path: &Path, manifest: &WorkerManifest) -> AppResult<()> {
    let rendered = fs::read_to_string(path)
        .map_err(|_| AppError::Worker("worker contract cannot be read".to_owned()))?;
    let value = super::protocol::parse_strict_json_bytes(rendered.as_bytes())?;
    let object = value.as_object()
        .ok_or_else(|| AppError::Worker("worker contract is not an object".to_owned()))?;
    if object.len() != 3
        || object.get("protocolVersion").and_then(serde_json::Value::as_str) != Some(super::protocol::PROTOCOL_VERSION)
        || object.get("target").and_then(serde_json::Value::as_str) != Some(manifest.target.as_str())
        || object.get("workerVersion").and_then(serde_json::Value::as_str) != Some(manifest.worker_version.as_str())
    {
        return Err(AppError::Worker("worker contract does not match the embedded manifest".to_owned()));
    }
    Ok(())
}

fn is_pe_path(value: &str) -> bool {
    Path::new(value)
        .extension()
        .and_then(|extension| extension.to_str())
        .is_some_and(|extension| matches!(extension.to_ascii_lowercase().as_str(), "exe" | "dll" | "pyd"))
}

fn validate_amd64_pe(path: &Path) -> AppResult<()> {
    let mut file = File::open(path)?;
    let mut dos_header = [0_u8; 64];
    file.read_exact(&mut dos_header)
        .map_err(|_| AppError::Worker("worker launcher has a truncated DOS header".to_owned()))?;
    if &dos_header[..2] != b"MZ" {
        return Err(AppError::Worker("worker launcher is not a PE file".to_owned()));
    }
    let pe_offset = u32::from_le_bytes(dos_header[0x3c..0x40].try_into().expect("fixed PE offset"));
    if !(64..=16 * 1024 * 1024).contains(&pe_offset) {
        return Err(AppError::Worker("worker launcher has an invalid PE offset".to_owned()));
    }
    file.seek(SeekFrom::Start(u64::from(pe_offset)))?;
    let mut header = [0_u8; 6];
    file.read_exact(&mut header)
        .map_err(|_| AppError::Worker("worker launcher has a truncated PE header".to_owned()))?;
    if &header[..4] != b"PE\0\0" || u16::from_le_bytes([header[4], header[5]]) != 0x8664 {
        return Err(AppError::Worker("worker launcher is not an AMD64 PE".to_owned()));
    }
    Ok(())
}

fn validate_relative_path(value: &str) -> AppResult<()> {
    if value.is_empty() || value.contains('\\') || value.starts_with('/') || value.contains(':') {
        return Err(AppError::Worker("worker manifest path is not canonical".to_owned()));
    }
    let path = Path::new(value);
    if path.components().any(|component| !matches!(component, Component::Normal(_))) {
        return Err(AppError::Worker("worker manifest path escapes the bundle".to_owned()));
    }
    Ok(())
}

fn collect_actual_files(root: &Path, directory: &Path, output: &mut BTreeSet<String>) -> AppResult<()> {
    for entry in fs::read_dir(directory)? {
        let entry = entry?;
        let path = entry.path();
        let metadata = fs::symlink_metadata(&path)?;
        if is_reparse_point(&metadata) {
            return Err(AppError::Worker("worker bundle contains a reparse point".to_owned()));
        }
        if metadata.is_dir() {
            collect_actual_files(root, &path, output)?;
        } else if metadata.is_file() {
            let relative = path.strip_prefix(root)
                .map_err(|_| AppError::Worker("worker path escaped its bundle".to_owned()))?;
            let normalized = relative.to_str()
                .ok_or_else(|| AppError::Worker("worker bundle path is not Unicode".to_owned()))?
                .replace('\\', "/");
            validate_relative_path(&normalized)?;
            if output.iter().any(|existing| existing.eq_ignore_ascii_case(&normalized)) {
                return Err(AppError::Worker("worker paths collide case-insensitively".to_owned()));
            }
            output.insert(normalized);
        } else {
            return Err(AppError::Worker("worker bundle contains an unsupported entry".to_owned()));
        }
    }
    Ok(())
}

#[cfg(windows)]
fn is_reparse_point(metadata: &fs::Metadata) -> bool {
    use std::os::windows::fs::MetadataExt;
    metadata.file_attributes() & 0x400 != 0
}

#[cfg(not(windows))]
fn is_reparse_point(metadata: &fs::Metadata) -> bool {
    metadata.file_type().is_symlink()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    fn minimal_pe(machine: u16) -> Vec<u8> {
        let mut bytes = vec![0_u8; 0x86];
        bytes[..2].copy_from_slice(b"MZ");
        bytes[0x3c..0x40].copy_from_slice(&(0x80_u32).to_le_bytes());
        bytes[0x80..0x84].copy_from_slice(b"PE\0\0");
        bytes[0x84..0x86].copy_from_slice(&machine.to_le_bytes());
        bytes
    }

    fn fixture() -> (tempfile::TempDir, WorkerManifest) {
        let directory = tempfile::tempdir().unwrap();
        let launcher = directory.path().join(EXPECTED_LAUNCHER);
        let bytes = minimal_pe(0x8664);
        File::create(&launcher).unwrap().write_all(&bytes).unwrap();
        let hash = crate::security::sha256_hex(&bytes);
        let contract_bytes = br#"{"protocolVersion":"1.0.0","target":"windows-x86_64","workerVersion":"test"}"#;
        File::create(directory.path().join(WORKER_CONTRACT)).unwrap().write_all(contract_bytes).unwrap();
        let manifest = WorkerManifest {
            manifest_version: "1.0.0".into(),
            available: true,
            worker_version: "test".into(),
            target: EXPECTED_WORKER_TARGET.into(),
            build_target: "x86_64-pc-windows-msvc".into(),
            launcher_relative_path: EXPECTED_LAUNCHER.into(),
            files: vec![
                WorkerManifestFile {
                    relative_path: EXPECTED_LAUNCHER.into(),
                    size_bytes: bytes.len() as u64,
                    sha256: hash,
                },
                WorkerManifestFile {
                    relative_path: WORKER_CONTRACT.into(),
                    size_bytes: contract_bytes.len() as u64,
                    sha256: crate::security::sha256_hex(contract_bytes),
                },
            ],
        };
        (directory, manifest)
    }

    #[test]
    fn accepts_exact_fixture_and_rejects_tamper() {
        let (directory, manifest) = fixture();
        assert!(verify_bundle(directory.path(), &manifest).is_ok());
        fs::write(directory.path().join(EXPECTED_LAUNCHER), b"tampered launcher").unwrap();
        assert!(verify_bundle(directory.path(), &manifest).is_err());
    }

    #[test]
    fn rejects_missing_extra_wrong_target_and_substituted_manifest() {
        let (directory, manifest) = fixture();
        fs::remove_file(directory.path().join(EXPECTED_LAUNCHER)).unwrap();
        assert!(verify_bundle(directory.path(), &manifest).is_err());

        let (directory, manifest) = fixture();
        fs::write(directory.path().join("extra.dll"), b"extra").unwrap();
        assert!(verify_bundle(directory.path(), &manifest).is_err());

        let (directory, mut manifest) = fixture();
        manifest.target = "linux-x86_64".into();
        assert!(verify_bundle(directory.path(), &manifest).is_err());

        let (directory, manifest) = fixture();
        fs::write(directory.path().join("worker-manifest.json"), b"{}").unwrap();
        assert!(verify_bundle(directory.path(), &manifest).is_err());
    }

    #[test]
    fn rejects_a_real_x86_pe_machine_header() {
        let (directory, mut manifest) = fixture();
        let bytes = minimal_pe(0x014c);
        fs::write(directory.path().join(EXPECTED_LAUNCHER), &bytes).unwrap();
        manifest.files[0].size_bytes = bytes.len() as u64;
        manifest.files[0].sha256 = crate::security::sha256_hex(&bytes);
        assert!(verify_bundle(directory.path(), &manifest).is_err());
    }

    #[test]
    fn rejects_contract_substitution_even_when_its_manifest_hash_is_updated() {
        let (directory, mut manifest) = fixture();
        let substituted = br#"{"protocolVersion":"1.0.0","target":"windows-x86_64","workerVersion":"other"}"#;
        fs::write(directory.path().join(WORKER_CONTRACT), substituted).unwrap();
        let entry = manifest.files.iter_mut().find(|entry| entry.relative_path == WORKER_CONTRACT).unwrap();
        entry.size_bytes = substituted.len() as u64;
        entry.sha256 = crate::security::sha256_hex(substituted);
        assert!(verify_bundle(directory.path(), &manifest).is_err());
    }

    #[test]
    fn rejects_escaped_duplicate_contract_key() {
        let (directory, mut manifest) = fixture();
        let substituted = br#"{"protocolVersion":"1.0.0","\u0070rotocolVersion":"1.0.0","target":"windows-x86_64","workerVersion":"test"}"#;
        fs::write(directory.path().join(WORKER_CONTRACT), substituted).unwrap();
        let entry = manifest.files.iter_mut().find(|entry| entry.relative_path == WORKER_CONTRACT).unwrap();
        entry.size_bytes = substituted.len() as u64;
        entry.sha256 = crate::security::sha256_hex(substituted);
        assert!(verify_bundle(directory.path(), &manifest).is_err());
    }
}
