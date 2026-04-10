from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol

from .model_router import ModelEndpoint, ModelScore


class ProviderAdapterError(ValueError):
    """Raised when FURYOKU cannot resolve an execution adapter for a model."""


@dataclass(frozen=True)
class ProviderExecutionRequest:
    """Input passed to a selected model endpoint."""

    prompt: str
    timeout_seconds: float | None = 60.0
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderExecutionResult:
    """Observed result of one model endpoint execution."""

    model_id: str
    provider: str
    status: str
    response_text: str = ""
    elapsed_ms: int = 0
    exit_code: int | None = None
    stderr: str = ""
    error: str = ""
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.status == "ok" and not self.timed_out


class ProviderAdapter(Protocol):
    def execute(
        self,
        endpoint: ModelEndpoint,
        request: ProviderExecutionRequest,
    ) -> ProviderExecutionResult:
        """Execute one endpoint and return an observable result."""


SubprocessRunner = Callable[
    [tuple[str, ...], str, float | None],
    subprocess.CompletedProcess[str],
]
ApiTransport = Callable[[ModelEndpoint, ProviderExecutionRequest], Mapping[str, Any] | str | ProviderExecutionResult]


class SubprocessProviderAdapter:
    """Adapter for local and CLI providers backed by command execution."""

    def __init__(self, runner: SubprocessRunner | None = None) -> None:
        self._runner = runner or _run_subprocess

    def execute(
        self,
        endpoint: ModelEndpoint,
        request: ProviderExecutionRequest,
    ) -> ProviderExecutionResult:
        if not endpoint.invocation:
            return _error_result(endpoint, "subprocess-backed endpoints require invocation")

        started = time.perf_counter()
        try:
            completed = self._runner(endpoint.invocation, request.prompt, request.timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            return ProviderExecutionResult(
                model_id=endpoint.model_id,
                provider=endpoint.provider,
                status="timeout",
                response_text=_coerce_text(exc.stdout),
                elapsed_ms=_elapsed_ms(started),
                stderr=_coerce_text(exc.stderr),
                error=f"execution timed out after {exc.timeout} seconds",
                timed_out=True,
            )
        except OSError as exc:
            return _error_result(endpoint, str(exc), elapsed_ms=_elapsed_ms(started))

        status = "ok" if completed.returncode == 0 else "error"
        return ProviderExecutionResult(
            model_id=endpoint.model_id,
            provider=endpoint.provider,
            status=status,
            response_text=completed.stdout or "",
            elapsed_ms=_elapsed_ms(started),
            exit_code=completed.returncode,
            stderr=completed.stderr or "",
            error="" if completed.returncode == 0 else f"provider exited with code {completed.returncode}",
        )


class ApiProviderAdapter:
    """Adapter for remote/API providers with an injected transport seam."""

    def __init__(self, transport: ApiTransport | None = None) -> None:
        self._transport = transport

    def execute(
        self,
        endpoint: ModelEndpoint,
        request: ProviderExecutionRequest,
    ) -> ProviderExecutionResult:
        if self._transport is None:
            return _error_result(endpoint, "api transport is required for API provider execution")

        started = time.perf_counter()
        try:
            payload = self._transport(endpoint, request)
        except TimeoutError as exc:
            return ProviderExecutionResult(
                model_id=endpoint.model_id,
                provider=endpoint.provider,
                status="timeout",
                elapsed_ms=_elapsed_ms(started),
                error=str(exc) or "api execution timed out",
                timed_out=True,
            )
        except Exception as exc:  # noqa: BLE001 - transports must report observable failure to callers.
            return _error_result(endpoint, str(exc), elapsed_ms=_elapsed_ms(started))

        if isinstance(payload, ProviderExecutionResult):
            return payload
        if isinstance(payload, str):
            return ProviderExecutionResult(
                model_id=endpoint.model_id,
                provider=endpoint.provider,
                status="ok",
                response_text=payload,
                elapsed_ms=_elapsed_ms(started),
            )
        return ProviderExecutionResult(
            model_id=endpoint.model_id,
            provider=endpoint.provider,
            status=str(payload.get("status", "ok")),
            response_text=str(payload.get("response_text", payload.get("text", "")) or ""),
            elapsed_ms=int(payload.get("elapsed_ms", _elapsed_ms(started)) or 0),
            exit_code=_optional_int(payload.get("exit_code")),
            stderr=str(payload.get("stderr", "") or ""),
            error=str(payload.get("error", "") or ""),
            timed_out=bool(payload.get("timed_out", False)),
        )


def default_provider_adapters(
    *,
    subprocess_runner: SubprocessRunner | None = None,
    api_transport: ApiTransport | None = None,
) -> dict[str, ProviderAdapter]:
    subprocess_adapter = SubprocessProviderAdapter(subprocess_runner)
    return {
        "local": subprocess_adapter,
        "cli": subprocess_adapter,
        "api": ApiProviderAdapter(api_transport),
    }


def execute_model(
    endpoint: ModelEndpoint,
    request: ProviderExecutionRequest | str,
    *,
    adapters: Mapping[str, ProviderAdapter] | None = None,
) -> ProviderExecutionResult:
    resolved_request = request if isinstance(request, ProviderExecutionRequest) else ProviderExecutionRequest(request)
    resolved_adapters = adapters or default_provider_adapters()
    adapter = resolved_adapters.get(endpoint.provider)
    if adapter is None:
        raise ProviderAdapterError(f"Unsupported provider '{endpoint.provider}' for model '{endpoint.model_id}'")
    return adapter.execute(endpoint, resolved_request)


def execute_selected_model(
    selection: ModelScore,
    request: ProviderExecutionRequest | str,
    *,
    adapters: Mapping[str, ProviderAdapter] | None = None,
) -> ProviderExecutionResult:
    return execute_model(selection.model, request, adapters=adapters)


def _run_subprocess(
    invocation: tuple[str, ...],
    prompt: str,
    timeout_seconds: float | None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(invocation),
        input=prompt,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
    )


def _error_result(endpoint: ModelEndpoint, error: str, *, elapsed_ms: int = 0) -> ProviderExecutionResult:
    return ProviderExecutionResult(
        model_id=endpoint.model_id,
        provider=endpoint.provider,
        status="error",
        elapsed_ms=elapsed_ms,
        error=error,
    )


def _coerce_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _elapsed_ms(started: float) -> int:
    return max(0, int(round((time.perf_counter() - started) * 1000)))


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)
