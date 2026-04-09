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

- Current bounded follow-on: [#37](https://github.com/JKhyro/FURYOKU/issues/37)
- Local primary lane: `gemma3-heretic:4b-q4km`
- Local fallback lane: none configured
- The older `gemma3:4b-it-qat` / `qwen2.5:7b` ranking remains part of the archived 2026-03-24 benchmark record, not the active deployed FURYOKU baseline
- Current deployed-baseline evidence: [2026-03-25 Gemma Heretic summary](results/2026-03-25-gemma3-heretic-summary.md)
- Current direct comparison evidence: [2026-03-25 Gemma Heretic Q5 summary](results/2026-03-25-gemma3-heretic-q5-summary.md)
- `qwen3.5:4b` remains an upgrade candidate only if the runtime can force `think:false` cleanly
- `gemma3-heretic:4b-q5km` remains a comparison candidate, not the active deployed lane
- `qwen35-hauhaucs:9b-q4km` remains a tested but non-recommended heavy/undisciplined candidate for this machine profile

## Usage

1. Pull the candidate models you want to test with Ollama.
2. Run `run_ollama_benchmark.ps1`.
3. Run `run_ollama_response_suite.ps1` for same-prompt quality comparisons.
4. Review the JSON output and compare latency, throughput, answer quality, truthfulness, and refusal style together.
5. Use alternate prompt files to probe specific lanes such as sexual-boundary behavior or harder capability tasks.

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
