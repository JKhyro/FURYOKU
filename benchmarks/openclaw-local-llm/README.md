# OpenClaw Local LLM Benchmark

This lane evaluates small local models for basic OpenClaw work such as concise replies, rewrites, summaries, and simple routing/classification prompts.

## Goal

Select a local model that fits a 32 GB RAM / 4 GB VRAM machine profile with the best balance of:

- latency
- memory pressure
- context length
- answer quality on basic assistant tasks
- OpenClaw/Ollama integration fit

## Current Ranking After Live Benchmark

1. `gemma3:4b-it-qat`
2. `qwen2.5:7b`
3. `phi4-mini`
4. `qwen3.5:4b`
5. `huihui_ai/qwen3-abliterated:4b`
6. `huihui_ai/qwen3-abliterated:8b`

## Current Decision

- Default lightweight lane: `gemma3:4b-it-qat`
- Best regular fallback to keep testing: `qwen2.5:7b`
- Uncensored variants tested so far are not recommended on this machine
- `qwen3.5:4b` remains the strongest upgrade candidate only if the runtime can force `think:false` cleanly
- Imported experimental candidate tested on 2026-03-25: `gemma3-heretic:4b-q4km` is faster and lighter than the default Gemma path, but it was not promoted because instruction discipline and high-level reasoning were weaker
- Imported experimental candidate tested on 2026-03-25: `gemma3-heretic:4b-q5km` modestly refined the Q4 import, but it also was not promoted because the reasoning-discipline gains were too small to justify replacing the current default

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
