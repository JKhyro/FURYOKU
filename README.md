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
- Current active lane: [#230](https://github.com/JKhyro/FURYOKU/issues/230) Hermes Agent becomes the FURYOKU runtime base
- Downstream CHARACTER/MOA groundwork completed: [#97](https://github.com/JKhyro/FURYOKU/issues/97)
- Latest completed support lane: [#268](https://github.com/JKhyro/FURYOKU/issues/268) added local resume record preview/append support after the [#266](https://github.com/JKhyro/FURYOKU/issues/266) operator resume workflow contract
- Next support lane: select a fresh bounded [#230](https://github.com/JKhyro/FURYOKU/issues/230) child from current GitHub/local truth; do not infer runtime launch or scheduler expansion from the completed operator lane

## Current Baseline

- Local primary lane: `gemma4-e4b-ultra-heretic:q8_0` as the provisional balanced local default on limited hardware
- Local fallback lane: `gemma4-e4b-hauhau-aggressive:q8kp` first when latency or memory pressure rises, then `gemma4-e2b-hauhau-aggressive:q8kp` only for the tightest local fit, but neither is promoted over the current balanced default on this machine yet
- Strong remote continuation: `minimax-portal/MiniMax-M2.7` then `openai-codex/gpt-5.4`
- Current architecture direction: Hermes-derived FURYOKU runtime first, with the existing multi-model local/CLI/API selection, benchmark truth, provider health, feedback, and service-wrapper assets preserved as reusable FURYOKU components.
- Current follow-on focus: migrate the 7-Symbiote swarm onto the Hermes-derived FURYOKU base quickly, then inventory and port only the OpenClaw features that improve the new runtime without carrying forward OpenClaw's coordination failure modes.
- Migration plan: [Hermes-derived FURYOKU migration](docs/hermes-furyoku-migration.md)
- Launch bridge plan: [Hermes/FURYOKU launch bridge](docs/hermes-launch-bridge.md)
- OpenClaw carryover inventory: [OpenClaw carryover inventory](docs/openclaw-carryover-inventory.md)
- Routing evidence contract: [Hermes/FURYOKU routing evidence contract](docs/routing-evidence-contract.md)
- Operator-reviewed workflow envelope: [Operator-reviewed Hermes workflow envelope](docs/operator-reviewed-workflow-envelope.md)
- Approval/resume contract: [Execution-keyed approval/resume contract](docs/approval-resume-contract.md)
- Durable approval/resume ledger boundary: [Durable approval/resume ledger state boundary](docs/durable-approval-resume-ledger-boundary.md)
- Operator resume workflow contract: [Operator resume workflow contract](docs/operator-resume-workflow-contract.md)

### Provisional Local Usage Tiers

- Fast/light local lane: `gemma4-e4b-hauhau-aggressive:q8kp` first, then `gemma4-e2b-hauhau-aggressive:q8kp` only when the tighter memory/latency fit matters more than answer quality margin
- Balanced local default: `gemma4-e4b-ultra-heretic:q8_0`
- Deferred deeper local lane: `gemma3-12b-ultra-heretic:q8_0` only after it is installed and benchmarked on this machine
- Currently excluded on this 32 GB RAM / 4 GB VRAM machine because they returned empty final content in the blocked-roster probe: `gemma4-26b-a4b-heretic:q4_k_m`, `gemma4-26b-a4b-ultra-heretic:q4_k_m`, `gemma4-31b-heretic:q4_k_m`, `gemma4-26b-a4b-heretic:q8_0`, `gemma4-26b-a4b-ultra-heretic:q8_0`

## SDK Reuse

FURYOKU is now intended to be consumed both as:

- an importable Python package for direct library/SDK reuse
- a packaged CLI for process-level integration
- a thin local service/API wrapper for non-Python or process-isolated callers

Local install examples:

```powershell
python -m pip install -e .
furyoku --help
python -m furyoku --help
furyoku-service --help
```

Local service example:

```powershell
furyoku-service --registry .\examples\model_registry.example.json --host 127.0.0.1 --port 8765
```

```powershell
$task = @{
  schemaVersion = 1
  taskId = "private-chat"
  privacyRequirement = "local_only"
  requiredCapabilities = @{
    conversation = 0.9
  }
} | ConvertTo-Json -Depth 5

Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/v1/select -ContentType "application/json" -Body "{`"task`":$task}"
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/v1/run -ContentType "application/json" -Body "{`"task`":$task,`"prompt`":`"Hello`"}"
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/v1/health -ContentType "application/json" -Body "{}"
```

Initial wrapper contract:

- `GET /health` returns local service status and configured default registry path.
- `POST /v1/health` returns provider readiness for the configured or supplied registry.
- `POST /v1/select` accepts `task` or `taskPath`, plus optional `registry` or `registryPath`, and returns a JSON selection result.
- `POST /v1/run` accepts the same task inputs plus `prompt` and returns a JSON execution result.

## Product Direction

FURYOKU's current runtime direction is now Hermes-derived FURYOKU: Hermes Agent becomes the base architecture for operating the 7-Symbiote swarm, and OpenClaw becomes a feature/source integration lane rather than the controlling runtime.

The existing FURYOKU model-selection package remains part of the runtime spine. Its job is still to help the wider system choose and use the right LLM for each situation, but it now serves the Hermes-derived swarm runtime instead of assuming OpenClaw is the primary host.

Scope guard:

- Do not treat benchmark truth or CI support as the project purpose.
- Keep the primary execution lane on Hermes-derived FURYOKU for swarm operation, with the multi-model local/CLI/API decision system retained as reusable routing infrastructure.
- Treat OpenClaw as a source of features to inventory and selectively port, not as the default runtime base.
- Treat flexible CHARACTER/MOA support as important downstream product work, not discarded scope.
- Sequence the work deliberately: make the Hermes/FURYOKU 7-Symbiote control loop functional first, then layer broader CHARACTER/MOA arrays and OpenClaw feature harvests onto the stable runtime.
- Treat benchmark and CI work as supporting evidence and safety infrastructure.

- Register multiple model endpoints: local models, command-line/CLI models, and remote API models.
- Describe task requirements such as privacy, reasoning, coding, memory retrieval, context size, latency, tool support, and structured output.
- Rank eligible models and explain why a model was selected or rejected.
- Use persisted outcome feedback as bounded routing evidence so successful, failed, costly, slow, or manually overridden decisions can influence future model selection without bypassing hard blockers.
- Support flexible CHARACTER compositions, from a one-role tertiary Symbiote to larger arrays such as a primary role plus multiple secondary roles with their own subagent capacity.
- Use benchmark truth as evidence for routing decisions, not as the project goal by itself.

Current routing core:

- [`furyoku/model_router.py`](furyoku/model_router.py) defines the reusable model/task scoring contract and flexible CHARACTER composition selection.
- Routing score policy profiles can tune soft scoring weights for capability fit, context, speed, privacy preference, provider preference, and cost without bypassing hard blockers.
- [`furyoku/model_decisions.py`](furyoku/model_decisions.py) evaluates multiple local, CLI, and API models across representative decision situations.
- [`furyoku/character_profiles.py`](furyoku/character_profiles.py) loads flexible JSON CHARACTER role compositions for Symbiote/Curator/Synth/Agent-style arrays and serializes selected role assignments into CHARACTER orchestration envelopes.
- [`furyoku/model_registry.py`](furyoku/model_registry.py) loads JSON endpoint registries into router-ready model definitions.
- [`furyoku/routing_evidence.py`](furyoku/routing_evidence.py) normalizes retained OpenClaw benchmark outputs into Hermes/FURYOKU routing evidence without bypassing task, health, privacy, or duplicate-execution gates.
- [`furyoku/task_profiles.py`](furyoku/task_profiles.py) loads reusable JSON task profiles into router-ready task requirements.
- [`furyoku/workflow_envelope.py`](furyoku/workflow_envelope.py) validates a typed operator-reviewed workflow envelope around one Hermes/FURYOKU handoff without adding a second scheduler or hidden shared state.
- [`furyoku/approval_resume.py`](furyoku/approval_resume.py) validates execution-keyed approval/resume records and provides a small local JSON-backed durable adapter for append/read, latest gate selection, and consumption-event replay blocking.
- Live Hermes bridge handoffs can require approval/resume evidence from a record, ledger fixture, or local JSON-backed store and block before process invocation unless the latest matching record is `approved` or `resume_approved` for the exact bridge execution key.
- Local approval/resume stores can be inspected with `approval-resume-store-report` to review matching records, consumption events, and gate readiness without loading a model registry or invoking Hermes.
- The operator resume workflow contract defines how a consumed or blocked local-store report becomes a new append-only `resume_requested` or `resume_approved` record without adding a scheduler or hidden runtime state.
- `approval-resume-create` previews that operator resume record by default and appends it to the local store only with `--append`.
- [`furyoku/provider_adapters.py`](furyoku/provider_adapters.py) executes selected local, CLI, and API endpoints through one observable result contract.
- Registry-configured API endpoints can use OpenAI-compatible chat-completions HTTP metadata (`apiUrl`, `apiKeyEnv`, `apiModel`, `apiFormat`) or an injected transport.
- [`furyoku/provider_health.py`](furyoku/provider_health.py) checks registered endpoint readiness before routing work to a provider.
- Single-task `select` and direct `run` commands can use `--check-health` so unavailable local commands, missing CLI tools, or unconfigured API transports are demoted before execution.
- [`furyoku/outcome_feedback.py`](furyoku/outcome_feedback.py) records operator or automated feedback linked to persisted decision/execution reports.
- Outcome feedback records can be aggregated into bounded per-model score adjustments for future decision reports.
- Routed `run` executions can append inferred success/failure outcome records to JSONL feedback logs with `--output` plus `--capture-outcome-log`, allowing real execution results to become future routing evidence without hand-authored feedback entries.
- Captured outcome feedback logs can be summarized by model, provider, and situation with diagnostic `rankScore` and feedback-adjustment signals for operator review.
- `feedback-summary` also emits aggregate model scorecards and per-situation model leaderboards so operators can review long-run winners and failures across accumulated routed and comparative evidence.
- Outcome feedback records preserve observed execution latency and any available model-rate or estimated cost telemetry already present in persisted run/comparison reports, so scorecards can surface speed and cost trends without changing routing blockers.
- Task profiles and decision-suite situations can apply explicit latency and total-cost ceilings so routed selection, recommendations, and comparative reviews favor the best model that is still usable within operator constraints.
- Feedback-backed recommendation reports reuse the current decision engine and explain the recommended model/provider per situation without changing routing policy.
- Recommendation reports include additive confidence and evidence-quality metadata so operators can distinguish strong, sparse, mixed, and blocked recommendations.
- [`examples/decision_outcomes.example.jsonl`](examples/decision_outcomes.example.jsonl) is a runnable outcome fixture for the summary and recommendation workflow.
- [`examples/feedback_policy.example.json`](examples/feedback_policy.example.json) shows the configurable feedback adjustment policy contract for tuning max adjustment, verdict weights, default outcome scores, and optional recency decay.
- [`examples/routing_score_policy.speed-first.json`](examples/routing_score_policy.speed-first.json) shows a speed-heavy routing score policy profile.
- [`examples/operator_reviewed_hermes_workflow.example.json`](examples/operator_reviewed_hermes_workflow.example.json) shows the typed operator-reviewed Hermes handoff envelope.
- [`examples/hermes_approval_resume_contract.example.json`](examples/hermes_approval_resume_contract.example.json) shows approval and resume records keyed to the reviewed handoff envelope.
- [`examples/hermes_approval_resume_gate.approved.json`](examples/hermes_approval_resume_gate.approved.json) shows a single approved record for a gated one-Symbiote bridge handoff.
- [`examples/hermes_approval_resume_three_smoke.approved.json`](examples/hermes_approval_resume_three_smoke.approved.json) shows approved records for a gated three-Symbiote smoke handoff ledger.
- [`examples/hermes_approval_resume_seven_smoke.approved.json`](examples/hermes_approval_resume_seven_smoke.approved.json) shows approved records for a gated seven-Symbiote smoke handoff ledger.
- [`examples/operator_resume_workflow.example.json`](examples/operator_resume_workflow.example.json) shows a consumed first attempt followed by a safe `resume_approved` retry record.
- Feedback-informed decision and execution reports include `feedbackPolicy` metadata so operators can audit whether default or custom policy settings shaped routing.
- [`furyoku/runtime.py`](furyoku/runtime.py) combines task-based routing with provider execution and returns selection evidence plus execution output.
- Routed `run` execution can use fallback chains to try the next eligible ranked model when the selected provider fails or times out, while preserving every execution attempt in JSON output.
- Comparative `compare-run` execution can run the same prompt across multiple eligible ranked local, CLI, and API models, preserving per-candidate success/failure evidence for best-fit review.
- Comparative execution reports can append one feedback record per executed candidate so future recommendation and routing runs can learn from same-prompt comparison results.
- Suite-level comparative execution batches can now compare multiple decision-suite situations in one aggregate report using a prompt-map input.
- Suite-level `compare-batch` reports can append one feedback record per executed candidate so aggregate comparative batches feed the same reusable feedback-evidence loop.
- [`furyoku/cli.py`](furyoku/cli.py) provides `select`, `decide`, `run`, `compare-run`, `compare-batch`, `health`, `approval-resume-store-report`, `character-select`, and `character-run` commands for registry-backed model routing, multi-situation decisions, execution, readiness checks, local approval/resume store inspection, comparative execution, CHARACTER role selection, and selected role execution.
- [`examples/model_registry.example.json`](examples/model_registry.example.json) shows local, CLI, and API endpoint configuration.
- [`examples/decision_suite.primary-routing.json`](examples/decision_suite.primary-routing.json) shows a reusable multi-situation decision suite.
- [`examples/comparison_prompt_map.primary-routing.json`](examples/comparison_prompt_map.primary-routing.json) shows a reusable prompt-map for suite-level comparative execution batches.
- Decision suites can weight higher-value situations and define minimum score thresholds so FURYOKU can distinguish "best available" from "good enough to use."
- [`examples/task_profile.private-chat.json`](examples/task_profile.private-chat.json) shows reusable task profile configuration.
- [`examples/task_profile.tradeoff-speed-chat.json`](examples/task_profile.tradeoff-speed-chat.json) shows task-level soft tradeoff weighting for a latency-sensitive chat task.
- [`examples/character_profile.tertiary-symbiote.json`](examples/character_profile.tertiary-symbiote.json) shows a one-role tertiary Symbiote composition.
- [`examples/character_profile.kira-array.json`](examples/character_profile.kira-array.json) shows a larger Kira-style one-primary/seven-secondary role array.
- [`tests/test_character_profiles.py`](tests/test_character_profiles.py) verifies flexible CHARACTER profile loading and validation.
- [`tests/test_model_router.py`](tests/test_model_router.py) verifies local-only selection, CLI/API routing, blocker reporting, flexible CHARACTER composition, and the three-role compatibility helper.
- [`tests/test_model_registry.py`](tests/test_model_registry.py) verifies registry loading, validation, and routing from configuration.
- [`tests/test_task_profiles.py`](tests/test_task_profiles.py) verifies task profile loading and validation.
- [`tests/test_provider_adapters.py`](tests/test_provider_adapters.py) verifies subprocess, API transport, timeout, failure, unsupported-provider, and router-selected execution paths.
- [`tests/test_provider_health.py`](tests/test_provider_health.py) verifies command resolution, missing invocation, missing transport, probe, and aggregate readiness paths.
- [`tests/test_runtime.py`](tests/test_runtime.py) verifies route-and-execute success and observable execution failure paths.
- [`tests/test_cli.py`](tests/test_cli.py) verifies operator-facing selection, local execution, and runnable recommendation workflow fixture command paths.

CLI example:

```powershell
python -m furyoku.cli select --registry .\examples\model_registry.example.json --task-profile .\examples\task_profile.private-chat.json
python -m furyoku.cli select --registry .\examples\model_registry.example.json --task-id bounded-chat --capability conversation=0.8 --max-latency-ms 2000 --max-total-cost-per-1k 0.03
python -m furyoku.cli select --registry .\examples\model_registry.example.json --task-profile .\examples\task_profile.private-chat.json --check-health
python -m furyoku.cli select --registry .\examples\model_registry.example.json --task-profile .\examples\task_profile.private-chat.json --routing-policy .\examples\routing_score_policy.speed-first.json
python -m furyoku.cli select --registry .\examples\model_registry.example.json --task-profile .\examples\task_profile.private-chat.json --feedback-log .\decision-outcomes.jsonl
python -m furyoku.cli select --registry .\examples\model_registry.example.json --task-profile .\examples\task_profile.private-chat.json --feedback-log .\decision-outcomes.jsonl --feedback-policy .\examples\feedback_policy.example.json
python -m furyoku.cli decide --registry .\examples\model_registry.example.json
python -m furyoku.cli decide --registry .\examples\model_registry.example.json --decision-suite .\examples\decision_suite.primary-routing.json
python -m furyoku.cli decide --registry .\examples\model_registry.example.json --decision-suite .\examples\decision_suite.primary-routing.json --output .\decision-report.json
python -m furyoku.cli decide --registry .\examples\model_registry.example.json --decision-suite .\examples\decision_suite.primary-routing.json --feedback-log .\decision-outcomes.jsonl
python -m furyoku.cli decide --registry .\examples\model_registry.example.json --decision-suite .\examples\decision_suite.primary-routing.json --feedback-log .\decision-outcomes.jsonl --feedback-policy .\examples\feedback_policy.example.json
python -m furyoku.cli decide --registry .\examples\model_registry.example.json --decision-suite .\examples\decision_suite.primary-routing.json --routing-policy .\examples\routing_score_policy.speed-first.json
python -m furyoku.cli recommend --registry .\examples\model_registry.example.json --decision-suite .\examples\decision_suite.primary-routing.json --feedback-log .\examples\decision_outcomes.example.jsonl --output .\recommendations.json
python -m furyoku.cli run --registry .\examples\model_registry.example.json --decision-suite .\examples\decision_suite.primary-routing.json --situation-id decision.private-chat --prompt "Hello"
python -m furyoku.cli run --registry .\examples\model_registry.example.json --task-id bounded-chat --capability conversation=0.8 --max-latency-ms 2000 --max-total-cost-per-1k 0.03 --prompt "Hello"
python -m furyoku.cli run --registry .\examples\model_registry.example.json --decision-suite .\examples\decision_suite.primary-routing.json --situation-id decision.private-chat --prompt "Hello" --fallback --max-attempts 2
python -m furyoku.cli compare-run --registry .\examples\model_registry.example.json --decision-suite .\examples\decision_suite.primary-routing.json --situation-id decision.structured-json --prompt "Hello" --max-candidates 2 --output .\comparison-report.json
python -m furyoku.cli compare-run --registry .\examples\model_registry.example.json --decision-suite .\examples\decision_suite.primary-routing.json --situation-id decision.structured-json --prompt "Hello" --max-candidates 2 --output .\comparison-report.json --capture-comparison-outcomes .\decision-outcomes.jsonl --comparison-success-score 1.0 --comparison-failure-score 0.0 --comparison-outcome-tag compare-run
python -m furyoku.cli compare-batch --registry .\examples\model_registry.example.json --decision-suite .\examples\decision_suite.primary-routing.json --prompt-map .\examples\comparison_prompt_map.primary-routing.json --max-candidates 2 --output .\batch-comparison-report.json
python -m furyoku.cli compare-batch --registry .\examples\model_registry.example.json --decision-suite .\examples\decision_suite.primary-routing.json --prompt-map .\examples\comparison_prompt_map.primary-routing.json --max-candidates 2 --output .\batch-comparison-report.json --capture-comparison-outcomes .\decision-outcomes.jsonl --comparison-success-score 1.0 --comparison-failure-score 0.0 --comparison-outcome-tag compare-batch
python -m furyoku.cli run --registry .\examples\model_registry.example.json --decision-suite .\examples\decision_suite.primary-routing.json --situation-id decision.private-chat --prompt "Hello" --feedback-log .\decision-outcomes.jsonl
python -m furyoku.cli run --registry .\examples\model_registry.example.json --task-profile .\examples\task_profile.private-chat.json --prompt "Hello" --feedback-log .\decision-outcomes.jsonl
python -m furyoku.cli run --registry .\examples\model_registry.example.json --task-profile .\examples\task_profile.private-chat.json --prompt "Hello" --feedback-log .\decision-outcomes.jsonl --feedback-policy .\examples\feedback_policy.example.json
python -m furyoku.cli run --registry .\examples\model_registry.example.json --task-profile .\examples\task_profile.private-chat.json --prompt "Hello" --check-health
python -m furyoku.cli run --registry .\examples\model_registry.example.json --task-profile .\examples\task_profile.private-chat.json --prompt "Hello" --routing-policy .\examples\routing_score_policy.speed-first.json
python -m furyoku.cli run --registry .\examples\model_registry.example.json --task-profile .\examples\task_profile.private-chat.json --prompt "Hello" --output .\run-report.json --capture-outcome-log .\decision-outcomes.jsonl --outcome-score 0.9 --outcome-reason "accepted response"
python -m furyoku.cli feedback --report .\decision-report.json --feedback-log .\decision-outcomes.jsonl --verdict success --score 0.9 --reason "accepted response"
python -m furyoku.cli feedback-summary --feedback-log .\examples\decision_outcomes.example.jsonl --output .\feedback-summary.json
python -m furyoku.cli health --registry .\examples\model_registry.example.json
python -m furyoku.cli character-select --registry .\examples\model_registry.example.json --character-profile .\examples\character_profile.kira-array.json
python -m furyoku.cli character-select --registry .\examples\model_registry.example.json --character-profile .\examples\character_profile.tertiary-symbiote.json --check-health
python -m furyoku.cli character-select --registry .\examples\model_registry.example.json --character-profile .\examples\character_profile.kira-array.json --output .\character-envelope.json
python -m furyoku.cli character-run --registry .\examples\model_registry.example.json --character-profile .\examples\character_profile.tertiary-symbiote.json --prompt "Hello"
```

## Benchmark Evidence Lane

- Historical OpenClaw local-model benchmark, retained as FURYOKU routing evidence during the Hermes migration: [`benchmarks/openclaw-local-llm`](benchmarks/openclaw-local-llm)
- Hermes/FURYOKU routing evidence contract: [docs/routing-evidence-contract.md](docs/routing-evidence-contract.md)
- Current deployed-baseline manifest: [2026-04-13 approved-ready current-baseline manifest](benchmarks/openclaw-local-llm/results/2026-04-13-approved-ready-current-baseline.json)
- Current deployed-baseline evidence: [2026-04-13 approved-ready compare summary](benchmarks/openclaw-local-llm/results/2026-04-13-approved-ready-compare-summary.md)
- Current blocked-roster evidence: [2026-04-13 approved blocked-roster probe](benchmarks/openclaw-local-llm/results/2026-04-13-approved-blocked-roster-probe.json)
- GitHub Actions now enforces the benchmark contract reporter tests plus checked-in compare-truth freshness through [`.github/workflows/benchmark-truth-gate.yml`](.github/workflows/benchmark-truth-gate.yml) on pull requests and pushes to `main`
- The current benchmark evidence now carries mechanical hard-check scoring, machine-readable `promotionVerdict` and `resourceFitVerdict` outputs, and role-aware `compareDecision` statuses that can distinguish contract blockers from machine-fit blockers
- The benchmark report and local benchmark entrypoints now accept machine-profile overrides and reusable preset selection, and the current support follow-on is to keep both the compare-truth surfaces and the blocked-roster machine-fit classification mechanically current
