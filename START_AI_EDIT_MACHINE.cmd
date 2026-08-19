@echo off
setlocal
set "APP=%~dp0desktop\src-tauri\target\release\ai-edit-machine-desktop.exe"
if not exist "%APP%" (
  echo The verified AI Edit Machine review build is missing.
  echo Expected: %APP%
  pause
  exit /b 1
)
start "AI Edit Machine" /D "%~dp0desktop\src-tauri\target\release" "%APP%"
endlocal
