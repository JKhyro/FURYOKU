from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping

from .model_router import ModelEndpoint
from .provider_adapters import (
    ApiTransport,
    ProviderAdapter,
    ProviderExecutionRequest,
    ProviderExecutionResult,
    default_provider_adapters,
    execute_model,
)


CommandResolver = Callable[[str], str | None]


@dataclass(frozen=True)
class ProviderHealthCheckRequest:
    """Controls how deeply a provider endpoint is checked."""

    probe: bool = False
    probe_prompt: str = ""
    timeout_seconds: float | None = 5.0
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderHealthCheckResult:
    """Readiness result for one registered provider endpoint."""

    model_id: str
    provider: str
    status: str
    ready: bool
    reason: str = ""
    command: str | None = None
    resolved_command: str | None = None
    execution: ProviderExecutionResult | None = None


def check_provider_health(
    endpoint: ModelEndpoint,
    request: ProviderHealthCheckRequest | None = None,
    *,
    command_resolver: CommandResolver | None = None,
    api_transport: ApiTransport | None = None,
    adapters: Mapping[str, ProviderAdapter] | None = None,
) -> ProviderHealthCheckResult:
    resolved_request = request or ProviderHealthCheckRequest()
    if endpoint.provider in ("local", "cli"):
        return _check_subprocess_provider(
            endpoint,
            resolved_request,
            command_resolver=command_resolver or shutil.which,
            adapters=adapters,
        )
    if endpoint.provider == "api":
        return _check_api_provider(
            endpoint,
            resolved_request,
            api_transport=api_transport,
            adapters=adapters,
        )
    return ProviderHealthCheckResult(
        model_id=endpoint.model_id,
        provider=endpoint.provider,
        status="unsupported-provider",
        ready=False,
        reason=f"provider '{endpoint.provider}' is not supported by health checks",
    )


def check_provider_health_many(
    endpoints: Iterable[ModelEndpoint],
    request: ProviderHealthCheckRequest | None = None,
    *,
    command_resolver: CommandResolver | None = None,
    api_transport: ApiTransport | None = None,
    adapters: Mapping[str, ProviderAdapter] | None = None,
) -> list[ProviderHealthCheckResult]:
    return [
        check_provider_health(
            endpoint,
            request,
            command_resolver=command_resolver,
            api_transport=api_transport,
            adapters=adapters,
        )
        for endpoint in endpoints
    ]


def _check_subprocess_provider(
    endpoint: ModelEndpoint,
    request: ProviderHealthCheckRequest,
    *,
    command_resolver: CommandResolver,
    adapters: Mapping[str, ProviderAdapter] | None,
) -> ProviderHealthCheckResult:
    if not endpoint.invocation:
        return ProviderHealthCheckResult(
            model_id=endpoint.model_id,
            provider=endpoint.provider,
            status="missing-invocation",
            ready=False,
            reason="local/CLI providers require an invocation command",
        )

    command = endpoint.invocation[0]
    resolved_command = command_resolver(command)
    if not resolved_command:
        return ProviderHealthCheckResult(
            model_id=endpoint.model_id,
            provider=endpoint.provider,
            status="missing-command",
            ready=False,
            command=command,
            reason=f"command '{command}' was not found",
        )

    if not request.probe:
        return ProviderHealthCheckResult(
            model_id=endpoint.model_id,
            provider=endpoint.provider,
            status="ready",
            ready=True,
            command=command,
            resolved_command=resolved_command,
            reason="command is available",
        )

    execution = execute_model(
        endpoint,
        ProviderExecutionRequest(
            request.probe_prompt,
            timeout_seconds=request.timeout_seconds,
            metadata=request.metadata,
        ),
        adapters=adapters,
    )
    return _result_from_execution(endpoint, execution, command=command, resolved_command=resolved_command)


def _check_api_provider(
    endpoint: ModelEndpoint,
    request: ProviderHealthCheckRequest,
    *,
    api_transport: ApiTransport | None,
    adapters: Mapping[str, ProviderAdapter] | None,
) -> ProviderHealthCheckResult:
    if api_transport is None and (adapters is None or "api" not in adapters):
        return ProviderHealthCheckResult(
            model_id=endpoint.model_id,
            provider=endpoint.provider,
            status="missing-transport",
            ready=False,
            reason="api health checks require an injected API transport or adapter",
        )

    if not request.probe:
        return ProviderHealthCheckResult(
            model_id=endpoint.model_id,
            provider=endpoint.provider,
            status="ready",
            ready=True,
            reason="api transport is configured",
        )

    execution = execute_model(
        endpoint,
        ProviderExecutionRequest(
            request.probe_prompt,
            timeout_seconds=request.timeout_seconds,
            metadata=request.metadata,
        ),
        adapters=adapters or default_provider_adapters(api_transport=api_transport),
    )
    return _result_from_execution(endpoint, execution)


def _result_from_execution(
    endpoint: ModelEndpoint,
    execution: ProviderExecutionResult,
    *,
    command: str | None = None,
    resolved_command: str | None = None,
) -> ProviderHealthCheckResult:
    if execution.ok:
        return ProviderHealthCheckResult(
            model_id=endpoint.model_id,
            provider=endpoint.provider,
            status="ready",
            ready=True,
            command=command,
            resolved_command=resolved_command,
            reason="probe execution succeeded",
            execution=execution,
        )
    if execution.timed_out:
        status = "timeout"
        reason = execution.error or "probe execution timed out"
    else:
        status = "probe-failed"
        reason = execution.error or execution.stderr or "probe execution failed"
    return ProviderHealthCheckResult(
        model_id=endpoint.model_id,
        provider=endpoint.provider,
        status=status,
        ready=False,
        command=command,
        resolved_command=resolved_command,
        reason=reason,
        execution=execution,
    )
