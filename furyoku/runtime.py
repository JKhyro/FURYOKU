from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .character_profiles import CharacterProfile, CharacterProfileSelection, select_character_profile_models
from .model_router import ModelEndpoint, ModelScore, RouterError, TaskProfile, select_model
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


def route_and_execute(
    models: list[ModelEndpoint],
    task: TaskProfile,
    request: ProviderExecutionRequest | str,
    *,
    adapters: Mapping[str, ProviderAdapter] | None = None,
) -> RoutedExecutionResult:
    """Select the best eligible model for a task, then execute it."""

    selection = select_model(models, task)
    execution = execute_selected_model(selection, request, adapters=adapters)
    return RoutedExecutionResult(selection=selection, execution=execution)


def execute_character_role(
    models: list[ModelEndpoint],
    profile: CharacterProfile,
    request: ProviderExecutionRequest | str,
    *,
    role_id: str | None = None,
    allow_reuse: bool = True,
    adapters: Mapping[str, ProviderAdapter] | None = None,
) -> CharacterRoleExecutionResult:
    """Select all CHARACTER role assignments, then execute one role."""

    character_selection = select_character_profile_models(models, profile, allow_reuse=allow_reuse)
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
