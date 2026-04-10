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
- Current primary lane: [#97](https://github.com/JKhyro/FURYOKU/issues/97)
- Current support lane: [#73](https://github.com/JKhyro/FURYOKU/issues/73)

## Current Baseline

- Local primary lane: `gemma3-heretic:4b-q4km`
- Local fallback lane: none configured
- Strong remote continuation: `minimax-portal/MiniMax-M2.7` then `openai-codex/gpt-5.4`
- Current architecture direction: multi-model local/CLI/API selection and execution first, with flexible CHARACTER/MOA role composition layered on top.
- Current follow-on focus: add a CHARACTER orchestration envelope for selected role assignments.

## Product Direction

FURYOKU's currently known job is to help the wider system choose and use the right LLM for the situation. This is the current implementation horizon, not the final long-term definition of the project.

Scope guard:

- Do not treat benchmark truth or CI support as the project purpose.
- Keep the primary execution lane on the multi-model local/CLI/API runtime and flexible CHARACTER/MOA foundation unless the user explicitly redirects.
- Treat benchmark and CI work as supporting evidence and safety infrastructure.

- Register multiple model endpoints: local models, command-line/CLI models, and remote API models.
- Describe task requirements such as privacy, reasoning, coding, memory retrieval, context size, latency, tool support, and structured output.
- Rank eligible models and explain why a model was selected or rejected.
- Support flexible CHARACTER compositions, from a one-role tertiary Symbiote to larger arrays such as a primary role plus multiple secondary roles with their own subagent capacity.
- Use benchmark truth as evidence for routing decisions, not as the project goal by itself.

Current routing core:

- [`furyoku/model_router.py`](furyoku/model_router.py) defines the reusable model/task scoring contract and flexible CHARACTER composition selection.
- [`furyoku/character_profiles.py`](furyoku/character_profiles.py) loads flexible JSON CHARACTER role compositions for Symbiote/Curator/Synth/Agent-style arrays.
- [`furyoku/model_registry.py`](furyoku/model_registry.py) loads JSON endpoint registries into router-ready model definitions.
- [`furyoku/task_profiles.py`](furyoku/task_profiles.py) loads reusable JSON task profiles into router-ready task requirements.
- [`furyoku/provider_adapters.py`](furyoku/provider_adapters.py) executes selected local, CLI, and API endpoints through one observable result contract.
- [`furyoku/provider_health.py`](furyoku/provider_health.py) checks registered endpoint readiness before routing work to a provider.
- [`furyoku/runtime.py`](furyoku/runtime.py) combines task-based routing with provider execution and returns selection evidence plus execution output.
- [`furyoku/cli.py`](furyoku/cli.py) provides `select`, `run`, `health`, `character-select`, and `character-run` commands for registry-backed model routing, execution, readiness checks, CHARACTER role selection, and selected role execution.
- [`examples/model_registry.example.json`](examples/model_registry.example.json) shows local, CLI, and API endpoint configuration.
- [`examples/task_profile.private-chat.json`](examples/task_profile.private-chat.json) shows reusable task profile configuration.
- [`examples/character_profile.tertiary-symbiote.json`](examples/character_profile.tertiary-symbiote.json) shows a one-role tertiary Symbiote composition.
- [`examples/character_profile.kira-array.json`](examples/character_profile.kira-array.json) shows a larger Kira-style one-primary/seven-secondary role array.
- [`tests/test_character_profiles.py`](tests/test_character_profiles.py) verifies flexible CHARACTER profile loading and validation.
- [`tests/test_model_router.py`](tests/test_model_router.py) verifies local-only selection, CLI/API routing, blocker reporting, flexible CHARACTER composition, and the three-role compatibility helper.
- [`tests/test_model_registry.py`](tests/test_model_registry.py) verifies registry loading, validation, and routing from configuration.
- [`tests/test_task_profiles.py`](tests/test_task_profiles.py) verifies task profile loading and validation.
- [`tests/test_provider_adapters.py`](tests/test_provider_adapters.py) verifies subprocess, API transport, timeout, failure, unsupported-provider, and router-selected execution paths.
- [`tests/test_provider_health.py`](tests/test_provider_health.py) verifies command resolution, missing invocation, missing transport, probe, and aggregate readiness paths.
- [`tests/test_runtime.py`](tests/test_runtime.py) verifies route-and-execute success and observable execution failure paths.
- [`tests/test_cli.py`](tests/test_cli.py) verifies operator-facing selection and local execution command paths.

CLI example:

```powershell
python -m furyoku.cli select --registry .\examples\model_registry.example.json --task-profile .\examples\task_profile.private-chat.json
python -m furyoku.cli health --registry .\examples\model_registry.example.json
python -m furyoku.cli character-select --registry .\examples\model_registry.example.json --character-profile .\examples\character_profile.kira-array.json
python -m furyoku.cli character-run --registry .\examples\model_registry.example.json --character-profile .\examples\character_profile.tertiary-symbiote.json --prompt "Hello"
```

## Benchmark Evidence Lane

- Local OpenClaw model benchmark: [`benchmarks/openclaw-local-llm`](benchmarks/openclaw-local-llm)
- Current deployed-baseline manifest: [2026-04-09 Gemma Heretic current-baseline manifest](benchmarks/openclaw-local-llm/results/2026-04-09-gemma3-heretic-current-baseline.json)
- Current deployed-baseline evidence: [2026-04-09 Gemma Heretic compare summary](benchmarks/openclaw-local-llm/results/2026-04-09-gemma3-heretic-compare-summary.md)
- Current comparison-candidate evidence: [2026-04-09 Gemma Heretic compare summary](benchmarks/openclaw-local-llm/results/2026-04-09-gemma3-heretic-compare-summary.md)
- The current benchmark evidence now carries mechanical hard-check scoring, machine-readable `promotionVerdict` and `resourceFitVerdict` outputs, and role-aware `compareDecision` statuses that can distinguish contract blockers from machine-fit blockers
- The benchmark report and both local benchmark entrypoints now accept machine-profile overrides and reusable preset selection, and the active follow-on is to add a one-command compare publish helper that emits both the summary and current-baseline manifest together
