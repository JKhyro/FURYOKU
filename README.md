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
- Current primary lane: [#74](https://github.com/JKhyro/FURYOKU/issues/74)
- Current support lane: [#73](https://github.com/JKhyro/FURYOKU/issues/73)

## Current Baseline

- Local primary lane: `gemma3-heretic:4b-q4km`
- Local fallback lane: none configured
- Strong remote continuation: `minimax-portal/MiniMax-M2.7` then `openai-codex/gpt-5.4`
- Current architecture direction: Native C core/runtime first; Avalonia only as a thin shell through native C interop; C# only where necessary for host/binding glue
- Current follow-on focus: build a multi-model router that can choose the best local, CLI, or API LLM for a task and later feed CHARACTER/MOA-style agent arrays.

## Product Direction

FURYOKU's primary job is to help the wider system choose the right LLM for the situation.

- Register multiple model endpoints: local models, command-line/CLI models, and remote API models.
- Describe task requirements such as privacy, reasoning, coding, memory retrieval, context size, latency, tool support, and structured output.
- Rank eligible models and explain why a model was selected or rejected.
- Support three-role CHARACTER panels where one model can act as the interactive face, one as memory/retrieval support, and one as reasoning/coding/rationality support.
- Use benchmark truth as evidence for routing decisions, not as the project goal by itself.

Current routing core:

- [`furyoku/model_router.py`](furyoku/model_router.py) defines the reusable model/task scoring contract.
- [`tests/test_model_router.py`](tests/test_model_router.py) verifies local-only selection, CLI/API routing, blocker reporting, and three-role CHARACTER panel selection.

## Benchmark Evidence Lane

- Local OpenClaw model benchmark: [`benchmarks/openclaw-local-llm`](benchmarks/openclaw-local-llm)
- Current deployed-baseline manifest: [2026-04-09 Gemma Heretic current-baseline manifest](benchmarks/openclaw-local-llm/results/2026-04-09-gemma3-heretic-current-baseline.json)
- Current deployed-baseline evidence: [2026-04-09 Gemma Heretic compare summary](benchmarks/openclaw-local-llm/results/2026-04-09-gemma3-heretic-compare-summary.md)
- Current comparison-candidate evidence: [2026-04-09 Gemma Heretic compare summary](benchmarks/openclaw-local-llm/results/2026-04-09-gemma3-heretic-compare-summary.md)
- The current benchmark evidence now carries mechanical hard-check scoring, machine-readable `promotionVerdict` and `resourceFitVerdict` outputs, and role-aware `compareDecision` statuses that can distinguish contract blockers from machine-fit blockers
- The benchmark report and both local benchmark entrypoints now accept machine-profile overrides and reusable preset selection, and the active follow-on is to add a one-command compare publish helper that emits both the summary and current-baseline manifest together
