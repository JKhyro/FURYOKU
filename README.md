# FURYOKU

FURYOKU is the active AI lab program for custom LLM research, implementation, operations, and experimental runtime work.

## Coordination

- Execution truth lives in repo issues.
- Discussions are for narrative and design alignment.
- Project #20 is a mirror of current execution state, not the primary truth source.

## Current Anchors

- Charter ratification: [#1](https://github.com/JKhyro/FURYOKU/issues/1)
- First execution wave closure: [#2](https://github.com/JKhyro/FURYOKU/issues/2)
- Charter feedback discussion: [#3](https://github.com/JKhyro/FURYOKU/discussions/3)
- Current bounded follow-on: [#15](https://github.com/JKhyro/FURYOKU/issues/15)

## Current Baseline

- Local primary lane: `gemma3:4b-it-qat`
- Regular local fallback: `qwen2.5:7b`
- Local-safe experimental slot: `gemma3-heretic:4b-q4km`
- Strong remote continuation: `minimax-portal/MiniMax-M2.7` then `openai-codex/gpt-5.4`
- Current follow-on focus: remaining purpose-aware observational and startup caller cleanup

## Benchmark Evidence Lane

- Local OpenClaw model benchmark: [`benchmarks/openclaw-local-llm`](benchmarks/openclaw-local-llm)
- Latest benchmark result: [2026-03-24 summary](benchmarks/openclaw-local-llm/results/2026-03-24-summary.md)
