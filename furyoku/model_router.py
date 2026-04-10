from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping


ProviderKind = str
PrivacyRequirement = str


class RouterError(ValueError):
    """Raised when no registered model can satisfy a task profile."""


@dataclass(frozen=True)
class ModelEndpoint:
    """A callable LLM endpoint, whether local, CLI-backed, or remote API-backed."""

    model_id: str
    provider: ProviderKind
    capabilities: Mapping[str, float]
    context_window_tokens: int
    average_latency_ms: int
    input_cost_per_1k: float = 0.0
    output_cost_per_1k: float = 0.0
    available: bool = True
    privacy_level: str = "remote"
    invocation: tuple[str, ...] = ()
    supports_tools: bool = False
    supports_json: bool = False
    tags: tuple[str, ...] = ()

    def capability(self, name: str) -> float:
        return max(0.0, min(1.0, float(self.capabilities.get(name, 0.0))))

    @property
    def is_local(self) -> bool:
        return self.provider == "local" or self.privacy_level == "local"


@dataclass(frozen=True)
class TaskProfile:
    """Describes what a task needs before FURYOKU chooses a model."""

    task_id: str
    required_capabilities: Mapping[str, float]
    description: str = ""
    min_context_tokens: int = 0
    privacy_requirement: PrivacyRequirement = "allow_remote"
    max_input_cost_per_1k: float | None = None
    max_output_cost_per_1k: float | None = None
    require_tools: bool = False
    require_json: bool = False
    preferred_providers: tuple[ProviderKind, ...] = ()


@dataclass(frozen=True)
class ModelScore:
    model: ModelEndpoint
    task: TaskProfile
    score: float
    eligible: bool
    reasons: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()


@dataclass(frozen=True)
class CharacterPanelSelection:
    """Three-role selection for a CHARACTER/MOA-style agent array."""

    face: ModelScore
    memory: ModelScore
    reasoning: ModelScore

    def as_dict(self) -> dict[str, ModelScore]:
        return {
            "face": self.face,
            "memory": self.memory,
            "reasoning": self.reasoning,
        }


def default_character_role_tasks() -> dict[str, TaskProfile]:
    return {
        "face": TaskProfile(
            task_id="character.face",
            description="Interactive face of the CHARACTER; needs quick conversational quality.",
            required_capabilities={
                "conversation": 0.85,
                "instruction_following": 0.8,
                "safety": 0.75,
                "speed": 0.7,
            },
            privacy_requirement="allow_remote",
        ),
        "memory": TaskProfile(
            task_id="character.memory",
            description="Memory retrieval/storage role; needs long context and structured output.",
            required_capabilities={
                "retrieval": 0.85,
                "summarization": 0.8,
                "instruction_following": 0.75,
            },
            min_context_tokens=16000,
            require_json=True,
            privacy_requirement="prefer_local",
        ),
        "reasoning": TaskProfile(
            task_id="character.reasoning",
            description="Rationality, logic, coding, and hard problem-solving role.",
            required_capabilities={
                "reasoning": 0.9,
                "coding": 0.8,
                "instruction_following": 0.8,
            },
            privacy_requirement="allow_remote",
        ),
    }


def score_model(model: ModelEndpoint, task: TaskProfile) -> ModelScore:
    blockers: list[str] = []
    reasons: list[str] = []

    if not model.available:
        blockers.append("model is not currently available")
    if task.min_context_tokens and model.context_window_tokens < task.min_context_tokens:
        blockers.append(
            f"context window {model.context_window_tokens} is below required {task.min_context_tokens}"
        )
    if task.privacy_requirement == "local_only" and not model.is_local:
        blockers.append("task requires a local model")
    if task.max_input_cost_per_1k is not None and model.input_cost_per_1k > task.max_input_cost_per_1k:
        blockers.append("input cost exceeds task limit")
    if task.max_output_cost_per_1k is not None and model.output_cost_per_1k > task.max_output_cost_per_1k:
        blockers.append("output cost exceeds task limit")
    if task.require_tools and not model.supports_tools:
        blockers.append("task requires tool support")
    if task.require_json and not model.supports_json:
        blockers.append("task requires JSON output support")

    capability_score = _weighted_capability_score(model, task)
    score = capability_score * 100.0
    reasons.append(f"capability fit {capability_score:.3f}")

    if model.context_window_tokens >= task.min_context_tokens:
        context_bonus = min(model.context_window_tokens / 128000.0, 1.0) * 8.0
        score += context_bonus
        reasons.append(f"context bonus {context_bonus:.2f}")

    speed_bonus = max(0.0, min(1.0, 1.0 - (model.average_latency_ms / 30000.0))) * 8.0
    score += speed_bonus
    reasons.append(f"speed bonus {speed_bonus:.2f}")

    if task.privacy_requirement == "prefer_local" and model.is_local:
        score += 12.0
        reasons.append("local privacy preference bonus 12.00")
    elif task.privacy_requirement == "prefer_local":
        score -= 8.0
        reasons.append("remote privacy penalty 8.00")

    if task.preferred_providers and model.provider in task.preferred_providers:
        score += 8.0
        reasons.append(f"preferred provider bonus for {model.provider}")

    cost_penalty = min((model.input_cost_per_1k + model.output_cost_per_1k) * 2.0, 15.0)
    if cost_penalty:
        score -= cost_penalty
        reasons.append(f"cost penalty {cost_penalty:.2f}")

    for capability_name, required_score in task.required_capabilities.items():
        actual_score = model.capability(capability_name)
        if actual_score < required_score:
            blockers.append(
                f"{capability_name} capability {actual_score:.2f} is below required {required_score:.2f}"
            )

    eligible = not blockers
    if not eligible:
        score = min(score, 0.0)

    return ModelScore(
        model=model,
        task=task,
        score=round(score, 4),
        eligible=eligible,
        reasons=tuple(reasons),
        blockers=tuple(blockers),
    )


def rank_models(models: Iterable[ModelEndpoint], task: TaskProfile) -> list[ModelScore]:
    ranked = [score_model(model, task) for model in models]
    return sorted(ranked, key=lambda item: (item.eligible, item.score, item.model.model_id), reverse=True)


def select_model(models: Iterable[ModelEndpoint], task: TaskProfile) -> ModelScore:
    ranked = rank_models(models, task)
    for score in ranked:
        if score.eligible:
            return score
    blocker_summary = "; ".join(
        f"{score.model.model_id}: {', '.join(score.blockers)}" for score in ranked
    )
    raise RouterError(f"No eligible model for task '{task.task_id}'. {blocker_summary}")


def select_character_panel(
    models: Iterable[ModelEndpoint],
    role_tasks: Mapping[str, TaskProfile] | None = None,
    *,
    allow_reuse: bool = True,
) -> CharacterPanelSelection:
    tasks = dict(role_tasks or default_character_role_tasks())
    missing_roles = {"face", "memory", "reasoning"} - set(tasks)
    if missing_roles:
        raise RouterError(f"Missing CHARACTER role task profiles: {', '.join(sorted(missing_roles))}")

    remaining_models = list(models)
    selections: dict[str, ModelScore] = {}
    for role in ("face", "memory", "reasoning"):
        selected = select_model(remaining_models, tasks[role])
        selections[role] = selected
        if not allow_reuse:
            remaining_models = [
                model for model in remaining_models if model.model_id != selected.model.model_id
            ]

    return CharacterPanelSelection(
        face=selections["face"],
        memory=selections["memory"],
        reasoning=selections["reasoning"],
    )


def _weighted_capability_score(model: ModelEndpoint, task: TaskProfile) -> float:
    if not task.required_capabilities:
        return 0.0

    total_weight = 0.0
    weighted_score = 0.0
    for capability_name, required_score in task.required_capabilities.items():
        weight = max(float(required_score), 0.01)
        total_weight += weight
        weighted_score += min(model.capability(capability_name) / weight, 1.0) * weight
    return weighted_score / total_weight
