from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from .model_router import ModelEndpoint, ModelScore, TaskProfile, rank_models
from .task_profiles import parse_task_profile


class ModelDecisionError(ValueError):
    """Raised when a multi-situation model decision request is malformed."""


@dataclass(frozen=True)
class DecisionSuite:
    """Reusable set of situations for comparing local, CLI, and API models."""

    suite_id: str
    situations: tuple[TaskProfile, ...]
    description: str = ""


@dataclass(frozen=True)
class ModelDecisionSummary:
    """Compatibility summary for one model across a decision suite."""

    model_id: str
    provider: str
    selected_count: int
    eligible_count: int
    average_score: float
    blocked_count: int

    def to_dict(self) -> dict:
        return {
            "modelId": self.model_id,
            "provider": self.provider,
            "selectedCount": self.selected_count,
            "eligibleCount": self.eligible_count,
            "averageScore": self.average_score,
            "blockedCount": self.blocked_count,
        }


@dataclass(frozen=True)
class SituationDecision:
    """Ranked model evidence for one task/situation profile."""

    task: TaskProfile
    ranked: tuple[ModelScore, ...]
    selected: ModelScore | None
    blockers: Mapping[str, tuple[str, ...]]
    rationale: tuple[str, ...]

    @property
    def eligible(self) -> bool:
        return self.selected is not None

    @property
    def eligible_model_ids(self) -> tuple[str, ...]:
        return tuple(score.model.model_id for score in self.ranked if score.eligible)

    def to_dict(self) -> dict:
        return {
            "taskId": self.task.task_id,
            "description": self.task.description,
            "eligible": self.eligible,
            "selectedModelId": self.selected.model.model_id if self.selected else None,
            "selectedProvider": self.selected.model.provider if self.selected else None,
            "ranked": [_score_to_dict(score) for score in self.ranked],
            "blockers": {model_id: list(blockers) for model_id, blockers in self.blockers.items()},
            "rationale": list(self.rationale),
        }


@dataclass(frozen=True)
class ModelCoverage:
    """Aggregate coverage for one registered endpoint across all situations."""

    model: ModelEndpoint
    eligible_situations: tuple[str, ...]
    selected_situations: tuple[str, ...]
    blocked_situations: Mapping[str, tuple[str, ...]]
    average_eligible_score: float | None
    rationale: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "modelId": self.model.model_id,
            "provider": self.model.provider,
            "eligibleSituations": list(self.eligible_situations),
            "selectedSituations": list(self.selected_situations),
            "blockedSituations": {
                task_id: list(blockers) for task_id, blockers in self.blocked_situations.items()
            },
            "averageEligibleScore": self.average_eligible_score,
            "rationale": list(self.rationale),
        }


@dataclass(frozen=True)
class ProviderCoverage:
    """Aggregate coverage for a provider kind across all registered endpoints."""

    provider: str
    model_ids: tuple[str, ...]
    eligible_situations: tuple[str, ...]
    selected_situations: tuple[str, ...]
    blocked_situations: Mapping[str, tuple[str, ...]]
    rationale: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "modelIds": list(self.model_ids),
            "eligibleSituations": list(self.eligible_situations),
            "selectedSituations": list(self.selected_situations),
            "blockedSituations": {
                task_id: list(blockers) for task_id, blockers in self.blocked_situations.items()
            },
            "rationale": list(self.rationale),
        }


@dataclass(frozen=True)
class ModelDecisionAggregate:
    """Cross-situation model/provider coverage and blockers."""

    model_count: int
    situation_count: int
    selected_model_ids: tuple[str, ...]
    selected_providers: tuple[str, ...]
    model_coverage: Mapping[str, ModelCoverage]
    provider_coverage: Mapping[str, ProviderCoverage]
    blockers: Mapping[str, Mapping[str, tuple[str, ...]]]
    rationale: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "modelCount": self.model_count,
            "situationCount": self.situation_count,
            "selectedModelIds": list(self.selected_model_ids),
            "selectedProviders": list(self.selected_providers),
            "modelCoverage": {
                model_id: coverage.to_dict()
                for model_id, coverage in self.model_coverage.items()
            },
            "providerCoverage": {
                provider: coverage.to_dict()
                for provider, coverage in self.provider_coverage.items()
            },
            "blockers": {
                task_id: {
                    model_id: list(blockers)
                    for model_id, blockers in model_blockers.items()
                }
                for task_id, model_blockers in self.blockers.items()
            },
            "rationale": list(self.rationale),
        }


@dataclass(frozen=True)
class ModelDecisionReport:
    """Complete multi-model decision report for a group of task situations."""

    situations: Mapping[str, SituationDecision]
    aggregate: ModelDecisionAggregate

    @property
    def decisions(self) -> tuple[SituationDecision, ...]:
        return tuple(self.situations.values())

    @property
    def summaries(self) -> tuple[ModelDecisionSummary, ...]:
        summaries = [
            ModelDecisionSummary(
                model_id=coverage.model.model_id,
                provider=coverage.model.provider,
                selected_count=len(coverage.selected_situations),
                eligible_count=len(coverage.eligible_situations),
                average_score=coverage.average_eligible_score or 0.0,
                blocked_count=len(coverage.blocked_situations),
            )
            for coverage in self.aggregate.model_coverage.values()
        ]
        return tuple(
            sorted(summaries, key=lambda item: (item.selected_count, item.average_score, item.model_id), reverse=True)
        )

    @property
    def blocked_tasks(self) -> tuple[str, ...]:
        return tuple(task_id for task_id, decision in self.situations.items() if not decision.eligible)

    def selected_for(self, task_id: str) -> ModelScore | None:
        try:
            return self.situations[task_id].selected
        except KeyError as exc:
            raise ModelDecisionError(f"Unknown task situation '{task_id}'") from exc

    def selected_model_for(self, task_id: str) -> str | None:
        selected = self.selected_for(task_id)
        return selected.model.model_id if selected else None

    def to_dict(self) -> dict:
        return {
            "ok": not self.blocked_tasks,
            "blockedTasks": list(self.blocked_tasks),
            "situations": {
                task_id: decision.to_dict()
                for task_id, decision in self.situations.items()
            },
            "decisions": [decision.to_dict() for decision in self.decisions],
            "summaries": [summary.to_dict() for summary in self.summaries],
            "aggregate": self.aggregate.to_dict(),
        }


def default_decision_scenarios() -> tuple[TaskProfile, ...]:
    """Representative first-pass situations for local, CLI, and API routing."""

    return (
        TaskProfile(
            task_id="decision.private-chat",
            description="Private conversational response that must stay on a local model.",
            required_capabilities={"conversation": 0.8, "instruction_following": 0.75},
            privacy_requirement="local_only",
        ),
        TaskProfile(
            task_id="decision.tool-heavy-coding",
            description="Tool-capable coding and reasoning task.",
            required_capabilities={"coding": 0.9, "reasoning": 0.85, "instruction_following": 0.85},
            require_tools=True,
        ),
        TaskProfile(
            task_id="decision.long-context-memory",
            description="Long-context memory retrieval and summarization task.",
            required_capabilities={"retrieval": 0.85, "summarization": 0.85},
            min_context_tokens=64000,
            require_json=True,
        ),
        TaskProfile(
            task_id="decision.low-latency-local",
            description="Low-latency local response lane.",
            required_capabilities={"conversation": 0.75, "instruction_following": 0.75},
            privacy_requirement="prefer_local",
        ),
        TaskProfile(
            task_id="decision.structured-json",
            description="Structured response task requiring JSON output.",
            required_capabilities={"instruction_following": 0.8},
            require_json=True,
        ),
        TaskProfile(
            task_id="decision.cost-sensitive-remote",
            description="Remote-allowed task with tight cost controls.",
            required_capabilities={"summarization": 0.8, "instruction_following": 0.8},
            max_input_cost_per_1k=0.01,
            max_output_cost_per_1k=0.02,
        ),
    )


def load_decision_suite(path: str | Path) -> DecisionSuite:
    suite_path = Path(path)
    with suite_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return parse_decision_suite(payload, source=str(suite_path))


def parse_decision_suite(payload: Mapping[str, Any], *, source: str = "<memory>") -> DecisionSuite:
    if not isinstance(payload, Mapping):
        raise ModelDecisionError(f"{source}: decision suite must be a JSON object")
    schema_version = payload.get("schemaVersion", payload.get("schema_version", 1))
    if schema_version != 1:
        raise ModelDecisionError(f"{source}: unsupported decision suite schemaVersion {schema_version!r}")

    suite_id = str(payload.get("suiteId", payload.get("suite_id", "")) or "").strip()
    if not suite_id:
        raise ModelDecisionError(f"{source}: suiteId is required")

    situations_payload = payload.get("situations")
    if not isinstance(situations_payload, list) or not situations_payload:
        raise ModelDecisionError(f"{source}: situations must be a non-empty array")

    situations = tuple(
        parse_task_profile({"schemaVersion": 1, **raw}, source=f"{source}:situations[{index}]")
        for index, raw in enumerate(situations_payload)
    )
    _validate_unique_tasks(situations, source=source)
    return DecisionSuite(
        suite_id=suite_id,
        situations=situations,
        description=str(payload.get("description", "") or ""),
    )


def evaluate_model_decisions(
    models: Iterable[ModelEndpoint],
    tasks: Iterable[TaskProfile] | None = None,
) -> ModelDecisionReport:
    """Evaluate registered endpoints across multiple task/situation profiles.

    The evaluator deliberately reuses the single-task router score contract. It
    does not execute providers; it returns selection evidence for later runtime,
    CLI, API, or CHARACTER/MOA consumers.
    """

    model_list = list(models)
    task_list = list(default_decision_scenarios() if tasks is None else tasks)
    _validate_inputs(model_list, task_list)

    situation_decisions: dict[str, SituationDecision] = {}
    for task in task_list:
        ranked = tuple(rank_models(model_list, task))
        selected = next((score for score in ranked if score.eligible), None)
        blockers = {
            score.model.model_id: score.blockers
            for score in ranked
            if score.blockers
        }
        situation_decisions[task.task_id] = SituationDecision(
            task=task,
            ranked=ranked,
            selected=selected,
            blockers=blockers,
            rationale=_situation_rationale(task, ranked, selected),
        )

    return ModelDecisionReport(
        situations=situation_decisions,
        aggregate=_build_aggregate(model_list, situation_decisions),
    )


def _validate_inputs(models: list[ModelEndpoint], tasks: list[TaskProfile]) -> None:
    if not models:
        raise ModelDecisionError("At least one model endpoint is required")
    if not tasks:
        raise ModelDecisionError("At least one task profile is required")

    model_ids = [model.model_id for model in models]
    duplicate_model_ids = sorted({model_id for model_id in model_ids if model_ids.count(model_id) > 1})
    if duplicate_model_ids:
        raise ModelDecisionError(f"Duplicate model ids: {', '.join(duplicate_model_ids)}")

    _validate_unique_tasks(tasks)


def _validate_unique_tasks(tasks: Iterable[TaskProfile], *, source: str = "<memory>") -> None:
    task_ids = [task.task_id for task in tasks]
    duplicate_task_ids = sorted({task_id for task_id in task_ids if task_ids.count(task_id) > 1})
    if duplicate_task_ids:
        raise ModelDecisionError(f"{source}: duplicate task ids: {', '.join(duplicate_task_ids)}")


def _situation_rationale(
    task: TaskProfile,
    ranked: tuple[ModelScore, ...],
    selected: ModelScore | None,
) -> tuple[str, ...]:
    eligible_count = sum(1 for score in ranked if score.eligible)
    rationale = [
        f"ranked {len(ranked)} models; {eligible_count} eligible for {task.task_id}",
    ]
    if selected is None:
        rationale.append(f"no eligible model satisfied all blockers for {task.task_id}")
    else:
        rationale.append(
            f"selected {selected.model.model_id} from provider {selected.model.provider} "
            f"as highest ranked eligible model"
        )
        if selected.reasons:
            rationale.append("; ".join(selected.reasons))
    return tuple(rationale)


def _build_aggregate(
    models: list[ModelEndpoint],
    situations: Mapping[str, SituationDecision],
) -> ModelDecisionAggregate:
    blockers_by_task = {
        task_id: decision.blockers
        for task_id, decision in situations.items()
        if decision.blockers
    }
    selected_model_ids = _unique_sorted(
        decision.selected.model.model_id
        for decision in situations.values()
        if decision.selected is not None
    )
    selected_providers = _unique_sorted(
        decision.selected.model.provider
        for decision in situations.values()
        if decision.selected is not None
    )

    model_coverage = {
        model.model_id: _model_coverage(model, situations)
        for model in sorted(models, key=lambda item: item.model_id)
    }
    provider_coverage = _provider_coverage(models, situations)

    uncovered_situations = tuple(
        task_id for task_id, decision in situations.items() if decision.selected is None
    )
    rationale = [
        f"evaluated {len(models)} models across {len(situations)} situations",
        f"selected {len(selected_model_ids)} distinct models across {len(selected_providers)} providers",
    ]
    if uncovered_situations:
        rationale.append(f"uncovered situations: {', '.join(uncovered_situations)}")
    else:
        rationale.append("all situations have an eligible selected model")

    return ModelDecisionAggregate(
        model_count=len(models),
        situation_count=len(situations),
        selected_model_ids=selected_model_ids,
        selected_providers=selected_providers,
        model_coverage=model_coverage,
        provider_coverage=provider_coverage,
        blockers=blockers_by_task,
        rationale=tuple(rationale),
    )


def _model_coverage(
    model: ModelEndpoint,
    situations: Mapping[str, SituationDecision],
) -> ModelCoverage:
    eligible_situations: list[str] = []
    selected_situations: list[str] = []
    blocked_situations: dict[str, tuple[str, ...]] = {}
    eligible_scores: list[float] = []

    for task_id, decision in situations.items():
        score = _score_for_model(decision, model.model_id)
        if score is None:
            continue
        if score.eligible:
            eligible_situations.append(task_id)
            eligible_scores.append(score.score)
        elif score.blockers:
            blocked_situations[task_id] = score.blockers
        if decision.selected and decision.selected.model.model_id == model.model_id:
            selected_situations.append(task_id)

    average_eligible_score = None
    if eligible_scores:
        average_eligible_score = round(sum(eligible_scores) / len(eligible_scores), 4)

    rationale = [
        f"eligible for {len(eligible_situations)} of {len(situations)} situations",
        f"selected for {len(selected_situations)} situations",
    ]
    if blocked_situations:
        rationale.append(f"blocked in {len(blocked_situations)} situations")

    return ModelCoverage(
        model=model,
        eligible_situations=tuple(eligible_situations),
        selected_situations=tuple(selected_situations),
        blocked_situations=blocked_situations,
        average_eligible_score=average_eligible_score,
        rationale=tuple(rationale),
    )


def _provider_coverage(
    models: list[ModelEndpoint],
    situations: Mapping[str, SituationDecision],
) -> dict[str, ProviderCoverage]:
    providers = sorted({model.provider for model in models})
    coverage: dict[str, ProviderCoverage] = {}
    for provider in providers:
        provider_models = sorted(
            [model for model in models if model.provider == provider],
            key=lambda item: item.model_id,
        )
        model_ids = tuple(model.model_id for model in provider_models)
        eligible_situations = _unique_in_situation_order(
            task_id
            for task_id, decision in situations.items()
            for score in decision.ranked
            if score.model.provider == provider and score.eligible
        )
        selected_situations = _unique_in_situation_order(
            task_id
            for task_id, decision in situations.items()
            if decision.selected is not None and decision.selected.model.provider == provider
        )
        blocked_situations = _provider_blockers(provider, situations)
        rationale = [
            f"{len(model_ids)} registered models",
            f"eligible for {len(eligible_situations)} situations",
            f"selected for {len(selected_situations)} situations",
        ]
        if blocked_situations:
            rationale.append(f"provider has blockers in {len(blocked_situations)} situations")

        coverage[provider] = ProviderCoverage(
            provider=provider,
            model_ids=model_ids,
            eligible_situations=eligible_situations,
            selected_situations=selected_situations,
            blocked_situations=blocked_situations,
            rationale=tuple(rationale),
        )
    return coverage


def _provider_blockers(
    provider: str,
    situations: Mapping[str, SituationDecision],
) -> dict[str, tuple[str, ...]]:
    blocked: dict[str, tuple[str, ...]] = {}
    for task_id, decision in situations.items():
        provider_blockers = [
            f"{score.model.model_id}: {blocker}"
            for score in decision.ranked
            if score.model.provider == provider
            for blocker in score.blockers
        ]
        if provider_blockers:
            blocked[task_id] = tuple(provider_blockers)
    return blocked


def _score_for_model(decision: SituationDecision, model_id: str) -> ModelScore | None:
    return next((score for score in decision.ranked if score.model.model_id == model_id), None)


def _unique_sorted(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(set(values)))


def _unique_in_situation_order(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            ordered.append(value)
            seen.add(value)
    return tuple(ordered)


def _score_to_dict(score: ModelScore) -> dict:
    return {
        "modelId": score.model.model_id,
        "provider": score.model.provider,
        "score": score.score,
        "eligible": score.eligible,
        "reasons": list(score.reasons),
        "blockers": list(score.blockers),
    }
