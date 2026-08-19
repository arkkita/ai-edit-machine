use crate::{AppError, AppResult};

#[cfg(windows)]
mod platform {
    use std::mem::size_of;
    use std::os::windows::io::AsRawHandle;
    use std::process::Child;
    use std::ptr;

    use windows_sys::Win32::Foundation::{CloseHandle, GetLastError, HANDLE};
    use windows_sys::Win32::System::JobObjects::{
        AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
        SetInformationJobObject, TerminateJobObject,
    };
    use windows_sys::Win32::System::Diagnostics::ToolHelp::{
        CreateToolhelp32Snapshot, Thread32First, Thread32Next, TH32CS_SNAPTHREAD, THREADENTRY32,
    };
    use windows_sys::Win32::System::Threading::{OpenThread, ResumeThread, THREAD_SUSPEND_RESUME};

    use super::*;

    pub struct KillOnCloseJob {
        handle: HANDLE,
    }

    unsafe impl Send for KillOnCloseJob {}

    impl KillOnCloseJob {
        pub fn create() -> AppResult<Self> {
            let handle = unsafe { CreateJobObjectW(ptr::null(), ptr::null()) };
            if handle.is_null() {
                return Err(last_error("could not create the worker Job Object"));
            }
            let mut information: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = unsafe { std::mem::zeroed() };
            information.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            let succeeded = unsafe {
                SetInformationJobObject(
                    handle,
                    JobObjectExtendedLimitInformation,
                    (&raw const information).cast(),
                    size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
                )
            };
            if succeeded == 0 {
                unsafe { CloseHandle(handle) };
                return Err(last_error("could not configure the worker Job Object"));
            }
            Ok(Self { handle })
        }

        pub fn assign(&self, child: &Child) -> AppResult<()> {
            let process = child.as_raw_handle() as HANDLE;
            if unsafe { AssignProcessToJobObject(self.handle, process) } == 0 {
                return Err(last_error("could not place the worker in its Job Object"));
            }
            Ok(())
        }

        pub fn resume_suspended_process(&self, process_id: u32) -> AppResult<()> {
            let snapshot = unsafe { CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0) };
            if snapshot.is_null() || snapshot == -1_isize as HANDLE {
                return Err(last_error("could not enumerate the suspended worker thread"));
            }
            let mut entry: THREADENTRY32 = unsafe { std::mem::zeroed() };
            entry.dwSize = size_of::<THREADENTRY32>() as u32;
            let mut found = false;
            let mut has_entry = unsafe { Thread32First(snapshot, &mut entry) } != 0;
            while has_entry {
                if entry.th32OwnerProcessID == process_id {
                    let thread = unsafe { OpenThread(THREAD_SUSPEND_RESUME, 0, entry.th32ThreadID) };
                    if thread.is_null() {
                        unsafe { CloseHandle(snapshot) };
                        return Err(last_error("could not open the suspended worker thread"));
                    }
                    let previous = unsafe { ResumeThread(thread) };
                    unsafe { CloseHandle(thread) };
                    if previous == u32::MAX {
                        unsafe { CloseHandle(snapshot) };
                        return Err(last_error("could not resume the worker thread"));
                    }
                    found = true;
                }
                has_entry = unsafe { Thread32Next(snapshot, &mut entry) } != 0;
            }
            unsafe { CloseHandle(snapshot) };
            if !found {
                return Err(AppError::Worker("suspended worker thread was not found".to_owned()));
            }
            Ok(())
        }

        pub fn terminate(&self, exit_code: u32) -> AppResult<()> {
            if unsafe { TerminateJobObject(self.handle, exit_code) } == 0 {
                return Err(last_error("could not terminate the worker Job Object"));
            }
            Ok(())
        }
    }

    impl Drop for KillOnCloseJob {
        fn drop(&mut self) {
            if !self.handle.is_null() {
                unsafe { CloseHandle(self.handle) };
                self.handle = ptr::null_mut();
            }
        }
    }

    fn last_error(message: &str) -> AppError {
        let code = unsafe { GetLastError() };
        AppError::Worker(format!("{message} (Windows error {code})"))
    }
}

#[cfg(windows)]
pub use platform::KillOnCloseJob;

#[cfg(not(windows))]
pub struct KillOnCloseJob;

#[cfg(not(windows))]
impl KillOnCloseJob {
    pub fn create() -> AppResult<Self> {
        Err(AppError::Worker("Windows Job Objects are unavailable".to_owned()))
    }
    pub fn assign(&self, _child: &std::process::Child) -> AppResult<()> { Ok(()) }
    pub fn resume_suspended_process(&self, _process_id: u32) -> AppResult<()> { Ok(()) }
    pub fn terminate(&self, _exit_code: u32) -> AppResult<()> { Ok(()) }
}
