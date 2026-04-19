from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from .model_decisions import ModelDecisionReport, ReadinessEvidenceInput, evaluate_model_decisions
from .model_router import ModelEndpoint, ModelScore, RoutingScorePolicyInput, TaskProfile
from .provider_health import (
    CommandResolver,
    ProviderHealthCheckRequest,
    ProviderHealthCheckResult,
    check_provider_health_many,
)
from .task_profiles import parse_task_profile


class HermesBridgeError(ValueError):
    """Raised when a Hermes/FURYOKU bridge envelope is malformed."""


@dataclass(frozen=True)
class HermesBridgeRoutingOptions:
    """Routing controls embedded in a one-Symbiote bridge envelope."""

    check_health: bool = False
    fallback: bool = False
    max_attempts: int | None = None
    health_probe: bool = False
    health_probe_prompt: str = ""
    health_timeout_seconds: float | None = 5.0

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None, *, source: str = "<memory>") -> "HermesBridgeRoutingOptions":
        if payload is None:
            return cls()
        if not isinstance(payload, Mapping):
            raise HermesBridgeError(f"{source}: routing must be a JSON object")
        max_attempts = _optional_positive_int(payload.get("maxAttempts", payload.get("max_attempts")), field_name="maxAttempts", source=source)
        fallback = bool(payload.get("fallback", False))
        if max_attempts is not None and not fallback:
            raise HermesBridgeError(f"{source}: routing.maxAttempts requires routing.fallback=true")
        return cls(
            check_health=bool(payload.get("checkHealth", payload.get("check_health", False))),
            fallback=fallback,
            max_attempts=max_attempts,
            health_probe=bool(payload.get("healthProbe", payload.get("health_probe", False))),
            health_probe_prompt=str(payload.get("healthProbePrompt", payload.get("health_probe_prompt", "")) or ""),
            health_timeout_seconds=_optional_positive_float(
                payload.get("healthTimeoutSeconds", payload.get("health_timeout_seconds", 5.0)),
                field_name="healthTimeoutSeconds",
                source=source,
            ),
        )

    def to_dict(self) -> dict:
        return {
            "checkHealth": self.check_health,
            "fallback": self.fallback,
            "maxAttempts": self.max_attempts,
            "healthProbe": self.health_probe,
            "healthProbePrompt": self.health_probe_prompt,
            "healthTimeoutSeconds": self.health_timeout_seconds,
        }


@dataclass(frozen=True)
class HermesBridgeEnvelope:
    """One bounded Symbiote task envelope prepared for Hermes/FURYOKU handoff."""

    schema_version: int
    symbiote_id: str
    role: str
    task: TaskProfile
    prompt: str
    routing: HermesBridgeRoutingOptions = HermesBridgeRoutingOptions()

    @property
    def execution_key(self) -> str:
        return f"{self.symbiote_id}:{self.role}:{self.task.task_id}"

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any], *, source: str = "<memory>") -> "HermesBridgeEnvelope":
        if not isinstance(payload, Mapping):
            raise HermesBridgeError(f"{source}: bridge envelope must be a JSON object")
        if payload.get("symbiotes") is not None:
            raise HermesBridgeError(f"{source}: bridge envelope must describe exactly one Symbiote, not a symbiotes array")
        if payload.get("tasks") is not None:
            raise HermesBridgeError(f"{source}: bridge envelope must describe exactly one task, not a tasks array")

        schema_version = int(payload.get("schemaVersion", payload.get("schema_version", 1)) or 1)
        if schema_version != 1:
            raise HermesBridgeError(f"{source}: unsupported bridge envelope schemaVersion {schema_version!r}")

        symbiote_id = _required_string(payload, "symbioteId", "symbiote_id", source=source)
        role = _required_string(payload, "role", source=source)
        prompt = _required_string(payload, "prompt", source=source)

        raw_task = payload.get("task")
        if not isinstance(raw_task, Mapping):
            raise HermesBridgeError(f"{source}: task must be a JSON object")
        try:
            task = parse_task_profile(_normalize_bridge_task_payload(raw_task), source=f"{source}:task")
        except ValueError as exc:
            raise HermesBridgeError(str(exc)) from exc

        return cls(
            schema_version=schema_version,
            symbiote_id=symbiote_id,
            role=role,
            task=task,
            prompt=prompt,
            routing=HermesBridgeRoutingOptions.from_dict(payload.get("routing"), source=f"{source}:routing"),
        )

    def to_dict(self) -> dict:
        return {
            "schemaVersion": self.schema_version,
            "symbioteId": self.symbiote_id,
            "role": self.role,
            "task": self.task.to_dict(),
            "prompt": self.prompt,
            "routing": self.routing.to_dict(),
            "executionKey": self.execution_key,
        }


@dataclass(frozen=True)
class HermesBridgeDryRunResult:
    """Structured dry-run result for the first Hermes/FURYOKU one-Symbiote bridge."""

    envelope: HermesBridgeEnvelope
    handoff_status: str
    execution_status: str
    selected: ModelScore | None
    report: ModelDecisionReport | None
    readiness: tuple[ProviderHealthCheckResult, ...]
    elapsed_ms: float
    duplicate: bool = False
    error: Mapping[str, Any] | None = None

    @property
    def ok(self) -> bool:
        return self.handoff_status == "dry-run-ready" and self.selected is not None and self.selected.eligible

    def to_dict(self) -> dict:
        return {
            "schemaVersion": 1,
            "ok": self.ok,
            "mode": "dry_run",
            "bridge": "hermes-furyoku",
            "envelope": self.envelope.to_dict(),
            "selectedModel": _score_to_dict(self.selected) if self.selected is not None else None,
            "handoff": {
                "status": self.handoff_status,
                "dryRun": True,
                "runtime": "Hermes/FURYOKU",
                "boundary": "FURYOKU routing and envelope validation only; Hermes runtime was not invoked",
            },
            "execution": {
                "status": self.execution_status,
                "started": False,
                "elapsedMs": round(self.elapsed_ms, 3),
            },
            "duplicateGuard": {
                "enabled": True,
                "executionKey": self.envelope.execution_key,
                "duplicate": self.duplicate,
            },
            "readiness": [_health_to_dict(result) for result in self.readiness],
            "decisionReport": self.report.to_dict() if self.report is not None else None,
            "error": dict(self.error) if self.error is not None else None,
        }


def load_hermes_bridge_envelope(path: str | Path) -> HermesBridgeEnvelope:
    envelope_path = Path(path)
    with envelope_path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    return HermesBridgeEnvelope.from_dict(payload, source=str(envelope_path))


def dry_run_hermes_bridge(
    models: list[ModelEndpoint],
    envelope: HermesBridgeEnvelope,
    *,
    seen_execution_keys: Iterable[str] | None = None,
    readiness: ReadinessEvidenceInput | None = None,
    routing_policy: RoutingScorePolicyInput | None = None,
    command_resolver: CommandResolver | None = None,
) -> HermesBridgeDryRunResult:
    """Validate one Symbiote handoff and select its FURYOKU model without invoking Hermes."""

    started = time.perf_counter()
    seen_keys = set(seen_execution_keys or ())
    if envelope.execution_key in seen_keys:
        return HermesBridgeDryRunResult(
            envelope=envelope,
            handoff_status="duplicate-prevented",
            execution_status="skipped",
            selected=None,
            report=None,
            readiness=(),
            elapsed_ms=_elapsed_ms(started),
            duplicate=True,
            error={
                "recoverable": True,
                "code": "duplicate_execution_key",
                "message": f"duplicate Symbiote execution prevented for {envelope.execution_key}",
            },
        )

    resolved_readiness = readiness
    readiness_results = _provider_health_results(readiness)
    if envelope.routing.check_health and readiness is None:
        readiness_results = tuple(
            check_provider_health_many(
                models,
                ProviderHealthCheckRequest(
                    probe=envelope.routing.health_probe,
                    probe_prompt=envelope.routing.health_probe_prompt,
                    timeout_seconds=envelope.routing.health_timeout_seconds,
                ),
                command_resolver=command_resolver,
            )
        )
        resolved_readiness = readiness_results

    report = evaluate_model_decisions(
        models,
        [envelope.task],
        readiness=resolved_readiness or None,
        routing_policy=routing_policy,
    )
    selected = report.selected_for(envelope.task.task_id)
    if selected is None:
        return HermesBridgeDryRunResult(
            envelope=envelope,
            handoff_status="routing-blocked",
            execution_status="not-started",
            selected=None,
            report=report,
            readiness=readiness_results,
            elapsed_ms=_elapsed_ms(started),
            error={
                "recoverable": True,
                "code": "no_eligible_model",
                "message": _blocked_summary(report, envelope.task.task_id),
            },
        )

    return HermesBridgeDryRunResult(
        envelope=envelope,
        handoff_status="dry-run-ready",
        execution_status="not-started",
        selected=selected,
        report=report,
        readiness=readiness_results,
        elapsed_ms=_elapsed_ms(started),
    )


def _provider_health_results(readiness: ReadinessEvidenceInput | None) -> tuple[ProviderHealthCheckResult, ...]:
    if readiness is None:
        return ()
    values = readiness.values() if isinstance(readiness, Mapping) else readiness
    return tuple(item for item in values if isinstance(item, ProviderHealthCheckResult))


def _blocked_summary(report: ModelDecisionReport, task_id: str) -> str:
    decision = report.situations[task_id]
    if not decision.blockers:
        return f"no eligible model satisfied task {task_id}"
    return "; ".join(
        f"{model_id}: {', '.join(blockers)}"
        for model_id, blockers in decision.blockers.items()
    )


def _normalize_bridge_task_payload(payload: Mapping[str, Any]) -> dict:
    normalized = dict(payload)
    privacy = normalized.get("privacyRequirement", normalized.get("privacy_requirement"))
    if privacy == "local_preferred":
        normalized["privacyRequirement"] = "prefer_local"
    return normalized


def _score_to_dict(selection: ModelScore) -> dict:
    payload = {
        "modelId": selection.model.model_id,
        "provider": selection.model.provider,
        "score": selection.score,
        "eligible": selection.eligible,
        "averageLatencyMs": selection.model.average_latency_ms,
        "reasons": list(selection.reasons),
        "blockers": list(selection.blockers),
    }
    total_cost_per_1k = selection.model.input_cost_per_1k + selection.model.output_cost_per_1k
    if selection.model.input_cost_per_1k > 0.0:
        payload["inputCostPer1k"] = selection.model.input_cost_per_1k
    if selection.model.output_cost_per_1k > 0.0:
        payload["outputCostPer1k"] = selection.model.output_cost_per_1k
    if total_cost_per_1k > 0.0:
        payload["totalCostPer1k"] = round(total_cost_per_1k, 6)
    return payload


def _health_to_dict(result: ProviderHealthCheckResult) -> dict:
    payload = {
        "modelId": result.model_id,
        "provider": result.provider,
        "status": result.status,
        "ready": result.ready,
        "reason": result.reason,
        "command": result.command,
        "resolvedCommand": result.resolved_command,
    }
    if result.execution is not None:
        payload["execution"] = {
            "status": result.execution.status,
            "elapsedMs": result.execution.elapsed_ms,
            "exitCode": result.execution.exit_code,
            "stderr": result.execution.stderr,
            "error": result.execution.error,
            "timedOut": result.execution.timed_out,
        }
    return payload


def _required_string(payload: Mapping[str, Any], *keys: str, source: str) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    display_key = keys[0]
    raise HermesBridgeError(f"{source}: {display_key} is required")


def _optional_positive_int(value: Any, *, field_name: str, source: str) -> int | None:
    if value in (None, ""):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise HermesBridgeError(f"{source}: {field_name} must be an integer") from exc
    if parsed < 1:
        raise HermesBridgeError(f"{source}: {field_name} must be at least 1")
    return parsed


def _optional_positive_float(value: Any, *, field_name: str, source: str) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise HermesBridgeError(f"{source}: {field_name} must be numeric") from exc
    if parsed <= 0.0:
        raise HermesBridgeError(f"{source}: {field_name} must be greater than 0")
    return parsed


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000.0
