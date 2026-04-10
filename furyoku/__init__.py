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

__all__ = [
    "CharacterCompositionSelection",
    "CharacterPanelSelection",
    "CharacterRoleSpec",
    "ModelEndpoint",
    "ModelScore",
    "RouterError",
    "RegistryError",
    "TaskProfile",
    "default_character_role_tasks",
    "load_model_registry",
    "parse_model_registry",
    "rank_models",
    "select_character_composition",
    "select_character_panel",
    "select_model",
]
