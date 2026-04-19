# OpenClaw Carryover Inventory

Tracked by [issue #242](https://github.com/JKhyro/FURYOKU/issues/242) under parent [#230](https://github.com/JKhyro/FURYOKU/issues/230).

## Scope

The one-, three-, and seven-Symbiote Hermes/FURYOKU smoke path is complete. OpenClaw is now a feature/source inventory lane only. This document records the first carryover pass and keeps implementation decisions separate from the inventory.

Allowed in this pass:

- Inspect FURYOKU-owned OpenClaw evidence.
- Inspect OpenClaw-adjacent source mirrors read-only.
- Classify features as `carry`, `defer`, `reject`, or `needs-proof`.
- Recommend follow-on issues only after the inventory shows value without reintroducing OpenClaw coordination failure modes.

Out of scope:

- Mutating `JKhyro/HERMES-AGENT`.
- Mutating OpenClaw-adjacent source mirrors.
- Porting feature code before inventory acceptance.
- Restoring OpenClaw as the controlling runtime.
- Broad CORTEX, VECTOR, or SYNAPSE product integration.

## Source Surfaces

| Source | Status | Inventory Use |
| --- | --- | --- |
| FURYOKU migration docs | In repo | Defines Hermes-derived FURYOKU as runtime base and OpenClaw as carryover inventory only. |
| `benchmarks/openclaw-local-llm` | In repo | Retains OpenClaw-era local model prompts, machine-fit checks, promotion gates, and benchmark-truth workflow as routing evidence. |
| `JKhyro/LOBSTER` | Read-only GitHub source | OpenClaw-native workflow shell with typed pipelines, approval gates, state, workflow files, and OpenClaw invocation adapters. |
| `JKhyro/HERMES-AGENT` | Read-only GitHub source | Target runtime base; used as the compatibility boundary, not as a mutation target. |

No `JKhyro/OpenClaw` repository was found during this pass. `JKhyro/LOBSTER` is the explicit OpenClaw/Lobster evaluation mirror discovered through GitHub and is treated as the OpenClaw-adjacent feature source for this inventory.

## Candidate Matrix

| Candidate | Source Evidence | Disposition | Runtime Value | Coordination Risk | Follow-On |
| --- | --- | --- | --- | --- | --- |
| Benchmark prompts and model promotion gates | `benchmarks/openclaw-local-llm`, including prompt suites, `benchmark_contract_report.py`, and benchmark-truth CI | `carry` | Already helps FURYOKU rank local models with contract, resource-fit, and machine-profile evidence. | Low if kept as evidence only; high only if benchmark results become runtime authority without provider health checks. | Keep as FURYOKU routing evidence and continue using CI freshness gates. |
| Machine-profile and blocked-roster classification | `machine_profiles.json`, approved-roster preflight, blocked-roster probe, current-baseline manifest | `carry` | Prevents heavy or unstable local models from drifting back into the Hermes/FURYOKU runtime roster. | Low; it constrains execution rather than adding agent coordination. | Preserve in routing/provider-health decisions. |
| Typed JSON pipeline model | `JKhyro/LOBSTER` README, `src/runtime.ts`, `src/parser.ts`, command registry | `needs-proof` | Could give FURYOKU deterministic, typed operator workflows around Hermes tasks without making agents re-plan every step. | Medium; a generic pipeline runner can become a second runtime if it owns task scheduling. | Prototype only as a FURYOKU-side operator workflow envelope after runtime ownership boundaries are explicit. |
| Workflow files with resumable approval checkpoints | `JKhyro/LOBSTER` README, `src/workflows/file.ts`, `src/commands/stdlib/approve.ts` | `needs-proof` | Approval/resume semantics may help guard high-impact Hermes/FURYOKU handoffs and operator-reviewed actions. | Medium; approval state can become hidden mutable coordination state if not attached to a single execution key. | Consider a later issue for approval-gated operator workflows keyed by FURYOKU execution ids. |
| Stable `dedupe` command semantics | `JKhyro/LOBSTER/src/commands/stdlib/dedupe.ts` | `carry` | Aligns with the bridge's duplicate-prevention model and can inform future batch/task queue guards. | Low if implemented as a deterministic preflight filter, not as a shared agent memory. | Fold the behavior into future queue/batch guard design, not as a direct runtime dependency. |
| `openclaw.invoke` / `clawd.invoke` transport adapter | `JKhyro/LOBSTER/src/commands/stdlib/openclaw_invoke.ts` | `reject` for runtime carryover; `defer` as source reference | It is a useful example of a thin tool invocation boundary and dry-run flag. | High if ported directly: it points back at OpenClaw control endpoints and bearer-token conventions. | Do not port the OpenClaw transport. Reuse only the idea of a thin, explicit, JSON process boundary. |
| `llm.invoke` typed payload, output schema, cache, retry validation | `JKhyro/LOBSTER/src/commands/stdlib/llm_invoke.ts` | `needs-proof` | Schema-validated model calls could complement FURYOKU task profiles and Hermes adapter outputs. | Medium; cache/retry state can hide stale results or create duplicate execution unless keyed by Symbiote execution identity. | Evaluate as a future schema-validation layer around FURYOKU results, not as an LLM dispatcher replacement. |
| Persistent state commands | `JKhyro/LOBSTER/src/commands/stdlib/state.ts` | `defer` | Durable JSON state can support workflow resume or operator history. | High until FURYOKU defines state ownership; hidden shared mutable state was a known failure mode to avoid. | Revisit only after Hermes/FURYOKU state boundaries and ownership are explicit. |
| GitHub PR monitor recipe | `JKhyro/LOBSTER/src/recipes/github/pr-monitor.ts` | `defer` | Useful operator automation pattern for detecting external changes. | Low to medium; not part of the swarm runtime but can distract from core control loop. | Keep as later operator tooling inspiration, not part of current runtime migration. |
| Gmail/email command surface | `JKhyro/LOBSTER` command registry | `reject` for current lane | Not needed for Hermes/FURYOKU swarm runtime. | Scope risk, not runtime value. | Exclude from this migration lane. |

## Carry Rules

Carry features only when they meet all of these conditions:

1. They strengthen Hermes-derived FURYOKU without making OpenClaw the control plane.
2. They preserve one explicit owner for each task, state record, and execution key.
3. They keep FURYOKU routing/provider health as the model-selection authority.
4. They expose dry-run or validation behavior before live execution.
5. They keep secrets in caller-owned environment/config surfaces and out of committed artifacts.

## Rejection Rules

Reject or defer features that:

- Call OpenClaw control endpoints as part of the Hermes/FURYOKU runtime path.
- Add hidden shared state across Symbiotes.
- Introduce a second scheduler or workflow runtime that competes with Hermes task ownership.
- Bypass FURYOKU provider health, benchmark truth, or duplicate-prevention checks.
- Expand the migration into broad OpenClaw parity.

## Recommended Next Issues

Open follow-on implementation issues only after this inventory is accepted:

1. Carry benchmark-truth and machine-profile checks forward as explicit Hermes/FURYOKU routing evidence in [#244](https://github.com/JKhyro/FURYOKU/issues/244).
2. Prototype a FURYOKU-native typed workflow envelope for operator-reviewed Hermes handoffs.
3. Define an execution-keyed approval/resume contract before adding any durable workflow state.

The first follow-on should stay close to existing FURYOKU routing evidence. The workflow and approval ideas need proof against the coordination-failure guardrails before code is ported.
