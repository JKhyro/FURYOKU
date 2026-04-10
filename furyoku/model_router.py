from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping


ProviderKind = str
PrivacyRequirement = str


class RouterError(ValueError):
    """Raised when no registered model can satisfy a task profile."""


@dataclass(frozen=True)
class RoutingScorePolicy:
    """Configurable soft scoring weights for eligible model routing."""

    capability_weight: float = 100.0
    context_bonus_weight: float = 8.0
    context_reference_tokens: int = 128000
    speed_bonus_weight: float = 8.0
    speed_reference_ms: int = 30000
    local_preference_bonus: float = 12.0
    remote_privacy_penalty: float = 8.0
    preferred_provider_bonus: float = 8.0
    cost_penalty_multiplier: float = 2.0
    max_cost_penalty: float = 15.0

    def __post_init__(self) -> None:
        _validate_non_negative(self.capability_weight, field_name="capabilityWeight")
        _validate_non_negative(self.context_bonus_weight, field_name="contextBonusWeight")
        _validate_positive_int(self.context_reference_tokens, field_name="contextReferenceTokens")
        _validate_non_negative(self.speed_bonus_weight, field_name="speedBonusWeight")
        _validate_positive_int(self.speed_reference_ms, field_name="speedReferenceMs")
        _validate_non_negative(self.local_preference_bonus, field_name="localPreferenceBonus")
        _validate_non_negative(self.remote_privacy_penalty, field_name="remotePrivacyPenalty")
        _validate_non_negative(self.preferred_provider_bonus, field_name="preferredProviderBonus")
        _validate_non_negative(self.cost_penalty_multiplier, field_name="costPenaltyMultiplier")
        _validate_non_negative(self.max_cost_penalty, field_name="maxCostPenalty")

    def to_dict(self) -> dict:
        return {
            "schemaVersion": 1,
            "capabilityWeight": self.capability_weight,
            "contextBonusWeight": self.context_bonus_weight,
            "contextReferenceTokens": self.context_reference_tokens,
            "speedBonusWeight": self.speed_bonus_weight,
            "speedReferenceMs": self.speed_reference_ms,
            "localPreferenceBonus": self.local_preference_bonus,
            "remotePrivacyPenalty": self.remote_privacy_penalty,
            "preferredProviderBonus": self.preferred_provider_bonus,
            "costPenaltyMultiplier": self.cost_penalty_multiplier,
            "maxCostPenalty": self.max_cost_penalty,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any], *, source: str = "<memory>") -> "RoutingScorePolicy":
        if not isinstance(payload, Mapping):
            raise RouterError(f"{source}: routing score policy must be an object")
        schema_version = payload.get("schemaVersion", payload.get("schema_version", 1))
        if schema_version != 1:
            raise RouterError(f"{source}: unsupported routing score policy schemaVersion {schema_version!r}")
        defaults = cls()
        return cls(
            capability_weight=_policy_non_negative_float(
                payload,
                "capabilityWeight",
                "capability_weight",
                default=defaults.capability_weight,
                source=source,
            ),
            context_bonus_weight=_policy_non_negative_float(
                payload,
                "contextBonusWeight",
                "context_bonus_weight",
                default=defaults.context_bonus_weight,
                source=source,
            ),
            context_reference_tokens=_policy_positive_int(
                payload,
                "contextReferenceTokens",
                "context_reference_tokens",
                default=defaults.context_reference_tokens,
                source=source,
            ),
            speed_bonus_weight=_policy_non_negative_float(
                payload,
                "speedBonusWeight",
                "speed_bonus_weight",
                default=defaults.speed_bonus_weight,
                source=source,
            ),
            speed_reference_ms=_policy_positive_int(
                payload,
                "speedReferenceMs",
                "speed_reference_ms",
                default=defaults.speed_reference_ms,
                source=source,
            ),
            local_preference_bonus=_policy_non_negative_float(
                payload,
                "localPreferenceBonus",
                "local_preference_bonus",
                default=defaults.local_preference_bonus,
                source=source,
            ),
            remote_privacy_penalty=_policy_non_negative_float(
                payload,
                "remotePrivacyPenalty",
                "remote_privacy_penalty",
                default=defaults.remote_privacy_penalty,
                source=source,
            ),
            preferred_provider_bonus=_policy_non_negative_float(
                payload,
                "preferredProviderBonus",
                "preferred_provider_bonus",
                default=defaults.preferred_provider_bonus,
                source=source,
            ),
            cost_penalty_multiplier=_policy_non_negative_float(
                payload,
                "costPenaltyMultiplier",
                "cost_penalty_multiplier",
                default=defaults.cost_penalty_multiplier,
                source=source,
            ),
            max_cost_penalty=_policy_non_negative_float(
                payload,
                "maxCostPenalty",
                "max_cost_penalty",
                default=defaults.max_cost_penalty,
                source=source,
            ),
        )


RoutingScorePolicyInput = RoutingScorePolicy | Mapping[str, Any]


@dataclass(frozen=True)
class RoutingScorePolicyMetadata:
    """Stable report metadata for the routing score policy that shaped selection."""

    source: str
    policy: RoutingScorePolicy
    customized_fields: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "schemaVersion": 1,
            "source": self.source,
            "customizedFields": list(self.customized_fields),
            "policy": self.policy.to_dict(),
        }


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
    metadata: Mapping[str, Any] = field(default_factory=dict)

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
    max_latency_ms: int | None = None
    max_input_cost_per_1k: float | None = None
    max_output_cost_per_1k: float | None = None
    max_total_cost_per_1k: float | None = None
    require_tools: bool = False
    require_json: bool = False
    preferred_providers: tuple[ProviderKind, ...] = ()

    def to_dict(self) -> dict:
        return {
            "taskId": self.task_id,
            "description": self.description,
            "requiredCapabilities": dict(self.required_capabilities),
            "minContextTokens": self.min_context_tokens,
            "privacyRequirement": self.privacy_requirement,
            "maxLatencyMs": self.max_latency_ms,
            "maxInputCostPer1k": self.max_input_cost_per_1k,
            "maxOutputCostPer1k": self.max_output_cost_per_1k,
            "maxTotalCostPer1k": self.max_total_cost_per_1k,
            "requireTools": self.require_tools,
            "requireJson": self.require_json,
            "preferredProviders": list(self.preferred_providers),
        }


@dataclass(frozen=True)
class ModelScore:
    model: ModelEndpoint
    task: TaskProfile
    score: float
    eligible: bool
    reasons: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()


@dataclass(frozen=True)
class CharacterRoleSpec:
    """One role inside a flexible CHARACTER composition."""

    role_id: str
    task: TaskProfile
    primary: bool = False
    max_subagents: int = 0


@dataclass(frozen=True)
class CharacterCompositionSelection:
    """Flexible role selection for a CHARACTER/MOA-style agent array."""

    roles: Mapping[str, ModelScore]
    role_specs: Mapping[str, CharacterRoleSpec]
    primary_role: str | None = None

    def as_dict(self) -> dict[str, ModelScore]:
        return dict(self.roles)

    def max_subagents_for(self, role_id: str) -> int:
        spec = self.role_specs.get(role_id)
        if spec is None:
            raise RouterError(f"Unknown CHARACTER role '{role_id}'")
        return spec.max_subagents


@dataclass(frozen=True)
class CharacterPanelSelection:
    """Backward-compatible three-role selection for the earlier example panel."""

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


def score_model(
    model: ModelEndpoint,
    task: TaskProfile,
    *,
    policy: RoutingScorePolicyInput | None = None,
) -> ModelScore:
    resolved_policy = resolve_routing_score_policy(policy)
    blockers: list[str] = []
    reasons: list[str] = []
    total_cost_per_1k = model.input_cost_per_1k + model.output_cost_per_1k

    if not model.available:
        blockers.append("model is not currently available")
    if task.min_context_tokens and model.context_window_tokens < task.min_context_tokens:
        blockers.append(
            f"context window {model.context_window_tokens} is below required {task.min_context_tokens}"
        )
    if task.privacy_requirement == "local_only" and not model.is_local:
        blockers.append("task requires a local model")
    if task.max_latency_ms is not None:
        if model.average_latency_ms > task.max_latency_ms:
            blockers.append(
                f"average latency {model.average_latency_ms}ms exceeds task limit {task.max_latency_ms}ms"
            )
        else:
            reasons.append(
                f"average latency {model.average_latency_ms}ms within task limit {task.max_latency_ms}ms"
            )
    if task.max_input_cost_per_1k is not None and model.input_cost_per_1k > task.max_input_cost_per_1k:
        blockers.append("input cost exceeds task limit")
    if task.max_output_cost_per_1k is not None and model.output_cost_per_1k > task.max_output_cost_per_1k:
        blockers.append("output cost exceeds task limit")
    if task.max_total_cost_per_1k is not None:
        if total_cost_per_1k > task.max_total_cost_per_1k:
            blockers.append(
                f"total cost per 1k {total_cost_per_1k:.4f} exceeds task limit {task.max_total_cost_per_1k:.4f}"
            )
        else:
            reasons.append(
                f"total cost per 1k {total_cost_per_1k:.4f} within task limit {task.max_total_cost_per_1k:.4f}"
            )
    if task.require_tools and not model.supports_tools:
        blockers.append("task requires tool support")
    if task.require_json and not model.supports_json:
        blockers.append("task requires JSON output support")

    capability_score = _weighted_capability_score(model, task)
    score = capability_score * resolved_policy.capability_weight
    reasons.append(f"capability fit {capability_score:.3f}")

    if model.context_window_tokens >= task.min_context_tokens:
        context_bonus = (
            min(model.context_window_tokens / resolved_policy.context_reference_tokens, 1.0)
            * resolved_policy.context_bonus_weight
        )
        score += context_bonus
        reasons.append(f"context bonus {context_bonus:.2f}")

    speed_bonus = (
        max(0.0, min(1.0, 1.0 - (model.average_latency_ms / resolved_policy.speed_reference_ms)))
        * resolved_policy.speed_bonus_weight
    )
    score += speed_bonus
    reasons.append(f"speed bonus {speed_bonus:.2f}")

    if task.privacy_requirement == "prefer_local" and model.is_local:
        score += resolved_policy.local_preference_bonus
        reasons.append(f"local privacy preference bonus {resolved_policy.local_preference_bonus:.2f}")
    elif task.privacy_requirement == "prefer_local":
        score -= resolved_policy.remote_privacy_penalty
        reasons.append(f"remote privacy penalty {resolved_policy.remote_privacy_penalty:.2f}")

    if task.preferred_providers and model.provider in task.preferred_providers:
        score += resolved_policy.preferred_provider_bonus
        reasons.append(f"preferred provider bonus for {model.provider}")

    cost_penalty = min(total_cost_per_1k * resolved_policy.cost_penalty_multiplier, resolved_policy.max_cost_penalty)
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


def rank_models(
    models: Iterable[ModelEndpoint],
    task: TaskProfile,
    *,
    policy: RoutingScorePolicyInput | None = None,
) -> list[ModelScore]:
    ranked = [score_model(model, task, policy=policy) for model in models]
    return sorted(ranked, key=lambda item: (item.eligible, item.score, item.model.model_id), reverse=True)


def select_model(
    models: Iterable[ModelEndpoint],
    task: TaskProfile,
    *,
    policy: RoutingScorePolicyInput | None = None,
) -> ModelScore:
    ranked = rank_models(models, task, policy=policy)
    for score in ranked:
        if score.eligible:
            return score
    blocker_summary = "; ".join(
        f"{score.model.model_id}: {', '.join(score.blockers)}" for score in ranked
    )
    raise RouterError(f"No eligible model for task '{task.task_id}'. {blocker_summary}")


def select_character_composition(
    models: Iterable[ModelEndpoint],
    roles: Iterable[CharacterRoleSpec] | Mapping[str, TaskProfile],
    *,
    allow_reuse: bool = True,
    policy: RoutingScorePolicyInput | None = None,
) -> CharacterCompositionSelection:
    role_specs = _normalize_character_role_specs(roles)
    remaining_models = list(models)
    selections: dict[str, ModelScore] = {}

    for spec in _selection_order(role_specs):
        selected = select_model(remaining_models, spec.task, policy=policy)
        selections[spec.role_id] = selected
        if not allow_reuse:
            remaining_models = [
                model for model in remaining_models if model.model_id != selected.model.model_id
            ]

    primary_roles = [spec.role_id for spec in role_specs if spec.primary]
    primary_role = primary_roles[0] if primary_roles else role_specs[0].role_id
    return CharacterCompositionSelection(
        roles=selections,
        role_specs={spec.role_id: spec for spec in role_specs},
        primary_role=primary_role,
    )


def select_character_panel(
    models: Iterable[ModelEndpoint],
    role_tasks: Mapping[str, TaskProfile] | None = None,
    *,
    allow_reuse: bool = True,
    policy: RoutingScorePolicyInput | None = None,
) -> CharacterPanelSelection:
    tasks = dict(role_tasks or default_character_role_tasks())
    missing_roles = {"face", "memory", "reasoning"} - set(tasks)
    if missing_roles:
        raise RouterError(f"Missing CHARACTER role task profiles: {', '.join(sorted(missing_roles))}")

    composition = select_character_composition(
        models,
        [
            CharacterRoleSpec("face", tasks["face"], primary=True),
            CharacterRoleSpec("memory", tasks["memory"], max_subagents=12),
            CharacterRoleSpec("reasoning", tasks["reasoning"], max_subagents=12),
        ],
        allow_reuse=allow_reuse,
        policy=policy,
    )

    return CharacterPanelSelection(
        face=composition.roles["face"],
        memory=composition.roles["memory"],
        reasoning=composition.roles["reasoning"],
    )


def _normalize_character_role_specs(
    roles: Iterable[CharacterRoleSpec] | Mapping[str, TaskProfile],
) -> list[CharacterRoleSpec]:
    if isinstance(roles, Mapping):
        role_specs = [
            CharacterRoleSpec(role_id=str(role_id), task=task, primary=index == 0)
            for index, (role_id, task) in enumerate(roles.items())
        ]
    else:
        role_specs = list(roles)

    if not role_specs:
        raise RouterError("CHARACTER composition requires at least one role")

    seen: set[str] = set()
    primary_count = 0
    for spec in role_specs:
        if not spec.role_id.strip():
            raise RouterError("CHARACTER role ids must be non-empty")
        if spec.role_id in seen:
            raise RouterError(f"Duplicate CHARACTER role id '{spec.role_id}'")
        if spec.max_subagents < 0:
            raise RouterError(f"CHARACTER role '{spec.role_id}' has negative max_subagents")
        if spec.primary:
            primary_count += 1
        seen.add(spec.role_id)

    if primary_count > 1:
        raise RouterError("CHARACTER composition can only mark one primary role")
    return role_specs


def _selection_order(role_specs: list[CharacterRoleSpec]) -> list[CharacterRoleSpec]:
    primary_specs = [spec for spec in role_specs if spec.primary]
    secondary_specs = [spec for spec in role_specs if not spec.primary]
    return primary_specs + secondary_specs if primary_specs else role_specs


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


def load_routing_score_policy(path: str | Path) -> RoutingScorePolicy:
    policy_path = Path(path)
    with policy_path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    return parse_routing_score_policy(payload, source=str(policy_path))


def parse_routing_score_policy(payload: Mapping[str, Any], *, source: str = "<memory>") -> RoutingScorePolicy:
    return RoutingScorePolicy.from_dict(payload, source=source)


def resolve_routing_score_policy(policy: RoutingScorePolicyInput | None = None) -> RoutingScorePolicy:
    if policy is None:
        return DEFAULT_ROUTING_SCORE_POLICY
    if isinstance(policy, RoutingScorePolicy):
        return policy
    if isinstance(policy, Mapping):
        return parse_routing_score_policy(policy, source="<routing-policy>")
    raise RouterError(f"Unsupported routing score policy type: {type(policy).__name__}")


def build_routing_score_policy_metadata(
    policy: RoutingScorePolicyInput | None = None,
    *,
    source: str | None = None,
) -> RoutingScorePolicyMetadata:
    resolved_policy = resolve_routing_score_policy(policy)
    default_payload = DEFAULT_ROUTING_SCORE_POLICY.to_dict()
    policy_payload = resolved_policy.to_dict()
    customized_fields = tuple(
        key
        for key in sorted(policy_payload)
        if key != "schemaVersion" and policy_payload[key] != default_payload.get(key)
    )
    return RoutingScorePolicyMetadata(
        source=source or ("default" if not customized_fields else "custom"),
        policy=resolved_policy,
        customized_fields=customized_fields,
    )


def _policy_non_negative_float(
    payload: Mapping[str, Any],
    camel_key: str,
    snake_key: str,
    *,
    default: float,
    source: str,
) -> float:
    raw_value = payload.get(camel_key, payload.get(snake_key, default))
    try:
        value = float(raw_value)
    except (TypeError, ValueError) as exc:
        raise RouterError(f"{source}: {camel_key} must be numeric") from exc
    _validate_non_negative(value, field_name=camel_key, source=source)
    return value


def _policy_positive_int(
    payload: Mapping[str, Any],
    camel_key: str,
    snake_key: str,
    *,
    default: int,
    source: str,
) -> int:
    raw_value = payload.get(camel_key, payload.get(snake_key, default))
    try:
        value = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise RouterError(f"{source}: {camel_key} must be an integer") from exc
    _validate_positive_int(value, field_name=camel_key, source=source)
    return value


def _validate_non_negative(value: float, *, field_name: str, source: str = "<policy>") -> None:
    if not math.isfinite(value):
        raise RouterError(f"{source}: {field_name} must be finite")
    if value < 0.0:
        raise RouterError(f"{source}: {field_name} must be 0 or greater")


def _validate_positive_int(value: int, *, field_name: str, source: str = "<policy>") -> None:
    if value <= 0:
        raise RouterError(f"{source}: {field_name} must be greater than 0")


DEFAULT_ROUTING_SCORE_POLICY = RoutingScorePolicy()
