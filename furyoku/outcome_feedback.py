from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
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
    latency_ms: float | None = None
    input_cost_per_1k: float | None = None
    output_cost_per_1k: float | None = None
    estimated_input_cost: float | None = None
    estimated_output_cost: float | None = None
    estimated_total_cost: float | None = None
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
            "latencyMs": self.latency_ms,
            "inputCostPer1k": self.input_cost_per_1k,
            "outputCostPer1k": self.output_cost_per_1k,
            "estimatedInputCost": self.estimated_input_cost,
            "estimatedOutputCost": self.estimated_output_cost,
            "estimatedTotalCost": self.estimated_total_cost,
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
            latency_ms=_optional_non_negative_float(
                payload.get("latencyMs", payload.get("latency_ms")),
                field_name="latencyMs",
                source=source,
            ),
            input_cost_per_1k=_optional_non_negative_float(
                payload.get("inputCostPer1k", payload.get("input_cost_per_1k")),
                field_name="inputCostPer1k",
                source=source,
            ),
            output_cost_per_1k=_optional_non_negative_float(
                payload.get("outputCostPer1k", payload.get("output_cost_per_1k")),
                field_name="outputCostPer1k",
                source=source,
            ),
            estimated_input_cost=_optional_non_negative_float(
                payload.get("estimatedInputCost", payload.get("estimated_input_cost")),
                field_name="estimatedInputCost",
                source=source,
            ),
            estimated_output_cost=_optional_non_negative_float(
                payload.get("estimatedOutputCost", payload.get("estimated_output_cost")),
                field_name="estimatedOutputCost",
                source=source,
            ),
            estimated_total_cost=_optional_non_negative_float(
                payload.get("estimatedTotalCost", payload.get("estimated_total_cost")),
                field_name="estimatedTotalCost",
                source=source,
            ),
            verdict=verdict,
            score=score,
            reason=str(payload.get("reason", "") or ""),
            tags=tuple(str(tag) for tag in payload.get("tags", ()) or ()),
            override_model_id=str(payload.get("overrideModelId", payload.get("override_model_id", "")) or ""),
            metadata=_metadata_mapping(payload.get("metadata", {}), source=source),
        )


FeedbackAdjustmentInput = Iterable[DecisionOutcomeRecord | Mapping[str, Any]]


@dataclass(frozen=True)
class FeedbackAdjustmentPolicy:
    """Configurable scoring policy for turning outcome records into routing evidence."""

    max_adjustment: float = 12.0
    success_base: float = 2.0
    success_score_multiplier: float = 8.0
    failure_penalty: float = -10.0
    quality_concern_penalty: float = -7.0
    latency_concern_penalty: float = -4.0
    cost_concern_penalty: float = -4.0
    manual_override_penalty: float = -8.0
    manual_override_target_base: float = 6.0
    manual_override_target_score_multiplier: float = 4.0
    default_success_score: float = 1.0
    default_failure_score: float = 0.0
    default_concern_score: float = 0.35
    default_manual_override_score: float = 0.25
    default_override_target_score: float = 0.9
    recency_half_life_days: float | None = None

    def __post_init__(self) -> None:
        _validate_non_negative_float(self.max_adjustment, "maxAdjustment", source="<feedback-policy>")
        if self.recency_half_life_days is not None:
            _validate_positive_float(
                self.recency_half_life_days,
                "recencyHalfLifeDays",
                source="<feedback-policy>",
            )
        for field_name in (
            "default_success_score",
            "default_failure_score",
            "default_concern_score",
            "default_manual_override_score",
            "default_override_target_score",
        ):
            _validate_score_range(getattr(self, field_name), _camel_name(field_name), source="<feedback-policy>")

    def to_dict(self) -> dict:
        return {
            "schemaVersion": 1,
            "maxAdjustment": self.max_adjustment,
            "successBase": self.success_base,
            "successScoreMultiplier": self.success_score_multiplier,
            "failurePenalty": self.failure_penalty,
            "qualityConcernPenalty": self.quality_concern_penalty,
            "latencyConcernPenalty": self.latency_concern_penalty,
            "costConcernPenalty": self.cost_concern_penalty,
            "manualOverridePenalty": self.manual_override_penalty,
            "manualOverrideTargetBase": self.manual_override_target_base,
            "manualOverrideTargetScoreMultiplier": self.manual_override_target_score_multiplier,
            "defaultSuccessScore": self.default_success_score,
            "defaultFailureScore": self.default_failure_score,
            "defaultConcernScore": self.default_concern_score,
            "defaultManualOverrideScore": self.default_manual_override_score,
            "defaultOverrideTargetScore": self.default_override_target_score,
            "recencyHalfLifeDays": self.recency_half_life_days,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any], *, source: str = "<memory>") -> "FeedbackAdjustmentPolicy":
        if not isinstance(payload, Mapping):
            raise OutcomeFeedbackError(f"{source}: feedback adjustment policy must be an object")
        schema_version = payload.get("schemaVersion", payload.get("schema_version", 1))
        if schema_version != 1:
            raise OutcomeFeedbackError(f"{source}: unsupported feedback policy schemaVersion {schema_version!r}")
        defaults = cls()
        return cls(
            max_adjustment=_policy_float(payload, "maxAdjustment", "max_adjustment", default=defaults.max_adjustment, source=source),
            success_base=_policy_float(payload, "successBase", "success_base", default=defaults.success_base, source=source),
            success_score_multiplier=_policy_float(payload, "successScoreMultiplier", "success_score_multiplier", default=defaults.success_score_multiplier, source=source),
            failure_penalty=_policy_float(payload, "failurePenalty", "failure_penalty", default=defaults.failure_penalty, source=source),
            quality_concern_penalty=_policy_float(payload, "qualityConcernPenalty", "quality_concern_penalty", default=defaults.quality_concern_penalty, source=source),
            latency_concern_penalty=_policy_float(payload, "latencyConcernPenalty", "latency_concern_penalty", default=defaults.latency_concern_penalty, source=source),
            cost_concern_penalty=_policy_float(payload, "costConcernPenalty", "cost_concern_penalty", default=defaults.cost_concern_penalty, source=source),
            manual_override_penalty=_policy_float(payload, "manualOverridePenalty", "manual_override_penalty", default=defaults.manual_override_penalty, source=source),
            manual_override_target_base=_policy_float(payload, "manualOverrideTargetBase", "manual_override_target_base", default=defaults.manual_override_target_base, source=source),
            manual_override_target_score_multiplier=_policy_float(payload, "manualOverrideTargetScoreMultiplier", "manual_override_target_score_multiplier", default=defaults.manual_override_target_score_multiplier, source=source),
            default_success_score=_policy_float(payload, "defaultSuccessScore", "default_success_score", default=defaults.default_success_score, source=source),
            default_failure_score=_policy_float(payload, "defaultFailureScore", "default_failure_score", default=defaults.default_failure_score, source=source),
            default_concern_score=_policy_float(payload, "defaultConcernScore", "default_concern_score", default=defaults.default_concern_score, source=source),
            default_manual_override_score=_policy_float(payload, "defaultManualOverrideScore", "default_manual_override_score", default=defaults.default_manual_override_score, source=source),
            default_override_target_score=_policy_float(payload, "defaultOverrideTargetScore", "default_override_target_score", default=defaults.default_override_target_score, source=source),
            recency_half_life_days=_policy_optional_positive_float(
                payload,
                "recencyHalfLifeDays",
                "recency_half_life_days",
                default=defaults.recency_half_life_days,
                source=source,
            ),
        )


FeedbackAdjustmentPolicyInput = FeedbackAdjustmentPolicy | Mapping[str, Any]


@dataclass(frozen=True)
class FeedbackPolicyMetadata:
    """Stable report metadata for the feedback policy that shaped routing."""

    source: str
    policy: FeedbackAdjustmentPolicy
    customized_fields: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "schemaVersion": 1,
            "source": self.source,
            "customizedFields": list(self.customized_fields),
            "policy": self.policy.to_dict(),
        }


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
    weighted_record_count: float = 0.0
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
            "weightedRecordCount": self.weighted_record_count,
            "rationale": list(self.rationale),
        }


@dataclass(frozen=True)
class OutcomeFeedbackGroupSummary:
    """Human/operator summary for one outcome-feedback grouping."""

    group_type: str
    key: str
    record_count: int
    success_count: int
    concern_count: int
    failure_count: int
    manual_override_count: int
    average_score: float | None
    success_rate: float
    concern_rate: float
    failure_rate: float
    manual_override_rate: float
    net_outcome_count: int
    rank_score: float
    latest_generated_at: str = ""
    adjustment: float | None = None
    weighted_record_count: float | None = None
    provider: str = ""
    latency_record_count: int | None = None
    average_latency_ms: float | None = None
    minimum_latency_ms: float | None = None
    maximum_latency_ms: float | None = None
    cost_record_count: int | None = None
    average_input_cost_per_1k: float | None = None
    average_output_cost_per_1k: float | None = None
    average_estimated_input_cost: float | None = None
    average_estimated_output_cost: float | None = None
    average_estimated_total_cost: float | None = None

    def to_dict(self) -> dict:
        payload = {
            "groupType": self.group_type,
            "key": self.key,
            "recordCount": self.record_count,
            "successCount": self.success_count,
            "concernCount": self.concern_count,
            "failureCount": self.failure_count,
            "manualOverrideCount": self.manual_override_count,
            "averageScore": self.average_score,
            "successRate": self.success_rate,
            "concernRate": self.concern_rate,
            "failureRate": self.failure_rate,
            "manualOverrideRate": self.manual_override_rate,
            "netOutcomeCount": self.net_outcome_count,
            "rankScore": self.rank_score,
            "latestGeneratedAt": self.latest_generated_at,
        }
        if self.adjustment is not None:
            payload["adjustment"] = self.adjustment
        if self.weighted_record_count is not None:
            payload["weightedRecordCount"] = self.weighted_record_count
        if self.provider:
            payload["provider"] = self.provider
        if self.latency_record_count is not None:
            payload["latencyRecordCount"] = self.latency_record_count
        if self.average_latency_ms is not None:
            payload["averageLatencyMs"] = self.average_latency_ms
        if self.minimum_latency_ms is not None:
            payload["minimumLatencyMs"] = self.minimum_latency_ms
        if self.maximum_latency_ms is not None:
            payload["maximumLatencyMs"] = self.maximum_latency_ms
        if self.cost_record_count is not None:
            payload["costRecordCount"] = self.cost_record_count
        if self.average_input_cost_per_1k is not None:
            payload["averageInputCostPer1k"] = self.average_input_cost_per_1k
        if self.average_output_cost_per_1k is not None:
            payload["averageOutputCostPer1k"] = self.average_output_cost_per_1k
        if self.average_estimated_input_cost is not None:
            payload["averageEstimatedInputCost"] = self.average_estimated_input_cost
        if self.average_estimated_output_cost is not None:
            payload["averageEstimatedOutputCost"] = self.average_estimated_output_cost
        if self.average_estimated_total_cost is not None:
            payload["averageEstimatedTotalCost"] = self.average_estimated_total_cost
        return payload


@dataclass(frozen=True)
class OutcomeFeedbackModelScorecard:
    """Aggregate outcome scorecard for one model across all and per-situation evidence."""

    model_id: str
    provider: str
    overall: OutcomeFeedbackGroupSummary
    situations: tuple[OutcomeFeedbackGroupSummary, ...]

    def to_dict(self) -> dict:
        return {
            "modelId": self.model_id,
            "provider": self.provider,
            "overall": self.overall.to_dict(),
            "situations": [summary.to_dict() for summary in self.situations],
        }


@dataclass(frozen=True)
class OutcomeFeedbackSituationLeaderboard:
    """Ranked model leaderboard for one situation using accumulated feedback evidence."""

    situation_id: str
    record_count: int
    models: tuple[OutcomeFeedbackGroupSummary, ...]

    def to_dict(self) -> dict:
        return {
            "situationId": self.situation_id,
            "recordCount": self.record_count,
            "modelCount": len(self.models),
            "models": [summary.to_dict() for summary in self.models],
        }


@dataclass(frozen=True)
class OutcomeFeedbackSummaryReport:
    """Report for comparing captured outcome feedback by model, provider, and task."""

    generated_at: str
    total: OutcomeFeedbackGroupSummary
    models: tuple[OutcomeFeedbackGroupSummary, ...]
    providers: tuple[OutcomeFeedbackGroupSummary, ...]
    situations: tuple[OutcomeFeedbackGroupSummary, ...]
    sources: tuple[OutcomeFeedbackGroupSummary, ...]
    feedback_policy_metadata: FeedbackPolicyMetadata
    model_scorecards: tuple[OutcomeFeedbackModelScorecard, ...] = ()
    situation_leaderboards: tuple[OutcomeFeedbackSituationLeaderboard, ...] = ()
    applied_evidence_sources: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "schemaVersion": 1,
            "generatedAt": self.generated_at,
            "recordCount": self.total.record_count,
            "total": self.total.to_dict(),
            "models": [summary.to_dict() for summary in self.models],
            "providers": [summary.to_dict() for summary in self.providers],
            "situations": [summary.to_dict() for summary in self.situations],
            "sources": [summary.to_dict() for summary in self.sources],
            "modelScorecards": [scorecard.to_dict() for scorecard in self.model_scorecards],
            "situationLeaderboards": [leaderboard.to_dict() for leaderboard in self.situation_leaderboards],
            "appliedEvidenceSources": list(self.applied_evidence_sources),
            "feedbackPolicy": self.feedback_policy_metadata.to_dict(),
        }


@dataclass
class _FeedbackStats:
    model_id: str
    contributions: list[float] = field(default_factory=list)
    scores: list[float] = field(default_factory=list)
    weights: list[float] = field(default_factory=list)
    success_count: int = 0
    concern_count: int = 0
    failure_count: int = 0
    manual_override_count: int = 0

    @property
    def record_count(self) -> int:
        return len(self.contributions)


@dataclass
class _OutcomeSummaryStats:
    group_type: str
    key: str
    scores: list[float] = field(default_factory=list)
    generated_at_values: list[str] = field(default_factory=list)
    latencies_ms: list[float] = field(default_factory=list)
    input_costs_per_1k: list[float] = field(default_factory=list)
    output_costs_per_1k: list[float] = field(default_factory=list)
    estimated_input_costs: list[float] = field(default_factory=list)
    estimated_output_costs: list[float] = field(default_factory=list)
    estimated_total_costs: list[float] = field(default_factory=list)
    success_count: int = 0
    concern_count: int = 0
    failure_count: int = 0
    manual_override_count: int = 0
    cost_record_count: int = 0

    @property
    def record_count(self) -> int:
        return self.success_count + self.concern_count + self.failure_count + self.manual_override_count

    def add(self, record: DecisionOutcomeRecord) -> None:
        if record.score is not None:
            self.scores.append(record.score)
        if record.generated_at:
            self.generated_at_values.append(record.generated_at)
        if record.latency_ms is not None:
            self.latencies_ms.append(record.latency_ms)
        has_cost_telemetry = False
        if record.input_cost_per_1k is not None:
            self.input_costs_per_1k.append(record.input_cost_per_1k)
            has_cost_telemetry = True
        if record.output_cost_per_1k is not None:
            self.output_costs_per_1k.append(record.output_cost_per_1k)
            has_cost_telemetry = True
        if record.estimated_input_cost is not None:
            self.estimated_input_costs.append(record.estimated_input_cost)
            has_cost_telemetry = True
        if record.estimated_output_cost is not None:
            self.estimated_output_costs.append(record.estimated_output_cost)
            has_cost_telemetry = True
        if record.estimated_total_cost is not None:
            self.estimated_total_costs.append(record.estimated_total_cost)
            has_cost_telemetry = True
        if has_cost_telemetry:
            self.cost_record_count += 1
        if record.verdict == "success":
            self.success_count += 1
        elif record.verdict == "failure":
            self.failure_count += 1
        elif record.verdict in ("latency_concern", "quality_concern", "cost_concern"):
            self.concern_count += 1
        elif record.verdict == "manual_override":
            self.manual_override_count += 1


@dataclass(frozen=True)
class _OutcomeRecordTelemetry:
    latency_ms: float | None = None
    input_cost_per_1k: float | None = None
    output_cost_per_1k: float | None = None
    estimated_input_cost: float | None = None
    estimated_output_cost: float | None = None
    estimated_total_cost: float | None = None


@dataclass(frozen=True)
class _ComparativeExecutionCapture:
    attempt: Mapping[str, Any]
    source_label: str
    report_type: str
    situation_id: str
    comparison_attempt_number: int
    comparison_executed_count: int
    suite_id: str = ""
    situation_index: int | None = None
    situation_count: int | None = None
    batch_executed_candidate_count: int | None = None


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
    path, report_bytes, report = _read_report_payload(report_path)
    return _decision_outcome_record_from_report(
        path=path,
        report_bytes=report_bytes,
        report=report,
        verdict=verdict,
        score=normalized_score,
        reason=reason,
        tags=tags,
        override_model_id=override_model_id,
        metadata=metadata,
    )


def create_execution_outcome_record(
    report_path: str | Path,
    *,
    verdict: str | None = None,
    score: float | None = None,
    reason: str = "",
    tags: Iterable[str] = (),
    override_model_id: str = "",
    metadata: Mapping[str, Any] | None = None,
) -> DecisionOutcomeRecord:
    """Create feedback evidence by inferring success/failure from a persisted execution report."""

    normalized_score = _optional_score(score, source="<outcome-capture>")
    path, report_bytes, report = _read_report_payload(report_path)
    resolved_verdict = verdict or infer_execution_outcome_verdict(report, source=str(path))
    _validate_verdict(resolved_verdict, source="<outcome-capture>")
    return _decision_outcome_record_from_report(
        path=path,
        report_bytes=report_bytes,
        report=report,
        verdict=resolved_verdict,
        score=normalized_score,
        reason=reason,
        tags=tags,
        override_model_id=override_model_id,
        metadata=metadata,
    )


def capture_execution_outcome(
    feedback_log_path: str | Path,
    report_path: str | Path,
    *,
    verdict: str | None = None,
    score: float | None = None,
    reason: str = "",
    tags: Iterable[str] = (),
    override_model_id: str = "",
    metadata: Mapping[str, Any] | None = None,
) -> DecisionOutcomeRecord:
    """Append one inferred or explicit execution outcome record to a JSONL feedback log."""

    record = create_execution_outcome_record(
        report_path,
        verdict=verdict,
        score=score,
        reason=reason,
        tags=tags,
        override_model_id=override_model_id,
        metadata=metadata,
    )
    append_decision_outcome(feedback_log_path, record)
    return record


def create_comparative_execution_outcome_records(
    report_path: str | Path,
    *,
    success_score: float | None = None,
    failure_score: float | None = None,
    reason: str = "",
    tags: Iterable[str] = (),
    metadata: Mapping[str, Any] | None = None,
) -> tuple[DecisionOutcomeRecord, ...]:
    """Create one feedback record per candidate execution in a persisted comparison report."""

    normalized_success_score = _optional_score(success_score, source="<comparison-outcome-capture:success-score>")
    normalized_failure_score = _optional_score(failure_score, source="<comparison-outcome-capture:failure-score>")
    path, report_bytes, report = _read_report_payload(report_path)
    captures = _comparative_execution_attempts(report, source=str(path))
    report_sha256 = hashlib.sha256(report_bytes).hexdigest()
    report_generated_at = _report_generated_at(report)
    generated_at = datetime.now(timezone.utc).isoformat()
    normalized_tags = tuple(str(tag) for tag in tags)
    extra_metadata = dict(metadata or {})
    records: list[DecisionOutcomeRecord] = []

    for capture in captures:
        attempt = capture.attempt
        selected = attempt.get("selectedModel")
        if not isinstance(selected, Mapping):
            raise OutcomeFeedbackError(f"{path}: {capture.source_label}.selectedModel must be an object")
        execution = attempt.get("execution")
        execution_status = _execution_status(execution)
        if not execution_status:
            raise OutcomeFeedbackError(f"{path}: {capture.source_label}.execution.status is required")
        verdict = "success" if execution_status == "ok" else "failure"
        telemetry = _extract_outcome_record_telemetry(
            report=attempt,
            execution=execution,
            selection=selected,
            source=f"{path}: {capture.source_label}",
        )
        capture_metadata = {
            "captureSource": "furyoku.comparative-execution",
            "comparisonAttemptNumber": capture.comparison_attempt_number,
            "comparisonExecutedCount": capture.comparison_executed_count,
            "comparisonReportType": capture.report_type,
        }
        if capture.suite_id:
            capture_metadata["comparisonSuiteId"] = capture.suite_id
        if capture.situation_index is not None:
            capture_metadata["comparisonSituationIndex"] = capture.situation_index
        if capture.situation_count is not None:
            capture_metadata["comparisonSituationCount"] = capture.situation_count
        if capture.batch_executed_candidate_count is not None:
            capture_metadata["comparisonBatchExecutedCandidateCount"] = capture.batch_executed_candidate_count
        records.append(
            DecisionOutcomeRecord(
                record_id=str(uuid4()),
                report_path=str(path),
                report_sha256=report_sha256,
                report_generated_at=report_generated_at,
                generated_at=generated_at,
                situation_id=capture.situation_id,
                selected_model_id=str(selected.get("modelId", "") or ""),
                selected_provider=str(selected.get("provider", "") or ""),
                execution_status=execution_status,
                latency_ms=telemetry.latency_ms,
                input_cost_per_1k=telemetry.input_cost_per_1k,
                output_cost_per_1k=telemetry.output_cost_per_1k,
                estimated_input_cost=telemetry.estimated_input_cost,
                estimated_output_cost=telemetry.estimated_output_cost,
                estimated_total_cost=telemetry.estimated_total_cost,
                verdict=verdict,
                score=normalized_success_score if verdict == "success" else normalized_failure_score,
                reason=reason,
                tags=normalized_tags,
                metadata={**capture_metadata, **extra_metadata},
            )
        )
    return tuple(records)


def capture_comparative_execution_outcomes(
    feedback_log_path: str | Path,
    report_path: str | Path,
    *,
    success_score: float | None = None,
    failure_score: float | None = None,
    reason: str = "",
    tags: Iterable[str] = (),
    metadata: Mapping[str, Any] | None = None,
) -> tuple[DecisionOutcomeRecord, ...]:
    """Append one inferred comparison outcome record per executed candidate."""

    records = create_comparative_execution_outcome_records(
        report_path,
        success_score=success_score,
        failure_score=failure_score,
        reason=reason,
        tags=tags,
        metadata=metadata,
    )
    for record in records:
        append_decision_outcome(feedback_log_path, record)
    return records


def infer_execution_outcome_verdict(report: Mapping[str, Any], *, source: str = "<memory>") -> str:
    """Infer a feedback verdict from a persisted run report execution status."""

    if not isinstance(report, Mapping):
        raise OutcomeFeedbackError(f"{source}: persisted report must be a JSON object")
    execution_status = _execution_status(report.get("execution"))
    if not execution_status:
        raise OutcomeFeedbackError(f"{source}: cannot infer outcome verdict without execution.status")
    return "success" if execution_status == "ok" else "failure"


def build_model_feedback_summaries(
    records: FeedbackAdjustmentInput,
    *,
    max_adjustment: float | None = None,
    policy: FeedbackAdjustmentPolicyInput | None = None,
    as_of: datetime | str | None = None,
) -> dict[str, ModelOutcomeFeedbackSummary]:
    """Aggregate outcome records into bounded per-model score adjustments."""

    resolved_policy = _resolve_feedback_policy(policy, max_adjustment=max_adjustment)
    resolved_as_of = _parse_as_of(as_of)
    stats_by_model: dict[str, _FeedbackStats] = {}
    for index, raw_record in enumerate(records, start=1):
        record = _normalize_feedback_record(raw_record, source=f"<feedback:{index}>")
        weight = _recency_weight(record, resolved_policy, as_of=resolved_as_of)
        if record.selected_model_id:
            _add_selected_feedback(stats_by_model, record, resolved_policy, weight=weight)
        if (
            record.verdict == "manual_override"
            and record.override_model_id
            and record.override_model_id != record.selected_model_id
        ):
            _add_feedback_contribution(
                stats_by_model,
                record.override_model_id,
                contribution=_manual_override_target_contribution(record.score, resolved_policy),
                score=record.score if record.score is not None else resolved_policy.default_override_target_score,
                verdict=record.verdict,
                override_target=True,
                weight=weight,
            )

    return {
        model_id: _summarize_feedback_stats(stats, policy=resolved_policy)
        for model_id, stats in sorted(stats_by_model.items())
        if stats.record_count
    }


def summarize_outcome_feedback(
    records: FeedbackAdjustmentInput,
    *,
    policy: FeedbackAdjustmentPolicyInput | None = None,
    max_adjustment: float | None = None,
    as_of: datetime | str | None = None,
    generated_at: datetime | str | None = None,
    evidence_sources: Iterable[str] | None = None,
) -> OutcomeFeedbackSummaryReport:
    """Summarize captured outcome feedback for model/provider/task comparison."""

    normalized_records = filter_outcome_feedback_records(records, evidence_sources=evidence_sources)
    normalized_evidence_sources = _normalize_evidence_source_filters(evidence_sources)
    feedback_adjustments = build_model_feedback_summaries(
        normalized_records,
        policy=policy,
        max_adjustment=max_adjustment,
        as_of=as_of,
    )
    total_stats = _OutcomeSummaryStats(group_type="total", key="all")
    model_stats: dict[str, _OutcomeSummaryStats] = {}
    provider_stats: dict[str, _OutcomeSummaryStats] = {}
    situation_stats: dict[str, _OutcomeSummaryStats] = {}
    source_stats: dict[str, _OutcomeSummaryStats] = {}
    model_situation_stats: dict[str, dict[str, _OutcomeSummaryStats]] = {}
    situation_model_stats: dict[str, dict[str, _OutcomeSummaryStats]] = {}
    model_providers: dict[str, str] = {}

    for record in normalized_records:
        model_id = record.selected_model_id or "<unknown>"
        provider = record.selected_provider or "<unknown>"
        situation_id = record.situation_id or "<unknown>"
        evidence_source = outcome_feedback_source(record)
        total_stats.add(record)
        _summary_stats_for(model_stats, "model", model_id).add(record)
        _summary_stats_for(provider_stats, "provider", provider).add(record)
        _summary_stats_for(situation_stats, "situation", situation_id).add(record)
        _summary_stats_for(source_stats, "source", evidence_source).add(record)
        _nested_summary_stats_for(model_situation_stats, model_id, "situation", situation_id).add(record)
        _nested_summary_stats_for(situation_model_stats, situation_id, "model", model_id).add(record)
        if model_id not in model_providers and provider:
            model_providers[model_id] = provider

    model_summaries_by_id = {
        model_id: _summarize_outcome_stats(
            stats,
            model_feedback=feedback_adjustments.get(model_id),
            provider=model_providers.get(model_id, ""),
        )
        for model_id, stats in model_stats.items()
    }
    models = tuple(sorted(model_summaries_by_id.values(), key=_outcome_group_sort_key))
    providers = tuple(
        sorted(
            (_summarize_outcome_stats(stats) for stats in provider_stats.values()),
            key=_outcome_group_sort_key,
        )
    )
    situations = tuple(
        sorted(
            (_summarize_outcome_stats(stats) for stats in situation_stats.values()),
            key=lambda summary: summary.key,
        )
    )
    sources = tuple(
        sorted(
            (_summarize_outcome_stats(stats) for stats in source_stats.values()),
            key=lambda summary: summary.key,
        )
    )
    model_scorecards = tuple(
        sorted(
            (
                OutcomeFeedbackModelScorecard(
                    model_id=model_id,
                    provider=model_providers.get(model_id, ""),
                    overall=model_summaries_by_id[model_id],
                    situations=tuple(
                        sorted(
                            (
                                _summarize_outcome_stats(situation_model_stats)
                                for situation_model_stats in model_situation_stats[model_id].values()
                            ),
                            key=lambda summary: summary.key,
                        )
                    ),
                )
                for model_id in model_situation_stats
            ),
            key=lambda scorecard: _outcome_group_sort_key(scorecard.overall),
        )
    )
    situation_leaderboards = tuple(
        sorted(
            (
                OutcomeFeedbackSituationLeaderboard(
                    situation_id=situation_id,
                    record_count=situation_stats[situation_id].record_count if situation_id in situation_stats else 0,
                    models=tuple(
                        sorted(
                            (
                                _summarize_outcome_stats(
                                    model_summary_stats,
                                    provider=model_providers.get(model_id, ""),
                                )
                                for model_id, model_summary_stats in situation_model_stats[situation_id].items()
                            ),
                            key=_outcome_group_sort_key,
                        )
                    ),
                )
                for situation_id in situation_model_stats
            ),
            key=lambda leaderboard: leaderboard.situation_id,
        )
    )

    return OutcomeFeedbackSummaryReport(
        generated_at=_summary_generated_at(generated_at),
        total=_summarize_outcome_stats(total_stats),
        models=models,
        providers=providers,
        situations=situations,
        sources=sources,
        model_scorecards=model_scorecards,
        situation_leaderboards=situation_leaderboards,
        applied_evidence_sources=normalized_evidence_sources,
        feedback_policy_metadata=build_feedback_policy_metadata(
            policy,
            max_adjustment=max_adjustment,
        ),
    )


def filter_outcome_feedback_records(
    records: FeedbackAdjustmentInput,
    *,
    evidence_sources: Iterable[str] | None = None,
) -> tuple[DecisionOutcomeRecord, ...]:
    """Normalize and optionally filter feedback records by evidence source."""

    normalized_records = tuple(
        _normalize_feedback_record(raw_record, source=f"<feedback:{index}>")
        for index, raw_record in enumerate(records, start=1)
    )
    normalized_sources = _normalize_evidence_source_filters(evidence_sources)
    if not normalized_sources:
        return normalized_records
    allowed_sources = {value.casefold() for value in normalized_sources}
    return tuple(
        record
        for record in normalized_records
        if outcome_feedback_source(record).casefold() in allowed_sources
    )


def outcome_feedback_source(record: DecisionOutcomeRecord) -> str:
    """Resolve the stable evidence-source label for one feedback record."""

    metadata = record.metadata if isinstance(record.metadata, Mapping) else {}
    for key in ("evidenceSource", "captureSource", "source"):
        raw_value = metadata.get(key)
        if isinstance(raw_value, str) and raw_value.strip():
            return raw_value.strip()
    return "manual-feedback"


def build_feedback_policy_metadata(
    policy: FeedbackAdjustmentPolicyInput | None = None,
    *,
    max_adjustment: float | None = None,
    source: str | None = None,
) -> FeedbackPolicyMetadata:
    resolved_policy = resolve_feedback_adjustment_policy(policy, max_adjustment=max_adjustment)
    default_payload = DEFAULT_FEEDBACK_ADJUSTMENT_POLICY.to_dict()
    policy_payload = resolved_policy.to_dict()
    customized_fields = tuple(
        key
        for key in sorted(policy_payload)
        if key != "schemaVersion" and policy_payload[key] != default_payload.get(key)
    )
    return FeedbackPolicyMetadata(
        source=source or ("default" if not customized_fields else "custom"),
        policy=resolved_policy,
        customized_fields=customized_fields,
    )


def load_feedback_adjustment_policy(path: str | Path) -> FeedbackAdjustmentPolicy:
    policy_path = Path(path)
    with policy_path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    return parse_feedback_adjustment_policy(payload, source=str(policy_path))


def parse_feedback_adjustment_policy(payload: Mapping[str, Any], *, source: str = "<memory>") -> FeedbackAdjustmentPolicy:
    return FeedbackAdjustmentPolicy.from_dict(payload, source=source)


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
    with path.open("r", encoding="utf-8-sig") as handle:
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


def _read_report_payload(report_path: str | Path) -> tuple[Path, bytes, Mapping[str, Any]]:
    path = Path(report_path)
    report_bytes = path.read_bytes()
    report = json.loads(report_bytes.decode("utf-8-sig"))
    if not isinstance(report, Mapping):
        raise OutcomeFeedbackError(f"{path}: persisted report must be a JSON object")
    return path, report_bytes, report


def _decision_outcome_record_from_report(
    *,
    path: Path,
    report_bytes: bytes,
    report: Mapping[str, Any],
    verdict: str,
    score: float | None,
    reason: str,
    tags: Iterable[str],
    override_model_id: str,
    metadata: Mapping[str, Any] | None,
) -> DecisionOutcomeRecord:
    selection = _extract_selected_model(report)
    execution = report.get("execution")
    telemetry = _extract_outcome_record_telemetry(
        report=report,
        execution=execution,
        selection=selection,
        source=str(path),
    )
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
        latency_ms=telemetry.latency_ms,
        input_cost_per_1k=telemetry.input_cost_per_1k,
        output_cost_per_1k=telemetry.output_cost_per_1k,
        estimated_input_cost=telemetry.estimated_input_cost,
        estimated_output_cost=telemetry.estimated_output_cost,
        estimated_total_cost=telemetry.estimated_total_cost,
        verdict=verdict,
        score=score,
        reason=reason,
        tags=tuple(str(tag) for tag in tags),
        override_model_id=override_model_id,
        metadata=dict(metadata or {}),
    )


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
    policy: FeedbackAdjustmentPolicy,
    *,
    weight: float,
) -> None:
    _add_feedback_contribution(
        stats_by_model,
        record.selected_model_id,
        contribution=_selected_model_contribution(record, policy),
        score=_score_for_record(record, policy),
        verdict=record.verdict,
        override_target=False,
        weight=weight,
    )


def _add_feedback_contribution(
    stats_by_model: dict[str, _FeedbackStats],
    model_id: str,
    *,
    contribution: float,
    score: float,
    verdict: str,
    override_target: bool,
    weight: float,
) -> None:
    stats = stats_by_model.setdefault(model_id, _FeedbackStats(model_id=model_id))
    stats.contributions.append(contribution)
    stats.scores.append(score)
    stats.weights.append(weight)
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


def _selected_model_contribution(record: DecisionOutcomeRecord, policy: FeedbackAdjustmentPolicy) -> float:
    if record.verdict == "success":
        return policy.success_base + (_score_for_record(record, policy) * policy.success_score_multiplier)
    if record.verdict == "failure":
        return policy.failure_penalty
    if record.verdict == "quality_concern":
        return policy.quality_concern_penalty
    if record.verdict == "latency_concern":
        return policy.latency_concern_penalty
    if record.verdict == "cost_concern":
        return policy.cost_concern_penalty
    if record.verdict == "manual_override":
        return policy.manual_override_penalty
    return 0.0


def _manual_override_target_contribution(score: float | None, policy: FeedbackAdjustmentPolicy) -> float:
    return policy.manual_override_target_base + (
        _normalize_outcome_score(score, default=policy.default_override_target_score)
        * policy.manual_override_target_score_multiplier
    )


def _score_for_record(record: DecisionOutcomeRecord, policy: FeedbackAdjustmentPolicy) -> float:
    if record.verdict == "success":
        return _normalize_outcome_score(record.score, default=policy.default_success_score)
    if record.verdict == "failure":
        return _normalize_outcome_score(record.score, default=policy.default_failure_score)
    if record.verdict in ("latency_concern", "quality_concern", "cost_concern"):
        return _normalize_outcome_score(record.score, default=policy.default_concern_score)
    if record.verdict == "manual_override":
        return _normalize_outcome_score(record.score, default=policy.default_manual_override_score)
    return _normalize_outcome_score(record.score, default=0.5)


def _normalize_outcome_score(score: float | None, *, default: float) -> float:
    return max(0.0, min(1.0, float(default if score is None else score)))


def _summarize_feedback_stats(
    stats: _FeedbackStats,
    *,
    policy: FeedbackAdjustmentPolicy,
) -> ModelOutcomeFeedbackSummary:
    weighted_count = sum(stats.weights) if stats.weights else float(len(stats.contributions))
    if weighted_count <= 0.0:
        raw_adjustment = 0.0
        average_score = None
    else:
        raw_adjustment = sum(
            contribution * weight
            for contribution, weight in zip(stats.contributions, stats.weights)
        ) / weighted_count
        average_score = round(
            sum(score * weight for score, weight in zip(stats.scores, stats.weights)) / weighted_count,
            4,
        ) if stats.scores else None
    adjustment = round(max(-policy.max_adjustment, min(policy.max_adjustment, raw_adjustment)), 4)
    rationale = [
        f"{stats.record_count} outcome feedback records",
        f"bounded feedback adjustment {adjustment:+.2f}",
    ]
    if policy.recency_half_life_days is not None:
        rationale.append(
            f"recency half-life {policy.recency_half_life_days:.2f} days; weighted records {weighted_count:.2f}"
        )
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
        weighted_record_count=round(weighted_count, 4),
        rationale=tuple(rationale),
    )


def _summary_stats_for(
    summaries: dict[str, _OutcomeSummaryStats],
    group_type: str,
    key: str,
) -> _OutcomeSummaryStats:
    return summaries.setdefault(key, _OutcomeSummaryStats(group_type=group_type, key=key))


def _nested_summary_stats_for(
    nested_summaries: dict[str, dict[str, _OutcomeSummaryStats]],
    outer_key: str,
    group_type: str,
    key: str,
) -> _OutcomeSummaryStats:
    return _summary_stats_for(
        nested_summaries.setdefault(outer_key, {}),
        group_type,
        key,
    )


def _summarize_outcome_stats(
    stats: _OutcomeSummaryStats,
    *,
    model_feedback: ModelOutcomeFeedbackSummary | None = None,
    provider: str = "",
) -> OutcomeFeedbackGroupSummary:
    record_count = stats.record_count
    average_score = round(sum(stats.scores) / len(stats.scores), 4) if stats.scores else None
    return OutcomeFeedbackGroupSummary(
        group_type=stats.group_type,
        key=stats.key,
        record_count=record_count,
        success_count=stats.success_count,
        concern_count=stats.concern_count,
        failure_count=stats.failure_count,
        manual_override_count=stats.manual_override_count,
        average_score=average_score,
        success_rate=_outcome_rate(stats.success_count, record_count),
        concern_rate=_outcome_rate(stats.concern_count, record_count),
        failure_rate=_outcome_rate(stats.failure_count, record_count),
        manual_override_rate=_outcome_rate(stats.manual_override_count, record_count),
        net_outcome_count=stats.success_count - stats.failure_count - stats.concern_count - stats.manual_override_count,
        rank_score=_outcome_rank_score(stats, record_count, model_feedback=model_feedback),
        latest_generated_at=max(stats.generated_at_values) if stats.generated_at_values else "",
        adjustment=model_feedback.adjustment if model_feedback is not None else None,
        weighted_record_count=model_feedback.weighted_record_count if model_feedback is not None else None,
        provider=provider,
        latency_record_count=len(stats.latencies_ms) or None,
        average_latency_ms=_average_metric(stats.latencies_ms, digits=4),
        minimum_latency_ms=_minimum_metric(stats.latencies_ms, digits=4),
        maximum_latency_ms=_maximum_metric(stats.latencies_ms, digits=4),
        cost_record_count=stats.cost_record_count or None,
        average_input_cost_per_1k=_average_metric(stats.input_costs_per_1k, digits=6),
        average_output_cost_per_1k=_average_metric(stats.output_costs_per_1k, digits=6),
        average_estimated_input_cost=_average_metric(stats.estimated_input_costs, digits=6),
        average_estimated_output_cost=_average_metric(stats.estimated_output_costs, digits=6),
        average_estimated_total_cost=_average_metric(stats.estimated_total_costs, digits=6),
    )


def _outcome_rate(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(count / total, 4)


def _outcome_rank_score(
    stats: _OutcomeSummaryStats,
    total: int,
    *,
    model_feedback: ModelOutcomeFeedbackSummary | None,
) -> float:
    success_rate = _outcome_rate(stats.success_count, total)
    failure_rate = _outcome_rate(stats.failure_count, total)
    concern_rate = _outcome_rate(stats.concern_count, total)
    manual_override_rate = _outcome_rate(stats.manual_override_count, total)
    net_outcome_count = stats.success_count - stats.failure_count - stats.concern_count - stats.manual_override_count
    adjustment = model_feedback.adjustment if model_feedback is not None else float(net_outcome_count)
    return round((success_rate * 100.0) + adjustment - (failure_rate * 25.0) - (concern_rate * 10.0) - (manual_override_rate * 25.0), 4)


def _outcome_group_sort_key(summary: OutcomeFeedbackGroupSummary) -> tuple[float, float, int, str]:
    average_score = summary.average_score if summary.average_score is not None else -1.0
    return (-summary.rank_score, -summary.success_rate, -average_score, -summary.record_count, summary.key)


def _average_metric(values: list[float], *, digits: int) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), digits)


def _minimum_metric(values: list[float], *, digits: int) -> float | None:
    if not values:
        return None
    return round(min(values), digits)


def _maximum_metric(values: list[float], *, digits: int) -> float | None:
    if not values:
        return None
    return round(max(values), digits)


def _summary_generated_at(value: datetime | str | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    if isinstance(value, datetime):
        return _ensure_aware_utc(value).isoformat()
    if isinstance(value, str):
        return _parse_feedback_datetime(value, source="<summary>:generatedAt").isoformat()
    raise OutcomeFeedbackError("<summary>: generated_at must be a datetime or ISO timestamp")


def _resolve_feedback_policy(
    policy: FeedbackAdjustmentPolicyInput | None,
    *,
    max_adjustment: float | None,
) -> FeedbackAdjustmentPolicy:
    return resolve_feedback_adjustment_policy(policy, max_adjustment=max_adjustment)


def resolve_feedback_adjustment_policy(
    policy: FeedbackAdjustmentPolicyInput | None = None,
    *,
    max_adjustment: float | None = None,
) -> FeedbackAdjustmentPolicy:
    if policy is None:
        resolved = DEFAULT_FEEDBACK_ADJUSTMENT_POLICY
    elif isinstance(policy, FeedbackAdjustmentPolicy):
        resolved = policy
    elif isinstance(policy, Mapping):
        resolved = parse_feedback_adjustment_policy(policy, source="<feedback-policy>")
    else:
        raise OutcomeFeedbackError(f"Unsupported feedback policy type: {type(policy).__name__}")

    if max_adjustment is None:
        return resolved
    return replace(
        resolved,
        max_adjustment=_validate_non_negative_float(
            max_adjustment,
            "maxAdjustment",
            source="<feedback-policy>",
        ),
    )


def _parse_as_of(as_of: datetime | str | None) -> datetime | None:
    if as_of is None:
        return None
    if isinstance(as_of, datetime):
        return _ensure_aware_utc(as_of)
    if isinstance(as_of, str):
        return _parse_feedback_datetime(as_of, source="<feedback-policy>:asOf")
    raise OutcomeFeedbackError(f"<feedback-policy>: as_of must be a datetime or ISO timestamp")


def _normalize_evidence_source_filters(evidence_sources: Iterable[str] | None) -> tuple[str, ...]:
    if evidence_sources is None:
        return ()
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_value in evidence_sources:
        value = str(raw_value).strip()
        if not value:
            raise OutcomeFeedbackError("<feedback-source>: evidence source must be non-empty")
        normalized_key = value.casefold()
        if normalized_key in seen:
            continue
        seen.add(normalized_key)
        normalized.append(value)
    return tuple(normalized)


def _recency_weight(
    record: DecisionOutcomeRecord,
    policy: FeedbackAdjustmentPolicy,
    *,
    as_of: datetime | None,
) -> float:
    if policy.recency_half_life_days is None:
        return 1.0

    record_time = _parse_feedback_datetime(record.generated_at, source=f"<feedback:{record.record_id}>")
    comparison_time = as_of or datetime.now(timezone.utc)
    age_seconds = max(0.0, (_ensure_aware_utc(comparison_time) - record_time).total_seconds())
    age_days = age_seconds / 86400.0
    return 0.5 ** (age_days / policy.recency_half_life_days)


def _parse_feedback_datetime(value: str, *, source: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise OutcomeFeedbackError(f"{source}: generatedAt must be an ISO timestamp") from exc
    return _ensure_aware_utc(parsed)


def _ensure_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _policy_float(
    payload: Mapping[str, Any],
    *keys: str,
    default: float,
    source: str,
) -> float:
    for key in keys:
        if key in payload:
            return _parse_float(payload[key], field_name=key, source=source)
    return float(default)


def _policy_optional_positive_float(
    payload: Mapping[str, Any],
    *keys: str,
    default: float | None,
    source: str,
) -> float | None:
    for key in keys:
        if key in payload:
            value = payload[key]
            if value in (None, ""):
                return None
            return _validate_positive_float(value, key, source=source)
    return default


def _parse_float(value: Any, *, field_name: str, source: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise OutcomeFeedbackError(f"{source}: {field_name} must be numeric") from exc


def _validate_non_negative_float(value: float, field_name: str, *, source: str) -> float:
    parsed = _parse_float(value, field_name=field_name, source=source)
    if parsed < 0.0:
        raise OutcomeFeedbackError(f"{source}: {field_name} must be 0 or greater")
    return parsed


def _validate_positive_float(value: float, field_name: str, *, source: str) -> float:
    parsed = _parse_float(value, field_name=field_name, source=source)
    if parsed <= 0.0:
        raise OutcomeFeedbackError(f"{source}: {field_name} must be greater than 0")
    return parsed


def _validate_score_range(value: float, field_name: str, *, source: str) -> float:
    parsed = _parse_float(value, field_name=field_name, source=source)
    if parsed < 0.0 or parsed > 1.0:
        raise OutcomeFeedbackError(f"{source}: {field_name} must be between 0.0 and 1.0")
    return parsed


def _camel_name(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.title() for part in tail)


DEFAULT_FEEDBACK_ADJUSTMENT_POLICY = FeedbackAdjustmentPolicy()


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


def _comparative_execution_attempts(
    report: Mapping[str, Any],
    *,
    source: str,
) -> tuple[_ComparativeExecutionCapture, ...]:
    executions = report.get("executions")
    if isinstance(executions, list):
        attempts: list[_ComparativeExecutionCapture] = []
        situation_id = str(report.get("situationId", report.get("taskId", _first_decision_task_id(report))) or "")
        for index, attempt in enumerate(executions, start=1):
            if not isinstance(attempt, Mapping):
                raise OutcomeFeedbackError(f"{source}: executions[{index}] must be an object")
            attempts.append(
                _ComparativeExecutionCapture(
                    attempt=attempt,
                    source_label=f"executions[{index}]",
                    report_type="compare-run",
                    situation_id=situation_id,
                    comparison_attempt_number=_comparison_attempt_number(attempt, fallback=index),
                    comparison_executed_count=len(executions),
                )
            )
        if not attempts:
            raise OutcomeFeedbackError(f"{source}: cannot capture comparative outcomes without executed candidates")
        return tuple(attempts)

    situations = report.get("situations")
    if not isinstance(situations, list):
        raise OutcomeFeedbackError(
            f"{source}: cannot capture comparative outcomes without an executions list or situations list"
        )

    attempts = []
    suite_id = str(report.get("suiteId", "") or "")
    situation_count = len(situations)
    batch_executed_candidate_count = _comparison_batch_executed_candidate_count(report)
    for situation_index, situation in enumerate(situations, start=1):
        if not isinstance(situation, Mapping):
            raise OutcomeFeedbackError(f"{source}: situations[{situation_index}] must be an object")
        situation_executions = situation.get("executions")
        if not isinstance(situation_executions, list):
            raise OutcomeFeedbackError(
                f"{source}: situations[{situation_index}].executions must be a list"
            )
        situation_id = str(situation.get("situationId", situation.get("taskId", "")) or "")
        for attempt_index, attempt in enumerate(situation_executions, start=1):
            if not isinstance(attempt, Mapping):
                raise OutcomeFeedbackError(
                    f"{source}: situations[{situation_index}].executions[{attempt_index}] must be an object"
                )
            attempts.append(
                _ComparativeExecutionCapture(
                    attempt=attempt,
                    source_label=f"situations[{situation_index}].executions[{attempt_index}]",
                    report_type="compare-batch",
                    situation_id=situation_id,
                    comparison_attempt_number=_comparison_attempt_number(attempt, fallback=attempt_index),
                    comparison_executed_count=len(situation_executions),
                    suite_id=suite_id,
                    situation_index=situation_index,
                    situation_count=situation_count,
                    batch_executed_candidate_count=batch_executed_candidate_count,
                )
            )
    if not attempts:
        raise OutcomeFeedbackError(f"{source}: cannot capture comparative outcomes without executed candidates")
    return tuple(attempts)


def _comparison_batch_executed_candidate_count(report: Mapping[str, Any]) -> int:
    comparison = report.get("comparison")
    if isinstance(comparison, Mapping):
        raw_value = comparison.get("executedCandidateCount")
        try:
            executed_candidate_count = int(raw_value)
        except (TypeError, ValueError):
            executed_candidate_count = None
        if executed_candidate_count is not None and executed_candidate_count >= 0:
            return executed_candidate_count

    situations = report.get("situations")
    if not isinstance(situations, list):
        return 0

    executed_candidate_count = 0
    for situation in situations:
        if not isinstance(situation, Mapping):
            continue
        situation_executions = situation.get("executions")
        if not isinstance(situation_executions, list):
            continue
        executed_candidate_count += len(situation_executions)
    return executed_candidate_count


def _comparison_attempt_number(attempt: Mapping[str, Any], *, fallback: int) -> int:
    raw_value = attempt.get("attemptNumber")
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return fallback
    return value if value >= 1 else fallback


def _execution_status(execution: Any) -> str:
    if isinstance(execution, Mapping):
        return str(execution.get("status", "") or "")
    return ""


def _report_generated_at(report: Mapping[str, Any]) -> str:
    metadata = report.get("reportMetadata")
    if isinstance(metadata, Mapping):
        return str(metadata.get("generatedAt", "") or "")
    return ""


def _extract_outcome_record_telemetry(
    *,
    report: Mapping[str, Any],
    execution: Any,
    selection: Mapping[str, Any],
    source: str,
) -> _OutcomeRecordTelemetry:
    telemetry_sources = _telemetry_sources(report=report, execution=execution, selection=selection)
    return _OutcomeRecordTelemetry(
        latency_ms=_first_optional_non_negative_float(
            telemetry_sources,
            ("elapsedMs", "elapsed_ms", "latencyMs", "latency_ms"),
            source=source,
        ),
        input_cost_per_1k=_first_optional_non_negative_float(
            telemetry_sources,
            ("inputCostPer1k", "input_cost_per_1k"),
            source=source,
        ),
        output_cost_per_1k=_first_optional_non_negative_float(
            telemetry_sources,
            ("outputCostPer1k", "output_cost_per_1k"),
            source=source,
        ),
        estimated_input_cost=_first_optional_non_negative_float(
            telemetry_sources,
            ("estimatedInputCost", "estimated_input_cost", "inputCost", "input_cost"),
            source=source,
        ),
        estimated_output_cost=_first_optional_non_negative_float(
            telemetry_sources,
            ("estimatedOutputCost", "estimated_output_cost", "outputCost", "output_cost"),
            source=source,
        ),
        estimated_total_cost=_first_optional_non_negative_float(
            telemetry_sources,
            ("estimatedTotalCost", "estimated_total_cost", "totalCost", "total_cost"),
            source=source,
        ),
    )


def _telemetry_sources(
    *,
    report: Mapping[str, Any],
    execution: Any,
    selection: Mapping[str, Any],
) -> tuple[Mapping[str, Any], ...]:
    sources: list[Mapping[str, Any]] = []
    _append_telemetry_source(sources, execution)
    _append_telemetry_source(sources, selection)
    _append_telemetry_source(sources, report.get("metadata"))
    _append_telemetry_source(sources, report.get("telemetry"))
    _append_telemetry_source(sources, report)
    return tuple(sources)


def _append_telemetry_source(sources: list[Mapping[str, Any]], value: Any) -> None:
    if not isinstance(value, Mapping):
        return
    sources.append(value)
    for nested_key in ("telemetry", "metadata", "cost", "usage"):
        nested = value.get(nested_key)
        if isinstance(nested, Mapping):
            _append_telemetry_source(sources, nested)


def _first_optional_non_negative_float(
    sources: Iterable[Mapping[str, Any]],
    keys: tuple[str, ...],
    *,
    source: str,
) -> float | None:
    for mapping in sources:
        for key in keys:
            if key not in mapping:
                continue
            return _optional_non_negative_float(mapping.get(key), field_name=key, source=source)
    return None


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


def _optional_non_negative_float(value: Any, *, field_name: str, source: str) -> float | None:
    if value in (None, ""):
        return None
    parsed = _parse_float(value, field_name=field_name, source=source)
    if parsed < 0.0:
        raise OutcomeFeedbackError(f"{source}: {field_name} must be 0 or greater")
    return round(parsed, 6)


def _metadata_mapping(value: Any, *, source: str) -> Mapping[str, Any]:
    if value in (None, ""):
        return {}
    if not isinstance(value, Mapping):
        raise OutcomeFeedbackError(f"{source}: metadata must be an object")
    return dict(value)
