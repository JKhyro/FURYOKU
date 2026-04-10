from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .model_router import ModelEndpoint


class RegistryError(ValueError):
    """Raised when a model registry file is malformed."""


def load_model_registry(path: str | Path) -> list[ModelEndpoint]:
    registry_path = Path(path)
    with registry_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return parse_model_registry(payload, source=str(registry_path))


def parse_model_registry(payload: Mapping[str, Any], *, source: str = "<memory>") -> list[ModelEndpoint]:
    if not isinstance(payload, Mapping):
        raise RegistryError(f"{source}: registry must be a JSON object")
    schema_version = payload.get("schemaVersion", payload.get("schema_version", 1))
    if schema_version != 1:
        raise RegistryError(f"{source}: unsupported registry schemaVersion {schema_version!r}")

    raw_models = payload.get("models", payload.get("endpoints"))
    if not isinstance(raw_models, list) or not raw_models:
        raise RegistryError(f"{source}: registry must contain a non-empty models array")

    models = [_parse_model_endpoint(raw, source=source, index=index) for index, raw in enumerate(raw_models)]
    model_ids = [model.model_id for model in models]
    duplicates = sorted({model_id for model_id in model_ids if model_ids.count(model_id) > 1})
    if duplicates:
        raise RegistryError(f"{source}: duplicate model ids: {', '.join(duplicates)}")
    return models


def _parse_model_endpoint(raw: Mapping[str, Any], *, source: str, index: int) -> ModelEndpoint:
    if not isinstance(raw, Mapping):
        raise RegistryError(f"{source}: models[{index}] must be a JSON object")

    model_id = _required_str(raw, "modelId", "model_id", source=source, index=index)
    provider = _required_str(raw, "provider", source=source, index=index)
    capabilities = raw.get("capabilities")
    if not isinstance(capabilities, Mapping) or not capabilities:
        raise RegistryError(f"{source}: models[{index}] must define non-empty capabilities")

    context_window_tokens = _required_int(raw, "contextWindowTokens", "context_window_tokens", source=source, index=index)
    average_latency_ms = _required_int(raw, "averageLatencyMs", "average_latency_ms", source=source, index=index)
    invocation = raw.get("invocation", [])
    if invocation is None:
        invocation = []
    if not isinstance(invocation, list):
        raise RegistryError(f"{source}: models[{index}].invocation must be an array when provided")

    return ModelEndpoint(
        model_id=model_id,
        provider=provider,
        capabilities={str(key): float(value) for key, value in capabilities.items()},
        context_window_tokens=context_window_tokens,
        average_latency_ms=average_latency_ms,
        input_cost_per_1k=float(raw.get("inputCostPer1k", raw.get("input_cost_per_1k", 0.0)) or 0.0),
        output_cost_per_1k=float(raw.get("outputCostPer1k", raw.get("output_cost_per_1k", 0.0)) or 0.0),
        available=bool(raw.get("available", True)),
        privacy_level=str(raw.get("privacyLevel", raw.get("privacy_level", "remote"))),
        invocation=tuple(str(item) for item in invocation),
        supports_tools=bool(raw.get("supportsTools", raw.get("supports_tools", False))),
        supports_json=bool(raw.get("supportsJson", raw.get("supports_json", False))),
        tags=tuple(str(item) for item in raw.get("tags", ())),
    )


def _required_str(raw: Mapping[str, Any], *keys: str, source: str, index: int) -> str:
    for key in keys:
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise RegistryError(f"{source}: models[{index}] missing required field {keys[0]}")


def _required_int(raw: Mapping[str, Any], *keys: str, source: str, index: int) -> int:
    for key in keys:
        value = raw.get(key)
        if value not in (None, ""):
            try:
                integer_value = int(value)
            except (TypeError, ValueError) as exc:
                raise RegistryError(f"{source}: models[{index}].{key} must be an integer") from exc
            if integer_value < 0:
                raise RegistryError(f"{source}: models[{index}].{key} must be non-negative")
            return integer_value
    raise RegistryError(f"{source}: models[{index}] missing required field {keys[0]}")
