from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Mapping

from .model_decisions import ModelDecisionReport, ReadinessEvidenceInput, evaluate_model_decisions
from .model_router import ModelEndpoint, ModelScore, RoutingScorePolicyInput, TaskProfile
from .provider_health import (
    CommandResolver,
    ProviderHealthCheckRequest,
    ProviderHealthCheckResult,
    check_provider_health_many,
)
from .task_profiles import parse_task_profile

if TYPE_CHECKING:
    from .approval_resume import ApprovalResumeLedger, ApprovalResumeRecord


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
class HermesBridgeThreeSymbioteSmokeEnvelope:
    """A bounded three-Symbiote smoke envelope for the next Hermes/FURYOKU scale step."""

    schema_version: int
    smoke_id: str
    symbiotes: tuple[HermesBridgeEnvelope, ...]

    @property
    def execution_keys(self) -> tuple[str, ...]:
        return tuple(symbiote.execution_key for symbiote in self.symbiotes)

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
        *,
        source: str = "<memory>",
    ) -> "HermesBridgeThreeSymbioteSmokeEnvelope":
        schema_version, smoke_id, symbiotes = _parse_symbiote_smoke_envelope(
            payload,
            expected_count=3,
            label="three-Symbiote",
            source=source,
        )
        return cls(schema_version=schema_version, smoke_id=smoke_id, symbiotes=tuple(symbiotes))

    def to_dict(self) -> dict:
        return {
            "schemaVersion": self.schema_version,
            "smokeId": self.smoke_id,
            "symbioteCount": len(self.symbiotes),
            "executionKeys": list(self.execution_keys),
            "symbiotes": [symbiote.to_dict() for symbiote in self.symbiotes],
        }


@dataclass(frozen=True)
class HermesBridgeSevenSymbioteSmokeEnvelope:
    """A bounded seven-Symbiote smoke envelope for the functional swarm gate."""

    schema_version: int
    smoke_id: str
    symbiotes: tuple[HermesBridgeEnvelope, ...]

    @property
    def execution_keys(self) -> tuple[str, ...]:
        return tuple(symbiote.execution_key for symbiote in self.symbiotes)

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
        *,
        source: str = "<memory>",
    ) -> "HermesBridgeSevenSymbioteSmokeEnvelope":
        schema_version, smoke_id, symbiotes = _parse_symbiote_smoke_envelope(
            payload,
            expected_count=7,
            label="seven-Symbiote",
            source=source,
        )
        return cls(schema_version=schema_version, smoke_id=smoke_id, symbiotes=tuple(symbiotes))

    def to_dict(self) -> dict:
        return {
            "schemaVersion": self.schema_version,
            "smokeId": self.smoke_id,
            "symbioteCount": len(self.symbiotes),
            "executionKeys": list(self.execution_keys),
            "symbiotes": [symbiote.to_dict() for symbiote in self.symbiotes],
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


@dataclass(frozen=True)
class HermesBridgeThreeSymbioteSmokeResult:
    """Aggregate result for a bounded three-Symbiote smoke run."""

    envelope: HermesBridgeThreeSymbioteSmokeEnvelope
    mode: str
    results: tuple[HermesBridgeDryRunResult | HermesBridgeLiveResult, ...]
    elapsed_ms: float
    handoff_command: tuple[str, ...] = ()
    expected_count: int = 3

    @property
    def ok(self) -> bool:
        return len(self.results) == self.expected_count and all(result.ok for result in self.results)

    def to_dict(self) -> dict:
        label = _smoke_count_label(self.expected_count)
        result_payloads = [result.to_dict() for result in self.results]
        duplicate_keys = [
            _bridge_result_execution_key(result)
            for result in self.results
            if _bridge_result_duplicate(result)
        ]
        failed_keys = [
            _bridge_result_execution_key(result)
            for result in self.results
            if not result.ok
        ]
        succeeded_keys = [
            _bridge_result_execution_key(result)
            for result in self.results
            if result.ok
        ]
        dry_run = self.mode == "dry_run"
        payload = {
            "schemaVersion": 1,
            "ok": self.ok,
            "mode": self.mode,
            "bridge": "hermes-furyoku",
            "smoke": self.envelope.to_dict(),
            "handoff": {
                "status": _aggregate_handoff_status(self.mode, self.results),
                "dryRun": dry_run,
                "runtime": "Hermes/FURYOKU",
                "boundary": f"FURYOKU routing and envelope validation with {self.expected_count} ordered one-Symbiote handoffs",
            },
            "execution": {
                "status": _aggregate_execution_status(self.mode, self.results),
                "started": any(_bridge_result_started(result) for result in self.results),
                "elapsedMs": round(self.elapsed_ms, 3),
                "ordered": True,
            },
            "aggregate": {
                "totalSymbiotes": len(self.results),
                "succeeded": len(succeeded_keys),
                "failed": len(failed_keys),
                "duplicatesPrevented": len(duplicate_keys),
                "executionKeys": [_bridge_result_execution_key(result) for result in self.results],
                "succeededExecutionKeys": succeeded_keys,
                "failedExecutionKeys": failed_keys,
            },
            "duplicateGuard": {
                "enabled": True,
                "uniqueExecutionKeys": len(set(self.envelope.execution_keys)),
                "duplicates": duplicate_keys,
            },
            "results": result_payloads,
            "error": None,
        }
        if self.handoff_command:
            payload["handoff"]["command"] = list(self.handoff_command)
        if not self.ok:
            payload["error"] = {
                "recoverable": True,
                "code": "three_symbiote_smoke_incomplete",
                "message": f"one or more {label} smoke handoffs did not complete successfully",
            }
        return payload


@dataclass(frozen=True)
class HermesBridgeSevenSymbioteSmokeResult(HermesBridgeThreeSymbioteSmokeResult):
    """Aggregate result for a bounded seven-Symbiote smoke run."""

    expected_count: int = 7

    def to_dict(self) -> dict:
        payload = super().to_dict()
        if payload["error"] is not None:
            payload["error"]["code"] = "seven_symbiote_smoke_incomplete"
        return payload


@dataclass(frozen=True)
class HermesBridgeApprovalGateResult:
    """Approval/resume gate decision for one live bridge handoff."""

    status: str
    execution_key: str
    required: bool
    safe_to_handoff: bool
    source: str = "none"
    record: ApprovalResumeRecord | None = None
    error: Mapping[str, Any] | None = None

    @property
    def ok(self) -> bool:
        return self.safe_to_handoff

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "executionKey": self.execution_key,
            "required": self.required,
            "safeToHandoff": self.safe_to_handoff,
            "source": self.source,
            "recordKey": self.record.record_key if self.record is not None else None,
            "workflowExecutionKey": self.record.workflow_execution_key if self.record is not None else None,
            "recordState": self.record.state if self.record is not None else None,
            "attemptIndex": self.record.attempt_index if self.record is not None else None,
            "owner": self.record.owner if self.record is not None else None,
            "resumable": self.record.is_resume if self.record is not None else False,
            "recordSource": self.record.source if self.record is not None else None,
            "error": dict(self.error) if self.error is not None else None,
        }


@dataclass(frozen=True)
class HermesBridgeLiveResult:
    """Structured result for a one-Symbiote Hermes/FURYOKU process-boundary handoff."""

    dry_run: HermesBridgeDryRunResult
    handoff_command: tuple[str, ...]
    handoff_status: str
    execution_status: str
    elapsed_ms: float
    started: bool = False
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    runtime_payload: Mapping[str, Any] | str | None = None
    approval_gate: HermesBridgeApprovalGateResult | None = None
    error: Mapping[str, Any] | None = None

    @property
    def ok(self) -> bool:
        return self.dry_run.ok and self.handoff_status == "completed" and self.execution_status == "succeeded"

    def to_dict(self) -> dict:
        payload = self.dry_run.to_dict()
        payload.update(
            {
                "ok": self.ok,
                "mode": "live",
                "selectedModel": _score_to_dict(self.dry_run.selected) if self.dry_run.selected is not None else None,
                "handoff": {
                    "status": self.handoff_status,
                    "dryRun": False,
                    "runtime": "Hermes/FURYOKU",
                    "boundary": "FURYOKU routing and envelope validation with one external process-boundary handoff",
                    "command": list(self.handoff_command),
                },
                "execution": {
                    "status": self.execution_status,
                    "started": self.started,
                    "elapsedMs": round(self.elapsed_ms, 3),
                    "exitCode": self.exit_code,
                    "stdout": self.stdout,
                    "stderr": self.stderr,
                    "timedOut": self.timed_out,
                    "runtimePayload": self.runtime_payload,
                },
                "error": dict(self.error) if self.error is not None else None,
            }
        )
        if self.approval_gate is not None:
            payload["approvalResumeGate"] = self.approval_gate.to_dict()
        return payload


def load_hermes_bridge_envelope(path: str | Path) -> HermesBridgeEnvelope:
    envelope_path = Path(path)
    with envelope_path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    return HermesBridgeEnvelope.from_dict(payload, source=str(envelope_path))


def load_hermes_three_symbiote_smoke(path: str | Path) -> HermesBridgeThreeSymbioteSmokeEnvelope:
    envelope_path = Path(path)
    with envelope_path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    return HermesBridgeThreeSymbioteSmokeEnvelope.from_dict(payload, source=str(envelope_path))


def load_hermes_seven_symbiote_smoke(path: str | Path) -> HermesBridgeSevenSymbioteSmokeEnvelope:
    envelope_path = Path(path)
    with envelope_path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    return HermesBridgeSevenSymbioteSmokeEnvelope.from_dict(payload, source=str(envelope_path))


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


def dry_run_three_symbiote_smoke(
    models: list[ModelEndpoint],
    envelope: HermesBridgeThreeSymbioteSmokeEnvelope,
    *,
    seen_execution_keys: Iterable[str] | None = None,
    readiness: ReadinessEvidenceInput | None = None,
    routing_policy: RoutingScorePolicyInput | None = None,
    command_resolver: CommandResolver | None = None,
) -> HermesBridgeThreeSymbioteSmokeResult:
    """Validate and route three bounded Symbiote handoffs without invoking Hermes."""

    return _dry_run_symbiote_smoke(
        models,
        envelope,
        seen_execution_keys=seen_execution_keys,
        readiness=readiness,
        routing_policy=routing_policy,
        command_resolver=command_resolver,
        result_factory=HermesBridgeThreeSymbioteSmokeResult,
    )


def dry_run_seven_symbiote_smoke(
    models: list[ModelEndpoint],
    envelope: HermesBridgeSevenSymbioteSmokeEnvelope,
    *,
    seen_execution_keys: Iterable[str] | None = None,
    readiness: ReadinessEvidenceInput | None = None,
    routing_policy: RoutingScorePolicyInput | None = None,
    command_resolver: CommandResolver | None = None,
) -> HermesBridgeSevenSymbioteSmokeResult:
    """Validate and route seven bounded Symbiote handoffs without invoking Hermes."""

    return _dry_run_symbiote_smoke(
        models,
        envelope,
        seen_execution_keys=seen_execution_keys,
        readiness=readiness,
        routing_policy=routing_policy,
        command_resolver=command_resolver,
        result_factory=HermesBridgeSevenSymbioteSmokeResult,
    )


def live_run_hermes_bridge(
    models: list[ModelEndpoint],
    envelope: HermesBridgeEnvelope,
    *,
    handoff_command: tuple[str, ...],
    seen_execution_keys: Iterable[str] | None = None,
    readiness: ReadinessEvidenceInput | None = None,
    routing_policy: RoutingScorePolicyInput | None = None,
    command_resolver: CommandResolver | None = None,
    timeout_seconds: float | None = 60.0,
    cwd: str | Path | None = None,
    approval_resume: ApprovalResumeRecord | ApprovalResumeLedger | None = None,
    require_approval_resume: bool = False,
) -> HermesBridgeLiveResult:
    """Route exactly one Symbiote task, then hand it to one configured Hermes process boundary."""

    started = time.perf_counter()
    if not handoff_command:
        raise HermesBridgeError("live Hermes bridge requires a non-empty handoff command")

    dry_run = dry_run_hermes_bridge(
        models,
        envelope,
        seen_execution_keys=seen_execution_keys,
        readiness=readiness,
        routing_policy=routing_policy,
        command_resolver=command_resolver,
    )
    if not dry_run.ok:
        return HermesBridgeLiveResult(
            dry_run=dry_run,
            handoff_command=tuple(handoff_command),
            handoff_status=dry_run.handoff_status,
            execution_status=dry_run.execution_status,
            elapsed_ms=_elapsed_ms(started),
            error=dry_run.error,
        )

    approval_gate = validate_hermes_bridge_approval_gate(
        envelope,
        approval_resume,
        required=require_approval_resume,
    )
    if not approval_gate.ok:
        return HermesBridgeLiveResult(
            dry_run=dry_run,
            handoff_command=tuple(handoff_command),
            handoff_status="approval-blocked",
            execution_status="not-started",
            elapsed_ms=_elapsed_ms(started),
            started=False,
            approval_gate=approval_gate,
            error=approval_gate.error,
        )

    handoff_payload = {
        "schemaVersion": 1,
        "bridge": "hermes-furyoku",
        "mode": "live",
        "envelope": envelope.to_dict(),
        "selectedModel": _score_to_dict(dry_run.selected) if dry_run.selected is not None else None,
        "decisionReport": dry_run.report.to_dict() if dry_run.report is not None else None,
        "readiness": [_health_to_dict(result) for result in dry_run.readiness],
        "approvalResumeGate": approval_gate.to_dict(),
    }
    try:
        completed = subprocess.run(
            list(handoff_command),
            input=json.dumps(handoff_payload),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout_seconds,
            cwd=str(cwd) if cwd is not None else None,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return HermesBridgeLiveResult(
            dry_run=dry_run,
            handoff_command=tuple(handoff_command),
            handoff_status="timeout",
            execution_status="timeout",
            elapsed_ms=_elapsed_ms(started),
            started=True,
            stdout=_coerce_text(exc.stdout),
            stderr=_coerce_text(exc.stderr),
            timed_out=True,
            approval_gate=approval_gate,
            error={
                "recoverable": True,
                "code": "handoff_timeout",
                "message": f"Hermes/FURYOKU handoff timed out after {exc.timeout} seconds",
            },
        )
    except OSError as exc:
        return HermesBridgeLiveResult(
            dry_run=dry_run,
            handoff_command=tuple(handoff_command),
            handoff_status="failed",
            execution_status="error",
            elapsed_ms=_elapsed_ms(started),
            approval_gate=approval_gate,
            error={
                "recoverable": True,
                "code": "handoff_launch_failed",
                "message": str(exc),
            },
        )

    runtime_payload = _parse_runtime_payload(completed.stdout)
    if completed.returncode != 0:
        return HermesBridgeLiveResult(
            dry_run=dry_run,
            handoff_command=tuple(handoff_command),
            handoff_status="failed",
            execution_status="error",
            elapsed_ms=_elapsed_ms(started),
            started=True,
            exit_code=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            runtime_payload=runtime_payload,
            approval_gate=approval_gate,
            error={
                "recoverable": True,
                "code": "handoff_process_failed",
                "message": f"Hermes/FURYOKU handoff exited with code {completed.returncode}",
            },
        )

    return HermesBridgeLiveResult(
        dry_run=dry_run,
        handoff_command=tuple(handoff_command),
        handoff_status="completed",
        execution_status="succeeded",
        elapsed_ms=_elapsed_ms(started),
        started=True,
        exit_code=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
        runtime_payload=runtime_payload,
        approval_gate=approval_gate,
    )


def validate_hermes_bridge_approval_gate(
    envelope: HermesBridgeEnvelope,
    approval_resume: ApprovalResumeRecord | ApprovalResumeLedger | None = None,
    *,
    required: bool = False,
) -> HermesBridgeApprovalGateResult:
    """Validate approval/resume evidence for one external Hermes/FURYOKU handoff."""

    from .approval_resume import ApprovalResumeLedger, ApprovalResumeRecord

    if approval_resume is None:
        if required:
            return HermesBridgeApprovalGateResult(
                status="blocked",
                execution_key=envelope.execution_key,
                required=required,
                safe_to_handoff=False,
                error={
                    "recoverable": True,
                    "code": "approval_resume_record_missing",
                    "message": f"approval/resume record is required for {envelope.execution_key}",
                },
            )
        return HermesBridgeApprovalGateResult(
            status="not-required",
            execution_key=envelope.execution_key,
            required=required,
            safe_to_handoff=True,
        )

    if isinstance(approval_resume, ApprovalResumeRecord):
        if approval_resume.handoff_execution_key != envelope.execution_key:
            return HermesBridgeApprovalGateResult(
                status="blocked",
                execution_key=envelope.execution_key,
                required=required,
                safe_to_handoff=False,
                source="record",
                record=approval_resume,
                error={
                    "recoverable": True,
                    "code": "approval_resume_handoff_mismatch",
                    "message": (
                        "approval/resume record is keyed to "
                        f"{approval_resume.handoff_execution_key}, not {envelope.execution_key}"
                    ),
                },
            )
        record = approval_resume
        source = "record"
    elif isinstance(approval_resume, ApprovalResumeLedger):
        records = approval_resume.records_for_handoff(envelope.execution_key)
        if not records:
            return HermesBridgeApprovalGateResult(
                status="blocked",
                execution_key=envelope.execution_key,
                required=required,
                safe_to_handoff=False,
                source="ledger",
                error={
                    "recoverable": True,
                    "code": "approval_resume_record_missing",
                    "message": f"approval/resume ledger has no record for {envelope.execution_key}",
                },
            )
        workflow_keys = {record.workflow_execution_key for record in records}
        if len(workflow_keys) > 1:
            return HermesBridgeApprovalGateResult(
                status="blocked",
                execution_key=envelope.execution_key,
                required=required,
                safe_to_handoff=False,
                source="ledger",
                error={
                    "recoverable": True,
                    "code": "approval_resume_ambiguous_handoff",
                    "message": f"approval/resume ledger has multiple workflow executions for {envelope.execution_key}",
                    "workflowExecutionKeys": sorted(workflow_keys),
                },
            )
        record = max(records, key=lambda item: item.attempt_index)
        source = "ledger"
    else:
        raise HermesBridgeError("approval_resume must be an ApprovalResumeRecord, ApprovalResumeLedger, or None")

    if not record.safe_to_handoff:
        return HermesBridgeApprovalGateResult(
            status="blocked",
            execution_key=envelope.execution_key,
            required=required,
            safe_to_handoff=False,
            source=source,
            record=record,
            error={
                "recoverable": True,
                "code": "approval_resume_not_safe",
                "message": f"approval/resume record state {record.state!r} is not safe to hand off",
            },
        )

    return HermesBridgeApprovalGateResult(
        status="resume-approved" if record.state == "resume_approved" else "approved",
        execution_key=envelope.execution_key,
        required=required,
        safe_to_handoff=True,
        source=source,
        record=record,
    )


def live_run_three_symbiote_smoke(
    models: list[ModelEndpoint],
    envelope: HermesBridgeThreeSymbioteSmokeEnvelope,
    *,
    handoff_command: tuple[str, ...],
    seen_execution_keys: Iterable[str] | None = None,
    readiness: ReadinessEvidenceInput | None = None,
    routing_policy: RoutingScorePolicyInput | None = None,
    command_resolver: CommandResolver | None = None,
    timeout_seconds: float | None = 60.0,
    cwd: str | Path | None = None,
) -> HermesBridgeThreeSymbioteSmokeResult:
    """Run three ordered one-Symbiote handoffs through one configured Hermes process boundary."""

    return _live_run_symbiote_smoke(
        models,
        envelope,
        handoff_command=handoff_command,
        seen_execution_keys=seen_execution_keys,
        readiness=readiness,
        routing_policy=routing_policy,
        command_resolver=command_resolver,
        timeout_seconds=timeout_seconds,
        cwd=cwd,
        result_factory=HermesBridgeThreeSymbioteSmokeResult,
    )


def live_run_seven_symbiote_smoke(
    models: list[ModelEndpoint],
    envelope: HermesBridgeSevenSymbioteSmokeEnvelope,
    *,
    handoff_command: tuple[str, ...],
    seen_execution_keys: Iterable[str] | None = None,
    readiness: ReadinessEvidenceInput | None = None,
    routing_policy: RoutingScorePolicyInput | None = None,
    command_resolver: CommandResolver | None = None,
    timeout_seconds: float | None = 60.0,
    cwd: str | Path | None = None,
) -> HermesBridgeSevenSymbioteSmokeResult:
    """Run seven ordered one-Symbiote handoffs through one configured Hermes process boundary."""

    return _live_run_symbiote_smoke(
        models,
        envelope,
        handoff_command=handoff_command,
        seen_execution_keys=seen_execution_keys,
        readiness=readiness,
        routing_policy=routing_policy,
        command_resolver=command_resolver,
        timeout_seconds=timeout_seconds,
        cwd=cwd,
        result_factory=HermesBridgeSevenSymbioteSmokeResult,
    )


def _dry_run_symbiote_smoke(
    models: list[ModelEndpoint],
    envelope: HermesBridgeThreeSymbioteSmokeEnvelope | HermesBridgeSevenSymbioteSmokeEnvelope,
    *,
    seen_execution_keys: Iterable[str] | None,
    readiness: ReadinessEvidenceInput | None,
    routing_policy: RoutingScorePolicyInput | None,
    command_resolver: CommandResolver | None,
    result_factory: type[HermesBridgeThreeSymbioteSmokeResult],
) -> HermesBridgeThreeSymbioteSmokeResult:
    started = time.perf_counter()
    seen_keys = set(seen_execution_keys or ())
    results: list[HermesBridgeDryRunResult] = []
    for symbiote in envelope.symbiotes:
        result = dry_run_hermes_bridge(
            models,
            symbiote,
            seen_execution_keys=seen_keys,
            readiness=readiness,
            routing_policy=routing_policy,
            command_resolver=command_resolver,
        )
        results.append(result)
        if not result.duplicate:
            seen_keys.add(symbiote.execution_key)
    return result_factory(
        envelope=envelope,
        mode="dry_run",
        results=tuple(results),
        elapsed_ms=_elapsed_ms(started),
    )


def _live_run_symbiote_smoke(
    models: list[ModelEndpoint],
    envelope: HermesBridgeThreeSymbioteSmokeEnvelope | HermesBridgeSevenSymbioteSmokeEnvelope,
    *,
    handoff_command: tuple[str, ...],
    seen_execution_keys: Iterable[str] | None,
    readiness: ReadinessEvidenceInput | None,
    routing_policy: RoutingScorePolicyInput | None,
    command_resolver: CommandResolver | None,
    timeout_seconds: float | None,
    cwd: str | Path | None,
    result_factory: type[HermesBridgeThreeSymbioteSmokeResult],
) -> HermesBridgeThreeSymbioteSmokeResult:
    started = time.perf_counter()
    seen_keys = set(seen_execution_keys or ())
    results: list[HermesBridgeLiveResult] = []
    for symbiote in envelope.symbiotes:
        result = live_run_hermes_bridge(
            models,
            symbiote,
            handoff_command=handoff_command,
            seen_execution_keys=seen_keys,
            readiness=readiness,
            routing_policy=routing_policy,
            command_resolver=command_resolver,
            timeout_seconds=timeout_seconds,
            cwd=cwd,
        )
        results.append(result)
        if not result.dry_run.duplicate:
            seen_keys.add(symbiote.execution_key)
    return result_factory(
        envelope=envelope,
        mode="live",
        results=tuple(results),
        elapsed_ms=_elapsed_ms(started),
        handoff_command=tuple(handoff_command),
    )


def _provider_health_results(readiness: ReadinessEvidenceInput | None) -> tuple[ProviderHealthCheckResult, ...]:
    if readiness is None:
        return ()
    values = readiness.values() if isinstance(readiness, Mapping) else readiness
    return tuple(item for item in values if isinstance(item, ProviderHealthCheckResult))


def _parse_symbiote_smoke_envelope(
    payload: Mapping[str, Any],
    *,
    expected_count: int,
    label: str,
    source: str,
) -> tuple[int, str, tuple[HermesBridgeEnvelope, ...]]:
    if not isinstance(payload, Mapping):
        raise HermesBridgeError(f"{source}: {label} smoke envelope must be a JSON object")

    schema_version = int(payload.get("schemaVersion", payload.get("schema_version", 1)) or 1)
    if schema_version != 1:
        raise HermesBridgeError(f"{source}: unsupported {label} smoke schemaVersion {schema_version!r}")

    smoke_id = _required_string(payload, "smokeId", "smoke_id", source=source)
    raw_symbiotes = payload.get("symbiotes")
    count_phrase = _expected_count_phrase(expected_count)
    if not isinstance(raw_symbiotes, list):
        raise HermesBridgeError(f"{source}: symbiotes must be a JSON array with exactly {count_phrase} items")
    if len(raw_symbiotes) != expected_count:
        raise HermesBridgeError(f"{source}: {label} smoke requires exactly {count_phrase} Symbiotes")

    symbiotes: list[HermesBridgeEnvelope] = []
    for index, raw_symbiote in enumerate(raw_symbiotes, start=1):
        if not isinstance(raw_symbiote, Mapping):
            raise HermesBridgeError(f"{source}:symbiotes[{index - 1}] must be a JSON object")
        symbiote_payload = dict(raw_symbiote)
        symbiote_payload.setdefault("schemaVersion", 1)
        try:
            symbiotes.append(
                HermesBridgeEnvelope.from_dict(
                    symbiote_payload,
                    source=f"{source}:symbiotes[{index - 1}]",
                )
            )
        except HermesBridgeError:
            raise
        except ValueError as exc:
            raise HermesBridgeError(str(exc)) from exc
    return schema_version, smoke_id, tuple(symbiotes)


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


def _parse_runtime_payload(stdout: str) -> Mapping[str, Any] | str | None:
    stripped = stdout.strip()
    if not stripped:
        return None
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return stripped
    if isinstance(payload, Mapping):
        return payload
    return stripped


def _smoke_count_label(expected_count: int) -> str:
    if expected_count == 3:
        return "three-Symbiote"
    if expected_count == 7:
        return "seven-Symbiote"
    return f"{expected_count}-Symbiote"


def _expected_count_phrase(expected_count: int) -> str:
    if expected_count == 3:
        return "three"
    return str(expected_count)


def _bridge_result_execution_key(result: HermesBridgeDryRunResult | HermesBridgeLiveResult) -> str:
    if isinstance(result, HermesBridgeLiveResult):
        return result.dry_run.envelope.execution_key
    return result.envelope.execution_key


def _bridge_result_duplicate(result: HermesBridgeDryRunResult | HermesBridgeLiveResult) -> bool:
    if isinstance(result, HermesBridgeLiveResult):
        return result.dry_run.duplicate
    return result.duplicate


def _bridge_result_started(result: HermesBridgeDryRunResult | HermesBridgeLiveResult) -> bool:
    if isinstance(result, HermesBridgeLiveResult):
        return result.started
    return False


def _aggregate_handoff_status(
    mode: str,
    results: tuple[HermesBridgeDryRunResult | HermesBridgeLiveResult, ...],
) -> str:
    if all(result.ok for result in results):
        return "dry-run-ready" if mode == "dry_run" else "completed"
    if any(result.ok for result in results):
        return "partial"
    if any(_bridge_result_duplicate(result) for result in results):
        return "duplicate-prevented"
    return "failed"


def _aggregate_execution_status(
    mode: str,
    results: tuple[HermesBridgeDryRunResult | HermesBridgeLiveResult, ...],
) -> str:
    if all(result.ok for result in results):
        return "not-started" if mode == "dry_run" else "succeeded"
    if any(result.ok for result in results):
        return "partial"
    if any(_bridge_result_duplicate(result) for result in results):
        return "skipped"
    return "error"


def _coerce_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


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
