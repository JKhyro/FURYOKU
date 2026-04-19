# Hermes-Derived FURYOKU Migration

## Decision

FURYOKU now moves to a Hermes Agent-derived runtime base. Hermes carries the FURYOKU runtime name going forward, and OpenClaw is demoted from controlling runtime to feature/source integration lane.

This decision was tracked through [issue #230](https://github.com/JKhyro/FURYOKU/issues/230) and closed out by [issue #278](https://github.com/JKhyro/FURYOKU/issues/278).

## Why This Changes

The current 7-Symbiote swarm is exposing coordination failures that are larger than model selection. The hard problems are identity stability, task ownership, swarm arbitration, state boundaries, backpressure, and recovery from confused or duplicate agent behavior.

Hermes Agent is the preferred base because its design is expected to fit multi-agent operation better than OpenClaw's current shape. The migration should preserve proven FURYOKU assets while putting a stricter runtime spine under the swarm.

## Runtime Stance

- Hermes-derived FURYOKU is the active base for the 7-Symbiote swarm.
- OpenClaw is a feature inventory source, not the default runtime host.
- Existing FURYOKU local/CLI/API model routing, provider health, feedback, benchmark truth, and service-wrapper contracts remain reusable components.
- The fastest useful milestone is a functional 7-Symbiote Hermes/FURYOKU control loop, not broad feature parity.
- Current local model restrictions remain in force; do not use local models outside the approved roster.

## Hermes Source Inventory

The first read-only source check against `JKhyro/HERMES-AGENT` shows the mirror is a Python package named `hermes-agent` at version `0.6.0` with these likely migration-relevant surfaces:

- `run_agent.py`: packaged `hermes-agent` entrypoint and likely primary agent loop surface.
- `cli.py` and `hermes_cli`: interactive CLI and operator command surface.
- `agent/`: provider adapters, prompt construction, credential pools, model metadata, smart routing, skills, context compression, trajectory capture, and pricing/usage support.
- `acp_adapter/` and `acp_registry/`: Agent Client Protocol integration surfaces that may be useful for clean process boundaries.
- `model_tools.py`, `toolsets.py`, and `toolset_distributions.py`: model/tool capability surfaces that should be compared with FURYOKU's current provider registry and task requirements.
- `mcp_serve.py`: MCP serving surface for future tool interoperability.
- `batch_runner.py`, `mini_swe_runner.py`, `trajectory_compressor.py`, and `rl_cli.py`: research/evaluation/training-adjacent surfaces that are useful later, but not the first swarm-stability target.
- `scripts/install.ps1` and `scripts/install.cmd`: Windows install helpers exist, but upstream README historically recommended WSL2 for Windows users.

Current host stance: do not treat Ubuntu, WSL, or Ubuntu-VM launch as a standing prerequisite for #230 work. Any future runtime launch path must be selected by a separately formalized child issue; until then, continue local FURYOKU-side contract, bridge, approval/resume, and documentation work without invoking Hermes.

## Completed Migration Path

The first #230 migration path is no longer pending. The completed path confirmed the local Hermes source and process-boundary shape, added the first FURYOKU-owned bridge, scaled it from one to three to seven ordered Symbiote handoffs, inventoried OpenClaw carryover as a feature source only, and added the approval/resume contracts that keep handoffs operator-reviewed and replay-safe.

The smoke path through seven ordered Symbiote handoffs is complete through issue [#240](https://github.com/JKhyro/FURYOKU/issues/240). The first OpenClaw carryover inventory completed in [#242](https://github.com/JKhyro/FURYOKU/issues/242), recorded in [OpenClaw carryover inventory](openclaw-carryover-inventory.md). The routing evidence contract completed in [#244](https://github.com/JKhyro/FURYOKU/issues/244), the operator-reviewed workflow envelope completed in [#246](https://github.com/JKhyro/FURYOKU/issues/246), the [execution-keyed approval/resume contract](approval-resume-contract.md) completed in [#248](https://github.com/JKhyro/FURYOKU/issues/248), one-Symbiote approval gating completed in [#250](https://github.com/JKhyro/FURYOKU/issues/250), multi-Symbiote approval/resume ledger gating completed in [#252](https://github.com/JKhyro/FURYOKU/issues/252), the reusable seven-Symbiote approval fixture completed in [#254](https://github.com/JKhyro/FURYOKU/issues/254), the durable approval/resume ledger state boundary completed in [#256](https://github.com/JKhyro/FURYOKU/issues/256), the local durable approval/resume adapter completed in [#258](https://github.com/JKhyro/FURYOKU/issues/258), local-store bridge gate integration completed in [#260](https://github.com/JKhyro/FURYOKU/issues/260), local approval/resume store inspection completed in [#262](https://github.com/JKhyro/FURYOKU/issues/262), the [operator resume workflow contract](operator-resume-workflow-contract.md) completed in [#266](https://github.com/JKhyro/FURYOKU/issues/266), the bounded local resume record preview/append command completed in [#268](https://github.com/JKhyro/FURYOKU/issues/268), the operator-lane status reconciliation completed in [#270](https://github.com/JKhyro/FURYOKU/issues/270), the local operator resume loop smoke completed in [#272](https://github.com/JKhyro/FURYOKU/issues/272), migration/bridge documentation reconciliation completed in [#276](https://github.com/JKhyro/FURYOKU/issues/276), and final parent-lane closeout truth alignment completed in [#278](https://github.com/JKhyro/FURYOKU/issues/278). Future runtime work should be opened as a new explicitly scoped issue rather than inferred as a #230 child, scheduler, launch, Ubuntu/WSL/Ubuntu-VM task, OpenClaw mutation, or full runtime expansion.

## OpenClaw Feature Harvest Rules

- Keep: useful UI affordances, local model configuration lessons, benchmark prompts, operator ergonomics, and any proven adapter contracts.
- Re-evaluate: agent conversation flow, shared state, task routing, and fallback behavior before porting.
- Avoid: uncontrolled cross-talk, unclear task ownership, hidden shared mutable state, or any pattern that makes seven agents compete for the same work.

## Completed Bridge Slice

The first code-bearing migration slice is complete. Its target was the smallest possible bridge:

- input: one Symbiote task envelope with role, prompt, and required model capabilities
- routing: FURYOKU model selection and provider health checks choose an eligible lane
- runtime handoff: Hermes/FURYOKU receives exactly one bounded task through the confirmed WSL2 or local process boundary
- output: structured result with selected model, execution status, latency, and recoverable error details

That bridge was then extended into bounded three- and seven-Symbiote smokes, approval/resume gating, local durable approval/resume state, and an operator-driven local resume loop. Any next implementation child must still be selected explicitly under #230 and must not infer full OpenClaw parity, long-running memory, remote deployment, scheduler ownership, Ubuntu/WSL launch work, or cross-product CORTEX/VECTOR/SYNAPSE integration from the completed bridge path.

## Verification Plan

- Documentation truth: README and this plan identify Hermes-derived FURYOKU as the established runtime direction.
- GitHub truth: issue #230 can close after #278 because the parent adoption lane and its bounded bridge/support children are locally and remotely reconciled.
- Local smoke: one-Symbiote, three-Symbiote, and seven-Symbiote bridge paths have proved bounded handoff contracts without making launch or scheduler work implicit.
- Scale smoke: seven Symbiotes can hold distinct identities and task boundaries without duplicate execution in the current smoke sequence.
