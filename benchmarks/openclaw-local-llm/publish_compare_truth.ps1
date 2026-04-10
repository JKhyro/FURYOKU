[CmdletBinding()]
param(
    [string[]]$InputPath = @(),
    [string]$SummaryOutputPath = "",
    [string]$CurrentBaselineOutputPath = "",
    [string]$Title = "Gemma 3 Heretic Q4_K_M vs Q5_K_M Contract Report (2026-04-09)",
    [string]$MachineProfilePath = "",
    [string]$MachineProfileName = "",
    [string]$MachineProfileLabel = "",
    [int]$ProfileSystemMemoryMb = 0,
    [int]$ProfileGpuMemoryMb = 0,
    [switch]$NoOverwrite
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$resultsDirectory = Join-Path $PSScriptRoot "results"

if (-not $InputPath -or $InputPath.Count -eq 0) {
    $InputPath = @(
        (Join-Path $resultsDirectory "2026-04-09-gemma3-heretic-compare-benchmark.json"),
        (Join-Path $resultsDirectory "2026-04-09-gemma3-heretic-compare-response-suite.json"),
        (Join-Path $resultsDirectory "2026-04-09-gemma3-heretic-compare-sexual-boundary.json"),
        (Join-Path $resultsDirectory "2026-04-09-gemma3-heretic-compare-advanced-suite.json")
    )
}

if ([string]::IsNullOrWhiteSpace($SummaryOutputPath)) {
    $SummaryOutputPath = Join-Path $resultsDirectory "2026-04-09-gemma3-heretic-compare-summary.md"
}

if ([string]::IsNullOrWhiteSpace($CurrentBaselineOutputPath)) {
    $CurrentBaselineOutputPath = Join-Path $resultsDirectory "2026-04-09-gemma3-heretic-current-baseline.json"
}

if ([string]::IsNullOrWhiteSpace($MachineProfilePath)) {
    $MachineProfilePath = Join-Path $PSScriptRoot "machine_profiles.json"
}

$contractReport = Join-Path $PSScriptRoot "benchmark_contract_report.py"
if (-not (Test-Path $contractReport)) {
    throw "benchmark_contract_report.py was not found at $contractReport."
}

$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCommand) {
    throw "python is required to publish compare truth surfaces."
}

foreach ($path in $InputPath) {
    if (-not (Test-Path $path)) {
        throw "Compare input file was not found: $path"
    }
}

$summaryDirectory = Split-Path -Parent $SummaryOutputPath
if ($summaryDirectory -and -not (Test-Path $summaryDirectory)) {
    New-Item -ItemType Directory -Path $summaryDirectory | Out-Null
}

$baselineDirectory = Split-Path -Parent $CurrentBaselineOutputPath
if ($baselineDirectory -and -not (Test-Path $baselineDirectory)) {
    New-Item -ItemType Directory -Path $baselineDirectory | Out-Null
}

$contractArgs = @($contractReport)
foreach ($path in $InputPath) {
    $contractArgs += @("--input", $path)
}

if (-not $NoOverwrite) {
    $contractArgs += "--overwrite"
}

$contractArgs += @(
    "--summary-output",
    $SummaryOutputPath,
    "--current-baseline-output",
    $CurrentBaselineOutputPath,
    "--title",
    $Title
)

if (-not [string]::IsNullOrWhiteSpace($MachineProfilePath)) {
    $contractArgs += @("--machine-profile-path", $MachineProfilePath)
}
if (-not [string]::IsNullOrWhiteSpace($MachineProfileName)) {
    $contractArgs += @("--machine-profile-name", $MachineProfileName)
}
if (-not [string]::IsNullOrWhiteSpace($MachineProfileLabel)) {
    $contractArgs += @("--machine-profile-label", $MachineProfileLabel)
}
if ($ProfileSystemMemoryMb -gt 0) {
    $contractArgs += @("--profile-system-memory-mb", $ProfileSystemMemoryMb)
}
if ($ProfileGpuMemoryMb -gt 0) {
    $contractArgs += @("--profile-gpu-memory-mb", $ProfileGpuMemoryMb)
}

& $pythonCommand.Source @contractArgs
if ($LASTEXITCODE -ne 0) {
    throw "Compare truth publish failed."
}

Write-Output "Published compare summary to $SummaryOutputPath"
Write-Output "Published current-baseline manifest to $CurrentBaselineOutputPath"
