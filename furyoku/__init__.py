"""FURYOKU multi-model routing primitives."""

from .model_router import (
    CharacterPanelSelection,
    ModelEndpoint,
    ModelScore,
    RouterError,
    TaskProfile,
    default_character_role_tasks,
    rank_models,
    select_character_panel,
    select_model,
)

__all__ = [
    "CharacterPanelSelection",
    "ModelEndpoint",
    "ModelScore",
    "RouterError",
    "TaskProfile",
    "default_character_role_tasks",
    "rank_models",
    "select_character_panel",
    "select_model",
]
