[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$workerParent = [System.IO.Path]::GetFullPath((Join-Path $repositoryRoot 'desktop\src-tauri\resources\worker'))
$workerTarget = [System.IO.Path]::GetFullPath((Join-Path $workerParent 'windows-x86_64'))
$buildRoot = [System.IO.Path]::GetFullPath((Join-Path $repositoryRoot 'build\m1-worker'))
$distRoot = Join-Path $buildRoot 'dist'
$workRoot = Join-Path $buildRoot 'work'
$specRoot = Join-Path $buildRoot 'spec'
$uvPath = Join-Path $repositoryRoot '.tools\uv-py\bin\uv.exe'
$pythonPath = Join-Path $repositoryRoot '.tools\python\cpython-3.12.14-windows-x86_64-none\python.exe'
$venvPython = Join-Path $repositoryRoot '.venv\Scripts\python.exe'
$pyInstaller = Join-Path $repositoryRoot '.venv\Scripts\pyinstaller.exe'

function Assert-ChildPath {
    param(
        [Parameter(Mandatory = $true)][string]$Candidate,
        [Parameter(Mandatory = $true)][string]$Parent
    )
    $candidateFull = [System.IO.Path]::GetFullPath($Candidate)
    $parentFull = [System.IO.Path]::GetFullPath($Parent).TrimEnd('\') + '\'
    if (-not $candidateFull.StartsWith($parentFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing an out-of-scope worker path: $candidateFull"
    }
}

function Assert-PlainPathChain {
    param(
        [Parameter(Mandatory = $true)][string]$Candidate,
        [Parameter(Mandatory = $true)][string]$Root
    )
    $rootItem = Get-Item -LiteralPath $Root -Force
    if (($rootItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Refusing a reparse-point workspace root: $($rootItem.FullName)"
    }
    $rootFull = [System.IO.Path]::GetFullPath($rootItem.FullName).TrimEnd('\')
    $candidateFull = [System.IO.Path]::GetFullPath($Candidate)
    Assert-ChildPath -Candidate $candidateFull -Parent $rootFull
    $relative = $candidateFull.Substring($rootFull.Length).TrimStart('\')
    $current = $rootFull
    foreach ($segment in $relative.Split('\', [System.StringSplitOptions]::RemoveEmptyEntries)) {
        $current = Join-Path $current $segment
        if (-not (Test-Path -LiteralPath $current)) { break }
        $item = Get-Item -LiteralPath $current -Force
        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Refusing a reparse point in a worker build/publish path: $($item.FullName)"
        }
        if ([System.IO.Path]::GetFullPath($item.FullName) -ne [System.IO.Path]::GetFullPath($current)) {
            throw "Worker build/publish path did not resolve exactly: $current"
        }
    }
}

function Assert-NoReparseTree {
    param([Parameter(Mandatory = $true)][string]$Root)
    if (-not (Test-Path -LiteralPath $Root)) { return }
    $rootItem = Get-Item -LiteralPath $Root -Force
    if (($rootItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Refusing a reparse-point worker tree: $($rootItem.FullName)"
    }
    foreach ($item in Get-ChildItem -LiteralPath $Root -Recurse -Force) {
        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Refusing a reparse point inside a worker tree: $($item.FullName)"
        }
    }
}

if (-not [System.Runtime.InteropServices.RuntimeInformation]::IsOSPlatform(
    [System.Runtime.InteropServices.OSPlatform]::Windows
)) {
    throw 'The M1 worker bundle must be built on Windows.'
}
if ([System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString() -ne 'X64') {
    throw 'The M1 worker bundle must be built on Windows x64.'
}
foreach ($path in @($uvPath, $pythonPath)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required pinned build tool is missing: $path"
    }
}

Assert-ChildPath -Candidate $buildRoot -Parent $repositoryRoot
Assert-ChildPath -Candidate $workerTarget -Parent $workerParent
Assert-PlainPathChain -Candidate $buildRoot -Root $repositoryRoot
Assert-PlainPathChain -Candidate $workerParent -Root $repositoryRoot
if (Test-Path -LiteralPath $buildRoot) {
    Assert-NoReparseTree -Root $buildRoot
    Remove-Item -LiteralPath $buildRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $distRoot, $workRoot, $specRoot -Force | Out-Null

$env:UV_CACHE_DIR = Join-Path $repositoryRoot '.tools\uv-cache'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $repositoryRoot '.tools\python'
& $uvPath sync --frozen --group worker-build --python $pythonPath
if ($LASTEXITCODE -ne 0) { throw 'The frozen worker build environment could not be synchronized.' }
foreach ($path in @($venvPython, $pyInstaller)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Locked worker build executable is missing: $path"
    }
}
$WorkerContractValues = @(& $venvPython -c 'from ai_edit_machine.worker_protocol import PROTOCOL_VERSION, WORKER_TARGET, WORKER_VERSION; print(PROTOCOL_VERSION); print(WORKER_TARGET); print(WORKER_VERSION)')
if ($LASTEXITCODE -ne 0 -or $WorkerContractValues.Count -ne 3) {
    throw 'The frozen worker contract could not be read from the packaged source.'
}
$WorkerContractJson = [ordered]@{
    protocolVersion = [string]$WorkerContractValues[0]
    target = [string]$WorkerContractValues[1]
    workerVersion = [string]$WorkerContractValues[2]
} | ConvertTo-Json -Compress
$WorkerContract = $WorkerContractJson | ConvertFrom-Json
$WorkerVersion = [string]$WorkerContract.workerVersion
if (
    $WorkerContract.PSObject.Properties.Name.Count -ne 3 -or
    (@($WorkerContract.PSObject.Properties.Name | Sort-Object) -join ',') -ne 'protocolVersion,target,workerVersion' -or
    $WorkerContract.protocolVersion -ne '1.0.0' -or
    $WorkerContract.target -ne 'windows-x86_64' -or
    $WorkerVersion -notmatch '^[0-9A-Za-z][0-9A-Za-z._-]{0,63}$'
) {
    throw 'The frozen worker contract has unsupported fields, protocol, target, or version.'
}

& $pyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --console `
    --noupx `
    --name 'ai-edit-machine-worker' `
    --paths (Join-Path $repositoryRoot 'src') `
    --distpath $distRoot `
    --workpath $workRoot `
    --specpath $specRoot `
    (Join-Path $repositoryRoot 'scripts\worker_entrypoint.py')
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller did not produce the M1 worker bundle.' }

$builtBundle = Join-Path $distRoot 'ai-edit-machine-worker'
if (-not (Test-Path -LiteralPath $builtBundle -PathType Container)) {
    throw 'PyInstaller output directory is missing.'
}
$contractPath = Join-Path $builtBundle 'worker-contract.json'
[System.IO.File]::WriteAllText(
    $contractPath,
    [string]$WorkerContractJson,
    [System.Text.UTF8Encoding]::new($false)
)
Assert-NoReparseTree -Root $builtBundle
& $venvPython (Join-Path $repositoryRoot 'scripts\verify_worker_bundle.py') $builtBundle
if ($LASTEXITCODE -ne 0) { throw 'The packaged M1 worker failed its integrity/protocol smoke test.' }

New-Item -ItemType Directory -Path $workerParent -Force | Out-Null
$publishPath = Join-Path $workerParent ('.windows-x86_64-publish-' + [guid]::NewGuid().ToString('N'))
$previousPath = Join-Path $workerParent ('.windows-x86_64-previous-' + [guid]::NewGuid().ToString('N'))
Assert-ChildPath -Candidate $publishPath -Parent $workerParent
Assert-ChildPath -Candidate $previousPath -Parent $workerParent
Assert-PlainPathChain -Candidate $publishPath -Root $repositoryRoot
Assert-PlainPathChain -Candidate $previousPath -Root $repositoryRoot
Move-Item -LiteralPath $builtBundle -Destination $publishPath
$movedPrevious = $false
try {
    if (Test-Path -LiteralPath $workerTarget) {
        Assert-NoReparseTree -Root $workerTarget
        Move-Item -LiteralPath $workerTarget -Destination $previousPath
        $movedPrevious = $true
    }
    Move-Item -LiteralPath $publishPath -Destination $workerTarget
} catch {
    if ($movedPrevious -and -not (Test-Path -LiteralPath $workerTarget)) {
        Move-Item -LiteralPath $previousPath -Destination $workerTarget
    }
    throw
}
if ($movedPrevious -and (Test-Path -LiteralPath $previousPath)) {
    Assert-NoReparseTree -Root $previousPath
    Remove-Item -LiteralPath $previousPath -Recurse -Force
}

Write-Output "Published verified M1 worker bundle to $workerTarget"
