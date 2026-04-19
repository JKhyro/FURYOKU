# Durable Approval/Resume Ledger State Boundary

Parent lane: [#230](https://github.com/JKhyro/FURYOKU/issues/230)

Boundary issue: [#256](https://github.com/JKhyro/FURYOKU/issues/256)

Local adapter prototype issue: [#258](https://github.com/JKhyro/FURYOKU/issues/258)

Bridge integration issue: [#260](https://github.com/JKhyro/FURYOKU/issues/260)

Inspection/report issue: [#262](https://github.com/JKhyro/FURYOKU/issues/262)

Operator resume workflow issue: [#266](https://github.com/JKhyro/FURYOKU/issues/266)

Operator resume command issue: [#268](https://github.com/JKhyro/FURYOKU/issues/268)

## Purpose

FURYOKU now has approval/resume records for one-Symbiote handoffs, multi-Symbiote ledger gating, and a checked-in seven-Symbiote approval fixture. This document defines the durable state boundary that a later implementation can use without adding a second scheduler, hidden shared state, or Hermes-owned coordination state.

This boundary started as a contract only. Issue #258 added the first local JSON-backed adapter prototype for the ledger operations below, issue #260 wired that adapter into the existing bridge gate path, issue #262 added an operator-facing inspection report for the local store, issue #266 defined the bounded operator resume workflow contract, and issue #268 added the local resume record preview/append command. Durable workflow scheduling and a full runtime store remain out of scope.

## Ownership Boundary

FURYOKU owns durable approval/resume ledger state because FURYOKU already owns:

- task envelope validation
- duplicate execution prevention
- model routing and provider-health evidence
- approval/resume gate evaluation
- structured bridge and smoke reports

Hermes remains the runtime executor behind the already validated process boundary. Hermes should receive only the approved bounded task payload and runtime invocation context. Hermes must not become the authority for approval ledger state, FURYOKU routing evidence, or Symbiote duplicate-prevention keys.

## Durable State Model

The durable ledger stores versioned approval/resume records that already conform to the [execution-keyed approval/resume contract](approval-resume-contract.md). A durable store must preserve these fields exactly:

| Field | Purpose |
| --- | --- |
| `recordKey` | Stable append-only record identity. |
| `workflowExecutionKey` | Groups records for one reviewed workflow execution. |
| `handoffExecutionKey` | Binds a record to exactly one Symbiote handoff. |
| `recordState` | Approval/resume decision state. |
| `attemptIndex` | Ordered attempt number for replay control. |
| `owner` | Operator or system authority that owns the decision. |
| `createdAtUtc` | Record creation timestamp. |
| `approvedBy` / `approvedAtUtc` | Required approval identity for handoff-safe states. |
| `resume` | Required explicit resume intent for later attempts. |
| `evidence` | Non-secret links to issue, envelope, report, or operator evidence. |

The store may maintain indexes by `workflowExecutionKey`, `handoffExecutionKey`, `recordKey`, and `createdAtUtc`, but those indexes are derived from the record payload. They are not a second source of truth.

## Minimal Store Interface

A future implementation should expose a narrow interface shaped around gate evaluation:

| Operation | Input | Output | Required behavior |
| --- | --- | --- | --- |
| `append_record` | one approval/resume record | accepted record metadata or recoverable conflict | Reject duplicate `recordKey` values and ambiguous ownership for the same record key. |
| `records_for_handoff` | `handoffExecutionKey` | ordered matching records | Return records ordered by `attemptIndex`, then creation time. |
| `latest_gate_record` | `handoffExecutionKey` plus optional `workflowExecutionKey` | one record, missing, or ambiguous | Select the latest record only when all matches belong to one workflow execution. |
| `records_for_workflow` | `workflowExecutionKey` | ordered workflow records | Preserve per-handoff ordering for one-, three-, and seven-Symbiote reports. |
| `append_consumption_event` | `recordKey`, `handoffExecutionKey`, result summary | accepted event or replay conflict | Record that a safe approval was consumed by a handoff attempt without mutating the original approval record. |

The first implementation may use a local file or in-memory adapter if the interface and error behavior are the same. The boundary should not require a database before the contract is proven.

## Gate Selection Rules

A durable gate must keep the current in-memory semantics:

- If approval/resume is required and no matching record exists, block before process invocation.
- If multiple workflow executions claim the same `handoffExecutionKey`, block as ambiguous unless the caller selects an exact `workflowExecutionKey`.
- Only `approved` and `resume_approved` records are safe to hand off.
- Any attempt after attempt `1` must include valid resume intent.
- `resume.resumeOf` must match the current `workflowExecutionKey`.
- Duplicate record keys must be rejected at append time.
- Stale or already consumed records must block before invoking Hermes.

The durable gate must return recoverable error details using the same style as current bridge reports: a stable error code, a human-readable message, and any safe diagnostic keys needed by an operator.

## Consumption Events

Approval records are append-only. A future durable implementation should not rewrite `approved` or `resume_approved` records after execution. Instead, it should append a consumption event when FURYOKU starts or completes a handoff under that approval.

A consumption event may include:

- `recordKey`
- `handoffExecutionKey`
- bridge or smoke `executionKey`
- result status
- `startedAtUtc`
- `finishedAtUtc`
- recoverable error code when applicable

It must not include provider credentials, hidden memory, full conversation state, or unbounded Hermes transcripts. If transcript evidence is needed, store a non-secret reference to the structured bridge report.

## Replay And Stale Behavior

The durable boundary must make replay behavior explicit:

- A fresh first attempt uses an `approved` record with `attemptIndex` `1`.
- A retry uses `resume_approved` with `attemptIndex` greater than the previous attempt.
- A retry must reference the prior workflow execution through `resume.resumeOf`.
- A record whose `attemptIndex` is not greater than the latest consumed attempt is stale.
- A consumed approval record cannot authorize a second process invocation.
- A durable implementation may add `stale_blocked` records to explain operator decisions, but that state is never safe to hand off.

## Audit Requirements

Durable state must be auditable without becoming hidden runtime memory. Each accepted record or consumption event should allow an operator to reconstruct:

- which GitHub issue or local report authorized the handoff
- which Symbiote handoff execution key was gated
- which operator approved or resumed the handoff
- which attempt index was executed
- whether Hermes was invoked
- whether the invocation succeeded, failed, timed out, or was blocked before launch

## Non-Goals

This boundary does not authorize:

- a durable workflow scheduler
- hidden shared memory between Symbiotes
- Hermes-owned approval ledger state
- OpenClaw as the controlling runtime
- provider secret persistence
- broad runtime feature parity
- full seven-Symbiote production operation

## Compatibility

The current JSON records remain version `1`. Future durable implementations should be additive: they may add a store wrapper, indexes, or consumption events, but they should keep existing approval/resume records readable by `load_approval_resume_record` and `load_approval_resume_ledger`.

Any incompatible schema change should open a new issue and introduce an explicit version gate before current fixtures are changed.

## Local Adapter Prototype And Bridge Use

Issue #258 implements the first local durable ledger adapter in `furyoku/approval_resume.py`. Issue #260 lets live bridge and smoke commands use that adapter through `--approval-resume-store`. Together they prove:

- append and read behavior for one handoff
- latest-record selection for a multi-Symbiote ledger
- consumption event replay blocking
- JSON report compatibility with the existing bridge output contract
- operator inspection of record readiness and consumption history without invoking Hermes
- operator-approved retry records through the [operator resume workflow contract](operator-resume-workflow-contract.md)
- local preview/append support for operator resume records through `approval-resume-create`

When the bridge consumes a local-store approval record, it appends a `started` consumption event before invoking the external Hermes process boundary. That makes a second invocation with the same approval record block before process execution.

`approval-resume-store-report` gives operators a read-only report over the same local store. With a `handoffExecutionKey`, it returns the matching records, consumption events, summary counts, and gate readiness or recoverable blocking code that a bridge gate would use.

`approval-resume-create` can preview a candidate resume record, or append it with `--append`, while preserving the contract boundary: append-only records, explicit operator identity, evidence references instead of hidden memory, and no scheduler or runtime loop.

This adapter path is a bounded local persistence scaffold. It is not a durable workflow scheduler, a queue runner, or a Hermes-owned approval store.
