[CmdletBinding()]
param(
    [string]$ReleaseRoot,
    [string]$PythonPath
)

$ErrorActionPreference = 'Stop'

$repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$targetRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $repositoryRoot 'desktop\src-tauri\target')
)

if ([string]::IsNullOrWhiteSpace($ReleaseRoot)) {
    $ReleaseRoot = Join-Path $targetRoot 'release'
}
$releaseRootFull = [System.IO.Path]::GetFullPath($ReleaseRoot)
$targetPrefix = $targetRoot.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
if (-not $releaseRootFull.StartsWith($targetPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Release root must remain under the Tauri target directory: $targetRoot"
}

if ([string]::IsNullOrWhiteSpace($PythonPath)) {
    $PythonPath = Join-Path $repositoryRoot '.venv\Scripts\python.exe'
}
$pythonFull = [System.IO.Path]::GetFullPath($PythonPath)
$sourceBundle = [System.IO.Path]::GetFullPath(
    (Join-Path $repositoryRoot 'desktop\src-tauri\resources\worker\windows-x86_64')
)
$builtBundle = [System.IO.Path]::GetFullPath(
    (Join-Path $releaseRootFull 'worker\windows-x86_64')
)
$releaseExecutable = [System.IO.Path]::GetFullPath(
    (Join-Path $releaseRootFull 'ai-edit-machine-desktop.exe')
)
$verifier = [System.IO.Path]::GetFullPath(
    (Join-Path $repositoryRoot 'scripts\verify_worker_bundle.py')
)

foreach ($requiredPath in @(
    $pythonFull,
    $sourceBundle,
    $builtBundle,
    $releaseExecutable,
    $verifier
)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Required release-verification path is missing: $requiredPath"
    }
}

& $pythonFull $verifier $builtBundle --reference-bundle $sourceBundle
if ($LASTEXITCODE -ne 0) {
    throw 'The Tauri release worker layout/integrity/protocol gate failed.'
}

Write-Output "Verified Tauri release worker resource: $builtBundle"

