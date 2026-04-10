# OpenClaw Local LLM Benchmark

This lane evaluates small local models for basic OpenClaw work such as concise replies, rewrites, summaries, and simple routing/classification prompts.

## Goal

Select a local model that fits a 32 GB RAM / 4 GB VRAM machine profile with the best balance of:

- latency
- memory pressure
- context length
- answer quality on basic assistant tasks
- OpenClaw/Ollama integration fit

## Historical 2026-03-24 Ranking

1. `gemma3:4b-it-qat`
2. `qwen2.5:7b`
3. `phi4-mini`
4. `qwen3.5:4b`
5. `huihui_ai/qwen3-abliterated:4b`
6. `huihui_ai/qwen3-abliterated:8b`

## Current Runtime Truth

- Current bounded follow-on: [#68](https://github.com/JKhyro/FURYOKU/issues/68)
- Local primary lane: `gemma3-heretic:4b-q4km`
- Local fallback lane: none configured
- The older `gemma3:4b-it-qat` / `qwen2.5:7b` ranking remains part of the archived 2026-03-24 benchmark record, not the active deployed FURYOKU baseline
- Current deployed-baseline manifest: [2026-04-09 Gemma Heretic current-baseline manifest](results/2026-04-09-gemma3-heretic-current-baseline.json)
- Current deployed-baseline evidence: [2026-04-09 Gemma Heretic compare summary](results/2026-04-09-gemma3-heretic-compare-summary.md)
- Current direct comparison evidence: [2026-04-09 Gemma Heretic compare summary](results/2026-04-09-gemma3-heretic-compare-summary.md)
- Those April 9 summaries now include mechanical hard-check scoring for route decisions, JSON/code output contracts, fabricated-entity skepticism, and sexual-boundary classifier shape
- The benchmark outputs now also attach a machine-readable `promotionVerdict` per model so candidate promotion can be gated mechanically
- The benchmark outputs now also attach a machine-readable `resourceFitVerdict` so local RAM, GPU, and latency regressions can be gated mechanically against the 32 GB RAM / 4 GB VRAM target profile
- Compare reports now also attach a machine-readable `compareDecision` so the deployed baseline and each comparison candidate can be evaluated with explicit roles and with contract-versus-machine-fit blocker reasons
- The benchmark lane now supports both direct machine-profile overrides and reusable preset selection, and the active follow-on is to add a one-command compare publish helper for the summary plus current-baseline manifest
- `qwen3.5:4b` remains an upgrade candidate only if the runtime can force `think:false` cleanly
- `gemma3-heretic:4b-q5km` remains a comparison candidate, not the active deployed lane
- `qwen35-hauhaucs:9b-q4km` remains a tested but non-recommended heavy/undisciplined candidate for this machine profile

## Usage

1. Pull the candidate models you want to test with Ollama.
2. Run `run_ollama_benchmark.ps1`.
3. Run `run_ollama_response_suite.ps1` for same-prompt quality comparisons.
4. Review the JSON output, including the attached `contractEvaluation`, `contractChecks`, `contractSummary`, `promotionVerdict`, `resourceFitVerdict`, and `compareDecision` fields.
5. When you publish a compare lane, run `publish_compare_truth.ps1` so the compare summary and current-baseline manifest are emitted together.
6. Use alternate prompt files to probe specific lanes such as sexual-boundary behavior or harder capability tasks.

Preset file:

- `machine_profiles.json` contains reusable local hardware presets shared by the benchmark entrypoints and the Python contract reporter.
- Use `-MachineProfileName <preset>` or `--machine-profile-name <preset>` to select a preset, and keep the direct `*MemoryMb` flags for one-off overrides.

Publish current compare truth:

```powershell
powershell -ExecutionPolicy Bypass -File .\benchmarks\openclaw-local-llm\publish_compare_truth.ps1
```

Verify checked-in compare truth is fresh:

```powershell
powershell -ExecutionPolicy Bypass -File .\benchmarks\openclaw-local-llm\check_compare_truth_fresh.ps1
```

Publish an alternate compare set:

```powershell
powershell -ExecutionPolicy Bypass -File .\benchmarks\openclaw-local-llm\publish_compare_truth.ps1 `
  -InputPath .\benchmarks\openclaw-local-llm\results\candidate-compare-benchmark.json,.\benchmarks\openclaw-local-llm\results\candidate-compare-response-suite.json `
  -SummaryOutputPath .\benchmarks\openclaw-local-llm\results\candidate-compare-summary.md `
  -CurrentBaselineOutputPath .\benchmarks\openclaw-local-llm\results\candidate-current-baseline.json
```

Example:

```powershell
powershell -ExecutionPolicy Bypass -File .\benchmarks\openclaw-local-llm\run_ollama_benchmark.ps1 `
  -OutputPath .\benchmarks\openclaw-local-llm\results.json
```

```powershell
powershell -ExecutionPolicy Bypass -File .\benchmarks\openclaw-local-llm\run_ollama_response_suite.ps1 `
  -OutputPath .\benchmarks\openclaw-local-llm\results\response-suite.json
```

```powershell
powershell -ExecutionPolicy Bypass -File .\benchmarks\openclaw-local-llm\run_ollama_response_suite.ps1 `
  -PromptsPath .\benchmarks\openclaw-local-llm\sexual_boundary_prompts.json `
  -OutputPath .\benchmarks\openclaw-local-llm\results\sexual-boundary.json
```

```powershell
powershell -ExecutionPolicy Bypass -File .\benchmarks\openclaw-local-llm\run_ollama_response_suite.ps1 `
  -PromptsPath .\benchmarks\openclaw-local-llm\advanced_suite_prompts.json `
  -ThinkFalse `
  -OutputPath .\benchmarks\openclaw-local-llm\results\advanced-suite-thinkfalse.json
```
