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


FeedbackAdjustmentInput = Iterable[DecisionOutcomeRecord | Mapping[str, Any]]


@dataclass(frozen=True)
class ModelOutcomeFeedbackSummary:
    """Bounded per-model outcome evidence used to adjust eligible rankings."""

    model_id: str
    record_count: int
    success_count: int
    concern_count: int
    failure_count: int
    manual_override_count: int
    average_score: float | None
    adjustment: float
    rationale: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "modelId": self.model_id,
            "recordCount": self.record_count,
            "successCount": self.success_count,
            "concernCount": self.concern_count,
            "failureCount": self.failure_count,
            "manualOverrideCount": self.manual_override_count,
            "averageScore": self.average_score,
            "adjustment": self.adjustment,
            "rationale": list(self.rationale),
        }


@dataclass
class _FeedbackStats:
    model_id: str
    contributions: list[float] = field(default_factory=list)
    scores: list[float] = field(default_factory=list)
    success_count: int = 0
    concern_count: int = 0
    failure_count: int = 0
    manual_override_count: int = 0

    @property
    def record_count(self) -> int:
        return len(self.contributions)


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


def build_model_feedback_summaries(
    records: FeedbackAdjustmentInput,
    *,
    max_adjustment: float = 12.0,
) -> dict[str, ModelOutcomeFeedbackSummary]:
    """Aggregate outcome records into bounded per-model score adjustments."""

    stats_by_model: dict[str, _FeedbackStats] = {}
    for index, raw_record in enumerate(records, start=1):
        record = _normalize_feedback_record(raw_record, source=f"<feedback:{index}>")
        if record.selected_model_id:
            _add_selected_feedback(stats_by_model, record)
        if (
            record.verdict == "manual_override"
            and record.override_model_id
            and record.override_model_id != record.selected_model_id
        ):
            _add_feedback_contribution(
                stats_by_model,
                record.override_model_id,
                contribution=_manual_override_target_contribution(record.score),
                score=record.score if record.score is not None else 0.9,
                verdict=record.verdict,
                override_target=True,
            )

    return {
        model_id: _summarize_feedback_stats(stats, max_adjustment=max_adjustment)
        for model_id, stats in sorted(stats_by_model.items())
        if stats.record_count
    }


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


def _normalize_feedback_record(
    raw_record: DecisionOutcomeRecord | Mapping[str, Any],
    *,
    source: str,
) -> DecisionOutcomeRecord:
    if isinstance(raw_record, DecisionOutcomeRecord):
        return raw_record
    if isinstance(raw_record, Mapping):
        return DecisionOutcomeRecord.from_dict(raw_record, source=source)
    raise OutcomeFeedbackError(f"{source}: unsupported feedback record type {type(raw_record).__name__}")


def _add_selected_feedback(
    stats_by_model: dict[str, _FeedbackStats],
    record: DecisionOutcomeRecord,
) -> None:
    _add_feedback_contribution(
        stats_by_model,
        record.selected_model_id,
        contribution=_selected_model_contribution(record),
        score=_score_for_record(record),
        verdict=record.verdict,
        override_target=False,
    )


def _add_feedback_contribution(
    stats_by_model: dict[str, _FeedbackStats],
    model_id: str,
    *,
    contribution: float,
    score: float,
    verdict: str,
    override_target: bool,
) -> None:
    stats = stats_by_model.setdefault(model_id, _FeedbackStats(model_id=model_id))
    stats.contributions.append(contribution)
    stats.scores.append(score)
    if verdict == "success":
        stats.success_count += 1
    elif verdict == "failure":
        stats.failure_count += 1
    elif verdict in ("latency_concern", "quality_concern", "cost_concern"):
        stats.concern_count += 1
    elif verdict == "manual_override":
        stats.manual_override_count += 1
        if override_target:
            stats.success_count += 1


def _selected_model_contribution(record: DecisionOutcomeRecord) -> float:
    if record.verdict == "success":
        return 2.0 + (_score_for_record(record) * 8.0)
    if record.verdict == "failure":
        return -10.0
    if record.verdict == "quality_concern":
        return -7.0
    if record.verdict in ("latency_concern", "cost_concern"):
        return -4.0
    if record.verdict == "manual_override":
        return -8.0
    return 0.0


def _manual_override_target_contribution(score: float | None) -> float:
    return 6.0 + (_normalize_outcome_score(score, default=0.9) * 4.0)


def _score_for_record(record: DecisionOutcomeRecord) -> float:
    if record.verdict == "success":
        return _normalize_outcome_score(record.score, default=1.0)
    if record.verdict == "failure":
        return _normalize_outcome_score(record.score, default=0.0)
    if record.verdict in ("latency_concern", "quality_concern", "cost_concern"):
        return _normalize_outcome_score(record.score, default=0.35)
    if record.verdict == "manual_override":
        return _normalize_outcome_score(record.score, default=0.25)
    return _normalize_outcome_score(record.score, default=0.5)


def _normalize_outcome_score(score: float | None, *, default: float) -> float:
    return max(0.0, min(1.0, float(default if score is None else score)))


def _summarize_feedback_stats(
    stats: _FeedbackStats,
    *,
    max_adjustment: float,
) -> ModelOutcomeFeedbackSummary:
    raw_adjustment = sum(stats.contributions) / len(stats.contributions)
    adjustment = round(max(-max_adjustment, min(max_adjustment, raw_adjustment)), 4)
    average_score = round(sum(stats.scores) / len(stats.scores), 4) if stats.scores else None
    rationale = [
        f"{stats.record_count} outcome feedback records",
        f"bounded feedback adjustment {adjustment:+.2f}",
    ]
    if average_score is not None:
        rationale.append(f"average outcome score {average_score:.2f}")
    if stats.success_count:
        rationale.append(f"{stats.success_count} success signals")
    if stats.concern_count:
        rationale.append(f"{stats.concern_count} concern signals")
    if stats.failure_count:
        rationale.append(f"{stats.failure_count} failure signals")
    if stats.manual_override_count:
        rationale.append(f"{stats.manual_override_count} manual override signals")
    return ModelOutcomeFeedbackSummary(
        model_id=stats.model_id,
        record_count=stats.record_count,
        success_count=stats.success_count,
        concern_count=stats.concern_count,
        failure_count=stats.failure_count,
        manual_override_count=stats.manual_override_count,
        average_score=average_score,
        adjustment=adjustment,
        rationale=tuple(rationale),
    )


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
