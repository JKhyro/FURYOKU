# Execution-Keyed Approval/Resume Contract

Tracked by [issue #248](https://github.com/JKhyro/FURYOKU/issues/248) under parent [#230](https://github.com/JKhyro/FURYOKU/issues/230).

## Purpose

FURYOKU now has a typed operator-reviewed workflow envelope for one Hermes/FURYOKU handoff. This contract defines the approval and resume record that can govern that handoff before any durable workflow state is added.

The contract is execution-keyed, not scheduler-owned. It records approval, rejection, and explicit resume intent for a handoff already described by the [operator-reviewed workflow envelope](operator-reviewed-workflow-envelope.md). It does not execute Hermes, persist state, or create a workflow runtime.

Issue [#250](https://github.com/JKhyro/FURYOKU/issues/250) wires this contract into the live Hermes bridge. When a live one-Symbiote handoff is run with approval required, FURYOKU evaluates the approval/resume record after dry-run routing succeeds and before invoking the external Hermes process boundary.

## Identity

Each record binds these fields:

| Field | Required | Meaning |
| --- | --- | --- |
| `workflowId` | Yes | The workflow envelope contract id. |
| `executionId` | Yes | The caller-owned execution id from the workflow envelope. |
| `handoffExecutionKey` | Yes | The nested one-Symbiote bridge execution key. |
| `attemptIndex` | Yes | The handoff attempt number; first attempt is `1`. |
| `owner` | Yes | The single FURYOKU/operator owner for this record. |

The derived `workflowExecutionKey` is:

```text
workflowId:executionId:handoffExecutionKey
```

The derived `recordKey` is:

```text
workflowExecutionKey:attempt:attemptIndex
```

Ledgers reject duplicate `recordKey` values. If two duplicate records claim different owners, the ledger reports ambiguous ownership.

## Record States

| `recordState` | Meaning |
| --- | --- |
| `approval_pending` | Valid record, but not safe to hand off. |
| `approved` | Safe to hand off after normal routing/provider-health checks; requires `approvedBy`. |
| `rejected` | Explicitly stopped; requires `reason`. |
| `resume_requested` | Operator requested a later attempt; requires `resume`. |
| `resume_approved` | Resume is approved and safe to hand off; requires `resume` and `approvedBy`. |
| `resumed` | Resume has already been consumed; requires `resume` and `approvedBy`. |
| `duplicate_blocked` | Duplicate execution was intentionally blocked; requires `reason`. |
| `stale_blocked` | Stale replay was intentionally blocked; requires `reason`. |

`safeToHandoff` is true only for `approved` and `resume_approved`.

## Resume Intent

Any `attemptIndex` greater than `1` requires an explicit `resume` object:

```json
{
  "resumeOf": "workflowId:executionId:handoffExecutionKey",
  "previousAttemptIndex": 1,
  "requestedBy": "operator",
  "reason": "recoverable provider timeout"
}
```

The parser rejects replay attempts without resume intent, resume records whose `resumeOf` does not match the current `workflowExecutionKey`, and resume records whose `previousAttemptIndex` is not lower than `attemptIndex`.

## Guardrails

Approval/resume records may not carry:

- hidden state: `sharedState`, `globalState`, `resumeState`, `state`, `memory`, `cache`, or `conversationHistory`
- ambiguous ownership: `owners`
- scheduler/runtime surfaces: `scheduler`, `workflowRuntime`, `handoffCommand`, or `secrets`
- multi-handoff arrays: `handoffs`, `symbiotes`, or `tasks`

These records are validation and audit artifacts only. Durable persistence, queueing, and runtime execution remain out of scope for this contract.

## Live Bridge Gate

The live bridge accepts one approval/resume record, a static ledger fixture, or a local JSON-backed approval/resume store. Multi-Symbiote smoke commands use the ledger or store to gate each ordered handoff independently. The gate blocks before process invocation when:

- `--require-approval-resume` is set and no record, ledger, or store is provided
- the record `handoffExecutionKey` does not match the bridge envelope `executionKey`
- the latest matching ledger record is not `approved` or `resume_approved`
- a ledger has multiple workflow executions for the same bridge handoff execution key
- a local store record has already been consumed by a previous handoff attempt

The live bridge result includes `approvalResumeGate` with the gate status, record state, record key, attempt index, owner, optional local-store `consumptionEvent`, and recoverable error details when blocked. Multi-Symbiote aggregate reports also list `blockedExecutionKeys`. Only `approved` and `resume_approved` records are safe to hand off.

Durable ledger ownership, replay blocking, consumption events, and persistence non-goals are defined separately in the [durable approval/resume ledger state boundary](durable-approval-resume-ledger-boundary.md). The current local adapter keeps those rules inside FURYOKU-owned approval/resume state and remains a bounded persistence scaffold, not a workflow scheduler.

Example gated live bridge:

```powershell
python -m furyoku.cli hermes-bridge `
  --registry .\examples\model_registry.example.json `
  --envelope .\examples\hermes_bridge_one_symbiote.example.json `
  --approval-resume-record .\examples\hermes_approval_resume_gate.approved.json `
  --require-approval-resume `
  --handoff-command python .\examples\hermes_bridge_echo_runtime.py
```

Example local store-backed gate:

```powershell
python -m furyoku.cli hermes-bridge `
  --registry .\examples\model_registry.example.json `
  --envelope .\examples\hermes_bridge_one_symbiote.example.json `
  --approval-resume-store .\operator-state\approval-resume-store.json `
  --require-approval-resume `
  --handoff-command python .\examples\hermes_bridge_echo_runtime.py
```

## Example

```python
from furyoku.approval_resume import load_approval_resume_ledger

ledger = load_approval_resume_ledger(
    "examples/hermes_approval_resume_contract.example.json"
)

assert ledger.records[0].safe_to_handoff is True
assert ledger.records[1].is_resume is True
```
