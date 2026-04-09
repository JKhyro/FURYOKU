[CmdletBinding()]
param(
    [string]$HostUrl = "http://127.0.0.1:11434",
    [string]$CandidatesPath = "",
    [string]$PromptsPath = "",
    [string]$OutputPath = "",
    [int]$RunsPerPrompt = 1,
    [switch]$SkipWarmup
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($CandidatesPath)) {
    $CandidatesPath = Join-Path $PSScriptRoot "candidates.json"
}

if ([string]::IsNullOrWhiteSpace($PromptsPath)) {
    $PromptsPath = Join-Path $PSScriptRoot "prompts.json"
}

if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = Join-Path $PSScriptRoot "results.json"
}

function Get-JsonFile {
    param([string]$Path)
    $data = Get-Content -Raw $Path | ConvertFrom-Json
    Write-Output $data
}

function Get-OllamaProcessSnapshot {
    $processes = @(Get-Process -Name "ollama" -ErrorAction SilentlyContinue)
    if (-not $processes) {
        return [pscustomobject]@{
            workingSetMb = 0
            privateMemoryMb = 0
        }
    }

    $workingSet = [math]::Round((($processes | Measure-Object WorkingSet64 -Sum).Sum / 1MB), 1)
    $privateMemory = [math]::Round((($processes | Measure-Object PrivateMemorySize64 -Sum).Sum / 1MB), 1)

    return [pscustomobject]@{
        workingSetMb = $workingSet
        privateMemoryMb = $privateMemory
    }
}

function Get-GpuSnapshot {
    $nvidiaSmi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
    if (-not $nvidiaSmi) {
        return $null
    }

    try {
        $rows = & $nvidiaSmi.Source --query-gpu=name,memory.used,memory.total --format=csv,noheader,nounits
    } catch {
        return $null
    }

    $parsed = foreach ($row in $rows) {
        $parts = $row -split ","
        if ($parts.Count -lt 3) {
            continue
        }
        [pscustomobject]@{
            name = $parts[0].Trim()
            memoryUsedMb = [int]($parts[1].Trim())
            memoryTotalMb = [int]($parts[2].Trim())
        }
    }

    return @($parsed)
}

function Invoke-OllamaChat {
    param(
        [string]$Model,
        [pscustomobject]$Prompt
    )

    $payload = @{
        model = $Model
        stream = $false
        messages = @(
            @{ role = "system"; content = $Prompt.system }
            @{ role = "user"; content = $Prompt.user }
        )
        options = @{
            temperature = 0.2
            num_predict = $Prompt.max_tokens
        }
    } | ConvertTo-Json -Depth 6

    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    $response = Invoke-RestMethod -Method Post -Uri "$HostUrl/api/chat" -ContentType "application/json" -Body $payload
    $stopwatch.Stop()

    $evalDurationSeconds = if ($response.eval_duration) { [double]$response.eval_duration / 1000000000.0 } else { 0.0 }
    $tokensPerSecond = if ($response.eval_count -and $evalDurationSeconds -gt 0) {
        [math]::Round(([double]$response.eval_count / $evalDurationSeconds), 2)
    } else {
        0
    }

    return [pscustomobject]@{
        model = $Model
        promptId = $Prompt.id
        task = $Prompt.task
        totalDurationMs = [math]::Round($stopwatch.Elapsed.TotalMilliseconds, 1)
        loadDurationMs = if ($response.load_duration) { [math]::Round(([double]$response.load_duration / 1000000.0), 1) } else { 0 }
        promptEvalCount = if ($response.prompt_eval_count) { [int]$response.prompt_eval_count } else { 0 }
        evalCount = if ($response.eval_count) { [int]$response.eval_count } else { 0 }
        tokensPerSecond = $tokensPerSecond
        responseText = $response.message.content
    }
}

$candidates = @((Get-JsonFile -Path $CandidatesPath) | Sort-Object priority)
$prompts = @(Get-JsonFile -Path $PromptsPath)
$results = @()

foreach ($candidate in $candidates) {
    $model = $candidate.model

    if (-not $SkipWarmup) {
        try {
            Invoke-OllamaChat -Model $model -Prompt $prompts[0] | Out-Null
        } catch {
            $results += [pscustomobject]@{
                model = $model
                promptId = "__warmup__"
                task = "warmup"
                error = $_.Exception.Message
            }
            continue
        }
    }

    foreach ($prompt in $prompts) {
        for ($run = 1; $run -le $RunsPerPrompt; $run++) {
            $cpuBefore = Get-OllamaProcessSnapshot
            $gpuBefore = Get-GpuSnapshot

            try {
                $record = Invoke-OllamaChat -Model $model -Prompt $prompt
                $cpuAfter = Get-OllamaProcessSnapshot
                $gpuAfter = Get-GpuSnapshot

                $record | Add-Member -NotePropertyName run -NotePropertyValue $run
                $record | Add-Member -NotePropertyName processBefore -NotePropertyValue $cpuBefore
                $record | Add-Member -NotePropertyName processAfter -NotePropertyValue $cpuAfter
                $record | Add-Member -NotePropertyName gpuBefore -NotePropertyValue $gpuBefore
                $record | Add-Member -NotePropertyName gpuAfter -NotePropertyValue $gpuAfter
                $results += $record
            } catch {
                $results += [pscustomobject]@{
                    model = $model
                    promptId = $prompt.id
                    task = $prompt.task
                    run = $run
                    error = $_.Exception.Message
                }
            }
        }
    }
}

$summary = [pscustomobject]@{
    host = $HostUrl
    generatedAtUtc = [DateTime]::UtcNow.ToString("o")
    runsPerPrompt = $RunsPerPrompt
    candidates = $candidates
    results = $results
}

$summary | ConvertTo-Json -Depth 8 | Set-Content -Path $OutputPath -Encoding utf8
$contractReport = Join-Path $PSScriptRoot "benchmark_contract_report.py"
if (Test-Path $contractReport) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) {
        throw "python is required to attach benchmark contract checks."
    }

    & $pythonCommand.Source $contractReport --input $OutputPath --overwrite
    if ($LASTEXITCODE -ne 0) {
        throw "Benchmark contract evaluation failed for $OutputPath."
    }
}
Write-Output "Wrote benchmark results to $OutputPath"
