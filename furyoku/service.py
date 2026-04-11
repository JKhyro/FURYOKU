from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from .model_decisions import ModelDecisionError, evaluate_model_decisions
from .model_registry import RegistryError, load_model_registry, parse_model_registry
from .model_router import (
    ModelScore,
    RouterError,
    TaskProfile,
    load_routing_score_policy,
    parse_routing_score_policy,
    select_model,
)
from .provider_adapters import ProviderAdapterError, ProviderExecutionRequest, ProviderExecutionResult
from .provider_health import ProviderHealthCheckRequest, ProviderHealthCheckResult, check_provider_health_many
from .runtime import RoutedExecutionResult, route_and_execute, route_and_execute_with_fallback
from .task_profiles import TaskProfileError, load_task_profile, parse_task_profile


SERVICE_SCHEMA_VERSION = 1

try:
    SERVICE_VERSION = package_version("furyoku")
except PackageNotFoundError:
    SERVICE_VERSION = "0.1.0"


class ServiceRequestError(ValueError):
    """Raised when a service request body is malformed or incomplete."""


@dataclass(frozen=True)
class ServiceConfig:
    """Startup configuration for the thin local FURYOKU service."""

    default_registry_path: Path | None = None
    quiet: bool = False


class FuryokuServiceServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def create_service_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    *,
    default_registry_path: str | Path | None = None,
    quiet: bool = False,
) -> FuryokuServiceServer:
    config = ServiceConfig(
        default_registry_path=_coerce_startup_path(default_registry_path),
        quiet=quiet,
    )
    return FuryokuServiceServer((host, port), _build_handler(config))


def serve(
    host: str = "127.0.0.1",
    port: int = 8765,
    *,
    default_registry_path: str | Path | None = None,
    quiet: bool = False,
) -> int:
    server = create_service_server(
        host,
        port,
        default_registry_path=default_registry_path,
        quiet=quiet,
    )
    if not quiet:
        print(
            f"FURYOKU service listening on http://{host}:{server.server_address[1]}",
            flush=True,
        )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FURYOKU thin local service/API wrapper.")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind. Defaults to 127.0.0.1.")
    parser.add_argument("--port", type=int, default=8765, help="TCP port to bind. Defaults to 8765.")
    parser.add_argument(
        "--registry",
        type=Path,
        help="Optional default model registry JSON file used when requests omit registry/registryPath.",
    )
    parser.add_argument("--quiet", action="store_true", help="Suppress request logs and startup banner.")
    args = parser.parse_args(argv)
    return serve(
        args.host,
        args.port,
        default_registry_path=args.registry,
        quiet=args.quiet,
    )


def build_service_status(config: ServiceConfig) -> dict[str, Any]:
    return {
        "schemaVersion": SERVICE_SCHEMA_VERSION,
        "ok": True,
        "service": "furyoku-service",
        "version": SERVICE_VERSION,
        "defaultRegistryPath": str(config.default_registry_path) if config.default_registry_path else None,
        "endpoints": {
            "serviceHealth": {"method": "GET", "path": "/health"},
            "providerHealth": {"method": "POST", "path": "/v1/health"},
            "select": {"method": "POST", "path": "/v1/select"},
            "run": {"method": "POST", "path": "/v1/run"},
        },
    }


def handle_service_health(payload: Mapping[str, Any], *, config: ServiceConfig) -> dict[str, Any]:
    models = _resolve_models(payload, config=config)
    request = ProviderHealthCheckRequest(
        probe=_bool_value(payload.get("probe"), field_name="probe", default=False),
        probe_prompt=_string_value(payload.get("probePrompt"), field_name="probePrompt", default=""),
        timeout_seconds=_optional_positive_float(
            payload.get("timeoutSeconds"),
            field_name="timeoutSeconds",
            default=5.0,
        ),
        metadata=_mapping_value(payload.get("metadata"), field_name="metadata", default={}),
    )
    results = check_provider_health_many(models, request)
    return {
        "schemaVersion": SERVICE_SCHEMA_VERSION,
        "ok": all(result.ready for result in results),
        "providers": [_health_result_to_dict(result) for result in results],
    }


def handle_service_select(payload: Mapping[str, Any], *, config: ServiceConfig) -> dict[str, Any]:
    models = _resolve_models(payload, config=config)
    task = _resolve_task(payload)
    readiness = _resolve_readiness(payload, models)
    routing_policy = _resolve_routing_policy(payload)

    report = None
    if readiness is None and routing_policy is None:
        selection = select_model(models, task)
    else:
        report = evaluate_model_decisions(
            models,
            [task],
            readiness=readiness,
            routing_policy=routing_policy,
        )
        selection = report.selected_for(task.task_id)
        if selection is None:
            raise RouterError(f"No eligible model for task '{task.task_id}'")

    response: dict[str, Any] = {
        "schemaVersion": SERVICE_SCHEMA_VERSION,
        "ok": selection.eligible,
        "selection": _score_to_dict(selection),
        "taskProfile": task.to_dict(),
    }
    if readiness is not None:
        response["readiness"] = [_health_result_to_dict(result) for result in readiness]
    if report is not None:
        response["decisionReport"] = report.to_dict()
    return response


def handle_service_run(payload: Mapping[str, Any], *, config: ServiceConfig) -> dict[str, Any]:
    models = _resolve_models(payload, config=config)
    task = _resolve_task(payload)
    prompt = _required_string(payload.get("prompt"), field_name="prompt")
    timeout_seconds = _optional_positive_float(
        payload.get("timeoutSeconds"),
        field_name="timeoutSeconds",
        default=60.0,
    )
    metadata = _mapping_value(payload.get("metadata"), field_name="metadata", default={})
    fallback = _bool_value(payload.get("fallback"), field_name="fallback", default=False)
    max_attempts = _optional_positive_int(payload.get("maxAttempts"), field_name="maxAttempts")
    if max_attempts is not None and not fallback:
        raise ServiceRequestError("maxAttempts requires fallback=true")

    readiness = _resolve_readiness(payload, models)
    routing_policy = _resolve_routing_policy(payload)
    request = ProviderExecutionRequest(
        prompt,
        timeout_seconds=timeout_seconds,
        metadata=metadata,
    )
    runner = route_and_execute_with_fallback if fallback else route_and_execute
    result = runner(
        models,
        task,
        request,
        readiness=readiness,
        routing_policy=routing_policy,
        **({"max_attempts": max_attempts} if fallback else {}),
    )
    return _routed_result_to_dict(result, readiness=readiness)


def _build_handler(config: ServiceConfig) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path
            if path != "/health":
                self._write_json(
                    HTTPStatus.NOT_FOUND,
                    _error_payload("not_found", f"unknown path '{path}'"),
                )
                return
            self._write_json(HTTPStatus.OK, build_service_status(config))

        def do_POST(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path
            try:
                payload = self._read_json_body()
                if path == "/v1/health":
                    response = handle_service_health(payload, config=config)
                elif path == "/v1/select":
                    response = handle_service_select(payload, config=config)
                elif path == "/v1/run":
                    response = handle_service_run(payload, config=config)
                else:
                    self._write_json(
                        HTTPStatus.NOT_FOUND,
                        _error_payload("not_found", f"unknown path '{path}'"),
                    )
                    return
            except (ServiceRequestError, RegistryError, TaskProfileError, ModelDecisionError) as exc:
                self._write_json(HTTPStatus.BAD_REQUEST, _error_payload(exc.__class__.__name__, str(exc)))
                return
            except (RouterError, ProviderAdapterError) as exc:
                self._write_json(HTTPStatus.UNPROCESSABLE_ENTITY, _error_payload(exc.__class__.__name__, str(exc)))
                return
            except Exception as exc:  # noqa: BLE001
                self._write_json(HTTPStatus.INTERNAL_SERVER_ERROR, _error_payload(exc.__class__.__name__, str(exc)))
                return

            self._write_json(HTTPStatus.OK, response)

        def log_message(self, format: str, *args: object) -> None:
            if config.quiet:
                return
            super().log_message(format, *args)

        def _read_json_body(self) -> Mapping[str, Any]:
            raw_length = self.headers.get("Content-Length", "0")
            try:
                content_length = int(raw_length or "0")
            except ValueError as exc:
                raise ServiceRequestError("Content-Length must be an integer") from exc
            raw_body = self.rfile.read(content_length) if content_length > 0 else b"{}"
            try:
                payload = json.loads(raw_body.decode("utf-8") or "{}")
            except json.JSONDecodeError as exc:
                raise ServiceRequestError(f"request body must be valid JSON: {exc.msg}") from exc
            if not isinstance(payload, Mapping):
                raise ServiceRequestError("request body must be a JSON object")
            return payload

        def _write_json(self, status: HTTPStatus, payload: Mapping[str, Any]) -> None:
            encoded = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
            self.send_response(status.value)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    return Handler


def _resolve_models(payload: Mapping[str, Any], *, config: ServiceConfig):
    registry = payload.get("registry")
    registry_path = payload.get("registryPath")
    if registry not in (None, "") and registry_path not in (None, ""):
        raise ServiceRequestError("provide only one of registry or registryPath")
    if registry not in (None, ""):
        if not isinstance(registry, Mapping):
            raise ServiceRequestError("registry must be a JSON object")
        return parse_model_registry(registry, source="request.registry")
    if registry_path not in (None, ""):
        return load_model_registry(_request_path(registry_path, field_name="registryPath"))
    if config.default_registry_path is not None:
        return load_model_registry(config.default_registry_path)
    raise ServiceRequestError(
        "registry or registryPath is required unless the service was started with --registry"
    )


def _resolve_task(payload: Mapping[str, Any]) -> TaskProfile:
    task = payload.get("task")
    task_path = payload.get("taskPath")
    if task not in (None, "") and task_path not in (None, ""):
        raise ServiceRequestError("provide only one of task or taskPath")
    if task not in (None, ""):
        if not isinstance(task, Mapping):
            raise ServiceRequestError("task must be a JSON object")
        return parse_task_profile(task, source="request.task")
    if task_path not in (None, ""):
        return load_task_profile(_request_path(task_path, field_name="taskPath"))
    raise ServiceRequestError("task or taskPath is required")


def _resolve_routing_policy(payload: Mapping[str, Any]):
    routing_policy = payload.get("routingPolicy")
    routing_policy_path = payload.get("routingPolicyPath")
    if routing_policy not in (None, "") and routing_policy_path not in (None, ""):
        raise ServiceRequestError("provide only one of routingPolicy or routingPolicyPath")
    if routing_policy not in (None, ""):
        if not isinstance(routing_policy, Mapping):
            raise ServiceRequestError("routingPolicy must be a JSON object")
        return parse_routing_score_policy(routing_policy, source="request.routingPolicy")
    if routing_policy_path not in (None, ""):
        return load_routing_score_policy(_request_path(routing_policy_path, field_name="routingPolicyPath"))
    return None


def _resolve_readiness(payload: Mapping[str, Any], models) -> list[ProviderHealthCheckResult] | None:
    if not _bool_value(payload.get("checkHealth"), field_name="checkHealth", default=False):
        return None
    request = ProviderHealthCheckRequest(
        probe=_bool_value(payload.get("healthProbe"), field_name="healthProbe", default=False),
        probe_prompt=_string_value(
            payload.get("healthProbePrompt"),
            field_name="healthProbePrompt",
            default="",
        ),
        timeout_seconds=_optional_positive_float(
            payload.get("healthTimeoutSeconds"),
            field_name="healthTimeoutSeconds",
            default=5.0,
        ),
        metadata=_mapping_value(payload.get("healthMetadata"), field_name="healthMetadata", default={}),
    )
    return check_provider_health_many(models, request)


def _score_to_dict(selection: ModelScore) -> dict[str, Any]:
    payload = {
        "modelId": selection.model.model_id,
        "provider": selection.model.provider,
        "score": selection.score,
        "eligible": selection.eligible,
        "averageLatencyMs": selection.model.average_latency_ms,
        "reasons": list(selection.reasons),
        "blockers": list(selection.blockers),
    }
    total_cost_per_1k = selection.model.input_cost_per_1k + selection.model.output_cost_per_1k
    if selection.model.input_cost_per_1k > 0.0:
        payload["inputCostPer1k"] = selection.model.input_cost_per_1k
    if selection.model.output_cost_per_1k > 0.0:
        payload["outputCostPer1k"] = selection.model.output_cost_per_1k
    if total_cost_per_1k > 0.0:
        payload["totalCostPer1k"] = round(total_cost_per_1k, 6)
    return payload


def _execution_to_dict(execution: ProviderExecutionResult) -> dict[str, Any]:
    return {
        "modelId": execution.model_id,
        "provider": execution.provider,
        "status": execution.status,
        "responseText": execution.response_text,
        "elapsedMs": execution.elapsed_ms,
        "exitCode": execution.exit_code,
        "stderr": execution.stderr,
        "error": execution.error,
        "timedOut": execution.timed_out,
    }


def _execution_attempt_to_dict(attempt) -> dict[str, Any]:
    return {
        "attemptNumber": attempt.attempt_number,
        "selectedModel": _score_to_dict(attempt.selection),
        "execution": _execution_to_dict(attempt.execution),
    }


def _routed_result_to_dict(
    result: RoutedExecutionResult,
    *,
    readiness: list[ProviderHealthCheckResult] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schemaVersion": SERVICE_SCHEMA_VERSION,
        "ok": result.ok,
        "selection": _score_to_dict(result.selection),
        "taskProfile": result.selection.task.to_dict(),
        "execution": _execution_to_dict(result.execution),
    }
    if result.execution_attempts:
        payload["fallback"] = {
            "enabled": True,
            "attemptCount": len(result.execution_attempts),
            "succeeded": any(attempt.ok for attempt in result.execution_attempts),
        }
        payload["executionAttempts"] = [
            _execution_attempt_to_dict(attempt)
            for attempt in result.execution_attempts
        ]
    if result.report is not None:
        payload["decisionReport"] = result.report.to_dict()
    if readiness is not None:
        payload["readiness"] = [_health_result_to_dict(result) for result in readiness]
    return payload


def _health_result_to_dict(result: ProviderHealthCheckResult) -> dict[str, Any]:
    payload = {
        "modelId": result.model_id,
        "provider": result.provider,
        "status": result.status,
        "ready": result.ready,
        "reason": result.reason,
        "command": result.command,
        "resolvedCommand": result.resolved_command,
    }
    if result.execution is not None:
        payload["execution"] = _execution_to_dict(result.execution)
    return payload


def _error_payload(error_type: str, message: str) -> dict[str, Any]:
    return {
        "schemaVersion": SERVICE_SCHEMA_VERSION,
        "ok": False,
        "error": {
            "type": error_type,
            "message": message,
        },
    }


def _bool_value(value: Any, *, field_name: str, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    raise ServiceRequestError(f"{field_name} must be a boolean")


def _string_value(value: Any, *, field_name: str, default: str) -> str:
    if value is None:
        return default
    if isinstance(value, str):
        return value
    raise ServiceRequestError(f"{field_name} must be a string")


def _required_string(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ServiceRequestError(f"{field_name} is required and must be a non-empty string")
    return value


def _mapping_value(value: Any, *, field_name: str, default: Mapping[str, Any]) -> Mapping[str, Any]:
    if value is None:
        return default
    if isinstance(value, Mapping):
        return value
    raise ServiceRequestError(f"{field_name} must be a JSON object")


def _optional_positive_float(value: Any, *, field_name: str, default: float | None) -> float | None:
    if value is None:
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ServiceRequestError(f"{field_name} must be a number") from exc
    if parsed <= 0:
        raise ServiceRequestError(f"{field_name} must be greater than 0")
    return parsed


def _optional_positive_int(value: Any, *, field_name: str) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ServiceRequestError(f"{field_name} must be an integer") from exc
    if parsed < 1:
        raise ServiceRequestError(f"{field_name} must be at least 1")
    return parsed


def _coerce_startup_path(path_value: str | Path | None) -> Path | None:
    if path_value in (None, ""):
        return None
    return Path(path_value).expanduser().resolve()


def _request_path(value: Any, *, field_name: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ServiceRequestError(f"{field_name} must be a non-empty string path")
    return Path(value).expanduser()


if __name__ == "__main__":
    raise SystemExit(main())
