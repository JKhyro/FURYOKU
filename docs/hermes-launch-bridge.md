# Hermes/FURYOKU Launch Bridge

## Purpose

This document tracks issue [#232](https://github.com/JKhyro/FURYOKU/issues/232): prepare the first executable Hermes-derived FURYOKU launch bridge and one-Symbiote smoke.

Parent migration lane: [#230](https://github.com/JKhyro/FURYOKU/issues/230).

## Current Host Check

The current Windows host does not yet expose a usable Linux WSL2 distro for upstream Hermes:

```powershell
wsl -l -v
```

Observed result in this thread: only `docker-desktop` was listed, and it was stopped.

Upstream Hermes says native Windows is not supported and recommends WSL2 for Windows users. That makes WSL2 launch readiness the first practical gate before we claim the Hermes runtime is runnable on this machine.

## Operator Handoff If WSL2 Is Missing

Run this from an elevated or normal PowerShell session as appropriate for the host policy:

```powershell
wsl --install -d Ubuntu
wsl -d Ubuntu -- uname -a
```

Once Ubuntu is available, prepare a read-only Hermes source checkout inside WSL:

```bash
mkdir -p ~/src
cd ~/src
git clone https://github.com/JKhyro/HERMES-AGENT.git
cd HERMES-AGENT
python3 --version
```

Do not migrate secrets yet. First prove the source checkout, Python version, and launch command.

## One-Symbiote Smoke Contract

The first bridge smoke should pass exactly one bounded task from FURYOKU into Hermes-derived FURYOKU:

```json
{
  "schemaVersion": 1,
  "symbioteId": "symbiote-01",
  "role": "primary",
  "task": {
    "taskId": "hermes.bridge.one-symbiote",
    "requiredCapabilities": {
      "conversation": 0.8,
      "instruction_following": 0.8
    },
    "privacyRequirement": "local_preferred"
  },
  "prompt": "Reply with one short sentence confirming the Hermes/FURYOKU bridge received this task.",
  "routing": {
    "checkHealth": true,
    "fallback": true,
    "maxAttempts": 2
  }
}
```

Expected output contract:

- selected model/provider from FURYOKU routing evidence
- Hermes/FURYOKU handoff status
- execution success or recoverable error
- latency or timing detail when available
- no duplicate Symbiote execution

## Implementation Boundary

- FURYOKU owns model selection, provider health, benchmark evidence, task profile loading, and result shape.
- Hermes-derived FURYOKU owns the agent runtime loop and Symbiote task execution.
- OpenClaw remains a carryover inventory source only.
- The first smoke must not start all seven Symbiotes.
- The first smoke must not import broad Hermes source into the FURYOKU package.

## Next Code Slice

After WSL2 and the Hermes source path are confirmed, add the smallest bridge scaffold:

1. A FURYOKU bridge module or CLI command that serializes the one-Symbiote task envelope.
2. A configurable Hermes launch command/path.
3. A dry-run mode that validates the envelope without invoking Hermes.
4. A live mode that invokes one Hermes/FURYOKU task and captures structured output.

The scale path is one Symbiote first, then three, then seven.

## Dry-Run Scaffold

The first FURYOKU-side scaffold is intentionally dry-run only. It can be exercised before Ubuntu WSL2 is available because it does not invoke Hermes:

```powershell
python -m furyoku.cli hermes-bridge --registry .\examples\model_registry.example.json --envelope .\examples\hermes_bridge_one_symbiote.example.json --dry-run
```

The dry-run validates that the input describes exactly one Symbiote task, derives a duplicate-prevention execution key from `symbioteId`, `role`, and `taskId`, runs FURYOKU model selection with optional provider health evidence from the envelope, and emits the structured handoff result expected by the live bridge.

Live mode remains blocked until a usable Ubuntu WSL2 distro and Hermes source path are confirmed. The scaffold must not be widened into multi-Symbiote execution until the one-Symbiote live handoff is proven.
