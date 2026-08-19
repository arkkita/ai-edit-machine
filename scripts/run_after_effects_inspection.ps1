[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string] $AfterFxPath,

    [Parameter(Mandatory = $true)]
    [string] $AepInput,

    [Parameter(Mandatory = $true)]
    [string] $ReportOutput,

    [Parameter(Mandatory = $true)]
    [switch] $ConfirmedAfterEffectsClosed,

    [ValidateRange(1, 900)]
    [int] $ReportTimeoutSeconds = 120
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not $ConfirmedAfterEffectsClosed) {
    throw 'Explicit confirmation that After Effects is closed is required.'
}
if (Get-Process -Name 'AfterFX' -ErrorAction SilentlyContinue) {
    throw 'After Effects is running. Close it before inspection.'
}

$repositoryRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$analysisRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $repositoryRoot 'artifacts\reference-analysis')
)
$jsxPath = (Resolve-Path -LiteralPath (
    Join-Path $PSScriptRoot 'inspect_after_effects_project.jsx'
)).Path
$afterFx = (Resolve-Path -LiteralPath $AfterFxPath).Path
$source = (Resolve-Path -LiteralPath $AepInput).Path
$report = [System.IO.Path]::GetFullPath($ReportOutput)
$rootPrefix = $analysisRoot.TrimEnd('\') + '\'

if (-not $report.StartsWith(
    $rootPrefix,
    [System.StringComparison]::OrdinalIgnoreCase
)) {
    throw 'Report output must be inside artifacts\reference-analysis.'
}
if ($report.Equals($source, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'AEP input and report output must not collide.'
}
$reportDirectory = Split-Path -LiteralPath $report -Parent
if (-not (Test-Path -LiteralPath $reportDirectory -PathType Container)) {
    throw 'Report output directory does not exist.'
}
$provenancePath = $report + '.provenance.json'
if (
    (Test-Path -LiteralPath $report) -or
    (Test-Path -LiteralPath $provenancePath)
) {
    throw 'Report or provenance target already exists; inspection uses create-new output.'
}

$runId = [Guid]::NewGuid().ToString('N')
$stagingDirectory = Join-Path $analysisRoot ('.ae-inspection-' + $runId + '.unvalidated')
New-Item -ItemType Directory -Path $stagingDirectory -ErrorAction Stop | Out-Null
$stagingReport = Join-Path $stagingDirectory 'inspection-report.json'

$sourceItemBefore = Get-Item -LiteralPath $source
$sourceHashBefore = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
$previousInput = $env:AI_EDIT_AEP_INPUT
$previousReport = $env:AI_EDIT_AEP_REPORT
$previousConfirmation = $env:AI_EDIT_AE_INSPECTION_CONFIRMED

try {
    $env:AI_EDIT_AEP_INPUT = $source
    $env:AI_EDIT_AEP_REPORT = $stagingReport
    $env:AI_EDIT_AE_INSPECTION_CONFIRMED = 'true'
    $quotedJsxPath = '"' + $jsxPath + '"'
    Start-Process -FilePath $afterFx -ArgumentList @('-r', $quotedJsxPath)
    $deadline = [DateTime]::UtcNow.AddSeconds($ReportTimeoutSeconds)
    while (-not (Test-Path -LiteralPath $stagingReport -PathType Leaf)) {
        if ([DateTime]::UtcNow -ge $deadline) {
            throw (
                'Timed out waiting for the quarantined After Effects inspection report. ' +
                'The wrapper did not stop After Effects; close it manually if it is still running.'
            )
        }
        Start-Sleep -Milliseconds 250
    }
}
finally {
    $env:AI_EDIT_AEP_INPUT = $previousInput
    $env:AI_EDIT_AEP_REPORT = $previousReport
    $env:AI_EDIT_AE_INSPECTION_CONFIRMED = $previousConfirmation
}

$sourceItemAfter = Get-Item -LiteralPath $source
$sourceHashAfter = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
if (
    $sourceHashAfter -ne $sourceHashBefore -or
    $sourceItemAfter.Length -ne $sourceItemBefore.Length -or
    $sourceItemAfter.LastWriteTimeUtc -ne $sourceItemBefore.LastWriteTimeUtc
) {
    throw 'AEP source changed during inspection; discard the report.'
}
$parsedReport = Get-Content -LiteralPath $stagingReport -Raw -Encoding UTF8 | ConvertFrom-Json
if ($null -ne $parsedReport.error) {
    throw ('After Effects inspection failed: ' + [string] $parsedReport.error)
}

$reportHash = (
    Get-FileHash -LiteralPath $stagingReport -Algorithm SHA256
).Hash.ToLowerInvariant()
$provenance = [ordered]@{
    provenance_version = '1.1.0'
    validation_status = 'PASSED'
    source_name = [System.IO.Path]::GetFileName($source)
    source_sha256_before = $sourceHashBefore
    source_sha256_after = $sourceHashAfter
    source_size_bytes = $sourceItemAfter.Length
    source_last_write_time_utc_before = $sourceItemBefore.LastWriteTimeUtc.ToString('o')
    source_last_write_time_utc_after = $sourceItemAfter.LastWriteTimeUtc.ToString('o')
    report_name = [System.IO.Path]::GetFileName($report)
    report_sha256 = $reportHash
}
$provenanceTemporary = Join-Path (
    $reportDirectory
) ('.' + [System.IO.Path]::GetFileName($provenancePath) + '.' + $runId + '.partial')
$utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)
$provenanceJson = $provenance | ConvertTo-Json -Depth 5
New-Item -ItemType File -Path $provenanceTemporary -ErrorAction Stop | Out-Null
[System.IO.File]::WriteAllText($provenanceTemporary, $provenanceJson, $utf8WithoutBom)
$verifiedProvenance = Get-Content -LiteralPath $provenanceTemporary -Raw -Encoding UTF8 |
    ConvertFrom-Json
if (
    $verifiedProvenance.validation_status -ne 'PASSED' -or
    $verifiedProvenance.report_sha256 -ne $reportHash -or
    $verifiedProvenance.source_sha256_before -ne $sourceHashBefore -or
    $verifiedProvenance.source_sha256_after -ne $sourceHashAfter
) {
    throw 'Temporary After Effects provenance verification failed.'
}
if ((Get-FileHash -LiteralPath $stagingReport -Algorithm SHA256).Hash.ToLowerInvariant() -ne $reportHash) {
    throw 'Quarantined After Effects report changed before publication.'
}

# Publish provenance first. A report at its final path is consumable only when this
# matching sidecar already exists; failure paths leave only .unvalidated/.partial data.
[System.IO.File]::Move($provenanceTemporary, $provenancePath)
[System.IO.File]::Move($stagingReport, $report)
Remove-Item -LiteralPath $stagingDirectory -ErrorAction SilentlyContinue
Write-Output $report
