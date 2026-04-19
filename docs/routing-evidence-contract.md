# Hermes/FURYOKU Routing Evidence Contract

Tracked by [issue #244](https://github.com/JKhyro/FURYOKU/issues/244) under parent [#230](https://github.com/JKhyro/FURYOKU/issues/230).

## Purpose

FURYOKU retains OpenClaw-era benchmark truth as routing evidence while Hermes-derived FURYOKU remains the runtime base. This contract defines how checked-in benchmark outputs can inform model selection without becoming a second runtime, scheduler, or hidden coordination channel.

## Evidence Inputs

The first supported inputs are the existing OpenClaw local-model benchmark outputs:

- Current baseline manifest: `benchmarks/openclaw-local-llm/results/2026-04-13-approved-ready-current-baseline.json`
- Blocked-roster probe: `benchmarks/openclaw-local-llm/results/2026-04-13-approved-blocked-roster-probe.json`
- Compare summary: `benchmarks/openclaw-local-llm/results/2026-04-13-approved-ready-compare-summary.md`
- Benchmark truth workflow: `.github/workflows/benchmark-truth-gate.yml`

`furyoku.routing_evidence` normalizes those files into a `RoutingEvidenceContract` with:

- selected baseline model
- machine profile
- per-model `compareDecision`
- per-model `promotionVerdict`
- per-model `resourceFitVerdict`
- hard blocker ids
- degradation counts
- blocked-roster machine decisions

## Routing Meaning

| Evidence Signal | Routing Directive | Meaning |
| --- | --- | --- |
| `promotable=true` with no contract or resource blocker | `eligible-routing-evidence` | Model can be treated as positive benchmark evidence, subject to normal routing gates. |
| Baseline with `compareDecision=retain-baseline-at-risk` | `retain-baseline-at-risk` | Current baseline may remain as a least-bad fallback, but reports must surface risk. |
| Candidate with blocked promotion or resource fit | `do-not-promote` | Model must not be promoted or auto-selected from benchmark evidence. |
| Blocked-roster `exclude-*` machine decision | `exclude` | Model stays out of automatic local routing until new evidence clears the exclusion. |
| Blocked-roster manual review or benchmark-before-use state | `manual-review` or `benchmark-before-use` | Model needs operator or benchmark proof before use. |
| Missing benchmark evidence | `missing-evidence` | Benchmark truth is silent; normal routing may still consider other evidence, but must not infer approval. |

## Non-Bypass Rules

Benchmark truth is evidence only. It must not bypass:

- task capability requirements
- privacy requirements
- provider health checks
- duplicate execution guards

Provider health remains live execution truth. Benchmark truth can demote, block, or annotate routing decisions, but it should not force execution when the provider is unavailable or the task profile does not fit.

## Error Behavior

The contract parser raises `RoutingEvidenceError` when:

- the evidence root is not a JSON object
- `schemaVersion` is unsupported
- the baseline manifest lacks a non-empty `models` object
- a model entry has a mismatched key and `model` field
- blocked-roster evidence lacks a `results` array

## Compatibility Notes

- Schema version `1` is the only accepted version.
- The current parser accepts existing checked-in benchmark truth without rewriting it.
- Future evidence files should add fields rather than changing the meaning of existing directives.
- Carryover implementation issues should consume this contract instead of reading benchmark JSON ad hoc.

## Example

```python
from furyoku.routing_evidence import load_routing_evidence_contract

contract = load_routing_evidence_contract(
    "benchmarks/openclaw-local-llm/results/2026-04-13-approved-ready-current-baseline.json",
    blocked_roster_path="benchmarks/openclaw-local-llm/results/2026-04-13-approved-blocked-roster-probe.json",
)

assert contract.routing_directive_for("gemma4-e4b-ultra-heretic:q8_0") == "retain-baseline-at-risk"
```
