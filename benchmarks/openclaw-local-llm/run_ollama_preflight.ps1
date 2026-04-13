[CmdletBinding()]
param(
    [string]$HostUrl = "http://127.0.0.1:11434",
    [string]$CandidatesPath = "",
    [string]$OutputPath = "",
    [int]$MaxProbeSeconds = 30
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
    $PSNativeCommandUseErrorActionPreference = $false
}

if ([string]::IsNullOrWhiteSpace($CandidatesPath)) {
    $CandidatesPath = Join-Path $PSScriptRoot "candidates.json"
}

if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = Join-Path $PSScriptRoot "results\approved-roster-preflight.json"
}

function Get-JsonFile {
    param([string]$Path)
    Get-Content -Raw $Path | ConvertFrom-Json
}

function Get-CandidateRole {
    param([pscustomobject]$Candidate)

    $explicitRole = ""
    if ($Candidate.PSObject.Properties.Match("role").Count -gt 0) {
        $explicitRole = [string]$Candidate.role
    }

    if ($explicitRole -in @("baseline", "candidate")) {
        return $explicitRole
    }

    if ($Candidate.PSObject.Properties.Match("priority").Count -gt 0) {
        $priority = 0
        if ([int]::TryParse([string]$Candidate.priority, [ref]$priority)) {
            if ($priority -eq 1) {
                return "baseline"
            }
            if ($priority -gt 1) {
                return "candidate"
            }
        }
    }

    return $null
}

function Get-InstalledModelNames {
    param([System.Management.Automation.CommandInfo]$OllamaCommand)

    $lines = & $OllamaCommand.Source list 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $lines) {
        throw "ollama list failed during preflight."
    }

    $installed = @{}
    foreach ($line in @($lines | Select-Object -Skip 1)) {
        $trimmed = [string]$line
        if ([string]::IsNullOrWhiteSpace($trimmed)) {
            continue
        }

        $columns = $trimmed -split "\s{2,}"
        if ($columns.Count -lt 1) {
            continue
        }

        $installed[$columns[0].Trim()] = $true
    }

    return $installed
}

function Test-ModelInstalled {
    param(
        [hashtable]$InstalledModels,
        [string]$Model
    )

    if ($InstalledModels.ContainsKey($Model)) {
        return [pscustomobject]@{
            installed = $true
            status = "installed"
            reason = "model is present in ollama list"
            detail = ""
        }
    }

    return [pscustomobject]@{
        installed = $false
        status = "missing"
        reason = "model is not present in ollama list"
        detail = "model was not available locally"
    }
}

function Invoke-ChatProbe {
    param(
        [string]$Uri,
        [string]$Payload,
        [int]$TimeoutSeconds
    )

    $job = Start-Job -ScriptBlock {
        param($RequestUri, $RequestPayload)
        try {
            $response = Invoke-RestMethod -Method Post -Uri $RequestUri -ContentType "application/json" -Body $RequestPayload
            [pscustomobject]@{
                ok = $true
                response = $response
                error = ""
            }
        } catch {
            [pscustomobject]@{
                ok = $false
                response = $null
                error = $_.Exception.Message
            }
        }
    } -ArgumentList $Uri, $Payload

    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    $completed = Wait-Job -Job $job -Timeout $TimeoutSeconds
    $stopwatch.Stop()

    if (-not $completed) {
        Stop-Job -Job $job | Out-Null
        Remove-Job -Job $job | Out-Null
        return [pscustomobject]@{
            ok = $false
            status = "timeout"
            elapsedMs = [math]::Round($stopwatch.Elapsed.TotalMilliseconds, 1)
            error = "chat probe exceeded ${TimeoutSeconds}s"
            responseText = ""
        }
    }

    $result = Receive-Job -Job $job
    Remove-Job -Job $job | Out-Null

    if (-not $result.ok) {
        return [pscustomobject]@{
            ok = $false
            status = "error"
            elapsedMs = [math]::Round($stopwatch.Elapsed.TotalMilliseconds, 1)
            error = $result.error
            responseText = ""
        }
    }

    $responseText = [string]$result.response.message.content
    if ([string]::IsNullOrWhiteSpace($responseText)) {
        return [pscustomobject]@{
            ok = $false
            status = "empty-response"
            elapsedMs = [math]::Round($stopwatch.Elapsed.TotalMilliseconds, 1)
            error = "chat probe returned empty content"
            responseText = ""
        }
    }

    return [pscustomobject]@{
        ok = $true
        status = "ready"
        elapsedMs = [math]::Round($stopwatch.Elapsed.TotalMilliseconds, 1)
        error = ""
        responseText = $responseText
    }
}

$ollamaCommand = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $ollamaCommand) {
    throw "ollama is required for the roster preflight."
}
$installedModels = Get-InstalledModelNames -OllamaCommand $ollamaCommand

$outputDirectory = Split-Path -Parent $OutputPath
if ($outputDirectory -and -not (Test-Path $outputDirectory)) {
    New-Item -ItemType Directory -Path $outputDirectory | Out-Null
}

$candidates = @((Get-JsonFile -Path $CandidatesPath) | Sort-Object priority)
$results = @()

foreach ($candidate in $candidates) {
    $model = [string]$candidate.model
    $candidateRole = Get-CandidateRole -Candidate $candidate
    $installed = Test-ModelInstalled -InstalledModels $installedModels -Model $model

    if (-not $installed.installed) {
        $results += [pscustomobject]@{
            model = $model
            candidateRole = $candidateRole
            candidatePriority = $candidate.priority
            candidateWhy = $candidate.why
            installed = $false
            availabilityStatus = $installed.status
            probeStatus = "skipped"
            ready = $false
            elapsedMs = 0
            reason = $installed.reason
            detail = $installed.detail
            responseText = ""
        }
        continue
    }

    $payload = @{
        model = $model
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
        model = $model
        candidateRole = $candidateRole
        candidatePriority = $candidate.priority
        candidateWhy = $candidate.why
        installed = $true
        availabilityStatus = $installed.status
        probeStatus = $probe.status
        ready = $probe.ok
        elapsedMs = $probe.elapsedMs
        reason = if ($probe.ok) { "chat probe completed" } else { $probe.error }
        detail = $installed.detail
        responseText = $probe.responseText
    }
}

$summary = [pscustomobject]@{
    host = $HostUrl
    generatedAtUtc = [DateTime]::UtcNow.ToString("o")
    maxProbeSeconds = $MaxProbeSeconds
    candidates = $candidates
    results = $results
    counts = [pscustomobject]@{
        installed = @($results | Where-Object { $_.installed }).Count
        missing = @($results | Where-Object { $_.availabilityStatus -eq "missing" }).Count
        ready = @($results | Where-Object { $_.probeStatus -eq "ready" }).Count
        timeout = @($results | Where-Object { $_.probeStatus -eq "timeout" }).Count
        emptyResponse = @($results | Where-Object { $_.probeStatus -eq "empty-response" }).Count
        error = @($results | Where-Object { $_.probeStatus -eq "error" }).Count
        skipped = @($results | Where-Object { $_.probeStatus -eq "skipped" }).Count
    }
    recommendedStartModel = (
        $results |
        Where-Object { $_.probeStatus -eq "ready" } |
        Sort-Object candidatePriority |
        Select-Object -First 1 -ExpandProperty model
    )
}

$summary | ConvertTo-Json -Depth 8 | Set-Content -Path $OutputPath -Encoding utf8
Write-Output "Wrote roster preflight results to $OutputPath"
