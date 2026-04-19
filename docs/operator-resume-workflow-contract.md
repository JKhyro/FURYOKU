# Operator Resume Workflow Contract

Tracked by [issue #266](https://github.com/JKhyro/FURYOKU/issues/266) under parent [#230](https://github.com/JKhyro/FURYOKU/issues/230).

## Purpose

This contract defines the bounded operator workflow for turning a consumed or blocked local approval/resume store report into a new append-only resume approval record. It extends the existing [execution-keyed approval/resume contract](approval-resume-contract.md) without adding a scheduler, queue runner, hidden shared state, Hermes-owned ledger, or automatic retry loop.

The workflow is local and operator-driven. It does not invoke Hermes, launch Ubuntu or WSL, mutate OpenClaw, or write provider secrets.

## Required Inputs

An operator resume decision must start from explicit evidence:

| Input | Required | Meaning |
| --- | --- | --- |
| `handoffExecutionKey` | Yes | The exact Symbiote handoff key being resumed. |
| `workflowExecutionKey` | Yes | The workflow execution being resumed. This disambiguates repeated handoff keys. |
| `previousAttemptIndex` | Yes | The last attempted or consumed approval attempt. |
| `consumptionEvent` | Yes | Evidence that the prior approval was consumed or attempted. |
| `requestedBy` | Yes | Operator or system identity requesting the retry. |
| `reason` | Yes | Human-readable reason for the retry. |
| `evidence` | Yes | Non-secret references to the store report, issue, bridge report, or operator review. |

The operator should obtain these values from `approval-resume-store-report`, the bridge/smoke report, and the governing GitHub issue. If the report is ambiguous, the operator must select the exact `workflowExecutionKey` before preparing a resume record.

## Workflow

1. Run `approval-resume-store-report` with the target `handoffExecutionKey`.
2. If the report returns multiple workflow execution keys, rerun with the exact `workflowExecutionKey`.
3. Confirm the latest consumed record and its `attemptIndex`.
4. Decide whether the retry is justified by a recoverable failure, timeout, operator correction, or another explicit reason.
5. Create a new approval/resume record with `attemptIndex` greater than the consumed attempt.
6. Set `resume.resumeOf` to the exact `workflowExecutionKey` and `resume.previousAttemptIndex` to the consumed attempt.
7. Use `resume_requested` when the operator is recording intent only.
8. Use `resume_approved` only when the operator has approved the retry and the record is safe to hand off.
9. Append the new record to the FURYOKU-owned approval/resume store through `approval-resume-create --append` or an explicitly reviewed store update.
10. Re-run `approval-resume-store-report` before any live handoff to confirm the selected record is ready and not already consumed.

## Output Record

A resume approval record remains schema version `1` and uses the same identity fields as the original approval record. The only safe retry state is `resume_approved`.

Required output behavior:

- `attemptIndex` must be greater than `resume.previousAttemptIndex`.
- `resume.resumeOf` must equal the current `workflowExecutionKey`.
- `resume.previousAttemptIndex` must identify the consumed or failed prior attempt.
- `resume.requestedBy` and `resume.reason` must be non-empty.
- `approvedBy` and `approvedAtUtc` are required for `resume_approved`.
- `evidence` must contain safe references only; no provider secrets, hidden memory, full transcripts, scheduler payloads, or runtime command state.

## Blocking Behavior

The operator resume workflow must block before preparing or using a retry approval when:

- the local store report is missing the target `handoffExecutionKey`
- the report contains multiple workflow execution keys and none is selected
- there is no consumption event or equivalent bridge report evidence for the previous attempt
- the new `attemptIndex` is not greater than the previous attempt
- `resume.resumeOf` does not match the exact workflow execution key
- the record carries hidden state, secrets, scheduler fields, runtime commands, multi-handoff arrays, or broad Hermes/OpenClaw state
- the selected retry approval has already been consumed
- the retry reason is not recoverable or explicitly operator-approved

Blocking records may use `stale_blocked`, `duplicate_blocked`, or `rejected` to preserve operator decisions, but those states are never safe to hand off.

## Example

The checked-in fixture [operator_resume_workflow.example.json](../examples/operator_resume_workflow.example.json) shows a consumed first attempt followed by a safe `resume_approved` record for attempt `2`. It parses through the existing approval/resume contract and does not launch Hermes.

## Non-Goals

This contract does not authorize:

- an automatic retry loop
- a durable workflow scheduler
- a queue runner
- broad runtime state persistence
- Hermes-owned approval state
- OpenClaw as the controlling runtime
- provider secret persistence
- full seven-Symbiote production operation

Issue [#268](https://github.com/JKhyro/FURYOKU/issues/268) adds the bounded local command to preview or append resume approval records while preserving this contract.
