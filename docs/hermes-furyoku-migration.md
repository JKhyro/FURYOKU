# Hermes-Derived FURYOKU Migration

## Decision

FURYOKU now moves to a Hermes Agent-derived runtime base. Hermes carries the FURYOKU runtime name going forward, and OpenClaw is demoted from controlling runtime to feature/source integration lane.

This decision is tracked in [issue #230](https://github.com/JKhyro/FURYOKU/issues/230).

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
- `scripts/install.ps1` and `scripts/install.cmd`: Windows install helpers exist, but upstream README still says native Windows is not supported and recommends WSL2.

Immediate risk: this project is currently operating from Windows, while upstream Hermes is explicitly WSL2-oriented for Windows users. The first implementation slice should therefore prove either a WSL2-hosted Hermes/FURYOKU bridge or a narrowly adapted local process bridge before assuming direct native Windows operation.

## Fast Migration Order

1. Confirm the local Hermes Agent source path, launch command, config path, and current runnable state.
2. Define the minimal Hermes/FURYOKU swarm contract for seven Symbiotes: identity, role, allowed model lane, state boundary, task queue ownership, and stop/retry behavior.
3. Build or adapt the first local bridge so FURYOKU can route selected model/provider calls into the Hermes runtime without bypassing provider health and benchmark-truth evidence.
4. Run a one-Symbiote smoke, then a three-Symbiote coordination smoke, then the full seven-Symbiote smoke.
5. Inventory OpenClaw features and port only the pieces that improve Hermes/FURYOKU without recreating the coordination failure modes.

The smoke path through seven ordered Symbiote handoffs is complete through issue [#240](https://github.com/JKhyro/FURYOKU/issues/240). The first OpenClaw carryover inventory completed in [#242](https://github.com/JKhyro/FURYOKU/issues/242), recorded in [OpenClaw carryover inventory](openclaw-carryover-inventory.md). The active follow-on is [#244](https://github.com/JKhyro/FURYOKU/issues/244), which defines the [Hermes/FURYOKU routing evidence contract](routing-evidence-contract.md) from retained benchmark truth before any wider OpenClaw feature port.

## OpenClaw Feature Harvest Rules

- Keep: useful UI affordances, local model configuration lessons, benchmark prompts, operator ergonomics, and any proven adapter contracts.
- Re-evaluate: agent conversation flow, shared state, task routing, and fallback behavior before porting.
- Avoid: uncontrolled cross-talk, unclear task ownership, hidden shared mutable state, or any pattern that makes seven agents compete for the same work.

## First Implementation Slice

The first code-bearing migration issue should be opened after the local Hermes path is confirmed. It should target the smallest possible bridge:

- input: one Symbiote task envelope with role, prompt, and required model capabilities
- routing: FURYOKU model selection and provider health checks choose an eligible lane
- runtime handoff: Hermes/FURYOKU receives exactly one bounded task through the confirmed WSL2 or local process boundary
- output: structured result with selected model, execution status, latency, and recoverable error details

The first slice should not attempt full OpenClaw parity, long-running memory, remote deployment, or cross-product CORTEX/VECTOR/SYNAPSE integration.

## Verification Plan

- Documentation truth: README and this plan identify Hermes-derived FURYOKU as the active direction.
- GitHub truth: issue #230 stays In Progress until the first executable bridge issue is opened.
- Local smoke: one-Symbiote route can run without swarm contention.
- Scale smoke: seven Symbiotes can hold distinct identities and task boundaries without duplicate execution.
