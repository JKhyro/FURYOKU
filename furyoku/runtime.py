from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

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
    ProviderExecutionRequest,
    ProviderExecutionResult,
    execute_selected_model,
)


@dataclass(frozen=True)
class RoutedExecutionResult:
    """A complete route-and-execute decision for one task."""

    selection: ModelScore
    execution: ProviderExecutionResult
    report: ModelDecisionReport | None = None

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
class DecisionSituationExecutionResult:
    """A calibrated decision-suite situation executed through a selected endpoint."""

    report: ModelDecisionReport
    situation_id: str
    decision: SituationDecision
    selection: ModelScore | None
    execution: ProviderExecutionResult | None

    @property
    def ok(self) -> bool:
        return self.selection is not None and self.selection.eligible and self.execution is not None and self.execution.ok

    @property
    def model_id(self) -> str | None:
        return self.selection.model.model_id if self.selection else None

    @property
    def provider(self) -> str | None:
        return self.selection.model.provider if self.selection else None


def route_and_execute(
    models: list[ModelEndpoint],
    task: TaskProfile,
    request: ProviderExecutionRequest | str,
    *,
    readiness: ReadinessEvidenceInput | None = None,
    feedback: FeedbackAdjustmentInput | None = None,
    feedback_policy: FeedbackAdjustmentPolicyInput | None = None,
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


def execute_decision_situation(
    models: list[ModelEndpoint],
    decision_input: DecisionSuite | Iterable[TaskProfile] | None,
    situation_id: str,
    request: ProviderExecutionRequest | str,
    *,
    readiness: ReadinessEvidenceInput | None = None,
    feedback: FeedbackAdjustmentInput | None = None,
    feedback_policy: FeedbackAdjustmentPolicyInput | None = None,
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
