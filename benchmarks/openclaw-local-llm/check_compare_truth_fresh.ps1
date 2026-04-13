[CmdletBinding()]
param(
    [string[]]$InputPath = @(),
    [string]$SummaryOutputPath = "",
    [string]$CurrentBaselineOutputPath = "",
    [string]$Title = "Approved Ready Gemma Subset Contract Report (2026-04-13)",
    [string]$MachineProfilePath = "",
    [string]$MachineProfileName = "",
    [string]$MachineProfileLabel = "",
    [int]$ProfileSystemMemoryMb = 0,
    [int]$ProfileGpuMemoryMb = 0
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$resultsDirectory = Join-Path $PSScriptRoot "results"

if (-not $InputPath -or $InputPath.Count -eq 0) {
    $InputPath = @(
        (Join-Path $resultsDirectory "2026-04-13-approved-ready-compare-benchmark.json"),
        (Join-Path $resultsDirectory "2026-04-13-approved-ready-compare-response-suite.json"),
        (Join-Path $resultsDirectory "2026-04-13-approved-ready-compare-sexual-boundary.json"),
        (Join-Path $resultsDirectory "2026-04-13-approved-ready-compare-advanced-suite.json")
    )
}

if ([string]::IsNullOrWhiteSpace($SummaryOutputPath)) {
    $SummaryOutputPath = Join-Path $resultsDirectory "2026-04-13-approved-ready-compare-summary.md"
}

if ([string]::IsNullOrWhiteSpace($CurrentBaselineOutputPath)) {
    $CurrentBaselineOutputPath = Join-Path $resultsDirectory "2026-04-13-approved-ready-current-baseline.json"
}

if ([string]::IsNullOrWhiteSpace($MachineProfilePath)) {
    $MachineProfilePath = Join-Path $PSScriptRoot "machine_profiles.json"
}

$publishScript = Join-Path $PSScriptRoot "publish_compare_truth.ps1"
if (-not (Test-Path $publishScript)) {
    throw "publish_compare_truth.ps1 was not found at $publishScript."
}

foreach ($path in @($SummaryOutputPath, $CurrentBaselineOutputPath)) {
    if (-not (Test-Path $path)) {
        throw "Expected compare truth output was not found: $path"
    }
}

function Normalize-ManifestForFreshnessCheck {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Manifest,
        [string]$CanonicalSummaryOutput = ""
    )

    $normalized = $Manifest | ConvertTo-Json -Depth 100 | ConvertFrom-Json
    if ($normalized.PSObject.Properties.Name -contains "generatedAtUtc") {
        $normalized.PSObject.Properties.Remove("generatedAtUtc")
    }
    if (
        -not [string]::IsNullOrWhiteSpace($CanonicalSummaryOutput) -and
        $normalized.PSObject.Properties.Name -contains "summaryOutput"
    ) {
        $normalized.summaryOutput = $CanonicalSummaryOutput
    }
    return $normalized
}

$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("furyoku-compare-truth-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tempRoot | Out-Null

try {
    $generatedSummaryPath = Join-Path $tempRoot "compare-summary.md"
    $generatedManifestPath = Join-Path $tempRoot "current-baseline.json"

    $publishParams = @{
        InputPath = $InputPath
        SummaryOutputPath = $generatedSummaryPath
        CurrentBaselineOutputPath = $generatedManifestPath
        Title = $Title
        MachineProfilePath = $MachineProfilePath
        NoOverwrite = $true
    }
    if (-not [string]::IsNullOrWhiteSpace($MachineProfileName)) {
        $publishParams["MachineProfileName"] = $MachineProfileName
    }
    if (-not [string]::IsNullOrWhiteSpace($MachineProfileLabel)) {
        $publishParams["MachineProfileLabel"] = $MachineProfileLabel
    }
    if ($ProfileSystemMemoryMb -gt 0) {
        $publishParams["ProfileSystemMemoryMb"] = $ProfileSystemMemoryMb
    }
    if ($ProfileGpuMemoryMb -gt 0) {
        $publishParams["ProfileGpuMemoryMb"] = $ProfileGpuMemoryMb
    }

    & $publishScript @publishParams | Out-Null

    $failures = @()
    $expectedSummary = Get-Content -Path $SummaryOutputPath -Raw
    $generatedSummary = Get-Content -Path $generatedSummaryPath -Raw
    if ($expectedSummary -ne $generatedSummary) {
        $failures += "summary output differs from regenerated helper output"
    }

    $expectedManifest = Get-Content -Path $CurrentBaselineOutputPath -Raw | ConvertFrom-Json
    $generatedManifest = Get-Content -Path $generatedManifestPath -Raw | ConvertFrom-Json
    $canonicalSummaryOutput = ""
    if ($expectedManifest.PSObject.Properties.Name -contains "summaryOutput") {
        $canonicalSummaryOutput = $expectedManifest.summaryOutput
    }
    $expectedManifestJson = Normalize-ManifestForFreshnessCheck -Manifest $expectedManifest |
        ConvertTo-Json -Depth 100
    $generatedManifestJson = Normalize-ManifestForFreshnessCheck -Manifest $generatedManifest -CanonicalSummaryOutput $canonicalSummaryOutput |
        ConvertTo-Json -Depth 100
    if ($expectedManifestJson -ne $generatedManifestJson) {
        $failures += "current-baseline manifest differs from regenerated helper output"
    }

    if ($failures.Count -gt 0) {
        throw "Compare truth outputs are stale: $($failures -join '; '). Run publish_compare_truth.ps1 and commit the refreshed outputs."
    }

    Write-Output "Compare truth outputs are fresh: $SummaryOutputPath"
    Write-Output "Compare truth manifest is fresh: $CurrentBaselineOutputPath"
}
finally {
    if (Test-Path $tempRoot) {
        [System.IO.Directory]::Delete($tempRoot, $true)
    }
}
