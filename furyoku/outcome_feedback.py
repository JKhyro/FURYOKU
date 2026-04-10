from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from uuid import uuid4


VALID_OUTCOME_VERDICTS = (
    "success",
    "failure",
    "latency_concern",
    "quality_concern",
    "cost_concern",
    "manual_override",
)


class OutcomeFeedbackError(ValueError):
    """Raised when a decision outcome feedback record is malformed."""


@dataclass(frozen=True)
class DecisionOutcomeRecord:
    """Operator or automated feedback tied to a persisted decision/execution report."""

    record_id: str
    report_path: str
    report_sha256: str
    verdict: str
    generated_at: str
    report_generated_at: str = ""
    situation_id: str = ""
    selected_model_id: str = ""
    selected_provider: str = ""
    execution_status: str = ""
    score: float | None = None
    reason: str = ""
    tags: tuple[str, ...] = ()
    override_model_id: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "schemaVersion": 1,
            "recordId": self.record_id,
            "reportPath": self.report_path,
            "reportSha256": self.report_sha256,
            "reportGeneratedAt": self.report_generated_at,
            "generatedAt": self.generated_at,
            "situationId": self.situation_id,
            "selectedModelId": self.selected_model_id,
            "selectedProvider": self.selected_provider,
            "executionStatus": self.execution_status,
            "verdict": self.verdict,
            "score": self.score,
            "reason": self.reason,
            "tags": list(self.tags),
            "overrideModelId": self.override_model_id,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any], *, source: str = "<memory>") -> "DecisionOutcomeRecord":
        if not isinstance(payload, Mapping):
            raise OutcomeFeedbackError(f"{source}: feedback record must be an object")
        schema_version = payload.get("schemaVersion", payload.get("schema_version", 1))
        if schema_version != 1:
            raise OutcomeFeedbackError(f"{source}: unsupported feedback schemaVersion {schema_version!r}")
        verdict = _required_string(payload, "verdict", source=source)
        _validate_verdict(verdict, source=source)
        score = _optional_score(payload.get("score"), source=source)
        return cls(
            record_id=_required_string(payload, "recordId", "record_id", source=source),
            report_path=_required_string(payload, "reportPath", "report_path", source=source),
            report_sha256=_required_string(payload, "reportSha256", "report_sha256", source=source),
            report_generated_at=str(payload.get("reportGeneratedAt", payload.get("report_generated_at", "")) or ""),
            generated_at=_required_string(payload, "generatedAt", "generated_at", source=source),
            situation_id=str(payload.get("situationId", payload.get("situation_id", "")) or ""),
            selected_model_id=str(payload.get("selectedModelId", payload.get("selected_model_id", "")) or ""),
            selected_provider=str(payload.get("selectedProvider", payload.get("selected_provider", "")) or ""),
            execution_status=str(payload.get("executionStatus", payload.get("execution_status", "")) or ""),
            verdict=verdict,
            score=score,
            reason=str(payload.get("reason", "") or ""),
            tags=tuple(str(tag) for tag in payload.get("tags", ()) or ()),
            override_model_id=str(payload.get("overrideModelId", payload.get("override_model_id", "")) or ""),
            metadata=_metadata_mapping(payload.get("metadata", {}), source=source),
        )


def create_decision_outcome_record(
    report_path: str | Path,
    *,
    verdict: str,
    score: float | None = None,
    reason: str = "",
    tags: Iterable[str] = (),
    override_model_id: str = "",
    metadata: Mapping[str, Any] | None = None,
) -> DecisionOutcomeRecord:
    """Create one feedback record linked to a persisted decision/execution report."""

    _validate_verdict(verdict, source="<feedback>")
    normalized_score = _optional_score(score, source="<feedback>")
    path = Path(report_path)
    report_bytes = path.read_bytes()
    report = json.loads(report_bytes.decode("utf-8"))
    if not isinstance(report, Mapping):
        raise OutcomeFeedbackError(f"{path}: persisted report must be a JSON object")

    selection = _extract_selected_model(report)
    execution = report.get("execution")
    return DecisionOutcomeRecord(
        record_id=str(uuid4()),
        report_path=str(path),
        report_sha256=hashlib.sha256(report_bytes).hexdigest(),
        report_generated_at=_report_generated_at(report),
        generated_at=datetime.now(timezone.utc).isoformat(),
        situation_id=str(report.get("situationId", _first_decision_task_id(report)) or ""),
        selected_model_id=str(selection.get("modelId", "") or ""),
        selected_provider=str(selection.get("provider", "") or ""),
        execution_status=_execution_status(execution),
        verdict=verdict,
        score=normalized_score,
        reason=reason,
        tags=tuple(str(tag) for tag in tags),
        override_model_id=override_model_id,
        metadata=dict(metadata or {}),
    )


def append_decision_outcome(
    feedback_log_path: str | Path,
    record: DecisionOutcomeRecord,
) -> None:
    path = Path(feedback_log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        json.dump(record.to_dict(), handle, sort_keys=True)
        handle.write("\n")


def load_decision_outcomes(feedback_log_path: str | Path) -> tuple[DecisionOutcomeRecord, ...]:
    path = Path(feedback_log_path)
    if not path.exists():
        return ()
    records: list[DecisionOutcomeRecord] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                payload = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                raise OutcomeFeedbackError(f"{path}:{line_number}: invalid JSON feedback record") from exc
            records.append(DecisionOutcomeRecord.from_dict(payload, source=f"{path}:{line_number}"))
    return tuple(records)


def _extract_selected_model(report: Mapping[str, Any]) -> Mapping[str, Any]:
    selected = report.get("selectedModel")
    if isinstance(selected, Mapping):
        return selected
    selection = report.get("selection")
    if isinstance(selection, Mapping):
        return selection
    decisions = report.get("decisions")
    if isinstance(decisions, list):
        for decision in decisions:
            if isinstance(decision, Mapping) and isinstance(decision.get("selectedModel"), Mapping):
                return decision["selectedModel"]
    return {}


def _first_decision_task_id(report: Mapping[str, Any]) -> str:
    decisions = report.get("decisions")
    if isinstance(decisions, list) and decisions and isinstance(decisions[0], Mapping):
        return str(decisions[0].get("taskId", "") or "")
    decision = report.get("decision")
    if isinstance(decision, Mapping):
        return str(decision.get("taskId", "") or "")
    return ""


def _execution_status(execution: Any) -> str:
    if isinstance(execution, Mapping):
        return str(execution.get("status", "") or "")
    return ""


def _report_generated_at(report: Mapping[str, Any]) -> str:
    metadata = report.get("reportMetadata")
    if isinstance(metadata, Mapping):
        return str(metadata.get("generatedAt", "") or "")
    return ""


def _required_string(payload: Mapping[str, Any], *keys: str, source: str) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise OutcomeFeedbackError(f"{source}: missing required field {keys[0]}")


def _validate_verdict(verdict: str, *, source: str) -> None:
    if verdict not in VALID_OUTCOME_VERDICTS:
        raise OutcomeFeedbackError(
            f"{source}: verdict must be one of {', '.join(VALID_OUTCOME_VERDICTS)}"
        )


def _optional_score(value: Any, *, source: str) -> float | None:
    if value in (None, ""):
        return None
    try:
        score = float(value)
    except (TypeError, ValueError) as exc:
        raise OutcomeFeedbackError(f"{source}: score must be numeric") from exc
    if score < 0.0 or score > 1.0:
        raise OutcomeFeedbackError(f"{source}: score must be between 0.0 and 1.0")
    return round(score, 4)


def _metadata_mapping(value: Any, *, source: str) -> Mapping[str, Any]:
    if value in (None, ""):
        return {}
    if not isinstance(value, Mapping):
        raise OutcomeFeedbackError(f"{source}: metadata must be an object")
    return dict(value)
