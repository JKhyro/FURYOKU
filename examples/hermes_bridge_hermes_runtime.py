#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from typing import Any, Mapping


HERMES_PROVIDERS = {
    "auto",
    "openrouter",
    "nous",
    "openai-codex",
    "copilot-acp",
    "copilot",
    "anthropic",
    "huggingface",
    "zai",
    "kimi-coding",
    "minimax",
    "minimax-cn",
    "kilocode",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run one FURYOKU bridge payload through the Hermes Agent CLI.",
    )
    parser.add_argument(
        "--hermes-command",
        default=os.getenv("FURYOKU_HERMES_COMMAND", "hermes"),
        help="Hermes executable command. Defaults to FURYOKU_HERMES_COMMAND or hermes.",
    )
    parser.add_argument(
        "--hermes-command-json",
        default=os.getenv("FURYOKU_HERMES_COMMAND_JSON", ""),
        help="JSON array form of the Hermes command, used when paths need exact tokenization.",
    )
    parser.add_argument(
        "--provider",
        default=os.getenv("FURYOKU_HERMES_PROVIDER", ""),
        help="Optional Hermes provider override. Defaults to FURYOKU_HERMES_PROVIDER.",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("FURYOKU_HERMES_MODEL", ""),
        help="Optional Hermes model override. Defaults to FURYOKU_HERMES_MODEL.",
    )
    parser.add_argument(
        "--toolsets",
        default=os.getenv("FURYOKU_HERMES_TOOLSETS", ""),
        help="Optional Hermes toolset list. Defaults to FURYOKU_HERMES_TOOLSETS.",
    )
    parser.add_argument(
        "--skills",
        action="append",
        default=None,
        help="Optional Hermes skill preload. May be repeated.",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=_positive_int_env("FURYOKU_HERMES_MAX_TURNS", 1),
        help="Maximum Hermes tool-calling turns for this one task.",
    )
    parser.add_argument(
        "--source",
        default=os.getenv("FURYOKU_HERMES_SOURCE", "furyoku-bridge"),
        help="Hermes session source tag.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=_positive_float_env("FURYOKU_HERMES_TIMEOUT_SECONDS", 120.0),
        help="Timeout for the Hermes subprocess.",
    )
    parser.add_argument(
        "--cwd",
        default=os.getenv("FURYOKU_HERMES_CWD", ""),
        help="Optional working directory for Hermes.",
    )
    args = parser.parse_args(argv)

    started = time.perf_counter()
    try:
        payload = json.load(sys.stdin)
        envelope = _mapping(payload.get("envelope"), "payload.envelope")
        task = _mapping(envelope.get("task"), "payload.envelope.task")
        selected = _mapping(payload.get("selectedModel"), "payload.selectedModel", required=False)
        command = _build_hermes_command(args, envelope, selected)
    except Exception as exc:
        _emit(
            _result_payload(
                started,
                status="error",
                error={
                    "recoverable": True,
                    "code": "invalid_bridge_payload",
                    "message": str(exc),
                },
            )
        )
        return 2

    try:
        completed = subprocess.run(
            command,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=args.timeout_seconds,
            cwd=args.cwd or None,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        _emit(
            _result_payload(
                started,
                payload=payload,
                command=command,
                status="timeout",
                stdout=_coerce_text(exc.stdout),
                stderr=_coerce_text(exc.stderr),
                timed_out=True,
                error={
                    "recoverable": True,
                    "code": "hermes_timeout",
                    "message": f"Hermes command timed out after {exc.timeout} seconds",
                },
            )
        )
        return 124
    except OSError as exc:
        _emit(
            _result_payload(
                started,
                payload=payload,
                command=command,
                status="error",
                error={
                    "recoverable": True,
                    "code": "hermes_launch_failed",
                    "message": str(exc),
                },
            )
        )
        return 127

    ok = completed.returncode == 0
    _emit(
        _result_payload(
            started,
            payload=payload,
            command=command,
            status="ok" if ok else "error",
            exit_code=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            error=None
            if ok
            else {
                "recoverable": True,
                "code": "hermes_execution_failed",
                "message": f"Hermes command exited with code {completed.returncode}",
            },
        )
    )
    return completed.returncode


def _build_hermes_command(args: argparse.Namespace, envelope: Mapping[str, Any], selected: Mapping[str, Any]) -> list[str]:
    prompt = _required_string(envelope, "prompt")
    selected_model = _optional_string(selected, "modelId")
    selected_provider = _optional_string(selected, "provider")
    provider = (args.provider or "").strip()
    model = (args.model or selected_model or "").strip()

    command = _command_tokens(args)
    command.extend(["chat", "--query", prompt, "--quiet", "--max-turns", str(args.max_turns), "--source", args.source])
    if model:
        command.extend(["--model", model])
    if provider:
        if provider not in HERMES_PROVIDERS:
            raise ValueError(f"unsupported Hermes provider override {provider!r}")
        command.extend(["--provider", provider])
    elif selected_provider in HERMES_PROVIDERS:
        command.extend(["--provider", selected_provider])
    if args.toolsets:
        command.extend(["--toolsets", args.toolsets])
    for skill in args.skills or []:
        command.extend(["--skills", skill])
    return command


def _command_tokens(args: argparse.Namespace) -> list[str]:
    if args.hermes_command_json:
        value = json.loads(args.hermes_command_json)
        if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
            raise ValueError("--hermes-command-json must be a non-empty JSON string array")
        return list(value)
    return shlex.split(args.hermes_command, posix=(os.name != "nt"))


def _result_payload(
    started: float,
    *,
    payload: Mapping[str, Any] | None = None,
    command: list[str] | None = None,
    status: str,
    exit_code: int | None = None,
    stdout: str = "",
    stderr: str = "",
    timed_out: bool = False,
    error: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    envelope = _mapping(payload.get("envelope"), "payload.envelope", required=False) if payload else {}
    task = _mapping(envelope.get("task"), "payload.envelope.task", required=False) if envelope else {}
    selected = _mapping(payload.get("selectedModel"), "payload.selectedModel", required=False) if payload else {}
    return {
        "schemaVersion": 1,
        "adapter": "hermes-bridge-hermes-runtime",
        "runtime": "hermes-agent",
        "status": status,
        "executionKey": _optional_string(envelope, "executionKey"),
        "symbioteId": _optional_string(envelope, "symbioteId"),
        "role": _optional_string(envelope, "role"),
        "taskId": _optional_string(task, "taskId"),
        "selectedModelId": _optional_string(selected, "modelId"),
        "selectedProvider": _optional_string(selected, "provider"),
        "hermesCommand": list(command or []),
        "elapsedMs": round((time.perf_counter() - started) * 1000.0, 3),
        "exitCode": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "timedOut": timed_out,
        "responseText": stdout.strip() if status == "ok" else "",
        "error": dict(error) if error is not None else None,
    }


def _mapping(value: Any, label: str, *, required: bool = True) -> Mapping[str, Any]:
    if value is None and not required:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _required_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _optional_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    return value if isinstance(value, str) else ""


def _coerce_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _positive_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _positive_float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _emit(payload: Mapping[str, Any]) -> None:
    json.dump(payload, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    raise SystemExit(main())
