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
- Current bounded follow-on: [#65](https://github.com/JKhyro/FURYOKU/issues/65)

## Current Baseline

- Local primary lane: `gemma3-heretic:4b-q4km`
- Local fallback lane: none configured
- Strong remote continuation: `minimax-portal/MiniMax-M2.7` then `openai-codex/gpt-5.4`
- Current architecture direction: Native C core/runtime first; Avalonia only as a thin shell through native C interop; C# only where necessary for host/binding glue
- Current follow-on focus: emit a compact machine-readable current-baseline manifest so runtime glue and automation can consume the deployed local model verdict without scraping the full compare artifacts

## Benchmark Evidence Lane

- Local OpenClaw model benchmark: [`benchmarks/openclaw-local-llm`](benchmarks/openclaw-local-llm)
- Current deployed-baseline evidence: [2026-04-09 Gemma Heretic compare summary](benchmarks/openclaw-local-llm/results/2026-04-09-gemma3-heretic-compare-summary.md)
- Current comparison-candidate evidence: [2026-04-09 Gemma Heretic compare summary](benchmarks/openclaw-local-llm/results/2026-04-09-gemma3-heretic-compare-summary.md)
- The current benchmark evidence now carries mechanical hard-check scoring, machine-readable `promotionVerdict` and `resourceFitVerdict` outputs, and role-aware `compareDecision` statuses that can distinguish contract blockers from machine-fit blockers
- The benchmark report and both local benchmark entrypoints now accept machine-profile overrides and reusable preset selection, and the active follow-on is to emit a compact current-baseline manifest from the compare outputs for downstream runtime and automation use
