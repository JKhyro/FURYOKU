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
- Current primary lane: [#78](https://github.com/JKhyro/FURYOKU/issues/78)
- Current support lane: [#73](https://github.com/JKhyro/FURYOKU/issues/73)

## Current Baseline

- Local primary lane: `gemma3-heretic:4b-q4km`
- Local fallback lane: none configured
- Strong remote continuation: `minimax-portal/MiniMax-M2.7` then `openai-codex/gpt-5.4`
- Current architecture direction: Native C core/runtime first; Avalonia only as a thin shell through native C interop; C# only where necessary for host/binding glue
- Current follow-on focus: connect concrete local, CLI, and API transports to validated operator/runtime flows.

## Product Direction

FURYOKU's currently known job is to help the wider system choose and use the right LLM for the situation. This is the current implementation horizon, not the final long-term definition of the project.

- Register multiple model endpoints: local models, command-line/CLI models, and remote API models.
- Describe task requirements such as privacy, reasoning, coding, memory retrieval, context size, latency, tool support, and structured output.
- Rank eligible models and explain why a model was selected or rejected.
- Support flexible CHARACTER compositions, from a one-role tertiary Symbiote to larger arrays such as a primary role plus multiple secondary roles with their own subagent capacity.
- Use benchmark truth as evidence for routing decisions, not as the project goal by itself.

Current routing core:

- [`furyoku/model_router.py`](furyoku/model_router.py) defines the reusable model/task scoring contract and flexible CHARACTER composition selection.
- [`furyoku/model_registry.py`](furyoku/model_registry.py) loads JSON endpoint registries into router-ready model definitions.
- [`furyoku/provider_adapters.py`](furyoku/provider_adapters.py) executes selected local, CLI, and API endpoints through one observable result contract.
- [`furyoku/runtime.py`](furyoku/runtime.py) combines task-based routing with provider execution and returns selection evidence plus execution output.
- [`furyoku/cli.py`](furyoku/cli.py) provides `select` and `run` commands for registry-backed model routing and execution.
- [`examples/model_registry.example.json`](examples/model_registry.example.json) shows local, CLI, and API endpoint configuration.
- [`tests/test_model_router.py`](tests/test_model_router.py) verifies local-only selection, CLI/API routing, blocker reporting, flexible CHARACTER composition, and the three-role compatibility helper.
- [`tests/test_model_registry.py`](tests/test_model_registry.py) verifies registry loading, validation, and routing from configuration.
- [`tests/test_provider_adapters.py`](tests/test_provider_adapters.py) verifies subprocess, API transport, timeout, failure, unsupported-provider, and router-selected execution paths.
- [`tests/test_runtime.py`](tests/test_runtime.py) verifies route-and-execute success and observable execution failure paths.
- [`tests/test_cli.py`](tests/test_cli.py) verifies operator-facing selection and local execution command paths.

CLI example:

```powershell
python -m furyoku.cli select --registry .\examples\model_registry.example.json --task-id private-chat --capability conversation=0.8 --privacy local_only
```

## Benchmark Evidence Lane

- Local OpenClaw model benchmark: [`benchmarks/openclaw-local-llm`](benchmarks/openclaw-local-llm)
- Current deployed-baseline manifest: [2026-04-09 Gemma Heretic current-baseline manifest](benchmarks/openclaw-local-llm/results/2026-04-09-gemma3-heretic-current-baseline.json)
- Current deployed-baseline evidence: [2026-04-09 Gemma Heretic compare summary](benchmarks/openclaw-local-llm/results/2026-04-09-gemma3-heretic-compare-summary.md)
- Current comparison-candidate evidence: [2026-04-09 Gemma Heretic compare summary](benchmarks/openclaw-local-llm/results/2026-04-09-gemma3-heretic-compare-summary.md)
- The current benchmark evidence now carries mechanical hard-check scoring, machine-readable `promotionVerdict` and `resourceFitVerdict` outputs, and role-aware `compareDecision` statuses that can distinguish contract blockers from machine-fit blockers
- The benchmark report and both local benchmark entrypoints now accept machine-profile overrides and reusable preset selection, and the active follow-on is to add a one-command compare publish helper that emits both the summary and current-baseline manifest together
