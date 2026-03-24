# OpenClaw Local LLM Benchmark

This lane evaluates small local models for basic OpenClaw work such as concise replies, rewrites, summaries, and simple routing/classification prompts.

## Goal

Select a local model that fits a 32 GB RAM / 4 GB VRAM machine profile with the best balance of:

- latency
- memory pressure
- context length
- answer quality on basic assistant tasks
- OpenClaw/Ollama integration fit

## Current Candidate Order

1. `qwen3.5:4b`
2. `phi4-mini`
3. `gemma3:4b-it-q4_K_M`
4. `qwen2.5:7b`

## Usage

1. Pull the candidate models you want to test with Ollama.
2. Run `run_ollama_benchmark.ps1`.
3. Review the JSON output and compare latency, throughput, and answer quality together.

Example:

```powershell
powershell -ExecutionPolicy Bypass -File .\benchmarks\openclaw-local-llm\run_ollama_benchmark.ps1 `
  -OutputPath .\benchmarks\openclaw-local-llm\results.json
```
