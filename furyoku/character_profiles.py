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


def load_character_profile(path: str | Path) -> CharacterProfile:
    profile_path = Path(path)
    with profile_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return parse_character_profile(payload, source=str(profile_path))


def select_character_profile_models(
    models: Iterable[ModelEndpoint],
    profile: CharacterProfile,
    *,
    allow_reuse: bool = True,
) -> CharacterProfileSelection:
    """Select concrete model endpoints for every role in a CHARACTER profile."""

    if not isinstance(profile, CharacterProfile):
        raise RouterError("CHARACTER profile selection requires a parsed CharacterProfile")
    composition = select_character_composition(models, profile.role_specs, allow_reuse=allow_reuse)
    return CharacterProfileSelection(profile=profile, composition=composition)


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
