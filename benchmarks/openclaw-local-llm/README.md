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

- Current bounded follow-on: [#206](https://github.com/JKhyro/FURYOKU/issues/206)
- Local primary lane: `gemma4-e4b-ultra-heretic:q8_0` as the provisional balanced local default
- Local fallback lane: `gemma4-e4b-hauhau-aggressive:q8kp` first when latency or memory pressure rises, then `gemma4-e2b-hauhau-aggressive:q8kp` only when the tighter machine fit matters more than answer quality margin
- The older `gemma3:4b-it-qat` / `qwen2.5:7b` ranking remains part of the archived 2026-03-24 benchmark record, not the active deployed FURYOKU baseline
- The active candidate roster now lives in `candidates.json` and only uses the currently approved local Gemma set for this lane
- Current approved-roster preflight evidence: [2026-04-13 approved-roster preflight](results/2026-04-13-approved-roster-preflight.json)
- Current approved-roster preflight summary: 3 ready (`gemma4-e4b-ultra-heretic:q8_0`, `gemma4-e4b-hauhau-aggressive:q8kp`, `gemma4-e2b-hauhau-aggressive:q8kp`), 1 missing (`gemma3-12b-ultra-heretic:q8_0`), 2 empty-response (`gemma4-26b-a4b-heretic:q4_k_m`, `gemma4-26b-a4b-ultra-heretic:q4_k_m`), and 3 timeout-bound (`gemma4-31b-heretic:q4_k_m`, `gemma4-26b-a4b-heretic:q8_0`, `gemma4-26b-a4b-ultra-heretic:q8_0`) at a 20-second direct probe budget
- Current blocked-roster second-stage evidence: [2026-04-13 approved blocked-roster probe](results/2026-04-13-approved-blocked-roster-probe.json)
- Current blocked-roster decision summary: the missing `gemma3-12b-ultra-heretic:q8_0` stays excluded until it is installed, and every currently installed heavy 26B/31B approved model returned empty final content even with a 60-second direct probe budget, so those models are excluded on this machine until the empty-response behavior is resolved
- Current approved-ready compare manifest: [2026-04-13 approved-ready current-baseline manifest](results/2026-04-13-approved-ready-current-baseline.json)
- Current approved-ready compare evidence: [2026-04-13 approved-ready compare summary](results/2026-04-13-approved-ready-compare-summary.md)
- Archived April 9 compare manifest: [2026-04-09 Gemma Heretic current-baseline manifest](results/2026-04-09-gemma3-heretic-current-baseline.json)
- Archived April 9 compare evidence: [2026-04-09 Gemma Heretic compare summary](results/2026-04-09-gemma3-heretic-compare-summary.md)
- Those April 9 summaries now include mechanical hard-check scoring for route decisions, JSON/code output contracts, fabricated-entity skepticism, and sexual-boundary classifier shape
- The benchmark outputs now also attach a machine-readable `promotionVerdict` per model so candidate promotion can be gated mechanically
- The benchmark outputs now also attach a machine-readable `resourceFitVerdict` so local RAM, GPU, and latency regressions can be gated mechanically against the 32 GB RAM / 4 GB VRAM target profile
- Compare reports now also attach a machine-readable `compareDecision` so the deployed baseline and each comparison candidate can be evaluated with explicit roles and with contract-versus-machine-fit blocker reasons
- The benchmark lane now supports both direct machine-profile overrides and reusable preset selection, and the current support follow-on is to keep the approved-ready compare truth mechanically reproducible in CI while the blocked roster stays explicitly classified instead of drifting back into vague "heavy model" assumptions
- Older Gemma3 and Qwen comparison lanes remain archived evidence only; they are not the active approved local runtime roster for this lane

## Usage

1. Pull the candidate models you want to test with Ollama.
2. Run `run_ollama_preflight.ps1` first to classify the approved roster as ready, missing, empty-response, or timeout-bound before spending time on the full suites.
3. If any approved models are still non-ready, run `run_ollama_blocked_roster_probe.ps1` next so the machine-fit decision becomes explicit before you spend time rerunning the larger suites.
4. Run `run_ollama_benchmark.ps1`.
5. Run `run_ollama_response_suite.ps1` for same-prompt quality comparisons.
6. Review the JSON output, including the attached `contractEvaluation`, `contractChecks`, `contractSummary`, `promotionVerdict`, `resourceFitVerdict`, and `compareDecision` fields.
7. When you publish a compare lane, run `publish_compare_truth.ps1` so the compare summary and current-baseline manifest are emitted together.
8. Use alternate prompt files to probe specific lanes such as sexual-boundary behavior or harder capability tasks.

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

GitHub Actions also runs the benchmark contract reporter tests plus this compare-truth freshness check on pull requests and pushes to `main` through [`.github/workflows/benchmark-truth-gate.yml`](../../.github/workflows/benchmark-truth-gate.yml).

Run the approved-roster preflight:

```powershell
powershell -ExecutionPolicy Bypass -File .\benchmarks\openclaw-local-llm\run_ollama_preflight.ps1 `
  -OutputPath .\benchmarks\openclaw-local-llm\results\approved-roster-preflight.json
```

Run the blocked-roster second-stage probe:

```powershell
powershell -ExecutionPolicy Bypass -File .\benchmarks\openclaw-local-llm\run_ollama_blocked_roster_probe.ps1 `
  -PreflightPath .\benchmarks\openclaw-local-llm\results\2026-04-13-approved-roster-preflight.json `
  -OutputPath .\benchmarks\openclaw-local-llm\results\2026-04-13-approved-blocked-roster-probe.json `
  -MaxProbeSeconds 60
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
