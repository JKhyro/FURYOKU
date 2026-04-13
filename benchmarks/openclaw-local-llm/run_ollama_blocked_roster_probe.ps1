[CmdletBinding()]
param(
    [string]$HostUrl = "http://127.0.0.1:11434",
    [string]$PreflightPath = "",
    [string]$OutputPath = "",
    [int]$MaxProbeSeconds = 60
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Net.Http

function Get-JsonFile {
    param([string]$Path)
    Get-Content -Raw $Path | ConvertFrom-Json
}

function Resolve-DefaultPreflightPath {
    param([string]$ResultsDirectory)

    $latest = Get-ChildItem -Path $ResultsDirectory -Filter "*approved-roster-preflight*.json" -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($latest) {
        return $latest.FullName
    }

    $fallback = Join-Path $ResultsDirectory "approved-roster-preflight.json"
    if (Test-Path $fallback) {
        return $fallback
    }

    throw "No approved-roster preflight artifact was found under $ResultsDirectory."
}

function Invoke-ChatProbe {
    param(
        [string]$Uri,
        [string]$Payload,
        [int]$TimeoutSeconds
    )

    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    $client = [System.Net.Http.HttpClient]::new()
    $client.Timeout = [TimeSpan]::FromSeconds($TimeoutSeconds)
    $content = $null
    try {
        $content = [System.Net.Http.StringContent]::new($Payload, [System.Text.Encoding]::UTF8, "application/json")
        $httpResponse = $client.PostAsync($Uri, $content).GetAwaiter().GetResult()
        $responseBody = $httpResponse.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        $stopwatch.Stop()

        if (-not $httpResponse.IsSuccessStatusCode) {
            return [pscustomobject]@{
                ok = $false
                status = "error"
                elapsedMs = [math]::Round($stopwatch.Elapsed.TotalMilliseconds, 1)
                error = "HTTP $([int]$httpResponse.StatusCode): $responseBody"
                responseText = ""
                done = $false
                doneReason = ""
                totalDuration = 0
                loadDuration = 0
                promptEvalCount = 0
                evalCount = 0
                evalDuration = 0
            }
        }

        $response = $responseBody | ConvertFrom-Json
    } catch [System.Threading.Tasks.TaskCanceledException] {
        $stopwatch.Stop()
        return [pscustomobject]@{
            ok = $false
            status = "timeout"
            elapsedMs = [math]::Round($stopwatch.Elapsed.TotalMilliseconds, 1)
            error = "chat probe exceeded ${TimeoutSeconds}s"
            responseText = ""
            done = $false
            doneReason = ""
            totalDuration = 0
            loadDuration = 0
            promptEvalCount = 0
            evalCount = 0
            evalDuration = 0
        }
    } catch {
        $stopwatch.Stop()
        return [pscustomobject]@{
            ok = $false
            status = "error"
            elapsedMs = [math]::Round($stopwatch.Elapsed.TotalMilliseconds, 1)
            error = $_.Exception.Message
            responseText = ""
            done = $false
            doneReason = ""
            totalDuration = 0
            loadDuration = 0
            promptEvalCount = 0
            evalCount = 0
            evalDuration = 0
        }
    } finally {
        if ($content) {
            $content.Dispose()
        }
        $client.Dispose()
    }

    $responseText = [string]$response.message.content
    $doneReason = ""
    if ($response.PSObject.Properties.Match("done_reason").Count -gt 0) {
        $doneReason = [string]$response.done_reason
    }

    $record = [pscustomobject]@{
        ok = $true
        status = "ready"
        elapsedMs = [math]::Round($stopwatch.Elapsed.TotalMilliseconds, 1)
        error = ""
        responseText = $responseText
        done = [bool]$response.done
        doneReason = $doneReason
        totalDuration = [long]$response.total_duration
        loadDuration = [long]$response.load_duration
        promptEvalCount = [int]$response.prompt_eval_count
        evalCount = [int]$response.eval_count
        evalDuration = [long]$response.eval_duration
    }

    if ([string]::IsNullOrWhiteSpace($responseText)) {
        $record.ok = $false
        $record.status = "empty-response"
        $record.error = "chat probe returned empty content"
    }

    return $record
}

function Get-ProbeDecision {
    param([pscustomobject]$Probe)

    switch ($Probe.status) {
        "ready" { return "promote-to-full-benchmark" }
        "empty-response" { return "exclude-until-empty-response-is-resolved" }
        "timeout" { return "exclude-on-current-machine-budget" }
        "error" { return "exclude-until-runtime-error-is-resolved" }
        default { return "exclude-pending-manual-review" }
    }
}

$resultsDirectory = Join-Path $PSScriptRoot "results"
if ([string]::IsNullOrWhiteSpace($PreflightPath)) {
    $PreflightPath = Resolve-DefaultPreflightPath -ResultsDirectory $resultsDirectory
}

if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = Join-Path $resultsDirectory "approved-blocked-roster-probe.json"
}

if (-not (Test-Path $PreflightPath)) {
    throw "Preflight artifact was not found: $PreflightPath"
}

$outputDirectory = Split-Path -Parent $OutputPath
if ($outputDirectory -and -not (Test-Path $outputDirectory)) {
    New-Item -ItemType Directory -Path $outputDirectory | Out-Null
}

$preflight = Get-JsonFile -Path $PreflightPath
$blocked = @(
    $preflight.results | Where-Object {
        $_.availabilityStatus -eq "missing" -or $_.probeStatus -in @("timeout", "empty-response", "error")
    } | Sort-Object candidatePriority
)

$results = @()
foreach ($entry in $blocked) {
    if ($entry.availabilityStatus -eq "missing") {
        $results += [pscustomobject]@{
            model = $entry.model
            candidateRole = $entry.candidateRole
            candidatePriority = $entry.candidatePriority
            candidateWhy = $entry.candidateWhy
            initialAvailabilityStatus = $entry.availabilityStatus
            initialProbeStatus = $entry.probeStatus
            initialElapsedMs = $entry.elapsedMs
            secondStageProbeStatus = "missing"
            secondStageElapsedMs = 0
            machineDecision = "exclude-until-installed"
            reason = "model is not present in ollama list"
            responseText = ""
            responseMetadata = [pscustomobject]@{
                done = $false
                doneReason = ""
                totalDuration = 0
                loadDuration = 0
                promptEvalCount = 0
                evalCount = 0
                evalDuration = 0
            }
        }
        continue
    }

    $payload = @{
        model = $entry.model
        stream = $false
        messages = @(
            @{ role = "system"; content = "You are concise." }
            @{ role = "user"; content = "Reply with exactly the word ok." }
        )
        options = @{
            temperature = 0
            num_predict = 8
        }
    } | ConvertTo-Json -Depth 6

    $probe = Invoke-ChatProbe -Uri "$HostUrl/api/chat" -Payload $payload -TimeoutSeconds $MaxProbeSeconds
    $results += [pscustomobject]@{
        model = $entry.model
        candidateRole = $entry.candidateRole
        candidatePriority = $entry.candidatePriority
        candidateWhy = $entry.candidateWhy
        initialAvailabilityStatus = $entry.availabilityStatus
        initialProbeStatus = $entry.probeStatus
        initialElapsedMs = $entry.elapsedMs
        secondStageProbeStatus = $probe.status
        secondStageElapsedMs = $probe.elapsedMs
        machineDecision = Get-ProbeDecision -Probe $probe
        reason = if ($probe.ok) { "second-stage blocked probe completed" } else { $probe.error }
        responseText = $probe.responseText
        responseMetadata = [pscustomobject]@{
            done = $probe.done
            doneReason = $probe.doneReason
            totalDuration = $probe.totalDuration
            loadDuration = $probe.loadDuration
            promptEvalCount = $probe.promptEvalCount
            evalCount = $probe.evalCount
            evalDuration = $probe.evalDuration
        }
    }
}

$summary = [pscustomobject]@{
    host = $HostUrl
    generatedAtUtc = [DateTime]::UtcNow.ToString("o")
    maxProbeSeconds = $MaxProbeSeconds
    preflightPath = $PreflightPath
    results = $results
    counts = [pscustomobject]@{
        total = @($results).Count
        missing = @($results | Where-Object { $_.secondStageProbeStatus -eq "missing" }).Count
        ready = @($results | Where-Object { $_.secondStageProbeStatus -eq "ready" }).Count
        timeout = @($results | Where-Object { $_.secondStageProbeStatus -eq "timeout" }).Count
        emptyResponse = @($results | Where-Object { $_.secondStageProbeStatus -eq "empty-response" }).Count
        error = @($results | Where-Object { $_.secondStageProbeStatus -eq "error" }).Count
    }
    recommendedDecisions = [pscustomobject]@{
        promoteToFullBenchmark = @($results | Where-Object { $_.machineDecision -eq "promote-to-full-benchmark" } | Select-Object -ExpandProperty model)
        excludeUntilInstalled = @($results | Where-Object { $_.machineDecision -eq "exclude-until-installed" } | Select-Object -ExpandProperty model)
        excludeUntilEmptyResponseIsResolved = @($results | Where-Object { $_.machineDecision -eq "exclude-until-empty-response-is-resolved" } | Select-Object -ExpandProperty model)
        excludeOnCurrentMachineBudget = @($results | Where-Object { $_.machineDecision -eq "exclude-on-current-machine-budget" } | Select-Object -ExpandProperty model)
        excludeUntilRuntimeErrorIsResolved = @($results | Where-Object { $_.machineDecision -eq "exclude-until-runtime-error-is-resolved" } | Select-Object -ExpandProperty model)
        manualReview = @($results | Where-Object { $_.machineDecision -eq "exclude-pending-manual-review" } | Select-Object -ExpandProperty model)
    }
}

$summary | ConvertTo-Json -Depth 8 | Set-Content -Path $OutputPath -Encoding utf8
Write-Output "Wrote blocked-roster probe results to $OutputPath"
