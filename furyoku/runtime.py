from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .model_router import ModelEndpoint, ModelScore, TaskProfile, select_model
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
