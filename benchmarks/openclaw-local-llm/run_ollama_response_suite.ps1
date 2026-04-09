[CmdletBinding()]
param(
    [string]$HostUrl = "http://127.0.0.1:11434",
    [string]$CandidatesPath = "",
    [string]$PromptsPath = "",
    [string]$OutputPath = "",
    [int]$SampleIntervalMs = 500,
    [int]$MaxRequestSeconds = 120,
    [switch]$ThinkFalse,
    [switch]$SkipWarmup
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($CandidatesPath)) {
    $CandidatesPath = Join-Path $PSScriptRoot "candidates.json"
}

if ([string]::IsNullOrWhiteSpace($PromptsPath)) {
    $PromptsPath = Join-Path $PSScriptRoot "response_suite_prompts.json"
}

if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = Join-Path $PSScriptRoot "results\\response-suite.json"
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
            processCount = 0
            workingSetMb = 0
            privateMemoryMb = 0
        }
    }

    [pscustomobject]@{
        processCount = $processes.Count
        workingSetMb = [math]::Round((($processes | Measure-Object WorkingSet64 -Sum).Sum / 1MB), 1)
        privateMemoryMb = [math]::Round((($processes | Measure-Object PrivateMemorySize64 -Sum).Sum / 1MB), 1)
    }
}

function Get-SystemSnapshot {
    $os = Get-CimInstance Win32_OperatingSystem
    $cpu = @(Get-CimInstance Win32_Processor | Measure-Object LoadPercentage -Average).Average
    $memoryTotalMb = [math]::Round(([double]$os.TotalVisibleMemorySize / 1024), 1)
    $memoryFreeMb = [math]::Round(([double]$os.FreePhysicalMemory / 1024), 1)

    [pscustomobject]@{
        totalCpuPercent = if ($null -ne $cpu) { [math]::Round([double]$cpu, 1) } else { 0 }
        systemMemoryUsedMb = [math]::Round(($memoryTotalMb - $memoryFreeMb), 1)
        systemMemoryFreeMb = $memoryFreeMb
        systemMemoryTotalMb = $memoryTotalMb
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

    @($parsed)
}

function New-ChatPayload {
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
            temperature = 0.1
            num_predict = $Prompt.max_tokens
        }
    }

    if ($ThinkFalse) {
        $payload.think = $false
    }

    $payload | ConvertTo-Json -Depth 6
}

function Invoke-OllamaRequest {
    param(
        [string]$Uri,
        [string]$Payload,
        [int]$SampleIntervalMs,
        [int]$MaxRequestSeconds
    )

    $job = Start-Job -ScriptBlock {
        param($RequestUri, $RequestPayload)
        $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()

        try {
            $response = Invoke-RestMethod -Method Post -Uri $RequestUri -ContentType "application/json" -Body $RequestPayload
            $stopwatch.Stop()

            [pscustomobject]@{
                ok = $true
                elapsedMs = [math]::Round($stopwatch.Elapsed.TotalMilliseconds, 1)
                error = $null
                response = $response
            }
        } catch {
            $stopwatch.Stop()

            [pscustomobject]@{
                ok = $false
                elapsedMs = [math]::Round($stopwatch.Elapsed.TotalMilliseconds, 1)
                error = $_.Exception.Message
                response = $null
            }
        }
    } -ArgumentList $Uri, $Payload

    $samples = @()
    $requestStopwatch = [System.Diagnostics.Stopwatch]::StartNew()

    try {
        while ($true) {
            $jobState = (Get-Job -Id $job.Id).State
            $ollamaSnapshot = Get-OllamaProcessSnapshot
            $systemSnapshot = Get-SystemSnapshot
            $gpuSnapshot = Get-GpuSnapshot

            $samples += [pscustomobject]@{
                elapsedMs = [math]::Round($requestStopwatch.Elapsed.TotalMilliseconds, 1)
                totalCpuPercent = $systemSnapshot.totalCpuPercent
                systemMemoryUsedMb = $systemSnapshot.systemMemoryUsedMb
                systemMemoryFreeMb = $systemSnapshot.systemMemoryFreeMb
                ollamaWorkingSetMb = $ollamaSnapshot.workingSetMb
                ollamaPrivateMemoryMb = $ollamaSnapshot.privateMemoryMb
                gpu = $gpuSnapshot
            }

            if ($jobState -ne "Running" -and $jobState -ne "NotStarted") {
                break
            }

            if ($requestStopwatch.Elapsed.TotalSeconds -ge $MaxRequestSeconds) {
                Stop-Job -Id $job.Id | Out-Null
                return [pscustomobject]@{
                    ok = $false
                    elapsedMs = [math]::Round($requestStopwatch.Elapsed.TotalMilliseconds, 1)
                    error = "Request timed out after $MaxRequestSeconds seconds."
                    samples = $samples
                }
            }

            Start-Sleep -Milliseconds $SampleIntervalMs
        }

        $jobResult = @(Receive-Job -Id $job.Id -Wait)
        if ($jobResult.Count -eq 1) {
            $jobResult = $jobResult[0]
        }
        $requestStopwatch.Stop()

        return [pscustomobject]@{
            ok = [bool]$jobResult.ok
            elapsedMs = if ($jobResult.elapsedMs) { [double]$jobResult.elapsedMs } else { [math]::Round($requestStopwatch.Elapsed.TotalMilliseconds, 1) }
            error = $jobResult.error
            response = $jobResult.response
            samples = $samples
        }
    } finally {
        Remove-Job -Id $job.Id -Force -ErrorAction SilentlyContinue
    }
}

function Get-PeakMetric {
    param(
        [object[]]$Samples,
        [string]$PropertyName
    )

    if (-not $Samples) {
        return 0
    }

    $values = @($Samples | ForEach-Object { $_.$PropertyName } | Where-Object { $null -ne $_ })
    if (-not $values) {
        return 0
    }

    [math]::Round(([double](($values | Measure-Object -Maximum).Maximum)), 1)
}

function Get-PeakGpuMemoryMb {
    param([object[]]$Samples)

    $values = @()
    foreach ($sample in $Samples) {
        foreach ($gpu in @($sample.gpu)) {
            if ($null -ne $gpu.memoryUsedMb) {
                $values += [double]$gpu.memoryUsedMb
            }
        }
    }

    if (-not $values) {
        return 0
    }

    [math]::Round(([double](($values | Measure-Object -Maximum).Maximum)), 1)
}

$resultsDirectory = Split-Path -Parent $OutputPath
if ($resultsDirectory -and -not (Test-Path $resultsDirectory)) {
    New-Item -ItemType Directory -Path $resultsDirectory | Out-Null
}

$candidates = @((Get-JsonFile -Path $CandidatesPath) | Sort-Object priority)
$prompts = @(Get-JsonFile -Path $PromptsPath)
$results = @()

foreach ($candidate in $candidates) {
    $model = $candidate.model

    if (-not $SkipWarmup) {
        try {
            $warmPayload = New-ChatPayload -Model $model -Prompt $prompts[0]
            $warmResult = Invoke-OllamaRequest -Uri "$HostUrl/api/chat" -Payload $warmPayload -SampleIntervalMs $SampleIntervalMs -MaxRequestSeconds $MaxRequestSeconds
            if (-not $warmResult.ok) {
                throw $warmResult.error
            }
        } catch {
            $results += [pscustomobject]@{
                model = $model
                promptId = "__warmup__"
                category = "warmup"
                error = $_.Exception.Message
            }
            continue
        }
    }

    foreach ($prompt in $prompts) {
        $payload = New-ChatPayload -Model $model -Prompt $prompt
        $result = Invoke-OllamaRequest -Uri "$HostUrl/api/chat" -Payload $payload -SampleIntervalMs $SampleIntervalMs -MaxRequestSeconds $MaxRequestSeconds

        if (-not $result.ok) {
            $results += [pscustomobject]@{
                model = $model
                promptId = $prompt.id
                category = $prompt.category
                totalDurationMs = $result.elapsedMs
                peakCpuPercent = Get-PeakMetric -Samples $result.samples -PropertyName "totalCpuPercent"
                peakSystemMemoryUsedMb = Get-PeakMetric -Samples $result.samples -PropertyName "systemMemoryUsedMb"
                peakOllamaPrivateMemoryMb = Get-PeakMetric -Samples $result.samples -PropertyName "ollamaPrivateMemoryMb"
                peakGpuMemoryUsedMb = Get-PeakGpuMemoryMb -Samples $result.samples
                error = $result.error
                samples = $result.samples
            }
            continue
        }

        $response = $result.response
        $evalDurationSeconds = if ($response.eval_duration) { [double]$response.eval_duration / 1000000000.0 } else { 0.0 }
        $tokensPerSecond = if ($response.eval_count -and $evalDurationSeconds -gt 0) {
            [math]::Round(([double]$response.eval_count / $evalDurationSeconds), 2)
        } else {
            0
        }

        $results += [pscustomobject]@{
            model = $model
            promptId = $prompt.id
            category = $prompt.category
            totalDurationMs = $result.elapsedMs
            loadDurationMs = if ($response.load_duration) { [math]::Round(([double]$response.load_duration / 1000000.0), 1) } else { 0 }
            promptEvalCount = if ($response.prompt_eval_count) { [int]$response.prompt_eval_count } else { 0 }
            evalCount = if ($response.eval_count) { [int]$response.eval_count } else { 0 }
            tokensPerSecond = $tokensPerSecond
            peakCpuPercent = Get-PeakMetric -Samples $result.samples -PropertyName "totalCpuPercent"
            peakSystemMemoryUsedMb = Get-PeakMetric -Samples $result.samples -PropertyName "systemMemoryUsedMb"
            peakOllamaPrivateMemoryMb = Get-PeakMetric -Samples $result.samples -PropertyName "ollamaPrivateMemoryMb"
            peakGpuMemoryUsedMb = Get-PeakGpuMemoryMb -Samples $result.samples
            responseText = $response.message.content
            samples = $result.samples
        }
    }
}

$summary = [pscustomobject]@{
    host = $HostUrl
    generatedAtUtc = [DateTime]::UtcNow.ToString("o")
    sampleIntervalMs = $SampleIntervalMs
    maxRequestSeconds = $MaxRequestSeconds
    thinkFalse = [bool]$ThinkFalse
    candidates = $candidates
    prompts = $prompts
    results = $results
}

$summary | ConvertTo-Json -Depth 10 | Set-Content -Path $OutputPath -Encoding utf8
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
Write-Output "Wrote response-suite results to $OutputPath"
