use sha2::{Digest, Sha256};
use serde::de::{self, MapAccess, Visitor};
use std::env;
use std::fs::{self, File};
use std::io::{self, Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};
use std::fmt;

const COMMANDS: &[&str] = &[
    "get_diagnostics",
    "set_project_budget",
    "preview_research",
    "start_research",
    "get_research_run",
    "cancel_research",
    "open_evidence_link",
    "get_credential_status",
    "store_credential",
    "validate_credential",
    "delete_credential",
];

fn main() {
    configure_explicit_unpacked_development_build();
    let attributes = tauri_build::Attributes::new()
        .app_manifest(tauri_build::AppManifest::new().commands(COMMANDS));
    tauri_build::try_build(attributes).expect("Tauri build configuration must be valid");

    println!("cargo:rerun-if-env-changed=AI_EDIT_WORKER_BUNDLE_DIR");
    println!("cargo:rerun-if-env-changed=AI_EDIT_ALLOW_UNPACKAGED_WORKER");
    println!("cargo:rerun-if-changed=resources/worker");
    write_embedded_worker_manifest().expect("worker manifest generation must succeed");
}

fn configure_explicit_unpacked_development_build() {
    let allow_unpacked = env::var("AI_EDIT_ALLOW_UNPACKAGED_WORKER").as_deref() == Ok("1");
    let profile = env::var("PROFILE").unwrap_or_default();
    let bundle_root = env::var_os("AI_EDIT_WORKER_BUNDLE_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("resources/worker/windows-x86_64"));
    if allow_unpacked && profile != "release" && !bundle_root.is_dir() {
        let mut override_config = env::var("TAURI_CONFIG")
            .ok()
            .and_then(|value| serde_json::from_str::<serde_json::Value>(&value).ok())
            .unwrap_or_else(|| serde_json::json!({}));
        override_config["bundle"]["resources"] = serde_json::json!([]);
        // SAFETY: Cargo runs this build script as a single-threaded process before
        // tauri-build reads the override. The variable is scoped to this child.
        unsafe { env::set_var("TAURI_CONFIG", override_config.to_string()) };
    }
}

fn write_embedded_worker_manifest() -> io::Result<()> {
    let target = env::var("TARGET").unwrap_or_else(|_| "unknown-target".to_owned());
    let profile = env::var("PROFILE").unwrap_or_else(|_| "unknown".to_owned());
    let bundle_root = env::var_os("AI_EDIT_WORKER_BUNDLE_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("resources/worker/windows-x86_64"));
    let allow_unpacked = env::var("AI_EDIT_ALLOW_UNPACKAGED_WORKER").as_deref() == Ok("1");
    if target != "x86_64-pc-windows-msvc" && (profile == "release" || !allow_unpacked) {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            format!("worker packaging requires x86_64-pc-windows-msvc, got {target}"),
        ));
    }
    let mut files = Vec::new();
    let available = if bundle_root.is_dir() {
        let metadata = fs::symlink_metadata(&bundle_root)?;
        if !metadata.is_dir() || is_reparse_point(&metadata) {
            return Err(io::Error::new(io::ErrorKind::InvalidData, "worker bundle root must be a plain directory"));
        }
        collect_files(&bundle_root, &bundle_root, &mut files)?;
        true
    } else if profile != "release" && allow_unpacked {
        false
    } else {
        return Err(io::Error::new(
            io::ErrorKind::NotFound,
            format!("packaged worker directory is missing: {}", bundle_root.display()),
        ));
    };
    if available && files.is_empty() {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "worker bundle is empty"));
    }
    let contract = if available {
        parse_worker_contract(&bundle_root.join("worker-contract.json"))?
    } else {
        (String::new(), "windows-x86_64".to_owned())
    };
    if available && target != "x86_64-pc-windows-msvc" {
        return Err(io::Error::new(io::ErrorKind::InvalidInput, "packaged worker builds require the exact x86_64-pc-windows-msvc target"));
    }
    files.sort_by(|left, right| left["relative_path"].as_str().cmp(&right["relative_path"].as_str()));
    let mut casefolded = std::collections::BTreeSet::new();
    for entry in &files {
        let relative = entry["relative_path"].as_str().expect("worker relative path is a string");
        if !casefolded.insert(relative.to_ascii_lowercase()) {
            return Err(io::Error::new(io::ErrorKind::InvalidData, "worker paths collide case-insensitively"));
        }
    }

    let launcher = if files.iter().any(|entry| entry["relative_path"] == "ai-edit-machine-worker.exe") {
        "ai-edit-machine-worker.exe"
    } else if available {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "worker bundle lacks ai-edit-machine-worker.exe",
        ));
    } else {
        ""
    };
    if available {
        for entry in &files {
            let relative = entry["relative_path"].as_str().expect("worker relative path is a string");
            if is_pe_path(relative) {
                validate_amd64_pe(&bundle_root.join(relative.replace('/', std::path::MAIN_SEPARATOR_STR)))?;
            }
        }
    }
    let manifest = serde_json::json!({
        "manifest_version": "1.0.0",
        "available": available,
        "worker_version": contract.0,
        "target": contract.1,
        "build_target": target,
        "launcher_relative_path": launcher,
        "files": files,
    });
    let rendered = serde_json::to_string(&manifest)?;
    let generated = format!("pub const EMBEDDED_WORKER_MANIFEST_JSON: &str = {rendered:?};\n");
    let output = PathBuf::from(env::var_os("OUT_DIR").expect("OUT_DIR is set by Cargo"));
    fs::write(output.join("embedded_worker_manifest.rs"), generated)
}

fn parse_worker_contract(path: &Path) -> io::Result<(String, String)> {
    let rendered = fs::read_to_string(path)
        .map_err(|_| io::Error::new(io::ErrorKind::NotFound, "worker-contract.json is missing"))?;
    let mut deserializer = serde_json::Deserializer::from_str(&rendered);
    let contract = serde::Deserialize::deserialize(&mut deserializer)
        .map_err(|_| io::Error::new(io::ErrorKind::InvalidData, "worker contract is malformed, duplicated, or has unknown fields"))?;
    deserializer.end()
        .map_err(|_| io::Error::new(io::ErrorKind::InvalidData, "worker contract has trailing data"))?;
    let WorkerContract { protocol_version, target, worker_version } = contract;
    if protocol_version != "1.0.0"
        || target != "windows-x86_64"
    {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "worker contract protocol or target is unsupported"));
    }
    if worker_version.is_empty() || worker_version.len() > 64
        || !worker_version.bytes().all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-'))
    {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "worker contract version is invalid"));
    }
    Ok((worker_version, target))
}

struct WorkerContract {
    protocol_version: String,
    target: String,
    worker_version: String,
}

impl<'de> serde::Deserialize<'de> for WorkerContract {
    fn deserialize<D: serde::Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        struct ContractVisitor;
        impl<'de> Visitor<'de> for ContractVisitor {
            type Value = WorkerContract;
            fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result { formatter.write_str("the exact worker contract") }
            fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Self::Value, A::Error> {
                let mut protocol_version = None;
                let mut target = None;
                let mut worker_version = None;
                while let Some(key) = map.next_key::<String>()? {
                    let slot = match key.as_str() {
                        "protocolVersion" => &mut protocol_version,
                        "target" => &mut target,
                        "workerVersion" => &mut worker_version,
                        _ => return Err(de::Error::unknown_field(&key, &["protocolVersion", "target", "workerVersion"])),
                    };
                    if slot.is_some() { return Err(de::Error::custom("duplicate worker contract key")); }
                    *slot = Some(map.next_value::<String>()?);
                }
                Ok(WorkerContract {
                    protocol_version: protocol_version.ok_or_else(|| de::Error::missing_field("protocolVersion"))?,
                    target: target.ok_or_else(|| de::Error::missing_field("target"))?,
                    worker_version: worker_version.ok_or_else(|| de::Error::missing_field("workerVersion"))?,
                })
            }
        }
        deserializer.deserialize_map(ContractVisitor)
    }
}

fn is_pe_path(value: &str) -> bool {
    Path::new(value)
        .extension()
        .and_then(|extension| extension.to_str())
        .is_some_and(|extension| matches!(extension.to_ascii_lowercase().as_str(), "exe" | "dll" | "pyd"))
}

fn validate_amd64_pe(path: &Path) -> io::Result<()> {
    let mut file = File::open(path)?;
    let mut dos_header = [0_u8; 64];
    file.read_exact(&mut dos_header)?;
    if &dos_header[..2] != b"MZ" {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "worker launcher is not a PE file"));
    }
    let pe_offset = u32::from_le_bytes(dos_header[0x3c..0x40].try_into().expect("fixed PE offset"));
    if !(64..=16 * 1024 * 1024).contains(&pe_offset) {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "worker launcher has an invalid PE header offset"));
    }
    file.seek(SeekFrom::Start(u64::from(pe_offset)))?;
    let mut signature_and_machine = [0_u8; 6];
    file.read_exact(&mut signature_and_machine)?;
    if &signature_and_machine[..4] != b"PE\0\0"
        || u16::from_le_bytes([signature_and_machine[4], signature_and_machine[5]]) != 0x8664
    {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "worker launcher is not an AMD64 PE"));
    }
    Ok(())
}

fn collect_files(root: &Path, directory: &Path, files: &mut Vec<serde_json::Value>) -> io::Result<()> {
    for entry in fs::read_dir(directory)? {
        let entry = entry?;
        let path = entry.path();
        let metadata = fs::symlink_metadata(&path)?;
        if is_reparse_point(&metadata) {
            return Err(io::Error::new(io::ErrorKind::InvalidData, "worker bundle cannot contain reparse points"));
        }
        if metadata.is_dir() {
            collect_files(root, &path, files)?;
        } else if metadata.is_file() {
            let relative = path.strip_prefix(root).map_err(io::Error::other)?;
            let relative_path = relative.to_str()
                .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidData, "worker bundle path is not Unicode"))?
                .replace('\\', "/");
            let mut input = File::open(&path)?;
            let mut hasher = Sha256::new();
            let mut buffer = [0_u8; 64 * 1024];
            loop {
                let count = input.read(&mut buffer)?;
                if count == 0 { break; }
                hasher.update(&buffer[..count]);
            }
            files.push(serde_json::json!({
                "relative_path": relative_path,
                "size_bytes": metadata.len(),
                "sha256": hex::encode(hasher.finalize()),
            }));
        } else {
            return Err(io::Error::new(io::ErrorKind::InvalidData, "worker bundle contains an unsupported entry"));
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
