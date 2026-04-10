from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .model_router import TaskProfile


class TaskProfileError(ValueError):
    """Raised when a task profile file is malformed."""


def load_task_profile(path: str | Path) -> TaskProfile:
    profile_path = Path(path)
    with profile_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return parse_task_profile(payload, source=str(profile_path))


def parse_task_profile(payload: Mapping[str, Any], *, source: str = "<memory>") -> TaskProfile:
    if not isinstance(payload, Mapping):
        raise TaskProfileError(f"{source}: task profile must be a JSON object")
    schema_version = payload.get("schemaVersion", payload.get("schema_version", 1))
    if schema_version != 1:
        raise TaskProfileError(f"{source}: unsupported task profile schemaVersion {schema_version!r}")

    task_id = str(payload.get("taskId", payload.get("task_id", "")) or "").strip()
    if not task_id:
        raise TaskProfileError(f"{source}: taskId is required")

    raw_capabilities = payload.get("requiredCapabilities", payload.get("required_capabilities"))
    if not isinstance(raw_capabilities, Mapping) or not raw_capabilities:
        raise TaskProfileError(f"{source}: requiredCapabilities must be a non-empty object")

    return TaskProfile(
        task_id=task_id,
        description=str(payload.get("description", "") or ""),
        required_capabilities={str(key): float(value) for key, value in raw_capabilities.items()},
        min_context_tokens=int(payload.get("minContextTokens", payload.get("min_context_tokens", 0)) or 0),
        privacy_requirement=str(payload.get("privacyRequirement", payload.get("privacy_requirement", "allow_remote"))),
        max_input_cost_per_1k=_optional_float(payload.get("maxInputCostPer1k", payload.get("max_input_cost_per_1k"))),
        max_output_cost_per_1k=_optional_float(payload.get("maxOutputCostPer1k", payload.get("max_output_cost_per_1k"))),
        require_tools=bool(payload.get("requireTools", payload.get("require_tools", False))),
        require_json=bool(payload.get("requireJson", payload.get("require_json", False))),
        preferred_providers=tuple(str(item) for item in payload.get("preferredProviders", payload.get("preferred_providers", ()))),
    )


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)
