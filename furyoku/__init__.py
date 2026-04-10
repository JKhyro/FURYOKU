"""FURYOKU multi-model routing primitives."""

from .model_router import (
    CharacterCompositionSelection,
    CharacterPanelSelection,
    CharacterRoleSpec,
    ModelEndpoint,
    ModelScore,
    RouterError,
    TaskProfile,
    default_character_role_tasks,
    rank_models,
    select_character_composition,
    select_character_panel,
    select_model,
)
from .model_registry import RegistryError, load_model_registry, parse_model_registry
from .provider_adapters import (
    ApiProviderAdapter,
    ProviderAdapterError,
    ProviderExecutionRequest,
    ProviderExecutionResult,
    SubprocessProviderAdapter,
    default_provider_adapters,
    execute_model,
    execute_selected_model,
)
from .runtime import RoutedExecutionResult, route_and_execute

__all__ = [
    "ApiProviderAdapter",
    "CharacterCompositionSelection",
    "CharacterPanelSelection",
    "CharacterRoleSpec",
    "ModelEndpoint",
    "ModelScore",
    "ProviderAdapterError",
    "ProviderExecutionRequest",
    "ProviderExecutionResult",
    "RouterError",
    "RegistryError",
    "RoutedExecutionResult",
    "SubprocessProviderAdapter",
    "TaskProfile",
    "default_character_role_tasks",
    "default_provider_adapters",
    "execute_model",
    "execute_selected_model",
    "load_model_registry",
    "parse_model_registry",
    "rank_models",
    "route_and_execute",
    "select_character_composition",
    "select_character_panel",
    "select_model",
]
