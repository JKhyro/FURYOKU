# Operator-Reviewed Hermes Workflow Envelope

Tracked by [issue #246](https://github.com/JKhyro/FURYOKU/issues/246) under parent [#230](https://github.com/JKhyro/FURYOKU/issues/230).

## Purpose

This prototype carries forward the useful OpenClaw/Lobster idea of typed operator workflows without making OpenClaw, a second scheduler, or hidden shared state part of the Hermes-derived FURYOKU runtime.

The envelope is FURYOKU-owned and intentionally narrow: it wraps exactly one existing Hermes/FURYOKU bridge handoff with explicit workflow identity, execution identity, operator review state, and evidence references.

## Envelope Fields

| Field | Required | Meaning |
| --- | --- | --- |
| `schemaVersion` | Yes | Version `1` is the only accepted schema. |
| `workflowId` | Yes | Stable workflow contract identifier. |
| `executionId` | Yes | Caller-owned execution identity for the reviewed handoff. |
| `createdAtUtc` | No | Creation timestamp for operator/audit display. |
| `review` | Yes | Operator approval boundary. |
| `handoff` | Yes | Existing one-Symbiote `HermesBridgeEnvelope` payload. |
| `evidence` | No | String references to issue, docs, routing evidence, or review evidence. |

The derived `workflowExecutionKey` is:

```text
workflowId:executionId:symbioteId:role:taskId
```

This makes approval and later resume behavior keyable without adding hidden mutable state.

## Review States

| `review.approvalState` | Meaning |
| --- | --- |
| `approval_required` | Envelope is valid, but must not be handed to Hermes yet. |
| `approved` | Envelope can be handed off after normal routing/provider-health gates; `approvedBy` is required. |
| `rejected` | Envelope is intentionally stopped; `reason` is required. |

The parser exposes `safeToHandoff=true` only for `approved` envelopes. It does not execute the handoff.

## Guardrails

The prototype rejects root fields that would create hidden state, unclear ownership, or a second runtime:

- `sharedState`, `globalState`, `resumeState`, `state`, `memory`, `cache`, or `conversationHistory`
- `handoffs`, `symbiotes`, or `tasks` arrays
- `scheduler`, `workflowRuntime`, `handoffCommand`, or `secrets`

The nested `handoff` is still validated by the existing one-Symbiote bridge contract, so multi-Symbiote payloads are rejected at the bridge boundary.

## Example

```python
from furyoku.workflow_envelope import load_operator_reviewed_workflow_envelope

envelope = load_operator_reviewed_workflow_envelope(
    "examples/operator_reviewed_hermes_workflow.example.json"
)

assert envelope.safe_to_handoff is False
assert envelope.handoff.execution_key == "symbiote-01:primary:hermes.bridge.one-symbiote"
```

The checked-in example stays in `approval_required` state so it can be loaded and validated without starting Hermes.
