[CmdletBinding()]
param(
    [string]$PythonPath
)

$ErrorActionPreference = 'Stop'

$repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$desktopRoot = [System.IO.Path]::GetFullPath((Join-Path $repositoryRoot 'desktop'))
$workerBuilder = [System.IO.Path]::GetFullPath(
    (Join-Path $repositoryRoot 'scripts\build_worker_bundle.ps1')
)
$verifier = [System.IO.Path]::GetFullPath(
    (Join-Path $repositoryRoot 'scripts\verify_tauri_release_worker.ps1')
)
$cargoHome = [System.IO.Path]::GetFullPath((Join-Path $repositoryRoot '.tools\cargo'))
$rustupHome = [System.IO.Path]::GetFullPath((Join-Path $repositoryRoot '.tools\rustup'))
$cargoExecutable = Join-Path $cargoHome 'bin\cargo.exe'
if (-not (Test-Path -LiteralPath $cargoExecutable -PathType Leaf)) {
    throw "The pinned local Cargo executable is missing: $cargoExecutable"
}
$env:CARGO_HOME = $cargoHome
$env:RUSTUP_HOME = $rustupHome
$env:PATH = "$(Join-Path $cargoHome 'bin');$env:PATH"

# The worker is source code compiled into a one-folder executable bundle. A
# Tauri rebuild alone only copies whatever bundle is already present, which can
# silently ship stale Python after a provider/domain fix. Rebuild and protocol-
# verify the worker before every optimized desktop release.
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $workerBuilder
if ($LASTEXITCODE -ne 0) {
    throw 'The packaged M1 worker build failed.'
}

Push-Location $desktopRoot
try {
    & npm.cmd run tauri:build -- --no-bundle
    if ($LASTEXITCODE -ne 0) {
        throw 'The optimized Tauri application build failed.'
    }
}
finally {
    Pop-Location
}

$arguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $verifier)
if (-not [string]::IsNullOrWhiteSpace($PythonPath)) {
    $arguments += @('-PythonPath', $PythonPath)
}
& powershell.exe @arguments
if ($LASTEXITCODE -ne 0) {
    throw 'The optimized Tauri application failed its built-worker gate.'
}

Write-Output 'Built and verified the optimized M1 Tauri application.'
