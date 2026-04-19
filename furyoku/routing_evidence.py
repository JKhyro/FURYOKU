from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


class RoutingEvidenceError(ValueError):
    """Raised when retained benchmark evidence cannot be used as routing evidence."""


@dataclass(frozen=True)
class BenchmarkModelEvidence:
    """OpenClaw-era benchmark truth normalized for Hermes/FURYOKU routing."""

    model_id: str
    role: str
    compare_decision: str
    promotion_verdict: str
    resource_fit_verdict: str
    promotable: bool
    compare_summary: str = ""
    blocking_failure_count: int = 0
    degradation_count: int = 0
    resource_blocking_failure_count: int = 0
    resource_degradation_count: int = 0
    blocking_failure_ids: tuple[str, ...] = ()
    resource_blocking_failure_ids: tuple[str, ...] = ()
    suites: tuple[str, ...] = ()
    metrics: Mapping[str, Any] = field(default_factory=dict)
    machine_profile: Mapping[str, Any] = field(default_factory=dict)

    @property
    def retained_baseline_at_risk(self) -> bool:
        return self.role == "baseline" and self.compare_decision == "retain-baseline-at-risk"

    @property
    def contract_blocked(self) -> bool:
        return self.promotion_verdict == "blocked" or self.blocking_failure_count > 0

    @property
    def resource_blocked(self) -> bool:
        return self.resource_fit_verdict == "blocked" or self.resource_blocking_failure_count > 0

    @property
    def routing_directive(self) -> str:
        if self.retained_baseline_at_risk:
            return "retain-baseline-at-risk"
        if self.promotable and not self.contract_blocked and not self.resource_blocked:
            return "eligible-routing-evidence"
        if self.compare_decision.startswith("candidate-blocked") or self.contract_blocked or self.resource_blocked:
            return "do-not-promote"
        return "evidence-only"

    @property
    def hard_blocker_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((*self.blocking_failure_ids, *self.resource_blocking_failure_ids)))

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any], *, source: str) -> "BenchmarkModelEvidence":
        if not isinstance(payload, Mapping):
            raise RoutingEvidenceError(f"{source}: model evidence must be an object")
        model_id = _required_str(payload, "model", source=source)
        return cls(
            model_id=model_id,
            role=_optional_str(payload, "role", default="candidate"),
            compare_decision=_optional_str(payload, "compareDecision", default="evidence-only"),
            promotion_verdict=_optional_str(payload, "promotionVerdict", default="unknown"),
            resource_fit_verdict=_optional_str(payload, "resourceFitVerdict", default="unknown"),
            promotable=bool(payload.get("promotable", False)),
            compare_summary=_optional_str(payload, "compareSummary", default=""),
            blocking_failure_count=_optional_int(payload, "blockingFailureCount"),
            degradation_count=_optional_int(payload, "degradationCount"),
            resource_blocking_failure_count=_optional_int(payload, "resourceBlockingFailureCount"),
            resource_degradation_count=_optional_int(payload, "resourceDegradationCount"),
            blocking_failure_ids=_str_tuple(payload.get("blockingFailureIds", ())),
            resource_blocking_failure_ids=_str_tuple(payload.get("resourceBlockingFailureIds", ())),
            suites=_str_tuple(payload.get("suites", ())),
            metrics=_mapping(payload.get("metrics", {}), source=f"{source}: {model_id}.metrics"),
            machine_profile=_mapping(
                payload.get("machineProfile", {}),
                source=f"{source}: {model_id}.machineProfile",
            ),
        )

    def to_dict(self) -> dict:
        return {
            "modelId": self.model_id,
            "role": self.role,
            "routingDirective": self.routing_directive,
            "compareDecision": self.compare_decision,
            "promotionVerdict": self.promotion_verdict,
            "resourceFitVerdict": self.resource_fit_verdict,
            "promotable": self.promotable,
            "retainedBaselineAtRisk": self.retained_baseline_at_risk,
            "contractBlocked": self.contract_blocked,
            "resourceBlocked": self.resource_blocked,
            "compareSummary": self.compare_summary,
            "blockingFailureCount": self.blocking_failure_count,
            "degradationCount": self.degradation_count,
            "resourceBlockingFailureCount": self.resource_blocking_failure_count,
            "resourceDegradationCount": self.resource_degradation_count,
            "blockingFailureIds": list(self.blocking_failure_ids),
            "resourceBlockingFailureIds": list(self.resource_blocking_failure_ids),
            "hardBlockerIds": list(self.hard_blocker_ids),
            "suites": list(self.suites),
            "metrics": dict(self.metrics),
            "machineProfile": dict(self.machine_profile),
        }


@dataclass(frozen=True)
class BlockedRosterEvidence:
    """Second-stage local machine-fit evidence for models excluded from routing."""

    model_id: str
    machine_decision: str
    reason: str = ""
    initial_availability_status: str = ""
    initial_probe_status: str = ""
    second_stage_probe_status: str = ""
    candidate_role: str = ""
    candidate_priority: int = 0

    @property
    def routing_directive(self) -> str:
        if self.machine_decision.startswith("exclude-"):
            return "exclude"
        if self.machine_decision == "manual-review":
            return "manual-review"
        if self.machine_decision == "promote-to-full-benchmark":
            return "benchmark-before-use"
        return "evidence-only"

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any], *, source: str) -> "BlockedRosterEvidence":
        if not isinstance(payload, Mapping):
            raise RoutingEvidenceError(f"{source}: blocked roster entry must be an object")
        return cls(
            model_id=_required_str(payload, "model", source=source),
            machine_decision=_optional_str(payload, "machineDecision", default="evidence-only"),
            reason=_optional_str(payload, "reason", default=""),
            initial_availability_status=_optional_str(payload, "initialAvailabilityStatus", default=""),
            initial_probe_status=_optional_str(payload, "initialProbeStatus", default=""),
            second_stage_probe_status=_optional_str(payload, "secondStageProbeStatus", default=""),
            candidate_role=_optional_str(payload, "candidateRole", default=""),
            candidate_priority=_optional_int(payload, "candidatePriority"),
        )

    def to_dict(self) -> dict:
        return {
            "modelId": self.model_id,
            "routingDirective": self.routing_directive,
            "machineDecision": self.machine_decision,
            "reason": self.reason,
            "initialAvailabilityStatus": self.initial_availability_status,
            "initialProbeStatus": self.initial_probe_status,
            "secondStageProbeStatus": self.second_stage_probe_status,
            "candidateRole": self.candidate_role,
            "candidatePriority": self.candidate_priority,
        }


@dataclass(frozen=True)
class RoutingEvidenceContract:
    """Contract FURYOKU uses to consume retained benchmark truth."""

    generated_at_utc: str
    selected_baseline_model: str | None
    machine_profile: Mapping[str, Any]
    models: Mapping[str, BenchmarkModelEvidence]
    blocked_roster: Mapping[str, BlockedRosterEvidence] = field(default_factory=dict)
    source: str = "<memory>"
    evidence_files: tuple[str, ...] = ()
    summary_output: str | None = None

    @property
    def retained_model_ids(self) -> tuple[str, ...]:
        return tuple(
            model_id
            for model_id, evidence in self.models.items()
            if evidence.routing_directive in {"eligible-routing-evidence", "retain-baseline-at-risk"}
        )

    @property
    def blocked_model_ids(self) -> tuple[str, ...]:
        blocked = [
            model_id
            for model_id, evidence in self.models.items()
            if evidence.routing_directive == "do-not-promote"
        ]
        blocked.extend(
            model_id
            for model_id, evidence in self.blocked_roster.items()
            if evidence.routing_directive == "exclude"
        )
        return tuple(dict.fromkeys(blocked))

    @property
    def manual_review_model_ids(self) -> tuple[str, ...]:
        return tuple(
            model_id
            for model_id, evidence in self.blocked_roster.items()
            if evidence.routing_directive in {"manual-review", "benchmark-before-use"}
        )

    def routing_directive_for(self, model_id: str) -> str:
        blocked_roster_evidence = self.blocked_roster.get(model_id)
        if blocked_roster_evidence and blocked_roster_evidence.routing_directive != "evidence-only":
            return blocked_roster_evidence.routing_directive
        model_evidence = self.models.get(model_id)
        if model_evidence:
            return model_evidence.routing_directive
        return "missing-evidence"

    def hard_blocker_ids_for(self, model_id: str) -> tuple[str, ...]:
        model_evidence = self.models.get(model_id)
        if not model_evidence:
            return ()
        return model_evidence.hard_blocker_ids

    def to_dict(self) -> dict:
        return {
            "schemaVersion": 1,
            "source": self.source,
            "generatedAtUtc": self.generated_at_utc,
            "selectedBaselineModel": self.selected_baseline_model,
            "machineProfile": dict(self.machine_profile),
            "routingSemantics": {
                "authority": "evidence-only",
                "mustNotBypass": [
                    "task_capability_requirements",
                    "privacy_requirements",
                    "provider_health",
                    "duplicate_execution_guard",
                ],
                "hardBlockerMeaning": "model must not be promoted or auto-selected unless later evidence clears the blocker",
                "retainedBaselineAtRiskMeaning": "baseline can remain as least-bad fallback, but reports must surface risk",
            },
            "retainedModelIds": list(self.retained_model_ids),
            "blockedModelIds": list(self.blocked_model_ids),
            "manualReviewModelIds": list(self.manual_review_model_ids),
            "models": {model_id: evidence.to_dict() for model_id, evidence in self.models.items()},
            "blockedRoster": {
                model_id: evidence.to_dict() for model_id, evidence in self.blocked_roster.items()
            },
            "evidenceFiles": list(self.evidence_files),
            "summaryOutput": self.summary_output,
        }


def load_routing_evidence_contract(
    current_baseline_path: str | Path,
    *,
    blocked_roster_path: str | Path | None = None,
) -> RoutingEvidenceContract:
    baseline_path = Path(current_baseline_path)
    baseline_payload = _load_json(baseline_path)
    blocked_payload = _load_json(Path(blocked_roster_path)) if blocked_roster_path else None
    return parse_routing_evidence_contract(
        baseline_payload,
        blocked_roster_payload=blocked_payload,
        source=str(baseline_path),
    )


def parse_routing_evidence_contract(
    payload: Mapping[str, Any],
    *,
    blocked_roster_payload: Mapping[str, Any] | None = None,
    source: str = "<memory>",
) -> RoutingEvidenceContract:
    if not isinstance(payload, Mapping):
        raise RoutingEvidenceError(f"{source}: routing evidence must be an object")
    schema_version = payload.get("schemaVersion", 1)
    if schema_version != 1:
        raise RoutingEvidenceError(f"{source}: unsupported routing evidence schemaVersion {schema_version!r}")

    raw_models = payload.get("models")
    if not isinstance(raw_models, Mapping) or not raw_models:
        raise RoutingEvidenceError(f"{source}: routing evidence requires non-empty models object")

    models: dict[str, BenchmarkModelEvidence] = {}
    for model_id, raw_model in raw_models.items():
        evidence = BenchmarkModelEvidence.from_dict(raw_model, source=f"{source}: models.{model_id}")
        if evidence.model_id != str(model_id):
            raise RoutingEvidenceError(
                f"{source}: models.{model_id} has mismatched model field {evidence.model_id!r}"
            )
        models[evidence.model_id] = evidence

    return RoutingEvidenceContract(
        generated_at_utc=_optional_str(payload, "generatedAtUtc", default=""),
        selected_baseline_model=_optional_nullable_str(payload, "selectedBaselineModel"),
        machine_profile=_mapping(payload.get("machineProfile", {}), source=f"{source}: machineProfile"),
        models=models,
        blocked_roster=_parse_blocked_roster(blocked_roster_payload, source=source),
        source=source,
        evidence_files=_str_tuple(payload.get("evidenceFiles", ())),
        summary_output=_optional_nullable_str(payload, "summaryOutput"),
    )


def _parse_blocked_roster(
    payload: Mapping[str, Any] | None,
    *,
    source: str,
) -> dict[str, BlockedRosterEvidence]:
    if payload is None:
        return {}
    if not isinstance(payload, Mapping):
        raise RoutingEvidenceError(f"{source}: blocked roster evidence must be an object")
    raw_results = payload.get("results", ())
    if not isinstance(raw_results, list):
        raise RoutingEvidenceError(f"{source}: blocked roster evidence requires results array")
    blocked: dict[str, BlockedRosterEvidence] = {}
    for index, raw_item in enumerate(raw_results):
        evidence = BlockedRosterEvidence.from_dict(raw_item, source=f"{source}: blockedRoster[{index}]")
        blocked[evidence.model_id] = evidence
    return blocked


def _load_json(path: Path) -> Mapping[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    if not isinstance(payload, Mapping):
        raise RoutingEvidenceError(f"{path}: expected JSON object")
    return payload


def _required_str(payload: Mapping[str, Any], key: str, *, source: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RoutingEvidenceError(f"{source}: missing required string field {key}")
    return value.strip()


def _optional_str(payload: Mapping[str, Any], key: str, *, default: str) -> str:
    value = payload.get(key, default)
    if value in (None, ""):
        return default
    return str(value)


def _optional_nullable_str(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value in (None, ""):
        return None
    return str(value)


def _optional_int(payload: Mapping[str, Any], key: str) -> int:
    value = payload.get(key, 0)
    if value in (None, ""):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise RoutingEvidenceError(f"field {key} must be an integer") from exc


def _str_tuple(value: Any) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    if not isinstance(value, (list, tuple)):
        return (str(value),)
    return tuple(str(item) for item in value)


def _mapping(value: Any, *, source: str) -> Mapping[str, Any]:
    if value in (None, ""):
        return {}
    if not isinstance(value, Mapping):
        raise RoutingEvidenceError(f"{source}: expected object")
    return {str(key): item for key, item in value.items()}
