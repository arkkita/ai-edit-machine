use std::io::{BufReader, Read};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError};
use std::time::{Duration, Instant};

use serde::Serialize;
use uuid::Uuid;

use super::bundle::{self, VerifiedWorkerBundle};
use super::job_object::KillOnCloseJob;
use super::protocol::{self, WorkerEnvelope, WorkerHello, WorkerMessage};
use crate::{AppError, AppResult};

#[derive(Debug, Clone, Copy, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum WorkerRuntimeStatus {
    Ready,
    Running,
    Unavailable,
    InvalidBundle,
    Stopped,
}

pub struct WorkerSupervisor {
    bundle: Option<VerifiedWorkerBundle>,
    status: WorkerRuntimeStatus,
    diagnostic: Option<String>,
    child: Option<Child>,
    stdin: Option<ChildStdin>,
    frames: Option<Receiver<AppResult<serde_json::Value>>>,
    job: Option<KillOnCloseJob>,
    temp_root: PathBuf,
    active_request: Option<Uuid>,
    last_terminal_request: Option<Uuid>,
}

impl WorkerSupervisor {
    pub fn from_paths(resource_dir: &Path, temp_root: &Path) -> Self {
        let temp_root = temp_root.to_path_buf();
        let embedded = bundle::embedded_manifest();
        match embedded {
            Ok(manifest) if !manifest.available => Self::without_bundle(
                WorkerRuntimeStatus::Unavailable,
                "development build has no packaged worker",
            ),
            Ok(_) => match bundle::verify_embedded(resource_dir) {
                Ok(bundle) => Self {
                    bundle: Some(bundle),
                    status: WorkerRuntimeStatus::Ready,
                    diagnostic: None,
                    child: None,
                    stdin: None,
                    frames: None,
                    job: None,
                    temp_root,
                    active_request: None,
                    last_terminal_request: None,
                },
                Err(error) => Self::without_bundle(
                    WorkerRuntimeStatus::InvalidBundle,
                    &error.to_string(),
                ),
            },
            Err(error) => Self::without_bundle(
                WorkerRuntimeStatus::InvalidBundle,
                &error.to_string(),
            ),
        }
    }

    fn without_bundle(status: WorkerRuntimeStatus, diagnostic: &str) -> Self {
        Self {
            bundle: None,
            status,
            diagnostic: Some(crate::security::sanitized_error(diagnostic)),
            child: None,
            stdin: None,
            frames: None,
            job: None,
            temp_root: PathBuf::new(),
            active_request: None,
            last_terminal_request: None,
        }
    }

    pub fn status(&self) -> WorkerRuntimeStatus { self.status }
    pub fn worker_version(&self) -> Option<&str> { self.bundle.as_ref().map(|value| value.worker_version.as_str()) }
    pub fn target(&self) -> Option<&str> { self.bundle.as_ref().map(|value| value.target.as_str()) }
    pub fn file_count(&self) -> Option<usize> { self.bundle.as_ref().map(|value| value.file_count) }
    pub fn diagnostic(&self) -> Option<&str> { self.diagnostic.as_deref() }
    pub fn active_request_id(&self) -> Option<Uuid> { self.active_request }

    pub fn start(&mut self) -> AppResult<()> {
        if let Some(child) = &mut self.child {
            if child.try_wait()?.is_none() { return Ok(()); }
            self.clear_process_state();
        }
        let cached_bundle = self.bundle.clone().ok_or_else(|| {
            AppError::Worker("verified packaged worker is unavailable".to_owned())
        })?;
        let manifest = bundle::embedded_manifest()?;
        let bundle = match bundle::verify_bundle(&cached_bundle.root, &manifest) {
            Ok(bundle) => bundle,
            Err(error) => {
                self.status = WorkerRuntimeStatus::InvalidBundle;
                self.diagnostic = Some(crate::security::sanitized_error(&error.to_string()));
                self.bundle = None;
                return Err(error);
            }
        };
        self.bundle = Some(bundle.clone());
        let job = KillOnCloseJob::create()?;
        let mut command = Command::new(&bundle.launcher);
        command
            .current_dir(&bundle.root)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .env_clear()
            .env("PYTHONUTF8", "1")
            .env("PYTHONNOUSERSITE", "1")
            .env("PYTHONSAFEPATH", "1")
            .env("AI_EDIT_WORKER_PROTOCOL", protocol::PROTOCOL_VERSION);
        apply_sanitized_windows_environment(&mut command, &bundle.root, &self.temp_root)?;
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            const CREATE_SUSPENDED: u32 = 0x0000_0004;
            const CREATE_NO_WINDOW: u32 = 0x0800_0000;
            command.creation_flags(CREATE_SUSPENDED | CREATE_NO_WINDOW);
        }
        let mut child = command.spawn()
            .map_err(|_| AppError::Worker("packaged worker could not be launched".to_owned()))?;
        if let Err(error) = job.assign(&child) {
            let _ = child.kill();
            let _ = child.wait();
            return Err(error);
        }
        if let Err(error) = job.resume_suspended_process(child.id()) {
            let _ = job.terminate(13);
            let _ = child.wait();
            return Err(error);
        }
        let stdin = child.stdin.take().ok_or_else(|| AppError::Worker("worker stdin was not inherited".to_owned()))?;
        let stdout = child.stdout.take().ok_or_else(|| AppError::Worker("worker stdout was not inherited".to_owned()))?;
        let stderr = child.stderr.take().ok_or_else(|| AppError::Worker("worker stderr was not inherited".to_owned()))?;
        let (sender, receiver) = mpsc::sync_channel(16);
        std::thread::Builder::new()
            .name("ai-edit-worker-stdout".into())
            .spawn(move || {
                let mut reader = BufReader::new(stdout);
                loop {
                    let frame = protocol::read_frame::<_, serde_json::Value>(&mut reader);
                    let terminal = frame.is_err();
                    if sender.send(frame).is_err() || terminal { break; }
                }
            })
            .map_err(|_| AppError::Worker("worker protocol reader could not start".to_owned()))?;
        std::thread::Builder::new()
            .name("ai-edit-worker-stderr".into())
            .spawn(move || {
                let mut reader = BufReader::new(stderr);
                let mut buffer = [0_u8; 4096];
                loop {
                    match reader.read(&mut buffer) {
                        Ok(0) | Err(_) => break,
                        Ok(count) => {
                            let diagnostic = String::from_utf8_lossy(&buffer[..count]);
                            let _sanitized = crate::security::sanitized_error(&diagnostic);
                        }
                    }
                }
            })
            .map_err(|_| AppError::Worker("worker diagnostic reader could not start".to_owned()))?;

        let hello_value = match receiver.recv_timeout(protocol::HANDSHAKE_TIMEOUT) {
            Ok(result) => result?,
            Err(_) => {
                let _ = job.terminate(10);
                let _ = child.wait();
                return Err(AppError::Worker("worker handshake exceeded 5 seconds".to_owned()));
            }
        };
        let hello: WorkerHello = serde_json::from_value(hello_value)
            .map_err(|_| AppError::Worker("worker handshake violates its schema".to_owned()))?;
        if hello.message_type != "hello"
            || hello.protocol_version != protocol::PROTOCOL_VERSION
            || hello.worker_version != bundle.worker_version
            || hello.target != bundle.target
        {
            let _ = job.terminate(11);
            let _ = child.wait();
            return Err(AppError::Worker("worker handshake version or target mismatch".to_owned()));
        }
        self.child = Some(child);
        self.stdin = Some(stdin);
        self.frames = Some(receiver);
        self.job = Some(job);
        self.status = WorkerRuntimeStatus::Running;
        Ok(())
    }

    pub fn send<T: Serialize>(&mut self, message_type: &str, request_id: Uuid, payload: T) -> AppResult<()> {
        if message_type.trim().is_empty() { return Err(AppError::Validation("worker message type is empty".to_owned())); }
        if self.active_request.is_some_and(|active| active != request_id) {
            return Err(AppError::Worker("worker already has an active request".to_owned()));
        }
        let Some(writer) = self.stdin.as_mut() else {
            return Err(AppError::Worker("worker is not running".to_owned()));
        };
        let result = protocol::write_frame(writer, &WorkerEnvelope {
            protocol_version: protocol::PROTOCOL_VERSION.to_owned(),
            request_id,
            message_type: message_type.to_owned(),
            payload,
        });
        if let Err(error) = result {
            self.fail_and_reap();
            return Err(error);
        }
        self.active_request = Some(request_id);
        self.last_terminal_request = None;
        Ok(())
    }

    pub fn receive(&mut self, timeout: Duration) -> AppResult<WorkerMessage> {
        match self.poll(timeout)? {
            Some(message) => Ok(message),
            None => {
                self.fail_and_reap();
                Err(AppError::Worker("worker response timed out".to_owned()))
            }
        }
    }

    pub fn poll(&mut self, timeout: Duration) -> AppResult<Option<WorkerMessage>> {
        let result = match self.frames.as_ref()
            .ok_or_else(|| AppError::Worker("worker is not running".to_owned()))?
            .recv_timeout(timeout)
        {
            Ok(value) => value,
            Err(RecvTimeoutError::Timeout) => return Ok(None),
            Err(RecvTimeoutError::Disconnected) => Err(AppError::Worker("worker response channel disconnected".to_owned())),
        };
        let value = match result {
            Ok(value) => value,
            Err(error) => {
                self.fail_and_reap();
                return Err(error);
            }
        };
        let (request_id, message) = match protocol::decode_worker_message(value) {
            Ok(value) => value,
            Err(error) => {
                self.fail_and_reap();
                return Err(error);
            }
        };
        if self.active_request != Some(request_id) {
            self.fail_and_reap();
            return Err(AppError::Worker("worker response identity mismatch".to_owned()));
        }
        if message.is_terminal_for_active_request() {
            self.active_request = None;
            self.last_terminal_request = Some(request_id);
        }
        Ok(Some(message))
    }

    pub fn send_cancel(&mut self, job_id: Uuid) -> AppResult<()> {
        let request_id = self.active_request
            .ok_or_else(|| AppError::Worker("worker has no active research request".to_owned()))?;
        if request_id != job_id {
            return Err(AppError::Worker("active worker request does not match the cancelled job".to_owned()));
        }
        self.send("research.cancel", request_id, serde_json::json!({
            "schemaVersion": protocol::PAYLOAD_SCHEMA_VERSION,
            "jobId": job_id,
        }))
    }

    pub fn abort_active(&mut self) {
        self.fail_and_reap();
    }

    /// Abort only when the currently bound request still matches.  Cancellation
    /// escalation runs asynchronously, so this identity check prevents a late
    /// watchdog from terminating a subsequently started job.
    pub fn abort_request(&mut self, request_id: Uuid) -> bool {
        if self.active_request == Some(request_id)
            || (self.active_request.is_none() && self.last_terminal_request == Some(request_id))
        {
            self.fail_and_reap();
            true
        } else {
            false
        }
    }

    pub fn stop(&mut self) -> AppResult<()> {
        if self.child.is_none() {
            self.status = if self.bundle.is_some() { WorkerRuntimeStatus::Stopped } else { self.status };
            return Ok(());
        }
        if self.active_request.is_some() {
            self.fail_and_reap();
            self.status = WorkerRuntimeStatus::Stopped;
            return Ok(());
        }
        let request_id = Uuid::new_v4();
        self.send("shutdown", request_id, protocol::ShutdownPayload {
            schema_version: protocol::PAYLOAD_SCHEMA_VERSION.to_owned(),
            reason: "host shutdown".to_owned(),
        })?;
        match self.receive(Duration::from_secs(2)) {
            Ok(WorkerMessage::ShutdownAck(_)) => {}
            Ok(_) => {
                self.fail_and_reap();
                return Err(AppError::Worker("worker returned the wrong shutdown acknowledgement".to_owned()));
            }
            Err(error) => return Err(error),
        }
        self.stdin.take();
        let deadline = Instant::now() + Duration::from_secs(2);
        let mut successful_exit = false;
        let exited = loop {
            match self.child.as_mut().and_then(|child| child.try_wait().ok()).flatten() {
                Some(status) => {
                    successful_exit = status.success();
                    break true;
                }
                None if Instant::now() < deadline => std::thread::sleep(Duration::from_millis(25)),
                None => break false,
            }
        };
        if !exited {
            if let Some(job) = &self.job { let _ = job.terminate(12); }
            if let Some(child) = &mut self.child { let _ = child.wait(); }
            self.clear_process_state();
            self.status = WorkerRuntimeStatus::Stopped;
            return Err(AppError::Worker("worker did not exit after shutdown acknowledgement".to_owned()));
        }
        if exited && !successful_exit {
            self.fail_and_reap();
            return Err(AppError::Worker("worker exited unsuccessfully after shutdown acknowledgement".to_owned()));
        }
        let clean_eof = self.frames.as_ref().is_some_and(|frames| {
            matches!(
                frames.recv_timeout(Duration::from_millis(250)),
                Ok(Err(AppError::Worker(message))) if message == "worker stdout reached unexpected EOF"
            )
        });
        if !clean_eof {
            self.fail_and_reap();
            return Err(AppError::Worker("worker emitted trailing or malformed stdout after shutdown acknowledgement".to_owned()));
        }
        self.child.take();
        self.frames.take();
        self.job.take();
        self.active_request = None;
        self.last_terminal_request = None;
        self.status = WorkerRuntimeStatus::Stopped;
        Ok(())
    }

    fn fail_and_reap(&mut self) {
        if let Some(job) = &self.job { let _ = job.terminate(14); }
        if let Some(child) = &mut self.child { let _ = child.wait(); }
        self.clear_process_state();
        self.status = if self.bundle.is_some() { WorkerRuntimeStatus::Ready } else { WorkerRuntimeStatus::Unavailable };
    }

    fn clear_process_state(&mut self) {
        self.stdin.take();
        self.frames.take();
        self.child.take();
        self.job.take();
        self.active_request = None;
        self.last_terminal_request = None;
    }
}

impl Drop for WorkerSupervisor {
    fn drop(&mut self) { let _ = self.stop(); }
}

fn apply_sanitized_windows_environment(command: &mut Command, bundle_root: &Path, temp_root: &Path) -> AppResult<()> {
    let (system_root, system32) = trusted_windows_directories()?;
    std::fs::create_dir_all(temp_root)?;
    let temp_root = std::fs::canonicalize(temp_root)
        .map_err(|_| AppError::Worker("app-owned worker temp directory is invalid".to_owned()))?;
    let path = std::env::join_paths([bundle_root, system32.as_path()])
        .map_err(|_| AppError::Worker("sanitized worker PATH is invalid".to_owned()))?;
    command.env("SystemRoot", &system_root).env("WINDIR", &system_root).env("PATH", path);
    command.env("TEMP", &temp_root).env("TMP", temp_root);
    Ok(())
}

#[cfg(windows)]
fn trusted_windows_directories() -> AppResult<(PathBuf, PathBuf)> {
    use windows_sys::Win32::System::SystemInformation::{GetSystemDirectoryW, GetWindowsDirectoryW};

    fn query(function: unsafe extern "system" fn(*mut u16, u32) -> u32) -> AppResult<PathBuf> {
        let mut buffer = vec![0_u16; 32_768];
        let length = unsafe { function(buffer.as_mut_ptr(), buffer.len() as u32) };
        if length == 0 || length as usize >= buffer.len() {
            return Err(AppError::Worker("Windows system directory lookup failed".to_owned()));
        }
        buffer.truncate(length as usize);
        Ok(PathBuf::from(String::from_utf16(&buffer)
            .map_err(|_| AppError::Worker("Windows returned a non-Unicode system path".to_owned()))?))
    }
    let root = std::fs::canonicalize(query(GetWindowsDirectoryW)?)?;
    let system32 = std::fs::canonicalize(query(GetSystemDirectoryW)?)?;
    if !system32.starts_with(&root) {
        return Err(AppError::Worker("Windows system directory failed canonical validation".to_owned()));
    }
    Ok((root, system32))
}

#[cfg(not(windows))]
fn trusted_windows_directories() -> AppResult<(PathBuf, PathBuf)> {
    Err(AppError::Worker("packaged worker is Windows-only".to_owned()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn late_abort_watchdog_cannot_kill_a_different_request() {
        let first = Uuid::new_v4();
        let second = Uuid::new_v4();
        let mut supervisor = WorkerSupervisor::without_bundle(WorkerRuntimeStatus::Ready, "fixture");
        supervisor.active_request = Some(second);
        assert!(!supervisor.abort_request(first));
        assert_eq!(supervisor.active_request_id(), Some(second));
        assert!(supervisor.abort_request(second));
        assert_eq!(supervisor.active_request_id(), None);
    }

    #[test]
    fn malformed_typed_response_clears_active_request_for_a_clean_restart() {
        let request_id = Uuid::new_v4();
        let (sender, receiver) = mpsc::sync_channel(1);
        sender.send(Ok(serde_json::json!({
            "protocolVersion": protocol::PROTOCOL_VERSION,
            "requestId": request_id,
            "messageType": "research.unknown",
            "payload": {"schemaVersion": protocol::PAYLOAD_SCHEMA_VERSION}
        }))).unwrap();
        let mut supervisor = WorkerSupervisor::without_bundle(WorkerRuntimeStatus::Ready, "fixture");
        supervisor.frames = Some(receiver);
        supervisor.active_request = Some(request_id);
        assert!(supervisor.poll(Duration::from_millis(10)).is_err());
        assert_eq!(supervisor.active_request_id(), None);
        assert!(supervisor.frames.is_none());
    }

    #[test]
    fn post_terminal_host_failure_can_reap_only_the_completed_request() {
        let request_id = Uuid::new_v4();
        let (sender, receiver) = mpsc::sync_channel(1);
        sender.send(Ok(serde_json::json!({
            "protocolVersion": protocol::PROTOCOL_VERSION,
            "requestId": request_id,
            "messageType": "research.error",
            "payload": {
                "schemaVersion": protocol::PAYLOAD_SCHEMA_VERSION,
                "jobId": request_id,
                "message": "fixture terminal error",
                "providerOutcomes": []
            }
        }))).unwrap();
        let mut supervisor = WorkerSupervisor::without_bundle(WorkerRuntimeStatus::Ready, "fixture");
        supervisor.frames = Some(receiver);
        supervisor.active_request = Some(request_id);
        assert!(matches!(
            supervisor.poll(Duration::from_millis(10)).unwrap(),
            Some(WorkerMessage::ResearchError(_))
        ));
        assert_eq!(supervisor.active_request_id(), None);
        assert!(supervisor.abort_request(request_id));
        assert!(supervisor.frames.is_none());

        let next = Uuid::new_v4();
        supervisor.active_request = Some(next);
        supervisor.last_terminal_request = Some(request_id);
        assert!(!supervisor.abort_request(request_id));
        assert_eq!(supervisor.active_request_id(), Some(next));
    }

    #[test]
    fn cancel_is_bound_to_the_active_job_identity() {
        let active = Uuid::new_v4();
        let mut supervisor = WorkerSupervisor::without_bundle(WorkerRuntimeStatus::Ready, "fixture");
        supervisor.active_request = Some(active);
        assert!(supervisor.send_cancel(Uuid::new_v4()).is_err());
        assert_eq!(supervisor.active_request_id(), Some(active));
    }
}
