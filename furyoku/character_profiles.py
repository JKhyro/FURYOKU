from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from .model_router import (
    CharacterCompositionSelection,
    CharacterRoleSpec,
    ModelEndpoint,
    ModelScore,
    RouterError,
    select_character_composition,
)
from .model_decisions import ReadinessEvidenceInput, evaluate_model_decisions
from .task_profiles import parse_task_profile


class CharacterProfileError(ValueError):
    """Raised when a CHARACTER composition profile is malformed."""


@dataclass(frozen=True)
class CharacterProfile:
    character_id: str
    character_class: str
    rank: str
    role_specs: tuple[CharacterRoleSpec, ...]
    description: str = ""

    @property
    def primary_role_id(self) -> str:
        primary_roles = [role.role_id for role in self.role_specs if role.primary]
        return primary_roles[0] if primary_roles else self.role_specs[0].role_id


@dataclass(frozen=True)
class CharacterProfileSelection:
    """Registry-backed model selections for one flexible CHARACTER profile."""

    profile: CharacterProfile
    composition: CharacterCompositionSelection

    @property
    def character_id(self) -> str:
        return self.profile.character_id

    @property
    def primary_role(self) -> str:
        return self.composition.primary_role or self.profile.primary_role_id

    @property
    def roles(self) -> Mapping[str, ModelScore]:
        return self.composition.roles

    def max_subagents_for(self, role_id: str) -> int:
        return self.composition.max_subagents_for(role_id)


@dataclass(frozen=True)
class CharacterRoleAssignment:
    """One selected role inside a CHARACTER orchestration envelope."""

    role_spec: CharacterRoleSpec
    selection: ModelScore

    @property
    def role_id(self) -> str:
        return self.role_spec.role_id

    @property
    def primary(self) -> bool:
        return self.role_spec.primary

    @property
    def max_subagents(self) -> int:
        return self.role_spec.max_subagents

    def to_dict(self) -> dict:
        return {
            "roleId": self.role_id,
            "primary": self.primary,
            "maxSubagents": self.max_subagents,
            "taskId": self.role_spec.task.task_id,
            "selectedModelId": self.selection.model.model_id,
            "selectedProvider": self.selection.model.provider,
            "selection": _score_to_dict(self.selection),
        }


@dataclass(frozen=True)
class CharacterOrchestrationEnvelope:
    """Serializable assignment plan for a flexible CHARACTER/MOA role array."""

    selection: CharacterProfileSelection
    role_assignments: Mapping[str, CharacterRoleAssignment]

    @property
    def character_id(self) -> str:
        return self.selection.character_id

    @property
    def primary_role(self) -> str:
        return self.selection.primary_role

    @property
    def role_count(self) -> int:
        return len(self.role_assignments)

    @property
    def total_max_subagents(self) -> int:
        return sum(assignment.max_subagents for assignment in self.role_assignments.values())

    def assignment_for(self, role_id: str) -> CharacterRoleAssignment:
        try:
            return self.role_assignments[role_id]
        except KeyError as exc:
            raise RouterError(f"Unknown CHARACTER role '{role_id}'") from exc

    def to_dict(self) -> dict:
        profile = self.selection.profile
        return {
            "characterId": profile.character_id,
            "class": profile.character_class,
            "rank": profile.rank,
            "description": profile.description,
            "primaryRole": self.primary_role,
            "roleCount": self.role_count,
            "totalMaxSubagents": self.total_max_subagents,
            "roles": [
                self.role_assignments[role.role_id].to_dict()
                for role in profile.role_specs
            ],
        }


def build_character_orchestration_envelope(
    selection: CharacterProfileSelection,
) -> CharacterOrchestrationEnvelope:
    assignments = {
        role_spec.role_id: CharacterRoleAssignment(
            role_spec=role_spec,
            selection=selection.roles[role_spec.role_id],
        )
        for role_spec in selection.profile.role_specs
    }
    return CharacterOrchestrationEnvelope(selection=selection, role_assignments=assignments)


def load_character_profile(path: str | Path) -> CharacterProfile:
    profile_path = Path(path)
    with profile_path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    return parse_character_profile(payload, source=str(profile_path))


def select_character_profile_models(
    models: Iterable[ModelEndpoint],
    profile: CharacterProfile,
    *,
    allow_reuse: bool = True,
    readiness: ReadinessEvidenceInput | None = None,
) -> CharacterProfileSelection:
    """Select concrete model endpoints for every role in a CHARACTER profile."""

    if not isinstance(profile, CharacterProfile):
        raise RouterError("CHARACTER profile selection requires a parsed CharacterProfile")
    if readiness is not None:
        return _select_character_profile_models_with_readiness(
            list(models),
            profile,
            allow_reuse=allow_reuse,
            readiness=readiness,
        )
    composition = select_character_composition(models, profile.role_specs, allow_reuse=allow_reuse)
    return CharacterProfileSelection(profile=profile, composition=composition)


def select_character_orchestration_envelope(
    models: Iterable[ModelEndpoint],
    profile: CharacterProfile,
    *,
    allow_reuse: bool = True,
    readiness: ReadinessEvidenceInput | None = None,
) -> CharacterOrchestrationEnvelope:
    return build_character_orchestration_envelope(
        select_character_profile_models(
            models,
            profile,
            allow_reuse=allow_reuse,
            readiness=readiness,
        )
    )


def _select_character_profile_models_with_readiness(
    models: list[ModelEndpoint],
    profile: CharacterProfile,
    *,
    allow_reuse: bool,
    readiness: ReadinessEvidenceInput,
) -> CharacterProfileSelection:
    remaining_models = list(models)
    selections: dict[str, ModelScore] = {}
    role_specs = _selection_order(profile.role_specs)

    for role_spec in role_specs:
        filtered_readiness = _readiness_for_models(readiness, remaining_models)
        report = evaluate_model_decisions(remaining_models, [role_spec.task], readiness=filtered_readiness)
        selected = report.selected_for(role_spec.task.task_id)
        if selected is None:
            decision = report.situations[role_spec.task.task_id]
            blocker_summary = "; ".join(
                f"{model_id}: {', '.join(blockers)}"
                for model_id, blockers in decision.blockers.items()
            )
            raise RouterError(f"No eligible model for CHARACTER role '{role_spec.role_id}'. {blocker_summary}")
        selections[role_spec.role_id] = selected
        if not allow_reuse:
            remaining_models = [
                model for model in remaining_models if model.model_id != selected.model.model_id
            ]

    primary_role = profile.primary_role_id
    return CharacterProfileSelection(
        profile=profile,
        composition=CharacterCompositionSelection(
            roles=selections,
            role_specs={role.role_id: role for role in profile.role_specs},
            primary_role=primary_role,
        ),
    )


def _selection_order(role_specs: tuple[CharacterRoleSpec, ...]) -> tuple[CharacterRoleSpec, ...]:
    primary_specs = tuple(role for role in role_specs if role.primary)
    secondary_specs = tuple(role for role in role_specs if not role.primary)
    return primary_specs + secondary_specs if primary_specs else role_specs


def _readiness_for_models(
    readiness: ReadinessEvidenceInput,
    models: list[ModelEndpoint],
) -> ReadinessEvidenceInput:
    model_ids = {model.model_id for model in models}
    if isinstance(readiness, Mapping):
        return {model_id: evidence for model_id, evidence in readiness.items() if str(model_id) in model_ids}
    return tuple(
        evidence
        for evidence in readiness
        if _readiness_model_id(evidence) in model_ids
    )


def _readiness_model_id(evidence: Any) -> str:
    if isinstance(evidence, Mapping):
        return str(evidence.get("modelId", evidence.get("model_id", "")) or "")
    return str(getattr(evidence, "model_id", "") or "")


def parse_character_profile(payload: Mapping[str, Any], *, source: str = "<memory>") -> CharacterProfile:
    if not isinstance(payload, Mapping):
        raise CharacterProfileError(f"{source}: CHARACTER profile must be a JSON object")
    schema_version = payload.get("schemaVersion", payload.get("schema_version", 1))
    if schema_version != 1:
        raise CharacterProfileError(f"{source}: unsupported CHARACTER profile schemaVersion {schema_version!r}")

    character_id = str(payload.get("characterId", payload.get("character_id", "")) or "").strip()
    if not character_id:
        raise CharacterProfileError(f"{source}: characterId is required")

    roles_payload = payload.get("roles")
    if not isinstance(roles_payload, list) or not roles_payload:
        raise CharacterProfileError(f"{source}: roles must be a non-empty array")

    role_specs = tuple(_parse_role(raw, source=source, index=index) for index, raw in enumerate(roles_payload))
    _validate_roles(role_specs, source=source)
    return CharacterProfile(
        character_id=character_id,
        character_class=str(payload.get("class", payload.get("characterClass", payload.get("character_class", ""))) or ""),
        rank=str(payload.get("rank", "") or ""),
        description=str(payload.get("description", "") or ""),
        role_specs=role_specs,
    )


def _parse_role(raw: Mapping[str, Any], *, source: str, index: int) -> CharacterRoleSpec:
    if not isinstance(raw, Mapping):
        raise CharacterProfileError(f"{source}: roles[{index}] must be a JSON object")
    role_id = str(raw.get("roleId", raw.get("role_id", "")) or "").strip()
    if not role_id:
        raise CharacterProfileError(f"{source}: roles[{index}].roleId is required")
    task_payload = raw.get("task")
    if not isinstance(task_payload, Mapping):
        raise CharacterProfileError(f"{source}: roles[{index}].task must be a JSON object")
    task = parse_task_profile({"schemaVersion": 1, **task_payload}, source=f"{source}:roles[{index}].task")
    return CharacterRoleSpec(
        role_id=role_id,
        task=task,
        primary=bool(raw.get("primary", False)),
        max_subagents=int(raw.get("maxSubagents", raw.get("max_subagents", 0)) or 0),
    )


def _validate_roles(role_specs: tuple[CharacterRoleSpec, ...], *, source: str) -> None:
    seen: set[str] = set()
    primary_count = 0
    for role in role_specs:
        if role.role_id in seen:
            raise CharacterProfileError(f"{source}: duplicate roleId '{role.role_id}'")
        if role.max_subagents < 0:
            raise CharacterProfileError(f"{source}: role '{role.role_id}' has negative maxSubagents")
        if role.primary:
            primary_count += 1
        seen.add(role.role_id)
    if primary_count > 1:
        raise CharacterProfileError(f"{source}: only one role can be primary")


def _score_to_dict(selection: ModelScore) -> dict:
    return {
        "modelId": selection.model.model_id,
        "provider": selection.model.provider,
        "score": selection.score,
        "eligible": selection.eligible,
        "reasons": list(selection.reasons),
        "blockers": list(selection.blockers),
    }
