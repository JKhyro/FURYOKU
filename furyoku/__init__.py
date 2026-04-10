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
from .character_profiles import (
    CharacterProfile,
    CharacterProfileError,
    CharacterProfileSelection,
    load_character_profile,
    parse_character_profile,
    select_character_profile_models,
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
from .provider_health import (
    ProviderHealthCheckRequest,
    ProviderHealthCheckResult,
    check_provider_health,
    check_provider_health_many,
)
from .runtime import RoutedExecutionResult, route_and_execute
from .task_profiles import TaskProfileError, load_task_profile, parse_task_profile

__all__ = [
    "ApiProviderAdapter",
    "CharacterCompositionSelection",
    "CharacterPanelSelection",
    "CharacterProfile",
    "CharacterProfileError",
    "CharacterProfileSelection",
    "CharacterRoleSpec",
    "ModelEndpoint",
    "ModelScore",
    "ProviderAdapterError",
    "ProviderExecutionRequest",
    "ProviderExecutionResult",
    "ProviderHealthCheckRequest",
    "ProviderHealthCheckResult",
    "RouterError",
    "RegistryError",
    "RoutedExecutionResult",
    "SubprocessProviderAdapter",
    "TaskProfile",
    "TaskProfileError",
    "default_character_role_tasks",
    "default_provider_adapters",
    "execute_model",
    "execute_selected_model",
    "check_provider_health",
    "check_provider_health_many",
    "load_model_registry",
    "load_character_profile",
    "load_task_profile",
    "parse_model_registry",
    "parse_character_profile",
    "parse_task_profile",
    "rank_models",
    "route_and_execute",
    "select_character_composition",
    "select_character_profile_models",
    "select_character_panel",
    "select_model",
]
