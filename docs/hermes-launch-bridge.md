# Hermes/FURYOKU Launch Bridge

## Purpose

This document records the completed issues [#232](https://github.com/JKhyro/FURYOKU/issues/232), [#238](https://github.com/JKhyro/FURYOKU/issues/238), and [#240](https://github.com/JKhyro/FURYOKU/issues/240) for the one-, three-, and seven-Symbiote Hermes/FURYOKU smoke sequence.

Parent migration lane: [#230](https://github.com/JKhyro/FURYOKU/issues/230).

## Current Host Check

The Windows host now exposes an Ubuntu WSL2 distro for the Hermes launch path:

```powershell
wsl -l -v
wsl -d Ubuntu -- uname -a
```

Observed result in this thread: `wsl --install -d Ubuntu` timed out after registering Ubuntu, the first `uname` probe returned `Wsl/Service/E_UNEXPECTED`, then `wsl --shutdown` cleared the WSL service state and `wsl -d Ubuntu -- uname -a` succeeded.

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

## Live Process-Boundary Scaffold

Live mode invokes exactly one configured handoff command after the same one-Symbiote envelope validation, duplicate guard, and FURYOKU model routing used by dry-run mode. The validated handoff payload is written to the command on stdin, and the command's stdout/stderr, exit code, timing, and recoverable errors are captured in the structured bridge report.

The live one-Symbiote bridge can now require an execution-keyed approval/resume record before process invocation. With `--require-approval-resume`, FURYOKU blocks the handoff unless the supplied record or latest matching ledger entry is `approved` or `resume_approved` for the exact bridge `executionKey`.

This command proves the Windows-to-WSL process boundary without claiming a full Hermes agent execution. The example runtime reads the bridge payload from stdin and echoes the execution key plus selected model evidence:

```powershell
python -m furyoku.cli hermes-bridge `
  --registry .\examples\model_registry.example.json `
  --envelope .\examples\hermes_bridge_one_symbiote.example.json `
  --approval-resume-record .\examples\hermes_approval_resume_gate.approved.json `
  --require-approval-resume `
  --timeout-seconds 10 `
  --handoff-command wsl -d Ubuntu python3 <furyoku-repo-wsl-path>/examples/hermes_bridge_echo_runtime.py
```

On the current handoff host, `<furyoku-repo-wsl-path>` resolved to `/mnt/c/Users/Allan/OneDrive/Documents/FURYOKU-local-model-roster-refresh`.

To execute Hermes itself, replace the handoff command with the confirmed Hermes/FURYOKU launch command from the read-only WSL checkout. The scaffold must not be widened into multi-Symbiote execution until the one-Symbiote live handoff is proven.

## Hermes Runtime Adapter

`examples/hermes_bridge_hermes_runtime.py` is the first FURYOKU-owned adapter for the actual Hermes CLI. It reads the validated live bridge payload from stdin, invokes exactly one `hermes chat --query ... --quiet` process, and returns a structured JSON runtime payload with:

- bridge execution key
- Symbiote id, role, and task id
- selected FURYOKU model/provider evidence
- Hermes command argv without secret values
- stdout/stderr, exit code, timeout state, elapsed timing, and recoverable error details

The adapter does not store credentials and does not mutate `JKhyro/HERMES-AGENT`. It only runs the Hermes CLI already installed in WSL.

If Hermes exits successfully while printing a terminal agent failure such as exhausted API retries or a final provider error, the adapter treats that as a recoverable runtime failure instead of a successful Symbiote execution. That keeps the bridge from advancing on a session id or setup/error transcript alone.

Current host command shape:

```powershell
python -m furyoku.cli hermes-bridge `
  --registry .\examples\model_registry.example.json `
  --envelope .\examples\hermes_bridge_one_symbiote.example.json `
  --approval-resume-record .\examples\hermes_approval_resume_gate.approved.json `
  --require-approval-resume `
  --timeout-seconds 180 `
  --handoff-command wsl -d Ubuntu python3 /mnt/c/Users/Allan/OneDrive/Documents/FURYOKU-local-model-roster-refresh/examples/hermes_bridge_hermes_runtime.py `
    --hermes-command /root/.venvs/hermes-agent-smoke/bin/hermes `
    --max-turns 1
```

If Hermes needs an explicit provider/model override for the first smoke, pass it to the adapter, not to FURYOKU routing:

```powershell
    --provider openrouter `
    --model anthropic/claude-sonnet-4.6
```

FURYOKU still records the selected model from its own routing evidence. The adapter override only tells Hermes which configured runtime provider to use for the one bounded execution.

## Hermes Provider/Auth Gate

On this host, the Hermes checkout and venv are usable. Initial execution was blocked until a provider path was supplied:

```powershell
wsl -d Ubuntu -- /root/.venvs/hermes-agent-smoke/bin/hermes status
wsl -d Ubuntu -- /root/.venvs/hermes-agent-smoke/bin/hermes chat --query "Reply with one short sentence confirming the Hermes/FURYOKU bridge received this task." --quiet --source furyoku-bridge --max-turns 1
```

Previously observed blocker:

- `/root/.hermes/.env` was not present.
- Hermes model/provider was not set.
- API-key providers and OAuth providers reported not configured.
- `hermes chat --query ...` exited before execution with first-run non-interactive setup guidance.

Minimum non-interactive configuration is provider-specific. Hermes currently suggests either setting provider environment variables such as `OPENROUTER_API_KEY` or `OPENAI_API_KEY`, or configuring a custom endpoint with:

```bash
hermes config set model.provider custom
hermes config set model.base_url http://localhost:8080/v1
hermes config set model.default your-model-name
```

OpenAI provider wiring now reaches Hermes through transient `OPENAI_API_KEY` pass-through, but the current account is quota-blocked. A successful one-Symbiote Hermes execution was proven with a transient `GH_TOKEN`/Copilot provider override and model `gpt-4.1`; no provider secret was stored or migrated.

## Three-Symbiote Smoke Contract

Issue [#238](https://github.com/JKhyro/FURYOKU/issues/238) scales the proven one-Symbiote bridge into exactly three ordered one-Symbiote handoffs. This is still not the full seven-Symbiote runtime.

Example dry-run:

```powershell
python -m furyoku.cli hermes-three-smoke `
  --registry .\examples\model_registry.example.json `
  --envelope .\examples\hermes_bridge_three_symbiote.example.json `
  --dry-run
```

Expected aggregate output contract:

- exactly three Symbiote handoff results
- ordered execution keys derived from `symbioteId`, `role`, and `taskId`
- per-Symbiote selected model, handoff status, execution status, timing, and recoverable error details
- aggregate counts for succeeded, failed, and duplicate-prevented handoffs
- no duplicate execution if two handoffs claim the same execution key

Live mode reuses the existing one-Symbiote process boundary and invokes the configured handoff command once per ordered Symbiote:

```powershell
python -m furyoku.cli hermes-three-smoke `
  --registry .\examples\model_registry.example.json `
  --envelope .\examples\hermes_bridge_three_symbiote.example.json `
  --approval-resume-ledger .\examples\hermes_approval_resume_three_smoke.approved.json `
  --require-approval-resume `
  --timeout-seconds 180 `
  --handoff-command wsl -d Ubuntu python3 /mnt/c/Users/Allan/OneDrive/Documents/FURYOKU-local-model-roster-refresh/examples/hermes_bridge_hermes_runtime.py `
    --hermes-command /root/.venvs/hermes-agent-smoke/bin/hermes `
    --provider copilot `
    --model gpt-4.1 `
    --max-turns 1
```

## Seven-Symbiote Smoke Contract

Issue [#240](https://github.com/JKhyro/FURYOKU/issues/240) scales the proven three-Symbiote smoke into exactly seven ordered one-Symbiote handoffs. This is the first full swarm-count smoke, but it still avoids broad runtime feature parity and OpenClaw carryover inventory.

Example dry-run:

```powershell
python -m furyoku.cli hermes-seven-smoke `
  --registry .\examples\model_registry.example.json `
  --envelope .\examples\hermes_bridge_seven_symbiote.example.json `
  --dry-run
```

Expected aggregate output contract:

- exactly seven Symbiote handoff results
- ordered execution keys derived from `symbioteId`, `role`, and `taskId`
- per-Symbiote selected model, handoff status, execution status, timing, and recoverable error details
- aggregate counts for succeeded, failed, and duplicate-prevented handoffs
- no duplicate execution if two handoffs claim the same execution key

Live mode reuses the one-Symbiote process boundary and invokes the configured handoff command once per ordered Symbiote:

```powershell
python -m furyoku.cli hermes-seven-smoke `
  --registry .\examples\model_registry.example.json `
  --envelope .\examples\hermes_bridge_seven_symbiote.example.json `
  --timeout-seconds 180 `
  --handoff-command wsl -d Ubuntu python3 /mnt/c/Users/Allan/OneDrive/Documents/FURYOKU-local-model-roster-refresh/examples/hermes_bridge_hermes_runtime.py `
    --hermes-command /root/.venvs/hermes-agent-smoke/bin/hermes `
    --provider copilot `
    --model gpt-4.1 `
    --max-turns 1
```

The seven-Symbiote smoke has established bounded coordination behavior for the current bridge sequence. The first OpenClaw carryover inventory completed in [#242](https://github.com/JKhyro/FURYOKU/issues/242), the routing evidence contract completed in [#244](https://github.com/JKhyro/FURYOKU/issues/244), the operator-reviewed workflow envelope completed in [#246](https://github.com/JKhyro/FURYOKU/issues/246), the execution-keyed approval/resume contract completed in [#248](https://github.com/JKhyro/FURYOKU/issues/248), and one-Symbiote approval gating completed in [#250](https://github.com/JKhyro/FURYOKU/issues/250). The active follow-on is [#252](https://github.com/JKhyro/FURYOKU/issues/252), which extends approval/resume ledger gating across multi-Symbiote smoke handoffs before durable workflow state is introduced.
