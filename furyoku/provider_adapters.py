from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
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
            return _execute_configured_api_endpoint(endpoint, request)

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


def _execute_configured_api_endpoint(
    endpoint: ModelEndpoint,
    request: ProviderExecutionRequest,
) -> ProviderExecutionResult:
    api_url = _metadata_string(endpoint, "apiUrl", "api_url", "url")
    if not api_url:
        return _error_result(endpoint, "api transport requires metadata.apiUrl or an injected transport")

    api_key_env = _metadata_string(endpoint, "apiKeyEnv", "api_key_env")
    api_key = os.environ.get(api_key_env) if api_key_env else None
    if api_key_env and not api_key:
        return _error_result(endpoint, f"api key environment variable '{api_key_env}' is not set")

    started = time.perf_counter()
    try:
        body = _api_request_body(endpoint, request)
    except ProviderAdapterError as exc:
        return _error_result(endpoint, str(exc), elapsed_ms=_elapsed_ms(started))
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    http_request = urllib.request.Request(
        api_url,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(http_request, timeout=request.timeout_seconds) as response:
            raw_text = response.read().decode("utf-8", errors="replace")
            status_code = getattr(response, "status", 200)
    except urllib.error.HTTPError as exc:
        error_text = exc.read().decode("utf-8", errors="replace")
        return ProviderExecutionResult(
            model_id=endpoint.model_id,
            provider=endpoint.provider,
            status="error",
            response_text=error_text,
            elapsed_ms=_elapsed_ms(started),
            exit_code=exc.code,
            error=f"api request failed with HTTP {exc.code}",
        )
    except TimeoutError as exc:
        return ProviderExecutionResult(
            model_id=endpoint.model_id,
            provider=endpoint.provider,
            status="timeout",
            elapsed_ms=_elapsed_ms(started),
            error=str(exc) or "api execution timed out",
            timed_out=True,
        )
    except OSError as exc:
        return _error_result(endpoint, str(exc), elapsed_ms=_elapsed_ms(started))

    try:
        payload = json.loads(raw_text) if raw_text else {}
    except json.JSONDecodeError:
        payload = {"text": raw_text}

    response_text = _extract_api_response_text(payload)
    return ProviderExecutionResult(
        model_id=endpoint.model_id,
        provider=endpoint.provider,
        status="ok" if 200 <= int(status_code) < 300 else "error",
        response_text=response_text,
        elapsed_ms=_elapsed_ms(started),
        exit_code=int(status_code),
        error="" if 200 <= int(status_code) < 300 else f"api request returned HTTP {status_code}",
    )


def _api_request_body(endpoint: ModelEndpoint, request: ProviderExecutionRequest) -> dict[str, Any]:
    api_format = (_metadata_string(endpoint, "apiFormat", "api_format", "format") or "openai-chat").lower()
    model_name = _metadata_string(endpoint, "apiModel", "api_model", "model") or endpoint.model_id
    if api_format in ("generic-json", "prompt-json"):
        return {
            "model": model_name,
            "prompt": request.prompt,
            **dict(request.metadata),
        }
    if api_format != "openai-chat":
        raise ProviderAdapterError(f"Unsupported api format '{api_format}' for model '{endpoint.model_id}'")
    return {
        "model": model_name,
        "messages": [{"role": "user", "content": request.prompt}],
        **dict(request.metadata),
    }


def _extract_api_response_text(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    if not isinstance(payload, Mapping):
        return str(payload)
    for key in ("response_text", "responseText", "output_text", "outputText", "text"):
        value = payload.get(key)
        if value not in (None, ""):
            return str(value)
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first_choice = choices[0]
        if isinstance(first_choice, Mapping):
            message = first_choice.get("message")
            if isinstance(message, Mapping) and message.get("content") not in (None, ""):
                return str(message["content"])
            if first_choice.get("text") not in (None, ""):
                return str(first_choice["text"])
    output = payload.get("output")
    if isinstance(output, list):
        for item in output:
            if isinstance(item, Mapping) and item.get("text") not in (None, ""):
                return str(item["text"])
    return json.dumps(payload, sort_keys=True)


def _metadata_string(endpoint: ModelEndpoint, *keys: str) -> str:
    for key in keys:
        value = endpoint.metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


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
