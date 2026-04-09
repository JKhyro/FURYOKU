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
- Current bounded follow-on: [#39](https://github.com/JKhyro/FURYOKU/issues/39)

## Current Baseline

- Local primary lane: `gemma3-heretic:4b-q4km`
- Local fallback lane: none configured
- Strong remote continuation: `minimax-portal/MiniMax-M2.7` then `openai-codex/gpt-5.4`
- Current architecture direction: Native C core/runtime first; Avalonia only as a thin shell through native C interop; C# only where necessary for host/binding glue
- Current follow-on focus: publish and integrate the new hard-check benchmark scoring surfaced by the April 9, 2026 Gemma Heretic rerun

## Benchmark Evidence Lane

- Local OpenClaw model benchmark: [`benchmarks/openclaw-local-llm`](benchmarks/openclaw-local-llm)
- Current deployed-baseline evidence: [2026-04-09 Gemma Heretic compare summary](benchmarks/openclaw-local-llm/results/2026-04-09-gemma3-heretic-compare-summary.md)
- Current comparison-candidate evidence: [2026-04-09 Gemma Heretic compare summary](benchmarks/openclaw-local-llm/results/2026-04-09-gemma3-heretic-compare-summary.md)
- The current benchmark evidence now carries mechanical hard-check scoring alongside latency and quality results
