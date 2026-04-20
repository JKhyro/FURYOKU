from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from .character_arrays import (
    CharacterArray,
    CharacterArrayError,
    CharacterArrayMember,
)
from .character_profiles import CharacterProfile, CharacterProfileSelection, select_character_profile_models
from .model_decisions import (
    DecisionSuite,
    ModelDecisionError,
    ModelDecisionReport,
    ReadinessEvidenceInput,
    SituationDecision,
    evaluate_model_decisions,
)
from .model_router import ModelEndpoint, ModelScore, RouterError, RoutingScorePolicyInput, TaskProfile, select_model
from .outcome_feedback import FeedbackAdjustmentInput, FeedbackAdjustmentPolicyInput
from .provider_adapters import (
    ProviderAdapter,
    ProviderAdapterError,
    ProviderExecutionRequest,
    ProviderExecutionResult,
    execute_selected_model,
)


@dataclass(frozen=True)
class ProviderExecutionAttempt:
    """One attempted execution in a routed fallback chain."""

    attempt_number: int
    selection: ModelScore
    execution: ProviderExecutionResult

    @property
    def ok(self) -> bool:
        return self.selection.eligible and self.execution.ok


@dataclass(frozen=True)
class RoutedExecutionResult:
    """A complete route-and-execute decision for one task."""

    selection: ModelScore
    execution: ProviderExecutionResult
    report: ModelDecisionReport | None = None
    execution_attempts: tuple[ProviderExecutionAttempt, ...] = ()

    @property
    def ok(self) -> bool:
        return self.selection.eligible and self.execution.ok

    @property
    def model_id(self) -> str:
        return self.selection.model.model_id

    @property
    def provider(self) -> str:
        return self.selection.model.provider


@dataclass(frozen=True)
class CharacterRoleExecutionResult:
    """A selected CHARACTER role assignment executed through a provider adapter."""

    character_selection: CharacterProfileSelection
    role_id: str
    selection: ModelScore
    execution: ProviderExecutionResult

    @property
    def ok(self) -> bool:
        return self.selection.eligible and self.execution.ok

    @property
    def character_id(self) -> str:
        return self.character_selection.character_id

    @property
    def model_id(self) -> str:
        return self.selection.model.model_id

    @property
    def provider(self) -> str:
        return self.selection.model.provider


@dataclass(frozen=True)
class CharacterArrayMemberExecutionResult:
    """One CHARACTER ARRAY (ACA) member's selected role executed through a provider adapter."""

    array: CharacterArray
    member: CharacterArrayMember
    slot_id: str
    role_result: CharacterRoleExecutionResult

    @property
    def ok(self) -> bool:
        return self.role_result.ok

    @property
    def array_id(self) -> str:
        return self.array.array_id

    @property
    def character_id(self) -> str:
        return self.role_result.character_id

    @property
    def role_id(self) -> str:
        return self.role_result.role_id

    @property
    def primary(self) -> bool:
        return self.member.primary

    @property
    def selection(self) -> ModelScore:
        return self.role_result.selection

    @property
    def execution(self) -> ProviderExecutionResult:
        return self.role_result.execution

    @property
    def character_selection(self) -> CharacterProfileSelection:
        return self.role_result.character_selection

    @property
    def model_id(self) -> str:
        return self.role_result.model_id

    @property
    def provider(self) -> str:
        return self.role_result.provider


@dataclass(frozen=True)
class DecisionSituationExecutionResult:
    """A calibrated decision-suite situation executed through a selected endpoint."""

    report: ModelDecisionReport
    situation_id: str
    decision: SituationDecision
    selection: ModelScore | None
    execution: ProviderExecutionResult | None
    execution_attempts: tuple[ProviderExecutionAttempt, ...] = ()

    @property
    def ok(self) -> bool:
        return self.selection is not None and self.selection.eligible and self.execution is not None and self.execution.ok

    @property
    def model_id(self) -> str | None:
        return self.selection.model.model_id if self.selection else None

    @property
    def provider(self) -> str | None:
        return self.selection.model.provider if self.selection else None


@dataclass(frozen=True)
class ComparativeEvaluationResult:
    """Execution comparison across eligible ranked candidates for one task/situation."""

    report: ModelDecisionReport
    decision: SituationDecision
    execution_attempts: tuple[ProviderExecutionAttempt, ...]
    situation_id: str = ""
    max_candidates: int | None = None

    @property
    def ok(self) -> bool:
        return any(attempt.ok for attempt in self.execution_attempts)

    @property
    def executed_count(self) -> int:
        return len(self.execution_attempts)

    @property
    def task_id(self) -> str:
        return self.decision.task.task_id

    @property
    def successful_count(self) -> int:
        return sum(1 for attempt in self.execution_attempts if attempt.ok)

    @property
    def failed_count(self) -> int:
        return len(self.execution_attempts) - self.successful_count


@dataclass(frozen=True)
class ComparativeExecutionBatchResult:
    """Aggregate comparative execution report across multiple decision-suite situations."""

    report: ModelDecisionReport
    situation_results: tuple[ComparativeEvaluationResult, ...]
    suite_id: str = ""
    max_candidates: int | None = None

    @property
    def ok(self) -> bool:
        return not self.report.blocked_tasks and all(result.ok for result in self.situation_results)

    @property
    def successful_situation_count(self) -> int:
        return sum(1 for result in self.situation_results if result.ok)

    @property
    def failed_situation_count(self) -> int:
        return sum(1 for result in self.situation_results if result.decision.selected is not None and not result.ok)

    @property
    def blocked_situation_count(self) -> int:
        return sum(1 for result in self.situation_results if result.decision.selected is None)

    @property
    def executed_candidate_count(self) -> int:
        return sum(result.executed_count for result in self.situation_results)

    @property
    def successful_execution_count(self) -> int:
        return sum(result.successful_count for result in self.situation_results)

    @property
    def failed_execution_count(self) -> int:
        return sum(result.failed_count for result in self.situation_results)


def route_and_execute(
    models: list[ModelEndpoint],
    task: TaskProfile,
    request: ProviderExecutionRequest | str,
    *,
    readiness: ReadinessEvidenceInput | None = None,
    feedback: FeedbackAdjustmentInput | None = None,
    feedback_policy: FeedbackAdjustmentPolicyInput | None = None,
    evidence_sources: Iterable[str] | None = None,
    routing_policy: RoutingScorePolicyInput | None = None,
    adapters: Mapping[str, ProviderAdapter] | None = None,
) -> RoutedExecutionResult:
    """Select the best eligible model for a task, then execute it."""

    report = None
    if feedback is None and readiness is None and routing_policy is None:
        selection = select_model(models, task)
    else:
        report = evaluate_model_decisions(
            models,
            [task],
            readiness=readiness,
            feedback=feedback,
            feedback_policy=feedback_policy,
            evidence_sources=evidence_sources,
            routing_policy=routing_policy,
        )
        selection = report.selected_for(task.task_id)
        if selection is None:
            decision = report.situations[task.task_id]
            blocker_summary = "; ".join(
                f"{model_id}: {', '.join(blockers)}"
                for model_id, blockers in decision.blockers.items()
            )
            raise RouterError(f"No eligible model for task '{task.task_id}'. {blocker_summary}")
    execution = execute_selected_model(selection, request, adapters=adapters)
    return RoutedExecutionResult(selection=selection, execution=execution, report=report)


def route_and_execute_with_fallback(
    models: list[ModelEndpoint],
    task: TaskProfile,
    request: ProviderExecutionRequest | str,
    *,
    readiness: ReadinessEvidenceInput | None = None,
    feedback: FeedbackAdjustmentInput | None = None,
    feedback_policy: FeedbackAdjustmentPolicyInput | None = None,
    evidence_sources: Iterable[str] | None = None,
    routing_policy: RoutingScorePolicyInput | None = None,
    max_attempts: int | None = None,
    adapters: Mapping[str, ProviderAdapter] | None = None,
) -> RoutedExecutionResult:
    """Execute eligible ranked candidates in order until one succeeds or all attempts fail."""

    _validate_max_attempts(max_attempts)
    report = evaluate_model_decisions(
        models,
        [task],
        readiness=readiness,
        feedback=feedback,
        feedback_policy=feedback_policy,
        evidence_sources=evidence_sources,
        routing_policy=routing_policy,
    )
    decision = report.situations[task.task_id]
    if decision.selected is None:
        blocker_summary = "; ".join(
            f"{model_id}: {', '.join(blockers)}"
            for model_id, blockers in decision.blockers.items()
        )
        raise RouterError(f"No eligible model for task '{task.task_id}'. {blocker_summary}")

    attempts = _execute_fallback_attempts(
        decision.ranked,
        request,
        max_attempts=max_attempts,
        adapters=adapters,
    )
    final_attempt = attempts[-1]
    return RoutedExecutionResult(
        selection=final_attempt.selection,
        execution=final_attempt.execution,
        report=report,
        execution_attempts=attempts,
    )


def compare_model_executions(
    models: list[ModelEndpoint],
    task: TaskProfile,
    request: ProviderExecutionRequest | str,
    *,
    readiness: ReadinessEvidenceInput | None = None,
    feedback: FeedbackAdjustmentInput | None = None,
    feedback_policy: FeedbackAdjustmentPolicyInput | None = None,
    routing_policy: RoutingScorePolicyInput | None = None,
    max_candidates: int | None = None,
    adapters: Mapping[str, ProviderAdapter] | None = None,
) -> ComparativeEvaluationResult:
    """Execute the same request across eligible ranked candidates for comparison."""

    _validate_positive_limit(max_candidates, "max_candidates")
    report = evaluate_model_decisions(
        models,
        [task],
        readiness=readiness,
        feedback=feedback,
        feedback_policy=feedback_policy,
        routing_policy=routing_policy,
    )
    decision = report.situations[task.task_id]
    if decision.selected is None:
        blocker_summary = "; ".join(
            f"{model_id}: {', '.join(blockers)}"
            for model_id, blockers in decision.blockers.items()
        )
        raise RouterError(f"No eligible model for task '{task.task_id}'. {blocker_summary}")

    return ComparativeEvaluationResult(
        report=report,
        decision=decision,
        max_candidates=max_candidates,
        execution_attempts=_execute_comparative_attempts(
            decision.ranked,
            request,
            max_candidates=max_candidates,
            adapters=adapters,
        ),
    )


def execute_decision_situation(
    models: list[ModelEndpoint],
    decision_input: DecisionSuite | Iterable[TaskProfile] | None,
    situation_id: str,
    request: ProviderExecutionRequest | str,
    *,
    readiness: ReadinessEvidenceInput | None = None,
    feedback: FeedbackAdjustmentInput | None = None,
    feedback_policy: FeedbackAdjustmentPolicyInput | None = None,
    evidence_sources: Iterable[str] | None = None,
    routing_policy: RoutingScorePolicyInput | None = None,
    adapters: Mapping[str, ProviderAdapter] | None = None,
) -> DecisionSituationExecutionResult:
    """Run one calibrated decision situation using the same selection evidence as `decide`."""

    report = evaluate_model_decisions(
        models,
        decision_input,
        readiness=readiness,
        feedback=feedback,
        feedback_policy=feedback_policy,
        evidence_sources=evidence_sources,
        routing_policy=routing_policy,
    )
    try:
        decision = report.situations[situation_id]
    except KeyError as exc:
        available = ", ".join(report.situations)
        raise ModelDecisionError(
            f"Unknown decision situation '{situation_id}'. Available situations: {available}"
        ) from exc

    if decision.selected is None:
        return DecisionSituationExecutionResult(
            report=report,
            situation_id=situation_id,
            decision=decision,
            selection=None,
            execution=None,
        )

    execution = execute_selected_model(decision.selected, request, adapters=adapters)
    return DecisionSituationExecutionResult(
        report=report,
        situation_id=situation_id,
        decision=decision,
        selection=decision.selected,
        execution=execution,
    )


def execute_decision_situation_with_fallback(
    models: list[ModelEndpoint],
    decision_input: DecisionSuite | Iterable[TaskProfile] | None,
    situation_id: str,
    request: ProviderExecutionRequest | str,
    *,
    readiness: ReadinessEvidenceInput | None = None,
    feedback: FeedbackAdjustmentInput | None = None,
    feedback_policy: FeedbackAdjustmentPolicyInput | None = None,
    evidence_sources: Iterable[str] | None = None,
    routing_policy: RoutingScorePolicyInput | None = None,
    max_attempts: int | None = None,
    adapters: Mapping[str, ProviderAdapter] | None = None,
) -> DecisionSituationExecutionResult:
    """Run a calibrated situation with fallback across eligible ranked candidates."""

    _validate_max_attempts(max_attempts)
    report = evaluate_model_decisions(
        models,
        decision_input,
        readiness=readiness,
        feedback=feedback,
        feedback_policy=feedback_policy,
        evidence_sources=evidence_sources,
        routing_policy=routing_policy,
    )
    try:
        decision = report.situations[situation_id]
    except KeyError as exc:
        available = ", ".join(report.situations)
        raise ModelDecisionError(
            f"Unknown decision situation '{situation_id}'. Available situations: {available}"
        ) from exc

    if decision.selected is None:
        return DecisionSituationExecutionResult(
            report=report,
            situation_id=situation_id,
            decision=decision,
            selection=None,
            execution=None,
        )

    attempts = _execute_fallback_attempts(
        decision.ranked,
        request,
        max_attempts=max_attempts,
        adapters=adapters,
    )
    final_attempt = attempts[-1]
    return DecisionSituationExecutionResult(
        report=report,
        situation_id=situation_id,
        decision=decision,
        selection=final_attempt.selection,
        execution=final_attempt.execution,
        execution_attempts=attempts,
    )


def compare_decision_situation_executions(
    models: list[ModelEndpoint],
    decision_input: DecisionSuite | Iterable[TaskProfile] | None,
    situation_id: str,
    request: ProviderExecutionRequest | str,
    *,
    readiness: ReadinessEvidenceInput | None = None,
    feedback: FeedbackAdjustmentInput | None = None,
    feedback_policy: FeedbackAdjustmentPolicyInput | None = None,
    routing_policy: RoutingScorePolicyInput | None = None,
    max_candidates: int | None = None,
    adapters: Mapping[str, ProviderAdapter] | None = None,
) -> ComparativeEvaluationResult:
    """Compare eligible ranked candidates for one calibrated decision-suite situation."""

    _validate_positive_limit(max_candidates, "max_candidates")
    report = evaluate_model_decisions(
        models,
        decision_input,
        readiness=readiness,
        feedback=feedback,
        feedback_policy=feedback_policy,
        routing_policy=routing_policy,
    )
    try:
        decision = report.situations[situation_id]
    except KeyError as exc:
        available = ", ".join(report.situations)
        raise ModelDecisionError(
            f"Unknown decision situation '{situation_id}'. Available situations: {available}"
        ) from exc

    return ComparativeEvaluationResult(
        report=report,
        decision=decision,
        situation_id=situation_id,
        max_candidates=max_candidates,
        execution_attempts=_execute_comparative_attempts(
            decision.ranked,
            request,
            max_candidates=max_candidates,
            adapters=adapters,
        ) if decision.selected is not None else (),
    )


def compare_decision_suite_executions(
    models: list[ModelEndpoint],
    decision_input: DecisionSuite | Iterable[TaskProfile] | None,
    requests_by_situation: Mapping[str, ProviderExecutionRequest | str],
    *,
    readiness: ReadinessEvidenceInput | None = None,
    feedback: FeedbackAdjustmentInput | None = None,
    feedback_policy: FeedbackAdjustmentPolicyInput | None = None,
    routing_policy: RoutingScorePolicyInput | None = None,
    max_candidates: int | None = None,
    adapters: Mapping[str, ProviderAdapter] | None = None,
) -> ComparativeExecutionBatchResult:
    """Compare eligible ranked candidates across every situation in a decision suite."""

    _validate_positive_limit(max_candidates, "max_candidates")
    report = evaluate_model_decisions(
        models,
        decision_input,
        readiness=readiness,
        feedback=feedback,
        feedback_policy=feedback_policy,
        routing_policy=routing_policy,
    )
    _validate_suite_batch_requests(report, requests_by_situation)
    situation_results = tuple(
        ComparativeEvaluationResult(
            report=report,
            decision=decision,
            situation_id=decision.task.task_id,
            max_candidates=max_candidates,
            execution_attempts=(
                _execute_comparative_attempts(
                    decision.ranked,
                    requests_by_situation[decision.task.task_id],
                    max_candidates=max_candidates,
                    adapters=adapters,
                )
                if decision.selected is not None
                else ()
            ),
        )
        for decision in report.decisions
    )
    return ComparativeExecutionBatchResult(
        report=report,
        suite_id=decision_input.suite_id if isinstance(decision_input, DecisionSuite) else "",
        situation_results=situation_results,
        max_candidates=max_candidates,
    )


def execute_character_role(
    models: list[ModelEndpoint],
    profile: CharacterProfile,
    request: ProviderExecutionRequest | str,
    *,
    role_id: str | None = None,
    allow_reuse: bool = True,
    readiness: ReadinessEvidenceInput | None = None,
    adapters: Mapping[str, ProviderAdapter] | None = None,
) -> CharacterRoleExecutionResult:
    """Select all CHARACTER role assignments, then execute one role."""

    character_selection = select_character_profile_models(
        models,
        profile,
        allow_reuse=allow_reuse,
        readiness=readiness,
    )
    resolved_role_id = role_id or character_selection.primary_role
    if resolved_role_id not in character_selection.roles:
        available_roles = ", ".join(character_selection.roles)
        raise RouterError(f"Unknown CHARACTER role '{resolved_role_id}'. Available roles: {available_roles}")
    selection = character_selection.roles[resolved_role_id]
    execution = execute_selected_model(selection, request, adapters=adapters)
    return CharacterRoleExecutionResult(
        character_selection=character_selection,
        role_id=resolved_role_id,
        selection=selection,
        execution=execution,
    )


def execute_character_array_member(
    models: list[ModelEndpoint],
    array: CharacterArray,
    request: ProviderExecutionRequest | str,
    *,
    slot_id: str | None = None,
    role_id: str | None = None,
    allow_reuse: bool = True,
    readiness: ReadinessEvidenceInput | None = None,
    adapters: Mapping[str, ProviderAdapter] | None = None,
) -> CharacterArrayMemberExecutionResult:
    """Execute one role on one CHARACTER member of an Agentic Character Array."""

    if not isinstance(array, CharacterArray):
        raise CharacterArrayError(
            "CHARACTER ARRAY execution requires a parsed CharacterArray"
        )
    if slot_id is None:
        member = next(
            (candidate for candidate in array.members if candidate.primary),
            array.members[0],
        )
    else:
        member = array.member(slot_id)
    role_result = execute_character_role(
        models,
        member.profile,
        request,
        role_id=role_id,
        allow_reuse=allow_reuse,
        readiness=readiness,
        adapters=adapters,
    )
    return CharacterArrayMemberExecutionResult(
        array=array,
        member=member,
        slot_id=member.slot_id,
        role_result=role_result,
    )


def _execute_fallback_attempts(
    ranked: tuple[ModelScore, ...],
    request: ProviderExecutionRequest | str,
    *,
    max_attempts: int | None,
    adapters: Mapping[str, ProviderAdapter] | None,
) -> tuple[ProviderExecutionAttempt, ...]:
    return _execute_eligible_attempts(
        ranked,
        request,
        max_attempts=max_attempts,
        adapters=adapters,
        stop_on_success=True,
    )


def _execute_comparative_attempts(
    ranked: tuple[ModelScore, ...],
    request: ProviderExecutionRequest | str,
    *,
    max_candidates: int | None,
    adapters: Mapping[str, ProviderAdapter] | None,
) -> tuple[ProviderExecutionAttempt, ...]:
    return _execute_eligible_attempts(
        ranked,
        request,
        max_attempts=max_candidates,
        adapters=adapters,
        stop_on_success=False,
    )


def _execute_eligible_attempts(
    ranked: tuple[ModelScore, ...],
    request: ProviderExecutionRequest | str,
    *,
    max_attempts: int | None,
    adapters: Mapping[str, ProviderAdapter] | None,
    stop_on_success: bool,
) -> tuple[ProviderExecutionAttempt, ...]:
    eligible = [selection for selection in ranked if selection.eligible]
    if max_attempts is not None:
        eligible = eligible[:max_attempts]
    attempts: list[ProviderExecutionAttempt] = []
    for attempt_number, selection in enumerate(eligible, start=1):
        execution = _execute_selected_model_safely(selection, request, adapters=adapters)
        attempts.append(
            ProviderExecutionAttempt(
                attempt_number=attempt_number,
                selection=selection,
                execution=execution,
            )
        )
        if stop_on_success and execution.ok:
            break
    return tuple(attempts)


def _execute_selected_model_safely(
    selection: ModelScore,
    request: ProviderExecutionRequest | str,
    *,
    adapters: Mapping[str, ProviderAdapter] | None,
) -> ProviderExecutionResult:
    try:
        return execute_selected_model(selection, request, adapters=adapters)
    except ProviderAdapterError as exc:
        return ProviderExecutionResult(
            model_id=selection.model.model_id,
            provider=selection.model.provider,
            status="error",
            error=str(exc),
        )


def _validate_max_attempts(max_attempts: int | None) -> None:
    _validate_positive_limit(max_attempts, "max_attempts")


def _validate_suite_batch_requests(
    report: ModelDecisionReport,
    requests_by_situation: Mapping[str, ProviderExecutionRequest | str],
) -> None:
    expected = {decision.task.task_id for decision in report.decisions}
    provided = set(requests_by_situation)
    missing = sorted(expected - provided)
    if missing:
        raise ModelDecisionError(
            f"Missing comparative batch requests for situations: {', '.join(missing)}"
        )
    unknown = sorted(provided - expected)
    if unknown:
        raise ModelDecisionError(
            f"Unknown comparative batch request situations: {', '.join(unknown)}"
        )


def _validate_positive_limit(limit: int | None, name: str) -> None:
    if limit is not None and limit < 1:
        raise RouterError(f"{name} must be at least 1")
